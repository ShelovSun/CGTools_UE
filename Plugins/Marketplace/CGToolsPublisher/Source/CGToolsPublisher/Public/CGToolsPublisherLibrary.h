#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CGToolsPublisherLibrary.generated.h"

UCLASS()
class CGTOOLSPUBLISHER_API UCGToolsPublisherLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Opens the existing desktop region selector and writes the accepted region as PNG.
     * An unaccepted capture with an empty error means cancellation.
     * Outputs are explicit so Python also receives the error on failure.
     */
    UFUNCTION(BlueprintCallable, Category = "CGTools|Publisher")
    static void CaptureScreenshotToFile(
        const FString& OutputFilename, bool& bOutAccepted, FString& OutError);
};
