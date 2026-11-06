#pragma once

#include "CoreMinimal.h"
#include "Async/Future.h"
#include "ImageCore.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/STreeView.h"

class FDeferredCleanupSlateBrush;

namespace CGToolsVfxBrowser
{
    struct FEntry
    {
        FString Path;
        FString Name;
        FString ClassName;
        bool bDirectory = false;
    };

    struct FDirectoryResult
    {
        TArray<FEntry> Entries;
        FString Error;
    };

    // Disk metadata only: no mount points, UObject loads, registry scan or server writes.
    FDirectoryResult ReadDirectory(const FString& Directory, const TAtomic<bool>& Cancelled);
    FString ThumbnailCachePath(const FString& Filename);
    FImage ReadThumbnail(const FString& Filename);
}

DECLARE_DELEGATE_OneParam(FCGToolsVfxFolderEvent, const FString&);

class SCGToolsVfxDestinationBrowser : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SCGToolsVfxDestinationBrowser) {}
        SLATE_ARGUMENT(FString, RootDirectory)
        SLATE_EVENT(FCGToolsVfxFolderEvent, OnFolderSelected)
        SLATE_EVENT(FCGToolsVfxFolderEvent, OnFolderDoubleClicked)
    SLATE_END_ARGS()

    void Construct(const FArguments& Args);
    ~SCGToolsVfxDestinationBrowser();
    void Refresh(const FString& Selection);

private:
    friend class FCGToolsVfxBrowserWindowTest;
    struct FNode
    {
        CGToolsVfxBrowser::FEntry Entry;
        TArray<TSharedPtr<FNode>> Children;
        TSharedPtr<FDeferredCleanupSlateBrush> Thumbnail;
        bool bLoaded = false;
        bool bQueued = false;
        bool bThumbnailRequested = false;
        bool bPlaceholder = false;
    };
    struct FScanJob
    {
        TSharedPtr<FNode> Node;
        TFuture<CGToolsVfxBrowser::FDirectoryResult> Future;
    };
    struct FThumbnailJob
    {
        TSharedPtr<FNode> Node;
        TFuture<FImage> Future;
    };

    FString RootDirectory;
    FString RestoreDirectory;
    FString Status;
    TSharedPtr<FNode> Root;
    TArray<TSharedPtr<FNode>> Roots;
    TSharedPtr<STreeView<TSharedPtr<FNode>>> Tree;
    TArray<TSharedPtr<FNode>> ScanQueue;
    TArray<FScanJob> ScanJobs;
    TArray<TSharedPtr<FNode>> ThumbnailQueue;
    TArray<FThumbnailJob> ThumbnailJobs;
    TSharedPtr<TAtomic<bool>, ESPMode::ThreadSafe> Cancelled;
    FCGToolsVfxFolderEvent FolderSelected;
    FCGToolsVfxFolderEvent FolderDoubleClicked;

    void QueueScan(const TSharedPtr<FNode>& Node);
    void GetNodeChildren(TSharedPtr<FNode> Node, TArray<TSharedPtr<FNode>>& Children);
    TSharedRef<ITableRow> GenerateRow(TSharedPtr<FNode> Node, const TSharedRef<STableViewBase>& Owner);
    void Selected(TSharedPtr<FNode> Node, ESelectInfo::Type);
    void Clicked(TSharedPtr<FNode> Node);
    void RestoreSelection();
    EActiveTimerReturnType Poll(double Time, float Delta);
};
