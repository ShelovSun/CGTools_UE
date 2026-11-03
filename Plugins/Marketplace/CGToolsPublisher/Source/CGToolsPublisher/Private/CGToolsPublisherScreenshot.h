#pragma once

#include "CoreMinimal.h"

class SWindow;

namespace CGToolsPublisher
{
    // False with an empty error means the user canceled. Runs on the editor thread.
    bool CaptureScreenshotPixels(
        TArray<FColor>& OutPixels,
        FIntPoint& OutSize,
        const TSharedPtr<SWindow>& ParentWindow,
        FText& OutError);
}
