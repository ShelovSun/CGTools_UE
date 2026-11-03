// Copyright 2017-2021 marynate. All Rights Reserved.

#include "EdGraphNode_ExtDependency.h"
#include "ExtAssetData.h"
#include "ExtPackageUtils.h"
#include "ExtContentBrowser.h"

#include "GenericPlatform/GenericPlatformFile.h"
#include "EdGraph/EdGraphPin.h"
#include "HAL/PlatformFilemanager.h"

#define LOCTEXT_NAMESPACE "ExtDependencyViewer"

//////////////////////////////////////////////////////////////////////////
// UEdGraphNode_ExtDependency

UEdGraphNode_ExtDependency::UEdGraphNode_ExtDependency(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	DependencyPin = NULL;
	ReferencerPin = NULL;
	bIsCollapsed = false;
	bIsPackage = false;
	bIsPrimaryAsset = false;
	bUsesThumbnail = false;
	bIsMissingOrInvalid = false;
	bIsADuplicate = false;
	bIsFiltered = false;
	bIsOverflow = false;
	bAllowThumbnail = true;
	AssetTypeColor = FLinearColor(0.55f, 0.55f, 0.55f);
}

void UEdGraphNode_ExtDependency::SetupReferenceNode(const FIntPoint& NodeLoc, const TArray<FExtAssetIdentifier>& NewIdentifiers, const FExtAssetData& InAssetData, bool bInAllowThumbnail, bool bInIsADuplicate)
{
	check(NewIdentifiers.Num() > 0);

	NodePosX = NodeLoc.X;
	NodePosY = NodeLoc.Y;

	Identifiers = NewIdentifiers;
	const FExtAssetIdentifier& First = NewIdentifiers[0];
	FString MainAssetName = InAssetData.AssetName.ToString();
	FString AssetTypeName = InAssetData.AssetClass.ToString();

	// TODO: Implement asset type color lookup
	AssetTypeColor = FLinearColor(0.4f, 0.62f, 1.0f);
	// AssetBrush = FSlateIcon("EditorStyle", FName( *("ClassIcon." + AssetTypeName)));

	bIsCollapsed = false;
	bIsPackage = true;
	bAllowThumbnail = bInAllowThumbnail;
	bIsADuplicate = bInIsADuplicate;

	FPrimaryAssetId PrimaryAssetID = NewIdentifiers[0].GetPrimaryAssetId();
	if (PrimaryAssetID.IsValid())  // Management References (PrimaryAssetIDs)
	{
		static FText ManagerText = LOCTEXT("ReferenceManager", "Manager");
		MainAssetName = PrimaryAssetID.PrimaryAssetType.ToString() + TEXT(":") + PrimaryAssetID.PrimaryAssetName.ToString();
		AssetTypeName = ManagerText.ToString();
		bIsPackage = false;
		bIsPrimaryAsset = true;
		AssetTypeColor = FLinearColor(0.2f, 0.8f, 0.2f);
	}
	else if (First.IsValue()) // Searchable Names (GamePlay Tags, Data Table Row Handle)
	{
		MainAssetName = First.ValueName.ToString();
		AssetTypeName = First.ObjectName.ToString();
		bIsPackage = false;
		AssetTypeColor = FLinearColor(0.0f, 0.55f, 0.62f);
	}
	else if (First.IsPackage() && !InAssetData.IsValid())
	{
		const FString PackageNameStr = Identifiers[0].PackageName.ToString();
		if ( PackageNameStr.StartsWith(TEXT("/Script")) )// C++ Packages (/Script Code)
		{
			MainAssetName = PackageNameStr.RightChop(8);
			AssetTypeName = TEXT("Script");
		}
	}

	if (NewIdentifiers.Num() == 1 )
	{
		static const FName NAME_ActorLabel(TEXT("ActorLabel"));
		// InAssetData.GetTagValue(NAME_ActorLabel, MainAssetName);

		// append the type so it shows up on the extra line
		NodeTitle = FText::FromString(FString::Printf(TEXT("%s\n%s"), *MainAssetName, *AssetTypeName));

		if (bIsPackage)
		{
			NodeComment = First.PackageName.ToString();
		}
	}
	else
	{
		NodeTitle = FText::Format(LOCTEXT("ReferenceNodeMultiplePackagesComment", "{0} and {1} others"), FText::FromString(MainAssetName), FText::AsNumber(NewIdentifiers.Num() - 1));
	}

	CacheAssetData(InAssetData);
	AllocateDefaultPins();
}

void UEdGraphNode_ExtDependency::SetReferenceNodeCollapsed(const FIntPoint& NodeLoc, int32 InNumReferencesExceedingMax, const TArray<FExtAssetIdentifier>& InIdentifiers)
{
	NodePosX = NodeLoc.X;
	NodePosY = NodeLoc.Y;

	if (InIdentifiers.Num() > 0)
	{
		Identifiers = InIdentifiers;
	}
	bIsCollapsed = true;
	bUsesThumbnail = false;
	bIsOverflow = true;
	// AssetBrush = FSlateIcon(FAppStyle::GetAppStyleSetName(), "Icons.WarningWithColor");

	NodeTitle = FText::Format( LOCTEXT("ReferenceNodeCollapsedTitle", "{0} Collapsed nodes"), FText::AsNumber(InNumReferencesExceedingMax));
	CacheAssetData(FExtAssetData());
	AllocateDefaultPins();
}

void UEdGraphNode_ExtDependency::AddReferencer(UEdGraphNode_ExtDependency* ReferencerNode)
{
	UEdGraphPin* ReferencerDependencyPin = ReferencerNode->GetDependencyPin();

	if ( ensure(ReferencerDependencyPin) )
	{
		ReferencerDependencyPin->bHidden = false;
		ReferencerPin->bHidden = false;
		ReferencerPin->MakeLinkTo(ReferencerDependencyPin);
	}
}

FExtAssetIdentifier UEdGraphNode_ExtDependency::GetIdentifier() const
{
	if (Identifiers.Num() > 0)
	{
		return Identifiers[0];
	}

	return FExtAssetIdentifier();
}

void UEdGraphNode_ExtDependency::GetAllIdentifiers(TArray<FExtAssetIdentifier>& OutIdentifiers) const
{
	OutIdentifiers.Append(Identifiers);
}

void UEdGraphNode_ExtDependency::GetAllPackageNames(TArray<FName>& OutPackageNames) const
{
	for (const FExtAssetIdentifier& AssetId : Identifiers)
	{
		if (AssetId.IsPackage())
		{
			OutPackageNames.AddUnique(AssetId.PackageName);
		}
	}
}

UEdGraph_ExtDependencyViewer* UEdGraphNode_ExtDependency::GetDependencyViewerGraph() const
{
	return Cast<UEdGraph_ExtDependencyViewer>( GetGraph() );
}

FText UEdGraphNode_ExtDependency::GetNodeTitle(ENodeTitleType::Type TitleType) const
{
	return NodeTitle;
}

FLinearColor UEdGraphNode_ExtDependency::GetNodeTitleColor() const
{
	if (bIsPrimaryAsset)
	{
		return FLinearColor(0.2f, 0.8f, 0.2f);
	}
	else if (bIsPackage)
	{
		return AssetTypeColor;
	}
	else if (bIsCollapsed)
	{
		return FLinearColor(0.55f, 0.55f, 0.55f);
	}
	else
	{
		return FLinearColor(0.0f, 0.55f, 0.62f);
	}
}

FSlateIcon UEdGraphNode_ExtDependency::GetIconAndTint(FLinearColor& OutColor) const
{
	OutColor = bIsOverflow ? FLinearColor::White : AssetTypeColor;
	return AssetBrush;
}

bool UEdGraphNode_ExtDependency::AllowsThumbnail() const
{
	return bAllowThumbnail;
}

void UEdGraphNode_ExtDependency::SetIsFiltered(bool bInFiltered)
{
	bIsFiltered = bInFiltered;
}

bool UEdGraphNode_ExtDependency::GetIsFiltered() const
{
	return bIsFiltered;
}

FText UEdGraphNode_ExtDependency::GetTooltipText() const
{
	FString TooltipString;
	for (const FExtAssetIdentifier& AssetId : Identifiers)
	{
		if (!TooltipString.IsEmpty())
		{
			TooltipString.Append(TEXT("\n"));
		}
		TooltipString.Append(AssetId.ToString());
	}
	return FText::FromString(TooltipString);
}

void UEdGraphNode_ExtDependency::AllocateDefaultPins()
{
	ReferencerPin = CreatePin( EEdGraphPinDirection::EGPD_Input, NAME_None, NAME_None);
	DependencyPin = CreatePin( EEdGraphPinDirection::EGPD_Output, NAME_None, NAME_None);

	ReferencerPin->bHidden = true;
	ReferencerPin->PinType.PinCategory = FName(TEXT("passive"));
	DependencyPin->bHidden = true;
	DependencyPin->PinType.PinCategory = FName(TEXT("passive"));
}

UObject* UEdGraphNode_ExtDependency::GetJumpTargetForDoubleClick() const
{
	if (Identifiers.Num() > 0 )
	{
		GetDependencyViewerGraph()->SetGraphRoot(Identifiers, FIntPoint(NodePosX, NodePosY));
		GetDependencyViewerGraph()->RebuildGraph();
	}
	return NULL;
}

UEdGraphPin* UEdGraphNode_ExtDependency::GetDependencyPin()
{
	return DependencyPin;
}

UEdGraphPin* UEdGraphNode_ExtDependency::GetReferencerPin()
{
	return ReferencerPin;
}

void UEdGraphNode_ExtDependency::CacheAssetData(const FExtAssetData& AssetData)
{
	CachedAssetData = AssetData;
	bUsesThumbnail = false;

	if ( AssetData.IsValid()/* && IsPackage()*/ )
	{
		bUsesThumbnail = true;
		bIsMissingOrInvalid = false;
	}
	else
	{
		if (Identifiers.Num() == 1 )
		{
			const FString PackageNameStr = Identifiers[0].PackageName.ToString();
			if ( FPackageName::IsValidLongPackageName(PackageNameStr, true) )
			{
				bool bIsMapPackage = false;

				const bool bIsScriptPackage = PackageNameStr.StartsWith(TEXT("/Script"));

				if (bIsScriptPackage)
				{
					CachedAssetData.AssetClass = FName(TEXT("Code"));

					bIsMissingOrInvalid = !FExtPackageUtils::DoesPackageExist(PackageNameStr);
					if (bIsMissingOrInvalid)
					{
						CachedAssetData.AssetClass = FName(TEXT("Code Missing"));
					}
				}
				else
				{
					const FString PotentiallyMapFilename = FPackageName::LongPackageNameToFilename(PackageNameStr, FPackageName::GetMapPackageExtension());
					bIsMapPackage = FPlatformFileManager::Get().GetPlatformFile().FileExists(*PotentiallyMapFilename);
					if ( bIsMapPackage )
					{
						CachedAssetData.AssetClass = FName(TEXT("World"));

						bIsMissingOrInvalid = !FExtPackageUtils::DoesPackageExist(PackageNameStr);
						if (bIsMissingOrInvalid)
						{
							CachedAssetData.AssetClass = FName(TEXT("Map Missing"));
						}
					}
				}

				if (!bIsScriptPackage && !bIsMapPackage)
				{
					CachedAssetData = FExtAssetData(Identifiers[0].PackageName);
					bUsesThumbnail = CachedAssetData.HasThumbnail();

					const FString PackageFileStr = CachedAssetData.PackageFilePath.ToString();
					if (CachedAssetData.IsUAsset())
					{
						bIsMissingOrInvalid = !FExtAssetValidator::ValidateDependency({ CachedAssetData });
						if (bIsMissingOrInvalid)
						{
							CachedAssetData.AssetClass = FName(*CachedAssetData.GetInvalidReason());
						}
					}
					else
					{
						bIsMissingOrInvalid = !FExtPackageUtils::DoesPackageExist(PackageNameStr);
						if (bIsMissingOrInvalid)
						{
							CachedAssetData.AssetClass = FName(TEXT("Package Missing"));
						}
					}
				}
			}
		}
		else
		{
			CachedAssetData = FExtAssetData();
			CachedAssetData.AssetClass = FName(TEXT("Multiple Nodes"));
		}
	}
}

FExtAssetData UEdGraphNode_ExtDependency::GetAssetData() const
{
	return CachedAssetData;
}

bool UEdGraphNode_ExtDependency::UsesThumbnail() const
{
	return bUsesThumbnail && bAllowThumbnail;
}

bool UEdGraphNode_ExtDependency::IsPackage() const
{
	return bIsPackage;
}

bool UEdGraphNode_ExtDependency::IsCollapsed() const
{
	return bIsCollapsed;
}

bool UEdGraphNode_ExtDependency::IsMissingOrInvalid() const
{
	return bIsMissingOrInvalid;
}

#undef LOCTEXT_NAMESPACE
