#pragma once

#include "CGToolsPublisherBatch.h"
#include "CGToolsPublisherPanel.h"
#include "Containers/Ticker.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"

class FAssetThumbnail;
class FAssetThumbnailPool;
class SBox;
class SProgressBar;

struct FCGToolsPublisherPanelHandle
{
    TSharedPtr<SWidget> Widget;
    TSharedPtr<ICGToolsPublisherPanel> Panel;
    TSharedPtr<FCGToolsPublisherDialogState> State;
};

namespace CGToolsPublisher
{
    // Keep every selected asset in the list, but publish one UE folder/record
    // per mesh group. Other asset classes retain individual output files.
    TArray<TArray<int32>> MakePublishGroups(const TArray<FAssetData>& Assets,
        const FString& AssetsFolder = TEXT("Assets"), const FString& ScenesFolder = TEXT("Scenes"));
    int32 FindFolderRepresentative(const TArray<FAssetData>& Assets, const TArray<int32>& Members,
        const FString& AssetsFolder = TEXT("Assets"), const FString& ScenesFolder = TEXT("Scenes"));
}

class SCGToolsPublisherBatchWindow : public SCompoundWidget
{
public:
    using FPanelFactory = TFunction<FCGToolsPublisherPanelHandle(const FAssetData&)>;
    SLATE_BEGIN_ARGS(SCGToolsPublisherBatchWindow) {}
        SLATE_ARGUMENT(TArray<FAssetData>, Assets)
        SLATE_ARGUMENT(TSharedPtr<FCGToolsPublisherDialogState>, DialogState)
        SLATE_ARGUMENT(FPanelFactory, PanelFactory)
        SLATE_ARGUMENT(TFunction<bool(const FString&)>, ConfirmBatch)
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);
    virtual ~SCGToolsPublisherBatchWindow() override;

private:
    enum class EPhase : uint8 { Idle, Validate, Publish };
    enum class EResult : uint8 { Waiting, Checking, Ready, Publishing, Succeeded, Warning, Partial, Failed };
    struct FItem
    {
        FAssetData Asset;
        int32 Group = INDEX_NONE;
        FCGToolsPublisherPanelHandle Handle;
        TSharedPtr<FAssetThumbnail> Thumbnail;
        EResult Result = EResult::Waiting;
        FString Detail;
        FString PublishedSettingsKey;
    };
    struct FGroup
    {
        TArray<int32> Members;
        int32 Representative = INDEX_NONE;
        FString Destination;
        FString RecordLabel;
        FString ValidationError;
        bool bCompleted = false;
    };

    TArray<TSharedPtr<FItem>> Items;
    TArray<FGroup> Groups;
    TSharedPtr<FItem> SelectedItem;
    TSharedPtr<FCGToolsPublisherDialogState> DialogState;
    TSharedPtr<FAssetThumbnailPool> ThumbnailPool;
    TSharedPtr<SListView<TSharedPtr<FItem>>> AssetList;
    TSharedPtr<SBox> DetailBox;
    TSharedPtr<SProgressBar> ProgressBar;
    FPanelFactory PanelFactory;
    TFunction<bool(const FString&)> ConfirmBatch;
    FCGToolsPublisherSharedSettings SharedSettings;
    FCGToolsPublisherSharedSettings LastRunSettings;
    TArray<int32> Work;
    TMap<FString, int32> Destinations;
    EPhase Phase = EPhase::Idle;
    int32 Next = 0;
    int32 NextMember = 0;
    bool bRunning = false;
    bool bInStep = false;
    bool bStopRequested = false;
    bool bValidationFailed = false;
    FString Status;
    FTSTicker::FDelegateHandle Ticker;

    FCGToolsPublisherPanelHandle& GetPanel(int32 Index);
    void SelectItem(TSharedPtr<FItem> Item, ESelectInfo::Type SelectInfo);
    TSharedRef<ITableRow> GenerateRow(TSharedPtr<FItem> Item, const TSharedRef<STableViewBase>& Owner);
    void SetGroupResult(int32 Index, EResult Result, const FString& Detail);
    FReply OnStart();
    FReply OnStopOrClose();
    bool Step(float Delta);
    void Finish(const FString& Message);
    FString GetGroupDescription() const;
    FString GetCompletionSummary() const;
    FText GetResultText(const TSharedPtr<FItem>& Item) const;
    FSlateColor GetResultColor(const TSharedPtr<FItem>& Item) const;
    friend class FCGToolsPublisherUnifiedWindowTest;
};
