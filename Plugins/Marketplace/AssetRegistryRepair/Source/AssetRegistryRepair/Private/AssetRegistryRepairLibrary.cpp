#include "AssetRegistryRepairLibrary.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "ContentBrowserModule.h"
#include "EditorUtilityLibrary.h"
#include "HAL/FileManager.h"
#include "IContentBrowserSingleton.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopedSlowTask.h"
#include "Modules/ModuleManager.h"
#include "UObject/Package.h"
#include "UObject/UObjectGlobals.h"

DEFINE_LOG_CATEGORY_STATIC(LogAssetRegistryRepair, Log, All);

namespace
{
    FString NormalizeVirtualFolder(FString Path)
    {
        Path.TrimStartAndEndInline();
        Path.ReplaceInline(TEXT("\\"), TEXT("/"));
        Path.RemoveFromEnd(TEXT("/"));

        if (Path.Equals(TEXT("/All/Game"), ESearchCase::IgnoreCase))
        {
            Path = TEXT("/Game");
        }
        else if (Path.StartsWith(TEXT("/All/Game/"), ESearchCase::IgnoreCase))
        {
            Path = FString(TEXT("/Game")) + Path.Mid(9);
        }

        return Path;
    }

    bool IsValidGameVirtualPath(const FString& Path)
    {
        return Path == TEXT("/Game") || Path.StartsWith(TEXT("/Game/"));
    }

    bool ShouldSkipAssetFile(FString Filename)
    {
        Filename.ReplaceInline(TEXT("\\"), TEXT("/"));

        return Filename.Contains(TEXT("/__ExternalActors__/"))
            || Filename.Contains(TEXT("/__ExternalObjects__/"))
            || Filename.Contains(TEXT("/Collections/"));
    }

    bool WasModifiedWithinMinutes(const FString& Filename, int32 ModifiedWithinMinutes)
    {
        if (ModifiedWithinMinutes <= 0)
        {
            return true;
        }

        const FDateTime ModifiedTime = IFileManager::Get().GetTimeStamp(*Filename);

        if (ModifiedTime == FDateTime::MinValue())
        {
            return false;
        }

        const FTimespan Age = FDateTime::Now() - ModifiedTime;

        if (Age.GetTicks() < 0)
        {
            return true;
        }

        return Age <= FTimespan::FromMinutes(ModifiedWithinMinutes);
    }

    FString VirtualFolderToDiskFolder(const FString& VirtualFolder)
    {
        FString DiskFolder = FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir());

        if (VirtualFolder.StartsWith(TEXT("/Game/")))
        {
            const FString RelativeFolder = VirtualFolder.RightChop(6);
            DiskFolder = FPaths::Combine(DiskFolder, RelativeFolder);
        }

        FPaths::NormalizeDirectoryName(DiskFolder);
        return DiskFolder;
    }

    void AppendFilesByExtension(
        const FString& DiskFolder,
        const TCHAR* ExtensionPattern,
        TArray<FString>& OutFiles
    )
    {
        TArray<FString> FoundFiles;

        IFileManager::Get().FindFilesRecursive(
            FoundFiles,
            *DiskFolder,
            ExtensionPattern,
            true,
            false
        );

        for (FString File : FoundFiles)
        {
            FPaths::NormalizeFilename(File);
            OutFiles.Add(File);
        }
    }

    void CollectAssetFilesInFolder(
        const FString& VirtualFolder,
        int32 ModifiedWithinMinutes,
        bool bIncludeMaps,
        TArray<FString>& OutAssetFiles,
        FAssetRegistryRepairResult& Result
    )
    {
        const FString DiskFolder = VirtualFolderToDiskFolder(VirtualFolder);

        if (!IFileManager::Get().DirectoryExists(*DiskFolder))
        {
            UE_LOG(
                LogAssetRegistryRepair,
                Warning,
                TEXT("Folder does not exist on disk: %s"),
                *DiskFolder
            );

            return;
        }

        TArray<FString> FoundFiles;
        AppendFilesByExtension(DiskFolder, TEXT("*.uasset"), FoundFiles);

        if (bIncludeMaps)
        {
            AppendFilesByExtension(DiskFolder, TEXT("*.umap"), FoundFiles);
        }

        Result.FoundFileCount += FoundFiles.Num();

        for (const FString& File : FoundFiles)
        {
            if (ShouldSkipAssetFile(File))
            {
                ++Result.SkippedByFolderCount;
                continue;
            }

            if (!WasModifiedWithinMinutes(File, ModifiedWithinMinutes))
            {
                ++Result.SkippedByTimeCount;
                continue;
            }

            OutAssetFiles.AddUnique(File);
        }
    }

    bool TryConvertAssetFileToPackageName(const FString& AssetFile, FString& OutPackageName)
    {
        if (!FPackageName::TryConvertFilenameToLongPackageName(AssetFile, OutPackageName))
        {
            return false;
        }

        return OutPackageName == TEXT("/Game") || OutPackageName.StartsWith(TEXT("/Game/"));
    }

    bool PackageAlreadyInAssetRegistry(IAssetRegistry& AssetRegistry, const FString& PackageName)
    {
        TArray<FAssetData> ExistingAssets;
        AssetRegistry.GetAssetsByPackageName(FName(*PackageName), ExistingAssets, true);
        return ExistingAssets.Num() > 0;
    }

    int32 RegisterLoadedPackageAssets(
        const FString& PackageName,
        TArray<FAssetData>& OutRecoveredAssets,
        TSet<FString>& OutRegisteredObjectPaths
    )
    {
        UPackage* Package = FindPackage(nullptr, *PackageName);

        if (!Package)
        {
            Package = LoadPackage(nullptr, *PackageName, LOAD_None);
        }

        if (!Package)
        {
            return -1;
        }

        int32 RegisteredCount = 0;

        TArray<UObject*> PackageObjects;
        GetObjectsWithOuter(Package, PackageObjects, false);

        for (UObject* Object : PackageObjects)
        {
            if (!Object || !Object->IsAsset() || Object->HasAnyFlags(RF_Transient))
            {
                continue;
            }

            const FString ObjectPath = Object->GetPathName();

            if (OutRegisteredObjectPaths.Contains(ObjectPath))
            {
                continue;
            }

            FAssetRegistryModule::AssetCreated(Object);
            OutRegisteredObjectPaths.Add(ObjectPath);

            FAssetData AssetData(Object);

            if (AssetData.IsValid())
            {
                OutRecoveredAssets.Add(AssetData);
            }

            ++RegisteredCount;
        }

        if (RegisteredCount == 0)
        {
            const FString AssetName = FPackageName::GetLongPackageAssetName(PackageName);

            UObject* MainAsset = StaticFindObject(
                UObject::StaticClass(),
                Package,
                *AssetName
            );

            if (MainAsset && MainAsset->IsAsset() && !MainAsset->HasAnyFlags(RF_Transient))
            {
                const FString ObjectPath = MainAsset->GetPathName();

                if (!OutRegisteredObjectPaths.Contains(ObjectPath))
                {
                    FAssetRegistryModule::AssetCreated(MainAsset);
                    OutRegisteredObjectPaths.Add(ObjectPath);

                    FAssetData AssetData(MainAsset);

                    if (AssetData.IsValid())
                    {
                        OutRecoveredAssets.Add(AssetData);
                    }

                    ++RegisteredCount;
                }
            }
        }

        return RegisteredCount;
    }

    void SyncContentBrowser(
        const TArray<FString>& TargetFolders,
        const TArray<FAssetData>& RecoveredAssets,
        int32 MaxAssetsToSync
    )
    {
        // Automatic callers may need registry recovery without changing the
        // user's path, selection, search or filters. Zero disables all navigation,
        // including the folder-only fallback when nothing needed to be loaded.
        if (MaxAssetsToSync == 0)
        {
            return;
        }
        if (RecoveredAssets.Num() > 0)
        {
            // SyncBrowserToAssets creates a temporary multi-asset view.  If
            // recursively recovered assets from child folders are included,
            // Content Browser temporarily shows them as if they were direct
            // children of the selected parent folder.  Keep recursive repair,
            // but only use assets located directly in an explicitly requested
            // target folder for browser selection.
            TSet<FName> DirectTargetPackagePaths;
            for (const FString& TargetFolder : TargetFolders)
            {
                DirectTargetPackagePaths.Add(FName(*TargetFolder));
            }

            TArray<FAssetData> AssetsToSync;
            for (const FAssetData& RecoveredAsset : RecoveredAssets)
            {
                if (!DirectTargetPackagePaths.Contains(RecoveredAsset.PackagePath))
                {
                    continue;
                }

                AssetsToSync.Add(RecoveredAsset);
                if (MaxAssetsToSync > 0 && AssetsToSync.Num() >= MaxAssetsToSync)
                {
                    break;
                }
            }

            if (AssetsToSync.Num() > 0)
            {
                FContentBrowserModule& ContentBrowserModule =
                    FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));

                ContentBrowserModule.Get().SyncBrowserToAssets(AssetsToSync);
                return;
            }
        }

        if (TargetFolders.Num() > 0)
        {
            UEditorUtilityLibrary::SyncBrowserToFolders(TargetFolders);
        }
    }

    FString MakeSummaryMessage(const FAssetRegistryRepairResult& Result)
    {
        return FString::Printf(
            TEXT("Repair finished. Files found: %d, scanned: %d, packages: %d, missing packages: %d, loaded packages: %d, failed packages: %d, registered assets: %d, skipped by time: %d, skipped by folder: %d, skipped by load limit: %d."),
            Result.FoundFileCount,
            Result.ScannedFileCount,
            Result.PackageCount,
            Result.MissingPackageCount,
            Result.LoadedPackageCount,
            Result.FailedPackageCount,
            Result.RegisteredAssetCount,
            Result.SkippedByTimeCount,
            Result.SkippedByFolderCount,
            Result.SkippedByLoadLimitCount
        );
    }
}

TArray<FString> UAssetRegistryRepairLibrary::GetContentBrowserRepairTargetFolders()
{
    TArray<FString> Result;

    auto AddFolder = [&Result](FString Folder)
        {
            Folder = NormalizeVirtualFolder(Folder);

            if (!IsValidGameVirtualPath(Folder))
            {
                return;
            }

            Result.AddUnique(Folder);
        };

    for (const FString& Folder : UEditorUtilityLibrary::GetSelectedPathViewFolderPaths())
    {
        AddFolder(Folder);
    }

    for (const FString& Folder : UEditorUtilityLibrary::GetSelectedFolderPaths())
    {
        AddFolder(Folder);
    }

    if (Result.Num() == 0)
    {
        FString CurrentPath;

        if (UEditorUtilityLibrary::GetCurrentContentBrowserPath(CurrentPath))
        {
            AddFolder(CurrentPath);
        }
    }

    return Result;
}

FAssetRegistryRepairResult UAssetRegistryRepairLibrary::RepairSelectedContentBrowserFolders(
    int32 ModifiedWithinMinutes,
    bool bIncludeMaps,
    bool bForceLoadMissingPackages,
    int32 MaxPackagesToLoad,
    int32 MaxAssetsToSync
)
{
    const TArray<FString> TargetFolders = GetContentBrowserRepairTargetFolders();

    return RepairAssetRegistryFromDiskInFolders(
        TargetFolders,
        ModifiedWithinMinutes,
        bIncludeMaps,
        bForceLoadMissingPackages,
        MaxPackagesToLoad,
        MaxAssetsToSync
    );
}

FAssetRegistryRepairResult UAssetRegistryRepairLibrary::RepairAssetRegistryFromDiskInFolders(
    const TArray<FString>& VirtualFolders,
    int32 ModifiedWithinMinutes,
    bool bIncludeMaps,
    bool bForceLoadMissingPackages,
    int32 MaxPackagesToLoad,
    int32 MaxAssetsToSync
)
{
    FAssetRegistryRepairResult Result;

    for (FString Folder : VirtualFolders)
    {
        Folder = NormalizeVirtualFolder(Folder);

        if (IsValidGameVirtualPath(Folder))
        {
            Result.TargetFolders.AddUnique(Folder);
        }
    }

    if (Result.TargetFolders.Num() == 0)
    {
        Result.Message = TEXT("No valid /Game folder selected in Content Browser.");
        UE_LOG(LogAssetRegistryRepair, Warning, TEXT("%s"), *Result.Message);
        return Result;
    }

    TArray<FString> AssetFiles;

    for (const FString& Folder : Result.TargetFolders)
    {
        CollectAssetFilesInFolder(
            Folder,
            ModifiedWithinMinutes,
            bIncludeMaps,
            AssetFiles,
            Result
        );
    }

    Result.ScannedFileCount = AssetFiles.Num();

    if (AssetFiles.Num() == 0)
    {
        Result.bSucceeded = true;
        Result.Message = TEXT("No asset files matched the selected folder and modified-time filter.");
        UE_LOG(LogAssetRegistryRepair, Display, TEXT("%s"), *Result.Message);
        SyncContentBrowser(Result.TargetFolders, TArray<FAssetData>(), MaxAssetsToSync);
        return Result;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));

    IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

    UE_LOG(
        LogAssetRegistryRepair,
        Display,
        TEXT("Scanning %d files for asset registry repair."),
        AssetFiles.Num()
    );

    AssetRegistry.ScanModifiedAssetFiles(AssetFiles);
    AssetRegistry.ScanFilesSynchronous(AssetFiles, true);
    AssetRegistry.WaitForCompletion();

    TArray<FString> PackageNames;

    for (const FString& AssetFile : AssetFiles)
    {
        FString PackageName;

        if (TryConvertAssetFileToPackageName(AssetFile, PackageName))
        {
            PackageNames.AddUnique(PackageName);
        }
    }

    Result.PackageCount = PackageNames.Num();

    TArray<FString> MissingPackages;

    for (const FString& PackageName : PackageNames)
    {
        if (PackageAlreadyInAssetRegistry(AssetRegistry, PackageName))
        {
            ++Result.AlreadyVisiblePackageCount;
            continue;
        }

        MissingPackages.Add(PackageName);
    }

    Result.MissingPackageCount = MissingPackages.Num();

    if (!bForceLoadMissingPackages || MissingPackages.Num() == 0)
    {
        Result.bSucceeded = true;
        Result.Message = MakeSummaryMessage(Result);

        UE_LOG(LogAssetRegistryRepair, Display, TEXT("%s"), *Result.Message);
        SyncContentBrowser(Result.TargetFolders, TArray<FAssetData>(), MaxAssetsToSync);

        return Result;
    }

    const int32 PackagesToLoadCount = MaxPackagesToLoad <= 0
        ? MissingPackages.Num()
        : FMath::Min(MaxPackagesToLoad, MissingPackages.Num());

    Result.SkippedByLoadLimitCount = MissingPackages.Num() - PackagesToLoadCount;

    TArray<FAssetData> RecoveredAssets;
    TSet<FString> RegisteredObjectPaths;

    FScopedSlowTask SlowTask(
        PackagesToLoadCount,
        FText::FromString(TEXT("Repairing missing Content Browser assets..."))
    );

    SlowTask.MakeDialog(true);

    for (int32 Index = 0; Index < PackagesToLoadCount; ++Index)
    {
        if (SlowTask.ShouldCancel())
        {
            Result.bCanceled = true;
            break;
        }

        const FString& PackageName = MissingPackages[Index];

        SlowTask.EnterProgressFrame(
            1.0f,
            FText::FromString(PackageName)
        );

        const int32 RegisteredCount = RegisterLoadedPackageAssets(
            PackageName,
            RecoveredAssets,
            RegisteredObjectPaths
        );

        if (RegisteredCount < 0)
        {
            ++Result.FailedPackageCount;
            continue;
        }

        ++Result.LoadedPackageCount;
        Result.RegisteredAssetCount += RegisteredCount;
    }

    AssetRegistry.ScanModifiedAssetFiles(AssetFiles);
    AssetRegistry.ScanFilesSynchronous(AssetFiles, true);
    AssetRegistry.WaitForCompletion();

    SyncContentBrowser(Result.TargetFolders, RecoveredAssets, MaxAssetsToSync);

    Result.bSucceeded = !Result.bCanceled;
    Result.Message = MakeSummaryMessage(Result);

    UE_LOG(LogAssetRegistryRepair, Display, TEXT("%s"), *Result.Message);

    return Result;
}
