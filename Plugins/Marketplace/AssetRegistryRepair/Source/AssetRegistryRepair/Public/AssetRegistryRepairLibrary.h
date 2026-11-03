#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "AssetRegistryRepairLibrary.generated.h"

USTRUCT(BlueprintType)
struct ASSETREGISTRYREPAIR_API FAssetRegistryRepairResult
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    bool bSucceeded = false;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    bool bCanceled = false;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    TArray<FString> TargetFolders;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 FoundFileCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 SkippedByTimeCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 SkippedByFolderCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 ScannedFileCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 PackageCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 AlreadyVisiblePackageCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 MissingPackageCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 LoadedPackageCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 FailedPackageCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 SkippedByLoadLimitCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    int32 RegisteredAssetCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Asset Registry Repair")
    FString Message;
};

UCLASS()
class ASSETREGISTRYREPAIR_API UAssetRegistryRepairLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Asset Registry Repair")
    static TArray<FString> GetContentBrowserRepairTargetFolders();

    UFUNCTION(
        BlueprintCallable,
        Category = "Asset Registry Repair",
        meta = (
            DisplayName = "Repair Selected Content Browser Folders",
            AdvancedDisplay = "bIncludeMaps,bForceLoadMissingPackages,MaxPackagesToLoad,MaxAssetsToSync"
            )
    )
    static FAssetRegistryRepairResult RepairSelectedContentBrowserFolders(
        int32 ModifiedWithinMinutes = 30,
        bool bIncludeMaps = false,
        bool bForceLoadMissingPackages = true,
        int32 MaxPackagesToLoad = 200,
        int32 MaxAssetsToSync = 30
    );

    UFUNCTION(
        BlueprintCallable,
        Category = "Asset Registry Repair",
        meta = (
            DisplayName = "Repair Asset Registry From Folders",
            AdvancedDisplay = "bIncludeMaps,bForceLoadMissingPackages,MaxPackagesToLoad,MaxAssetsToSync"
            )
    )
    static FAssetRegistryRepairResult RepairAssetRegistryFromDiskInFolders(
        const TArray<FString>& VirtualFolders,
        int32 ModifiedWithinMinutes = 30,
        bool bIncludeMaps = false,
        bool bForceLoadMissingPackages = true,
        int32 MaxPackagesToLoad = 200,
        int32 MaxAssetsToSync = 30
    );
};