#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"
#include "CGToolsPublisherBatch.h"
#include "CGToolsPublisherPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/STreeView.h"

class SCGToolsVfxDestinationBrowser;

namespace CGToolsVfxPublisher
{
    bool IsEffectAsset(const FAssetData& Asset);
}

class SCGToolsVfxPublisherWindow : public SCompoundWidget, public ICGToolsPublisherPanel
{
public:
    SLATE_BEGIN_ARGS(SCGToolsVfxPublisherWindow) {}
        SLATE_ARGUMENT(FAssetData, AssetData)
        SLATE_ARGUMENT(TSharedPtr<FCGToolsPublisherDialogState>, DialogState)
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);
    virtual FCGToolsPublisherSharedSettings GetSharedSettings() const override;
    virtual void ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings) override;
    virtual bool ValidateBatch(FString& OutDestination, FString& OutError) override;
    virtual void PublishBatch() override { OnConfirm(); }
    virtual bool ReviewsPublishFiles() const override { return true; }

private:
    FAssetData AssetData;
    TSharedPtr<FCGToolsPublisherDialogState> DialogState;
    FString SelectedDirectory;
    FString DirectoryError;
    TSharedPtr<SCGToolsVfxDestinationBrowser> DirectoryBrowser;
    bool bPublishing = false;

    void RefreshDirectoryTree();
    void OnDirectoryDoubleClicked(const FString& Directory);
    void ShowFolderNameDialog(const FString& Directory, bool bRename);
    FReply OnNewFolder();
    bool CanCreateFolder() const;
    bool CanConfirm() const;
    FReply OnConfirm();
    FReply OnCancel();
    FReply OnSkip();
    void CloseWindow();
};
