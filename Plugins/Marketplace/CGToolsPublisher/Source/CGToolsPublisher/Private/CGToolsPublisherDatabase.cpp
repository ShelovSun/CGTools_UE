#include "CGToolsPublisherDatabase.h"

#include "Dom/JsonObject.h"
#include "Interfaces/IPluginManager.h"
#include "IPythonScriptPlugin.h"
#include "Misc/Base64.h"
#include "Modules/ModuleManager.h"
#include "PythonScriptTypes.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
    FString SerializeJson(const TSharedRef<FJsonObject>& Object)
    {
        FString Json;
        const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
        FJsonSerializer::Serialize(Object, Writer);
        return Json;
    }

    FString EscapePythonString(FString Value)
    {
        Value.ReplaceInline(TEXT("\\"), TEXT("\\\\"));
        Value.ReplaceInline(TEXT("'"), TEXT("\\'"));
        return Value;
    }
}

FCGToolsDatabaseResult FCGToolsPublisherDatabase::CheckSceneRecord(
    const FString& Project,
    const FString& AssetName,
    const FString& Host
)
{
    const TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("project"), Project);
    Payload->SetStringField(TEXT("asset_name"), AssetName);
    Payload->SetStringField(TEXT("host"), Host);
    return Invoke(TEXT("check_scene_record"), Payload);
}

FCGToolsDatabaseResult FCGToolsPublisherDatabase::CheckAssetRecord(
    const FString& Project,
    const FString& AssetName,
    const FString& Host
)
{
    const TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("project"), Project);
    Payload->SetStringField(TEXT("asset_name"), AssetName);
    Payload->SetStringField(TEXT("host"), Host);
    return Invoke(TEXT("check_asset_record"), Payload);
}

FCGToolsDatabaseResult FCGToolsPublisherDatabase::WriteSceneRecord(
    const FString& Project,
    const FString& AssetName,
    const FString& ChineseName,
    const FString& AssetType,
    const FString& IconPath,
    const FString& Host,
    bool bOverwrite
)
{
    const TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("project"), Project);
    Payload->SetStringField(TEXT("asset_name"), AssetName);
    Payload->SetStringField(TEXT("chinese_name"), ChineseName);
    Payload->SetStringField(TEXT("asset_type"), AssetType);
    Payload->SetStringField(TEXT("icon_path"), IconPath);
    Payload->SetStringField(TEXT("host"), Host);
    Payload->SetBoolField(TEXT("overwrite"), bOverwrite);
    return Invoke(TEXT("write_scene_record"), Payload);
}

FCGToolsDatabaseResult FCGToolsPublisherDatabase::WriteAssetRecord(
    const FString& Project,
    const FString& AssetName,
    const FString& ChineseName,
    const FString& AssetType,
    const FString& IconPath,
    const FString& Host,
    bool bOverwrite
)
{
    const TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("project"), Project);
    Payload->SetStringField(TEXT("asset_name"), AssetName);
    Payload->SetStringField(TEXT("chinese_name"), ChineseName);
    Payload->SetStringField(TEXT("asset_type"), AssetType);
    Payload->SetStringField(TEXT("icon_path"), IconPath);
    Payload->SetStringField(TEXT("host"), Host);
    Payload->SetBoolField(TEXT("overwrite"), bOverwrite);
    return Invoke(TEXT("write_asset_record"), Payload);
}

FCGToolsDatabaseResult FCGToolsPublisherDatabase::Invoke(
    const FString& Operation,
    const TSharedRef<FJsonObject>& Payload
)
{
    FCGToolsDatabaseResult Result;

    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("CGToolsPublisher"));
    if (!Plugin.IsValid())
    {
        Result.Error = TEXT("无法定位 CGToolsPublisher 插件目录。");
        return Result;
    }

    IPythonScriptPlugin& Python =
        FModuleManager::LoadModuleChecked<IPythonScriptPlugin>(TEXT("PythonScriptPlugin"));
    if (!Python.IsPythonInitialized())
    {
        Python.ForceEnablePythonAtRuntime();
    }
    if (!Python.IsPythonInitialized())
    {
        Result.Error = TEXT("UE Python 尚未初始化；请确认 PythonScriptPlugin 已启用并重启编辑器。");
        return Result;
    }

    const FString PythonDirectory = Plugin->GetContentDir() / TEXT("Python");
    FPythonCommandEx AddPathCommand;
    AddPathCommand.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
    AddPathCommand.Flags = EPythonCommandFlags::Unattended;
    AddPathCommand.Command = FString::Printf(
        TEXT("import sys; p='%s'; p not in sys.path and sys.path.insert(0, p)"),
        *EscapePythonString(PythonDirectory)
    );
    if (!Python.ExecPythonCommandEx(AddPathCommand))
    {
        Result.Error = FString::Printf(
            TEXT("无法加载数据库桥接目录：%s"),
            *AddPathCommand.CommandResult
        );
        return Result;
    }

    const FString RequestJson = SerializeJson(Payload);
    const FString RequestBase64 = FBase64::Encode(RequestJson);

    FPythonCommandEx Command;
    Command.ExecutionMode = EPythonCommandExecutionMode::EvaluateStatement;
    Command.Flags = EPythonCommandFlags::Unattended;
    Command.Command = FString::Printf(
        TEXT("__import__('cgtools_publisher_db').invoke('%s','%s')"),
        *EscapePythonString(Operation),
        *EscapePythonString(RequestBase64)
    );

    if (!Python.ExecPythonCommandEx(Command))
    {
        Result.Error = FString::Printf(
            TEXT("数据库桥接执行失败：%s"),
            *Command.CommandResult
        );
        return Result;
    }

    FString ResponseBase64 = Command.CommandResult;
    if (ResponseBase64.Len() >= 2)
    {
        const TCHAR First = ResponseBase64[0];
        const TCHAR Last = ResponseBase64[ResponseBase64.Len() - 1];
        if ((First == TEXT('\'') && Last == TEXT('\'')) || (First == TEXT('"') && Last == TEXT('"')))
        {
            ResponseBase64 = ResponseBase64.Mid(1, ResponseBase64.Len() - 2);
        }
    }

    FString ResponseJson;
    if (!FBase64::Decode(ResponseBase64, ResponseJson))
    {
        Result.Error = FString::Printf(
            TEXT("数据库桥接返回值不是有效的 Base64：%s"),
            *Command.CommandResult
        );
        return Result;
    }

    TSharedPtr<FJsonObject> Response;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ResponseJson);
    if (!FJsonSerializer::Deserialize(Reader, Response) || !Response.IsValid())
    {
        Result.Error = FString::Printf(
            TEXT("数据库桥接返回了无法解析的结果：%s"),
            *ResponseJson
        );
        return Result;
    }

    Response->TryGetBoolField(TEXT("ok"), Result.bOk);
    Response->TryGetBoolField(TEXT("exists"), Result.bExists);
    Response->TryGetStringField(TEXT("error"), Result.Error);
    if (!Result.bOk && Result.Error.IsEmpty())
    {
        Result.Error = TEXT("数据库操作失败，但没有返回详细错误。");
    }
    return Result;
}
