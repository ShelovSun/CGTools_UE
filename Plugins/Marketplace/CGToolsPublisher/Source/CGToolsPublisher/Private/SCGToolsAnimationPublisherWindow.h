#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"
#include "CGToolsPublisherBatch.h"
#include "CGToolsPublisherPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Input/SComboBox.h"

class SEditableTextBox;

class SCGToolsAnimationPublisherWindow : public SCompoundWidget, public ICGToolsPublisherPanel
{
public:
    SLATE_BEGIN_ARGS(SCGToolsAnimationPublisherWindow) {}
        SLATE_ARGUMENT(FAssetData, AssetData)
        SLATE_ARGUMENT(TSharedPtr<FCGToolsPublisherDialogState>, DialogState)
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);
    virtual FCGToolsPublisherSharedSettings GetSharedSettings() const override;
    virtual void ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings) override;
    virtual bool ValidateBatch(FString& OutDestination, FString& OutError) override;
    virtual FString GetPerAssetSettingsKey() const override;
    virtual void PublishBatch() override { OnConfirm(); }

private:
    FAssetData AssetData;
    TSharedPtr<FCGToolsPublisherDialogState> DialogState;
    TArray<TSharedPtr<FString>> ProjectOptions;
    TArray<TSharedPtr<FString>> TypeOptions;
    TSharedPtr<FString> SelectedProject;
    TSharedPtr<FString> SelectedType;
    TSharedPtr<SComboBox<TSharedPtr<FString>>> ProjectCombo;
    TSharedPtr<SComboBox<TSharedPtr<FString>>> TypeCombo;
    TSharedPtr<SEditableTextBox> AssetNameTextBox;
    TSharedPtr<SEditableTextBox> ActionNameTextBox;
    FString ConfigError;
    bool bPublishing = false;
    bool bNotifyMaya = false;

    FReply OnConfirm();
    FReply OnCancel();
    FReply OnSkip();
    void CloseWindow();
};
