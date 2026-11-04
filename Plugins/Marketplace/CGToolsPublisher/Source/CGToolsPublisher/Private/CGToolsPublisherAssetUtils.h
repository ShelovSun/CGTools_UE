#pragma once

#include "CoreMinimal.h"

namespace CGToolsPublisher
{
    // Shared by mesh and VFX publishing; keeps BuildPlugin independent of the
    // precompiled AssetRegistryRepair plugin's generated headers. Only repairs
    // registration; never navigates or selects items in the Content Browser.
    bool RepairSourceAssetDisplay(const TArray<FString>& VirtualFolders, FString& OutMessage);
}
