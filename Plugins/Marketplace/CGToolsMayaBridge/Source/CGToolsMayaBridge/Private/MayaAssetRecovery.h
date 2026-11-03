#pragma once

#include "CoreMinimal.h"
#include "MayaBridgeTypes.h"

struct FMayaAssetRecoveryResult
{
    FString Status = TEXT("error");
    FString Message;
    FString AssetRoot;
};

struct FMayaAssetRecoveryOperations
{
    TFunction<bool()> HasSkeleton;
    TFunction<bool(const FString&, const FString&)> Ask;
    TFunction<FMayaAssetRecoveryResult(const FString&)> Run;
};

class FMayaAssetRecovery
{
public:
    static bool EnsureSkeleton(const FMayaPublishedAction& Action, const FString& SkeletonPath, FString& OutError);
    static bool Recover(const FString& AssetName, const FString& SkeletonPath,
        const FMayaAssetRecoveryOperations& Operations, FString& OutError);
};
