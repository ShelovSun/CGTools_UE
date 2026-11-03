// Copyright CGTools. All Rights Reserved.

#include "MayaBridgeSettings.h"

#include "CGToolsMayaBridgeLog.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformMisc.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Interfaces/IPluginManager.h"

namespace
{
FString ExpandTemplate(const FString& Template, const FMayaPublishedAction& Action)
{
    FString Result = Template;
    Result.ReplaceInline(TEXT("{project_name}"), *Action.ProjectName, ESearchCase::CaseSensitive);
    Result.ReplaceInline(TEXT("{asset_type}"), *Action.AssetType, ESearchCase::CaseSensitive);
    Result.ReplaceInline(TEXT("{asset_name}"), *Action.AssetName, ESearchCase::CaseSensitive);
    Result.ReplaceInline(TEXT("{action_name}"), *Action.ActionName, ESearchCase::CaseSensitive);
    return Result;
}

bool IsOverrideMatch(const FMayaBridgeAssetOverride& Override, const FMayaPublishedAction& Action)
{
    const bool bProjectMatches = Override.ProjectName.IsEmpty()
        || Override.ProjectName.Equals(Action.ProjectName, ESearchCase::IgnoreCase);

    return bProjectMatches
        && Override.AssetType.Equals(Action.AssetType, ESearchCase::IgnoreCase)
        && Override.AssetName.Equals(Action.AssetName, ESearchCase::IgnoreCase);
}
}

void FMayaBridgeSettings::ResolveImportPaths(
    const FMayaPublishedAction& Action,
    FString& OutSkeleton,
    FString& OutAnimationPath) const
{
    OutSkeleton = ExpandTemplate(SkeletonTemplate, Action);
    OutAnimationPath = ExpandTemplate(AnimationPathTemplate, Action);

    for (const FMayaBridgeAssetOverride& Override : AssetOverrides)
    {
        if (!IsOverrideMatch(Override, Action))
        {
            continue;
        }

        if (!Override.Skeleton.IsEmpty())
        {
            OutSkeleton = ExpandTemplate(Override.Skeleton, Action);
        }
        if (!Override.AnimationPath.IsEmpty())
        {
            OutAnimationPath = ExpandTemplate(Override.AnimationPath, Action);
        }
        break;
    }
}

FString FMayaBridgeSettingsLoader::GetConfigPath()
{
    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("CGToolsMayaBridge"));
    if (!Plugin.IsValid())
    {
        return FPaths::Combine(
            FPaths::EnginePluginsDir(),
            TEXT("Marketplace/CGToolsMayaBridge/Config/BridgeSettings.json"));
    }

    return FPaths::Combine(Plugin->GetBaseDir(), TEXT("Config/BridgeSettings.json"));
}

FMayaBridgeSettings FMayaBridgeSettingsLoader::Load()
{
    FMayaBridgeSettings Settings;
    const FString ConfigPath = GetConfigPath();
    FString JsonText;

    if (!FFileHelper::LoadFileToString(JsonText, *ConfigPath))
    {
        UE_LOG(
            LogCGToolsMayaBridge,
            Warning,
            TEXT("Could not read %s; using default bridge settings."),
            *ConfigPath);
    }
    else
    {
        TSharedPtr<FJsonObject> Root;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
        if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
        {
            UE_LOG(
                LogCGToolsMayaBridge,
                Error,
                TEXT("Invalid JSON in %s; using default bridge settings."),
                *ConfigPath);
        }
        else
        {
            double JsonPort = 0.0;
            if (Root->TryGetNumberField(TEXT("port"), JsonPort)
                && JsonPort >= 1.0
                && JsonPort <= 65535.0)
            {
                Settings.Port = static_cast<int32>(JsonPort);
            }

            FString Value;
            if (Root->TryGetStringField(TEXT("skeleton_template"), Value) && !Value.IsEmpty())
            {
                Settings.SkeletonTemplate = MoveTemp(Value);
            }
            if (Root->TryGetStringField(TEXT("animation_path_template"), Value) && !Value.IsEmpty())
            {
                Settings.AnimationPathTemplate = MoveTemp(Value);
            }
            Root->TryGetBoolField(TEXT("replace_existing"), Settings.bReplaceExisting);

            const TArray<TSharedPtr<FJsonValue>>* Overrides = nullptr;
            if (Root->TryGetArrayField(TEXT("asset_overrides"), Overrides) && Overrides != nullptr)
            {
                for (const TSharedPtr<FJsonValue>& OverrideValue : *Overrides)
                {
                    if (!OverrideValue.IsValid() || OverrideValue->Type != EJson::Object)
                    {
                        continue;
                    }

                    const TSharedPtr<FJsonObject> OverrideObject = OverrideValue->AsObject();
                    FMayaBridgeAssetOverride Override;
                    OverrideObject->TryGetStringField(TEXT("project_name"), Override.ProjectName);
                    OverrideObject->TryGetStringField(TEXT("asset_type"), Override.AssetType);
                    OverrideObject->TryGetStringField(TEXT("asset_name"), Override.AssetName);
                    OverrideObject->TryGetStringField(TEXT("skeleton"), Override.Skeleton);
                    OverrideObject->TryGetStringField(TEXT("animation_path"), Override.AnimationPath);

                    if (!Override.AssetType.IsEmpty() && !Override.AssetName.IsEmpty())
                    {
                        Settings.AssetOverrides.Add(MoveTemp(Override));
                    }
                }
            }
        }
    }

    const FString EnvironmentPort = FPlatformMisc::GetEnvironmentVariable(TEXT("CGTOOLS_UE_BRIDGE_PORT"));
    int32 ParsedEnvironmentPort = 0;
    if (!EnvironmentPort.IsEmpty()
        && LexTryParseString(ParsedEnvironmentPort, *EnvironmentPort)
        && ParsedEnvironmentPort >= 1
        && ParsedEnvironmentPort <= 65535)
    {
        Settings.Port = ParsedEnvironmentPort;
    }
    else if (!EnvironmentPort.IsEmpty())
    {
        UE_LOG(
            LogCGToolsMayaBridge,
            Warning,
            TEXT("Ignoring invalid CGTOOLS_UE_BRIDGE_PORT value: %s"),
            *EnvironmentPort);
    }

    return Settings;
}
