#pragma once

#include "CoreMinimal.h"

// Only these settings are shared. Names, Chinese names and captured icons
// remain on their own asset panel when the user switches the selected row.
struct FCGToolsPublisherSharedSettings
{
    FString Project;
    FString Type;
    FString Directory;
    bool bIcon = true;
    bool bFbx = true;
    bool bTextures = false;
    bool bNotifyMaya = false;
};

class ICGToolsPublisherPanel
{
public:
    virtual ~ICGToolsPublisherPanel() = default;
    virtual FCGToolsPublisherSharedSettings GetSharedSettings() const = 0;
    virtual void ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings) = 0;
    // Validate without exporting or writing server files. Return the unique
    // output destination so the host can reject unintended overwrites.
    virtual bool ValidateBatch(FString& OutDestination, FString& OutError) = 0;
    virtual void PublishBatch() = 0;
    virtual FString GetRecordLabel() const { return FString(); }
    virtual FString GetPerAssetSettingsKey() const { return GetRecordLabel(); }
    virtual void SetRecordLabel(const FString&) {}
    virtual void SetGroupPanels(const TArray<TSharedPtr<ICGToolsPublisherPanel>>&) {}
};
