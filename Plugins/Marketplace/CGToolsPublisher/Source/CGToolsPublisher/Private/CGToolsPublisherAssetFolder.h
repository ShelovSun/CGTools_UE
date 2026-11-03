#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"

namespace CGToolsPublisher
{
    // Resolve the owning asset folder even when the selected mesh is nested
    // in Meshes or shares the folder with several independent models.
    inline bool ResolveTypedAssetFolder(
        const FString& PackageName,
        const FString& AssetsFolder,
        const FString& AssetKind,
        FString& OutType,
        FString& OutFolder,
        FString& OutName,
        FString& OutError)
    {
        OutType.Reset();
        OutFolder.Reset();
        OutName.Reset();
        OutError.Reset();
        const FString Prefix = TEXT("/Game/") + AssetsFolder + TEXT("/");
        TArray<FString> Parts;
        if (PackageName.StartsWith(Prefix))
        {
            PackageName.Mid(Prefix.Len()).ParseIntoArray(Parts, TEXT("/"), false);
        }
        if (Parts.Num() < 3 || Parts.Contains(FString())
            || Parts.Contains(TEXT(".")) || Parts.Contains(TEXT("..")))
        {
            OutError = FString::Printf(
                TEXT("%s必须位于 %s{类型}/{资产文件夹}/ 下。\n\n所选包：%s"),
                *AssetKind, *Prefix, *PackageName);
            return false;
        }
        OutType = Parts[0];
        OutName = Parts[1];
        OutFolder = Prefix + OutType + TEXT("/") + OutName;
        return true;
    }

    inline bool ResolveSkeletalAssetFolder(
        const FString& PackageName, const FString& AssetsFolder,
        FString& OutType, FString& OutFolder, FString& OutName, FString& OutError)
    {
        return ResolveTypedAssetFolder(PackageName, AssetsFolder, TEXT("骨骼网格体"),
            OutType, OutFolder, OutName, OutError);
    }

    inline bool ResolveStaticAssetFolder(
        const FString& PackageName, const FString& AssetsFolder, const FString& ScenesFolder,
        FString& OutType, FString& OutFolder, FString& OutName, FString& OutError)
    {
        // Both existing library layouts can contain static meshes. A mesh in
        // JinBiQian/Meshes still belongs to JinBiQian, rather than to Meshes.
        for (const FString& Root : { AssetsFolder, ScenesFolder })
        {
            const FString Prefix = TEXT("/Game/") + Root + TEXT("/");
            if (PackageName.StartsWith(Prefix))
            {
                return ResolveTypedAssetFolder(PackageName, Root, TEXT("静态网格体"),
                    OutType, OutFolder, OutName, OutError);
            }
        }
        OutType.Reset();
        OutFolder.Reset();
        OutName.Reset();
        OutError.Reset();
        // Static publishing also supports project folders outside the library
        // layouts. In that case, the immediate parent is the publish unit.
        const FString Prefix = TEXT("/Game/");
        TArray<FString> Parts;
        if (PackageName.StartsWith(Prefix))
        {
            PackageName.Mid(Prefix.Len()).ParseIntoArray(Parts, TEXT("/"), false);
        }
        if (Parts.Num() < 2 || Parts.Contains(FString())
            || Parts.Contains(TEXT(".")) || Parts.Contains(TEXT("..")))
        {
            OutError = TEXT("静态网格体必须位于 /Game 下的独立资产文件夹中，不能直接位于 /Game 根目录。\n\n所选包：") + PackageName;
            return false;
        }
        OutName = Parts[Parts.Num() - 2];
        Parts.Pop();
        OutFolder = Prefix + FString::Join(Parts, TEXT("/"));
        return true;
    }

    inline void AddAssetFolderPackages(
        const FString& Folder,
        const TArray<FAssetData>& Assets,
        TArray<FName>& OutPackages)
    {
        const FString Prefix = Folder + TEXT("/");
        for (const FAssetData& Data : Assets)
        {
            if (!Data.IsRedirector() && Data.PackageName.ToString().StartsWith(Prefix))
            {
                OutPackages.AddUnique(Data.PackageName);
            }
        }
    }
}
