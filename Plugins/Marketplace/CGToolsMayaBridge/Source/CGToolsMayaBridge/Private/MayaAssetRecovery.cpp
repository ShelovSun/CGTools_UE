#include "MayaAssetRecovery.h"

#include "Animation/Skeleton.h"
#include "Dom/JsonObject.h"
#include "Interfaces/IPluginManager.h"
#include "IPythonScriptPlugin.h"
#include "Misc/Base64.h"
#include "Misc/MessageDialog.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/SoftObjectPath.h"

namespace
{
FMayaAssetRecoveryResult RunAssetOperation(const FMayaPublishedAction& Action,
    const FString& SkeletonPath, const FString& Operation)
{
    FMayaAssetRecoveryResult Result;
    IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
    if (!Python || !Python->IsPythonInitialized())
    {
        Result.Message = TEXT("UE Python 尚未初始化，无法执行【加载资产】或【Import FBX】。");
        return Result;
    }
    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("CGToolsMayaBridge"));
    if (!Plugin)
    {
        Result.Message = TEXT("找不到 CGToolsMayaBridge 插件目录。");
        return Result;
    }
    // Use the plugin's own shim even when the asset manager has not been opened.
    const FString PythonDirectory = FBase64::Encode(Plugin->GetContentDir() / TEXT("Python"));
    FPythonCommandEx AddPath;
    AddPath.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
    AddPath.Flags = EPythonCommandFlags::Unattended;
    AddPath.Command = FString::Printf(
        TEXT("import sys, base64; p=base64.b64decode('%s').decode('utf-8'); p not in sys.path and sys.path.insert(0,p)"),
        *PythonDirectory);
    if (!Python->ExecPythonCommandEx(AddPath))
    {
        Result.Message = TEXT("无法初始化资产恢复服务：") + AddPath.CommandResult;
        return Result;
    }
    const TSharedRef<FJsonObject> Request = MakeShared<FJsonObject>();
    Request->SetStringField(TEXT("project_name"), Action.ProjectName);
    Request->SetStringField(TEXT("asset_type"), Action.AssetType);
    Request->SetStringField(TEXT("asset_name"), Action.AssetName);
    Request->SetStringField(TEXT("skeleton_path"), SkeletonPath);
    FString Json;
    FJsonSerializer::Serialize(Request, TJsonWriterFactory<>::Create(&Json));
    FPythonCommandEx Command;
    Command.ExecutionMode = EPythonCommandExecutionMode::EvaluateStatement;
    Command.Flags = EPythonCommandFlags::Unattended;
    Command.Command = FString::Printf(TEXT("__import__('cgtools_maya_bridge_assets').invoke('%s','%s')"),
        *Operation, *FBase64::Encode(Json));
    if (!Python->ExecPythonCommandEx(Command))
    {
        Result.Message = TEXT("资产恢复服务执行失败：") + Command.CommandResult;
        return Result;
    }
    FString Encoded = Command.CommandResult;
    if (Encoded.Len() >= 2 && ((Encoded[0] == TEXT('\'') && Encoded[Encoded.Len() - 1] == TEXT('\''))
        || (Encoded[0] == TEXT('"') && Encoded[Encoded.Len() - 1] == TEXT('"'))))
    {
        Encoded = Encoded.Mid(1, Encoded.Len() - 2);
    }
    TSharedPtr<FJsonObject> Response;
    if (!FBase64::Decode(Encoded, Json)
        || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Response) || !Response)
    {
        Result.Message = TEXT("资产恢复服务返回了无效结果。");
        return Result;
    }
    Response->TryGetStringField(TEXT("status"), Result.Status);
    Response->TryGetStringField(TEXT("message"), Result.Message);
    Response->TryGetStringField(TEXT("asset_root"), Result.AssetRoot);
    return Result;
}
}

bool FMayaAssetRecovery::EnsureSkeleton(const FMayaPublishedAction& Action,
    const FString& SkeletonPath, FString& OutError)
{
    FMayaAssetRecoveryOperations Operations;
    Operations.HasSkeleton = [&SkeletonPath]() { return Cast<USkeleton>(FSoftObjectPath(SkeletonPath).TryLoad()) != nullptr; };
    Operations.Ask = [](const FString& Title, const FString& Message)
    {
        return FMessageDialog::Open(EAppMsgType::YesNo, FText::FromString(Message), FText::FromString(Title)) == EAppReturnType::Yes;
    };
    Operations.Run = [&Action, &SkeletonPath](const FString& Operation)
    {
        return RunAssetOperation(Action, SkeletonPath, Operation);
    };
    return Recover(Action.AssetName, SkeletonPath, Operations, OutError);
}

bool FMayaAssetRecovery::Recover(const FString& AssetName, const FString& SkeletonPath,
    const FMayaAssetRecoveryOperations& Operations, FString& OutError)
{
    OutError.Reset();
    if (Operations.HasSkeleton())
    {
        return true;
    }
    const FMayaAssetRecoveryResult Description = Operations.Run(TEXT("describe"));
    if (Description.Status != TEXT("ready"))
    {
        OutError = Description.Message;
        return false;
    }
    const FString AskLoad = FString::Printf(
        TEXT("当前 UE 工程中没有找到资产“%s”的骨架。\n\n是否先加载资产，再继续导入动作？\n\n资产目录：%s\n骨架路径：%s"),
        *AssetName, *Description.AssetRoot, *SkeletonPath);
    if (!Operations.Ask(TEXT("缺少骨架：是否加载资产？"), AskLoad))
    {
        OutError = TEXT("用户取消加载资产，本资产的动作已跳过。");
        return false;
    }
    const FMayaAssetRecoveryResult Loaded = Operations.Run(TEXT("load"));
    if (Loaded.Status == TEXT("ready") && Operations.HasSkeleton())
    {
        return true;
    }
    const FString Reason = Loaded.Status == TEXT("missing_ue")
        ? TEXT("该资产还没有可加载的 UE 文件。")
        : TEXT("加载资产失败：") + (Loaded.Message.IsEmpty() ? TEXT("仍未找到指定骨架。") : Loaded.Message);
    if (!Operations.Ask(TEXT("加载资产失败：是否导入 FBX？"), FString::Printf(
        TEXT("%s\n\n资产：%s\n资产目录：%s\n\n是否执行【Import FBX】导入该资产，然后继续导入动作？"),
        *Reason, *AssetName, *Description.AssetRoot)))
    {
        OutError = Reason + TEXT("\n用户取消 Import FBX，本资产的动作已跳过。");
        return false;
    }
    const FMayaAssetRecoveryResult Imported = Operations.Run(TEXT("import_fbx"));
    if (Imported.Status != TEXT("ready") || !Operations.HasSkeleton())
    {
        OutError = TEXT("Import FBX 后仍无法导入动作：")
            + (Imported.Message.IsEmpty() ? SkeletonPath : Imported.Message);
        return false;
    }
    return true;
}

#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMayaAssetRecoveryFlowTest, "CGTools.MayaBridge.AssetRecovery.Decisions",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FMayaAssetRecoveryFlowTest::RunTest(const FString& Parameters)
{
    for (const FString Scenario : { TEXT("existing"), TEXT("load"), TEXT("fbx"), TEXT("decline_load"),
        TEXT("decline_fbx"), TEXT("load_error"), TEXT("fbx_error"), TEXT("false_success") })
    {
        TArray<FString> Calls;
        TArray<FString> Questions;
        bool bSkeleton = Scenario == TEXT("existing");
        FMayaAssetRecoveryOperations Operations;
        Operations.HasSkeleton = [&]() { return bSkeleton; };
        Operations.Ask = [&](const FString& Title, const FString& Message)
        {
            Questions.Add(Message);
            return Scenario != (Questions.Num() == 1 ? TEXT("decline_load") : TEXT("decline_fbx"));
        };
        Operations.Run = [&](const FString& Operation)
        {
            Calls.Add(Operation);
            FMayaAssetRecoveryResult Result;
            Result.AssetRoot = TEXT("Y:/MCCProject/GOF/Assets/Props/Yu015QiePian");
            Result.Status = TEXT("ready");
            if (Operation == TEXT("load"))
            {
                if (Scenario == TEXT("load")) { bSkeleton = true; }
                else if (Scenario == TEXT("load_error")) { Result.Status = TEXT("error"); Result.Message = TEXT("磁盘写入失败"); }
                else if (Scenario != TEXT("false_success")) { Result.Status = TEXT("missing_ue"); }
            }
            if (Operation == TEXT("import_fbx"))
            {
                if (Scenario == TEXT("fbx_error")) { Result.Status = TEXT("error"); Result.Message = TEXT("找不到资产 FBX"); }
                else if (Scenario != TEXT("false_success")) { bSkeleton = true; }
            }
            return Result;
        };
        FString Error;
        const bool bSuccess = FMayaAssetRecovery::Recover(TEXT("Yu015QiePian"), TEXT("/Game/Assets/Props/Yu015QiePian/Yu015QiePian_Skeleton"), Operations, Error);
        const bool bExpected = Scenario == TEXT("existing") || Scenario == TEXT("load") || Scenario == TEXT("fbx") || Scenario == TEXT("load_error");
        TestEqual(*Scenario, bSuccess, bExpected);
        if (Scenario == TEXT("existing")) { TestTrue(TEXT("Existing skeleton does not prompt or copy"), Calls.IsEmpty() && Questions.IsEmpty()); }
        if (Scenario == TEXT("load")) { TestFalse(TEXT("Successful load does not import asset FBX"), Calls.Contains(TEXT("import_fbx"))); }
        if (Scenario == TEXT("decline_load")) { TestEqual(TEXT("Declining load performs no import"), Calls.Num(), 1); }
        if (Scenario == TEXT("decline_fbx")) { TestFalse(TEXT("Declining FBX performs no FBX import"), Calls.Contains(TEXT("import_fbx"))); }
        if (Scenario == TEXT("fbx")) { TestTrue(TEXT("Missing release is explicitly explained"), Questions.Last().Contains(TEXT("还没有可加载的 UE 文件"))); }
        if (Scenario == TEXT("load_error")) { TestTrue(TEXT("I/O failure is not mislabeled as no UE files"), Questions.Last().Contains(TEXT("磁盘写入失败")) && !Questions.Last().Contains(TEXT("还没有可加载的 UE 文件"))); }
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMayaAssetRecoveryPythonProtocolTest, "CGTools.MayaBridge.AssetRecovery.PythonProtocol",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FMayaAssetRecoveryPythonProtocolTest::RunTest(const FString& Parameters)
{
    // Invalid context is rejected before reading the server configuration. This
    // exercises the real plugin shim and Unicode JSON round trip without I/O.
    FMayaPublishedAction Action;
    Action.ProjectName = TEXT("GOF");
    Action.AssetType = TEXT("Props");
    Action.AssetName = TEXT("../测试资产");
    const FMayaAssetRecoveryResult Result = RunAssetOperation(Action, FString(), TEXT("describe"));
    TestEqual(TEXT("Python service rejects an invalid asset context"), Result.Status, FString(TEXT("error")));
    TestTrue(TEXT("Unicode service error survives the C++/Python Base64 round trip"),
        Result.Message.Contains(TEXT("项目、类型或资产名无效")));
    return true;
}
#endif
