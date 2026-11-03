// Copyright 2017-2021 marynate. All Rights Reserved.

#pragma once

#include "ExtAssetData.h"

#include "CoreMinimal.h"
#include "UObject/ObjectMacros.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph_ExtDependencyViewer.h"

#include "EdGraphNode_ExtDependency.generated.h"

class UEdGraphPin;

UCLASS()
class UEdGraphNode_ExtDependency : public UEdGraphNode
{
	GENERATED_UCLASS_BODY()

	/** Returns first asset identifier */
	FExtAssetIdentifier GetIdentifier() const;

	/** Returns all identifiers on this node including virtual things */
	void GetAllIdentifiers(TArray<FExtAssetIdentifier>& OutIdentifiers) const;

	/** Returns only the packages in this node, skips searchable names */
	void GetAllPackageNames(TArray<FName>& OutPackageNames) const;

	/** Returns our owning graph */
	UEdGraph_ExtDependencyViewer* GetDependencyViewerGraph() const;

	// UEdGraphNode implementation
	virtual FText GetNodeTitle(ENodeTitleType::Type TitleType) const override;
	FLinearColor GetNodeTitleColor() const override;
	virtual FText GetTooltipText() const override;
	virtual void AllocateDefaultPins() override;
	virtual UObject* GetJumpTargetForDoubleClick() const override;
	virtual FSlateIcon GetIconAndTint(FLinearColor& OutColor) const override;
	virtual bool ShowPaletteIconOnNode() const override { return true; }
	// End UEdGraphNode implementation

	void SetAllowThumbnail(bool bInAllow) { bAllowThumbnail = bInAllow; }
	bool AllowsThumbnail() const;
	bool UsesThumbnail() const;
	bool IsPackage() const;
	bool IsCollapsed() const;
	bool IsADuplicate() const { return bIsADuplicate; }

	// Nodes that are filtered out still may still show because they
	// are between nodes that pass the filter and the root.  This "filtered"
	// bool allows us to render these in-between nodes differently
	void SetIsFiltered(bool bInFiltered);
	bool GetIsFiltered() const;

	bool IsOverflow() const { return bIsOverflow; }

	FExtAssetData GetAssetData() const;

	bool IsMissingOrInvalid() const;

	UEdGraphPin* GetDependencyPin();
	UEdGraphPin* GetReferencerPin();

public:
	void SetupReferenceNode(const FIntPoint& NodeLoc, const TArray<FExtAssetIdentifier>& NewIdentifiers, const FExtAssetData& InAssetData, bool bInAllowThumbnail = true, bool bInIsADuplicate = false);
	void SetReferenceNodeCollapsed(const FIntPoint& NodeLoc, int32 InNumReferencesExceedingMax, const TArray<FExtAssetIdentifier>& Identifiers = TArray<FExtAssetIdentifier>());

private:
	void CacheAssetData(const FExtAssetData& AssetData);
	void AddReferencer(class UEdGraphNode_ExtDependency* ReferencerNode);

	TArray<FExtAssetIdentifier> Identifiers;
	FText NodeTitle;

	bool bAllowThumbnail;
	bool bUsesThumbnail;
	bool bIsPackage;
	bool bIsPrimaryAsset;
	bool bIsCollapsed;
	bool bIsADuplicate;
	bool bIsFiltered;
	bool bIsOverflow;
	bool bIsMissingOrInvalid;

	FExtAssetData CachedAssetData;
	FLinearColor AssetTypeColor;
	FSlateIcon AssetBrush;

	UEdGraphPin* DependencyPin;
	UEdGraphPin* ReferencerPin;

	friend UEdGraph_ExtDependencyViewer;
};


