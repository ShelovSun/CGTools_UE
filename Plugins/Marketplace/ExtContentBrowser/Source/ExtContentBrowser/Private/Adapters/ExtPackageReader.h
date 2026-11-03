// Copyright 2017-2021 marynate. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Misc/EnumClassFlags.h"
#include "Serialization/ArchiveUObject.h"
#include "UObject/ObjectResource.h"
#include "UObject/PackageFileSummary.h"
#include "UObject/Linker.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Containers/ArrayView.h"
#include "Containers/BitArray.h"


struct FExtAssetData;
class FExtPackageDependencyData;
class FObjectThumbnail;

/**
 * Class for read and parse package file
 */
class FExtPackageReader : public FArchiveUObject
{
public:
	FExtPackageReader();
	~FExtPackageReader();

	enum class EOpenPackageResult : uint8
	{
		Success,
		NoLoader,
		MalformedTag,
		VersionTooOld,
		VersionTooNew,
		CustomVersionMissing,
		CustomVersionInvalid,
		Unversioned,
		FailedToLoad
	};

	/** Creates a loader for the filename */
	bool OpenPackageFile(const FString& PackageFilename, EOpenPackageResult* OutErrorCode = nullptr);
	bool OpenPackageFile(FArchive* Loader, EOpenPackageResult* OutErrorCode = nullptr);
	bool OpenPackageFile(EOpenPackageResult* OutErrorCode = nullptr);

	/**
	 * Returns the LongPackageName from constructor if provided, otherwise calculates it from
	 * FPackageName::TryConvertFilenameToLongPackageName.
	 */
	bool TryGetLongPackageName(FString& OutLongPackageName) const;

	/** Reads information from the asset registry data table and converts it to FAssetData */
	bool ReadAssetRegistryData(TArray<FAssetData*>& AssetDataList);

	/** Attempts to get the class name of an object from the thumbnail cache for packages older than VER_UE4_ASSET_REGISTRY_TAGS */
	bool ReadAssetDataFromThumbnailCache(TArray<FAssetData*>& AssetDataList);

	/** Creates asset data reconstructing all the required data from cooked package info */
	bool ReadAssetRegistryDataIfCookedPackage(TArray<FAssetData*>& AssetDataList, TArray<FString>& CookedPackageNamesWithoutAssetData);

	/** Options for what to read in functions that read multiple things at once. */
	enum class EReadOptions
	{
		None = 0,
		PackageData = 1 << 0,
		Dependencies = 1 << 1,
		Default = PackageData | Dependencies,
	};
	/** Reads information used by the dependency graph */
	bool ReadDependencyData(FExtPackageDependencyData& OutDependencyData, EReadOptions Options);

	/** Serializers for different package maps */
	bool SerializeNameMap();
	bool SerializeImportMap();
	bool SerializeExportMap();
	bool SerializeImportedClasses(const TArray<FObjectImport>& InImportMap, TArray<FName>& OutClassNames);
	bool SerializeSoftPackageReferenceList();
	bool SerializeSearchableNamesMap(FLinkerTables& OutSearchableNames);
	bool SerializeAssetRegistryDependencyData(TBitArray<>& OutImportUsedInGame, TBitArray<>& OutSoftPackageUsedInGame,
		TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& OutExtraPackageDependencies);
	bool SerializePackageTrailer(FAssetPackageData& PackageData);

	void ApplyRelocationToImportMapAndSoftPackageReferenceList(FStringView LoadedPackageName,
		TArray<FName>& InOutSoftPackageReferenceList,
		TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& InOutExtraPackageDependencies);
	static void ConvertLinkerTableToPaths(FName PackageName, TArray<FObjectExport>& ExportMap,
		TArray<FObjectImport>& ImportMap, TArray<FSoftObjectPath>& OutExports, TArray<FSoftObjectPath>& OutImports);


	/** Returns flags the asset package was saved with */
	uint32 GetPackageFlags() const;

	// Farchive implementation to redirect requests to the Loader
	void Serialize( void* V, int64 Length );
	bool Precache( int64 PrecacheOffset, int64 PrecacheSize );
	void Seek( int64 InPos );
	int64 Tell();
	int64 TotalSize();
	FArchive& operator<<( FName& Name );
	virtual FString GetArchiveName() const override
	{
		return PackageFilename;
	}

	//////////////////////////////////
	// For FExtAssetData 
	const FPackageFileSummary& GetPackageFileSummary() const;
	int32 GetSoftPackageReferencesCount() const;
	/** Reads information from the asset registry data table and converts it to FAssetData */
	bool ReadAssetRegistryData(FExtAssetData& OutAssetData);
	/** Attempts to get the class name of an object from the thumbnail cache for packages older than VER_UE4_ASSET_REGISTRY_TAGS */
	bool ReadAssetDataFromThumbnailCache(FExtAssetData& OutAssetData);
	/** Reads information used by the dependency graph */
	bool ReadDependencyData(FExtAssetData& OutAssetData);
	bool ReadThumbnail(FObjectThumbnail& OutThumbnail);

private:
	bool StartSerializeSection(int64 Offset);

	FString LongPackageName;
	FString PackageFilename;
	FArchive* Loader;
	FPackageFileSummary PackageFileSummary;
	TArray<FName> NameMap;
	TArray<FObjectImport> ImportMap;
	TArray<FObjectExport> ExportMap;
	TArray<TArray<FPackageIndex>> DependsMap;
	TArray<FName> SoftPackageReferenceList;
	TArray<FSoftObjectPath> SoftObjectPathMap;
	TArray<FGatherableTextData> GatherableTextDataMap;
	TArray<FObjectFullNameAndThumbnail> ThumbnailMap;
	int64 PackageFileSize;
	int64 AssetRegistryDependencyDataOffset;
	bool bLoaderOwner;
};

/**
 * Support class for gathering package dependency data
 */ 
class FExtPackageDependencyData_Legacy : public FLinkerTables
{
public:
	/** The name of the package that dependency data is gathered from */
	FName PackageName;

	/** Asset Package data, gathered at the same time as dependency data */
	FAssetPackageData PackageData;

	TBitArray<> ImportUsedInGame;
	TBitArray<> SoftPackageUsedInGame;

	// Transient Flags indicating which types of data have been gathered
	bool bHasPackageData = false;
	bool bHasDependencyData = false;

	/**
	 * Return the package name of the UObject represented by the specified import.
	 *
	 * @param	PackageIndex	package index for the resource to get the name for
	 *
	 * @return	the path name of the UObject represented by the resource at PackageIndex, or the empty string if this isn't an import
	 */
	FName GetImportPackageName(int32 ImportIndex);

	/**
	 * Serialize as part of the registry cache. This is not meant to be serialized as part of a package so  it does not handle versions normally
	 * To version this data change FAssetRegistryVersion or CacheSerializationVersion
	 */
	void SerializeForCache(FArchive& Ar)
	{
		Ar << PackageName;
		Ar << SoftPackageReferenceList;
		Ar << SearchableNamesMap;
		PackageData.SerializeForCache(Ar);
	}
};

class FExtPackageDependencyData
{
public:
	struct FPackageDependency
	{
		FName PackageName;
		UE::AssetRegistry::EDependencyProperty Property;
		friend FArchive& operator<<(FArchive& Ar, FPackageDependency& Dependency)
		{
			Ar << Dependency.PackageName;
			uint8 PropertyAsInteger = static_cast<uint8>(Dependency.Property);
			Ar << PropertyAsInteger;
			Dependency.Property = static_cast<UE::AssetRegistry::EDependencyProperty>(PropertyAsInteger);
			return Ar;
		}

		bool operator==(const FPackageDependency& Other) const
		{
			return PackageName == Other.PackageName && Property == Other.Property;
		}
	};
	struct FSearchableNamesDependency
	{
		FName PackageName;
		FName ObjectName;
		TArray<FName> ValueNames;
		friend FArchive& operator<<(FArchive& Ar, FSearchableNamesDependency& Dependency)
		{
			Ar << Dependency.PackageName << Dependency.ObjectName << Dependency.ValueNames;
			return Ar;
		}
	};

	/** The name of the package that dependency data is gathered from */
	FName PackageName;

	/** Asset Package data, gathered at the same time as dependency data */
	FAssetPackageData PackageData;

	// Dependency Data
	TArray<FPackageDependency> PackageDependencies;
	TArray<FSearchableNamesDependency> SearchableNameDependencies;

	// Transient Flags indicating which types of data have been gathered
	bool bHasPackageData = false;
	bool bHasDependencyData = false;

	/**
	 * Serialize as part of the registry cache. This is not meant to be serialized as part of a package so it does not handle versions normally
	 * To version this data change FAssetRegistryVersion or AssetDataGathererConstants::CacheSerializationMagic
	 */
	void SerializeForCache(FArchive& Ar)
	{
		Ar << PackageName;
		PackageData.SerializeForCache(Ar);
		Ar << PackageDependencies;
		Ar << SearchableNameDependencies;
	}

	void LoadDependenciesFromPackageHeader(FName PackageName, TConstArrayView<FObjectImport> ImportMap,
		TArray<FName>& SoftPackageReferenceList, TMap<FPackageIndex, TArray<FName>>& SearchableNames,
		TBitArray<>& ImportUsedInGame, TBitArray<>& SoftPackageUsedInGame,
		TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& ExtraPackageDependencies);

	/** Returns the amount of memory allocated by this container, not including sizeof(*this). */
	SIZE_T GetAllocatedSize() const
	{
		SIZE_T Result = PackageDependencies.GetAllocatedSize();
		Result += SearchableNameDependencies.GetAllocatedSize();
		Result += PackageData.GetAllocatedSize();
		return Result;
	}

private:
	FName GetImportPackageName(TConstArrayView<FObjectImport> ImportMap, int32 ImportIndex);


};

