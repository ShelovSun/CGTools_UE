// Copyright 2017-2021 marynate. All Rights Reserved.

#include "ExtDependencyViewerSettings.h"

UExtDependencyViewerSettings::UExtDependencyViewerSettings()
{
	// Initialize default values
	bLimitSearchDepth = true;
	bIsShowReferencers = false;
	MaxSearchReferencerDepth = 1;
	bIsShowDependencies = true;
	MaxSearchDependencyDepth = 1;
	bLimitSearchBreadth = false;
	MaxSearchBreadth = 20;
	bEnableCollectionFilter = false;
	bEnablePluginFilter = false;
	bIsShowSoftReferences = true;
	bIsShowHardReferences = true;
	bIsShowEditorOnlyReferences = false;
	bIsShowManagementReferences = true;
	bIsShowSearchableNames = false;
	bIsShowCodePackages = false;
	bIsShowDuplicates = true;
	bIsShowFilteredPackagesOnly = false;
	bIsCompactMode = false;
	bIsShowExternalReferencers = true;
	bIsShowPath = false;
	bFiltersEnabled = true;
	bAutoUpdateFilters = true;
	bFindPathEnabled = false;
	NodeSpacingScale = 0.25f;
}

bool UExtDependencyViewerSettings::IsSearchDepthLimited() const
{
	return bLimitSearchDepth;
}

void UExtDependencyViewerSettings::SetSearchDepthLimitEnabled(bool bNewEnabled)
{
	bLimitSearchDepth = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowReferencers() const
{
	return bIsShowReferencers;
}

void UExtDependencyViewerSettings::SetShowReferencers(const bool bShouldShowReferencers)
{
	bIsShowReferencers = bShouldShowReferencers;
	SaveConfig();
}

int32 UExtDependencyViewerSettings::GetSearchReferencerDepthLimit() const
{
	return MaxSearchReferencerDepth;
}

void UExtDependencyViewerSettings::SetSearchReferencerDepthLimit(int32 NewDepthLimit, bool bSaveConfig)
{
	MaxSearchReferencerDepth = NewDepthLimit;
	if (bSaveConfig)
	{
		SaveConfig();
	}
}

bool UExtDependencyViewerSettings::IsShowDependencies() const
{
	return bIsShowDependencies;
}

void UExtDependencyViewerSettings::SetShowDependencies(const bool bShouldShowDependencies)
{
	bIsShowDependencies = bShouldShowDependencies;
	SaveConfig();
}

int32 UExtDependencyViewerSettings::GetSearchDependencyDepthLimit() const
{
	return MaxSearchDependencyDepth;
}

void UExtDependencyViewerSettings::SetSearchDependencyDepthLimit(int32 NewDepthLimit, bool bSaveConfig)
{
	MaxSearchDependencyDepth = NewDepthLimit;
	if (bSaveConfig)
	{
		SaveConfig();
	}
}

bool UExtDependencyViewerSettings::IsSearchBreadthLimited() const
{
	return bLimitSearchBreadth;
}

void UExtDependencyViewerSettings::SetSearchBreadthLimitEnabled(bool bNewEnabled)
{
	bLimitSearchBreadth = bNewEnabled;
	SaveConfig();
}

int32 UExtDependencyViewerSettings::GetSearchBreadthLimit() const
{
	return MaxSearchBreadth;
}

void UExtDependencyViewerSettings::SetSearchBreadthLimit(int32 NewBreadthLimit)
{
	MaxSearchBreadth = NewBreadthLimit;
	SaveConfig();
}

bool UExtDependencyViewerSettings::GetEnableCollectionFilter() const
{
	return bEnableCollectionFilter;
}

void UExtDependencyViewerSettings::SetEnableCollectionFilter(bool bEnabled)
{
	bEnableCollectionFilter = bEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::GetEnablePluginFilter() const
{
	return bEnablePluginFilter;
}

void UExtDependencyViewerSettings::SetEnablePluginFilter(bool bEnabled)
{
	bEnablePluginFilter = bEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowSoftReferences() const
{
	return bIsShowSoftReferences;
}

void UExtDependencyViewerSettings::SetShowSoftReferencesEnabled(bool bNewEnabled)
{
	bIsShowSoftReferences = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowHardReferences() const
{
	return bIsShowHardReferences;
}

void UExtDependencyViewerSettings::SetShowHardReferencesEnabled(bool bNewEnabled)
{
	bIsShowHardReferences = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowEditorOnlyReferences() const
{
	return bIsShowEditorOnlyReferences;
}

void UExtDependencyViewerSettings::SetShowEditorOnlyReferencesEnabled(bool bNewEnabled)
{
	bIsShowEditorOnlyReferences = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowManagementReferences() const
{
	return bIsShowManagementReferences;
}

void UExtDependencyViewerSettings::SetShowManagementReferencesEnabled(bool bNewEnabled)
{
	bIsShowManagementReferences = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowSearchableNames() const
{
	return bIsShowSearchableNames;
}

void UExtDependencyViewerSettings::SetShowSearchableNames(bool bNewEnabled)
{
	bIsShowSearchableNames = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowCodePackages() const
{
	return bIsShowCodePackages;
}

void UExtDependencyViewerSettings::SetShowCodePackages(bool bNewEnabled)
{
	bIsShowCodePackages = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowDuplicates() const
{
	return bIsShowDuplicates;
}

void UExtDependencyViewerSettings::SetShowDuplicatesEnabled(bool bNewEnabled)
{
	bIsShowDuplicates = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowFilteredPackagesOnly() const
{
	return bIsShowFilteredPackagesOnly;
}

void UExtDependencyViewerSettings::SetShowFilteredPackagesOnlyEnabled(bool bNewEnabled)
{
	bIsShowFilteredPackagesOnly = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsCompactMode() const
{
	return bIsCompactMode;
}

void UExtDependencyViewerSettings::SetCompactModeEnabled(bool bNewEnabled)
{
	bIsCompactMode = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowExternalReferencers() const
{
	return bIsShowExternalReferencers;
}

void UExtDependencyViewerSettings::SetShowExternalReferencersEnabled(bool bNewEnabled)
{
	bIsShowExternalReferencers = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::IsShowPath() const
{
	return bIsShowPath;
}

void UExtDependencyViewerSettings::SetShowPathEnabled(bool bNewEnabled)
{
	bIsShowPath = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::GetFiltersEnabled() const
{
	return bFiltersEnabled;
}

void UExtDependencyViewerSettings::SetFiltersEnabled(bool bNewEnabled)
{
	bFiltersEnabled = bNewEnabled;
	SaveConfig();
}

bool UExtDependencyViewerSettings::AutoUpdateFilters() const
{
	return bAutoUpdateFilters;
}

void UExtDependencyViewerSettings::SetAutoUpdateFilters(bool bNewEnabled)
{
	bAutoUpdateFilters = bNewEnabled;
	SaveConfig();
}

const TArray<FExtFilterState>& UExtDependencyViewerSettings::GetUserFilters() const
{
	return UserFilters;
}

void UExtDependencyViewerSettings::SetUserFilters(TArray<FExtFilterState>& InFilters)
{
	UserFilters = InFilters;
	SaveConfig();
}

bool UExtDependencyViewerSettings::GetFindPathEnabled() const
{
	return bFindPathEnabled;
}

void UExtDependencyViewerSettings::SetFindPathEnabled(bool bNewEnabled)
{
	bFindPathEnabled = bNewEnabled;
	SaveConfig();
}

float UExtDependencyViewerSettings::GetNodeSpacingScale() const
{
	return NodeSpacingScale;
}

void UExtDependencyViewerSettings::SetNodeSpacingScale(float NewNodeSpacingScale)
{
	NodeSpacingScale = NewNodeSpacingScale;
	SaveConfig();
}

void UExtDependencyViewerSettings::InitWithDependcyViewerDefaultSetting()
{
	bIsShowReferencers = false;
	bIsShowDependencies = true;
	MaxSearchBreadth = 20;
	MaxSearchDependencyDepth = 1;
	bIsShowEditorOnlyReferences = false;
	bIsShowDuplicates = true;
}
