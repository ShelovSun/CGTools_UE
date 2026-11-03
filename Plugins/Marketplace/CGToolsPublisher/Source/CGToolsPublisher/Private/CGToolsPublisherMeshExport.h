#pragma once

#include "CoreMinimal.h"

namespace CGToolsPublisher
{
    // Shared by the publish window and the native FBX export regression test.
    bool ExportMeshFbx(UObject* Asset, const FString& DestinationFile, FString& OutError);
}
