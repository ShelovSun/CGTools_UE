#pragma once

#include "AssetRegistry/AssetData.h"
#include "CoreMinimal.h"

enum class ECGToolsPublisherKind : uint8
{
    None,
    StaticMesh,
    SkeletalMesh,
    Animation,
    Vfx
};

enum class ECGToolsPublisherDialogResult : uint8
{
    Cancelled,
    Published,
    Skipped
};

struct FCGToolsPublisherDialogState
{
    FCGToolsPublisherDialogState(int32 InIndex = 1, int32 InCount = 1)
        : Index(InIndex), Count(InCount) {}

    const int32 Index;
    const int32 Count;
    bool bPublishing = false;
    bool bEmbedded = false;
    bool bBatchExecution = false;
    bool bWarning = false;
    bool bPartial = false;
    FString Error;
    FString Completion;
    ECGToolsPublisherDialogResult Result = ECGToolsPublisherDialogResult::Cancelled;

    bool IsBatch() const { return Count > 1; }
};

// One non-modal window owns the complete immutable selection snapshot.
class FCGToolsPublisherBatch
{
public:
    using FShowDialog = TFunction<void(const TArray<FAssetData>&, const TSharedRef<FCGToolsPublisherDialogState>&)>;

    FCGToolsPublisherBatch(TArray<FAssetData> InAssets, FShowDialog InShowDialog);
    void Start();
    void OnDialogClosed(const TSharedRef<FCGToolsPublisherDialogState>& State);
    void Cancel();
    bool IsFinished() const { return bFinished; }

private:
    TArray<FAssetData> Assets;
    FShowDialog ShowDialog;
    TSharedPtr<FCGToolsPublisherDialogState> CurrentState;
    bool bFinished = false;
};

namespace CGToolsPublisher
{
    // All selected assets must have the same supported asset class. In
    // particular, a mixed Niagara/Cascade selection is not homogeneous.
    ECGToolsPublisherKind GetSelectionKind(const TArray<FAssetData>& Assets);

    // The owner keeps the complete selection alive until its one window closes.
    TSharedPtr<FCGToolsPublisherBatch> RunBatch(TArray<FAssetData> Assets,
        FCGToolsPublisherBatch::FShowDialog ShowDialog);
}
