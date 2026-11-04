#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"
#include "CGToolsPublisherBatch.h"
#include "CGToolsPublisherPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/STreeView.h"

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

private:
    struct FDirectoryNode
    {
        explicit FDirectoryNode(const FString& InDirectory) : Directory(InDirectory) {}

        FString Directory;
        TArray<TSharedPtr<FDirectoryNode>> Children;
        bool bChildrenLoaded = false;
    };

    FAssetData AssetData;
    TSharedPtr<FCGToolsPublisherDialogState> DialogState;
    FString SelectedDirectory;
    FString DirectoryError;
    TArray<TSharedPtr<FDirectoryNode>> DirectoryRoots;
    TSharedPtr<STreeView<TSharedPtr<FDirectoryNode>>> DirectoryTree;
    bool bPublishing = false;

    void RefreshDirectoryTree();
    void GetDirectoryChildren(TSharedPtr<FDirectoryNode> Item, TArray<TSharedPtr<FDirectoryNode>>& OutChildren);
    TSharedRef<ITableRow> GenerateDirectoryRow(
        TSharedPtr<FDirectoryNode> Item, const TSharedRef<STableViewBase>& OwnerTable) const;
    void OnDirectorySelected(TSharedPtr<FDirectoryNode> Item, ESelectInfo::Type SelectInfo);
    void OnDirectoryClicked(TSharedPtr<FDirectoryNode> Item);
    void OnDirectoryDoubleClicked(TSharedPtr<FDirectoryNode> Item);
    void ShowFolderNameDialog(const FString& Directory, bool bRename);
    FReply OnNewFolder();
    bool CanCreateFolder() const;
    bool CanConfirm() const;
    FReply OnConfirm();
    FReply OnCancel();
    FReply OnSkip();
    void CloseWindow();
};
