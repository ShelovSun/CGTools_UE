// Copyright Epic Games, Inc. All Rights Reserved.

#include "BlueprintScript.h"
#include "BlueprintScriptStyle.h"
#include "BlueprintScriptCommands.h"

#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Text/STextBlock.h"

static const FName BlueprintScriptTabName("BlueprintScript");

#define LOCTEXT_NAMESPACE "FBlueprintScriptModule"

void FBlueprintScriptModule::StartupModule()
{
	// Initialize Style
	FBlueprintScriptStyle::Initialize();
	FBlueprintScriptStyle::ReloadTextures();

	// Register Commands
	FBlueprintScriptCommands::Register();

	// Register Hidden Tab
	FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
		BlueprintScriptTabName,
		FOnSpawnTab::CreateRaw(
			this,
			&FBlueprintScriptModule::OnSpawnPluginTab
		)
	)
		.SetDisplayName(
			LOCTEXT("FBlueprintScriptTabTitle", "BlueprintScript")
		)
		.SetMenuType(ETabSpawnerMenuType::Hidden);
}

void FBlueprintScriptModule::ShutdownModule()
{
	FBlueprintScriptStyle::Shutdown();

	FBlueprintScriptCommands::Unregister();

	FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(
		BlueprintScriptTabName
	);
}

TSharedRef<SDockTab> FBlueprintScriptModule::OnSpawnPluginTab(
	const FSpawnTabArgs& SpawnTabArgs)
{
	return SNew(SDockTab)
		.TabRole(ETabRole::NomadTab)
		[
			SNew(SBox)
				.HAlign(HAlign_Center)
				.VAlign(VAlign_Center)
				[
					SNew(STextBlock)
						.Text(
							LOCTEXT(
								"BlueprintScriptText",
								"BlueprintScript Window"
							)
						)
				]
		];
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FBlueprintScriptModule, BlueprintScript)