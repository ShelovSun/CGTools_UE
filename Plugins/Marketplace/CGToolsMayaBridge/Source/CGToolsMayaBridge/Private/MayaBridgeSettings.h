// Copyright CGTools. All Rights Reserved.

#pragma once

#include "MayaBridgeTypes.h"

class FMayaBridgeSettingsLoader
{
public:
    static FMayaBridgeSettings Load();
    static FString GetConfigPath();
};
