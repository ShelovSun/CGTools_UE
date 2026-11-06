#include "SCGToolsVfxPublisherWindow.h"
#include "SCGToolsVfxDestinationBrowser.h"
#include "CGToolsPublisherFileReview.h"

#include "Animation/Skeleton.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetToolsModule.h"
#include "Async/Async.h"
#include "CGToolsPublisherAssetUtils.h"
#include "SCGToolsPublisherAssetPreview.h"
#include "ContentBrowserModule.h"
#include "Editor.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture.h"
#include "Engine/Texture2D.h"
#include "Tests/CGToolsPublisherBrowserTestScope.h"
#include "FileHelpers.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "HAL/PlatformProcess.h"
#include "IAssetTools.h"
#include "IContentBrowserSingleton.h"
#include "Materials/MaterialFunctionInterface.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/MessageDialog.h"
#include "Misc/ObjectThumbnail.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "Misc/SecureHash.h"
#include "Misc/ScopedSlowTask.h"
#include "NiagaraSystem.h"
#include "ObjectTools.h"
#include "PackageTools.h"
#include "Particles/ParticleSystem.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "Serialization/Archive.h"
#include "Styling/AppStyle.h"
#include "UObject/ObjectRedirector.h"
#include "UObject/LinkerInstancingContext.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

#if WITH_DEV_AUTOMATION_TESTS
#include "Factories/Factory.h"
#include "Materials/MaterialFunction.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Misc/AutomationTest.h"
#include "Engine/Texture2D.h"
#endif

#define LOCTEXT_NAMESPACE "CGToolsVfxPublisher"

DEFINE_LOG_CATEGORY_STATIC(LogCGToolsVfxPublisher, Log, All);

namespace CGToolsVfxPublisher
{
    bool IsEffectAsset(const FAssetData& Asset)
    {
        return Asset.IsInstanceOf<UNiagaraSystem>(EResolveClass::Yes)
            || Asset.IsInstanceOf<UParticleSystem>(EResolveClass::Yes);
    }
}

namespace
{
    const FString VfxProjectDirectory = TEXT("Y:/MCCTools/src/UE574/VFX");
    const FString VfxContentDirectory = VfxProjectDirectory / TEXT("Content");
    const FString VfxRootDirectory = VfxContentDirectory / TEXT("VFX");

    TArray<FString> GetVfxPublishReviewRoots(const FString& Stage)
    {
        // Review the organized output and its dependencies, not unrelated effects
        // already sharing the target folder. No server-only file is removed.
        TArray<FString> Roots;
        IFileManager::Get().FindFilesRecursive(Roots, *Stage, TEXT("*"), true, false);
        const FString StageRoot = FPaths::ConvertRelativePathToFull(Stage) + TEXT("/");
        for (FString& Path : Roots) { FPaths::MakePathRelativeTo(Path, *StageRoot); }
        return Roots;
    }

    FString NormalizeDirectory(const FString& Directory)
    {
        FString Result = FPaths::ConvertRelativePathToFull(Directory);
        FPaths::NormalizeDirectoryName(Result);
        FPaths::CollapseRelativeDirectories(Result);
        return Result;
    }

    bool IsDirectoryWithin(const FString& Directory, const FString& Root)
    {
        const FString NormalizedDirectory = NormalizeDirectory(Directory);
        const FString NormalizedRoot = NormalizeDirectory(Root);
        return NormalizedDirectory.Equals(NormalizedRoot, ESearchCase::IgnoreCase)
            || NormalizedDirectory.StartsWith(NormalizedRoot + TEXT("/"), ESearchCase::IgnoreCase);
    }

    bool GetTargetPackageFolder(const FString& Directory, FString& OutFolder, const FString& ContentDirectory = VfxContentDirectory)
    {
        if (!IsDirectoryWithin(Directory, ContentDirectory / TEXT("VFX")))
        {
            return false;
        }
        OutFolder = TEXT("/Game/")
            + NormalizeDirectory(Directory).Mid(NormalizeDirectory(ContentDirectory).Len() + 1);
        return FPackageName::IsValidLongPackageName(OutFolder);
    }

    bool IsOrganizerDirectoryName(const FString& Name)
    {
        return Name.Equals(TEXT("M_F"), ESearchCase::IgnoreCase)
            || Name.Equals(TEXT("Mat"), ESearchCase::IgnoreCase)
            || Name.Equals(TEXT("Mesh"), ESearchCase::IgnoreCase)
            || Name.Equals(TEXT("Tex"), ESearchCase::IgnoreCase);
    }

    bool ValidateDirectoryName(const FString& Name, FString& OutError)
    {
        FString Stem = Name;
        int32 DotIndex;
        if (Stem.FindChar(TEXT('.'), DotIndex))
        {
            Stem.LeftInline(DotIndex);
        }
        Stem.ToUpperInline();
        const bool bReserved = Stem == TEXT("CON") || Stem == TEXT("PRN") || Stem == TEXT("AUX") || Stem == TEXT("NUL")
            || (Stem.Len() == 4 && (Stem.StartsWith(TEXT("COM")) || Stem.StartsWith(TEXT("LPT")))
                && Stem[3] >= TEXT('1') && Stem[3] <= TEXT('9'));
        FText Reason;
        if (Name.IsEmpty() || Name.Contains(TEXT("/")) || Name.Contains(TEXT("\\"))
            || Name.EndsWith(TEXT(".")) || bReserved
            || !FPackageName::IsValidLongPackageName(TEXT("/Game/VFX/") + Name, false, &Reason))
        {
            OutError = TEXT("请输入有效的单层文件夹名称，可使用中文、字母、数字和下划线。");
            return false;
        }
        return true;
    }

    bool CreateChildDirectory(const FString& Parent, const FString& InName, FString& OutDirectory,
        FString& OutError, const FString& Root = VfxRootDirectory)
    {
        OutDirectory.Reset();
        const FString Name = InName.TrimStartAndEnd();
        if (!ValidateDirectoryName(Name, OutError)) { return false; }
        IFileManager& Files = IFileManager::Get();
        if (!IsDirectoryWithin(Parent, Root) || !Files.DirectoryExists(*Parent))
        {
            OutError = TEXT("选中的父文件夹不可访问，请刷新后重试。");
            return false;
        }
        const FString NewDirectory = NormalizeDirectory(Parent / Name);
        if (Files.DirectoryExists(*NewDirectory) || Files.FileExists(*NewDirectory))
        {
            OutError = TEXT("该名称已存在，请使用其他文件夹名称。");
            return false;
        }
        if (!Files.MakeDirectory(*NewDirectory, false))
        {
            OutError = TEXT("新建文件夹失败，请检查网络连接和目录写入权限。");
            return false;
        }
        OutDirectory = NewDirectory;
        OutError.Reset();
        return true;
    }

    bool ValidateEmptyDirectoryTree(const FString& Directory, FString& OutError,
        const FString& Root = VfxRootDirectory)
    {
        OutError.Reset();
        const FString Source = NormalizeDirectory(Directory);
        const FString NormalizedRoot = NormalizeDirectory(Root);
        IPlatformFile& Physical = FPlatformFileManager::Get().GetPlatformPhysical();
        if (!IsDirectoryWithin(Source, NormalizedRoot)
            || Source.Equals(NormalizedRoot, ESearchCase::IgnoreCase)
            || !Physical.DirectoryExists(*Source))
        {
            OutError = TEXT("只能重命名 VFX 下可访问的子文件夹，请刷新后重试。\n") + Source;
            return false;
        }
        // Never follow junctions/symlinks, including ancestors of the selected directory.
        for (FString Ancestor = Source; ; Ancestor = FPaths::GetPath(Ancestor))
        {
            if (Physical.IsSymlink(*Ancestor) != ESymlinkResult::NonSymlink)
            {
                OutError = TEXT("不支持重命名包含链接路径的文件夹。\n") + Ancestor;
                return false;
            }
            if (Ancestor.Equals(NormalizedRoot, ESearchCase::IgnoreCase)) { break; }
        }
#if PLATFORM_WINDOWS
        TArray<FString> Pending = { Source };
        while (!Pending.IsEmpty())
        {
            const FString Current = Pending.Pop(EAllowShrinking::No);
            WIN32_FIND_DATAW Data;
            const HANDLE Handle = FindFirstFileW(*(Current / TEXT("*")), &Data);
            if (Handle == INVALID_HANDLE_VALUE)
            {
                const DWORD Code = GetLastError();
                if (Code == ERROR_FILE_NOT_FOUND && Physical.DirectoryExists(*Current)) { continue; }
                OutError = FString::Printf(TEXT("无法完整检查文件夹，未执行改名。请检查网络连接和读取权限。\n%s\nWindows 错误码：%lu"), *Current, Code);
                return false;
            }
            ON_SCOPE_EXIT { FindClose(Handle); };
            // UE's directory iterator reports success for some Windows enumeration
            // errors. Read the native error codes so unreadable is never treated as empty.
            do
            {
                if (FCString::Strcmp(Data.cFileName, TEXT(".")) == 0
                    || FCString::Strcmp(Data.cFileName, TEXT("..")) == 0)
                {
                    continue;
                }
                const FString Path = Current / Data.cFileName;
                if ((Data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0)
                {
                    OutError = TEXT("该文件夹或下级目录中含有文件，仅支持空目录改名。\n")
                        TEXT("已有特效请在目标 VFX 工程的内容浏览器中重命名并修复引用。\n\n") + Path;
                    return false;
                }
                if ((Data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                {
                    OutError = TEXT("不支持重命名包含链接路径的文件夹。\n") + Path;
                    return false;
                }
                Pending.Add(Path);
            } while (FindNextFileW(Handle, &Data));
            const DWORD Code = GetLastError();
            if (Code != ERROR_NO_MORE_FILES)
            {
                OutError = FString::Printf(TEXT("文件夹检查中断，未执行改名。请检查网络连接和读取权限。\n%s\nWindows 错误码：%lu"), *Current, Code);
                return false;
            }
        }
        return true;
#else
        OutError = TEXT("空目录安全改名当前仅支持 Windows。");
        return false;
#endif
    }

    bool RenameEmptyDirectory(const FString& Directory, const FString& InName, FString& OutDirectory,
        FString& OutError, const FString& Root = VfxRootDirectory)
    {
        OutDirectory.Reset();
        OutError.Reset();
        const FString Name = InName.TrimStartAndEnd();
        if (!ValidateDirectoryName(Name, OutError)) { return false; }
        if (IsOrganizerDirectoryName(Name))
        {
            OutError = TEXT("M_F、Mat、Mesh、Tex 是隐藏的特效辅助目录名称，请使用其他名称。");
            return false;
        }
        const FString Source = NormalizeDirectory(Directory);
        const FString Destination = NormalizeDirectory(FPaths::GetPath(Source) / Name);
        if (!ValidateEmptyDirectoryTree(Source, OutError, Root)) { return false; }
        if (Source.Equals(Destination, ESearchCase::CaseSensitive))
        {
            OutDirectory = Source;
            return true;
        }
        IPlatformFile& Physical = FPlatformFileManager::Get().GetPlatformPhysical();
        if (Physical.DirectoryExists(*Destination) || Physical.FileExists(*Destination))
        {
            OutError = Source.Equals(Destination, ESearchCase::IgnoreCase)
                ? TEXT("暂不支持只修改字母大小写，请使用其他名称。")
                : TEXT("该名称已存在，请使用其他文件夹名称。");
            return false;
        }
        // Windows' physical MoveFile is one non-overwriting directory rename.
        // Do not fall back to copying/deleting or merging an existing directory.
        if (!Physical.MoveFile(*Destination, *Source))
        {
            OutError = TEXT("文件夹重命名失败，请检查网络连接、写入权限及文件夹占用情况。\n")
                + Source + TEXT("\n→ ") + Destination;
            return false;
        }
        OutDirectory = Destination;
        return true;
    }

    // Match CGToolsFolderOrganizer's real-class rules. Other asset types keep
    // their original package paths and are still included in the migration.
    FString GetOrganizedPackage(UObject* Asset, const FString& RootFolder)
    {
        FString Folder;
        if (Asset->IsA<UMaterialFunctionInterface>())
        {
            Folder = RootFolder / TEXT("M_F");
        }
        else if (Asset->IsA<UMaterialInterface>())
        {
            Folder = RootFolder / TEXT("Mat");
        }
        else if (Asset->IsA<UStaticMesh>() || Asset->IsA<USkeletalMesh>()
            || Asset->IsA<USkeleton>() || Asset->IsA<UPhysicsAsset>())
        {
            Folder = RootFolder / TEXT("Mesh");
        }
        else if (Asset->IsA<UTexture>())
        {
            Folder = RootFolder / TEXT("Tex");
        }
        else if (Asset->IsA<UNiagaraSystem>() || Asset->IsA<UParticleSystem>())
        {
            Folder = RootFolder;
        }
        else
        {
            return Asset->GetOutermost()->GetName();
        }
        return Folder / Asset->GetName();
    }

    struct FPackagePlan
    {
        TStrongObjectPtr<UObject> Asset;
        FString OriginalPackage;
        FString TargetPackage;
        FString Extension;
    };

    bool GatherPlans(
        IAssetRegistry& Registry, FName RootPackage, const FString& RootFolder,
        TArray<FPackagePlan>& OutPlans, FString& OutError)
    {
        Registry.WaitForCompletion();
        TArray<FName> Pending = { RootPackage };
        TSet<FName> Visited;
        while (!Pending.IsEmpty())
        {
            const FName PackageName = Pending.Pop(EAllowShrinking::No);
            if (Visited.Contains(PackageName))
            {
                continue;
            }
            Visited.Add(PackageName);

            TArray<FAssetData> Assets;
            Registry.GetAssetsByPackageName(PackageName, Assets);
            UObject* Asset = nullptr;
            for (const FAssetData& Data : Assets)
            {
                if (!Data.IsRedirector())
                {
                    Asset = Data.GetAsset();
                    break;
                }
            }
            if (!Asset && !Assets.IsEmpty())
            {
                Asset = Assets[0].GetAsset();
            }
            // Existing redirectors keep their paths and migrate with the
            // closure, so pre-existing soft paths remain resolvable.
            if (Asset)
            {
                UPackage* Package = Asset->GetOutermost();
                if (Package->IsDirty()
                    && !UEditorLoadingAndSavingUtils::SavePackages({ Package }, true))
                {
                    OutError = FString::Printf(TEXT("无法保存资产包：%s\n尚未整理或迁移，请检查写入权限和源代码管理状态。"), *PackageName.ToString());
                    return false;
                }
                FPackagePlan Plan;
                Plan.Asset = TStrongObjectPtr<UObject>(Asset);
                Plan.OriginalPackage = PackageName.ToString();
                Plan.TargetPackage = GetOrganizedPackage(Asset, RootFolder);
                Plan.Extension = Package->HasAnyPackageFlags(PKG_ContainsMap)
                    ? FPackageName::GetMapPackageExtension() : FPackageName::GetAssetPackageExtension();
                // Save events update dependencies asynchronously. Force the
                // on-disk graph current before following this package's edges.
                Registry.ScanModifiedAssetFiles({
                    FPackageName::LongPackageNameToFilename(Plan.OriginalPackage, Plan.Extension)
                });
                OutPlans.Add(MoveTemp(Plan));
            }
            else
            {
                OutError = FString::Printf(TEXT("无法读取特效依赖包：%s\n尚未整理或迁移，请先修复缺失依赖。"), *PackageName.ToString());
                return false;
            }

            TArray<FName> Dependencies;
            Registry.GetDependencies(PackageName, Dependencies);
            for (const FName Dependency : Dependencies)
            {
                if (Dependency.ToString().StartsWith(TEXT("/Game/")) && !Visited.Contains(Dependency))
                {
                    Pending.Add(Dependency);
                }
            }
        }
        return !OutPlans.IsEmpty();
    }

    bool ValidatePackageTargets(const TArray<FPackagePlan>& Plans, FString& OutError)
    {
        TSet<FString> TargetPackages;
        TArray<FString> Conflicts;
        for (const FPackagePlan& Plan : Plans)
        {
            const FString Key = Plan.TargetPackage.ToLower();
            if (TargetPackages.Contains(Key))
            {
                Conflicts.AddUnique(Plan.TargetPackage + TEXT("（多个依赖整理到同一位置）"));
            }
            TargetPackages.Add(Key);
        }
        if (Conflicts.IsEmpty())
        {
            return true;
        }
        Conflicts.Sort();
        const int32 Total = Conflicts.Num();
        if (Conflicts.Num() > 12)
        {
            Conflicts.SetNum(12);
            Conflicts.Add(FString::Printf(TEXT("另有 %d 项冲突"), Total - 12));
        }
        OutError = FString(TEXT("多个源资产整理后会占用同一个目标包，无法确定应发布哪一个。\n请先调整源资产名称后重试：\n\n"))
            + FString::Join(Conflicts, TEXT("\n"));
        return false;
    }

    void CacheEffectThumbnail(UObject* Source, UObject* Copy)
    {
        if (!Source || !Copy || (!Source->IsA<UNiagaraSystem>() && !Source->IsA<UParticleSystem>()))
        {
            return;
        }
        FObjectThumbnail Thumbnail;
        if (!ThumbnailTools::LoadThumbnailFromPackage(FAssetData(Source), Thumbnail)
            || Thumbnail.IsEmpty() || !Thumbnail.HasValidImageData())
        {
            // Niagara and Cascade can have an internal preview texture without
            // any FObjectThumbnail table. Read its source pixels without a GPU render.
            UTexture2D* Texture = Source->IsA<UNiagaraSystem>()
                ? CastChecked<UNiagaraSystem>(Source)->ThumbnailImage
                : CastChecked<UParticleSystem>(Source)->ThumbnailImage;
            FImage Image;
            if (Texture && Texture->Source.GetMipImage(Image, 0))
            {
                FImage SmallImage;
                Image.ResizeTo(SmallImage, 256, 256, ERawImageFormat::BGRA8, EGammaSpace::sRGB);
                Thumbnail.SetImage(MoveTemp(SmallImage));
            }
        }
        if (!Thumbnail.IsEmpty() && Thumbnail.HasValidImageData())
        {
            Thumbnail.SetCreatedAfterCustomThumbsEnabled();
            // SavePackage only writes entries keyed by the COPY's full name.
            ThumbnailTools::CacheThumbnail(Copy->GetFullName(), &Thumbnail, Copy->GetOutermost());
        }
    }

    bool SaveOrganizedCopies(const TArray<FPackagePlan>& Plans, const FString& Mount,
        TArray<UPackage*>& OutPackages, FString& OutError)
    {
        FLinkerInstancingContext Context(true);
        TArray<TStrongObjectPtr<UPackage>> CopyReferences;
        for (const FPackagePlan& Plan : Plans)
        {
            Context.AddPackageMapping(FName(*Plan.OriginalPackage), FName(*(Mount + Plan.TargetPackage.Mid(6))));
        }
        // Prepare all linkers before loading exports, including cyclic imports.
        // Package instancing remaps hard and soft paths only in the copies.
        for (const FPackagePlan& Plan : Plans)
        {
            UPackage* Copy = CreatePackage(*(Mount + Plan.TargetPackage.Mid(6)));
            OutPackages.Add(Copy);
            CopyReferences.Emplace(Copy);
            if (!LoadPackage(Copy, *Plan.OriginalPackage, LOAD_Verify | LOAD_NoVerify, nullptr, &Context))
            {
                OutError = TEXT("无法建立发布副本：") + Plan.OriginalPackage;
                return false;
            }
            Copy->SetPackageFlags(PKG_NewlyCreated);
        }
        for (int32 Index = 0; Index < Plans.Num(); ++Index)
        {
            if (!LoadPackage(OutPackages[Index], *Plans[Index].OriginalPackage, LOAD_None, nullptr, &Context))
            {
                OutError = TEXT("无法加载发布副本：") + Plans[Index].OriginalPackage;
                return false;
            }
        }
        for (int32 Index = 0; Index < Plans.Num(); ++Index)
        {
            UPackage* Copy = OutPackages[Index];
            UObject* Asset = FindObjectFast<UObject>(Copy, Plans[Index].Asset->GetFName());
            CacheEffectThumbnail(Plans[Index].Asset.Get(), Asset);
            const FString Filename = FPackageName::LongPackageNameToFilename(Copy->GetName(), Plans[Index].Extension);
            FSavePackageArgs Args;
            Args.TopLevelFlags = RF_Standalone;
            Args.SaveFlags = SAVE_RehydratePayloads | SAVE_FromAutosave;
            if (!Asset || !IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true)
                || !GEditor->Save(Copy, Asset, *Filename, Args).IsSuccessful())
            {
                OutError = TEXT("无法保存整理后的发布副本：") + Plans[Index].TargetPackage;
                return false;
            }
        }
        return true;
    }

    struct FUploadResult
    {
        bool bSucceeded = false;
        FString Error;
        FString BackupDirectory;
    };

    struct FUploadFile
    {
        FString Relative;
        FString StagedFilename; // Empty for an obsolete package companion.
        FMD5Hash StagedHash;
        bool bExisted = false;
        FMD5Hash OriginalHash;
    };

    struct FUploadPlan
    {
        FString DestinationContent;
        FString TargetFolder;
        TArray<FUploadFile> Files;
        FString Error;

        TArray<FString> GetConflicts() const
        {
            TArray<FString> Conflicts;
            for (const FUploadFile& File : Files)
            {
                if (File.bExisted)
                {
                    Conflicts.Add(File.Relative + (File.StagedFilename.IsEmpty()
                        ? TEXT("（旧包附属文件，将备份后移除）") : TEXT("")));
                }
            }
            return Conflicts;
        }
    };

    FUploadPlan PrepareUpload(const FString& StagedContent, const FString& DestinationContent, const FString& TargetFolder)
    {
        FUploadPlan Plan;
        Plan.DestinationContent = NormalizeDirectory(DestinationContent);
        Plan.TargetFolder = NormalizeDirectory(TargetFolder);
        IFileManager& Files = IFileManager::Get();
        TArray<FString> StagedFiles;
        Files.FindFilesRecursive(StagedFiles, *StagedContent, TEXT("*"), true, false);
        StagedFiles.Sort();
        if (StagedFiles.IsEmpty())
        {
            Plan.Error = TEXT("UE 没有生成任何迁移文件，未写入服务器。");
            return Plan;
        }
        TSet<FString> RelativeKeys;
        TArray<FString> PackageStems;
        for (const FString& File : StagedFiles)
        {
            FString Relative = File;
            const FString Base = NormalizeDirectory(StagedContent) + TEXT("/");
            if (!FPaths::MakePathRelativeTo(Relative, *Base)
                || !FPaths::IsRelative(Relative)
                || !IsDirectoryWithin(Plan.DestinationContent / Relative, Plan.DestinationContent)
                || RelativeKeys.Contains(Relative.ToLower()))
            {
                Plan.Error = TEXT("迁移文件路径无效或重名，未写入服务器：\n") + Relative;
                return Plan;
            }
            RelativeKeys.Add(Relative.ToLower());
            FUploadFile& Entry = Plan.Files.AddDefaulted_GetRef();
            Entry.Relative = Relative;
            Entry.StagedFilename = File;
            Entry.StagedHash = FMD5Hash::HashFile(*File);
            if (!Entry.StagedHash.IsValid())
            {
                Plan.Error = TEXT("无法读取迁移文件，未写入服务器：\n") + File;
                return Plan;
            }
            const FString Extension = FPaths::GetExtension(Relative);
            if (Extension.Equals(TEXT("uasset"), ESearchCase::IgnoreCase)
                || Extension.Equals(TEXT("umap"), ESearchCase::IgnoreCase))
            {
                PackageStems.Add(FPaths::ChangeExtension(Relative, TEXT("")));
            }
        }
        // Old split-package data must not survive when its new primary package
        // becomes self-contained. Track absent companions too to detect races.
        for (const FString& Stem : PackageStems)
        {
            for (const TCHAR* Extension : { TEXT(".uasset"), TEXT(".umap"), TEXT(".uexp"),
                TEXT(".ubulk"), TEXT(".uptnl"), TEXT(".m.ubulk") })
            {
                const FString Relative = Stem + Extension;
                if (!RelativeKeys.Contains(Relative.ToLower()))
                {
                    RelativeKeys.Add(Relative.ToLower());
                    Plan.Files.AddDefaulted_GetRef().Relative = Relative;
                }
            }
        }
        Plan.Files.Sort([](const FUploadFile& A, const FUploadFile& B) { return A.Relative < B.Relative; });
        for (FUploadFile& Entry : Plan.Files)
        {
            const FString Destination = Plan.DestinationContent / Entry.Relative;
            Entry.bExisted = Files.FileExists(*Destination);
            if (Entry.bExisted)
            {
                Entry.OriginalHash = FMD5Hash::HashFile(*Destination);
                if (!Entry.OriginalHash.IsValid())
                {
                    Plan.Error = TEXT("无法读取目标同名文件，未写入服务器：\n") + Destination;
                    return Plan;
                }
            }
        }
        return Plan;
    }

    bool TargetMatchesSnapshot(const FUploadPlan& Plan, FString& OutError)
    {
        for (const FUploadFile& Entry : Plan.Files)
        {
            const FString Destination = Plan.DestinationContent / Entry.Relative;
            if (IFileManager::Get().FileExists(*Destination) != Entry.bExisted
                || (Entry.bExisted && FMD5Hash::HashFile(*Destination) != Entry.OriginalHash))
            {
                OutError = TEXT("确认期间目标文件发生变化，已取消本次上传。请重新发布并确认覆盖列表：\n") + Destination;
                return false;
            }
        }
        return true;
    }

    FUploadResult CommitUpload(const FUploadPlan& Plan, bool bOverwrite)
    {
        FUploadResult Result;
        Result.Error = Plan.Error;
        if (!Result.Error.IsEmpty())
        {
            return Result;
        }
        const TArray<FString> Conflicts = Plan.GetConflicts();
        if (!Conflicts.IsEmpty() && !bOverwrite)
        {
            Result.Error = TEXT("目标存在同名文件，尚未确认覆盖，未写入任何发布文件。");
            return Result;
        }
        IFileManager& Files = IFileManager::Get();
        const FString History = FPaths::GetPath(Plan.DestinationContent) / TEXT("Saved/CGToolsPublisher");
        // A file handle (rather than file existence) is the lock: a crashed
        // publisher cannot leave a stale lock. Other CGTools uploads retry later.
        Files.MakeDirectory(*History, true);
        TUniquePtr<FArchive> PublishLock(Files.CreateFileWriter(*(History / TEXT("VFXPublish.lock"))));
        if (!PublishLock)
        {
            Result.Error = TEXT("无法锁定目标工程，可能有其他用户正在发布，或目录不可写。请稍后重试：\n") + History;
            return Result;
        }
        if (!TargetMatchesSnapshot(Plan, Result.Error))
        {
            return Result;
        }
        const FString UploadId = FGuid::NewGuid().ToString(EGuidFormats::Digits);
        const auto TemporaryName = [&UploadId](const FString& Destination)
        {
            return Destination + TEXT(".cgtools_") + UploadId + TEXT(".tmp");
        };
        TArray<FString> TemporaryFiles;
        ON_SCOPE_EXIT
        {
            for (const FString& Temporary : TemporaryFiles)
            {
                if (Files.FileExists(*Temporary) && !Files.Delete(*Temporary, false, false, true))
                {
                    UE_LOG(LogCGToolsVfxPublisher, Warning, TEXT("Upload temporary file could not be removed: %s"), *Temporary);
                }
            }
        };
        // Upload and verify every new file before touching any final file.
        for (const FUploadFile& Entry : Plan.Files)
        {
            if (Entry.StagedFilename.IsEmpty())
            {
                continue;
            }
            const FString Destination = Plan.DestinationContent / Entry.Relative;
            const FString Temporary = TemporaryName(Destination);
            TemporaryFiles.Add(Temporary);
            if (!Files.MakeDirectory(*FPaths::GetPath(Destination), true)
                || Files.Copy(*Temporary, *Entry.StagedFilename, false, false) != COPY_OK
                || FMD5Hash::HashFile(*Temporary) != Entry.StagedHash)
            {
                Result.Error = FString::Printf(TEXT("服务器上传失败：\n%s"), *Destination);
                return Result;
            }
        }
        if (!TargetMatchesSnapshot(Plan, Result.Error))
        {
            return Result;
        }
        if (!Conflicts.IsEmpty())
        {
            Result.BackupDirectory = History / TEXT("VFXBackups")
                / (FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S_")) + UploadId);
            FString Manifest = TEXT("CGTools VFX publish backup\nTarget Content: ") + Plan.DestinationContent
                + TEXT("\nOriginal files are under Content/ using their original relative paths.\n\n");
            for (const FUploadFile& Entry : Plan.Files)
            {
                Manifest += (Entry.bExisted ? TEXT("BACKUP ") : TEXT("NEW ")) + Entry.Relative + TEXT("\n");
                if (Entry.bExisted)
                {
                    const FString Backup = Result.BackupDirectory / TEXT("Content") / Entry.Relative;
                    if (!Files.MakeDirectory(*FPaths::GetPath(Backup), true)
                        || Files.Copy(*Backup, *(Plan.DestinationContent / Entry.Relative), false, false) != COPY_OK
                        || FMD5Hash::HashFile(*Backup) != Entry.OriginalHash)
                    {
                        Result.Error = TEXT("原文件备份失败，未替换任何发布文件：\n") + Backup;
                        return Result;
                    }
                }
            }
            if (!FFileHelper::SaveStringToFile(Manifest, *(Result.BackupDirectory / TEXT("manifest.txt"))))
            {
                Result.Error = TEXT("无法保存备份清单，未替换任何发布文件：\n") + Result.BackupDirectory;
                return Result;
            }
        }
        // Backup copying can be slow on a share. Recheck the exact snapshot the
        // user approved after that work, before replacing the first final file.
        if (!TargetMatchesSnapshot(Plan, Result.Error))
        {
            return Result;
        }
        TArray<int32> Touched;
        for (int32 Index = 0; Index < Plan.Files.Num(); ++Index)
        {
            const FUploadFile& Entry = Plan.Files[Index];
            if (!Entry.bExisted && Entry.StagedFilename.IsEmpty())
            {
                continue;
            }
            const FString Destination = Plan.DestinationContent / Entry.Relative;
            // Mark old files before attempting removal so failure always
            // restores any original content that was already removed.
            if (Entry.bExisted)
            {
                Touched.Add(Index);
                if (!Files.Delete(*Destination, true, false, true))
                {
                    Result.Error = TEXT("无法替换目标文件（可能被占用或没有权限）：\n") + Destination;
                    break;
                }
            }
            if (!Entry.StagedFilename.IsEmpty())
            {
                if (!Entry.bExisted)
                {
                    Touched.Add(Index);
                }
                if (!Files.Move(*Destination, *TemporaryName(Destination), false, false, false, true))
                {
                    Result.Error = TEXT("无法提交上传文件：\n") + Destination;
                    break;
                }
                if (FMD5Hash::HashFile(*Destination) != Entry.StagedHash)
                {
                    Result.Error = TEXT("上传文件内容校验失败：\n") + Destination;
                    break;
                }
            }
        }
        if (Result.Error.IsEmpty())
        {
            for (const TCHAR* Folder : { TEXT("M_F"), TEXT("Mat"), TEXT("Mesh"), TEXT("Tex") })
            {
                if (!Files.MakeDirectory(*(Plan.TargetFolder / Folder), true))
                {
                    Result.Error = TEXT("无法建立服务器整理目录：\n") + (Plan.TargetFolder / Folder);
                    break;
                }
            }
        }
        if (!Result.Error.IsEmpty())
        {
            TArray<FString> RecoveryFailures;
            for (int32 Index = Touched.Num() - 1; Index >= 0; --Index)
            {
                const FUploadFile& Entry = Plan.Files[Touched[Index]];
                const FString Destination = Plan.DestinationContent / Entry.Relative;
                const bool bExistsNow = Files.FileExists(*Destination);
                const FMD5Hash CurrentHash = bExistsNow ? FMD5Hash::HashFile(*Destination) : FMD5Hash();
                if (Entry.bExisted && bExistsNow && CurrentHash == Entry.OriginalHash)
                {
                    continue;
                }
                // Never delete unexpected concurrent content during recovery.
                if (bExistsNow && (Entry.StagedFilename.IsEmpty() || CurrentHash != Entry.StagedHash))
                {
                    RecoveryFailures.Add(Destination);
                    continue;
                }
                if (bExistsNow && !Files.Delete(*Destination, false, false, true))
                {
                    RecoveryFailures.Add(Destination);
                    continue;
                }
                if (Entry.bExisted)
                {
                    const FString Backup = Result.BackupDirectory / TEXT("Content") / Entry.Relative;
                    if (Files.Copy(*Destination, *Backup, false, false) != COPY_OK
                        || FMD5Hash::HashFile(*Destination) != Entry.OriginalHash)
                    {
                        RecoveryFailures.Add(Destination);
                    }
                }
            }
            Result.Error += RecoveryFailures.IsEmpty()
                ? TEXT("\n\n已恢复本次替换的原文件，并清理本次新增文件。")
                : TEXT("\n\n以下文件未能自动恢复，请使用备份检查：\n") + FString::Join(RecoveryFailures, TEXT("\n"));
            if (!Result.BackupDirectory.IsEmpty())
            {
                Result.Error += TEXT("\n\n原文件备份：\n") + Result.BackupDirectory;
            }
            return Result;
        }
        Result.bSucceeded = true;
        return Result;
    }

#if WITH_DEV_AUTOMATION_TESTS
    FUploadResult UploadStagedContent(const FString& StagedContent, const FString& DestinationContent,
        const FString& TargetFolder, bool bOverwrite = false)
    {
        return CommitUpload(PrepareUpload(StagedContent, DestinationContent, TargetFolder), bOverwrite);
    }
#endif

    bool ConfirmVfxOverwrite(const FString& AssetName, const FString& Destination,
        const TArray<FString>& Conflicts, const TSharedPtr<SWindow>& Parent)
    {
        bool bOverwrite = false;
        const TSharedRef<SWindow> Dialog = SNew(SWindow)
            .Title(LOCTEXT("OverwriteVfxTitle", "目标存在同名资产"))
            .ClientSize(FVector2D(720.0f, 480.0f))
            .SupportsMinimize(false).SupportsMaximize(false);
        const TWeakPtr<SWindow> WeakDialog = Dialog;
        TSharedPtr<SButton> CancelButton;
        Dialog->SetContent(
            SNew(SBorder).Padding(16.0f)
            [
                SNew(SVerticalBox)
                + SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 12)
                [
                    SNew(STextBlock).AutoWrapText(true)
                    .Text(FText::FromString(FString::Printf(
                        TEXT("特效：%s\n发布目录：%s\n\n目标已有以下 %d 个文件，是否覆盖发布？"),
                        *AssetName, *Destination, Conflicts.Num())))
                ]
                + SVerticalBox::Slot().FillHeight(1.0f)
                [
                    SNew(SBorder).Padding(8.0f)
                    [
                        SNew(SScrollBox)
                        + SScrollBox::Slot()
                        [ SNew(STextBlock).AutoWrapText(true).Text(FText::FromString(FString::Join(Conflicts, TEXT("\n")))) ]
                    ]
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 12, 0, 12)
                [
                    SNew(STextBlock).AutoWrapText(true)
                    .Text(LOCTEXT("OverwriteVfxScope", "覆盖范围包含同名特效和依赖文件（如材质、贴图）。旧文件会先备份，未参与本次发布的其他资产会保留。"))
                ]
                + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right)
                [
                    SNew(SHorizontalBox)
                    + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 12, 0)
                    [
                        SNew(SButton).Text(LOCTEXT("OverwriteVfx", "覆盖发布"))
                        .OnClicked_Lambda([&bOverwrite, WeakDialog]()
                        {
                            bOverwrite = true;
                            if (const TSharedPtr<SWindow> Window = WeakDialog.Pin())
                            {
                                Window->RequestDestroyWindow();
                            }
                            return FReply::Handled();
                        })
                    ]
                    + SHorizontalBox::Slot().AutoWidth()
                    [
                        SAssignNew(CancelButton, SButton).Text(LOCTEXT("CancelOverwriteVfx", "取消"))
                        .OnClicked_Lambda([WeakDialog]()
                        {
                            if (const TSharedPtr<SWindow> Window = WeakDialog.Pin())
                            {
                                Window->RequestDestroyWindow();
                            }
                            return FReply::Handled();
                        })
                    ]
                ]
            ]);
        Dialog->SetWidgetToFocusOnActivate(CancelButton);
        FSlateApplication::Get().AddModalWindow(Dialog, Parent, false);
        return bOverwrite;
    }

    bool PublishEffect(const FAssetData& AssetData, const FString& Directory, FString& OutError,
        const FString& TargetProjectDirectory = VfxProjectDirectory,
        const TFunction<bool(const TArray<FString>&)>& ConfirmOverwrite = {}, FString* OutBackupDirectory = nullptr,
        const TFunction<bool(const FString&, const FString&, CGToolsPublisher::FPublishFileResult&)>& ReviewFiles = {}, bool* OutPartial = nullptr)
    {
        OutError.Reset();
        if (OutBackupDirectory)
        {
            OutBackupDirectory->Reset();
        }
        const FString DestinationContent = TargetProjectDirectory / TEXT("Content");
        FString RootFolder;
        IPlatformFile& Files = FPlatformFileManager::Get().GetPlatformFile();
        if (!GEditor || !GetTargetPackageFolder(Directory, RootFolder, DestinationContent)
            || !Files.DirectoryExists(*Directory))
        {
            OutError = TEXT("目标目录不可用或不属于 VFX 工程的 Content/VFX，请刷新并重新选择目录。");
            return false;
        }
        if (NormalizeDirectory(FPaths::ProjectContentDir()).Equals(
            NormalizeDirectory(DestinationContent), ESearchCase::IgnoreCase))
        {
            OutError = TEXT("当前已经打开目标 VFX 工程，请直接使用【整理特效文件夹】；不能向当前工程自身迁移。");
            return false;
        }
        TStrongObjectPtr<UObject> RootAsset(AssetData.GetAsset());
        if (!RootAsset.IsValid() || !CGToolsVfxPublisher::IsEffectAsset(AssetData)
            || !AssetData.PackageName.ToString().StartsWith(TEXT("/Game/")))
        {
            OutError = TEXT("请选择一个当前工程 /Game 下的 Niagara 系统或 Cascade 粒子系统。");
            return false;
        }

        FScopedSlowTask Progress(100.0f, LOCTEXT("PublishingEffect", "正在整理迁移特效…"));
        Progress.MakeDialog(false);
        Progress.EnterProgressFrame(10.0f, LOCTEXT("ScanDependencies", "正在保存并递归扫描特效依赖…"));
        // Native migration also saves dirty maps/content. Save first so the
        // registry dependency graph includes unsaved edits before planning.
        if (!FEditorFileUtils::SaveDirtyPackages(false, true, true))
        {
            OutError = TEXT("当前工程内容保存失败，尚未整理或迁移，请检查写入权限和源代码管理状态。");
            return false;
        }
        IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
        IAssetTools& AssetTools = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools")).Get();
        TArray<FPackagePlan> Plans;
        if (!GatherPlans(Registry, AssetData.PackageName, RootFolder, Plans, OutError)
            || !ValidatePackageTargets(Plans, OutError))
        {
            return false;
        }

        const FString StagingBase = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/VFX"));
        const FString StagingId = FGuid::NewGuid().ToString(EGuidFormats::Digits);
        const FString StagingRoot = StagingBase / StagingId;
        const FString CopiesContent = StagingRoot / TEXT("Copies/Content");
        const FString StagedContent = StagingRoot / TEXT("Content");
        const FString CopiesMount = TEXT("/CGToolsVfxCopy_") + StagingId + TEXT("/");
        TArray<UPackage*> CopyPackages;
        TArray<TStrongObjectPtr<UPackage>> CopyReferences;
        bool bCopiesMounted = false;
        ON_SCOPE_EXIT
        {
            if (bCopiesMounted)
            {
                CopyReferences.Reset();
                FText UnloadError;
                if (!UPackageTools::UnloadPackages(CopyPackages, UnloadError, true))
                {
                    UE_LOG(LogCGToolsVfxPublisher, Warning, TEXT("Temporary copy cleanup: %s"), *UnloadError.ToString());
                }
                FPackageName::UnRegisterMountPoint(CopiesMount, CopiesContent + TEXT("/"));
            }
            // Only this operation's GUID directory may be recursively removed.
            if (IsDirectoryWithin(StagingRoot, StagingBase) && StagingRoot != StagingBase)
            {
                Files.DeleteDirectoryRecursively(*StagingRoot);
            }
        };
        if (!Files.CreateDirectoryTree(*StagedContent) || !Files.CreateDirectoryTree(*CopiesContent)
            || !FFileHelper::SaveStringToFile(
                TEXT("{\"FileVersion\":3,\"EngineAssociation\":\"5.7\",\"Plugins\":[{\"Name\":\"Niagara\",\"Enabled\":true}]}"),
                *(StagingRoot / TEXT("VfxPublish.uproject"))))
        {
            OutError = TEXT("无法建立本地迁移暂存工程，尚未写入服务器。");
            return false;
        }
        FPackageName::RegisterMountPoint(CopiesMount, CopiesContent + TEXT("/"));
        bCopiesMounted = true;
        Progress.EnterProgressFrame(25.0f, LOCTEXT("OrganizeCopies", "正在整理独立发布副本及其引用…"));
        if (!SaveOrganizedCopies(Plans, CopiesMount, CopyPackages, OutError))
        {
            return false;
        }
        for (UPackage* Package : CopyPackages)
        {
            CopyReferences.Emplace(Package);
        }
        TArray<FName> PackagesToMigrate;
        TArray<FString> CopyFiles;
        TArray<FString> RepairFolders;
        for (int32 Index = 0; Index < Plans.Num(); ++Index)
        {
            PackagesToMigrate.Add(CopyPackages[Index]->GetFName());
            CopyFiles.Add(FPackageName::LongPackageNameToFilename(CopyPackages[Index]->GetName(), Plans[Index].Extension));
            RepairFolders.AddUnique(FPackageName::GetLongPackagePath(Plans[Index].OriginalPackage));
        }
        Registry.ScanModifiedAssetFiles(CopyFiles);
        Progress.EnterProgressFrame(25.0f, LOCTEXT("MigrateToStaging", "正在原生迁移特效与完整工程内依赖到本地暂存目录…"));
        FMigrationOptions Options;
        Options.bPrompt = false;
        // The entire /Game dependency closure was copied above. Native
        // migration remaps our temporary mount to the target /Game paths.
        Options.bIgnoreDependencies = true;
        // UE 5.7 interprets Cancel as canceling the entire unattended
        // migration even when no conflicts exist. Staging is unique; Skip
        // prevents overwrites and the package verification detects any skip.
        Options.AssetConflict = EAssetMigrationConflict::Skip;
        // MigratePackages defers its work to a discovery-dialog callback when
        // the registry is still scanning. Finish saves/scans first so staging
        // verification and cleanup cannot race that deferred migration.
        if (!FEditorFileUtils::SaveDirtyPackages(false, true, true))
        {
            OutError = TEXT("迁移前保存未完成，尚未写入服务器。源资产位置未改变。");
            return false;
        }
        Registry.WaitForCompletion();
        AssetTools.MigratePackages(PackagesToMigrate, StagedContent, Options);

        Progress.EnterProgressFrame(5.0f, LOCTEXT("RestoreAssetDisplay", "正在恢复当前工程资产显示…"));
        FString RepairMessage;
        if (!CGToolsPublisher::RepairSourceAssetDisplay(RepairFolders, RepairMessage))
        {
            UE_LOG(LogCGToolsVfxPublisher, Warning, TEXT("Source asset display repair: %s"), *RepairMessage);
            Registry.ScanPathsSynchronous(RepairFolders, true);
        }
        for (const FPackagePlan& Plan : Plans)
        {
            const FString Expected = StagedContent / (Plan.TargetPackage.Mid(6) + Plan.Extension);
            if (!Files.FileExists(*Expected) || Files.FileSize(*Expected) <= 0)
            {
                OutError = TEXT("UE 迁移未生成完整依赖，未写入服务器：\n") + Expected
                    + TEXT("\n\n源资产位置未改变，请检查 Output Log 后重试。");
                return false;
            }
        }

        bool bComplete = true;
        if (ReviewFiles)
        {
            CGToolsPublisher::FPublishFileResult FileResult;
            if (!ReviewFiles(StagedContent, DestinationContent, FileResult))
            { OutError = FileResult.Error; return false; }
            bComplete = FileResult.bComplete;
            if (OutPartial) { *OutPartial = !bComplete; }
            if (OutBackupDirectory) { *OutBackupDirectory = FileResult.History; }
        }
        else
        {
            Progress.EnterProgressFrame(5.0f, LOCTEXT("CheckServerFiles", "正在检查服务器同名文件…"));
            TFuture<FUploadPlan> Preparation = Async(EAsyncExecution::ThreadPool,
                [StagedContent, Directory, DestinationContent]() { return PrepareUpload(StagedContent, DestinationContent, Directory); });
            while (!Preparation.IsReady())
            {
                Progress.ForceRefresh();
                FPlatformProcess::Sleep(0.03f);
            }
            const FUploadPlan UploadPlan = Preparation.Get();
            if (!UploadPlan.Error.IsEmpty())
            {
                OutError = UploadPlan.Error;
                return false;
            }
            const TArray<FString> Conflicts = UploadPlan.GetConflicts();
            if (!Conflicts.IsEmpty() && (!ConfirmOverwrite || !ConfirmOverwrite(Conflicts)))
            {
                // An empty error signals user cancellation; stay on this asset.
                return false;
            }
            Progress.EnterProgressFrame(0.0f, LOCTEXT("UploadToServer", "正在备份、上传服务器并校验文件…"));
            TFuture<FUploadResult> Upload = Async(EAsyncExecution::ThreadPool,
                [&UploadPlan, bOverwrite = !Conflicts.IsEmpty()]() { return CommitUpload(UploadPlan, bOverwrite); });
            while (!Upload.IsReady())
            {
                Progress.ForceRefresh();
                FPlatformProcess::Sleep(0.03f);
            }
            const FUploadResult Result = Upload.Get();
            if (OutBackupDirectory)
            {
                *OutBackupDirectory = Result.BackupDirectory;
            }
            if (!Result.bSucceeded)
            {
                OutError = Result.Error + TEXT("\n\n源特效及依赖位置未改变，修复问题后可再次发布。");
                return false;
            }
        }
        if (!bComplete) { return true; }
        Progress.EnterProgressFrame(30.0f, LOCTEXT("VfxPublishFinished", "特效发布完成。"));
        FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser")).Get()
            .SyncBrowserToAssets({ FAssetData(RootAsset.Get()) });
        UE_LOG(LogCGToolsVfxPublisher, Display, TEXT("Published %s and %d project packages to %s"),
            *RootAsset->GetPathName(), Plans.Num(), *Directory);
        return true;
    }
}

void SCGToolsVfxPublisherWindow::Construct(const FArguments& InArgs)
{
    AssetData = InArgs._AssetData;
    DialogState = InArgs._DialogState.IsValid() ? InArgs._DialogState : MakeShared<FCGToolsPublisherDialogState>();
    ChildSlot
    [
        SNew(SBorder)
        .Padding(16.0f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 24, 0)
            [ SNew(SCGToolsPublisherAssetPreview).AssetData(AssetData) ]
            + SHorizontalBox::Slot().FillWidth(1.0f)
            [
                SNew(SVerticalBox)
                + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0.0f, 0.0f, 0.0f, 10.0f)
                [
                    SNew(SHorizontalBox)
                    + SHorizontalBox::Slot().AutoWidth().Padding(0.0f, 0.0f, 10.0f, 0.0f)
                    [
                        SNew(SButton).Text(LOCTEXT("NewVfxFolder", "新建文件夹"))
                        .ToolTipText(LOCTEXT("NewVfxFolderTooltip", "在所选目录下新建文件夹；未选择目录时，在 VFX 下新建一级目录。"))
                        .IsEnabled(this, &SCGToolsVfxPublisherWindow::CanCreateFolder)
                        .OnClicked(this, &SCGToolsVfxPublisherWindow::OnNewFolder)
                    ]
                    + SHorizontalBox::Slot().AutoWidth()
                    [
                        SNew(SButton).Text(LOCTEXT("RefreshDirectories", "刷新"))
                        .IsEnabled_Lambda([this]() { return !bPublishing; })
                        .OnClicked_Lambda([this]() { RefreshDirectoryTree(); return FReply::Handled(); })
                    ]
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(STextBlock)
                    .Text_Lambda([this]() { return FText::FromString(DirectoryError); })
                    .Visibility_Lambda([this]() { return DirectoryError.IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; })
                    .AutoWrapText(true)
                ]
                + SVerticalBox::Slot().FillHeight(1.0f)
                [
                    SAssignNew(DirectoryBrowser, SCGToolsVfxDestinationBrowser)
                    .RootDirectory(VfxRootDirectory)
                    .OnFolderSelected_Lambda([this](const FString& Directory) { SelectedDirectory = Directory; DirectoryError.Reset(); })
                    .OnFolderDoubleClicked(this, &SCGToolsVfxPublisherWindow::OnDirectoryDoubleClicked)
                    .IsEnabled_Lambda([this]() { return !bPublishing; })
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0.0f, 12.0f, 0.0f, 0.0f).HAlign(HAlign_Right)
                [
                    SNew(SHorizontalBox)
                    .Visibility(DialogState->bEmbedded ? EVisibility::Collapsed : EVisibility::Visible)
                    + SHorizontalBox::Slot().AutoWidth().Padding(0.0f, 0.0f, 10.0f, 0.0f)
                    [
                        SNew(SButton).Text(LOCTEXT("SkipCurrent", "跳过当前"))
                        .Visibility(DialogState->IsBatch() ? EVisibility::Visible : EVisibility::Collapsed)
                        .IsEnabled_Lambda([this]() { return !bPublishing; })
                        .OnClicked(this, &SCGToolsVfxPublisherWindow::OnSkip)
                    ]
                    + SHorizontalBox::Slot().AutoWidth().Padding(0.0f, 0.0f, 10.0f, 0.0f)
                    [
                        SNew(SButton).Text(LOCTEXT("ConfirmVfxDirectory", "确定"))
                        .IsEnabled(this, &SCGToolsVfxPublisherWindow::CanConfirm)
                        .OnClicked(this, &SCGToolsVfxPublisherWindow::OnConfirm)
                    ]
                    + SHorizontalBox::Slot().AutoWidth()
                    [
                        SNew(SButton).Text(DialogState->IsBatch() ? LOCTEXT("EndBatch", "结束批量发布") : LOCTEXT("CancelVfxDirectory", "取消"))
                        .IsEnabled_Lambda([this]() { return !bPublishing; })
                        .OnClicked(this, &SCGToolsVfxPublisherWindow::OnCancel)
                    ]
                ]
            ]
        ]
    ];
    RefreshDirectoryTree();
}

void SCGToolsVfxPublisherWindow::RefreshDirectoryTree()
{
    if (bPublishing) { return; }
    DirectoryError.Reset();
    DirectoryBrowser->Refresh(SelectedDirectory);
}

void SCGToolsVfxPublisherWindow::OnDirectoryDoubleClicked(const FString& Directory)
{
    if (bPublishing) { return; }
    FString Error;
    if (!ValidateEmptyDirectoryTree(Directory, Error))
    {
        FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Error),
            LOCTEXT("RenameVfxFolderTitle", "重命名文件夹"));
        return;
    }
    ShowFolderNameDialog(Directory, true);
}

bool SCGToolsVfxPublisherWindow::CanConfirm() const
{
    FString PackageFolder;
    return !bPublishing && DirectoryError.IsEmpty() && !SelectedDirectory.IsEmpty()
        && GetTargetPackageFolder(SelectedDirectory, PackageFolder);
}

FReply SCGToolsVfxPublisherWindow::OnNewFolder()
{
    if (!CanCreateFolder())
    {
        return FReply::Handled();
    }
    ShowFolderNameDialog(SelectedDirectory.IsEmpty() ? VfxRootDirectory : SelectedDirectory, false);
    return FReply::Handled();
}

void SCGToolsVfxPublisherWindow::ShowFolderNameDialog(const FString& Directory, bool bRename)
{
    const TSharedRef<FString> Name = MakeShared<FString>(bRename ? FPaths::GetCleanFilename(Directory) : FString());
    const TSharedRef<FString> Error = MakeShared<FString>();
    const TSharedRef<SWindow> Dialog = SNew(SWindow)
        .Title(bRename ? LOCTEXT("RenameVfxFolderTitle", "重命名文件夹") : LOCTEXT("NewVfxFolderTitle", "新建文件夹"))
        .ClientSize(FVector2D(420.0f, 140.0f))
        .SizingRule(ESizingRule::Autosized)
        .SupportsMinimize(false).SupportsMaximize(false);
    const TWeakPtr<SWindow> WeakDialog = Dialog;
    const auto ApplyName = [this, Directory, bRename, Name, Error, WeakDialog]()
    {
        FString UpdatedDirectory;
        const bool bSucceeded = bRename
            ? RenameEmptyDirectory(Directory, *Name, UpdatedDirectory, *Error)
            : CreateChildDirectory(Directory, *Name, UpdatedDirectory, *Error);
        if (bSucceeded)
        {
            SelectedDirectory = UpdatedDirectory;
            RefreshDirectoryTree();
            if (const TSharedPtr<SWindow> Window = WeakDialog.Pin())
            {
                Window->RequestDestroyWindow();
            }
        }
        return FReply::Handled();
    };
    TSharedPtr<SEditableTextBox> NameInput;
    Dialog->SetContent(
        SNew(SBorder).Padding(16.0f)
        [
            SNew(SVerticalBox)
            + SVerticalBox::Slot().AutoHeight()
            [
                SAssignNew(NameInput, SEditableTextBox)
                .MinDesiredWidth(360.0f)
                .Text(FText::FromString(*Name))
                .SelectAllTextWhenFocused(true)
                .HintText(LOCTEXT("NewVfxFolderName", "文件夹名称"))
                .OnTextChanged_Lambda([Name, Error](const FText& Text) { *Name = Text.ToString(); Error->Reset(); })
                .OnTextCommitted_Lambda([ApplyName](const FText&, ETextCommit::Type Commit)
                {
                    if (Commit == ETextCommit::OnEnter)
                    {
                        ApplyName();
                    }
                })
            ]
            + SVerticalBox::Slot().AutoHeight().Padding(0.0f, 8.0f)
            [
                SNew(STextBlock).Text_Lambda([Error]() { return FText::FromString(*Error); })
                .AutoWrapText(true)
                .Visibility_Lambda([Error]() { return Error->IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; })
            ]
            + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right)
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth().Padding(0.0f, 0.0f, 10.0f, 0.0f)
                [
                    SNew(SButton).Text(LOCTEXT("CreateVfxFolder", "确定")).OnClicked_Lambda(ApplyName)
                ]
                + SHorizontalBox::Slot().AutoWidth()
                [
                    SNew(SButton).Text(LOCTEXT("CancelVfxFolder", "取消"))
                    .OnClicked_Lambda([WeakDialog]()
                    {
                        if (const TSharedPtr<SWindow> Window = WeakDialog.Pin())
                        {
                            Window->RequestDestroyWindow();
                        }
                        return FReply::Handled();
                    })
                ]
            ]
        ]);
    Dialog->SetWidgetToFocusOnActivate(NameInput);
    FSlateApplication::Get().AddModalWindow(Dialog, FSlateApplication::Get().FindWidgetWindow(AsShared()), false);
}

bool SCGToolsVfxPublisherWindow::CanCreateFolder() const
{
    return !bPublishing && DirectoryError.IsEmpty() && (SelectedDirectory.IsEmpty() || CanConfirm());
}

FReply SCGToolsVfxPublisherWindow::OnConfirm()
{
    if (!CanConfirm())
    {
        return FReply::Handled();
    }
    const FString Destination = SelectedDirectory;
    FString PackageFolder;
    GetTargetPackageFolder(Destination, PackageFolder);
    const FText Confirmation = FText::FromString(FString::Printf(
        TEXT("是否确定要将该特效整理迁移到以下工程的相对目录下？\n\n特效：%s\n目标工程：%s\n相对目录：Content/%s\n完整目录：%s\n\n"
            "确认后 UE 会保存当前工程未保存的内容，创建独立发布副本并整理到 %s，再通过 UE 原生迁移复制到目标工程。\n"
            "材质函数 → M_F，材质 → Mat，网格/骨骼/物理资产 → Mesh，贴图 → Tex，Niagara/Cascade → 所选目录根部。\n"
            "其他类型依赖保持原包路径；引擎/插件内容保留引用，目标工程需具备对应插件。\n"
            "源特效及依赖的位置和引用关系保持不变。目标存在同名文件时，会再次询问是否覆盖发布。\n\n是否继续？"),
        *AssetData.AssetName.ToString(), *VfxProjectDirectory, *PackageFolder.Mid(6), *Destination, *PackageFolder));
    if (!DialogState->bBatchExecution && FMessageDialog::Open(EAppMsgType::YesNo, Confirmation, LOCTEXT("ConfirmVfxPublishTitle", "确认特效发布")) != EAppReturnType::Yes)
    {
        return FReply::Handled();
    }
    bPublishing = true;
    TGuardValue<bool> DialogPublishingGuard(DialogState->bPublishing, true);
    DialogState->bPartial = false;
    DialogState->Result = ECGToolsPublisherDialogResult::Cancelled;
    DialogState->Error.Reset(); DialogState->Completion.Reset();
    ON_SCOPE_EXIT { bPublishing = false; };
    FString Error, BackupDirectory;
    bool bPartial = false;
    const auto ReviewFiles = [this, &Destination](const FString& Stage, const FString& Target, CGToolsPublisher::FPublishFileResult& Result)
    {
        return CGToolsPublisher::ReviewAndCommitPublishFiles(Stage, Target, GetVfxPublishReviewRoots(Stage),
            VfxProjectDirectory / TEXT("Saved/CGToolsPublisher/VFXBackups"),
            TEXT("特效：") + AssetData.AssetName.ToString() + TEXT("\n目标：") + Destination,
            FSlateApplication::Get().FindWidgetWindow(AsShared()), Result);
    };
    if (!PublishEffect(AssetData, Destination, Error, VfxProjectDirectory, {}, &BackupDirectory, ReviewFiles, &bPartial))
    {
        if (!Error.IsEmpty())
        {
            DialogState->Error = Error;
            if (!DialogState->bBatchExecution) { FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Error), LOCTEXT("VfxPublishFailed", "特效发布未完成")); }
        }
        return FReply::Handled();
    }
    DialogState->bPartial = bPartial;
    DialogState->Completion = (bPartial ? TEXT("特效部分发布，仍有差异文件未选择。\n\n") : TEXT("特效及工程内依赖已整理迁移完成。\n\n")) + Destination
            + (BackupDirectory.IsEmpty() ? FString() : TEXT("\n\n覆盖前的文件备份：\n") + BackupDirectory)
            + TEXT("\n\n在目标 VFX 工程中刷新内容浏览器即可查看。");
    if (!DialogState->bBatchExecution)
    {
        FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(DialogState->Completion), LOCTEXT("VfxPublishSucceeded", "特效发布完成"));
    }
    DialogState->Result = ECGToolsPublisherDialogResult::Published;
    if (!bPartial) { CloseWindow(); }
    return FReply::Handled();
}

FReply SCGToolsVfxPublisherWindow::OnCancel()
{
    if (!bPublishing)
    {
        CloseWindow();
    }
    return FReply::Handled();
}

void SCGToolsVfxPublisherWindow::CloseWindow()
{
    if (DialogState->bEmbedded) { return; }
    if (const TSharedPtr<SWindow> Window = FSlateApplication::Get().FindWidgetWindow(AsShared()))
    {
        FSlateApplication::Get().RequestDestroyWindow(Window.ToSharedRef());
    }
}

FCGToolsPublisherSharedSettings SCGToolsVfxPublisherWindow::GetSharedSettings() const
{
    FCGToolsPublisherSharedSettings Settings;
    Settings.Directory = SelectedDirectory;
    return Settings;
}

void SCGToolsVfxPublisherWindow::ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings)
{
    if (SelectedDirectory != Settings.Directory)
    {
        SelectedDirectory = Settings.Directory;
        RefreshDirectoryTree();
        // Keep the exact shared destination while the tree restores asynchronously.
        // ValidateBatch/PublishEffect check that it still exists; never use a parent fallback.
    }
}

bool SCGToolsVfxPublisherWindow::ValidateBatch(FString& OutDestination, FString& OutError)
{
    OutDestination.Reset();
    OutError = DirectoryError;
    if (!OutError.IsEmpty()) { return false; }
    if (!CanConfirm() || !IFileManager::Get().DirectoryExists(*SelectedDirectory))
    { OutError = TEXT("请选择可访问的特效发布目录。"); return false; }
    if (!CGToolsVfxPublisher::IsEffectAsset(AssetData) || !AssetData.GetAsset())
    { OutError = TEXT("所选特效已失效，请重新选择。"); return false; }
    OutDestination = SelectedDirectory / (AssetData.AssetName.ToString() + TEXT(".uasset"));
    return true;
}

FReply SCGToolsVfxPublisherWindow::OnSkip()
{
    if (!bPublishing && DialogState->IsBatch())
    {
        DialogState->Result = ECGToolsPublisherDialogResult::Skipped;
        CloseWindow();
    }
    return FReply::Handled();
}

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxRulesTest, "CGTools.Publisher.VFX.DirectoryAndAssetRules",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxRulesTest::RunTest(const FString& Parameters)
{
    FString Folder;
    TestTrue(TEXT("VFX root is selectable"), GetTargetPackageFolder(VfxRootDirectory, Folder));
    TestEqual(TEXT("Root maps to /Game/VFX"), Folder, FString(TEXT("/Game/VFX")));
    TestTrue(TEXT("Nested Chinese folder is selectable"),
        GetTargetPackageFolder(TEXT("Y:\\MCCTools\\src\\UE574\\VFX\\Content\\VFX\\Team1\\水"), Folder));
    TestEqual(TEXT("Nested folder retains Unicode and project-relative path"), Folder, FString(TEXT("/Game/VFX/Team1/水")));
    TestFalse(TEXT("Sibling with matching prefix is rejected"), GetTargetPackageFolder(VfxRootDirectory + TEXT("_Other"), Folder));
    TestFalse(TEXT("Parent traversal is rejected"), GetTargetPackageFolder(VfxRootDirectory / TEXT("../Other"), Folder));

    const FString Root = TEXT("/Game/VFX/Team1/水");
    UNiagaraSystem* Niagara = NewObject<UNiagaraSystem>();
    UParticleSystem* Cascade = NewObject<UParticleSystem>();
    TestTrue(TEXT("Niagara enables publishing"), CGToolsVfxPublisher::IsEffectAsset(FAssetData(Niagara)));
    TestTrue(TEXT("Cascade enables publishing"), CGToolsVfxPublisher::IsEffectAsset(FAssetData(Cascade)));
    TestEqual(TEXT("Niagara goes to the chosen root"), GetOrganizedPackage(Niagara, Root), Root / Niagara->GetName());
    TestEqual(TEXT("Cascade goes to the chosen root"), GetOrganizedPackage(Cascade, Root), Root / Cascade->GetName());
    UMaterialFunction* Function = NewObject<UMaterialFunction>();
    UMaterialInstanceConstant* Material = NewObject<UMaterialInstanceConstant>();
    UTexture2D* Texture = NewObject<UTexture2D>();
    USkeleton* Skeleton = NewObject<USkeleton>();
    UPhysicsAsset* Physics = NewObject<UPhysicsAsset>();
    TestEqual(TEXT("Material function bucket"), GetOrganizedPackage(Function, Root), Root / TEXT("M_F") / Function->GetName());
    TestEqual(TEXT("Derived material bucket"), GetOrganizedPackage(Material, Root), Root / TEXT("Mat") / Material->GetName());
    TestEqual(TEXT("Derived texture bucket"), GetOrganizedPackage(Texture, Root), Root / TEXT("Tex") / Texture->GetName());
    TestEqual(TEXT("Skeleton bucket"), GetOrganizedPackage(Skeleton, Root), Root / TEXT("Mesh") / Skeleton->GetName());
    TestEqual(TEXT("Physics asset bucket"), GetOrganizedPackage(Physics, Root), Root / TEXT("Mesh") / Physics->GetName());
    TestFalse(TEXT("Materials do not enable effect publishing"), CGToolsVfxPublisher::IsEffectAsset(FAssetData(Material)));
    UObject* Other = NewObject<UObjectRedirector>();
    TestEqual(TEXT("Unclassified assets keep original package paths"), GetOrganizedPackage(Other, Root), Other->GetOutermost()->GetName());
    TArray<FPackagePlan> DuplicateTargets;
    DuplicateTargets.AddDefaulted_GetRef().TargetPackage = Root / TEXT("Mat/MI_Same");
    DuplicateTargets.AddDefaulted_GetRef().TargetPackage = Root / TEXT("Mat/mi_same");
    FString CollisionError;
    TestFalse(TEXT("Overwrite cannot resolve two source packages mapped to the same target"),
        ValidatePackageTargets(DuplicateTargets, CollisionError));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxUploadTest, "CGTools.Publisher.VFX.UploadAndConflict",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxUploadTest::RunTest(const FString& Parameters)
{
    const FString TestBase = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests"));
    const FString TestRoot = TestBase / FGuid::NewGuid().ToString(EGuidFormats::Digits);
    ON_SCOPE_EXIT
    {
        if (IsDirectoryWithin(TestRoot, TestBase) && TestRoot != TestBase)
        {
            IFileManager::Get().DeleteDirectory(*TestRoot, false, true);
        }
    };
    const FString Stage = TestRoot / TEXT("Stage/Content");
    const FString Server = TestRoot / TEXT("Server/Content");
    const FString RelativeRoot = TEXT("VFX/Team1/水");
    const FString Effect = RelativeRoot / TEXT("NS_Test.uasset");
    const FString Bulk = RelativeRoot / TEXT("Tex/T_Test.ubulk");
    IFileManager& Files = IFileManager::Get();
    Files.MakeDirectory(*(Stage / RelativeRoot / TEXT("Tex")), true);
    Files.MakeDirectory(*(Server / RelativeRoot / TEXT("Tex")), true);
    if (!TestTrue(TEXT("Create staged asset"), FFileHelper::SaveStringToFile(TEXT("asset-data"), *(Stage / Effect)))
        || !TestTrue(TEXT("Create staged sidecar"), FFileHelper::SaveStringToFile(TEXT("bulk-data"), *(Stage / Bulk)))
        || !TestTrue(TEXT("Create existing server asset"), FFileHelper::SaveStringToFile(TEXT("original-data"), *(Server / Effect))))
    {
        return false;
    }
    const FUploadResult Conflict = UploadStagedContent(Stage, Server, Server / RelativeRoot);
    TestFalse(TEXT("Existing asset blocks the complete upload"), Conflict.bSucceeded);
    FString Contents;
    FFileHelper::LoadFileToString(Contents, *(Server / Effect));
    TestEqual(TEXT("Existing content is preserved"), Contents, FString(TEXT("original-data")));
    TestFalse(TEXT("Conflict does not upload sibling files"), Files.FileExists(*(Server / Bulk)));
    Files.Delete(*(Server / Effect));
    const FUploadResult Success = UploadStagedContent(Stage, Server, Server / RelativeRoot);
    TestTrue(TEXT("Upload succeeds after conflict is resolved"), Success.bSucceeded);
    FFileHelper::LoadFileToString(Contents, *(Server / Effect));
    TestEqual(TEXT("Uploaded asset content matches"), Contents, FString(TEXT("asset-data")));
    FFileHelper::LoadFileToString(Contents, *(Server / Bulk));
    TestEqual(TEXT("Sidecar content matches"), Contents, FString(TEXT("bulk-data")));
    for (const TCHAR* Subfolder : { TEXT("M_F"), TEXT("Mat"), TEXT("Mesh"), TEXT("Tex") })
    {
        TestTrue(TEXT("All organizer folders exist"), Files.DirectoryExists(*(Server / RelativeRoot / Subfolder)));
    }

    // A directory occupying the second file's path fails promotion after the
    // first file was uploaded, exercising cleanup of already committed files.
    const FString RollbackServer = TestRoot / TEXT("Rollback/Content");
    Files.MakeDirectory(*(RollbackServer / Bulk), true);
    const FUploadResult Failure = UploadStagedContent(Stage, RollbackServer, RollbackServer / RelativeRoot);
    TestFalse(TEXT("Failed promotion reports failure"), Failure.bSucceeded);
    TestFalse(TEXT("Previously uploaded asset is rolled back"), Files.FileExists(*(RollbackServer / Effect)));
    TestTrue(TEXT("Existing obstructing directory is preserved"), Files.DirectoryExists(*(RollbackServer / Bulk)));
    TArray<FString> Leftovers;
    Files.FindFilesRecursive(Leftovers, *RollbackServer, TEXT("*.tmp"), true, false);
    TestTrue(TEXT("Failed promotion cleans temporary upload files"), Leftovers.IsEmpty());

    const FString OtherEffect = RelativeRoot / TEXT("NS_Other.uasset");
    const FString ExternalDependency = TEXT("Projects/Shared/CoreParameters.uasset");
    Files.MakeDirectory(*(Stage / TEXT("Projects/Shared")), true);
    TestTrue(TEXT("Create unrelated server effect"), FFileHelper::SaveStringToFile(TEXT("keep other effect"), *(Server / OtherEffect)));
    TestTrue(TEXT("Create dependency outside the chosen VFX folder"), FFileHelper::SaveStringToFile(TEXT("shared dependency"), *(Stage / ExternalDependency)));
    TestTrue(TEXT("Change the current effect on the server"), FFileHelper::SaveStringToFile(TEXT("older effect"), *(Server / Effect)));
    auto ReviewPlan = CGToolsPublisher::BuildPublishFilePlan(Stage, Server, GetVfxPublishReviewRoots(Stage));
    TestTrue(TEXT("VFX file review compares staged output without errors"), ReviewPlan.Error.IsEmpty());
    TestEqual(TEXT("Only the current effect, sidecar and external dependency are listed"), ReviewPlan.Files.Num(), 3);
    TestFalse(TEXT("Other effects do not appear as missing rows"), ReviewPlan.Files.ContainsByPredicate([](const auto& File)
        { return File->Difference == CGToolsPublisher::EPublishFileDifference::Missing; }));
    TestTrue(TEXT("External dependencies remain in the comparison"), ReviewPlan.Files.ContainsByPredicate([&](const auto& File)
        { return File->Relative == ExternalDependency && File->Difference == CGToolsPublisher::EPublishFileDifference::Added; }));
    ReviewPlan.SelectAll(true);
    const auto Reviewed = CGToolsPublisher::CommitPublishFiles(ReviewPlan, TestRoot / TEXT("Backups"));
    TestTrue(TEXT("The staged effect and external dependency can be completely published"), Reviewed.bSucceeded && Reviewed.bComplete);
    FFileHelper::LoadFileToString(Contents, *(Server / OtherEffect));
    TestEqual(TEXT("An unlisted server-only effect is retained"), Contents, FString(TEXT("keep other effect")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxOverwriteTest, "CGTools.Publisher.VFX.OverwriteAndRecovery",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxOverwriteTest::RunTest(const FString& Parameters)
{
    const FString Base = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests"));
    const FString Root = Base / FGuid::NewGuid().ToString(EGuidFormats::Digits);
    IFileManager& Files = IFileManager::Get();
    ON_SCOPE_EXIT
    {
        if (IsDirectoryWithin(Root, Base) && Root != Base)
        {
            Files.DeleteDirectory(*Root, false, true);
        }
    };
    const FString RelativeRoot = TEXT("VFX/Team1/水");
    const FString Effect = RelativeRoot / TEXT("NS_Test.uasset");
    const FString OldBulk = RelativeRoot / TEXT("NS_Test.ubulk");
    const FString Material = RelativeRoot / TEXT("Mat/MI_Test.uasset");
    const FString Bulk = RelativeRoot / TEXT("Tex/T_Test.ubulk");
    const FString Unrelated = RelativeRoot / TEXT("NS_Unrelated.uasset");
    const FString Stage = Root / TEXT("Stage/Content");
    const FString Server = Root / TEXT("Server/Content");
    const auto Write = [this, &Files](const FString& Path, const FString& Value)
    {
        Files.MakeDirectory(*FPaths::GetPath(Path), true);
        return TestTrue(TEXT("Write local fixture"), FFileHelper::SaveStringToFile(Value, *Path));
    };
    const auto Read = [](const FString& Path)
    {
        FString Value;
        FFileHelper::LoadFileToString(Value, *Path);
        return Value;
    };
    Write(Stage / Effect, TEXT("new-effect"));
    Write(Stage / Material, TEXT("new-material"));
    Write(Stage / Bulk, TEXT("new-bulk"));
    Write(Server / Effect, TEXT("old-effect"));
    Write(Server / OldBulk, TEXT("old-sidecar"));
    Write(Server / Unrelated, TEXT("untouched"));
    const FUploadPlan Approved = PrepareUpload(Stage, Server, Server / RelativeRoot);
    TestTrue(TEXT("Overwrite plan is valid"), Approved.Error.IsEmpty());
    TestEqual(TEXT("Confirmation includes original package and obsolete sidecar"), Approved.GetConflicts().Num(), 2);
    const FUploadResult Rejected = CommitUpload(Approved, false);
    TestFalse(TEXT("Overwrite is opt-in"), Rejected.bSucceeded);
    TestEqual(TEXT("Rejected upload preserves effect"), Read(Server / Effect), FString(TEXT("old-effect")));
    TestFalse(TEXT("Rejected upload does not create a backup"), Files.DirectoryExists(*(Root / TEXT("Server/Saved"))));
    const FUploadResult Replaced = CommitUpload(Approved, true);
    TestTrue(TEXT("Explicit overwrite succeeds"), Replaced.bSucceeded);
    TestEqual(TEXT("Effect is replaced"), Read(Server / Effect), FString(TEXT("new-effect")));
    TestEqual(TEXT("New dependency is uploaded"), Read(Server / Material), FString(TEXT("new-material")));
    TestEqual(TEXT("Unrelated effect is preserved"), Read(Server / Unrelated), FString(TEXT("untouched")));
    TestFalse(TEXT("Obsolete sidecar is removed"), Files.FileExists(*(Server / OldBulk)));
    TestEqual(TEXT("Original package backup is exact"), Read(Replaced.BackupDirectory / TEXT("Content") / Effect), FString(TEXT("old-effect")));
    TestEqual(TEXT("Original sidecar is backed up"), Read(Replaced.BackupDirectory / TEXT("Content") / OldBulk), FString(TEXT("old-sidecar")));
    TestTrue(TEXT("Backup includes recovery manifest"), Files.FileExists(*(Replaced.BackupDirectory / TEXT("manifest.txt"))));

    const FUploadPlan Changed = PrepareUpload(Stage, Server, Server / RelativeRoot);
    Write(Server / Effect, TEXT("other-data")); // Same length: size-only checks cannot detect it.
    const FUploadResult Stale = CommitUpload(Changed, true);
    TestFalse(TEXT("Changed target invalidates confirmation"), Stale.bSucceeded);
    TestEqual(TEXT("Newer content is not overwritten"), Read(Server / Effect), FString(TEXT("other-data")));
    const FString NewConflictServer = Root / TEXT("NewConflict/Content");
    const FUploadPlan NoConflict = PrepareUpload(Stage, NewConflictServer, NewConflictServer / RelativeRoot);
    Write(NewConflictServer / Bulk, TEXT("concurrent"));
    TestFalse(TEXT("A newly appearing conflict cancels the complete upload"), CommitUpload(NoConflict, false).bSucceeded);
    TestFalse(TEXT("New conflict does not partially publish the effect"), Files.FileExists(*(NewConflictServer / Effect)));
    TestEqual(TEXT("Concurrent file is preserved"), Read(NewConflictServer / Bulk), FString(TEXT("concurrent")));

    const FString RollbackServer = Root / TEXT("Rollback/Content");
    Write(RollbackServer / Effect, TEXT("restore-effect"));
    Write(RollbackServer / OldBulk, TEXT("restore-sidecar"));
    // Sorting commits Mat and NS before Tex. This final path is a directory,
    // so its promotion fails after replacement and obsolete-sidecar removal.
    Files.MakeDirectory(*(RollbackServer / Bulk), true);
    const FUploadResult Failed = UploadStagedContent(Stage, RollbackServer, RollbackServer / RelativeRoot, true);
    TestFalse(TEXT("Partial overwrite failure is reported"), Failed.bSucceeded);
    TestEqual(TEXT("Old effect is restored after partial overwrite"), Read(RollbackServer / Effect), FString(TEXT("restore-effect")));
    TestEqual(TEXT("Removed old sidecar is restored"), Read(RollbackServer / OldBulk), FString(TEXT("restore-sidecar")));
    TestFalse(TEXT("Newly committed dependency is removed by rollback"), Files.FileExists(*(RollbackServer / Material)));
    TestTrue(TEXT("Unrelated obstructing directory is preserved"), Files.DirectoryExists(*(RollbackServer / Bulk)));
    TestEqual(TEXT("Backup is retained after rollback"), Read(Failed.BackupDirectory / TEXT("Content") / Effect), FString(TEXT("restore-effect")));
    TArray<FString> Leftovers;
    Files.FindFilesRecursive(Leftovers, *Root, TEXT("*.tmp"), true, false);
    TestTrue(TEXT("All temporary uploads are cleaned"), Leftovers.IsEmpty());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxCreateFolderTest, "CGTools.Publisher.VFX.CreateChildFolder",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxCreateFolderTest::RunTest(const FString& Parameters)
{
    const FString Base = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests"));
    const FString Root = Base / FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString Parent = Root / TEXT("Team1");
    IFileManager& Files = IFileManager::Get();
    ON_SCOPE_EXIT
    {
        if (IsDirectoryWithin(Root, Base) && Root != Base)
        {
            Files.DeleteDirectory(*Root, false, true);
        }
    };
    Files.MakeDirectory(*Parent, true);
    FString Created, Error;
    TestTrue(TEXT("Create a Chinese child under the selected folder"),
        CreateChildDirectory(Parent, TEXT("水花"), Created, Error, Root));
    TestEqual(TEXT("New directory is a direct child"), Created, Parent / TEXT("水花"));
    TestTrue(TEXT("New directory exists on disk"), Files.DirectoryExists(*Created));
    TestFalse(TEXT("Existing folders are not reused"), CreateChildDirectory(Parent, TEXT("水花"), Created, Error, Root));
    TestTrue(TEXT("Create under the root"), CreateChildDirectory(Root, TEXT("Team2"), Created, Error, Root));
    TestFalse(TEXT("Parents outside the tree are rejected"), CreateChildDirectory(Base, TEXT("Outside"), Created, Error, Root));
    TestFalse(TEXT("Missing parent is rejected"), CreateChildDirectory(Root / TEXT("Missing"), TEXT("Child"), Created, Error, Root));
    for (const TCHAR* Invalid : { TEXT(""), TEXT(".."), TEXT("../Outside"), TEXT("A/B"), TEXT("A\\B"), TEXT("Bad:Name"), TEXT("CON"), TEXT("LPT1"), TEXT("Trailing.") })
    {
        TestFalse(TEXT("Invalid folder name is rejected"), CreateChildDirectory(Parent, Invalid, Created, Error, Root));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxRenameFolderTest, "CGTools.Publisher.VFX.RenameEmptyFolderSafely",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxRenameFolderTest::RunTest(const FString& Parameters)
{
    const FString Base = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests"));
    const FString Fixture = Base / FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString Content = Fixture / TEXT("Content");
    const FString Root = Content / TEXT("VFX");
    const FString Parent = Root / TEXT("Team1");
    IFileManager& Files = IFileManager::Get();
    ON_SCOPE_EXIT
    {
        if (IsDirectoryWithin(Fixture, Base) && Fixture != Base)
        {
            Files.DeleteDirectory(*Fixture, false, true);
        }
    };
    const FString Old = Parent / TEXT("Old");
    Files.MakeDirectory(*(Old / TEXT("Child/Deep")), true);
    FString Renamed, Error;
    TestTrue(TEXT("Rename an empty directory tree with a Chinese name"),
        RenameEmptyDirectory(Old, TEXT("水花"), Renamed, Error, Root));
    const FString Expected = Parent / TEXT("水花");
    TestEqual(TEXT("Return the new selection path"), Renamed, Expected);
    TestFalse(TEXT("The old directory no longer exists"), Files.DirectoryExists(*Old));
    TestTrue(TEXT("Nested empty directories are preserved"), Files.DirectoryExists(*(Expected / TEXT("Child/Deep"))));
    FString PackageFolder;
    TestTrue(TEXT("The new selection is a publish destination"), GetTargetPackageFolder(Renamed, PackageFolder, Content));
    TestEqual(TEXT("The publish path uses the new folder name"), PackageFolder, FString(TEXT("/Game/VFX/Team1/水花")));
    TestTrue(TEXT("Unchanged name is a no-op"), RenameEmptyDirectory(Expected, TEXT("水花"), Renamed, Error, Root));

    Files.MakeDirectory(*(Parent / TEXT("Existing")), true);
    TestFalse(TEXT("Existing directories are never overwritten"),
        RenameEmptyDirectory(Expected, TEXT("Existing"), Renamed, Error, Root));
    FFileHelper::SaveStringToFile(TEXT("file collision"), *(Parent / TEXT("ExistingFile")));
    TestFalse(TEXT("Existing files are never overwritten"),
        RenameEmptyDirectory(Expected, TEXT("ExistingFile"), Renamed, Error, Root));
    TestFalse(TEXT("The VFX container cannot be renamed"), RenameEmptyDirectory(Root, TEXT("Other"), Renamed, Error, Root));
    TestFalse(TEXT("Folders outside the VFX root cannot be renamed"),
        RenameEmptyDirectory(Content, TEXT("Other"), Renamed, Error, Root));
    TestFalse(TEXT("Missing folders cannot be renamed"),
        RenameEmptyDirectory(Parent / TEXT("Missing"), TEXT("Other"), Renamed, Error, Root));
    for (const TCHAR* Invalid : { TEXT(""), TEXT(".."), TEXT("../Outside"), TEXT("A/B"), TEXT("A\\B"),
        TEXT("Bad:Name"), TEXT("CON"), TEXT("LPT1"), TEXT("Trailing."), TEXT("Mat"), TEXT("m_f"), TEXT("Mesh"), TEXT("Tex") })
    {
        TestFalse(TEXT("Invalid or hidden destination names are rejected"),
            RenameEmptyDirectory(Expected, Invalid, Renamed, Error, Root));
    }
    TestTrue(TEXT("Rejected renames leave the directory intact"), Files.DirectoryExists(*(Expected / TEXT("Child/Deep"))));

    const FString Filled = Parent / TEXT("Filled");
    const FString Package = Filled / TEXT("Tex/T_Test.uasset");
    Files.MakeDirectory(*FPaths::GetPath(Package), true);
    FFileHelper::SaveStringToFile(TEXT("Do not modify package contents"), *Package);
    TestFalse(TEXT("Files inside hidden dependency folders prevent renaming"),
        RenameEmptyDirectory(Filled, TEXT("Changed"), Renamed, Error, Root));
    TestTrue(TEXT("Failure includes the blocking file location"), Error.Contains(TEXT("T_Test.uasset")));
    FString Contents;
    FFileHelper::LoadFileToString(Contents, *Package);
    TestEqual(TEXT("Existing package contents are preserved"), Contents, FString(TEXT("Do not modify package contents")));
    TestFalse(TEXT("A rejected rename does not create a destination"), Files.DirectoryExists(*(Parent / TEXT("Changed"))));

    const FString Concurrent = Parent / TEXT("Concurrent");
    Files.MakeDirectory(*Concurrent, true);
    TestTrue(TEXT("The directory is initially eligible for the rename dialog"), ValidateEmptyDirectoryTree(Concurrent, Error, Root));
    FFileHelper::SaveStringToFile(TEXT("Added while the dialog was open"), *(Concurrent / TEXT("New.txt")));
    TestFalse(TEXT("Confirmation rechecks files added after opening the dialog"),
        RenameEmptyDirectory(Concurrent, TEXT("Changed"), Renamed, Error, Root));
    TestTrue(TEXT("Files added during the dialog remain in the original location"), Files.FileExists(*(Concurrent / TEXT("New.txt"))));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxMigrationTest, "CGTools.Publisher.VFX.OrganizeMigrateAndReloadReferences",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsVfxMigrationTest::RunTest(const FString& Parameters)
{
    const FString Id = FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString SourceRoot = TEXT("/Game/__CGToolsVfxPublisherTest_") + Id;
    const FString RelativeTarget = TEXT("VFX/__CGToolsVfxPublisherTest_") + Id + TEXT("/水");
    const FString TargetPackageRoot = TEXT("/Game/") + RelativeTarget;
    const FString TestBase = NormalizeDirectory(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests"));
    const FString TestRoot = TestBase / Id;
    const FString TargetProject = TestRoot / TEXT("TargetProject");
    const FString Content = TargetProject / TEXT("Content");
    const FString Mount = TEXT("/CGToolsVfxReload_") + Id + TEXT("/");
    bool bMounted = false;
    ON_SCOPE_EXIT
    {
        if (bMounted)
        {
            FPackageName::UnRegisterMountPoint(Mount, Content + TEXT("/"));
        }
        const FString SourceDirectory = NormalizeDirectory(FPackageName::LongPackageNameToFilename(SourceRoot));
        const FString OrganizedDirectory = NormalizeDirectory(FPackageName::LongPackageNameToFilename(TEXT("/Game/VFX/__CGToolsVfxPublisherTest_") + Id));
        const FString ProjectContent = NormalizeDirectory(FPaths::ProjectContentDir());
        for (const FString& FixtureDirectory : { SourceDirectory, OrganizedDirectory })
        {
            if (IsDirectoryWithin(FixtureDirectory, ProjectContent) && FixtureDirectory != ProjectContent)
            {
                IFileManager::Get().DeleteDirectory(*FixtureDirectory, false, true);
            }
        }
        if (IsDirectoryWithin(TestRoot, TestBase) && TestRoot != TestBase)
        {
            IFileManager::Get().DeleteDirectory(*TestRoot, false, true);
        }
    };
    IFileManager::Get().MakeDirectory(*(Content / RelativeTarget), true);
    UPackage* TexturePackage = CreatePackage(*(SourceRoot / TEXT("T_Test")));
    UTexture2D* Texture = NewObject<UTexture2D>(TexturePackage, TEXT("T_Test"), RF_Public | RF_Standalone);
    const uint8 Pixel[4] = { 255, 255, 255, 255 };
    Texture->Source.Init(1, 1, 1, 1, TSF_BGRA8, Pixel);
    UPackage* MaterialPackage = CreatePackage(*(SourceRoot / TEXT("MI_Test")));
    UMaterialInstanceConstant* Material = NewObject<UMaterialInstanceConstant>(MaterialPackage, TEXT("MI_Test"), RF_Public | RF_Standalone);
    FTextureParameterValue TextureParameter;
    TextureParameter.ParameterInfo = FMaterialParameterInfo(TEXT("TestTexture"));
    TextureParameter.ParameterValue = Texture;
    Material->TextureParameterValues.Add(TextureParameter);
    UPackage* EffectPackage = CreatePackage(*(SourceRoot / TEXT("P_Test")));
    UParticleSystem* Effect = NewObject<UParticleSystem>(EffectPackage, TEXT("P_Test"), RF_Public | RF_Standalone);
    FNamedEmitterMaterial MaterialSlot;
    MaterialSlot.Name = TEXT("TestMaterial");
    MaterialSlot.Material = Material;
    Effect->NamedMaterialSlots.Add(MaterialSlot);
    UPackage* NiagaraPackage = CreatePackage(*(SourceRoot / TEXT("NS_Test")));
    UClass* FactoryClass = LoadClass<UFactory>(nullptr, TEXT("/Script/NiagaraEditor.NiagaraSystemFactoryNew"));
    if (!TestNotNull(TEXT("Niagara factory is available"), FactoryClass))
    {
        return false;
    }
    UFactory* Factory = NewObject<UFactory>(GetTransientPackage(), FactoryClass);
    UNiagaraSystem* Niagara = Cast<UNiagaraSystem>(Factory->FactoryCreateNew(
        UNiagaraSystem::StaticClass(), NiagaraPackage, TEXT("NS_Test"), RF_Public | RF_Standalone, nullptr, GWarn));
    if (!TestNotNull(TEXT("Create a valid Niagara system with editor script graphs"), Niagara))
    {
        return false;
    }
    Niagara->WaitForCompilationComplete();
    // Both legacy effect types have preview textures but no thumbnail table.
    for (UObject* PreviewOwner : { static_cast<UObject*>(Niagara), static_cast<UObject*>(Effect) })
    {
        UTexture2D* Preview = NewObject<UTexture2D>(PreviewOwner, TEXT("ThumbnailTexture"));
        const uint8 PreviewPixel[4] = { 35, 180, 70, 255 };
        Preview->Source.Init(1, 1, 1, 1, TSF_BGRA8, PreviewPixel);
        if (UNiagaraSystem* System = Cast<UNiagaraSystem>(PreviewOwner))
        {
            System->ThumbnailImage = Preview;
        }
        else
        {
            CastChecked<UParticleSystem>(PreviewOwner)->ThumbnailImage = Preview;
        }
    }
    // This serialized soft path exercises a Niagara-owned soft dependency.
    Niagara->PreviewMoviePath = FSoftObjectPath(Effect);
    const FSoftObjectPath OriginalSoftPath = Niagara->PreviewMoviePath;
    UPackage* ExistingPackage = CreatePackage(*(TargetPackageRoot / TEXT("Mat/MI_Test")));
    UMaterialInstanceConstant* ExistingMaterial = NewObject<UMaterialInstanceConstant>(ExistingPackage, TEXT("MI_Test"), RF_Public | RF_Standalone);
    for (UObject* Asset : { static_cast<UObject*>(Texture), static_cast<UObject*>(Material), static_cast<UObject*>(Effect),
        static_cast<UObject*>(Niagara), static_cast<UObject*>(ExistingMaterial) })
    {
        FAssetRegistryModule::AssetCreated(Asset);
        Asset->MarkPackageDirty();
    }
    if (!TestTrue(TEXT("Save source fixture packages"),
        UEditorLoadingAndSavingUtils::SavePackages({ TexturePackage, MaterialPackage, EffectPackage, NiagaraPackage, ExistingPackage }, false)))
    {
        return false;
    }
    const FString ExistingFilename = FPackageName::LongPackageNameToFilename(ExistingPackage->GetName(), TEXT(".uasset"));
    const FMD5Hash ExistingHash = FMD5Hash::HashFile(*ExistingFilename);
    const TArray<UObject*> SourceAssets = { Texture, Material, Effect, Niagara };
    TArray<FString> SourcePaths;
    TArray<FMD5Hash> SourceHashes;
    for (UObject* Asset : SourceAssets)
    {
        SourcePaths.Add(Asset->GetPathName());
        SourceHashes.Add(FMD5Hash::HashFile(*FPackageName::LongPackageNameToFilename(
            Asset->GetOutermost()->GetName(), TEXT(".uasset"))));
    }
    FAssetData EffectData(Niagara);
    FString Error;
    bool bPublished = false;
    {
        // UE's automation mode includes read-only engine packages in its
        // dirty-package scan. Exercise the normal editor's save policy.
        TGuardValue<bool> NormalEditorSavePolicy(GIsAutomationTesting, false);
        TGuardValue<bool> UnattendedSavePolicy(GIsRunningUnattendedScript, true);
        bPublished = PublishEffect(EffectData, Content / RelativeTarget, Error, TargetProject);
    }
    if (!TestTrue(TEXT("Complete local VFX publishing succeeds"), bPublished))
    {
        AddError(Error);
        return false;
    }
    const FString PublishedNiagaraFile = Content / RelativeTarget / TEXT("NS_Test.uasset");
    TAtomic<bool> BrowserCancelled(false);
    const auto BrowserListing = CGToolsVfxBrowser::ReadDirectory(Content / RelativeTarget, BrowserCancelled);
    TestTrue(TEXT("The publish destination browser recognizes real Niagara packages by metadata"), BrowserListing.Entries.ContainsByPredicate([](const auto& Entry)
        { return Entry.ClassName == TEXT("NiagaraSystem") && Entry.Name == TEXT("NS_Test"); }));
    TestTrue(TEXT("The publish destination browser recognizes real Cascade packages by metadata"), BrowserListing.Entries.ContainsByPredicate([](const auto& Entry)
        { return Entry.ClassName == TEXT("ParticleSystem"); }));
    const FMD5Hash FirstPublishedHash = FMD5Hash::HashFile(*PublishedNiagaraFile);
    FString OverwriteBackup;
    int32 ConfirmationCount = 0;
    {
        TGuardValue<bool> NormalEditorSavePolicy(GIsAutomationTesting, false);
        TGuardValue<bool> UnattendedSavePolicy(GIsRunningUnattendedScript, true);
        FCGToolsPublisherBrowserTestScope BrowserState(EffectData);
        FString RepairMessage;
        TestTrue(TEXT("Shared mesh/VFX display repair succeeds without browser navigation"),
            CGToolsPublisher::RepairSourceAssetDisplay({ SourceRoot }, RepairMessage));
        BrowserState.VerifyUnchanged(*this);
        const FString EmptyFolder = SourceRoot / TEXT("EmptyFolder");
        IFileManager::Get().MakeDirectory(*FPackageName::LongPackageNameToFilename(EmptyFolder), true);
        TestTrue(TEXT("Empty-folder repair also avoids the browser folder fallback"),
            CGToolsPublisher::RepairSourceAssetDisplay({ EmptyFolder }, RepairMessage));
        BrowserState.VerifyUnchanged(*this);
        const bool bCancelled = PublishEffect(EffectData, Content / RelativeTarget, Error, TargetProject,
            [this, &ConfirmationCount](const TArray<FString>& Conflicts)
            {
                ++ConfirmationCount;
                TestTrue(TEXT("Overwrite prompt includes the effect and its dependencies"), Conflicts.Num() >= 4);
                return false;
            }, &OverwriteBackup);
        TestFalse(TEXT("Cancelling overwrite does not publish"), bCancelled);
        TestTrue(TEXT("Cancellation is silent rather than a publishing error"), Error.IsEmpty());
        TestTrue(TEXT("Cancellation leaves the published package untouched"), FirstPublishedHash == FMD5Hash::HashFile(*PublishedNiagaraFile));
        TestTrue(TEXT("Cancellation does not create a backup"), OverwriteBackup.IsEmpty());
        BrowserState.VerifyUnchanged(*this);
        bool bReviewed = false;
        const bool bReviewCancelled = PublishEffect(EffectData, Content / RelativeTarget, Error, TargetProject, {}, &OverwriteBackup,
            [this, &bReviewed, &RelativeTarget](const FString& Stage, const FString& Server, CGToolsPublisher::FPublishFileResult& Result)
            {
                bReviewed = true;
                const auto Plan = CGToolsPublisher::BuildPublishFilePlan(Stage, Server, GetVfxPublishReviewRoots(Stage));
                TestTrue(TEXT("The runtime file review receives the effect and dependencies"), Plan.Files.Num() >= 4 && Plan.Error.IsEmpty());
                TestFalse(TEXT("VFX review has no unrelated server-only missing rows"), Plan.Files.ContainsByPredicate([](const auto& File)
                    { return File->Difference == CGToolsPublisher::EPublishFileDifference::Missing; }));
                TestEqual(TEXT("Runtime review defaults to no selected files"), Plan.NumSelected(), 0);
                return false;
            });
        TestTrue(TEXT("The new runtime file-review callback is reached"), bReviewed);
        TestFalse(TEXT("Cancelling the runtime file review does not publish"), bReviewCancelled);
        TestTrue(TEXT("File-review cancellation is silent"), Error.IsEmpty());
        TestTrue(TEXT("File-review cancellation leaves published package bytes unchanged"), FirstPublishedHash == FMD5Hash::HashFile(*PublishedNiagaraFile));
        BrowserState.VerifyUnchanged(*this);
        const bool bOverwritten = PublishEffect(EffectData, Content / RelativeTarget, Error, TargetProject,
            [&ConfirmationCount](const TArray<FString>&) { ++ConfirmationCount; return true; }, &OverwriteBackup);
        if (!TestTrue(TEXT("Confirmed republishing of real packages succeeds"), bOverwritten))
        {
            AddError(Error);
            return false;
        }
    }
    TestEqual(TEXT("Each conflicting publish asks exactly once"), ConfirmationCount, 2);
    TestTrue(TEXT("Real package overwrite retains an exact original backup"),
        FirstPublishedHash == FMD5Hash::HashFile(*(OverwriteBackup / TEXT("Content") / RelativeTarget / TEXT("NS_Test.uasset"))));
    for (UObject* PreviewOwner : { static_cast<UObject*>(Niagara), static_cast<UObject*>(Effect) })
    {
        const FString PublishedPackage = GetOrganizedPackage(PreviewOwner, TargetPackageRoot);
        const FString Filename = Content / (PublishedPackage.Mid(6) + TEXT(".uasset"));
        const FName FullName(*(PreviewOwner->GetClass()->GetName() + TEXT(" ")
            + PublishedPackage + TEXT(".") + PreviewOwner->GetName()));
        FThumbnailMap Thumbnails;
        // The first filename supplies the logical /Game identity; the last
        // filename is the actual migrated package in the isolated target.
        const FString LogicalFilename = FPackageName::LongPackageNameToFilename(PublishedPackage, TEXT(".uasset"));
        ThumbnailTools::LoadThumbnailsFromPackageDirectly(LogicalFilename, { FullName }, Thumbnails, Filename);
        const FObjectThumbnail* SavedThumbnail = Thumbnails.Find(FullName);
        if (TestNotNull(TEXT("Final published package contains a standard effect thumbnail"), SavedThumbnail))
        {
            TestEqual(TEXT("Published thumbnail width"), SavedThumbnail->GetImageWidth(), 256);
            TestTrue(TEXT("Published thumbnail pixels are readable"), !SavedThumbnail->GetUncompressedImageData().IsEmpty());
        }
    }
    for (int32 Index = 0; Index < SourceAssets.Num(); ++Index)
    {
        UObject* Asset = SourceAssets[Index];
        TestEqual(TEXT("Source asset stays at its original object path"), Asset->GetPathName(), SourcePaths[Index]);
        TestTrue(TEXT("Source file content remains unchanged"), SourceHashes[Index] == FMD5Hash::HashFile(
            *FPackageName::LongPackageNameToFilename(Asset->GetOutermost()->GetName(), TEXT(".uasset"))));
    }
    TestEqual(TEXT("Menu selection still identifies the source Niagara system"), EffectData.PackageName, FName(*(SourceRoot / TEXT("NS_Test"))));
    TestEqual(TEXT("Source Niagara soft reference remains unchanged"), Niagara->PreviewMoviePath.ToString(), OriginalSoftPath.ToString());
    TestTrue(TEXT("Current project asset at a target path is preserved"), FindObjectFast<UMaterialInstanceConstant>(ExistingPackage, TEXT("MI_Test")) == ExistingMaterial);
    TestTrue(TEXT("Current project target-path file remains unchanged"), FMD5Hash::HashFile(*ExistingFilename) == ExistingHash);
    TestTrue(TEXT("Source effect still references its source material"), Effect->NamedMaterialSlots[0].Material == Material);
    TestTrue(TEXT("Source material still references its source texture"), Material->TextureParameterValues[0].ParameterValue == Texture);
    TestFalse(TEXT("Publishing does not create organized assets in source Content"),
        IFileManager::Get().FileExists(*FPackageName::LongPackageNameToFilename(TargetPackageRoot / TEXT("P_Test"), TEXT(".uasset"))));

    FPackageName::RegisterMountPoint(Mount, Content + TEXT("/"));
    bMounted = true;
    FLinkerInstancingContext Context;
    for (UObject* Asset : SourceAssets)
    {
        const FString Target = GetOrganizedPackage(Asset, TargetPackageRoot);
        Context.AddPackageMapping(FName(*Target), FName(*(Mount + Target.Mid(6))));
        TestTrue(TEXT("Organized migrated package file exists"), IFileManager::Get().FileExists(*(Content / (Target.Mid(6) + TEXT(".uasset")))));
    }
    for (UObject* Asset : SourceAssets)
    {
        const FString Target = GetOrganizedPackage(Asset, TargetPackageRoot);
        UPackage* Package = CreatePackage(*(Mount + Target.Mid(6)));
        TestNotNull(TEXT("Prepare independent migrated package linker"), LoadPackage(Package,
            *(Content / (Target.Mid(6) + TEXT(".uasset"))), LOAD_Verify | LOAD_NoVerify, nullptr, &Context));
    }
    UPackage* ReloadedPackage = LoadPackage(FindPackage(nullptr, *(Mount + RelativeTarget / TEXT("P_Test"))),
        *(Content / RelativeTarget / TEXT("P_Test.uasset")), LOAD_None, nullptr, &Context);
    UParticleSystem* ReloadedEffect = ReloadedPackage ? FindObjectFast<UParticleSystem>(ReloadedPackage, TEXT("P_Test")) : nullptr;
    if (!TestNotNull(TEXT("Migrated effect reloads independently of source"), ReloadedEffect)
        || !TestTrue(TEXT("Reloaded effect retains material slots"), !ReloadedEffect->NamedMaterialSlots.IsEmpty()))
    {
        return false;
    }
    UMaterialInstanceConstant* ReloadedMaterial = Cast<UMaterialInstanceConstant>(ReloadedEffect->NamedMaterialSlots[0].Material);
    if (!TestNotNull(TEXT("Migrated effect resolves its material"), ReloadedMaterial)
        || !TestTrue(TEXT("Reloaded material retains texture parameters"), !ReloadedMaterial->TextureParameterValues.IsEmpty()))
    {
        return false;
    }
    TestTrue(TEXT("Material loads from migrated content"), ReloadedMaterial != Material);
    TestEqual(TEXT("Material reference uses the organized package path"), ReloadedMaterial->GetOutermost()->GetName(), Mount + RelativeTarget / TEXT("Mat/MI_Test"));
    UTexture* ReloadedTexture = ReloadedMaterial->TextureParameterValues[0].ParameterValue;
    if (TestNotNull(TEXT("Migrated material resolves its texture"), ReloadedTexture))
    {
        TestTrue(TEXT("Texture loads from migrated content"), ReloadedTexture != Texture);
        TestEqual(TEXT("Texture reference uses the organized package path"), ReloadedTexture->GetOutermost()->GetName(), Mount + RelativeTarget / TEXT("Tex/T_Test"));
    }
    UPackage* ReloadedNiagaraPackage = LoadPackage(FindPackage(nullptr, *(Mount + RelativeTarget / TEXT("NS_Test"))),
        *(Content / RelativeTarget / TEXT("NS_Test.uasset")), LOAD_None, nullptr, &Context);
    UNiagaraSystem* ReloadedNiagara = ReloadedNiagaraPackage ? FindObjectFast<UNiagaraSystem>(ReloadedNiagaraPackage, TEXT("NS_Test")) : nullptr;
    if (TestNotNull(TEXT("Published Niagara system reloads independently"), ReloadedNiagara))
    {
        TestTrue(TEXT("Published Niagara is an independent copy"), ReloadedNiagara != Niagara);
        TestEqual(TEXT("Niagara soft dependency uses the published path"), ReloadedNiagara->PreviewMoviePath.ToString(),
            FSoftObjectPath(ReloadedEffect).ToString());
        TestTrue(TEXT("Niagara soft dependency resolves to the published Cascade copy"),
            ReloadedNiagara->PreviewMoviePath.TryLoad() == ReloadedEffect);
    }
    return true;
}

#endif

#undef LOCTEXT_NAMESPACE
