#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CGToolsAssetBridgeLibrary.generated.h"

/**
 * Small native bridge used by AssetsManagerForUE.
 * Package copying and UI stay in Python; viewport hit testing and actor creation
 * remain in Unreal's native editor layer.
 */
UCLASS(meta = (ScriptName = "CGToolsAssetBridgeLibrary"))
class CGTOOLSASSETBRIDGE_API UCGToolsAssetBridgeLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "CGTools|AssetBridge")
    static FString GetBridgeVersion();

    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool CanPlaceAssetAtCursor(const FString& ObjectPath, FString& OutError);

    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool PlaceAssetAtCursor(const FString& ObjectPath, FString& OutError);

    /** Read the embedded thumbnail from an external .uasset and export it as PNG. */
    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool ExportExternalAssetThumbnail(
        const FString& AssetFilePath,
        const FString& OutputPngPath,
        FString& OutError);

    /** Worker-only: embedded thumbnail, then Niagara/Cascade preview texture.
     * Empty string means success. NO_THUMBNAIL| means a genuine missing image.
     * External packages are loaded only in a separate unattended thumbnail worker.
     */
    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static FString ExportExternalVfxThumbnail(
        const FString& AssetFilePath,
        const FString& SourceContentRoot,
        const FString& OutputPngPath);

    /** Return the top-level AssetClassPath asset name for each external package. */
    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool GetExternalAssetClassNames(
        const TArray<FString>& AssetFilePaths,
        const FString& SourceContentRoot,
        TArray<FString>& OutClassNames,
        FString& OutError);

    /** Resolve the selected external package and its recursive package dependencies. */
    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool ResolveExternalAssetDependencies(
        const FString& AssetFilePath,
        const FString& SourceContentRoot,
        TArray<FString>& OutPackageFiles,
        TArray<FString>& OutMissingPackages,
        FString& OutError);

    /** Place using the exact Qt mouse-release position in virtual-desktop coordinates. */
    UFUNCTION(BlueprintCallable, Category = "CGTools|AssetBridge")
    static bool PlaceAssetAtScreenPosition(
        const FString& ObjectPath,
        int32 ScreenX,
        int32 ScreenY,
        FString& OutError);
};
