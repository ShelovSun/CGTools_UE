// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "Framework/Commands/Commands.h"
#include "BlueprintScriptStyle.h"

class FBlueprintScriptCommands : public TCommands<FBlueprintScriptCommands>
{
public:

	FBlueprintScriptCommands()
		: TCommands<FBlueprintScriptCommands>(TEXT("BlueprintScript"), NSLOCTEXT("Contexts", "BlueprintScript", "BlueprintScript Plugin"), NAME_None, FBlueprintScriptStyle::GetStyleSetName())
	{
	}

	// TCommands<> interface
	virtual void RegisterCommands() override;

public:
	TSharedPtr< FUICommandInfo > OpenPluginWindow;
};