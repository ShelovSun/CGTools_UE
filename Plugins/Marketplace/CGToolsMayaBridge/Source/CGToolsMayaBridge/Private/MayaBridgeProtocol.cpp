// Copyright CGTools. All Rights Reserved.

#include "MayaBridgeProtocol.h"

#include "Containers/StringConv.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
constexpr TCHAR ProtocolName[] = TEXT("cgtools-ue-bridge");
constexpr int32 ProtocolVersion = 1;
constexpr TCHAR PublishedMessageType[] = TEXT("action_published");

bool RequireString(
    const TSharedPtr<FJsonObject>& Object,
    const TCHAR* FieldName,
    FString& OutValue,
    FString& OutError)
{
    if (!Object->TryGetStringField(FieldName, OutValue) || OutValue.IsEmpty())
    {
        OutError = FString::Printf(TEXT("missing or empty string field: %s"), FieldName);
        return false;
    }
    return true;
}
}

bool FMayaBridgeProtocol::ParseMessage(
    const TArray<uint8>& JsonBytes,
    FMayaBridgeMessage& OutMessage,
    FString& OutError)
{
    OutMessage = FMayaBridgeMessage();
    OutError.Reset();

    if (JsonBytes.IsEmpty() || JsonBytes.Num() > static_cast<int32>(MaxJsonBodyBytes))
    {
        OutError = TEXT("JSON body length is outside the supported range");
        return false;
    }

    const FUTF8ToTCHAR Converted(
        reinterpret_cast<const ANSICHAR*>(JsonBytes.GetData()),
        JsonBytes.Num());
    const FString JsonText(Converted.Length(), Converted.Get());

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutError = TEXT("body is not valid UTF-8 JSON object");
        return false;
    }

    Root->TryGetStringField(TEXT("event_id"), OutMessage.EventId);

    FString Protocol;
    if (!RequireString(Root, TEXT("protocol"), Protocol, OutError) || Protocol != ProtocolName)
    {
        if (OutError.IsEmpty())
        {
            OutError = TEXT("unsupported protocol");
        }
        return false;
    }

    double Version = 0.0;
    if (!Root->TryGetNumberField(TEXT("protocol_version"), Version)
        || Version != static_cast<double>(ProtocolVersion))
    {
        OutError = TEXT("unsupported protocol_version");
        return false;
    }

    FString MessageType;
    if (!RequireString(Root, TEXT("message_type"), MessageType, OutError)
        || MessageType != PublishedMessageType)
    {
        if (OutError.IsEmpty())
        {
            OutError = TEXT("unsupported message_type");
        }
        return false;
    }

    if (OutMessage.EventId.IsEmpty())
    {
        OutError = TEXT("missing or empty string field: event_id");
        return false;
    }
    Root->TryGetStringField(TEXT("sent_at_utc"), OutMessage.SentAtUtc);

    const TArray<TSharedPtr<FJsonValue>>* ProjectValues = nullptr;
    if (!Root->TryGetArrayField(TEXT("project_names"), ProjectValues)
        || ProjectValues == nullptr
        || ProjectValues->IsEmpty())
    {
        OutError = TEXT("project_names must be a non-empty string array");
        return false;
    }

    for (const TSharedPtr<FJsonValue>& ProjectValue : *ProjectValues)
    {
        FString ProjectName;
        if (!ProjectValue.IsValid()
            || ProjectValue->Type != EJson::String
            || !ProjectValue->TryGetString(ProjectName)
            || ProjectName.IsEmpty())
        {
            OutError = TEXT("project_names must be a non-empty string array");
            return false;
        }
        OutMessage.ProjectNames.Add(MoveTemp(ProjectName));
    }

    double ActionCount = -1.0;
    const TArray<TSharedPtr<FJsonValue>>* ActionValues = nullptr;
    if (!Root->TryGetNumberField(TEXT("action_count"), ActionCount)
        || !Root->TryGetArrayField(TEXT("actions"), ActionValues)
        || ActionValues == nullptr
        || ActionValues->IsEmpty()
        || ActionCount != static_cast<double>(ActionValues->Num()))
    {
        OutError = TEXT("action_count must match a non-empty actions array");
        return false;
    }

    for (const TSharedPtr<FJsonValue>& ActionValue : *ActionValues)
    {
        if (!ActionValue.IsValid() || ActionValue->Type != EJson::Object)
        {
            OutError = TEXT("every actions item must be an object");
            return false;
        }

        const TSharedPtr<FJsonObject> ActionObject = ActionValue->AsObject();
        FMayaPublishedAction Action;
        ActionObject->TryGetStringField(TEXT("project_name"), Action.ProjectName);

        if (!RequireString(ActionObject, TEXT("asset_type"), Action.AssetType, OutError)
            || (Action.AssetType != TEXT("Characters") && Action.AssetType != TEXT("Props")))
        {
            if (OutError.IsEmpty())
            {
                OutError = TEXT("asset_type must be Characters or Props");
            }
            return false;
        }
        if (!RequireString(ActionObject, TEXT("asset_name"), Action.AssetName, OutError)
            || !RequireString(ActionObject, TEXT("action_name"), Action.ActionName, OutError)
            || !RequireString(ActionObject, TEXT("fbx_path"), Action.FbxPath, OutError))
        {
            return false;
        }

        double Number = 0.0;
        if (ActionObject->TryGetNumberField(TEXT("fbx_size_bytes"), Number))
        {
            Action.FbxSizeBytes = static_cast<int64>(Number);
        }
        ActionObject->TryGetStringField(TEXT("maya_file_path"), Action.MayaFilePath);
        ActionObject->TryGetStringField(TEXT("reference_node"), Action.ReferenceNode);
        ActionObject->TryGetStringField(TEXT("reference_path"), Action.ReferencePath);
        ActionObject->TryGetStringField(TEXT("namespace"), Action.Namespace);
        ActionObject->TryGetNumberField(TEXT("start_frame"), Action.StartFrame);
        ActionObject->TryGetNumberField(TEXT("end_frame"), Action.EndFrame);

        OutMessage.Actions.Add(MoveTemp(Action));
    }

    return true;
}

TArray<uint8> FMayaBridgeProtocol::MakeAckFrame(
    const FString& EventId,
    const bool bAccepted,
    const FString& Message)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("protocol"), ProtocolName);
    Root->SetNumberField(TEXT("protocol_version"), ProtocolVersion);
    Root->SetStringField(TEXT("message_type"), TEXT("ack"));
    Root->SetStringField(TEXT("reply_to_event_id"), EventId);
    Root->SetBoolField(TEXT("accepted"), bAccepted);
    Root->SetStringField(TEXT("message"), Message);

    FString JsonText;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&JsonText);
    FJsonSerializer::Serialize(Root, Writer);

    const FTCHARToUTF8 Utf8(*JsonText);
    const uint32 BodyLength = static_cast<uint32>(Utf8.Length());
    TArray<uint8> Frame;
    Frame.SetNumUninitialized(4 + Utf8.Length());
    Frame[0] = static_cast<uint8>((BodyLength >> 24) & 0xff);
    Frame[1] = static_cast<uint8>((BodyLength >> 16) & 0xff);
    Frame[2] = static_cast<uint8>((BodyLength >> 8) & 0xff);
    Frame[3] = static_cast<uint8>(BodyLength & 0xff);
    FMemory::Memcpy(Frame.GetData() + 4, Utf8.Get(), Utf8.Length());
    return Frame;
}
