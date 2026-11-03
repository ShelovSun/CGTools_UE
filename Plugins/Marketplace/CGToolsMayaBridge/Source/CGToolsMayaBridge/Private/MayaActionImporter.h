// Copyright CGTools. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "AssetRegistry/AssetData.h"
#include "MayaBridgeTypes.h"

class FMayaActionImporter
{
public:
    explicit FMayaActionImporter(const FMayaBridgeSettings& InSettings);

    void PromptAndImport(const FMayaBridgeMessage& Message);
    static void CancelPendingFocus();

private:
    bool ImportAction(const FMayaPublishedAction& Action, FString& OutError,
        TArray<FAssetData>& OutImportedAnimations) const;
    static void FocusImportedAnimations(const TArray<FAssetData>& ImportedAnimations);
    FString BuildPrompt(const FMayaBridgeMessage& Message) const;

    FMayaBridgeSettings Settings;

#if WITH_DEV_AUTOMATION_TESTS
    friend class FMayaAnimationFocusIntegrationTest;
#endif
};
