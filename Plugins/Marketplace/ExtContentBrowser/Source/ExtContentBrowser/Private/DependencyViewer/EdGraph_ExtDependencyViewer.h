// Copyright 2017-2021 marynate. All Rights Reserved.

#pragma once

#include "ExtAssetData.h"
#include "ExtDependencyViewerSettings.h"

#include "CoreMinimal.h"
#include "UObject/ObjectMacros.h"
#include "EdGraph/EdGraph.h"
#include "Misc/AssetRegistryInterface.h"

#include "Misc/FilterCollection.h"
#include "Misc/IFilter.h"

#include "EdGraph_ExtDependencyViewer.generated.h"


struct ExtAssetData;

class FExtAssetThumbnailPool;
class UEdGraphNode_ExtDependency;
class SExtDependencyViewer;
class UExtDependencyViewerSettings;
enum class EExtDependencyPinCategory;

/*
*  Holds asset information for building reference graph
*/
struct FExtReferenceNodeInfo
{
	FExtAssetIdentifier AssetId;

	FExtAssetData AssetData;

	// immediate children (references or dependencies)
	TArray<TPair<FExtAssetIdentifier, EExtDependencyPinCategory>> Children;

	// this node's parent references (how it got included)
	TArray<FExtAssetIdentifier> Parents;

	// Which direction.  Referencers are left (other assets that depend on me), Dependencies are right (other assets I depend on)
	bool bReferencers;

	int32 OverflowCount;

	// Denote when all children have been manually expanded and the breadth limit should be ignored
	bool bExpandAllChildren;

	FExtReferenceNodeInfo(const FExtAssetIdentifier& InAssetId, bool InbReferencers);

	bool IsFirstParent(const FExtAssetIdentifier& InParentId) const;

	bool IsADuplicate() const;

	// The Provision Size, or vertical spacing required for layout, for a given parent.
	// At the time of writing, the intent is only the first node manifestation of
	// an asset will have its children shown
	int32 ProvisionSize(const FExtAssetIdentifier& InParentId) const;

	// how many nodes worth of children require vertical spacing
	int32 ChildProvisionSize;

	// Whether or not this nodeinfo passed the current filters
	bool PassedFilters;
};

UCLASS()
class UEdGraph_ExtDependencyViewer : public UEdGraph
{
	GENERATED_UCLASS_BODY()

public:
	// UObject implementation
	virtual void BeginDestroy() override;
	// End UObject implementation

	/** Set reference viewer to focus on these assets */
	void SetGraphRoot(const TArray<FExtAssetIdentifier>& GraphRootIdentifiers, const FIntPoint& GraphRootOrigin = FIntPoint(ForceInitToZero));

	/** Returns list of currently focused assets */
	const TArray<FExtAssetIdentifier>& GetCurrentGraphRootIdentifiers() const;

	/** If you're extending the reference viewer via GetAllGraphEditorContextMenuExtender you can use this to get the list of selected assets to use in your menu extender */
	bool GetSelectedAssetsForMenuExtender(const class UEdGraphNode* Node, TArray<FExtAssetIdentifier>& SelectedAssets) const;

	/** Accessor for the thumbnail pool in this graph */
	const TSharedPtr<class FExtAssetThumbnailPool>& GetAssetThumbnailPool() const;

	/** Force the graph to rebuild */
	class UEdGraphNode_ExtDependency* RebuildGraph();

	/** Refilters the nodes, more efficient that a full rebuild.  This function is preferred when the assets, reference types or depth hasn't changed, meaning the NodeInfos didn't change, just
	 * the presentation or filtering */
	class UEdGraphNode_ExtDependency* RefilterGraph();

	FName GetCurrentCollectionFilter() const;
	void SetCurrentCollectionFilter(FName NewFilter);

	TArray<FName> GetCurrentPluginFilter() const;
	void SetCurrentPluginFilter(TArray<FName> NewFilter);
	TArray<FName> GetEncounteredPluginsAmongNodes() const;

	/* Not to be confused with the above Content Browser Collection name, this is a TFiltercollection, a list of active filters */
	void SetCurrentFilterCollection(TSharedPtr< TFilterCollection<FExtReferenceNodeInfo&> > NewFilterCollection);

	/* Returns a set of unique asset types as UClass* */
	const TSet<FTopLevelAssetPath>& GetAssetTypes() const { return CurrentClasses; }

	/* Returns true if the current graph has overflow nodes */
	bool BreadthLimitExceeded() const { return bBreadthLimitReached; };

private:
	void SetReferenceViewer(TSharedPtr<SExtDependencyViewer> InViewer);
	UEdGraphNode_ExtDependency* ConstructNodes(const TArray<FExtAssetIdentifier>& GraphRootIdentifiers, const FIntPoint& GraphRootOrigin);

	bool ExceedsMaxSearchDepth(int32 Depth, int32 MaxDepth) const;
	bool ExceedsMaxSearchBreadth(int32 Breadth) const;
	struct FAssetManagerDependencyQuery GetReferenceSearchFlags(bool bHardOnly) const;

	/* Generates a NodeInfo structure then used to generate and layout the graph nodes */
	void RecursivelyPopulateNodeInfos(bool bReferencers, const TArray<FExtAssetIdentifier>& Identifiers, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& NodeInfos, int32 CurrentDepth, int32 MaxDepth);

	/* Marks up the NodeInfos with updated filter information and provision sizes */
	void RecursivelyFilterNodeInfos(const FExtAssetIdentifier& InAssetId, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& NodeInfos, int32 CurrentDepth, int32 MaxDepth);

	/* Searches for the AssetData for the list of packages derived from the AssetReferences  */
	void GatherAssetData(TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos);

	/* Uses the NodeInfos map to generate and layout the graph nodes */
	UEdGraphNode_ExtDependency* RecursivelyCreateNodes(
		bool bInReferencers,
		const FExtAssetIdentifier& InAssetId,
		const FIntPoint& InNodeLoc,
		const FExtAssetIdentifier& InParentId,
		UEdGraphNode_ExtDependency* InParentNode,
		TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos,
		int32 InCurrentDepth,
		int32 InMaxDepth,
		bool bIsRoot = false
	);

	void ExpandNode(bool bReferencers, const FExtAssetIdentifier& InAssetIdentifier);

	/** Removes all nodes from the graph */
	void RemoveAllNodes();

	/** Returns true if filtering is enabled and we have a valid collection */
	bool ShouldFilterByCollection() const;

	/** Returns true if filtering is enabled and we have a valid plugin name filter set */
	bool ShouldFilterByPlugin() const;

	void GetUnfilteredGraphPluginNamesRecursive(bool bReferencers, const FExtAssetIdentifier& InAssetIdentifier, int32 InCurrentDepth, int32 InMaxDepth, const FAssetManagerDependencyQuery& Query, TSet<FExtAssetIdentifier>& OutAssetIdentifiers);
	void GetUnfilteredGraphPluginNames(TArray<FExtAssetIdentifier> RootIdentifiers, TArray<FName>& OutPluginNames);

	void GetSortedLinks(const TArray<FExtAssetIdentifier>& Identifiers, bool bReferencers, const FAssetManagerDependencyQuery& Query, TMap<FExtAssetIdentifier, EExtDependencyPinCategory>& OutLinks) const;
	bool IsPackageIdentifierPassingFilter(const FExtAssetIdentifier& InAssetIdentifier) const;
	bool IsPackageIdentifierPassingPluginFilter(const FExtAssetIdentifier& InAssetIdentifier) const;

	UEdGraphNode_ExtDependency* FindPath(const FExtAssetIdentifier& RootId, const FExtAssetIdentifier& TargetId);
	bool FindPath_Recursive(bool bInReferencers, const FExtAssetIdentifier& InAssetId, const FExtAssetIdentifier& Target, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos, TSet<FExtAssetIdentifier>& Visited);

	// For compatibility with old implementation
	//int32 RecursivelyGatherSizes(bool bReferencers, const TArray<FExtAssetIdentifier>& Identifiers, const TSet<FName>& AllowedPackageNames, int32 CurrentDepth, TSet<FExtAssetIdentifier>& VisitedNames, TMap<FExtAssetIdentifier, int32>& OutNodeSizes) const;
	//UEdGraphNode_ExtDependency* RecursivelyConstructNodes(bool bReferencers, UEdGraphNode_ExtDependency* RootNode, const TArray<FExtAssetIdentifier>& Identifiers, const FIntPoint& NodeLoc, const TMap<FExtAssetIdentifier, int32>& NodeSizes, const TMap<FName, FExtAssetData>& PackagesToAssetDataMap, const TSet<FName>& AllowedPackageNames, int32 CurrentDepth, TSet<FExtAssetIdentifier>& VisitedNames);
	void GatherAssetData(const TSet<FName>& AllPackageNames, TMap<FName, FExtAssetData>& OutPackageToAssetDataMap) const;

private: // Keep CreateReferenceNode in private section since it's used internally
	UEdGraphNode_ExtDependency* CreateReferenceNode();

public:
	float GetNodeXSpacing() const;
	void SetNodeXSpacing(float NewNodeXSpacing);

	// Additional helper methods
	bool IsShowReferencers() const;
	bool IsShowDependencies() const;

private:
	/** Pool for maintaining and rendering thumbnails */
	TSharedPtr<FExtAssetThumbnailPool> AssetThumbnailPool;

	/** Editor for this pool */
	TWeakPtr<SExtDependencyViewer> ReferenceViewer;

	TArray<FExtAssetIdentifier> CurrentGraphRootIdentifiers;
	FIntPoint CurrentGraphRootOrigin;

	/** Stores if the breadth limit was reached on the last refilter*/
	bool bBreadthLimitReached;

	/** Current collection filter. NAME_None for no filter */
	FName CurrentCollectionFilter;

	/** Current plugin filter. Empty for no filter. */
	TArray<FName> CurrentPluginFilter;

	/** Plugin names found among unfiltered nodes. Chose among these when filtering for plugins. */
	TArray<FName> EncounteredPluginsAmongNodes;

	/** A set of the unique class types referenced */
	TSet<FTopLevelAssetPath> CurrentClasses;

	/* This is a convenience toggle to switch between the old & new methods for computing & displaying the graph */
	bool bUseNodeInfos;

	/* Settings variables */
	int32 MaxSearchDepth;
	int32 MaxSearchBreadth;

	float NodeXSpacing;

	/* Cached Reference Information used to quickly refilter */
	TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> ReferencerNodeInfos;
	TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> DependencyNodeInfos;

	/** List of packages the current collection filter allows */
	TSet<FName> CurrentCollectionPackages;

	/** Current filter collection */
	TSharedPtr< TFilterCollection<FExtReferenceNodeInfo & > > FilterCollection;

	UExtDependencyViewerSettings* Settings;

	/* A delegate to notify when the underlying assets changed (usually through a root or depth change) */
	FSimpleMulticastDelegate OnAssetsChangedDelegate;

	FExtAssetIdentifier TargetIdentifier;

	friend SExtDependencyViewer;
};
