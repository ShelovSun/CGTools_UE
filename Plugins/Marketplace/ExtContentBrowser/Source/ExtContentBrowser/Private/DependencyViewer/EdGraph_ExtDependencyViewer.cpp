// Copyright 2017-2021 marynate. All Rights Reserved.

#include "EdGraph_ExtDependencyViewer.h"
#include "EdGraphNode_ExtDependency.h"
#include "ExtContentBrowserSingleton.h"
#include "ExtAssetData.h"
#include "ExtAssetThumbnail.h"

#include "EdGraph/EdGraphPin.h"
#include "AssetRegistry/ARFilter.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetThumbnail.h"
#include "SExtDependencyViewer.h"
#include "SExtDependencyNode.h"
#include "GraphEditor.h"
#include "ICollectionManager.h"
#include "CollectionManagerModule.h"
#include "ICollectionContainer.h"
#include "Engine/AssetManager.h"
#include "AssetManagerEditorModule.h"
#include "Logging/TokenizedMessage.h"

// Implementation of FExtReferenceNodeInfo structure
FExtReferenceNodeInfo::FExtReferenceNodeInfo(const FExtAssetIdentifier& InAssetId, bool InbReferencers)
	: AssetId(InAssetId)
	, bReferencers(InbReferencers)
	, OverflowCount(0)
	, bExpandAllChildren(false)
	, ChildProvisionSize(0)
	, PassedFilters(true)
{
}

bool FExtReferenceNodeInfo::IsFirstParent(const FExtAssetIdentifier& InParentId) const
{
	return Parents.IsEmpty() || Parents[0] == InParentId;
}

bool FExtReferenceNodeInfo::IsADuplicate() const
{
	return Parents.Num() > 1;
}

int32 FExtReferenceNodeInfo::ProvisionSize(const FExtAssetIdentifier& InParentId) const
{
	return IsFirstParent(InParentId) ? ChildProvisionSize : 1;
}

UEdGraph_ExtDependencyViewer::UEdGraph_ExtDependencyViewer(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	AssetThumbnailPool = MakeShareable( new FExtAssetThumbnailPool(1024) );

	MaxSearchDepth = 1;
	MaxSearchBreadth = 15;

	NodeXSpacing = 400.f;

	bUseNodeInfos = true; // Enable the new node info system
	bBreadthLimitReached = false;

	Settings = GetMutableDefault<UExtDependencyViewerSettings>();
}

void UEdGraph_ExtDependencyViewer::BeginDestroy()
{
	AssetThumbnailPool.Reset();

	Super::BeginDestroy();
}

void UEdGraph_ExtDependencyViewer::SetGraphRoot(const TArray<FExtAssetIdentifier>& GraphRootIdentifiers, const FIntPoint& GraphRootOrigin)
{
	CurrentGraphRootIdentifiers = GraphRootIdentifiers;
	CurrentGraphRootOrigin = GraphRootOrigin;

	// If we're focused on a searchable name, enable that flag
	for (const FExtAssetIdentifier& AssetId : GraphRootIdentifiers)
	{
		if (AssetId.IsValue())
		{
			Settings->SetShowSearchableNames(true);
		}
		else if (AssetId.GetPrimaryAssetId().IsValid())
		{
			/*
			if (UAssetManager::IsInitialized())
			{
				UAssetManager::Get().UpdateManagementDatabase();
			}
			*/
			Settings->SetShowManagementReferencesEnabled(true);
		}
	}

	//RebuildGraph();
}

const TArray<FExtAssetIdentifier>& UEdGraph_ExtDependencyViewer::GetCurrentGraphRootIdentifiers() const
{
	return CurrentGraphRootIdentifiers;
}

void UEdGraph_ExtDependencyViewer::SetReferenceViewer(TSharedPtr<SExtDependencyViewer> InViewer)
{
	ReferenceViewer = InViewer;
}

bool UEdGraph_ExtDependencyViewer::GetSelectedAssetsForMenuExtender(const class UEdGraphNode* Node, TArray<FExtAssetIdentifier>& SelectedAssets) const
{
	if (!ReferenceViewer.IsValid())
	{
		return false;
	}
	TSharedPtr<SGraphEditor> GraphEditor = ReferenceViewer.Pin()->GetGraphEditor();

	if (!GraphEditor.IsValid())
	{
		return false;
	}

	TSet<UObject*> SelectedNodes = GraphEditor->GetSelectedNodes();
	for (FGraphPanelSelectionSet::TConstIterator It(SelectedNodes); It; ++It)
	{
		if (UEdGraphNode_ExtDependency* ReferenceNode = Cast<UEdGraphNode_ExtDependency>(*It))
		{
			if (!ReferenceNode->IsCollapsed())
			{
				SelectedAssets.Add(ReferenceNode->GetIdentifier());
			}
		}
	}
	return true;
}

UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::RebuildGraph()
{
	RemoveAllNodes();
	UEdGraphNode_ExtDependency* NewRootNode = nullptr;

	if (Settings && Settings->GetFindPathEnabled())
	{
		if (CurrentGraphRootIdentifiers.Num() > 0 && TargetIdentifier.IsValid())
		{
			NewRootNode = FindPath(CurrentGraphRootIdentifiers[0], TargetIdentifier);
		}
	}
	else
	{
		NewRootNode = ConstructNodes(CurrentGraphRootIdentifiers, CurrentGraphRootOrigin);
	}

	return NewRootNode;
}

UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::RefilterGraph()
{

	RemoveAllNodes();
	UEdGraphNode_ExtDependency* RootNode = nullptr;

	bBreadthLimitReached = false;
	if (CurrentGraphRootIdentifiers.Num() > 0 && (!ReferencerNodeInfos.IsEmpty() || !DependencyNodeInfos.IsEmpty()))
	{
		FExtAssetIdentifier FirstGraphRootIdentifier = CurrentGraphRootIdentifiers[0];

		// Create the root node
		bool bRootIsDuplicated = false;

		for (const FExtAssetIdentifier& RootID : CurrentGraphRootIdentifiers)
		{
			bRootIsDuplicated |= (IsShowDependencies() && DependencyNodeInfos.Contains(RootID) && DependencyNodeInfos[RootID].IsADuplicate()) ||
				(IsShowReferencers() && ReferencerNodeInfos.Contains(RootID) && ReferencerNodeInfos[RootID].IsADuplicate());
		}

		const FExtReferenceNodeInfo& NodeInfo = IsShowReferencers() ? ReferencerNodeInfos[FirstGraphRootIdentifier] : DependencyNodeInfos[FirstGraphRootIdentifier];

		RootNode = CreateReferenceNode();
		RootNode->SetupReferenceNode(CurrentGraphRootOrigin, CurrentGraphRootIdentifiers, NodeInfo.AssetData, !Settings->IsCompactMode(), bRootIsDuplicated);

		if (IsShowReferencers())
		{
			RecursivelyFilterNodeInfos(FirstGraphRootIdentifier, ReferencerNodeInfos, 0, Settings->GetSearchReferencerDepthLimit());
			RecursivelyCreateNodes(true, FirstGraphRootIdentifier, CurrentGraphRootOrigin, FirstGraphRootIdentifier, RootNode, ReferencerNodeInfos, 0, Settings->GetSearchReferencerDepthLimit(), /*bIsRoot*/ true);
		}

		if (IsShowDependencies())
		{
			RecursivelyFilterNodeInfos(FirstGraphRootIdentifier, DependencyNodeInfos, 0, Settings->GetSearchDependencyDepthLimit());
			RecursivelyCreateNodes(false, FirstGraphRootIdentifier, CurrentGraphRootOrigin, FirstGraphRootIdentifier, RootNode, DependencyNodeInfos, 0, Settings->GetSearchDependencyDepthLimit(), /*bIsRoot*/ true);
		}
	}

	NotifyGraphChanged();
	return RootNode;
}

FName UEdGraph_ExtDependencyViewer::GetCurrentCollectionFilter() const
{
	return CurrentCollectionFilter;
}

void UEdGraph_ExtDependencyViewer::SetCurrentCollectionFilter(FName NewFilter)
{
	CurrentCollectionFilter = NewFilter;
}

TArray<FName> UEdGraph_ExtDependencyViewer::GetCurrentPluginFilter() const
{
	return CurrentPluginFilter;
}

void UEdGraph_ExtDependencyViewer::SetCurrentPluginFilter(TArray<FName> NewFilter)
{
	CurrentPluginFilter = NewFilter;
}

TArray<FName> UEdGraph_ExtDependencyViewer::GetEncounteredPluginsAmongNodes() const
{
	return EncounteredPluginsAmongNodes;
}

void UEdGraph_ExtDependencyViewer::SetCurrentFilterCollection(TSharedPtr< TFilterCollection< FExtReferenceNodeInfo& > > InFilterCollection)
{
	FilterCollection = InFilterCollection;
}

bool UEdGraph_ExtDependencyViewer::IsShowReferencers() const
{
	bool bReferencers = Settings ? Settings->IsShowReferencers() : false;  // Default to false for dependency viewer
	bool bDependencies = Settings ? Settings->IsShowDependencies() : true;  // Default to true for dependency viewer

	// If both are disabled, enable dependencies instead of referencers (since it's a dependency viewer)
	if (!bReferencers && !bDependencies)
	{
		return false; // Don't show referencers in dependency viewer when both are disabled
	}
	return bReferencers;
}

bool UEdGraph_ExtDependencyViewer::IsShowDependencies() const
{
	bool bReferencers = Settings ? Settings->IsShowReferencers() : false;  // Default to false for dependency viewer
	bool bDependencies = Settings ? Settings->IsShowDependencies() : true;  // Default to true for dependency viewer

	// If both are disabled, make sure dependencies are shown (since it's a dependency viewer)
	if (!bReferencers && !bDependencies)
	{
		return true; // Show dependencies when both settings are false
	}
	return bDependencies;
}


float UEdGraph_ExtDependencyViewer::GetNodeXSpacing() const
{
	return NodeXSpacing;
}

void UEdGraph_ExtDependencyViewer::SetNodeXSpacing(float NewNodeXSpacing)
{
#if ECB_FEA_REF_VIEWER_NODE_SPACING
	NodeXSpacing = FMath::Clamp<float>(NewNodeXSpacing, 200.f, 10000.f);
#endif
}

FAssetManagerDependencyQuery UEdGraph_ExtDependencyViewer::GetReferenceSearchFlags(bool bHardOnly) const
{
	using namespace UE::AssetRegistry;
	FAssetManagerDependencyQuery Query;
	Query.Categories = EDependencyCategory::None;
	Query.Flags = EDependencyQuery::NoRequirements;

	bool bLocalIsShowSoftReferences = Settings->IsShowSoftReferences() && !bHardOnly;
	if (bLocalIsShowSoftReferences || Settings->IsShowHardReferences())
	{
		Query.Categories |= EDependencyCategory::Package;
		Query.Flags |= bLocalIsShowSoftReferences ? EDependencyQuery::NoRequirements : EDependencyQuery::Hard;
		Query.Flags |= Settings->IsShowHardReferences() ? EDependencyQuery::NoRequirements : EDependencyQuery::Soft;
		Query.Flags |= Settings->IsShowEditorOnlyReferences() ? EDependencyQuery::NotGame : EDependencyQuery::Game;
	}
	if (Settings->IsShowSearchableNames() && !bHardOnly)
	{
		Query.Categories |= EDependencyCategory::SearchableName;
	}
	if (Settings->IsShowManagementReferences())
	{
		Query.Categories |= EDependencyCategory::Manage;
		Query.Flags |= bHardOnly ? EDependencyQuery::Direct : EDependencyQuery::NoRequirements;
	}

	return Query;
}

UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::ConstructNodes(const TArray<FExtAssetIdentifier>& GraphRootIdentifiers, const FIntPoint& GraphRootOrigin )
{
	if (GraphRootIdentifiers.Num() > 0)
	{
		// It both were false, nothing (other than the GraphRootIdentifiers) would be displayed
		check(IsShowReferencers() || IsShowDependencies());

		// Refresh the current collection filter
		CurrentCollectionPackages.Empty();
		if (ShouldFilterByCollection())
		{
			FCollectionManagerModule& CollectionManagerModule = FCollectionManagerModule::GetModule();
			TArray<FSoftObjectPath> AssetPaths;
			CollectionManagerModule.Get().GetProjectCollectionContainer()->GetAssetsInCollection(CurrentCollectionFilter, ECollectionShareType::CST_All, AssetPaths);
			CurrentCollectionPackages.Reserve(AssetPaths.Num());
			for (const FSoftObjectPath& AssetPath : AssetPaths)
			{
				CurrentCollectionPackages.Add(FName(*FPackageName::ObjectPathToPackageName(AssetPath.ToString())));
			}
		}

		// Prepare for plugin filtering.
		{
			// Collect plugin names from assets reachable in the graph if the graph had been unfiltered.
			EncounteredPluginsAmongNodes.Empty();
			//GetUnfilteredGraphPluginNames(GraphRootIdentifiers, EncounteredPluginsAmongNodes);

			// Remove plugins from the current filter that were not encountered in the new unfiltered graph.
			for (TArray<FName>::TIterator It(CurrentPluginFilter); It; ++It)
			{
				if (!EncounteredPluginsAmongNodes.Contains(*It))
				{
					It.RemoveCurrent();
				}
			}
		}

		// Create & Populate the NodeInfo Maps
		// Note to add an empty parent to the root so that if the root node again gets found again as a duplicate, that next parent won't be
		// identified as the primary root and also it will appear as having multiple parents.
		TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> NewReferenceNodeInfos;
		for (const FExtAssetIdentifier& RootIdentifier : GraphRootIdentifiers)
		{
			FExtReferenceNodeInfo& RootNodeInfo = NewReferenceNodeInfos.FindOrAdd(RootIdentifier, FExtReferenceNodeInfo(RootIdentifier, true));
			RootNodeInfo.Parents.Emplace(FExtAssetIdentifier(NAME_None));
		}
		if (!Settings || !Settings->GetFindPathEnabled())
		{
			RecursivelyPopulateNodeInfos(true, GraphRootIdentifiers, NewReferenceNodeInfos, 0, Settings->GetSearchReferencerDepthLimit());
		}

		TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> NewDependencyNodeInfos;
		for (const FExtAssetIdentifier& RootIdentifier : GraphRootIdentifiers)
		{
			FExtReferenceNodeInfo& DRootNodeInfo = NewDependencyNodeInfos.FindOrAdd(RootIdentifier, FExtReferenceNodeInfo(RootIdentifier, false));
			DRootNodeInfo.Parents.Emplace(FExtAssetIdentifier(NAME_None));
		}
		if (!Settings || !Settings->GetFindPathEnabled())
		{
			RecursivelyPopulateNodeInfos(false, GraphRootIdentifiers, NewDependencyNodeInfos, 0, Settings->GetSearchDependencyDepthLimit());
		}

		TSet<FName> AllPackageNames;
		auto AddPackage = [](const FExtAssetIdentifier& AssetId, TSet<FName>& PackageNames)
		{
			// Only look for asset data if this is a package
			if (!AssetId.IsValue() && !AssetId.PackageName.IsNone())
			{
				PackageNames.Add(AssetId.PackageName);
			}
		};

		if (IsShowReferencers())
		{
			for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : NewReferenceNodeInfos)
			{
				AddPackage(InfoPair.Key, AllPackageNames);
			}
		}

		if (IsShowDependencies())
		{
			for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : NewDependencyNodeInfos)
			{
				AddPackage(InfoPair.Key, AllPackageNames);
			}
		}

		// Store the AssetData in the NodeInfos
		TMap<FName, FExtAssetData> PackagesToAssetDataMap;

		// Get asset data for all packages from the ext asset registry
		for (const FName& PackageName : AllPackageNames)
		{
			FExtAssetData* CachedAssetData = FExtContentBrowserSingleton::Get().ExtAssetRegistry.GetCachedAssetByPackageName(PackageName);
			if (CachedAssetData && CachedAssetData->IsValid())
			{
				PackagesToAssetDataMap.Add(PackageName, *CachedAssetData);
			}
			else
			{
				// If not cached, try to create a basic asset data
				PackagesToAssetDataMap.Add(PackageName, FExtAssetData(PackageName));
			}
		}

		// Store the AssetData in the NodeInfos and collect Asset Type UClasses to populate the filters
		TSet<FTopLevelAssetPath> AllClasses;
		for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : NewReferenceNodeInfos)
		{
			InfoPair.Value.AssetData = PackagesToAssetDataMap.FindRef(InfoPair.Key.PackageName);
			if (InfoPair.Value.AssetData.IsValid())
			{
				// Get the asset class and construct a proper asset class path to avoid FTopLevelAssetPath errors
				if (!InfoPair.Value.AssetData.AssetClass.IsNone())
				{
					FName AssetClassName = InfoPair.Value.AssetData.AssetClass;
					// Only attempt to create FTopLevelAssetPath if it looks like a proper class path
					FString AssetClassString = AssetClassName.ToString();
					if (AssetClassString.StartsWith(TEXT("/Script/")) || AssetClassString.StartsWith(TEXT("/Game/")))
					{
						FTopLevelAssetPath ClassPath(AssetClassString);
						AllClasses.Add(ClassPath);
					}
				}
			}
		}

		for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : NewDependencyNodeInfos)
		{
			InfoPair.Value.AssetData = PackagesToAssetDataMap.FindRef(InfoPair.Key.PackageName);
			if (InfoPair.Value.AssetData.IsValid())
			{
				// Get the asset class and construct a proper asset class path to avoid FTopLevelAssetPath errors
				if (!InfoPair.Value.AssetData.AssetClass.IsNone())
				{
					FName AssetClassName = InfoPair.Value.AssetData.AssetClass;
					// Only attempt to create FTopLevelAssetPath if it looks like a proper class path
					FString AssetClassString = AssetClassName.ToString();
					if (AssetClassString.StartsWith(TEXT("/Script/")) || AssetClassString.StartsWith(TEXT("/Game/")))
					{
						FTopLevelAssetPath ClassPath(AssetClassString);
						AllClasses.Add(ClassPath);
					}
				}
			}
		}

		// Update the cached class types list
		CurrentClasses = AllClasses;
		//OnAssetsChangedDelegate.Broadcast();

		ReferencerNodeInfos = NewReferenceNodeInfos;
		DependencyNodeInfos = NewDependencyNodeInfos;
	}
	else
	{
		ReferencerNodeInfos.Empty();
		DependencyNodeInfos.Empty();
	}

	return RefilterGraph();
}

void UEdGraph_ExtDependencyViewer::GetUnfilteredGraphPluginNamesRecursive(bool bReferencers, const FExtAssetIdentifier& InAssetIdentifier, int32 InCurrentDepth, int32 InMaxDepth, const FAssetManagerDependencyQuery& Query, TSet<FExtAssetIdentifier>& OutAssetIdentifiers)
{
	/*
	if (ExceedsMaxSearchDepth(InCurrentDepth, InMaxDepth))
	{
		return;
	}

	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
	TArray<FAssetDependency> LinksToAsset;
	if (bReferencers)
	{
		AssetRegistry.GetReferencers(InAssetIdentifier, LinksToAsset);
	}
	else
	{
		AssetRegistry.GetDependencies(InAssetIdentifier, LinksToAsset);
	}

	for (const FAssetDependency& Link : LinksToAsset)
	{
		// Avoid loops by skipping assets we've already visited.
		if (OutAssetIdentifiers.Contains(Link.AssetId))
		{
			continue;;
		}

		// Don't add assets that will be hidden by Reference Viewer settings the user cannot change.
		if (!IsPackageIdentifierPassingFilter(Link.AssetId))
		{
			continue;
		}

		OutAssetIdentifiers.Add(Link.AssetId);

		GetUnfilteredGraphPluginNamesRecursive(bReferencers, Link.AssetId, InCurrentDepth + 1, InMaxDepth, Query, OutAssetIdentifiers);
	}
	*/
}

void UEdGraph_ExtDependencyViewer::GetUnfilteredGraphPluginNames(TArray<FExtAssetIdentifier> RootIdentifiers, TArray<FName>& OutPluginNames)
{
	/*
	TRACE_CPUPROFILER_EVENT_SCOPE(UEdGraph_ReferenceViewer::GetUnfilteredGraphPluginNames);

	const FAssetManagerDependencyQuery Query = GetReferenceSearchFlags(false);

	TSet<FAssetIdentifier> AssetIdentifiers;
	for (const FAssetIdentifier& RootIdentifier : RootIdentifiers)
	{
		TSet<FAssetIdentifier> AssetReferencerIdentifiers;
		GetUnfilteredGraphPluginNamesRecursive(true, RootIdentifier, 0, Settings->GetSearchReferencerDepthLimit(), Query, AssetReferencerIdentifiers);
		AssetIdentifiers.Append(AssetReferencerIdentifiers);

		TSet<FAssetIdentifier> AssetDependencyIdentifiers;
		GetUnfilteredGraphPluginNamesRecursive(false, RootIdentifier, 0, Settings->GetSearchDependencyDepthLimit(), Query, AssetDependencyIdentifiers);
		AssetIdentifiers.Append(AssetDependencyIdentifiers);
	}

	for (const FAssetIdentifier& AssetIdentifier : AssetIdentifiers)
	{
		if (!AssetIdentifier.IsPackage())
		{
			continue;
		}

		FString FirstPathSegment;
		{
			FString AssetPath = AssetIdentifier.PackageName.ToString();

			// Chop of any leading slashes.
			while (AssetPath.StartsWith("/"))
			{
				AssetPath = AssetPath.Mid(1);
			}

			const int32 SecondSlash = AssetPath.Find("/");
			if (SecondSlash != INDEX_NONE)
			{
				AssetPath = AssetPath.Left(SecondSlash);
			}

			FirstPathSegment = AssetPath;
		}

		OutPluginNames.AddUnique(FName(FirstPathSegment));
	}
	*/
}


void UEdGraph_ExtDependencyViewer::RecursivelyPopulateNodeInfos(bool bInReferencers, const TArray<FExtAssetIdentifier>& Identifiers, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos, int32 InCurrentDepth, int32 InMaxDepth)
{
	check(Identifiers.Num() > 0);
	int32 ProvisionSize = 0;
	const FExtAssetIdentifier& InAssetId = Identifiers[0];

	if (!ExceedsMaxSearchDepth(InCurrentDepth, InMaxDepth))
	{
		TMap<FExtAssetIdentifier, EExtDependencyPinCategory> ReferenceLinks;
		GetSortedLinks(Identifiers, bInReferencers, GetReferenceSearchFlags(false), ReferenceLinks);

		InNodeInfos[InAssetId].Children.Reserve(ReferenceLinks.Num());
		for (const TPair<FExtAssetIdentifier, EExtDependencyPinCategory>& Pair : ReferenceLinks)
		{
			FExtAssetIdentifier ChildId = Pair.Key;

			if (!InNodeInfos.Contains(ChildId))
			{
				FExtReferenceNodeInfo& NewNodeInfo = InNodeInfos.FindOrAdd(ChildId, FExtReferenceNodeInfo(ChildId, bInReferencers));
				InNodeInfos[ChildId].Parents.Emplace(InAssetId);
				InNodeInfos[InAssetId].Children.Emplace(Pair);

				RecursivelyPopulateNodeInfos(bInReferencers, { ChildId }, InNodeInfos, InCurrentDepth + 1, InMaxDepth);
				ProvisionSize += InNodeInfos[ChildId].ProvisionSize(InAssetId);
			}
			else if (!InNodeInfos[ChildId].Parents.Contains(InAssetId))
			{
				InNodeInfos[ChildId].Parents.Emplace(InAssetId);
				InNodeInfos[InAssetId].Children.Emplace(Pair);
				ProvisionSize += 1;
			}
		}
	}

	// Account for an overflow node if necessary
	if (InNodeInfos[InAssetId].OverflowCount > 0)
	{
		ProvisionSize++;
	}

	InNodeInfos[InAssetId].ChildProvisionSize = ProvisionSize > 0 ? ProvisionSize : 1;
}

void UEdGraph_ExtDependencyViewer::GatherAssetData(TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos)
{
	// Grab the list of packages
	TSet<FName> PackageNames;
	for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : InNodeInfos)
	{
		FExtAssetIdentifier& AssetId = InfoPair.Key;
		if (!AssetId.IsValue() && !AssetId.PackageName.IsNone())
		{
			PackageNames.Add(AssetId.PackageName);
		}
	}

	// Retrieve the AssetData from the Registry
	TMap<FName, FExtAssetData> PackagesToAssetDataMap;
	GatherAssetData(PackageNames, PackagesToAssetDataMap);

	// Populate the AssetData back into the NodeInfos
	for (TPair<FExtAssetIdentifier, FExtReferenceNodeInfo>& InfoPair : InNodeInfos)
	{
		InfoPair.Value.AssetData = PackagesToAssetDataMap.FindRef(InfoPair.Key.PackageName);
	}
}


void UEdGraph_ExtDependencyViewer::RecursivelyFilterNodeInfos(const FExtAssetIdentifier& InAssetId, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos, int32 InCurrentDepth, int32 InMaxDepth)
{

	// Filters and Re-provisions the NodeInfo counts
	int32 NewProvisionSize = 0;

	int32 Breadth = 0;

	InNodeInfos[InAssetId].OverflowCount = 0;
	if (!ExceedsMaxSearchDepth(InCurrentDepth, InMaxDepth))
	{
		for (const TPair<FExtAssetIdentifier, EExtDependencyPinCategory>& Pair : InNodeInfos[InAssetId].Children)
		{
			FExtAssetIdentifier ChildId = Pair.Key;

			int32 ChildProvSize = 0;
			if (InNodeInfos[ChildId].IsFirstParent(InAssetId))
			{
				RecursivelyFilterNodeInfos(ChildId, InNodeInfos, InCurrentDepth + 1, InMaxDepth);
				ChildProvSize = InNodeInfos[ChildId].ProvisionSize(InAssetId);
			}
			else if (Settings && Settings->GetFindPathEnabled())
			{
				ChildProvSize = 1;
			}
			else if (InNodeInfos[ChildId].PassedFilters && Settings->IsShowDuplicates())
			{
				ChildProvSize = 1;
			}

			if (ChildProvSize > 0)
			{
				if (!ExceedsMaxSearchBreadth(Breadth) || InNodeInfos[InAssetId].bExpandAllChildren)
				{
					NewProvisionSize += ChildProvSize;
					Breadth++;
				}
				else
				{
					InNodeInfos[InAssetId].OverflowCount++;
					Breadth++;
				}
			}
		}
	}

	// Account for an overflow node if necessary
	if (InNodeInfos[InAssetId].OverflowCount > 0)
	{
		NewProvisionSize++;
		bBreadthLimitReached = true;
	}

	bool PassedAssetTypeFilter = FilterCollection && (Settings ? Settings->GetFiltersEnabled() : true) ? FilterCollection->PassesAllFilters(InNodeInfos[InAssetId]) : true;
	// bool PassedSearchTextFilter = IsAssetPassingSearchTextFilter(InAssetId); // Not implemented yet

	// Don't apply filters in Find Path Mode. Otherwise, check the type and search filters, and also don't include any assets in the central selection (where InCurrentDepth == 0)
	bool PassedAllFilters = Settings && Settings->GetFindPathEnabled() || (PassedAssetTypeFilter /*&& PassedSearchTextFilter*/ && (InCurrentDepth == 0 || !CurrentGraphRootIdentifiers.Contains(InAssetId)));

	InNodeInfos[InAssetId].ChildProvisionSize = NewProvisionSize > 0 ? NewProvisionSize : (PassedAllFilters ? 1 : 0);
	InNodeInfos[InAssetId].PassedFilters = PassedAllFilters;
}

UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::RecursivelyCreateNodes(
	bool bInReferencers,
	const FExtAssetIdentifier& InAssetId,
	const FIntPoint& InNodeLoc,
	const FExtAssetIdentifier& InParentId,
	UEdGraphNode_ExtDependency* InParentNode,
	TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos,
	int32 InCurrentDepth,
	int32 InMaxDepth,
	bool bIsRoot)
{
	check(InNodeInfos.Contains(InAssetId));

	const FExtReferenceNodeInfo& NodeInfo = InNodeInfos[InAssetId];
	int32 NodeProvSize = 1;

	UEdGraphNode_ExtDependency* NewNode = nullptr;
	if (bIsRoot)
	{
		NewNode = InParentNode;
		NodeProvSize = NodeInfo.ProvisionSize(FExtAssetIdentifier(NAME_None));
	}
	else
	{
		NewNode = CreateReferenceNode();
		NewNode->SetupReferenceNode(InNodeLoc, {InAssetId}, NodeInfo.AssetData, !Settings->IsCompactMode() && NodeInfo.PassedFilters, NodeInfo.IsADuplicate());
		NewNode->SetIsFiltered(!NodeInfo.PassedFilters);
		NodeProvSize = NodeInfo.ProvisionSize(InParentId);
	}

	bool bIsFirstOccurance = bIsRoot || NodeInfo.IsFirstParent(InParentId);
	FIntPoint ChildLoc = InNodeLoc;
	if (!ExceedsMaxSearchDepth(InCurrentDepth, InMaxDepth) && bIsFirstOccurance) // Only expand the first parent
	{
		// Check if dependency viewer is positioned under asset view (vertical layout) or to the right (horizontal layout)
		UExtContentBrowserSettings* ExtContentBrowserSettings = GetMutableDefault<UExtContentBrowserSettings>();
		bool bHorizontalLayout = ExtContentBrowserSettings && ExtContentBrowserSettings->ShowDependencyViewerUnderAssetView;

		// Make spacing proportional to NodeXSpacing
		float ScaleFactor = Settings->IsCompactMode() ? 0.25f : 0.5f;
		int32 SiblingSpacing = FMath::RoundToInt(NodeXSpacing * ScaleFactor);
		// Ensure reasonable minimum/maximum values for sibling spacing
		SiblingSpacing = FMath::Clamp(SiblingSpacing, 50, 400);

		// Define different spacing for parent-child relationship vs sibling spacing
		// Using a smaller spacing factor for parent-child distance to avoid excessive stretching
		int32 ParentChildSpacing = FMath::RoundToInt(NodeXSpacing * 0.6f); // Reduce parent-child distance
		ParentChildSpacing = FMath::Clamp(ParentChildSpacing, 150, 800);

		if (bHorizontalLayout)
		{
			// Vertical arrangement when dependency viewer is under asset view
			// Position children below the parent node with reduced parent-child spacing
			ChildLoc.Y += ParentChildSpacing;
			// Center children horizontally around the parent with full sibling spacing
			ChildLoc.X -= (NodeProvSize - 1) * SiblingSpacing * 0.5;
		}
		else
		{
			// Horizontal arrangement when dependency viewer is on the right of asset view
			ChildLoc.X += bInReferencers ? -ParentChildSpacing : ParentChildSpacing; // Use reduced spacing for parent-child
			ChildLoc.Y -= (NodeProvSize - 1) * SiblingSpacing * 0.5; // Use full sibling spacing for vertical centering
		}

		int32 Breadth = 0;
		int32 ChildIdx = 0;
		for (; ChildIdx < InNodeInfos[InAssetId].Children.Num(); ChildIdx++)
		{
			const TPair<FExtAssetIdentifier, EExtDependencyPinCategory>& Pair = InNodeInfos[InAssetId].Children[ChildIdx];
			if (ExceedsMaxSearchBreadth(Breadth) && !InNodeInfos[InAssetId].bExpandAllChildren)
			{
				break;
			}

			FExtAssetIdentifier ChildId = Pair.Key;
			int32 ChildProvSize = 0;
			if (InNodeInfos[ChildId].IsFirstParent(InAssetId))
			{
				ChildProvSize = InNodeInfos[ChildId].ProvisionSize(InAssetId);
			}
			else if (Settings && Settings->GetFindPathEnabled())
			{
				ChildProvSize = 1;
			}
			else if (InNodeInfos[ChildId].PassedFilters && Settings->IsShowDuplicates())
			{
				ChildProvSize = 1;
			}

			// The provision size will always be at least 1 if it should be shown, factoring in filters, breadth, duplicates, etc.
			if (ChildProvSize > 0)
			{
				if (bHorizontalLayout)
				{
					// Vertical layout (dependency viewer under asset view)
					// Use sibling spacing for horizontal positioning of children
					ChildLoc.X += (ChildProvSize - 1) * SiblingSpacing * 0.5;

					UEdGraphNode_ExtDependency* ChildNode = RecursivelyCreateNodes(bInReferencers, ChildId, ChildLoc, InAssetId, NewNode, InNodeInfos, InCurrentDepth + 1, InMaxDepth);

					if (bInReferencers)
					{
						ChildNode->GetDependencyPin()->PinType.PinCategory = ::GetName(Pair.Value);
						NewNode->AddReferencer(ChildNode);
					}
					else
					{
						ChildNode->GetReferencerPin()->PinType.PinCategory = ::GetName(Pair.Value);
						ChildNode->AddReferencer(NewNode);
					}

					// Use sibling spacing for horizontal positioning of children
					ChildLoc.X += SiblingSpacing * (ChildProvSize + 1) * 0.5;
				}
				else
				{
					// Horizontal layout (dependency viewer on the right of asset view)
					// Use sibling spacing for vertical positioning of children
					ChildLoc.Y += (ChildProvSize - 1) * SiblingSpacing * 0.5;

					UEdGraphNode_ExtDependency* ChildNode = RecursivelyCreateNodes(bInReferencers, ChildId, ChildLoc, InAssetId, NewNode, InNodeInfos, InCurrentDepth + 1, InMaxDepth);

					if (bInReferencers)
					{
						ChildNode->GetDependencyPin()->PinType.PinCategory = ::GetName(Pair.Value);
						NewNode->AddReferencer(ChildNode);
					}
					else
					{
						ChildNode->GetReferencerPin()->PinType.PinCategory = ::GetName(Pair.Value);
						ChildNode->AddReferencer(NewNode);
					}

					// Use sibling spacing for vertical positioning of children
					ChildLoc.Y += SiblingSpacing * (ChildProvSize + 1) * 0.5;
				}
				Breadth++;
			}
		}

		// There were more references than allowed to be displayed. Make a collapsed node.
		if (NodeInfo.OverflowCount > 0)
		{
			UEdGraphNode_ExtDependency* OverflowNode = CreateReferenceNode();
			FIntPoint RefNodeLoc;
			RefNodeLoc.X = ChildLoc.X;
			RefNodeLoc.Y = ChildLoc.Y;

			if (ensure(OverflowNode))
			{
				OverflowNode->SetAllowThumbnail(!Settings->IsCompactMode());

				TArray<FExtAssetIdentifier> CollapsedNodeIdentifiers;
				for (; ChildIdx < InNodeInfos[InAssetId].Children.Num(); ChildIdx++)
				{
					const TPair<FExtAssetIdentifier, EExtDependencyPinCategory>& Pair = InNodeInfos[InAssetId].Children[ChildIdx];
					CollapsedNodeIdentifiers.Add(Pair.Key);
				}
				OverflowNode->SetReferenceNodeCollapsed(RefNodeLoc, NodeInfo.OverflowCount, CollapsedNodeIdentifiers);

				if (bInReferencers)
				{
					NewNode->AddReferencer(OverflowNode);
				}
				else
				{
					OverflowNode->AddReferencer(NewNode);
				}
			}
		}
	}

	return NewNode;
}
/*
int32 UEdGraph_ExtDependencyViewer::RecursivelyGatherSizes(bool bReferencers, const TArray<FExtAssetIdentifier>& Identifiers, const TSet<FName>& AllowedPackageNames, int32 CurrentDepth, TSet<FExtAssetIdentifier>& VisitedNames, TMap<FExtAssetIdentifier, int32>& OutNodeSizes) const
{
	
	check(Identifiers.Num() > 0);

	VisitedNames.Append(Identifiers);

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	TArray<FExtAssetIdentifier> ReferenceNames;

	const FAssetManagerDependencyQuery DependencyQuery = GetReferenceSearchFlags(false);
	if ( bReferencers )
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			FExtContentBrowserSingleton::GetAssetRegistry().GetReferencers(AssetId, ReferenceNames, DependencyQuery.Categories);
		}
	}
	else
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			FExtContentBrowserSingleton::GetAssetRegistry().GetDependencies(AssetId, ReferenceNames, DependencyQuery.Categories);
		}
	}

	if (!Settings->IsShowCodePackages())
	{
		auto RemoveNativePackage = [](const FExtAssetIdentifier& InAsset) { return InAsset.PackageName.ToString().StartsWith(TEXT("/Script")) && !InAsset.IsValue(); };

		ReferenceNames.RemoveAll(RemoveNativePackage);
	}

	int32 NodeSize = 0;
	if ( ReferenceNames.Num() > 0 && !ExceedsMaxSearchDepth(CurrentDepth) )
	{
		int32 NumReferencesMade = 0;
		int32 NumReferencesExceedingMax = 0;
#if ECB_LEGACY
		// Filter for our registry source
		IAssetManagerEditorModule::Get().FilterAssetIdentifiersForCurrentRegistrySource(ReferenceNames, GetReferenceSearchFlags(false), !bReferencers);
#endif
		// Since there are referencers, use the size of all your combined referencers.
		// Do not count your own size since there could just be a horizontal line of nodes
		for (FExtAssetIdentifier& AssetId : ReferenceNames)
		{
			if ( !VisitedNames.Contains(AssetId) && (!AssetId.IsPackage() || !ShouldFilterByCollection() || AllowedPackageNames.Contains(AssetId.PackageName)) )
			{
				if ( !ExceedsMaxSearchBreadth(NumReferencesMade) )
				{
					TArray<FExtAssetIdentifier> NewPackageNames;
					NewPackageNames.Add(AssetId);
					NodeSize += RecursivelyGatherSizes(bReferencers, NewPackageNames, AllowedPackageNames, CurrentDepth + 1, VisitedNames, OutNodeSizes);
					NumReferencesMade++;
				}
				else
				{
					NumReferencesExceedingMax++;
				}
			}
		}

		if ( NumReferencesExceedingMax > 0 )
		{
			// Add one size for the collapsed node
			NodeSize++;
		}
	}

	if ( NodeSize == 0 )
	{
		// If you have no valid children, the node size is just 1 (counting only self to make a straight line)
		NodeSize = 1;
	}

	OutNodeSizes.Add(Identifiers[0], NodeSize);
	return NodeSize;
}
*/
void UEdGraph_ExtDependencyViewer::GetSortedLinks(const TArray<FExtAssetIdentifier>& Identifiers, bool bReferencers, const FAssetManagerDependencyQuery& Query, TMap<FExtAssetIdentifier, EExtDependencyPinCategory>& OutLinks) const
{

	// Using a simplified version without the complex sorting logic for now
	TArray<FExtAssetIdentifier> ReferenceNames;
	TArray<FExtAssetDependencyNode> DependNodes;

	if (bReferencers)
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			FExtContentBrowserSingleton::GetAssetRegistry().GetReferencers(AssetId, ReferenceNames, Query.Categories, Query.Flags);
		}
	}
	else
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			//FExtContentBrowserSingleton::GetAssetRegistry().GetDependencies(AssetId, ReferenceNames, Query.Categories, Query.Flags);
			FExtContentBrowserSingleton::GetAssetRegistry().GetDependencies(AssetId.PackageName, DependNodes, Query.Categories, Query.Flags);
		}
	}

	// Filter out native packages if needed
	if (!Settings->IsShowCodePackages())
	{
		//auto RemoveNativePackage = [](const FExtAssetIdentifier& InAsset) { return InAsset.PackageName.ToString().StartsWith(TEXT("/Script")) && !InAsset.IsValue(); };
		//ReferenceNames.RemoveAll(RemoveNativePackage);
		auto RemoveNativePackage = [](const FExtAssetDependencyNode& InNode) { return InNode.PackageName.ToString().StartsWith(TEXT("/Script")); };
		DependNodes.RemoveAll(RemoveNativePackage);

	}

	// Add to output map
	for (const FExtAssetDependencyNode& Node : DependNodes)
	{
		EExtDependencyPinCategory& Category = OutLinks.FindOrAdd(Node.PackageName, EExtDependencyPinCategory::LinkEndActive);

		bool bIsHard = Node.ReferenceType == EDependencyNodeReferenceType::Hard;
		bool bIsUsedInGame = true;// (LinkToAsset.Category != EDependencyCategory::Package) || ((LinkToAsset.Properties & EDependencyProperty::Game) != EDependencyProperty::None);
		Category |= EExtDependencyPinCategory::LinkEndActive;
		Category |= bIsHard ? EExtDependencyPinCategory::LinkTypeHard : EExtDependencyPinCategory::LinkTypeNone;
		Category |= bIsUsedInGame ? EExtDependencyPinCategory::LinkTypeUsedInGame : EExtDependencyPinCategory::LinkTypeNone;
	}

	// Apply collection filter
	if (ShouldFilterByCollection() && CurrentCollectionFilter != NAME_None)
	{
		TSet<FName> AllowedPackageNames;
		FCollectionManagerModule& CollectionManagerModule = FCollectionManagerModule::GetModule();
		TArray<FSoftObjectPath> AssetPaths;
		CollectionManagerModule.Get().GetProjectCollectionContainer()->GetAssetsInCollection(CurrentCollectionFilter, ECollectionShareType::CST_All, AssetPaths);
		AllowedPackageNames.Reserve(AssetPaths.Num());
		for (const FSoftObjectPath& AssetPath : AssetPaths)
		{
			AllowedPackageNames.Add(FName(*FPackageName::ObjectPathToPackageName(AssetPath.ToString())));
		}

		for (TMap<FExtAssetIdentifier, EExtDependencyPinCategory>::TIterator It(OutLinks); It; ++It)
		{
			if (It.Key().IsPackage() && !AllowedPackageNames.Contains(It.Key().PackageName))
			{
				It.RemoveCurrent();
			}
		}
	}
}

bool UEdGraph_ExtDependencyViewer::IsPackageIdentifierPassingFilter(const FExtAssetIdentifier& InAssetIdentifier) const
{
	if (!InAssetIdentifier.IsValue())
	{
		if (!Settings->IsShowCodePackages() && InAssetIdentifier.PackageName.ToString().StartsWith(TEXT("/Script")))
		{
			return false;
		}
	}

	return true;
}

bool UEdGraph_ExtDependencyViewer::IsPackageIdentifierPassingPluginFilter(const FExtAssetIdentifier& InAssetIdentifier) const
{
	if (!ShouldFilterByPlugin())
	{
		return true;
	}

	if (!InAssetIdentifier.IsPackage())
	{
		return true;
	}

	const FString AssetPath = InAssetIdentifier.PackageName.ToString();

	for (const FName& PluginName : CurrentPluginFilter)
	{
		if (AssetPath.StartsWith("/" + PluginName.ToString()))
		{
			return true;
		}
	}

	return false;
}

void UEdGraph_ExtDependencyViewer::GatherAssetData(const TSet<FName>& AllPackageNames, TMap<FName, FExtAssetData>& OutPackageToAssetDataMap) const
{
	// Get asset data for all packages from the ext asset registry
	for (const FName& PackageName : AllPackageNames)
	{
		FExtAssetData* CachedAssetData = FExtContentBrowserSingleton::Get().ExtAssetRegistry.GetCachedAssetByPackageName(PackageName);
		if (CachedAssetData && CachedAssetData->IsValid())
		{
			OutPackageToAssetDataMap.Add(PackageName, *CachedAssetData);
		}
		else
		{
			// If not cached, try to create a basic asset data
			OutPackageToAssetDataMap.Add(PackageName, FExtAssetData(PackageName));
		}
	}
}

UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::FindPath(const FExtAssetIdentifier& RootId, const FExtAssetIdentifier& TargetId)
{
	TargetIdentifier = TargetId;

	RemoveAllNodes();

	// Check for the target in the dependencies
	TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> NewNodeInfos;
	TSet<FExtAssetIdentifier> Visited;
	FExtReferenceNodeInfo& RootNodeInfo = NewNodeInfos.FindOrAdd(RootId, FExtReferenceNodeInfo(RootId, false));
	if (TargetId.IsValid())
	{
		FindPath_Recursive(false, RootId, TargetId, NewNodeInfos, Visited);
	}
	GatherAssetData(NewNodeInfos);
	DependencyNodeInfos = NewNodeInfos;

	// Check for the target in the references
	Visited.Empty();
	TMap<FExtAssetIdentifier, FExtReferenceNodeInfo> NewRefNodeInfos;
	FExtReferenceNodeInfo& RootRefNodeInfo = NewRefNodeInfos.FindOrAdd(RootId, FExtReferenceNodeInfo(RootId, true));
	if (TargetId.IsValid())
	{
		FindPath_Recursive(true, RootId, TargetId, NewRefNodeInfos, Visited);
	}
	GatherAssetData(NewRefNodeInfos);
	ReferencerNodeInfos = NewRefNodeInfos;

	UEdGraphNode_ExtDependency* NewRootNode = RefilterGraph();

	NotifyGraphChanged();

	return NewRootNode;
}

bool UEdGraph_ExtDependencyViewer::FindPath_Recursive(bool bInReferencers, const FExtAssetIdentifier& InAssetId, const FExtAssetIdentifier& TargetId, TMap<FExtAssetIdentifier, FExtReferenceNodeInfo>& InNodeInfos, TSet<FExtAssetIdentifier>& Visited)
{
	bool bFound = false;

	if (InAssetId == TargetId)
	{
		FExtReferenceNodeInfo& NewNodeInfo = InNodeInfos.FindOrAdd(InAssetId, FExtReferenceNodeInfo(InAssetId, bInReferencers));
		bFound = true;
	}

	// check if any decedents are the target and if any are found, add a node info for this asset as well
	else
	{
		Visited.Add(InAssetId);
		TMap<FExtAssetIdentifier, EExtDependencyPinCategory> ReferenceLinks;
		GetSortedLinks({InAssetId}, bInReferencers, GetReferenceSearchFlags(false), ReferenceLinks);

		for (const TPair<FExtAssetIdentifier, EExtDependencyPinCategory>& Pair : ReferenceLinks)
		{
			FExtAssetIdentifier ChildId = Pair.Key;
			if (!Visited.Contains(ChildId) && FindPath_Recursive(bInReferencers, ChildId, TargetId, InNodeInfos, Visited))
			{
				FExtReferenceNodeInfo& NewNodeInfo = InNodeInfos.FindOrAdd(InAssetId, FExtReferenceNodeInfo(InAssetId, bInReferencers));

				InNodeInfos[ChildId].Parents.AddUnique(InAssetId);
				InNodeInfos[InAssetId].Children.AddUnique(Pair);
				bFound = true;
			}
		}
	}

	return bFound;
}

/*
UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::RecursivelyConstructNodes(bool bReferencers, UEdGraphNode_ExtDependency* RootNode, const TArray<FExtAssetIdentifier>& Identifiers, const FIntPoint& NodeLoc, const TMap<FExtAssetIdentifier, int32>& NodeSizes, const TMap<FName, FExtAssetData>& PackagesToAssetDataMap, const TSet<FName>& AllowedPackageNames, int32 CurrentDepth, TSet<FExtAssetIdentifier>& VisitedNames)
{
	check(Identifiers.Num() > 0);

	VisitedNames.Append(Identifiers);

	UEdGraphNode_ExtDependency* NewNode = NULL;
	if ( RootNode->GetIdentifier() == Identifiers[0] )
	{
		// Don't create the root node. It is already created!
		NewNode = RootNode;
	}
	else
	{
		NewNode = CreateReferenceNode();
		NewNode->SetupReferenceNode(NodeLoc, Identifiers, PackagesToAssetDataMap.FindRef(Identifiers[0].PackageName), !Settings->IsCompactMode());
	}

	//FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	TArray<FExtAssetIdentifier> ReferenceNames;
	TArray<FExtAssetIdentifier> HardReferenceNames;

	const FAssetManagerDependencyQuery HardOnlyDependencyQuery = GetReferenceSearchFlags(true);
	const FAssetManagerDependencyQuery DependencyQuery = GetReferenceSearchFlags(false);
	if ( bReferencers )
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			FExtContentBrowserSingleton::GetAssetRegistry().GetReferencers(AssetId, HardReferenceNames, HardOnlyDependencyQuery.Categories);
			FExtContentBrowserSingleton::GetAssetRegistry().GetReferencers(AssetId, ReferenceNames, DependencyQuery.Categories);
		}
	}
	else
	{
		for (const FExtAssetIdentifier& AssetId : Identifiers)
		{
			FExtContentBrowserSingleton::GetAssetRegistry().GetDependencies(AssetId, HardReferenceNames, HardOnlyDependencyQuery.Categories);
			FExtContentBrowserSingleton::GetAssetRegistry().GetDependencies(AssetId, ReferenceNames, DependencyQuery.Categories);
		}
	}

	if (!Settings->IsShowCodePackages())
	{
		auto RemoveNativePackage = [](const FExtAssetIdentifier& InAsset) { return InAsset.PackageName.ToString().StartsWith(TEXT("/Script")) && !InAsset.IsValue(); };

		HardReferenceNames.RemoveAll(RemoveNativePackage);
		ReferenceNames.RemoveAll(RemoveNativePackage);
	}

	if ( ReferenceNames.Num() > 0 && !ExceedsMaxSearchDepth(CurrentDepth) )
	{
		FIntPoint ReferenceNodeLoc = NodeLoc;

		if ( bReferencers )
		{
			// Referencers go left
			ReferenceNodeLoc.X -= NodeXSpacing;
		}
		else
		{
			// Dependencies go right
			ReferenceNodeLoc.X += NodeXSpacing;
		}

		// Make vertical spacing proportional to horizontal spacing for consistency
		float VerticalScaleFactor = 0.5f;  // Normal mode factor
		int32 NodeSizeY = FMath::RoundToInt(NodeXSpacing * VerticalScaleFactor);
		NodeSizeY = FMath::Clamp(NodeSizeY, 100, 400);  // Ensure reasonable minimum/maximum values
		const int32 TotalReferenceSizeY = NodeSizes.FindChecked(Identifiers[0]) * NodeSizeY;

		ReferenceNodeLoc.Y -= TotalReferenceSizeY * 0.5f;
		ReferenceNodeLoc.Y += NodeSizeY * 0.5f;

		int32 NumReferencesMade = 0;
		int32 NumReferencesExceedingMax = 0;

#if ECB_LEGACY
		// Filter for our registry source
		IAssetManagerEditorModule::Get().FilterAssetIdentifiersForCurrentRegistrySource(ReferenceNames, GetReferenceSearchFlags(false), !bReferencers);
		IAssetManagerEditorModule::Get().FilterAssetIdentifiersForCurrentRegistrySource(HardReferenceNames, GetReferenceSearchFlags(false), !bReferencers);
#endif

		for ( int32 RefIdx = 0; RefIdx < ReferenceNames.Num(); ++RefIdx )
		{
			FExtAssetIdentifier ReferenceName = ReferenceNames[RefIdx];

			if ( !VisitedNames.Contains(ReferenceName) && (!ReferenceName.IsPackage() || !ShouldFilterByCollection() || AllowedPackageNames.Contains(ReferenceName.PackageName)) )
			{
				bool bIsHardReference = HardReferenceNames.Contains(ReferenceName);

				if ( !ExceedsMaxSearchBreadth(NumReferencesMade) )
				{
					// Use proportional smaller size for value types
					int32 ThisNodeSizeY = ReferenceName.IsValue() ? FMath::RoundToInt(NodeSizeY * 0.5f) : NodeSizeY;

					const int32 RefSizeY = NodeSizes.FindChecked(ReferenceName);
					FIntPoint RefNodeLoc;
					RefNodeLoc.X = ReferenceNodeLoc.X;
					RefNodeLoc.Y = ReferenceNodeLoc.Y + RefSizeY * ThisNodeSizeY * 0.5 - ThisNodeSizeY * 0.5;

					TArray<FExtAssetIdentifier> NewIdentifiers;
					NewIdentifiers.Add(ReferenceName);

					UEdGraphNode_ExtDependency* ReferenceNode = RecursivelyConstructNodes(bReferencers, RootNode, NewIdentifiers, RefNodeLoc, NodeSizes, PackagesToAssetDataMap, AllowedPackageNames, CurrentDepth + 1, VisitedNames);
					if (bIsHardReference)
					{
						if (bReferencers)
						{
							ReferenceNode->GetDependencyPin()->PinType.PinCategory = TEXT("hard");
						}
						else
						{
							ReferenceNode->GetReferencerPin()->PinType.PinCategory = TEXT("hard"); //-V595
						}
					}

					bool bIsMissingOrInvalid = ReferenceNode->IsMissingOrInvalid();
					if (bIsMissingOrInvalid)
					{
						if (bReferencers)
						{
							ReferenceNode->GetDependencyPin()->PinType.PinSubCategory = TEXT("invalid");
						}
						else
						{
							ReferenceNode->GetReferencerPin()->PinType.PinSubCategory = TEXT("invalid");
						}

						ReferenceNode->bHasCompilerMessage = true;
						if (!bIsHardReference)
						{
							ReferenceNode->ErrorType = EMessageSeverity::Warning;
						}
						else
						{
							ReferenceNode->ErrorType = EMessageSeverity::Error;
						}
					}

					if ( ensure(ReferenceNode) )
					{
						if ( bReferencers )
						{
							NewNode->AddReferencer( ReferenceNode );
						}
						else
						{
							ReferenceNode->AddReferencer( NewNode );
						}

						ReferenceNodeLoc.Y += RefSizeY * ThisNodeSizeY;
					}

					NumReferencesMade++;
				}
				else
				{
					NumReferencesExceedingMax++;
				}
			}
		}

		if ( NumReferencesExceedingMax > 0 )
		{
			// There are more references than allowed to be displayed. Make a collapsed node.
			UEdGraphNode_ExtDependency* ReferenceNode = CreateReferenceNode();
			FIntPoint RefNodeLoc;
			RefNodeLoc.X = ReferenceNodeLoc.X;
			RefNodeLoc.Y = ReferenceNodeLoc.Y;

			if ( ensure(ReferenceNode) )
			{
				ReferenceNode->SetAllowThumbnail(!Settings->IsCompactMode());
				ReferenceNode->SetReferenceNodeCollapsed(RefNodeLoc, NumReferencesExceedingMax);

				if ( bReferencers )
				{
					NewNode->AddReferencer( ReferenceNode );
				}
				else
				{
					ReferenceNode->AddReferencer( NewNode );
				}
			}
		}
	}

	return NewNode;
}
*/

const TSharedPtr<FExtAssetThumbnailPool>& UEdGraph_ExtDependencyViewer::GetAssetThumbnailPool() const
{
	return AssetThumbnailPool;
}


UEdGraphNode_ExtDependency* UEdGraph_ExtDependencyViewer::CreateReferenceNode()
{
	const bool bSelectNewNode = false;
	return Cast<UEdGraphNode_ExtDependency>(CreateNode(UEdGraphNode_ExtDependency::StaticClass(), bSelectNewNode));
}

void UEdGraph_ExtDependencyViewer::RemoveAllNodes()
{
	TArray<UEdGraphNode*> NodesToRemove = Nodes;
	for (int32 NodeIndex = 0; NodeIndex < NodesToRemove.Num(); ++NodeIndex)
	{
		RemoveNode(NodesToRemove[NodeIndex]);
	}
}

bool UEdGraph_ExtDependencyViewer::ShouldFilterByCollection() const
{
	return Settings->GetEnableCollectionFilter() && CurrentCollectionFilter != NAME_None; 
}

bool UEdGraph_ExtDependencyViewer::ShouldFilterByPlugin() const
{
	return Settings->GetEnablePluginFilter() && CurrentPluginFilter.Num() > 0;
}

bool UEdGraph_ExtDependencyViewer::ExceedsMaxSearchDepth(int32 Depth, int32 MaxDepth) const
{
	const bool bIsWithinDepthLimits = (MaxDepth > 0 && Depth < MaxDepth);
	// the FindPath feature is not depth limited
	if (Settings && Settings->GetFindPathEnabled())
	{
		return false;
	}
	else if (Settings->IsSearchDepthLimited() && !bIsWithinDepthLimits)
	{
		return true;
	}

	return false;
}

bool UEdGraph_ExtDependencyViewer::ExceedsMaxSearchBreadth(int32 Breadth) const
{
	// the FindPath feature is not breadth limited
	if (Settings && Settings->GetFindPathEnabled())
	{
		return false;
	}

	// ExceedsMaxSearchBreadth requires greater or equal than because the Breadth is 1-based indexed
	return Settings->IsSearchBreadthLimited() && (Breadth >= Settings->GetSearchBreadthLimit());
}

void UEdGraph_ExtDependencyViewer::ExpandNode(bool bReferencers, const FExtAssetIdentifier& InAssetIdentifier)
{
	if (!bReferencers && DependencyNodeInfos.Contains(InAssetIdentifier))
	{
		DependencyNodeInfos[InAssetIdentifier].bExpandAllChildren = true;
		RefilterGraph();
	}
	else if (bReferencers && ReferencerNodeInfos.Contains(InAssetIdentifier))
	{
		ReferencerNodeInfos[InAssetIdentifier].bExpandAllChildren = true;
		RefilterGraph();
	}
}
