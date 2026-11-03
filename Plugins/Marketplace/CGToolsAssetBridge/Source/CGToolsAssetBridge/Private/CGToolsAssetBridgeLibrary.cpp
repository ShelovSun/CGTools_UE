#include "CGToolsAssetBridgeLibrary.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Editor.h"
#include "EditorViewportClient.h"
#include "Elements/Framework/TypedElementHandle.h"
#include "Engine/Blueprint.h"
#include "Engine/Texture2D.h"
#include "Framework/Application/SlateApplication.h"
#include "GenericPlatform/ICursor.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "LevelEditor.h"
#include "LevelEditorViewport.h"
#include "Misc/Crc.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/ObjectThumbnail.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "Modules/ModuleManager.h"
#include "NiagaraSystem.h"
#include "Particles/ParticleSystem.h"
#include "SLevelViewport.h"
#include "UObject/PackageFileSummary.h"
#include "UnrealClient.h"

DEFINE_LOG_CATEGORY_STATIC(LogCGToolsAssetBridge, Log, All);

namespace
{
    UObject* LoadPlaceableObject(const FString& InObjectPath, FString& OutError)
    {
        FString ObjectPath = InObjectPath;
        ObjectPath.TrimStartAndEndInline();
        if (ObjectPath.IsEmpty())
        {
            OutError = TEXT("资产对象路径为空");
            return nullptr;
        }

        // Accept both /Game/A/B.Asset and the package-only /Game/A/B form.
        if (!ObjectPath.Contains(TEXT(".")))
        {
            const FString AssetName = FPackageName::GetLongPackageAssetName(ObjectPath);
            ObjectPath = FString::Printf(TEXT("%s.%s"), *ObjectPath, *AssetName);
        }

        UObject* Asset = LoadObject<UObject>(nullptr, *ObjectPath);
        if (!Asset)
        {
            OutError = FString::Printf(TEXT("无法加载资产: %s"), *ObjectPath);
            return nullptr;
        }
        return Asset;
    }

    struct FViewportCursor
    {
        FEditorViewportClient* Client = nullptr;
        FIntPoint LocalPx = FIntPoint::ZeroValue;
    };

    TOptional<FViewportCursor> ResolveViewportAtScreenPosition(
        const FVector2D& Cursor, FString& OutError)
    {
        if (!FSlateApplication::IsInitialized() || !GEditor)
        {
            OutError = TEXT("没有可用的关卡编辑器视口");
            return TOptional<FViewportCursor>();
        }

        UWorld* EditorWorld = GEditor->GetEditorWorldContext().World();
        FLevelEditorModule* LevelEditorModule =
            FModuleManager::GetModulePtr<FLevelEditorModule>(TEXT("LevelEditor"));
        const TSharedPtr<ILevelEditor> LevelEditor =
            LevelEditorModule ? LevelEditorModule->GetFirstLevelEditor() : nullptr;
        if (!LevelEditor.IsValid() || !EditorWorld)
        {
            OutError = TEXT("当前没有打开可编辑关卡");
            return TOptional<FViewportCursor>();
        }

        // 屏幕坐标减去 Slate 视口绝对几何，得到准确的视口本地坐标。
        for (const TSharedPtr<SLevelViewport>& LevelViewport : LevelEditor->GetViewports())
        {
            if (!LevelViewport.IsValid())
            {
                continue;
            }
            FEditorViewportClient* Client = &LevelViewport->GetAssetViewportClient();
            if (!Client || !Client->Viewport || Client->GetWorld() != EditorWorld)
            {
                continue;
            }
            const FGeometry& Geometry = LevelViewport->GetTickSpaceGeometry();
            const FVector2D AbsolutePosition = Geometry.GetAbsolutePosition();
            const FVector2D AbsoluteSize = Geometry.GetAbsoluteSize();
            if (Cursor.X < AbsolutePosition.X || Cursor.Y < AbsolutePosition.Y ||
                Cursor.X > AbsolutePosition.X + AbsoluteSize.X ||
                Cursor.Y > AbsolutePosition.Y + AbsoluteSize.Y)
            {
                continue;
            }
            const FVector2D Local = (Cursor - AbsolutePosition) / Geometry.Scale;
            const FIntPoint LocalPx(FMath::RoundToInt(Local.X), FMath::RoundToInt(Local.Y));
            const FIntPoint ViewportSize = Client->Viewport->GetSizeXY();
            if (LocalPx.X >= 0 && LocalPx.Y >= 0 &&
                LocalPx.X < ViewportSize.X && LocalPx.Y < ViewportSize.Y)
            {
                return FViewportCursor{ Client, LocalPx };
            }
        }

        OutError = FString::Printf(
            TEXT("松手位置不在当前关卡 Level Viewport 内（屏幕坐标 %d, %d）"),
            FMath::RoundToInt(Cursor.X), FMath::RoundToInt(Cursor.Y));
        return TOptional<FViewportCursor>();
    }

    TOptional<FViewportCursor> ResolveViewportUnderCursor(FString& OutError)
    {
        if (!FSlateApplication::IsInitialized())
        {
            OutError = TEXT("Slate 尚未初始化");
            return TOptional<FViewportCursor>();
        }
        // ICursor::GetPosition 直接查询平台光标；Qt 捕获鼠标时比 SlateUser 缓存可靠。
        const TSharedPtr<ICursor> PlatformCursor = FSlateApplication::Get().GetPlatformCursor();
        FVector2D Cursor = FSlateApplication::Get().GetCursorPos();
        if (PlatformCursor.IsValid())
        {
            Cursor = PlatformCursor->GetPosition();
        }
        return ResolveViewportAtScreenPosition(Cursor, OutError);
    }

    bool QueryDrop(UObject* Asset, const FViewportCursor& ViewportCursor, FString& OutError)
    {
        const FDropQuery Query = ViewportCursor.Client->CanDropObjectsAtCoordinates(
            ViewportCursor.LocalPx.X, ViewportCursor.LocalPx.Y, FAssetData(Asset));
        if (!Query.bCanDrop)
        {
            OutError = Query.HintText.IsEmpty()
                ? FString::Printf(TEXT("资产类型不能放入当前关卡: %s"), *Asset->GetName())
                : Query.HintText.ToString();
            return false;
        }
        return true;
    }

    bool DropAsset(UObject* Asset, const FViewportCursor& ViewportCursor, FString& OutError)
    {
        if (!QueryDrop(Asset, ViewportCursor, OutError))
        {
            return false;
        }

        TArray<UObject*> DroppedObjects;
        DroppedObjects.Add(Asset);
        TArray<FTypedElementHandle> NewElements;
        FEditorViewportClient::FDropObjectOptions Options;
        Options.bSelectOutput = true;
        const bool bDropped = ViewportCursor.Client->DropObjectsAtCoordinates(
            ViewportCursor.LocalPx.X,
            ViewportCursor.LocalPx.Y,
            DroppedObjects,
            NewElements,
            Options);

        if (!bDropped || NewElements.Num() == 0)
        {
            OutError = FString::Printf(
                TEXT("UE 拒绝创建资产 %s（视口坐标 %d, %d，Drop=%s，结果数=%d）"),
                *Asset->GetName(),
                ViewportCursor.LocalPx.X,
                ViewportCursor.LocalPx.Y,
                bDropped ? TEXT("true") : TEXT("false"),
                NewElements.Num());
            return false;
        }

        UE_LOG(LogCGToolsAssetBridge, Display,
            TEXT("Placed %s at viewport cursor (%d, %d); elements=%d"),
            *Asset->GetPathName(), ViewportCursor.LocalPx.X, ViewportCursor.LocalPx.Y,
            NewElements.Num());
        return true;
    }

    bool ResolvePackageFile(
        const FString& MountedPackage,
        const FString& MountRoot,
        const FString& SourceContentRoot,
        FString& OutFile)
    {
        if (!MountedPackage.StartsWith(MountRoot, ESearchCase::CaseSensitive))
        {
            return false;
        }

        FString Relative = MountedPackage.RightChop(MountRoot.Len());
        Relative.RemoveFromStart(TEXT("/"));
        if (Relative.IsEmpty() || Relative.StartsWith(TEXT("..")))
        {
            return false;
        }

        const FString Base = FPaths::Combine(SourceContentRoot, Relative);
        const FString AssetFile = Base + TEXT(".uasset");
        if (FPaths::FileExists(AssetFile))
        {
            OutFile = AssetFile;
            FPaths::NormalizeFilename(OutFile);
            return true;
        }

        const FString MapFile = Base + TEXT(".umap");
        if (FPaths::FileExists(MapFile))
        {
            OutFile = MapFile;
            FPaths::NormalizeFilename(OutFile);
            return true;
        }
        return false;
    }

    FString ToMountedPackage(const FString& PackageName, const FString& MountRoot)
    {
        if (PackageName.StartsWith(MountRoot, ESearchCase::CaseSensitive))
        {
            return PackageName;
        }
        if (PackageName.StartsWith(TEXT("/Game/"), ESearchCase::CaseSensitive))
        {
            return MountRoot + PackageName.RightChop(5);
        }
        return FString();
    }

    FString ToGamePackage(const FString& PackageName, const FString& MountRoot)
    {
        if (PackageName.StartsWith(MountRoot, ESearchCase::CaseSensitive))
        {
            return TEXT("/Game") + PackageName.RightChop(MountRoot.Len());
        }
        return PackageName;
    }
}

FString UCGToolsAssetBridgeLibrary::GetBridgeVersion()
{
    return TEXT("1.3.3");
}

bool UCGToolsAssetBridgeLibrary::GetExternalAssetClassNames(
    const TArray<FString>& AssetFilePaths,
    const FString& SourceContentRoot,
    TArray<FString>& OutClassNames,
    FString& OutError)
{
    OutClassNames.Init(FString(), AssetFilePaths.Num());
    OutError.Reset();

    if (!IsInGameThread())
    {
        OutError = TEXT("外部资产类型只能在 UE 主线程中读取");
        return false;
    }
    if (AssetFilePaths.Num() == 0)
    {
        return true;
    }

    FString ContentRoot = FPaths::ConvertRelativePathToFull(SourceContentRoot);
    FPaths::NormalizeDirectoryName(ContentRoot);
    if (!FPaths::DirectoryExists(ContentRoot))
    {
        OutError = FString::Printf(TEXT("找不到外部 Content 目录: %s"), *ContentRoot);
        return false;
    }

    const FString ContentRootWithSlash = ContentRoot / TEXT("");
    const uint32 MountHash = FCrc::StrCrc32(*ContentRoot.ToLower());
    const FString MountRoot = FString::Printf(TEXT("/CGToolsExternal_%08x"), MountHash);
    const FString MountPoint = MountRoot / TEXT("");

    TArray<FString> SourceFiles;
    TArray<FName> PackageNames;
    SourceFiles.Reserve(AssetFilePaths.Num());
    PackageNames.Init(NAME_None, AssetFilePaths.Num());
    for (int32 Index = 0; Index < AssetFilePaths.Num(); ++Index)
    {
        FString SourceFile = FPaths::ConvertRelativePathToFull(AssetFilePaths[Index]);
        FPaths::NormalizeFilename(SourceFile);
        if (!FPaths::FileExists(SourceFile) ||
            !FPaths::GetExtension(SourceFile, true).Equals(
                TEXT(".uasset"), ESearchCase::IgnoreCase))
        {
            continue;
        }

        FString RelativeFile = SourceFile;
        if (!FPaths::MakePathRelativeTo(RelativeFile, *ContentRootWithSlash) ||
            RelativeFile.StartsWith(TEXT("..")))
        {
            continue;
        }
        FPaths::NormalizeFilename(RelativeFile);
        FString RelativePackage = FPaths::ChangeExtension(RelativeFile, TEXT(""));
        RelativePackage.RemoveFromStart(TEXT("/"));
        if (RelativePackage.IsEmpty())
        {
            continue;
        }

        SourceFiles.Add(SourceFile);
        PackageNames[Index] = FName(*(MountRoot / RelativePackage));
    }
    if (SourceFiles.Num() == 0)
    {
        OutError = TEXT("没有可读取类型的外部 .uasset 文件");
        return false;
    }

    if (FPackageName::MountPointExists(MountPoint))
    {
        FPackageName::UnRegisterMountPoint(MountPoint, ContentRootWithSlash);
    }
    FPackageName::RegisterMountPoint(MountPoint, ContentRootWithSlash);
    ON_SCOPE_EXIT
    {
        FPackageName::UnRegisterMountPoint(MountPoint, ContentRootWithSlash);
    };

    FAssetRegistryModule& RegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = RegistryModule.Get();
    Registry.ScanFilesSynchronous(SourceFiles, true);

    int32 RecognizedCount = 0;
    for (int32 Index = 0; Index < PackageNames.Num(); ++Index)
    {
        if (PackageNames[Index].IsNone())
        {
            continue;
        }

        TArray<FAssetData> Assets;
        Registry.GetAssetsByPackageName(PackageNames[Index], Assets);
        if (Assets.Num() == 0)
        {
            continue;
        }

        const FString ExpectedAssetName =
            FPaths::GetBaseFilename(AssetFilePaths[Index]);
        const FAssetData* SelectedAsset = &Assets[0];
        for (const FAssetData& Asset : Assets)
        {
            if (Asset.AssetName.ToString().Equals(
                    ExpectedAssetName, ESearchCase::IgnoreCase))
            {
                SelectedAsset = &Asset;
                break;
            }
        }
        OutClassNames[Index] =
            SelectedAsset->AssetClassPath.GetAssetName().ToString();
        if (!OutClassNames[Index].IsEmpty())
        {
            ++RecognizedCount;
        }
    }

    if (RecognizedCount == 0)
    {
        OutError = TEXT("UE Asset Registry 无法识别这些外部资产的类型");
        return false;
    }

    UE_LOG(LogCGToolsAssetBridge, Display,
        TEXT("Read %d/%d external asset class names from %s"),
        RecognizedCount, AssetFilePaths.Num(), *ContentRoot);
    return true;
}

bool UCGToolsAssetBridgeLibrary::ResolveExternalAssetDependencies(
    const FString& AssetFilePath,
    const FString& SourceContentRoot,
    TArray<FString>& OutPackageFiles,
    TArray<FString>& OutMissingPackages,
    FString& OutError)
{
    OutPackageFiles.Reset();
    OutMissingPackages.Reset();
    OutError.Reset();

    if (!IsInGameThread())
    {
        OutError = TEXT("外部资产依赖只能在 UE 主线程中解析");
        return false;
    }

    FString SourceFile = FPaths::ConvertRelativePathToFull(AssetFilePath);
    FString ContentRoot = FPaths::ConvertRelativePathToFull(SourceContentRoot);
    FPaths::NormalizeFilename(SourceFile);
    FPaths::NormalizeDirectoryName(ContentRoot);
    if (!FPaths::FileExists(SourceFile))
    {
        OutError = FString::Printf(TEXT("找不到外部资产文件: %s"), *SourceFile);
        return false;
    }
    if (!FPaths::DirectoryExists(ContentRoot))
    {
        OutError = FString::Printf(TEXT("找不到外部 Content 目录: %s"), *ContentRoot);
        return false;
    }

    const FString Extension = FPaths::GetExtension(SourceFile, true);
    if (!Extension.Equals(TEXT(".uasset"), ESearchCase::IgnoreCase) &&
        !Extension.Equals(TEXT(".umap"), ESearchCase::IgnoreCase))
    {
        OutError = TEXT("只能解析 .uasset 或 .umap 的依赖");
        return false;
    }

    FString RelativeFile = SourceFile;
    const FString ContentRootWithSlash = ContentRoot / TEXT("");
    if (!FPaths::MakePathRelativeTo(RelativeFile, *ContentRootWithSlash) ||
        RelativeFile.StartsWith(TEXT("..")))
    {
        OutError = TEXT("选中的资产不在指定 Content 目录内");
        return false;
    }
    FPaths::NormalizeFilename(RelativeFile);
    FString RelativePackage = FPaths::ChangeExtension(RelativeFile, TEXT(""));
    RelativePackage.RemoveFromStart(TEXT("/"));

    const uint32 MountHash = FCrc::StrCrc32(*ContentRoot.ToLower());
    const FString MountRoot = FString::Printf(TEXT("/CGToolsExternal_%08x"), MountHash);
    const FString MountPoint = MountRoot / TEXT("");
    // 首次使用这个按 Content 路径生成的唯一挂载点时并不存在旧映射。
    // 只在确实存在时清理，避免正常首次加载打印“Mount point remove failed”。
    if (FPackageName::MountPointExists(MountPoint))
    {
        FPackageName::UnRegisterMountPoint(MountPoint, ContentRootWithSlash);
    }
    FPackageName::RegisterMountPoint(MountPoint, ContentRootWithSlash);
    ON_SCOPE_EXIT
    {
        FPackageName::UnRegisterMountPoint(MountPoint, ContentRootWithSlash);
    };

    FAssetRegistryModule& RegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = RegistryModule.Get();
    TArray<FString> ScanPaths{MountRoot};
    Registry.ScanPathsSynchronous(ScanPaths, true);

    const FString SeedPackage = MountRoot / RelativePackage;
    TArray<FAssetData> SeedAssets;
    Registry.GetAssetsByPackageName(FName(*SeedPackage), SeedAssets);
    if (SeedAssets.Num() == 0)
    {
        // ScanPathsSynchronous 已同步处理指定外部目录，不应再调用全局
        // WaitForCompletion：后者会等待当前工程正在进行的所有后台扫描，实测会
        // 把一次特效依赖解析额外阻塞 141 秒。极少数路径缓存尚未落账时，只对
        // 用户选中的文件做一次同步补扫即可。
        TArray<FString> SeedFiles{SourceFile};
        Registry.ScanFilesSynchronous(SeedFiles, true);
        Registry.GetAssetsByPackageName(FName(*SeedPackage), SeedAssets);
    }
    if (SeedAssets.Num() == 0)
    {
        OutError = FString::Printf(
            TEXT("UE Asset Registry 无法读取外部资产包: %s"), *SourceFile);
        return false;
    }

    TArray<FName> Queue;
    Queue.Add(FName(*SeedPackage));
    TSet<FName> Visited;
    TSet<FString> Missing;
    while (Queue.Num() > 0)
    {
        const FName Current = Queue.Pop(EAllowShrinking::No);
        if (Visited.Contains(Current))
        {
            continue;
        }
        Visited.Add(Current);

        const FString CurrentString = Current.ToString();
        FString CurrentFile;
        if (!ResolvePackageFile(CurrentString, MountRoot, ContentRoot, CurrentFile))
        {
            Missing.Add(ToGamePackage(CurrentString, MountRoot));
            continue;
        }
        OutPackageFiles.AddUnique(CurrentFile);

        TArray<FName> Dependencies;
        Registry.GetDependencies(Current, Dependencies);
        for (const FName& Dependency : Dependencies)
        {
            const FString DependencyString = Dependency.ToString();
            if (DependencyString.StartsWith(TEXT("/Engine/")) ||
                DependencyString.StartsWith(TEXT("/Script/")) ||
                DependencyString.StartsWith(TEXT("/Memory/")) ||
                DependencyString.StartsWith(TEXT("/Temp/")))
            {
                continue;
            }

            const FString MountedDependency =
                ToMountedPackage(DependencyString, MountRoot);
            if (!MountedDependency.IsEmpty())
            {
                FString DependencyFile;
                if (ResolvePackageFile(
                        MountedDependency, MountRoot, ContentRoot, DependencyFile))
                {
                    Queue.Add(FName(*MountedDependency));
                }
                else if (!FPackageName::DoesPackageExist(
                             ToGamePackage(MountedDependency, MountRoot)))
                {
                    Missing.Add(ToGamePackage(MountedDependency, MountRoot));
                }
                continue;
            }

            // Plugin content (for example /Niagara/...) is not copied. It must
            // already be available in the current editor installation.
            if (!FPackageName::DoesPackageExist(DependencyString))
            {
                Missing.Add(DependencyString);
            }
        }
    }

    OutPackageFiles.Sort();
    OutMissingPackages = Missing.Array();
    OutMissingPackages.Sort();
    if (OutPackageFiles.Num() == 0)
    {
        OutError = TEXT("没有解析到可迁移的外部资产包");
        return false;
    }

    UE_LOG(LogCGToolsAssetBridge, Display,
        TEXT("Resolved external dependency closure: %s -> %d packages, %d missing"),
        *SourceFile, OutPackageFiles.Num(), OutMissingPackages.Num());
    return true;
}

bool UCGToolsAssetBridgeLibrary::ExportExternalAssetThumbnail(
    const FString& AssetFilePath,
    const FString& OutputPngPath,
    FString& OutError)
{
    OutError.Reset();
    const FString SourcePath = FPaths::ConvertRelativePathToFull(AssetFilePath);
    const FString DestinationPath = FPaths::ConvertRelativePathToFull(OutputPngPath);
    if (!FPaths::FileExists(SourcePath))
    {
        OutError = FString::Printf(TEXT("找不到外部资产文件: %s"), *SourcePath);
        return false;
    }
    if (!DestinationPath.EndsWith(TEXT(".png"), ESearchCase::IgnoreCase))
    {
        OutError = TEXT("缩略图输出路径必须以 .png 结尾");
        return false;
    }

    TUniquePtr<FArchive> Reader(IFileManager::Get().CreateFileReader(*SourcePath));
    if (!Reader)
    {
        OutError = FString::Printf(TEXT("无法打开外部资产文件: %s"), *SourcePath);
        return false;
    }

    FPackageFileSummary Summary;
    (*Reader) << Summary;
    if (Summary.Tag != PACKAGE_FILE_TAG || Reader->IsError())
    {
        OutError = FString::Printf(TEXT("文件不是有效的 Unreal 资产包: %s"), *SourcePath);
        return false;
    }
    if (!Summary.IsFileVersionValid() || Summary.IsFileVersionTooOld() ||
        Summary.IsFileVersionTooNew() ||
        Summary.GetFileVersionLicenseeUE() > GPackageFileLicenseeUEVersion)
    {
        OutError = FString::Printf(TEXT("资产包版本与当前 UE 不兼容: %s"), *SourcePath);
        return false;
    }

    // FObjectThumbnail 的序列化格式取决于保存包时使用的版本。文件读取器默认使用
    // 当前最新版本；这里必须切换到包头记录的版本，否则旧包可能被误判为缩略图损坏。
    Reader->SetUEVer(Summary.GetFileVersionUE());
    Reader->SetLicenseeUEVer(Summary.GetFileVersionLicenseeUE());
    Reader->SetEngineVer(Summary.SavedByEngineVersion);
    Reader->SetCustomVersions(Summary.GetCustomVersionContainer());
    if (Summary.ThumbnailTableOffset <= 0 ||
        Summary.ThumbnailTableOffset >= Reader->TotalSize())
    {
        OutError = TEXT("该资产没有保存嵌入缩略图");
        return false;
    }

    Reader->Seek(Summary.ThumbnailTableOffset);
    int32 ThumbnailCount = 0;
    (*Reader) << ThumbnailCount;
    if (Reader->IsError() || ThumbnailCount <= 0 || ThumbnailCount > 100000)
    {
        OutError = TEXT("该资产的缩略图表为空或无效");
        return false;
    }

    const FString ExpectedAssetName = FPaths::GetBaseFilename(SourcePath);
    int32 FirstValidOffset = INDEX_NONE;
    int32 MatchingOffset = INDEX_NONE;
    for (int32 Index = 0; Index < ThumbnailCount; ++Index)
    {
        FString ObjectClassName;
        FString ObjectPathWithoutPackageName;
        int32 FileOffset = INDEX_NONE;
        (*Reader) << ObjectClassName;
        (*Reader) << ObjectPathWithoutPackageName;
        (*Reader) << FileOffset;
        if (Reader->IsError())
        {
            OutError = TEXT("读取资产缩略图索引失败");
            return false;
        }
        if (FileOffset <= 0 || FileOffset >= Reader->TotalSize())
        {
            continue;
        }
        if (FirstValidOffset == INDEX_NONE)
        {
            FirstValidOffset = FileOffset;
        }

        FString ObjectName = FPackageName::ObjectPathToObjectName(
            ObjectPathWithoutPackageName);
        if (ObjectName.IsEmpty())
        {
            ObjectName = ObjectPathWithoutPackageName;
        }
        if (ObjectName.Equals(ExpectedAssetName, ESearchCase::IgnoreCase))
        {
            MatchingOffset = FileOffset;
            break;
        }
    }

    const int32 ThumbnailOffset =
        MatchingOffset != INDEX_NONE ? MatchingOffset : FirstValidOffset;
    if (ThumbnailOffset == INDEX_NONE)
    {
        OutError = TEXT("缩略图表中没有可读取的图像");
        return false;
    }

    Reader->Seek(ThumbnailOffset);
    FObjectThumbnail Thumbnail;
    Thumbnail.Serialize(*Reader);
    if (Reader->IsError() || Thumbnail.IsEmpty() || !Thumbnail.HasValidImageData())
    {
        OutError = TEXT("资产缩略图数据为空或损坏");
        return false;
    }

    const FString DestinationDirectory = FPaths::GetPath(DestinationPath);
    if (!IFileManager::Get().MakeDirectory(*DestinationDirectory, true) &&
        !FPaths::DirectoryExists(DestinationDirectory))
    {
        OutError = FString::Printf(TEXT("无法创建缩略图缓存目录: %s"),
            *DestinationDirectory);
        return false;
    }
    if (!FImageUtils::SaveImageByExtension(*DestinationPath, Thumbnail.GetImage()))
    {
        OutError = FString::Printf(TEXT("无法写入缩略图 PNG: %s"), *DestinationPath);
        return false;
    }
    return true;
}

FString UCGToolsAssetBridgeLibrary::ExportExternalVfxThumbnail(
    const FString& AssetFilePath, const FString& SourceContentRoot, const FString& OutputPngPath)
{
    // Loading external effects on the user's editor thread would freeze browsing.
    if (!FApp::IsUnattended() || !FParse::Param(FCommandLine::Get(), TEXT("CGToolsThumbnailWorker")))
    {
        return TEXT("ERROR|旧特效预览图只能在独立缩略图进程中读取");
    }
    FString Error;
    if (ExportExternalAssetThumbnail(AssetFilePath, OutputPngPath, Error))
    {
        return FString();
    }
    if (!Error.Contains(TEXT("没有保存嵌入缩略图")) && !Error.Contains(TEXT("缩略图表为空"))
        && !Error.Contains(TEXT("没有可读取")) && !Error.Contains(TEXT("数据为空")))
    {
        return TEXT("ERROR|") + Error;
    }
    FString Root = FPaths::ConvertRelativePathToFull(SourceContentRoot);
    FPaths::NormalizeDirectoryName(Root);
    FString Source = FPaths::ConvertRelativePathToFull(AssetFilePath);
    FPaths::NormalizeFilename(Source);
    if (!Source.StartsWith(Root + TEXT("/"), ESearchCase::IgnoreCase)
        || !Source.EndsWith(TEXT(".uasset"), ESearchCase::IgnoreCase))
    {
        return TEXT("ERROR|特效文件不在指定 Content 目录内");
    }
    // The worker uses an empty, temporary project. This read-only mount resolves
    // /Game dependencies directly from the library; no source package is saved.
    FPackageName::RegisterMountPoint(TEXT("/Game/"), Root + TEXT("/"));
    ON_SCOPE_EXIT { FPackageName::UnRegisterMountPoint(TEXT("/Game/"), Root + TEXT("/")); };
    const FString Relative = Source.Mid(Root.Len() + 1);
    const FString PackageName = TEXT("/Game/") + FPaths::ChangeExtension(Relative, TEXT(""));
    const FString ObjectPath = PackageName + TEXT(".") + FPaths::GetBaseFilename(Source);
    UObject* Asset = LoadObject<UObject>(nullptr, *ObjectPath);
    if (!Asset)
    {
        return TEXT("ERROR|无法加载特效读取内部预览纹理：") + ObjectPath;
    }
    UTexture2D* Texture = nullptr;
    if (UNiagaraSystem* System = Cast<UNiagaraSystem>(Asset))
    {
        Texture = System->ThumbnailImage;
    }
    else if (UParticleSystem* Cascade = Cast<UParticleSystem>(Asset))
    {
        Texture = Cascade->ThumbnailImage;
    }
    FImage Image;
    if (!Texture || !Texture->Source.GetMipImage(Image, 0))
    {
        return TEXT("NO_THUMBNAIL|特效没有有效的标准缩略图或内部预览纹理");
    }
    FImage SmallImage;
    Image.ResizeTo(SmallImage, 256, 256, ERawImageFormat::BGRA8, EGammaSpace::sRGB);
    const FString Destination = FPaths::ConvertRelativePathToFull(OutputPngPath);
    if (!IFileManager::Get().MakeDirectory(*FPaths::GetPath(Destination), true)
        || !FImageUtils::SaveImageByExtension(*Destination, SmallImage))
    {
        return TEXT("ERROR|无法写入特效预览 PNG：") + Destination;
    }
    return FString();
}

bool UCGToolsAssetBridgeLibrary::CanPlaceAssetAtCursor(
    const FString& ObjectPath, FString& OutError)
{
    OutError.Reset();
    UObject* Asset = LoadPlaceableObject(ObjectPath, OutError);
    if (!Asset)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("CanPlace failed: %s"), *OutError);
        return false;
    }
    const TOptional<FViewportCursor> ViewportCursor = ResolveViewportUnderCursor(OutError);
    const bool bCanPlace = ViewportCursor.IsSet() && QueryDrop(Asset, ViewportCursor.GetValue(), OutError);
    if (!bCanPlace)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("CanPlace failed for %s: %s"),
            *ObjectPath, *OutError);
    }
    return bCanPlace;
}

bool UCGToolsAssetBridgeLibrary::PlaceAssetAtCursor(
    const FString& ObjectPath, FString& OutError)
{
    OutError.Reset();
    UObject* Asset = LoadPlaceableObject(ObjectPath, OutError);
    if (!Asset)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("Place failed: %s"), *OutError);
        return false;
    }

    const TOptional<FViewportCursor> ViewportCursor = ResolveViewportUnderCursor(OutError);
    if (!ViewportCursor.IsSet())
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("Place failed for %s: %s"),
            *ObjectPath, *OutError);
        return false;
    }
    const bool bPlaced = DropAsset(Asset, ViewportCursor.GetValue(), OutError);
    if (!bPlaced)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("Place failed for %s: %s"),
            *ObjectPath, *OutError);
    }
    return bPlaced;
}

bool UCGToolsAssetBridgeLibrary::PlaceAssetAtScreenPosition(
    const FString& ObjectPath,
    int32 ScreenX,
    int32 ScreenY,
    FString& OutError)
{
    OutError.Reset();
    UObject* Asset = LoadPlaceableObject(ObjectPath, OutError);
    if (!Asset)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning, TEXT("PlaceAtScreen failed: %s"), *OutError);
        return false;
    }

    TOptional<FViewportCursor> ViewportCursor = ResolveViewportAtScreenPosition(
        FVector2D(static_cast<double>(ScreenX), static_cast<double>(ScreenY)), OutError);
    if (!ViewportCursor.IsSet())
    {
        // 如果 Qt/Slate 在高 DPI 屏上使用了不同的屏幕单位，再用平台光标实时位置兜底。
        const FString ExplicitPositionError = OutError;
        FString PlatformPositionError;
        ViewportCursor = ResolveViewportUnderCursor(PlatformPositionError);
        if (!ViewportCursor.IsSet())
        {
            OutError = ExplicitPositionError + TEXT("；平台光标兜底也失败：") + PlatformPositionError;
            UE_LOG(LogCGToolsAssetBridge, Warning,
                TEXT("PlaceAtScreen failed for %s at (%d,%d): %s"),
                *ObjectPath, ScreenX, ScreenY, *OutError);
            return false;
        }
    }

    const bool bPlaced = DropAsset(Asset, ViewportCursor.GetValue(), OutError);
    if (!bPlaced)
    {
        UE_LOG(LogCGToolsAssetBridge, Warning,
            TEXT("PlaceAtScreen failed for %s at (%d,%d): %s"),
            *ObjectPath, ScreenX, ScreenY, *OutError);
    }
    return bPlaced;
}
