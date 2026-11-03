#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"
#include "CGToolsPublisherBatch.h"
#include "CGToolsPublisherPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Input/SComboBox.h"
#include "UObject/StrongObjectPtr.h"

class FAssetThumbnail;
class FAssetThumbnailPool;
class FDeferredCleanupSlateBrush;
struct FSlateBrush;
class SCheckBox;
class SEditableText;
class SEditableTextBox;
class SProgressBar;
class STextBlock;
class SWindow;

struct FCGToolsPublisherConfig
{
    TArray<FString> Projects;
    FString RootPath;
    FString Host;
    FString ScenesFolder = TEXT("Scenes");
    FString AssetsFolder = TEXT("Assets");
    FString Error;

    bool IsValid() const
    {
        return Error.IsEmpty() && !RootPath.IsEmpty() && !Host.IsEmpty() && Projects.Num() > 0;
    }
};

class SCGToolsPublisherWindow : public SCompoundWidget, public ICGToolsPublisherPanel
{
public:
    SLATE_BEGIN_ARGS(SCGToolsPublisherWindow) {}
        SLATE_ARGUMENT(FAssetData, AssetData)
        SLATE_ARGUMENT(TSharedPtr<FCGToolsPublisherDialogState>, DialogState)
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);
    virtual FCGToolsPublisherSharedSettings GetSharedSettings() const override;
    virtual void ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings) override;
    virtual bool ValidateBatch(FString& OutDestination, FString& OutError) override;
    virtual void PublishBatch() override { OnPublishClicked(); }
    FString GetSourceFolder() const { return MeshAssetFolder; }
    static FCGToolsPublisherConfig LoadConfig();
    virtual FString GetRecordLabel() const override;
    virtual FString GetPerAssetSettingsKey() const override;
    virtual void SetRecordLabel(const FString& Label) override;
    virtual void SetGroupPanels(const TArray<TSharedPtr<ICGToolsPublisherPanel>>& Panels) override;

private:
    friend class FCGToolsPublisherMeshPromotionTest;
    FAssetData AssetData;
    TSharedPtr<FCGToolsPublisherDialogState> DialogState;
    TStrongObjectPtr<UObject> PublishAsset;
    TArray<TWeakPtr<SCGToolsPublisherWindow>> BatchMeshPanels;
    bool bSkeletalMeshPublish = false;
    FString MeshAssetFolder;
    FCGToolsPublisherConfig Config;

    TArray<TSharedPtr<FString>> ProjectOptions;
    TArray<TSharedPtr<FString>> TypeOptions;
    TSharedPtr<FString> SelectedProject;
    TSharedPtr<FString> SelectedType;

    TSharedPtr<SComboBox<TSharedPtr<FString>>> ProjectCombo;
    TSharedPtr<SComboBox<TSharedPtr<FString>>> TypeCombo;
    TSharedPtr<SEditableText> TypeTextBox;
    TSharedPtr<SEditableTextBox> AssetNameTextBox;
    TSharedPtr<SEditableTextBox> ChineseNameTextBox;
    TSharedPtr<SCheckBox> PublishIconCheckBox;
    TSharedPtr<SCheckBox> PublishFbxCheckBox;
    TSharedPtr<SCheckBox> PublishTextureCheckBox;
    TSharedPtr<STextBlock> TargetPathText;
    TSharedPtr<STextBlock> StatusText;
    TSharedPtr<SProgressBar> ProgressBar;

    TSharedPtr<FAssetThumbnailPool> ThumbnailPool;
    TSharedPtr<FAssetThumbnail> AssetThumbnail;
    TArray<FColor> AutomaticIconPixels;
    FIntPoint AutomaticIconSize = FIntPoint::ZeroValue;
    TSharedPtr<FDeferredCleanupSlateBrush> AutomaticIconBrush;
    TArray<FColor> CustomIconPixels;
    FIntPoint CustomIconSize = FIntPoint::ZeroValue;
    // The texture can still be referenced by Slate render commands for a few
    // frames after this widget closes.  Deferred cleanup keeps it alive until
    // the render thread is finished with it.
    TSharedPtr<FDeferredCleanupSlateBrush> CustomIconBrush;

    TOptional<float> Progress = 0.0f;
    bool bIsPublishing = false;

    static FString ReadPublisherName();
    static bool IsSafePathComponent(const FString& Value, FString& OutReason);

    void RefreshTypes();
    void RefreshTargetPath();
    bool IsSkeletalMeshPublish() const;
    FString GetPublishBaseFolder() const;
    FString GetAssetKindLabel() const;
    FString GetSelectedProject() const;
    FString GetSelectedType() const;
    bool ResolveMeshAssetFolder(FString& OutType, FString& OutName, FString& OutError);
    FString GetAssetName() const;
    FString GetAssetRoot() const;

    TSharedRef<SWidget> GenerateComboItem(TSharedPtr<FString> Item) const;
    FText GetProjectComboText() const;
    FText GetTypeComboText() const;
    FText GetPublishBaseFolderPrefixText() const;
    void OnProjectChanged(TSharedPtr<FString> NewValue, ESelectInfo::Type SelectInfo);
    void OnTypeChanged(TSharedPtr<FString> NewValue, ESelectInfo::Type SelectInfo);
    void OnTypeTextChanged(const FText& NewText);
    void OnAssetNameChanged(const FText& NewText);

    FReply OnCaptureIconClicked();
    FReply OnUseAssetThumbnailClicked();
    FReply OnPublishClicked();
    FReply OnCancelClicked();
    FReply OnSkipClicked();
    bool CanPublish() const;
    void CloseWindow();
    void SetProgress(float InProgress, const FText& InStatus);
    void ShowError(const FText& Message) const;
    void ApplyCapturedIcon(TArray<FColor> Pixels, FIntPoint Size);
    void BuildAutomaticIcon(UObject* Asset);
    const FSlateBrush* GetAutomaticIconBrush() const;
    const FSlateBrush* GetCustomIconBrush() const;

    bool ExportFbx(UObject* Asset, const FString& DestinationFile, FString& OutError) const;
    bool ExportMeshOutputs(const FString& StagingRoot, bool bFbx, bool bIcon, FString& OutError) const;
    bool ExportIcon(UObject* Asset, const FString& DestinationFile, FString& OutError) const;
    bool ExportReferencedTextures(
        const TArray<FName>& RootPackageNames,
        const FString& DestinationDirectory,
        int32& OutTextureCount,
        FString& OutError
    ) const;
    bool WriteProjectFile(const FString& DestinationFile, FString& OutError) const;
    static bool PromoteStagedPublish(
        const FString& AssetName,
        const FString& AssetRoot,
        const FString& StagingRoot,
        const FString& ExpectedRelativeAssetFile,
        bool bPublishFbx,
        bool bPublishIcon,
        bool bPublishTextures,
        FString& OutHistoryPath,
        FString& OutError
    );
};
