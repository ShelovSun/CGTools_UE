#pragma once

#include "CoreMinimal.h"

namespace CGToolsPublisher
{
    // Shared by mesh and VFX publishing; keeps BuildPlugin independent of the
    // precompiled AssetRegistryRepair plugin's generated headers.
    bool RepairSourceAssetDisplay(const TArray<FString>& VirtualFolders, FString& OutMessage);
}
