#include "SCGToolsVfxDestinationBrowser.h"

#include "AssetRegistry/IAssetRegistry.h"
#include "Async/Async.h"
#include "Engine/Texture2D.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "ImageUtils.h"
#include "Misc/ObjectThumbnail.h"
#include "Misc/Paths.h"
#include "Misc/PackageName.h"
#include "Misc/SecureHash.h"
#include "Slate/DeferredCleanupSlateBrush.h"
#include "Styling/AppStyle.h"
#include "UObject/PackageFileSummary.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SToolTip.h"
#include "Widgets/Text/STextBlock.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
// Windows defines LoadImage as LoadImageW, which conflicts with FImageUtils.
#undef LoadImage
#endif

namespace CGToolsVfxBrowser
{
    namespace
    {
        bool OpenPackage(const FString& Filename, TUniquePtr<FArchive>& Reader, FPackageFileSummary& Summary)
        {
            Reader.Reset(IFileManager::Get().CreateFileReader(*Filename));
            if (!Reader) { return false; }
            Reader->ArMaxSerializeSize = 16 * 1024 * 1024;
            *Reader << Summary;
            if (Reader->IsError() || Summary.Tag != PACKAGE_FILE_TAG || !Summary.IsFileVersionValid()
                || Summary.IsFileVersionTooOld() || Summary.IsFileVersionTooNew()
                || Summary.GetFileVersionLicenseeUE() > GPackageFileLicenseeUEVersion) { return false; }
            Reader->SetUEVer(Summary.GetFileVersionUE());
            Reader->SetLicenseeUEVer(Summary.GetFileVersionLicenseeUE());
            Reader->SetEngineVer(Summary.SavedByEngineVersion);
            Reader->SetCustomVersions(Summary.GetCustomVersionContainer());
            return true;
        }

        FString ReadEffectClass(const FString& Filename)
        {
            TUniquePtr<FArchive> Reader;
            FPackageFileSummary Summary;
            if (!OpenPackage(Filename, Reader, Summary) || Summary.AssetRegistryDataOffset <= 0
                || Summary.AssetRegistryDataOffset >= Reader->TotalSize()) { return FString(); }
            Reader->Seek(Summary.AssetRegistryDataOffset);
            UE::AssetRegistry::EReadPackageDataMainErrorCode Error = UE::AssetRegistry::Unknown;
            UE::AssetRegistry::FDeserializePackageData PackageData;
            if (!PackageData.DoSerialize(*Reader, Summary, Error) || PackageData.ObjectCount > 100000) { return FString(); }
            for (int32 Index = 0; Index < PackageData.ObjectCount; ++Index)
            {
                UE::AssetRegistry::FDeserializeObjectPackageData Object;
                if (!Object.DoSerialize(*Reader, Error) || Object.TagCount > 100000) { return FString(); }
                const FString Class = Object.ObjectClassName;
                if (Class == TEXT("NiagaraSystem") || Class == TEXT("/Script/Niagara.NiagaraSystem")) { return TEXT("NiagaraSystem"); }
                if (Class == TEXT("ParticleSystem") || Class == TEXT("/Script/Engine.ParticleSystem")) { return TEXT("ParticleSystem"); }
                for (int32 TagIndex = 0; TagIndex < Object.TagCount; ++TagIndex)
                {
                    UE::AssetRegistry::FDeserializeTagData Tag;
                    if (!Tag.DoSerialize(*Reader, Error)) { return FString(); }
                }
            }
            return FString();
        }

        FImage ReadEmbeddedThumbnail(const FString& Filename)
        {
            FImage Image;
            TUniquePtr<FArchive> Reader;
            FPackageFileSummary Summary;
            if (!OpenPackage(Filename, Reader, Summary) || Summary.ThumbnailTableOffset <= 0
                || Summary.ThumbnailTableOffset >= Reader->TotalSize()) { return Image; }
            Reader->Seek(Summary.ThumbnailTableOffset);
            int32 Count = 0;
            *Reader << Count;
            if (Reader->IsError() || Count <= 0 || Count > 100000) { return Image; }
            const FString Expected = FPaths::GetBaseFilename(Filename);
            int32 Offset = INDEX_NONE;
            for (int32 Index = 0; Index < Count; ++Index)
            {
                FString Class, Object;
                int32 Position = -1;
                *Reader << Class << Object << Position;
                if (Reader->IsError()) { return Image; }
                if ((Object == Expected || FPackageName::ObjectPathToObjectName(Object) == Expected)
                    && Position > 0 && Position < Reader->TotalSize()) { Offset = Position; break; }
            }
            if (Offset == INDEX_NONE) { return Image; }
            Reader->Seek(Offset);
            FObjectThumbnail Thumbnail;
            Thumbnail.Serialize(*Reader);
            if (Reader->IsError() || Thumbnail.GetImageWidth() <= 0 || Thumbnail.GetImageHeight() <= 0
                || Thumbnail.GetImageWidth() > 2048 || Thumbnail.GetImageHeight() > 2048) { return Image; }
            const TArray<uint8>& Pixels = Thumbnail.GetUncompressedImageData();
            if (Pixels.Num() != Thumbnail.GetImageWidth() * Thumbnail.GetImageHeight() * 4) { return Image; }
            Image.Init(Thumbnail.GetImageWidth(), Thumbnail.GetImageHeight(), ERawImageFormat::BGRA8, EGammaSpace::sRGB);
            FMemory::Memcpy(Image.RawData.GetData(), Pixels.GetData(), Pixels.Num());
            return Image;
        }
    }

    FDirectoryResult ReadDirectory(const FString& Directory, const TAtomic<bool>& Cancelled)
    {
        FDirectoryResult Result;
        IPlatformFile& Files = FPlatformFileManager::Get().GetPlatformFile();
        if (!Files.DirectoryExists(*Directory))
        { Result.Error = TEXT("目录不可访问，请检查网络连接后刷新：\n") + Directory; return Result; }
        const bool bRead = Files.IterateDirectory(*Directory, [&](const TCHAR* Path, bool bIsDirectory)
        {
            if (Cancelled.Load()) { return false; }
            const FString Name = FPaths::GetCleanFilename(Path);
            if (bIsDirectory)
            {
                if (Name.Equals(TEXT("M_F"), ESearchCase::IgnoreCase) || Name.Equals(TEXT("Mat"), ESearchCase::IgnoreCase)
                    || Name.Equals(TEXT("Mesh"), ESearchCase::IgnoreCase) || Name.Equals(TEXT("Tex"), ESearchCase::IgnoreCase)) { return true; }
                // Do not follow junctions or links into unrelated trees.
                if (Files.IsSymlink(Path) == ESymlinkResult::Symlink) { return true; }
                Result.Entries.Add({ Path, Name, FString(), true });
            }
            else if (FPaths::GetExtension(Name).Equals(TEXT("uasset"), ESearchCase::IgnoreCase))
            {
                FString Class = ReadEffectClass(Path);
                if (!Class.IsEmpty()) { Result.Entries.Add({ Path, FPaths::GetBaseFilename(Name), MoveTemp(Class), false }); }
            }
            return true;
        });
        if (!bRead && !Cancelled.Load()) { Result.Error = TEXT("读取目录失败，请刷新重试：\n") + Directory; }
        Result.Entries.Sort([](const FEntry& A, const FEntry& B)
        { return A.bDirectory != B.bDirectory ? A.bDirectory : A.Name.Compare(B.Name, ESearchCase::IgnoreCase) < 0; });
        return Result;
    }

    FString ThumbnailCachePath(const FString& Filename)
    {
#if PLATFORM_WINDOWS
        // UE's generic stat truncates FILETIME to whole seconds. Python's
        // st_mtime_ns retains 100 ns precision, which is part of its cache key.
        WIN32_FILE_ATTRIBUTE_DATA Stat;
        if (!GetFileAttributesExW(*FPaths::ConvertRelativePathToFull(Filename), GetFileExInfoStandard, &Stat)
            || (Stat.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) { return FString(); }
        const int64 FileSize = (static_cast<int64>(Stat.nFileSizeHigh) << 32) | Stat.nFileSizeLow;
        const int64 WriteTime = (static_cast<int64>(Stat.ftLastWriteTime.dwHighDateTime) << 32) | Stat.ftLastWriteTime.dwLowDateTime;
        const int64 Nanoseconds = (WriteTime - 116444736000000000LL) * 100;
#else
        const FFileStatData Stat = IFileManager::Get().GetStatData(*Filename);
        if (!Stat.bIsValid || Stat.bIsDirectory) { return FString(); }
        const int64 FileSize = Stat.FileSize;
        const int64 Nanoseconds = (Stat.ModificationTime.GetTicks() - FDateTime(1970, 1, 1).GetTicks()) * 100;
#endif
        FString Path = FPaths::ConvertRelativePathToFull(Filename).ToLower();
        Path.ReplaceInline(TEXT("/"), TEXT("\\"));
        const FString Fingerprint = FString::Printf(TEXT("%s|%lld|%lld"), *Path, FileSize, Nanoseconds);
        FTCHARToUTF8 Utf8(*Fingerprint);
        uint8 Hash[FSHA1::DigestSize];
        FSHA1::HashBuffer(Utf8.Get(), Utf8.Length(), Hash);
        return FPlatformMisc::GetEnvironmentVariable(TEXT("TEMP")) / TEXT("AssetsManagerVfxThumbnails")
            / (BytesToHex(Hash, UE_ARRAY_COUNT(Hash)).ToLower() + TEXT(".png"));
    }

    FImage ReadThumbnail(const FString& Filename)
    {
        const FString Cache = ThumbnailCachePath(Filename);
        FImage Image;
        if (!Cache.IsEmpty() && IFileManager::Get().FileExists(*Cache) && FImageUtils::LoadImage(*Cache, Image)) { return Image; }
        Image = ReadEmbeddedThumbnail(Filename);
        if (Image.SizeX > 0 && !Cache.IsEmpty())
        {
            IFileManager::Get().MakeDirectory(*FPaths::GetPath(Cache), true);
            const FString Temporary = FPaths::ChangeExtension(Cache, TEXT("")) + TEXT("_") + FGuid::NewGuid().ToString(EGuidFormats::Digits) + TEXT(".png");
            if (FImageUtils::SaveImageByExtension(*Temporary, Image)) { IFileManager::Get().Move(*Cache, *Temporary, true); }
            IFileManager::Get().Delete(*Temporary, false);
        }
        return Image;
    }
}

namespace
{
    template<typename ItemType>
    class SReadOnlyVfxTreeRow : public STableRow<ItemType>
    {
    public:
        virtual ESelectionMode::Type GetSelectionMode() const override { return ESelectionMode::None; }
        virtual FReply OnMouseButtonDown(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
        virtual FReply OnMouseButtonUp(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
        virtual FReply OnMouseButtonDoubleClick(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
    };
}

void SCGToolsVfxDestinationBrowser::Construct(const FArguments& Args)
{
    RootDirectory = Args._RootDirectory;
    FolderSelected = Args._OnFolderSelected;
    FolderDoubleClicked = Args._OnFolderDoubleClicked;
    ChildSlot
    [ SNew(SVerticalBox)
        + SVerticalBox::Slot().FillHeight(1)
        [ SAssignNew(Tree, STreeView<TSharedPtr<FNode>>).TreeItemsSource(&Roots)
            .SelectionMode(ESelectionMode::Single)
            .OnIsSelectableOrNavigable_Lambda([](const TSharedPtr<FNode>& Node) { return Node.IsValid() && Node->Entry.bDirectory && !Node->bPlaceholder; })
            .OnGenerateRow(this, &SCGToolsVfxDestinationBrowser::GenerateRow)
            .OnGetChildren(this, &SCGToolsVfxDestinationBrowser::GetNodeChildren)
            .OnSelectionChanged(this, &SCGToolsVfxDestinationBrowser::Selected)
            .OnMouseButtonClick(this, &SCGToolsVfxDestinationBrowser::Clicked)
            .OnExpansionChanged_Lambda([this](TSharedPtr<FNode> Node, bool bExpanded) { if (bExpanded) { QueueScan(Node); } })
            .OnMouseButtonDoubleClick_Lambda([this](TSharedPtr<FNode> Node)
            { if (Node.IsValid() && Node->Entry.bDirectory && !Node->bPlaceholder) { FolderDoubleClicked.ExecuteIfBound(Node->Entry.Path); } }) ]
        + SVerticalBox::Slot().AutoHeight().Padding(0, 6, 0, 0)
        [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(Status); }).AutoWrapText(true)
            .ColorAndOpacity(FSlateColor::UseSubduedForeground())
            .Visibility_Lambda([this]() { return Status.IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; }) ]
    ];
    Refresh(FString());
    RegisterActiveTimer(0.05f, FWidgetActiveTimerDelegate::CreateSP(this, &SCGToolsVfxDestinationBrowser::Poll));
}

SCGToolsVfxDestinationBrowser::~SCGToolsVfxDestinationBrowser()
{
    if (Cancelled) { Cancelled->Store(true); }
}

void SCGToolsVfxDestinationBrowser::Refresh(const FString& Selection)
{
    if (Cancelled) { Cancelled->Store(true); }
    Cancelled = MakeShared<TAtomic<bool>, ESPMode::ThreadSafe>(false);
    ScanQueue.Reset(); ScanJobs.Reset(); ThumbnailQueue.Reset(); ThumbnailJobs.Reset();
    Tree->ClearSelection(); Tree->ClearExpandedItems(); Roots.Reset();
    RestoreDirectory = Selection;
    FPaths::NormalizeDirectoryName(RestoreDirectory);
    Status = TEXT("正在读取目录…");
    Root = MakeShared<FNode>();
    Root->Entry = { RootDirectory, FString(), FString(), true };
    QueueScan(Root);
    Tree->RequestTreeRefresh();
}

void SCGToolsVfxDestinationBrowser::QueueScan(const TSharedPtr<FNode>& Node)
{
    if (!Node.IsValid() || !Node->Entry.bDirectory || Node->bPlaceholder || Node->bLoaded || Node->bQueued) { return; }
    Node->bQueued = true;
    ScanQueue.Add(Node);
}

void SCGToolsVfxDestinationBrowser::GetNodeChildren(TSharedPtr<FNode> Node, TArray<TSharedPtr<FNode>>& Children)
{
    if (!Node.IsValid() || !Node->Entry.bDirectory || Node->bPlaceholder) { return; }
    if (!Node->bLoaded && Node->Children.IsEmpty())
    {
        auto Placeholder = MakeShared<FNode>();
        Placeholder->bPlaceholder = true; Placeholder->Entry.Name = TEXT("正在读取…");
        Node->Children.Add(Placeholder);
    }
    Children.Append(Node->Children);
}

void SCGToolsVfxDestinationBrowser::Clicked(TSharedPtr<FNode> Node)
{
    if (Node.IsValid() && Node->Entry.bDirectory && !Node->bPlaceholder) { Tree->SetItemExpansion(Node, true); QueueScan(Node); }
}

void SCGToolsVfxDestinationBrowser::Selected(TSharedPtr<FNode> Node, ESelectInfo::Type)
{
    if (!Node.IsValid() || !Node->Entry.bDirectory || Node->bPlaceholder) { return; }
    RestoreDirectory.Reset();
    FolderSelected.ExecuteIfBound(Node->Entry.Path);
    Clicked(Node);
}

TSharedRef<ITableRow> SCGToolsVfxDestinationBrowser::GenerateRow(TSharedPtr<FNode> Node, const TSharedRef<STableViewBase>& Owner)
{
    if (!Node->Entry.bDirectory && !Node->bPlaceholder && !Node->bThumbnailRequested)
    { Node->bThumbnailRequested = true; ThumbnailQueue.Add(Node); }
    const auto Image = [this, Node]() -> const FSlateBrush*
    {
        if (Node->Entry.bDirectory) { return FAppStyle::GetBrush(Tree->IsItemExpanded(Node) ? "ContentBrowser.AssetTreeFolderOpen" : "ContentBrowser.AssetTreeFolderClosed"); }
        if (Node->Thumbnail) { return Node->Thumbnail->GetSlateBrush(); }
        return FAppStyle::GetBrush(Node->Entry.ClassName == TEXT("NiagaraSystem") ? "ClassThumbnail.NiagaraSystem" : "ClassThumbnail.ParticleSystem");
    };
    TSharedRef<STableRow<TSharedPtr<FNode>>> Row = Node->Entry.bDirectory
        ? SNew(STableRow<TSharedPtr<FNode>>, Owner).Padding(FMargin(6, 3))
        : StaticCastSharedRef<STableRow<TSharedPtr<FNode>>>(SNew(SReadOnlyVfxTreeRow<TSharedPtr<FNode>>, Owner).Padding(FMargin(6, 3)));
    Row->SetContent(SNew(SHorizontalBox)
        + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
        [ SNew(SBox).WidthOverride(Node->Entry.bDirectory || Node->bPlaceholder ? 16 : 48).HeightOverride(Node->Entry.bDirectory || Node->bPlaceholder ? 16 : 48)
            [ SNew(SImage).Image_Lambda(Image).Visibility(Node->bPlaceholder ? EVisibility::Collapsed : EVisibility::Visible) ] ]
        + SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center)
        [ SNew(SVerticalBox)
            + SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(FText::FromString(Node->Entry.Name)) ]
            + SVerticalBox::Slot().AutoHeight()
            [ SNew(STextBlock).Text(FText::FromString(Node->Entry.ClassName == TEXT("NiagaraSystem") ? TEXT("Niagara 系统") : TEXT("Cascade 粒子系统")))
                .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                .Visibility(Node->Entry.bDirectory || Node->bPlaceholder ? EVisibility::Collapsed : EVisibility::Visible) ] ]);
    if (Node->Entry.bDirectory)
    { Row->SetToolTipText(FText::FromString(Node->Entry.Path + TEXT("\n双击重命名空文件夹；已有文件的目录请在目标 VFX 工程中修改。"))); }
    else if (!Node->bPlaceholder)
    {
        Row->SetToolTip(SNew(SToolTip)
            [ SNew(SVerticalBox)
                + SVerticalBox::Slot().AutoHeight()
                [ SNew(SBox).WidthOverride(256).HeightOverride(256)
                    [ SNew(SScaleBox).Stretch(EStretch::ScaleToFit) [ SNew(SImage).Image_Lambda(Image) ] ] ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
                [ SNew(STextBlock).Text(FText::FromString(Node->Entry.Name + TEXT("\n仅供预览；请选择文件夹作为发布目录。"))) ] ]);
    }
    return Row;
}

void SCGToolsVfxDestinationBrowser::RestoreSelection()
{
    if (RestoreDirectory.IsEmpty() || !Root->bLoaded) { return; }
    TSharedPtr<FNode> Node = Root;
    while (Node->bLoaded)
    {
        const auto* Child = Node->Children.FindByPredicate([this](const auto& Candidate)
        { return Candidate->Entry.bDirectory && (RestoreDirectory.Equals(Candidate->Entry.Path, ESearchCase::IgnoreCase)
            || RestoreDirectory.StartsWith(Candidate->Entry.Path + TEXT("/"), ESearchCase::IgnoreCase)); });
        if (!Child) { RestoreDirectory.Reset(); return; }
        Node = *Child;
        Tree->SetItemExpansion(Node, true); QueueScan(Node);
        if (RestoreDirectory.Equals(Node->Entry.Path, ESearchCase::IgnoreCase))
        { Tree->SetSelection(Node); Tree->RequestScrollIntoView(Node); RestoreDirectory.Reset(); return; }
    }
}

EActiveTimerReturnType SCGToolsVfxDestinationBrowser::Poll(double, float)
{
    for (int32 Index = ScanJobs.Num() - 1; Index >= 0; --Index)
    {
        if (!ScanJobs[Index].Future.IsReady()) { continue; }
        const auto Node = ScanJobs[Index].Node;
        auto Result = ScanJobs[Index].Future.Get();
        ScanJobs.RemoveAtSwap(Index);
        Node->bLoaded = true; Node->Children.Reset();
        if (!Result.Error.IsEmpty()) { Status = Result.Error; }
        else if (Node == Root) { Status.Reset(); }
        for (auto& Entry : Result.Entries)
        { auto Child = MakeShared<FNode>(); Child->Entry = MoveTemp(Entry); Node->Children.Add(Child); }
        if (Node == Root) { Roots = Node->Children; }
        Tree->RequestTreeRefresh();
        RestoreSelection();
    }
    while (ScanJobs.Num() < 2 && !ScanQueue.IsEmpty())
    {
        const auto Node = ScanQueue[0]; ScanQueue.RemoveAt(0);
        const FString Directory = Node->Entry.Path;
        const auto Token = Cancelled;
        FScanJob Job; Job.Node = Node;
        Job.Future = Async(EAsyncExecution::ThreadPool, [Directory, Token]() { return CGToolsVfxBrowser::ReadDirectory(Directory, *Token); });
        ScanJobs.Add(MoveTemp(Job));
    }
    for (int32 Index = ThumbnailJobs.Num() - 1; Index >= 0; --Index)
    {
        if (!ThumbnailJobs[Index].Future.IsReady()) { continue; }
        const auto Node = ThumbnailJobs[Index].Node;
        FImage Image = ThumbnailJobs[Index].Future.Get(); ThumbnailJobs.RemoveAtSwap(Index);
        if (Image.SizeX <= 0 || Image.SizeY <= 0 || Image.SizeX > 2048 || Image.SizeY > 2048) { continue; }
        FImage Pixels; Image.CopyTo(Pixels, ERawImageFormat::BGRA8, EGammaSpace::sRGB);
        for (int64 Byte = 3; Byte < Pixels.RawData.Num(); Byte += 4) { Pixels.RawData[Byte] = 255; }
        UTexture2D* Texture = UTexture2D::CreateTransient(Pixels.SizeX, Pixels.SizeY, PF_B8G8R8A8, NAME_None,
            TConstArrayView64<uint8>(Pixels.RawData.GetData(), Pixels.RawData.Num()));
        if (Texture)
        { Texture->SRGB = true; Texture->Filter = TF_Bilinear; Texture->NeverStream = true; Texture->UpdateResource();
            Node->Thumbnail = FDeferredCleanupSlateBrush::CreateBrush(Texture, FVector2D(Pixels.SizeX, Pixels.SizeY)); }
    }
    while (ThumbnailJobs.IsEmpty() && !ThumbnailQueue.IsEmpty())
    {
        const auto Node = ThumbnailQueue[0]; ThumbnailQueue.RemoveAt(0);
        if (!Tree->WidgetFromItem(Node).IsValid()) { Node->bThumbnailRequested = false; continue; }
        const FString Filename = Node->Entry.Path;
        FThumbnailJob Job; Job.Node = Node;
        Job.Future = Async(EAsyncExecution::ThreadPool, [Filename]() { return CGToolsVfxBrowser::ReadThumbnail(Filename); });
        ThumbnailJobs.Add(MoveTemp(Job));
    }
    return EActiveTimerReturnType::Continue;
}
