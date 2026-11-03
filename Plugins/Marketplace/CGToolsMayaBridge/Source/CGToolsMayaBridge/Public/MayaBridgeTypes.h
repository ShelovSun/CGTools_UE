// Copyright CGTools. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"

struct FMayaPublishedAction
{
    FString ProjectName;
    FString AssetType;
    FString AssetName;
    FString ActionName;
    FString FbxPath;
    int64 FbxSizeBytes = -1;
    FString MayaFilePath;
    FString ReferenceNode;
    FString ReferencePath;
    FString Namespace;
    double StartFrame = 0.0;
    double EndFrame = 0.0;
};

struct FMayaBridgeMessage
{
    FString EventId;
    FString SentAtUtc;
    TArray<FString> ProjectNames;
    TArray<FMayaPublishedAction> Actions;
};

struct FMayaBridgeAssetOverride
{
    FString ProjectName;
    FString AssetType;
    FString AssetName;
    FString Skeleton;
    FString AnimationPath;
};

struct FMayaBridgeSettings
{
    int32 Port = 19821;
    FString SkeletonTemplate = TEXT("/Game/Assets/{asset_type}/{asset_name}/{asset_name}_Skeleton");
    FString AnimationPathTemplate = TEXT("/Game/Assets/{asset_type}/{asset_name}/Action");
    bool bReplaceExisting = true;
    TArray<FMayaBridgeAssetOverride> AssetOverrides;

    void ResolveImportPaths(const FMayaPublishedAction& Action, FString& OutSkeleton, FString& OutAnimationPath) const;
};
