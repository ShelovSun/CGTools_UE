#pragma once

#include "AssetRegistry/AssetData.h"
#include "Widgets/SCompoundWidget.h"

class FDeferredCleanupSlateBrush;
struct FSlateBrush;

// Modal windows pump Slate rather than editor thumbnail-pool ticks. Keep a
// resolved image alive, including pending render commands after the dialog closes.
class SCGToolsPublisherAssetPreview : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SCGToolsPublisherAssetPreview) {}
        SLATE_ARGUMENT(FAssetData, AssetData)
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);

private:
    TSharedPtr<FDeferredCleanupSlateBrush> PreviewBrush;
    const FSlateBrush* ClassThumbnail = nullptr;
};
