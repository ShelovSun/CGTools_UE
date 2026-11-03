#include "CGToolsPublisherMayaBridge.h"

#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
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
bool InvokeMaya(const TSharedRef<FJsonObject>& Request, FString& OutMessage)
{
    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("CGToolsPublisher"));
    const FString Adapter = Plugin.IsValid()
        ? Plugin->GetContentDir() / TEXT("Python/cgtools_publisher_maya.py") : FString();
    if (Adapter.IsEmpty() || !IFileManager::Get().FileExists(*Adapter))
    {
        OutMessage = TEXT("无法找到 CGToolsPublisher 的 Maya 桥接脚本，请更新完整插件。");
        return false;
    }
    IPythonScriptPlugin& Python = FModuleManager::LoadModuleChecked<IPythonScriptPlugin>(TEXT("PythonScriptPlugin"));
    if (!Python.IsPythonInitialized())
    {
        Python.ForceEnablePythonAtRuntime();
    }
    if (!Python.IsPythonInitialized())
    {
        OutMessage = TEXT("UE Python 尚未初始化，无法执行 Maya 处理。");
        return false;
    }
    FPythonCommandEx Command;
    Command.ExecutionMode = EPythonCommandExecutionMode::EvaluateStatement;
    FString RequestJson;
    FJsonSerializer::Serialize(Request, TJsonWriterFactory<>::Create(&RequestJson));
    // Keep interactive progress and safe cancellation enabled for ADV baking.
    Command.Command = FString::Printf(
        TEXT("__import__('runpy').run_path(__import__('base64').b64decode('%s').decode('utf-8'), "
            "run_name='cgtools_publisher_maya_runtime')['invoke']('%s')"),
        *FBase64::Encode(Adapter), *FBase64::Encode(RequestJson));
    if (!Python.ExecPythonCommandEx(Command))
    {
        OutMessage = TEXT("Maya 桥接执行失败：") + Command.CommandResult;
        return false;
    }
    FString Encoded = Command.CommandResult.TrimStartAndEnd();
    if (Encoded.Len() >= 2 && ((Encoded[0] == TEXT('\'') && Encoded[Encoded.Len() - 1] == TEXT('\''))
        || (Encoded[0] == TEXT('"') && Encoded[Encoded.Len() - 1] == TEXT('"'))))
    {
        Encoded = Encoded.Mid(1, Encoded.Len() - 2);
    }
    FString Json;
    TSharedPtr<FJsonObject> Response;
    if (!FBase64::Decode(Encoded, Json)
        || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Response) || !Response.IsValid())
    {
        OutMessage = TEXT("Maya 桥接未返回有效结果，请查看 Output Log。");
        return false;
    }
    bool bOk = false;
    Response->TryGetBoolField(TEXT("ok"), bOk);
    Response->TryGetStringField(TEXT("message"), OutMessage);
    if (OutMessage.IsEmpty())
    {
        OutMessage = TEXT("Maya 桥接没有返回处理详情，请查看 Output Log。");
    }
    return bOk;
}
}

bool CGToolsPublisher::BakeAnimationToMaya(const FString& ObjectPath, const FString& OutputMa, FString& OutMessage)
{
    const TSharedRef<FJsonObject> Request = MakeShared<FJsonObject>();
    Request->SetStringField(TEXT("operation"), TEXT("bake"));
    Request->SetStringField(TEXT("object_path"), ObjectPath);
    Request->SetStringField(TEXT("output_ma"), OutputMa);
    return InvokeMaya(Request, OutMessage);
}

bool CGToolsPublisher::OpenPublishedMayaScene(const FString& SceneMa, FString& OutMessage)
{
    const TSharedRef<FJsonObject> Request = MakeShared<FJsonObject>();
    Request->SetStringField(TEXT("operation"), TEXT("open_scene"));
    Request->SetStringField(TEXT("scene_ma"), SceneMa);
    return InvokeMaya(Request, OutMessage);
}
