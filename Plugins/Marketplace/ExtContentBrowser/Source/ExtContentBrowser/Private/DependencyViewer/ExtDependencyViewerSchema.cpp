// Copyright 2017-2021 marynate. All Rights Reserved.

#include "ExtDependencyViewerSchema.h"
#include "ExtContentBrowser.h"
#include "ExtContentBrowserStyle.h"
#include "ExtContentBrowserSettings.h"
#include "ExtDependencyViewerCommands.h"
#include "SExtDependencyViewer.h"

#include "Textures/SlateIcon.h"
#include "Misc/Attribute.h"
#include "ToolMenus.h"
#include "EdGraph/EdGraph.h"
#include "EditorStyleSet.h"
#include "CollectionManagerTypes.h"
#include "Toolkits/GlobalEditorCommonCommands.h"
#include "ConnectionDrawingPolicy.h"


namespace UAssetBrowser
{
	namespace DependencyPinCategory
	{
		FName NamePassive(TEXT("Passive"));
		FName NameHardUsedInGame(TEXT("Hard"));
		FName NameHardEditorOnly(TEXT("HardEditorOnly"));
		FName NameSoftUsedInGame(TEXT("Soft"));
		FName NameSoftEditorOnly(TEXT("SoftEditorOnly"));
		const FLinearColor ColorPassive = FLinearColor(128, 128, 128);
		const FLinearColor ColorHardUsedInGame = FLinearColor(FColor(236, 252, 227)); // RiceFlower
		const FLinearColor ColorHardEditorOnly = FLinearColor(FColor(118, 126, 114));
		const FLinearColor ColorSoftUsedInGame = FLinearColor(FColor(145, 66, 117)); // CannonPink
		const FLinearColor ColorSoftEditorOnly = FLinearColor(FColor(73, 33, 58));

		const FLinearColor RiceFlower = FLinearColor(FColor(236, 252, 227));
		const FLinearColor CannonPink = FLinearColor(FColor(145, 66, 117));
		const FLinearColor CannonPinkRed = FLinearColor(FColor(245, 66, 11));
	}
}

EExtDependencyPinCategory ParseDependencyPinCategory(FName PinCategory)
{
	if (PinCategory == UAssetBrowser::DependencyPinCategory::NameHardUsedInGame)
	{
		return EExtDependencyPinCategory::LinkEndActive | EExtDependencyPinCategory::LinkTypeHard | EExtDependencyPinCategory::LinkTypeUsedInGame;
	}
	else if (PinCategory == UAssetBrowser::DependencyPinCategory::NameHardEditorOnly)
	{
		return EExtDependencyPinCategory::LinkEndActive | EExtDependencyPinCategory::LinkTypeHard;
	}
	else if (PinCategory == UAssetBrowser::DependencyPinCategory::NameSoftUsedInGame)
	{
		return EExtDependencyPinCategory::LinkEndActive | EExtDependencyPinCategory::LinkTypeUsedInGame;
	}
	else if (PinCategory == UAssetBrowser::DependencyPinCategory::NameSoftEditorOnly)
	{
		return EExtDependencyPinCategory::LinkEndActive;
	}
	else
	{
		return EExtDependencyPinCategory::LinkEndPassive;
	}
}

FName GetName(EExtDependencyPinCategory Category)
{
	if ((Category & EExtDependencyPinCategory::LinkEndMask) == EExtDependencyPinCategory::LinkEndPassive)
	{
		return UAssetBrowser::DependencyPinCategory::NamePassive;
	}
	else
	{
		switch (Category & EExtDependencyPinCategory::LinkTypeMask)
		{
		case EExtDependencyPinCategory::LinkTypeHard | EExtDependencyPinCategory::LinkTypeUsedInGame:
			return UAssetBrowser::DependencyPinCategory::NameHardUsedInGame;
		case EExtDependencyPinCategory::LinkTypeHard:
			return UAssetBrowser::DependencyPinCategory::NameHardEditorOnly;
		case EExtDependencyPinCategory::LinkTypeUsedInGame:
			return UAssetBrowser::DependencyPinCategory::NameSoftUsedInGame;
		default:
			return UAssetBrowser::DependencyPinCategory::NameSoftEditorOnly;
		}
	}
}

FLinearColor GetColor(EExtDependencyPinCategory Category)
{
	if ((Category & EExtDependencyPinCategory::LinkEndMask) == EExtDependencyPinCategory::LinkEndPassive)
	{
		return UAssetBrowser::DependencyPinCategory::ColorPassive;
	}
	else
	{
		switch (Category & EExtDependencyPinCategory::LinkTypeMask)
		{
		case EExtDependencyPinCategory::LinkTypeHard | EExtDependencyPinCategory::LinkTypeUsedInGame:
			return UAssetBrowser::DependencyPinCategory::ColorHardUsedInGame;
		case EExtDependencyPinCategory::LinkTypeHard:
			return UAssetBrowser::DependencyPinCategory::ColorHardEditorOnly;
		case EExtDependencyPinCategory::LinkTypeUsedInGame:
			return UAssetBrowser::DependencyPinCategory::ColorSoftUsedInGame;
		default:
			return UAssetBrowser::DependencyPinCategory::ColorSoftEditorOnly;
		}
	}
}

// Overridden connection drawing policy to use less curvy lines between nodes
class FExtDependencyViewerConnectionDrawingPolicy : public FConnectionDrawingPolicy
{
public:
	FExtDependencyViewerConnectionDrawingPolicy(int32 InBackLayerID, int32 InFrontLayerID, float InZoomFactor, const FSlateRect& InClippingRect, FSlateWindowElementList& InDrawElements)
		: FConnectionDrawingPolicy(InBackLayerID, InFrontLayerID, InZoomFactor, InClippingRect, InDrawElements)
	{
	}

	virtual FVector2f ComputeSplineTangent(const FVector2f& Start, const FVector2f& End) const override
	{
		const UExtContentBrowserSettings* ExtContentBrowserSetting = GetDefault<UExtContentBrowserSettings>();
		const bool bSpline = !ExtContentBrowserSetting->UseStraightLineInDependencyViewer;

		if (bSpline)
		{
			const int32 Tension = FMath::Abs<int32>(Start.X - End.X);
			return Tension * FVector2f(1.0f, 0);
		}
		else
		{
			const FVector2f Delta = End - Start;
			const FVector2f NormDelta = Delta.GetSafeNormal();
			return NormDelta;
		}
	}

	virtual void DetermineWiringStyle(UEdGraphPin* OutputPin, UEdGraphPin* InputPin, /*inout*/ FConnectionParams& Params) override
	{
		const bool bHardRefernce = OutputPin->PinType.PinCategory == TEXT("hard") || InputPin->PinType.PinCategory == TEXT("hard");
		const bool bInvalid = OutputPin->PinType.PinSubCategory == TEXT("invalid") || InputPin->PinType.PinSubCategory == TEXT("invalid");

		if (bHardRefernce)
		{
			if (bInvalid)
			{
				Params.WireColor = FExtContentBrowserStyle::Get().GetColor("ErrorReporting.HardReferenceColor");
			}
			else
			{
				Params.WireColor = UAssetBrowser::DependencyPinCategory::ColorHardUsedInGame;// RiceFlower;
			}
		}
		else
		{
			if (bInvalid)
			{
				Params.WireColor = FExtContentBrowserStyle::Get().GetColor("ErrorReporting.SoftReferenceColor");
			}
			else
			{
				Params.WireColor = UAssetBrowser::DependencyPinCategory::ColorSoftUsedInGame;// CannonPink;
			}
		}
	}
};

//////////////////////////////////////////////////////////////////////////
// UExtDependencyViewerSchema

UExtDependencyViewerSchema::UExtDependencyViewerSchema(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
}

void UExtDependencyViewerSchema::GetContextMenuActions(UToolMenu* Menu, UGraphNodeContextMenuContext* Context) const
{
	{
		FToolMenuSection& Section = Menu->AddSection(TEXT("Fit"), NSLOCTEXT("ReferenceViewerSchema", "FitSectionLabel", "Fit"));
		Section.AddMenuEntry(FExtDependencyViewerCommands::Get().ZoomToFitSelected);
	}

#if ECB_LEGACY
	{
		FToolMenuSection& Section = Menu->AddSection(TEXT("Asset"), NSLOCTEXT("ReferenceViewerSchema", "AssetSectionLabel", "Asset"));
		Section.AddMenuEntry(FGlobalEditorCommonCommands::Get().FindInContentBrowser);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().OpenSelectedInAssetEditor);
	}

	{
		FToolMenuSection& Section = Menu->AddSection(TEXT("Misc"), NSLOCTEXT("ReferenceViewerSchema", "MiscSectionLabel", "Misc"));
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ZoomToFit);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ReCenterGraph);
		Section.AddSubMenu(
			"MakeCollectionWith",
			NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithTitle", "Make Collection with"),
			NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithTooltip", "Makes a collection with either the referencers or dependencies of the selected nodes."),
			FNewToolMenuDelegate::CreateUObject(const_cast<UReferenceViewerSchema*>(this), &UReferenceViewerSchema::GetMakeCollectionWithSubMenu)
		);
	}

	{
		FToolMenuSection& Section = Menu->AddSection(TEXT("References"), NSLOCTEXT("ReferenceViewerSchema", "ReferencesSectionLabel", "References"));
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().CopyReferencedObjects);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().CopyReferencingObjects);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ShowReferencedObjects);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ShowReferencingObjects);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ShowReferenceTree);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().ViewSizeMap);

		FToolMenuEntry ViewAssetAuditEntry = FToolMenuEntry::InitMenuEntry(FAssetManagerEditorCommands::Get().ViewAssetAudit);
		ViewAssetAuditEntry.Name = TEXT("ContextMenu");
		Section.AddEntry(ViewAssetAuditEntry);
	}
#endif
}

FLinearColor UExtDependencyViewerSchema::GetPinTypeColor(const FEdGraphPinType& PinType) const
{
	return GetColor(ParseDependencyPinCategory(PinType.PinCategory));
}

void UExtDependencyViewerSchema::BreakPinLinks(UEdGraphPin& TargetPin, bool bSendsNodeNotifcation) const
{
	// Don't allow breaking any links
}

void UExtDependencyViewerSchema::BreakSinglePinLink(UEdGraphPin* SourcePin, UEdGraphPin* TargetPin) const
{
	// Don't allow breaking any links
}

FPinConnectionResponse UExtDependencyViewerSchema::MovePinLinks(UEdGraphPin& MoveFromPin, UEdGraphPin& MoveToPin, bool bIsIntermediateMove, bool bNotifyLinkedNodes) const
{
	// Don't allow moving any links
	return FPinConnectionResponse(CONNECT_RESPONSE_DISALLOW, FString());
}

FPinConnectionResponse UExtDependencyViewerSchema::CopyPinLinks(UEdGraphPin& CopyFromPin, UEdGraphPin& CopyToPin, bool bIsIntermediateCopy) const
{
	// Don't allow copying any links
	return FPinConnectionResponse(CONNECT_RESPONSE_DISALLOW, FString());
}

FConnectionDrawingPolicy* UExtDependencyViewerSchema::CreateConnectionDrawingPolicy(int32 InBackLayerID, int32 InFrontLayerID, float InZoomFactor, const FSlateRect& InClippingRect, class FSlateWindowElementList& InDrawElements, class UEdGraph* InGraphObj) const
{
	return new FExtDependencyViewerConnectionDrawingPolicy(InBackLayerID, InFrontLayerID, InZoomFactor, InClippingRect, InDrawElements);
}

void UExtDependencyViewerSchema::GetAssetsGraphHoverMessage(const TArray<FAssetData>& Assets, const UEdGraph* HoverGraph, FString& OutTooltipText, bool& OutOkIcon) const
{
	OutOkIcon = true;
}

void UExtDependencyViewerSchema::GetMakeCollectionWithSubMenu(UToolMenu* Menu)
{
#if ECB_LEGACY
	FToolMenuSection& Section = Menu->AddSection("Section");

	Section.AddSubMenu(
		"MakeCollectionWithReferencers",
		NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithReferencersTitle", "Referencers <-"),
		NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithReferencersTooltip", "Makes a collection with assets one connection to the left of selected nodes."),
		FNewToolMenuDelegate::CreateUObject(this, &UReferenceViewerSchema::GetMakeCollectionWithReferencersOrDependenciesSubMenu, true)
		);

	Section.AddSubMenu(
		"MakeCollectionWithDependencies",
		NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithDependenciesTitle", "Dependencies ->"),
		NSLOCTEXT("ReferenceViewerSchema", "MakeCollectionWithDependenciesTooltip", "Makes a collection with assets one connection to the right of selected nodes."),
		FNewToolMenuDelegate::CreateUObject(this, &UReferenceViewerSchema::GetMakeCollectionWithReferencersOrDependenciesSubMenu, false)
		);
#endif
}

void UExtDependencyViewerSchema::GetMakeCollectionWithReferencersOrDependenciesSubMenu(UToolMenu* Menu, bool bReferencers)
{
#if ECB_LEGACY
	FToolMenuSection& Section = Menu->AddSection("Section");

	if (bReferencers)
	{
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakeLocalCollectionWithReferencers, 
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Local), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Local))
			);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakePrivateCollectionWithReferencers,
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Private), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Private))
			);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakeSharedCollectionWithReferencers,
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Shared), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Shared))
			);
	}
	else
	{
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakeLocalCollectionWithDependencies, 
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Local), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Local))
			);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakePrivateCollectionWithDependencies,
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Private), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Private))
			);
		Section.AddMenuEntry(FAssetManagerEditorCommands::Get().MakeSharedCollectionWithDependencies,
			TAttribute<FText>(),
			ECollectionShareType::GetDescription(ECollectionShareType::CST_Shared), 
			FSlateIcon(FAppStyle::GetStyleSetName(), ECollectionShareType::GetIconStyleName(ECollectionShareType::CST_Shared))
			);
	}
#endif
}
