#pragma once

#include "CoreMinimal.h"

namespace CGToolsPublisher
{
    // Bake without opening Maya, before committing the three publication files.
    bool BakeAnimationToMaya(const FString& ObjectPath, const FString& OutputMa, FString& OutMessage);
    bool OpenPublishedMayaScene(const FString& SceneMa, FString& OutMessage);
}
