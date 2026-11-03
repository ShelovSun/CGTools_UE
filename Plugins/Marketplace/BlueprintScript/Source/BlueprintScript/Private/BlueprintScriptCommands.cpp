// Copyright Epic Games, Inc. All Rights Reserved.

#include "BlueprintScriptCommands.h"

#define LOCTEXT_NAMESPACE "FBlueprintScriptModule"

void FBlueprintScriptCommands::RegisterCommands()
{
	UI_COMMAND(OpenPluginWindow, "BlueprintScript", "Bring up BlueprintScript window", EUserInterfaceActionType::Button, FInputChord());
}

#undef LOCTEXT_NAMESPACE
