// Copyright 2017-2021 marynate. All Rights Reserved.

#include "ExtPackageReader.h"
#include "ExtContentBrowser.h"
#include "ExtAssetData.h"

//#include "AssetRegistry.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "Logging/MessageLog.h"
#include "Misc/Guid.h"
#include "Misc/PackageName.h"
#include "Misc/PackagePath.h"
#include "Misc/ScopeExit.h"
#include "UObject/Class.h"
#include "UObject/Linker.h"
#include "UObject/LinkerLoad.h"
#include "UObject/PackageRelocation.h"
#include "UObject/PackageTrailer.h"


#include "Algo/Unique.h"

FExtPackageReader::FExtPackageReader()
{
	Loader = nullptr;
	PackageFileSize = 0;
	AssetRegistryDependencyDataOffset = INDEX_NONE;
	bLoaderOwner = false;

	this->SetIsLoading(true);
	this->SetIsPersistent(true);
}

FExtPackageReader::~FExtPackageReader()
{
	if (Loader && bLoaderOwner)
	{
		delete Loader;
	}
}

bool FExtPackageReader::OpenPackageFile(const FString& InPackageFilename, EOpenPackageResult* OutErrorCode)
{
	PackageFilename = InPackageFilename;
	Loader = IFileManager::Get().CreateFileReader(*PackageFilename);
	bLoaderOwner = true;
	return OpenPackageFile(OutErrorCode);
}

bool FExtPackageReader::OpenPackageFile(FArchive* InLoader, EOpenPackageResult* OutErrorCode)
{
	Loader = InLoader;
	bLoaderOwner = false;
	PackageFilename = Loader->GetArchiveName();
	return OpenPackageFile(OutErrorCode);
}

bool FExtPackageReader::OpenPackageFile(EOpenPackageResult* OutErrorCode)
{
	auto SetPackageErrorCode = [&](const EOpenPackageResult InErrorCode)
	{
		if (OutErrorCode)
		{
			*OutErrorCode = InErrorCode;
		}
	};

	if( Loader == nullptr )
	{
		// Couldn't open the file
		SetPackageErrorCode(EOpenPackageResult::NoLoader);
		return false;
	}

	// Read package file summary from the file
	*Loader << PackageFileSummary;

	// Validate the summary.

	// Make sure this is indeed a package
	if( PackageFileSummary.Tag != PACKAGE_FILE_TAG || Loader->IsError() )
	{
		// Unrecognized or malformed package file
		SetPackageErrorCode(EOpenPackageResult::MalformedTag);
		return false;
	}

	// Don't read packages without header
	if (PackageFileSummary.TotalHeaderSize == 0)
	{
		SetPackageErrorCode(EOpenPackageResult::FailedToLoad);
		return false;
	}

	if (!PackageFileSummary.IsFileVersionValid())
	{
		// Log a warning rather than an error. Linkerload gracefully handles this case.
		SetPackageErrorCode(EOpenPackageResult::Unversioned);
		return false;
	}

	// Don't read packages that are too old
	if( PackageFileSummary.IsFileVersionTooOld())
	{
		SetPackageErrorCode(EOpenPackageResult::VersionTooOld);
		return false;
	}

	// Don't read packages that were saved with an package version newer than the current one.
	if(PackageFileSummary.IsFileVersionTooNew() || PackageFileSummary.GetFileVersionLicenseeUE() > GPackageFileLicenseeUEVersion)
	{
		SetPackageErrorCode(EOpenPackageResult::VersionTooNew);
		return false;
	}

	// Check serialized custom versions against latest custom versions.
#if ECB_WIP_IMPORT_CHECK_CUSTOM_VERSION // Ignore Custom Version Check
	TArray<FCustomVersionDifference> Diffs = FCurrentCustomVersions::Compare(PackageFileSummary.GetCustomVersionContainer().GetAllVersions(), *PackageFilename);
	for (FCustomVersionDifference Diff : Diffs)
	{
		if (Diff.Type == ECustomVersionDifference::Missing)
		{
			SetPackageErrorCode(EOpenPackageResult::CustomVersionMissing);
			return false;
		}
		else if (Diff.Type == ECustomVersionDifference::Invalid)
		{
			SetPackageErrorCode(EOpenPackageResult::CustomVersionInvalid);
			return false;
		}
		else if (Diff.Type == ECustomVersionDifference::Newer)
		{
			SetPackageErrorCode(EOpenPackageResult::VersionTooNew);
			return false;
		}
	}
#endif //

	//make sure the filereader gets the correct version number (it defaults to latest version)
	SetUEVer(PackageFileSummary.GetFileVersionUE());
	SetLicenseeUEVer(PackageFileSummary.GetFileVersionLicenseeUE());
	SetEngineVer(PackageFileSummary.SavedByEngineVersion);
	Loader->SetUEVer(PackageFileSummary.GetFileVersionUE());
	Loader->SetLicenseeUEVer(PackageFileSummary.GetFileVersionLicenseeUE());
	Loader->SetEngineVer(PackageFileSummary.SavedByEngineVersion);

	SetByteSwapping(Loader->ForceByteSwapping());

	const FCustomVersionContainer& PackageFileSummaryVersions = PackageFileSummary.GetCustomVersionContainer();
	SetCustomVersions(PackageFileSummaryVersions);
	Loader->SetCustomVersions(PackageFileSummaryVersions);

	PackageFileSize = Loader->TotalSize();

	if (LongPackageName.IsEmpty())
	{
		LongPackageName = PackageFileSummary.PackageName;
	}

	SetPackageErrorCode(EOpenPackageResult::Success);
	return true;
}

bool FExtPackageReader::TryGetLongPackageName(FString& OutLongPackageName) const
{
	if (!LongPackageName.IsEmpty())
	{
		OutLongPackageName = LongPackageName;
		return true;
	}
	else
	{
		return FPackageName::TryConvertFilenameToLongPackageName(PackageFilename, OutLongPackageName);
	}
}

bool FExtPackageReader::StartSerializeSection(int64 Offset)
{
	check(Loader);
	if (Offset <= 0 || Offset > PackageFileSize)
	{
		return false;
	}
	ClearError();
	Loader->ClearError();
	Seek(Offset);
	return !IsError();
}


namespace UA::AssetRegistry
{
	class FNameMapAwareArchive : public FArchiveProxy
	{
		TArray<FNameEntryId>	NameMap;

	public:

		FNameMapAwareArchive(FArchive& Inner)
			: FArchiveProxy(Inner)
		{}

		FORCEINLINE virtual FArchive& operator<<(FName& Name) override
		{
			FArchive& Ar = *this;
			int32 NameIndex;
			Ar << NameIndex;
			int32 Number = 0;
			Ar << Number;

			if (NameMap.IsValidIndex(NameIndex))
			{
				// if the name wasn't loaded (because it wasn't valid in this context)
				FNameEntryId MappedName = NameMap[NameIndex];

				// simply create the name from the NameMap's name and the serialized instance number
				Name = FName::CreateFromDisplayId(MappedName, Number);
			}
			else
			{
				Name = FName();
				SetCriticalError();
			}

			return *this;
		}

		void SerializeNameMap(const FPackageFileSummary& PackageFileSummary)
		{
			Seek(PackageFileSummary.NameOffset);
			NameMap.Reserve(PackageFileSummary.NameCount);
			FNameEntrySerialized NameEntry(ENAME_LinkerConstructor);
			for (int32 Idx = NameMap.Num(); Idx < PackageFileSummary.NameCount; ++Idx)
			{
				*this << NameEntry;
				NameMap.Emplace(FName(NameEntry).GetDisplayIndex());
			}
		}
	};
	FString ReconstructFullClassPath(FArchive& BinaryArchive, const FString& PackageName, const FPackageFileSummary& PackageFileSummary, const FString& AssetClassName,
		const TArray<FObjectImport>* InImports = nullptr, const TArray<FObjectExport>* InExports = nullptr)
	{
		FName ClassFName(*AssetClassName);
		FLinkerTables LinkerTables;
		if (!InImports || !InExports)
		{
			FNameMapAwareArchive NameMapArchive(BinaryArchive);
			NameMapArchive.SerializeNameMap(PackageFileSummary);

			// Load the linker tables
			if (!InImports)
			{
				BinaryArchive.Seek(PackageFileSummary.ImportOffset);
				for (int32 ImportMapIndex = 0; ImportMapIndex < PackageFileSummary.ImportCount; ++ImportMapIndex)
				{
					NameMapArchive << LinkerTables.ImportMap.Emplace_GetRef();
				}
			}
			if (!InExports)
			{
				BinaryArchive.Seek(PackageFileSummary.ExportOffset);
				for (int32 ExportMapIndex = 0; ExportMapIndex < PackageFileSummary.ExportCount; ++ExportMapIndex)
				{
					NameMapArchive << LinkerTables.ExportMap.Emplace_GetRef();
				}
			}
		}
		if (InImports)
		{
			LinkerTables.ImportMap = *InImports;
		}
		if (InExports)
		{
			LinkerTables.ExportMap = *InExports;
		}

		FString ClassPathName;

		// Now look through the exports' classes and find the one matching the asset class
		for (const FObjectExport& Export : LinkerTables.ExportMap)
		{
			if (Export.ClassIndex.IsImport())
			{
				if (LinkerTables.ImportMap[Export.ClassIndex.ToImport()].ObjectName == ClassFName)
				{
					ClassPathName = LinkerTables.GetImportPathName(Export.ClassIndex.ToImport());
					break;
				}
			}
			else if (Export.ClassIndex.IsExport())
			{
				if (LinkerTables.ExportMap[Export.ClassIndex.ToExport()].ObjectName == ClassFName)
				{
					ClassPathName = LinkerTables.GetExportPathName(PackageName, Export.ClassIndex.ToExport());
					break;
				}
			}
		}
		if (ClassPathName.IsEmpty())
		{
			//UE_LOG(LogAssetRegistry, Error, TEXT("Failed to find an import or export matching asset class short name \"%s\"."), *AssetClassName);
			// Just pass through the short class name
			ClassPathName = AssetClassName;
		}


		return ClassPathName;
	}

};


#define ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING(MessageKey, PackageFileName) \
	do \
	{\
		FFormatNamedArguments CorruptPackageWarningArguments; \
		CorruptPackageWarningArguments.Add(TEXT("FileName"), FText::FromString(PackageFileName)); \
		FMessageLog("AssetRegistry").Warning(FText::Format(NSLOCTEXT("AssetRegistry", MessageKey, "Cannot read AssetRegistry Data in {FileName}, skipping it. Error: " MessageKey "."), CorruptPackageWarningArguments)); \
	} while (false)

bool FExtPackageReader::ReadAssetRegistryData (TArray<FAssetData*>& AssetDataList)
{
	if (!StartSerializeSection(PackageFileSummary.AssetRegistryDataOffset))
	{
		return false;
	}

	FString PackageName;
	if (!FPackageName::TryConvertFilenameToLongPackageName(PackageFilename, PackageName))
	{
		// Path was possibly unmounted
		return false;
	}
	FString PackagePath = FPackageName::GetLongPackagePath(PackageName);
	const bool bIsMapPackage = (PackageFileSummary.GetPackageFlags() & PKG_ContainsMap) != 0;

	// ? To avoid large patch sizes, we have frozen cooked package format at the format before VER_UE4_ASSETREGISTRY_DEPENDENCYFLAGS
	bool bPreDependencyFormat = PackageFileSummary.GetFileVersionUE() < VER_UE4_ASSETREGISTRY_DEPENDENCYFLAGS;// || !!(PackageFileSummary.PackageFlags & PKG_FilterEditorOnly);

	if (bPreDependencyFormat)
	{
		AssetRegistryDependencyDataOffset = INDEX_NONE;
	}
	else
	{
		*this << AssetRegistryDependencyDataOffset;
	}

	// Load the object count
	int32 ObjectCount = 0;
	*this << ObjectCount;
	const int32 MinBytesPerObject = 1;

	// Check invalid object count
	if (this->IsError() || ObjectCount < 0 || PackageFileSize < this->Tell() + ObjectCount * MinBytesPerObject)
	{
		return false;
	}

	// Worlds that were saved before they were marked public do not have asset data so we will synthesize it here to make sure we see all legacy umaps
	// We will also do this for maps saved after they were marked public but no asset data was saved for some reason. A bug caused this to happen for some maps.
	if (bIsMapPackage)
	{
		const bool bLegacyPackage = PackageFileSummary.GetFileVersionUE() < VER_UE4_PUBLIC_WORLDS;
		const bool bNoMapAsset = (ObjectCount == 0);
		if (bLegacyPackage || bNoMapAsset)
		{
			FString AssetName = FPackageName::GetLongPackageAssetName(PackageName);
			AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*AssetName), FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("World")), FAssetDataTagMap(), PackageFileSummary.ChunkIDs, PackageFileSummary.GetPackageFlags()));
		}
	}

	const int32 MinBytesPerTag = 1;
	// UAsset files usually only have one asset, maps and redirectors have multiple
	for(int32 ObjectIdx = 0; ObjectIdx < ObjectCount; ++ObjectIdx)
	{
		FString ObjectPath;
		FString ObjectClassName;
		int32 TagCount = 0;
		*this << ObjectPath;
		*this << ObjectClassName;
		*this << TagCount;

		// check invalid tag count
		if (this->IsError() || TagCount < 0 || PackageFileSize < this->Tell() + TagCount * MinBytesPerTag)
		{
			return false;
		}

		FAssetDataTagMap TagsAndValues;
		TagsAndValues.Reserve(TagCount);

		for(int32 TagIdx = 0; TagIdx < TagCount; ++TagIdx)
		{
			FString Key;
			FString Value;
			*this << Key;
			*this << Value;

			// check invalid tag
			if (this->IsError())
			{
				return false;
			}

			if (!Key.IsEmpty() && !Value.IsEmpty())
			{
				TagsAndValues.Add(FName(*Key), Value);
			}
		}

		// Before world were RF_Public, other non-public assets were added to the asset data table in map packages.
		// Here we simply skip over them
		if (bIsMapPackage && PackageFileSummary.GetFileVersionUE() < VER_UE4_PUBLIC_WORLDS)
		{
			if (ObjectPath != FPackageName::GetLongPackageAssetName(PackageName))
			{
				continue;
			}
		}

		// if we have an object path that starts with the package then this asset is outer-ed to another package
		const bool bFullObjectPath = ObjectPath.StartsWith(TEXT("/"), ESearchCase::CaseSensitive);

		// if we do not have a full object path already, build it
		if (!bFullObjectPath)
		{
			// if we do not have a full object path, ensure that we have a top level object for the package and not a sub object
			if (!ensureMsgf(!ObjectPath.Contains(TEXT("."), ESearchCase::CaseSensitive), TEXT("Cannot make FAssetData for sub object %s in package %s!"), *ObjectPath, *PackageName))
			{
				ECB_LOG(Warning, TEXT("Cannot make FAssetData for sub object %s!"), *ObjectPath);
				continue;
			}
			ObjectPath = PackageName + TEXT(".") + ObjectPath;
		}
		// Previously export couldn't have its outer as an import
		else if (PackageFileSummary.GetFileVersionUE() < VER_UE4_NON_OUTER_PACKAGE_IMPORT)
		{
			ECB_LOG(Warning, TEXT("Package has invalid export %s, resave source package!"), *ObjectPath);
			continue;
		}
		 
		ObjectClassName = UA::AssetRegistry::ReconstructFullClassPath(*this, PackageName, PackageFileSummary,
			ObjectClassName, &ImportMap, &ExportMap);

		// Create a new FAssetData for this asset and update it with the gathered data
		AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*ObjectPath), FTopLevelAssetPath(ObjectClassName), MoveTemp(TagsAndValues), PackageFileSummary.ChunkIDs, PackageFileSummary.GetPackageFlags()));
	}

	return true;
}

bool FExtPackageReader::ReadAssetRegistryData(FExtAssetData& OutAssetData)
{
	if (!StartSerializeSection(PackageFileSummary.AssetRegistryDataOffset))
	{
		return false;
	}

#if ECB_LEGACY
	// Determine the package name and path
	FString PackageName = FPackageName::FilenameToLongPackageName(PackageFilename);
	FString PackagePath = FPackageName::GetLongPackagePath(PackageName);
#endif
	const bool bIsMapPackage = (PackageFileSummary.GetPackageFlags() & PKG_ContainsMap) != 0;

	// Load the object count
	int32 ObjectCount = 0;
	{
		// ? To avoid large patch sizes, we have frozen cooked package format at the format before VER_UE4_ASSETREGISTRY_DEPENDENCYFLAGS
		bool bPreDependencyFormat = PackageFileSummary.GetFileVersionUE() < VER_UE4_ASSETREGISTRY_DEPENDENCYFLAGS;// || !!(PackageFileSummary.PackageFlags & PKG_FilterEditorOnly);

		int64 DependencyDataOffset;
		if (!bPreDependencyFormat)
		{
			*this << DependencyDataOffset;
		}

		// Load the object count
		*this << ObjectCount;
		const int32 MinBytesPerObject = 1;

		// Check invalid object count
		if (this->IsError() || ObjectCount < 0 || PackageFileSize < this->Tell() + ObjectCount * MinBytesPerObject)
		{
			return false;
		}
	}

	OutAssetData.AssetCount = ObjectCount;

#if ECB_TODO // do we need really special treatment of legacy map asset?

	// Worlds that were saved before they were marked public do not have asset data so we will synthesize it here to make sure we see all legacy umaps
	// We will also do this for maps saved after they were marked public but no asset data was saved for some reason. A bug caused this to happen for some maps.
	if (bIsMapPackage)
	{
		const bool bLegacyPackage = PackageFileSummary.GetFileVersionUE4() < VER_UE4_PUBLIC_WORLDS;
		const bool bNoMapAsset = (ObjectCount == 0);
		if (bLegacyPackage || bNoMapAsset)
		{
			FString AssetName = FPackageName::GetLongPackageAssetName(PackageName);
			AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*AssetName), FName(TEXT("World")), FAssetDataTagMap(), PackageFileSummary.ChunkIDs, PackageFileSummary.PackageFlags));
		}
	}
#endif

	const int32 MinBytesPerTag = 1;
	// UAsset files usually only have one asset, maps and redirectors have multiple
	//for (int32 ObjectIdx = 0; ObjectIdx < ObjectCount; ++ObjectIdx)
	if (ObjectCount > 0) // Only care about first
	{
		FString ObjectPath;
		FString ObjectClassName;
		int32 TagCount = 0;
		*this << ObjectPath;
		*this << ObjectClassName;
		*this << TagCount;

		// check invalid tag count
		if (this->IsError() || TagCount < 0 || PackageFileSize < this->Tell() + TagCount * MinBytesPerTag)
		{
			return false;
		}

		ECB_LOG(Display, TEXT("\t\t%s'%s' (%d Tags)"), *ObjectClassName, *ObjectPath, TagCount); // Output : StaticMesh'SM_Test_LOD0' (14 Tags)
		OutAssetData.AssetName = FName(*ObjectPath);
		OutAssetData.AssetClass = FName(*ObjectClassName);

		FAssetDataTagMap TagsAndValues;
		TagsAndValues.Reserve(TagCount);

		for (int32 TagIdx = 0; TagIdx < TagCount; ++TagIdx)
		{
			FString Key;
			FString Value;
			*this << Key;
			*this << Value;

			// check invalid tag
			if (this->IsError())
			{
				return false;
			}

			if (!Key.IsEmpty() && !Value.IsEmpty())
			{
				TagsAndValues.Add(FName(*Key), Value);

				//ECB_LOG(Display, TEXT("\t\t\t\"%s\": \"%s\""), *Key, *Value);
			}
		}
		OutAssetData.TagsAndValues = FAssetDataTagMapSharedView(MoveTemp(TagsAndValues));

#if ECB_TODO

		if (ObjectPath.StartsWith(TEXT("/"), ESearchCase::CaseSensitive))
		{
			// This should never happen, it means that package A has an export with an outer of package B
			ECB_LOG(Warning, TEXT("Package %s has invalid export %s, resave source package!"), *PackageName, *ObjectPath);
			continue;
		}

		if (!ensureMsgf(!ObjectPath.Contains(TEXT("."), ESearchCase::CaseSensitive), TEXT("Cannot make FAssetData for sub object %s!"), *ObjectPath))
		{
			continue;
		}

		FString AssetName = ObjectPath;

		// Before world were RF_Public, other non-public assets were added to the asset data table in map packages.
		// Here we simply skip over them
		if (bIsMapPackage && PackageFileSummary.GetFileVersionUE4() < VER_UE4_PUBLIC_WORLDS)
		{
			if (AssetName != FPackageName::GetLongPackageAssetName(PackageName))
			{
				continue;
			}
		}

		// Create a new FAssetData for this asset and update it with the gathered data
		AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*AssetName), FName(*ObjectClassName), MoveTemp(TagsAndValues), PackageFileSummary.ChunkIDs, PackageFileSummary.PackageFlags));
#endif

	}

	return true;
}

bool FExtPackageReader::SerializeAssetRegistryDependencyData(TBitArray<>& OutImportUsedInGame,
	TBitArray<>& OutSoftPackageUsedInGame,
	TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& OutExtraPackageDependencies)
{
	UE::AssetRegistry::FReadPackageDataDependenciesArgs Args;
	Args.BinaryNameAwareArchive = this;
	Args.AssetRegistryDependencyDataOffset = AssetRegistryDependencyDataOffset;
	Args.NumImports = ImportMap.Num();
	Args.NumSoftPackageReferences = SoftPackageReferenceList.Num();
	Args.PackageVersion = PackageFileSummary.GetFileVersionUE();

	ClearError();
	Loader->ClearError();

	if (!UE::AssetRegistry::ReadPackageDataDependencies(Args))
	{
		ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeAssetRegistryDependencyData", PackageFilename);
		return false;
	}

	OutImportUsedInGame = MoveTemp(Args.ImportUsedInGame);
	OutSoftPackageUsedInGame = MoveTemp(Args.SoftPackageUsedInGame);
	OutExtraPackageDependencies = MoveTemp(Args.ExtraPackageDependencies);
	return true;
}

bool FExtPackageReader::SerializePackageTrailer(FAssetPackageData& PackageData)
{
	if (!StartSerializeSection(PackageFileSummary.PayloadTocOffset))
	{
		PackageData.SetHasVirtualizedPayloads(false);
		return true;
	}

	UE::FPackageTrailer Trailer;
	if (!Trailer.TryLoad(*this))
	{
		// This is not necessarily corrupt; TryLoad will return false if the trailer is empty
		PackageData.SetHasVirtualizedPayloads(false);
		return true;
	}

	PackageData.SetHasVirtualizedPayloads(Trailer.GetNumPayloads(UE::EPayloadStorageType::Virtualized) > 0);
	return true;
}


bool FExtPackageReader::ReadAssetDataFromThumbnailCache(TArray<FAssetData*>& AssetDataList)
{
	if (!StartSerializeSection(PackageFileSummary.ThumbnailTableOffset))
	{
		return false;
	}

	// Determine the package name and path
	FString PackageName = FPackageName::FilenameToLongPackageName(PackageFilename);
	FString PackagePath = FPackageName::GetLongPackagePath(PackageName);

	// Load the thumbnail count
	int32 ObjectCount = 0;
	*this << ObjectCount;

	// Iterate over every thumbnail entry and harvest the objects classnames
	for(int32 ObjectIdx = 0; ObjectIdx < ObjectCount; ++ObjectIdx)
	{
		// Serialize the classname
		FString AssetClassName;
		*this << AssetClassName;

		// Serialize the object path.
		FString ObjectPathWithoutPackageName;
		*this << ObjectPathWithoutPackageName;

		// Serialize the rest of the data to get at the next object
		int32 FileOffset = 0;
		*this << FileOffset;

		FString GroupNames;
		FString AssetName;

		if (!ensureMsgf(!ObjectPathWithoutPackageName.Contains(TEXT("."), ESearchCase::CaseSensitive), TEXT("Cannot make FAssetData for sub object %s!"), *ObjectPathWithoutPackageName))
		{
			continue;
		}

		// Create a new FAssetData for this asset and update it with the gathered data
		AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*ObjectPathWithoutPackageName), FTopLevelAssetPath(AssetClassName), FAssetDataTagMap(), PackageFileSummary.ChunkIDs, PackageFileSummary.GetPackageFlags()));
	}

	return true;
}

void FExtPackageReader::ApplyRelocationToImportMapAndSoftPackageReferenceList(FStringView LoadedPackageName,
	TArray<FName>& InOutSoftPackageReferenceList,
	TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& InOutExtraPackageDependencies)
{
#if WITH_EDITOR
	UE::Package::Relocation::Private::FPackageRelocationContext RelocationArgs;
	if (UE::Package::Relocation::Private::ShouldApplyRelocation(PackageFileSummary, LoadedPackageName, RelocationArgs))
	{
		UE_LOG(LogPackageRelocation, Verbose, TEXT("Detected relocated package (%.*s). The package was saved as (%s)."),
			LoadedPackageName.Len(), LoadedPackageName.GetData(), *PackageFileSummary.PackageName);
		UE::Package::Relocation::Private::ApplyRelocationToObjectImportMap(RelocationArgs, ImportMap);
		UE::Package::Relocation::Private::ApplyRelocationToNameArray(RelocationArgs, InOutSoftPackageReferenceList);
		for (TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>& Pair : InOutExtraPackageDependencies)
		{
			FNameBuilder Package(Pair.Key);
			FNameBuilder RelocatedPackageName;
			if (UE::Package::Relocation::Private::TryRelocateReference(
				RelocationArgs, Package.ToView(), RelocatedPackageName))
			{
				Pair.Key = *RelocatedPackageName;
			}
		}
	}
#endif
}

bool FExtPackageReader::ReadAssetDataFromThumbnailCache(FExtAssetData& OutAssetData)
{
	if (!StartSerializeSection(PackageFileSummary.ThumbnailTableOffset))
	{
		return false;
	}

#if ECB_LEGACY
	// Determine the package name and path
	FString PackageName = FPackageName::FilenameToLongPackageName(PackageFilename);
	FString PackagePath = FPackageName::GetLongPackagePath(PackageName);
#endif

	// Load the thumbnail count
	int32 ObjectCount = 0;
	*this << ObjectCount;

	OutAssetData.ThumbCount = ObjectCount;

	// Iterate over every thumbnail entry and harvest the objects classnames
	//for (int32 ObjectIdx = 0; ObjectIdx < ObjectCount; ++ObjectIdx)
	if (ObjectCount > 0)
	{
		// Serialize the classname
		FString AssetClassName;
		*this << AssetClassName;

		// Serialize the object path.
		FString ObjectPathWithoutPackageName;
		*this << ObjectPathWithoutPackageName;

		// Serialize the rest of the data to get at the next object
		int32 FileOffset = 0;
		*this << FileOffset;

		bool bHaveValidClassName = !AssetClassName.IsEmpty() && AssetClassName != TEXT("???");
		if (OutAssetData.AssetClass == NAME_None && bHaveValidClassName)
		{
			OutAssetData.AssetClass = FName(*AssetClassName);
		}

		const bool bHaveValidAssetName = !ObjectPathWithoutPackageName.IsEmpty();
		if (OutAssetData.AssetName == NAME_None && bHaveValidAssetName)
		{
			OutAssetData.AssetName = FName(*ObjectPathWithoutPackageName);
		}

		if (FileOffset > 0 && FileOffset < PackageFileSize)
		{
			OutAssetData.SetHasThumbnail(true);
		}

#if ECB_LEGACY
		FString GroupNames;
		FString AssetName;

		if (!ensureMsgf(!ObjectPathWithoutPackageName.Contains(TEXT("."), ESearchCase::CaseSensitive), TEXT("Cannot make FAssetData for sub object %s!"), *ObjectPathWithoutPackageName))
		{
			continue;
		}

		// Create a new FAssetData for this asset and update it with the gathered data
		AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), FName(*ObjectPathWithoutPackageName), FName(*AssetClassName), FAssetDataTagMap(), PackageFileSummary.ChunkIDs, PackageFileSummary.PackageFlags));
#endif
	}

	return true;
}

bool FExtPackageReader::ReadThumbnail(FObjectThumbnail& OutThumbnail)
{
	if (PackageFileSummary.ThumbnailTableOffset > 0)
	{
		// Seek the the part of the file where the thumbnail table lives
		Seek(PackageFileSummary.ThumbnailTableOffset);

		// Load the thumbnail count
		int32 ThumbnailCount = 0;
		*this << ThumbnailCount;

		// Load the names and file offsets for the thumbnails in this package
		if (ThumbnailCount > 0)
		{
			FString ObjectClassName;
			*this << ObjectClassName;

			FString ObjectPathWithoutPackageName;
			*this << ObjectPathWithoutPackageName;

			// File offset to image data
			int32 FileOffset = 0;
			*this << FileOffset;

			if (FileOffset > 0)
			{
				Seek(FileOffset);

				// Load the image data
				OutThumbnail.Serialize(*this);

				return true;
			}
		}
	}
	return false;
}

bool FExtPackageReader::ReadAssetRegistryDataIfCookedPackage(TArray<FAssetData*>& AssetDataList, TArray<FString>& CookedPackageNamesWithoutAssetData)
{
	if (!!(GetPackageFlags() & PKG_FilterEditorOnly))
	{
		const FString PackageName = FPackageName::FilenameToLongPackageName(PackageFilename);
		
		bool bFoundAtLeastOneAsset = false;

		// If the packaged is saved with the right version we have the information
		// which of the objects in the export map as the asset.
		// Otherwise we need to store a temp minimal data and then force load the asset
		// to re-generate its registry data
		if (UEVer() >= VER_UE4_COOKED_ASSETS_IN_EDITOR_SUPPORT)
		{
			const FString PackagePath = FPackageName::GetLongPackagePath(PackageName);

			SerializeNameMap();
			SerializeImportMap();
			SerializeExportMap();
			for (FObjectExport& Export : ExportMap)
			{
				if (Export.bIsAsset)
				{
					// We need to get the class name from the import/export maps
					FString ObjectClassName;
					if (Export.ClassIndex.IsNull())
					{
						ObjectClassName = UClass::StaticClass()->GetPathName();
					}
					else if (Export.ClassIndex.IsExport())
					{
						const FObjectExport& ClassExport = ExportMap[Export.ClassIndex.ToExport()];
						ObjectClassName = PackageName;
						ObjectClassName += '.';
						ClassExport.ObjectName.AppendString(ObjectClassName);
					}
					else if (Export.ClassIndex.IsImport())
					{
						const FObjectImport& ClassImport = ImportMap[Export.ClassIndex.ToImport()];
						const FObjectImport& ClassPackageImport = ImportMap[ClassImport.OuterIndex.ToImport()];
						ClassPackageImport.ObjectName.AppendString(ObjectClassName);
						ObjectClassName += '.';
						ClassImport.ObjectName.AppendString(ObjectClassName);
					}

					AssetDataList.Add(new FAssetData(FName(*PackageName), FName(*PackagePath), Export.ObjectName, FTopLevelAssetPath(ObjectClassName), FAssetDataTagMap(), TArray<int32>(), GetPackageFlags()));
					bFoundAtLeastOneAsset = true;
				}
			}
		}
		if (!bFoundAtLeastOneAsset)
		{
			CookedPackageNamesWithoutAssetData.Add(PackageName);
		}
		return true;
	}

	return false;
}

bool FExtPackageReader::ReadDependencyData(FExtAssetData& OutAssetData)
{
	FExtPackageDependencyData DependencyData;
	DependencyData.PackageName = OutAssetData.PackageName;
	ReadDependencyData(DependencyData, EReadOptions::Dependencies);
	{
		ECB_LOG(Display, TEXT("----------DependencyData.PackageDependencies-----------------"));
		int32 Index = 0;
		for (const auto& PackageDependency : DependencyData.PackageDependencies)
		{
			ECB_LOG(Display, TEXT("\t\t%d) %s, \t%d"), Index, *PackageDependency.PackageName.ToString(), PackageDependency.Property);
			Index++;
		}
	}

	// Get HardReferences
	auto& HardDependentPackages = OutAssetData.HardDependentPackages;
	if (DependencyData.PackageDependencies.Num())
	{
		ECB_LOG(Display, TEXT("----------FPackageReader::GetHardReferences-----------------"));
		int32 Index = 0;
		for (const auto& PackageDependency : DependencyData.PackageDependencies)
		{
			if (!!(PackageDependency.Property & UE::AssetRegistry::EDependencyProperty::Hard)) {
				HardDependentPackages.Add(PackageDependency.PackageName);
				ECB_LOG(Display, TEXT("\t\t%d) %s"), Index, *PackageDependency.PackageName.ToString());
				Index++;
			}
		}
	}

	// Get SoftReferences
	auto& SoftDependentPackages = OutAssetData.SoftReferencesList;
	{
		ECB_LOG(Display, TEXT("----------FPackageReader::GetSoftReferences-----------------"));
		int32 SoftIdx = 0;
		for (const FName& SoftPackageName : SoftPackageReferenceList)
		{
			if (HardDependentPackages.Contains(SoftPackageName))
			{
				ECB_LOG(Display, TEXT("\t\t %s found in both Hard and Soft Packge List, skip"), *SoftPackageName.ToString());
			}
			else
			{
				SoftDependentPackages.Add(SoftPackageName);
				ECB_LOG(Display, TEXT("\t\t%d) %s"), SoftIdx, *SoftPackageName.ToString());
				SoftIdx++;
			}
		}
	}
	return true;
}

bool FExtPackageReader::ReadDependencyData(FExtPackageDependencyData& OutDependencyData, EReadOptions Options)
{
	FString PackageNameString;
	if (!TryGetLongPackageName(PackageNameString))
	{
		// Path was possibly unmounted
		return false;
	}

	OutDependencyData.PackageName = FName(*PackageNameString);
	if (!EnumHasAnyFlags(Options, EReadOptions::Default))
	{
		return true;
	}

	if (!SerializeNameMap() || !SerializeImportMap())
	{
		return false;
	}

	if (EnumHasAnyFlags(Options, EReadOptions::PackageData))
	{
		OutDependencyData.bHasPackageData = true;
		FAssetPackageData& PackageData = OutDependencyData.PackageData;
		PackageData.DiskSize = PackageFileSize;
#if WITH_EDITORONLY_DATA
		PackageData.SetPackageSavedHash(PackageFileSummary.GetSavedHash());
#endif
		PackageData.SetCustomVersions(PackageFileSummary.GetCustomVersionContainer().GetAllVersions());
		PackageData.FileVersionUE = PackageFileSummary.GetFileVersionUE();
		PackageData.FileVersionLicenseeUE = PackageFileSummary.GetFileVersionLicenseeUE();
		PackageData.SetIsLicenseeVersion(PackageFileSummary.SavedByEngineVersion.IsLicenseeVersion());
		PackageData.Extension = FPackagePath::ParseExtension(PackageFilename);

		if (!SerializeImportedClasses(ImportMap, PackageData.ImportedClasses))
		{
			return false;
		}
		if (!SerializePackageTrailer(PackageData))
		{
			return false;
		}
	}

	if (EnumHasAnyFlags(Options, EReadOptions::Dependencies))
	{
		OutDependencyData.bHasDependencyData = true;
		if (!SerializeSoftPackageReferenceList())
		{
			return false;
		}
		FLinkerTables SearchableNames;
		if (!SerializeSearchableNamesMap(SearchableNames))
		{
			return false;
		}

		TBitArray<> ImportUsedInGame;
		TBitArray<> SoftPackageUsedInGame;
		TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>> ExtraPackageDependencies;
		if (!SerializeAssetRegistryDependencyData(ImportUsedInGame, SoftPackageUsedInGame, ExtraPackageDependencies))
		{
			return false;
		}

		ApplyRelocationToImportMapAndSoftPackageReferenceList(PackageNameString, SoftPackageReferenceList,
			ExtraPackageDependencies);

		OutDependencyData.LoadDependenciesFromPackageHeader(OutDependencyData.PackageName, ImportMap,
			SoftPackageReferenceList, SearchableNames.SearchableNamesMap, ImportUsedInGame, SoftPackageUsedInGame,
			ExtraPackageDependencies);
	}

	return true;
}

bool FExtPackageReader::SerializeNameMap()
{
	if( PackageFileSummary.NameCount > 0 )
	{
		if (!StartSerializeSection(PackageFileSummary.NameOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeNameMapInvalidNameOffset", PackageFilename);
			return false;
		}

		const int MinSizePerNameEntry = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.NameCount * MinSizePerNameEntry)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeNameMapInvalidNameCount", PackageFilename);
			return false;
		}

		for ( int32 NameMapIdx = 0; NameMapIdx < PackageFileSummary.NameCount; ++NameMapIdx )
		{
			// Read the name entry from the file.
			FNameEntrySerialized NameEntry(ENAME_LinkerConstructor);
			*this << NameEntry;
			if (IsError())
			{
				ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeNameMapInvalidName", PackageFilename);
				return false;
			}
			NameMap.Add(FName(NameEntry));
		}
	}

	return true;
}

bool FExtPackageReader::SerializeImportMap()
{
	if (ImportMap.Num() > 0)
	{
		return true;
	}

	if (PackageFileSummary.ImportCount > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.ImportOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeImportMapInvalidImportOffset", PackageFilename);
			return false;
		}

		const int MinSizePerImport = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.ImportCount * MinSizePerImport)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeImportMapInvalidImportCount", PackageFilename);
			return false;
		}
		ImportMap.Reserve(PackageFileSummary.ImportCount);
		for (int32 ImportMapIdx = 0; ImportMapIdx < PackageFileSummary.ImportCount; ++ImportMapIdx)
		{
			*this << ImportMap.Emplace_GetRef();
			if (IsError())
			{
				ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeImportMapInvalidImport", PackageFilename);
				ImportMap.Reset();
				return false;
			}
		}
	}

	return true;
}

static FName CoreUObjectPackageName(TEXT("/Script/CoreUObject"));
static FName ScriptStructName(TEXT("ScriptStruct"));

bool FExtPackageReader::SerializeImportedClasses(const TArray<FObjectImport>& InImportMap, TArray<FName>& OutClassNames)
{
	OutClassNames.Reset();

	TSet<int32> ClassImportIndices;
	if (PackageFileSummary.ExportCount > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.ExportOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExportOffset", PackageFilename);
			return false;
		}

		const int MinSizePerExport = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.ExportCount * MinSizePerExport)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExportCount", PackageFilename);
			return false;
		}
		FObjectExport ExportBuffer;
		for (int32 ExportMapIdx = 0; ExportMapIdx < PackageFileSummary.ExportCount; ++ExportMapIdx)
		{
			*this << ExportBuffer;
			if (IsError())
			{
				ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExport", PackageFilename);
				return false;
			}
			if (ExportBuffer.ClassIndex.IsImport())
			{
				ClassImportIndices.Add(ExportBuffer.ClassIndex.ToImport());
			}
		}
	}
	// Any imports of types UScriptStruct are an imported struct and need to be added to ImportedClasses
	// This covers e.g. DataTable, which has a RowStruct pointer that it uses in its native serialization to
	// serialize data into its rows
	// TODO: Projects may create their own ScriptStruct subclass, and if they use one of these subclasses
	// as a serialized-external-struct-pointer then we will miss it. In a future implementation we will 
	// change the PackageReader to report all imports, and allow the AssetRegistry to decide which ones
	// are classes based on its class database.
	for (int32 ImportIndex = 0; ImportIndex < InImportMap.Num(); ++ImportIndex)
	{
		const FObjectImport& ObjectImport = InImportMap[ImportIndex];
		if (ObjectImport.ClassPackage == CoreUObjectPackageName && ObjectImport.ClassName == ScriptStructName)
		{
			ClassImportIndices.Add(ImportIndex);
		}
	}

	TArray<FName, TInlineAllocator<5>>  ParentChain;
	FNameBuilder ClassObjectPath;
	for (int32 ClassImportIndex : ClassImportIndices)
	{
		ParentChain.Reset();
		ClassObjectPath.Reset();
		if (!InImportMap.IsValidIndex(ClassImportIndex))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeImportedClassesInvalidClassIndex", PackageFilename);
			return false;
		}
		bool bParentChainComplete = false;
		int32 CurrentParentIndex = ClassImportIndex;
		for (;;)
		{
			const FObjectImport& ObjectImport = InImportMap[CurrentParentIndex];
			ParentChain.Add(ObjectImport.ObjectName);
			if (ObjectImport.OuterIndex.IsImport())
			{
				CurrentParentIndex = ObjectImport.OuterIndex.ToImport();
				if (!InImportMap.IsValidIndex(CurrentParentIndex))
				{
					ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeImportedClassesInvalidImportInParentChain",
						PackageFilename);
					return false;
				}
			}
			else if (ObjectImport.OuterIndex.IsNull())
			{
				bParentChainComplete = true;
				break;
			}
			else
			{
				check(ObjectImport.OuterIndex.IsExport());
				// Ignore classes in an external package but with an object in this package as one of their outers;
				// We do not need to handle that case yet for Import Classes, and we would have to make this
				// loop more complex (searching in both ExportMap and ImportMap) to do so
				break;
			}
		}

		if (bParentChainComplete)
		{
			int32 NumTokens = ParentChain.Num();
			check(NumTokens >= 1);
			const TCHAR Delimiters[] = { '.', SUBOBJECT_DELIMITER_CHAR, '.' };
			int32 DelimiterIndex = 0;
			ParentChain[NumTokens - 1].AppendString(ClassObjectPath);
			for (int32 TokenIndex = NumTokens - 2; TokenIndex >= 0; --TokenIndex)
			{
				ClassObjectPath << Delimiters[DelimiterIndex];
				DelimiterIndex = FMath::Min(DelimiterIndex + 1, static_cast<int32>(UE_ARRAY_COUNT(Delimiters)) - 1);
				ParentChain[TokenIndex].AppendString(ClassObjectPath);
			}
			OutClassNames.Emplace(ClassObjectPath);
		}
	}

	OutClassNames.Sort(FNameLexicalLess());
	return true;
}

bool FExtPackageReader::SerializeExportMap()
{
	if (ExportMap.Num() > 0)
	{
		return true;
	}

	if (PackageFileSummary.ExportCount > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.ExportOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExportOffset", PackageFilename);
			return false;
		}

		const int MinSizePerExport = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.ExportCount * MinSizePerExport)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExportCount", PackageFilename);
			return false;
		}
		ExportMap.Reserve(PackageFileSummary.ExportCount);
		for (int32 ExportMapIdx = 0; ExportMapIdx < PackageFileSummary.ExportCount; ++ExportMapIdx)
		{
			*this << ExportMap.Emplace_GetRef();
			if (IsError())
			{
				ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeExportMapInvalidExport", PackageFilename);
				ExportMap.Reset();
				return false;
			}
		}
	}

	return true;
}
/*
bool FExtPackageReader::SerializeSoftPackageReferenceList(TArray<FName>& OutSoftPackageReferenceList)
{
	if (UEVer() >= VER_UE4_ADD_STRING_ASSET_REFERENCES_MAP && PackageFileSummary.SoftPackageReferencesOffset > 0 && PackageFileSummary.SoftPackageReferencesCount > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.SoftPackageReferencesOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencesOffset", PackageFilename);
			return false;
		}

		const int MinSizePerSoftPackageReference = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.SoftPackageReferencesCount * MinSizePerSoftPackageReference)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencesCount", PackageFilename);
			return false;
		}
		if (UEVer() < VER_UE4_ADDED_SOFT_OBJECT_PATH)
		{
			for (int32 ReferenceIdx = 0; ReferenceIdx < PackageFileSummary.SoftPackageReferencesCount; ++ReferenceIdx)
			{
				FString PackageName;
				*this << PackageName;
				if (IsError())
				{
					ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencePreSoftObjectPath", PackageFilename);
					return false;
				}

				if (UEVer() < VER_UE4_KEEP_ONLY_PACKAGE_NAMES_IN_STRING_ASSET_REFERENCES_MAP)
				{
					PackageName = FPackageName::GetNormalizedObjectPath(PackageName);
					if (!PackageName.IsEmpty())
					{
						PackageName = FPackageName::ObjectPathToPackageName(PackageName);
					}
				}

				OutSoftPackageReferenceList.Add(FName(*PackageName));
			}
		}
		else
		{
			for (int32 ReferenceIdx = 0; ReferenceIdx < PackageFileSummary.SoftPackageReferencesCount; ++ReferenceIdx)
			{
				FName PackageName;
				*this << PackageName;
				if (IsError())
				{
					ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReference", PackageFilename);
					return false;
				}

				OutSoftPackageReferenceList.Add(PackageName);
			}
		}
	}

	return true;
}
*/
bool FExtPackageReader::SerializeSoftPackageReferenceList()
{
	if (SoftPackageReferenceList.Num() > 0)
	{
		return true;
	}

	if (UEVer() >= VER_UE4_ADD_STRING_ASSET_REFERENCES_MAP && PackageFileSummary.SoftPackageReferencesOffset > 0 && PackageFileSummary.SoftPackageReferencesCount > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.SoftPackageReferencesOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencesOffset", PackageFilename);
			return false;
		}

		const int MinSizePerSoftPackageReference = 1;
		if (PackageFileSize < Tell() + PackageFileSummary.SoftPackageReferencesCount * MinSizePerSoftPackageReference)
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencesCount", PackageFilename);
			return false;
		}

		SoftPackageReferenceList.Reserve(PackageFileSummary.SoftPackageReferencesCount);
		if (UEVer() < VER_UE4_ADDED_SOFT_OBJECT_PATH)
		{
			for (int32 ReferenceIdx = 0; ReferenceIdx < PackageFileSummary.SoftPackageReferencesCount; ++ReferenceIdx)
			{
				FString PackageName;
				*this << PackageName;
				if (IsError())
				{
					ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReferencePreSoftObjectPath", PackageFilename);
					SoftPackageReferenceList.Reset();
					return false;
				}

				if (UEVer() < VER_UE4_KEEP_ONLY_PACKAGE_NAMES_IN_STRING_ASSET_REFERENCES_MAP)
				{
					PackageName = FPackageName::GetNormalizedObjectPath(PackageName);
					if (!PackageName.IsEmpty())
					{
						PackageName = FPackageName::ObjectPathToPackageName(PackageName);
					}
				}

				SoftPackageReferenceList.Add(FName(*PackageName));
			}
		}
		else
		{
			for (int32 ReferenceIdx = 0; ReferenceIdx < PackageFileSummary.SoftPackageReferencesCount; ++ReferenceIdx)
			{
				FName PackageName;
				*this << PackageName;
				if (IsError())
				{
					ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSoftPackageReferenceListInvalidReference", PackageFilename);
					SoftPackageReferenceList.Reset();
					return false;
				}

				SoftPackageReferenceList.Add(PackageName);
			}
		}
	}

	return true;
}
/*
bool FExtPackageReader::SerializeSearchableNamesMap(FExtPackageDependencyData& OutDependencyData)
{
	if (UEVer() >= VER_UE4_ADDED_SEARCHABLE_NAMES && PackageFileSummary.SearchableNamesOffset > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.SearchableNamesOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSearchableNamesMapInvalidOffset", PackageFilename);
			return false;
		}

		OutDependencyData.SerializeSearchableNamesMap(*this);
		if (IsError())
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSearchableNamesMapInvalidSearchableNamesMap", PackageFilename);
			return false;
		}
	}

	return true;
}*/

bool FExtPackageReader::SerializeSearchableNamesMap(FLinkerTables& OutSearchableNames)
{
	if (UEVer() >= VER_UE4_ADDED_SEARCHABLE_NAMES && PackageFileSummary.SearchableNamesOffset > 0)
	{
		if (!StartSerializeSection(PackageFileSummary.SearchableNamesOffset))
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSearchableNamesMapInvalidOffset", PackageFilename);
			return false;
		}

		OutSearchableNames.SerializeSearchableNamesMap(*this);
		if (IsError())
		{
			ECB_PACKAGEREADER_CORRUPTPACKAGE_WARNING("SerializeSearchableNamesMapInvalidSearchableNamesMap", PackageFilename);
			return false;
		}
	}

	return true;
}

void FExtPackageReader::Serialize( void* V, int64 Length )
{
	check(Loader);
	Loader->Serialize( V, Length );
}

bool FExtPackageReader::Precache( int64 PrecacheOffset, int64 PrecacheSize )
{
	check(Loader);
	return Loader->Precache( PrecacheOffset, PrecacheSize );
}

void FExtPackageReader::Seek( int64 InPos )
{
	check(Loader);
	Loader->Seek( InPos );
}

int64 FExtPackageReader::Tell()
{
	check(Loader);
	return Loader->Tell();
}

int64 FExtPackageReader::TotalSize()
{
	check(Loader);
	return Loader->TotalSize();
}

uint32 FExtPackageReader::GetPackageFlags() const
{
	return PackageFileSummary.GetPackageFlags();
}

const FPackageFileSummary& FExtPackageReader::GetPackageFileSummary() const
{
	return PackageFileSummary;
}

int32 FExtPackageReader::GetSoftPackageReferencesCount() const
{
	if (UEVer() >= VER_UE4_ADD_STRING_ASSET_REFERENCES_MAP && PackageFileSummary.SoftPackageReferencesOffset > 0 && PackageFileSummary.SoftPackageReferencesCount > 0)
	{
		return PackageFileSummary.SoftPackageReferencesCount;
	}
	return 0;
}

FArchive& FExtPackageReader::operator<<( FName& Name )
{
	check(Loader);

	int32 NameIndex;
	FArchive& Ar = *this;
	Ar << NameIndex;

	if( !NameMap.IsValidIndex(NameIndex) )
	{
		ECB_LOG(Fatal, TEXT("Bad name index %i/%i"), NameIndex, NameMap.Num() );
	}

	// if the name wasn't loaded (because it wasn't valid in this context)
	if (NameMap[NameIndex] == NAME_None)
	{
		int32 TempNumber;
		Ar << TempNumber;
		Name = NAME_None;
	}
	else
	{
		int32 Number;
		Ar << Number;
		// simply create the name from the NameMap's name and the serialized instance number
		Name = FName(NameMap[NameIndex], Number);
	}

	return *this;
}

void FExtPackageReader::ConvertLinkerTableToPaths(FName InPackageName, TArray<FObjectExport>& InExportMap, TArray<FObjectImport>& InImportMap,
	TArray<FSoftObjectPath>& OutExports, TArray<FSoftObjectPath>& OutImports)
{
	TMap<FPackageIndex, FSoftObjectPath> ObjectForIndex;
	TFunction<FSoftObjectPath& (FPackageIndex Index)> GetSoftObjectPath;
	FSoftObjectPath EmptySoftObjectPath;
	int32 Counter = 0;
	int32 NumExports = InExportMap.Num();
	int32 NumImports = InImportMap.Num();
	int32 NumObjects = NumExports + NumImports;

	ObjectForIndex.Reserve(NumObjects);
	GetSoftObjectPath = [&InImportMap, &InExportMap, &ObjectForIndex, &GetSoftObjectPath, &EmptySoftObjectPath,
		&Counter, NumObjects, InPackageName]
		(FPackageIndex Index) -> FSoftObjectPath&
		{
			if (++Counter > (NumObjects + 1) * 2)
			{
				// Recursive overflow should be impossible because every call fills in a new element of the table
				check(false);
			}
			ON_SCOPE_EXIT
			{
				--Counter;
			};
			if (Index.IsNull())
			{
				return EmptySoftObjectPath;
			}
			FSoftObjectPath* Existing = ObjectForIndex.Find(Index);
			if (Existing)
			{
				return *Existing;
			}

			FPackageIndex ParentIndex;
			FName ObjectName;
			if (Index.IsExport())
			{
				int32 ExportIndex = Index.ToExport();
				if (ExportIndex < InExportMap.Num())
				{
					FObjectExport& Export = InExportMap[ExportIndex];
					ParentIndex = Export.OuterIndex;
					ObjectName = Export.ObjectName;
				}
			}
			else
			{
				int32 ImportIndex = Index.ToImport();
				if (ImportIndex < InImportMap.Num())
				{
					FObjectImport& Import = InImportMap[ImportIndex];
					ParentIndex = Import.OuterIndex;
					ObjectName = Import.ObjectName;
				}
			}
			FSoftObjectPath Result;
			if (!ObjectName.IsNone())
			{
				FSoftObjectPath& ParentPath = GetSoftObjectPath(ParentIndex);
				if (ParentPath.IsNull())
				{
					if (Index.IsExport())
					{
						Result = FSoftObjectPath::ConstructFromAssetPath(FTopLevelAssetPath(InPackageName, ObjectName));
					}
					else
					{
						Result = FSoftObjectPath::ConstructFromAssetPath(FTopLevelAssetPath(ObjectName, NAME_None));
					}
				}
				else if (ParentPath.GetAssetFName().IsNone())
				{
					Result = FSoftObjectPath::ConstructFromAssetPath(FTopLevelAssetPath(ParentPath.GetLongPackageFName(), ObjectName));
				}
				else if (ParentPath.GetSubPathString().IsEmpty())
				{
					Result = FSoftObjectPath::ConstructFromAssetPathAndSubpath(
						FTopLevelAssetPath(ParentPath.GetLongPackageFName(), ParentPath.GetAssetFName()),
						ObjectName.ToString());
				}
				else
				{
					Result = FSoftObjectPath::ConstructFromAssetPathAndSubpath(
						FTopLevelAssetPath(ParentPath.GetLongPackageFName(), ParentPath.GetAssetFName()),
						ParentPath.GetSubPathString() + TEXT(".") + ObjectName.ToString());
				}
			}

			// Note we have to look up the Element again in ObjectForIndex. We can not cache a FindOrAdd Result for Index
			// because we have potentially modified ObjectForIndex by calling GetSoftObjectPath(ParentIndex).
			return ObjectForIndex.Add(Index, Result);
		};
		OutExports.Reset(NumExports);
		for (int32 ExportIndex = 0; ExportIndex < NumExports; ++ExportIndex)
		{
			OutExports.Add(GetSoftObjectPath(FPackageIndex::FromExport(ExportIndex)));
		}
		OutImports.Reset(NumImports);
		for (int32 ImportIndex = 0; ImportIndex < NumImports; ++ImportIndex)
		{
			OutImports.Add(GetSoftObjectPath(FPackageIndex::FromImport(ImportIndex)));
		}
}

//----------------------------------------------------------------------------------------------

FName FExtPackageDependencyData::GetImportPackageName(TConstArrayView<FObjectImport> ImportMap, int32 ImportIndex)
{
	for (int32 NumCycles = 0; NumCycles < ImportMap.Num(); ++NumCycles)
	{
		if (!ImportMap.IsValidIndex(ImportIndex))
		{
			return NAME_None;
		}
		const FObjectImport& Resource = ImportMap[ImportIndex];
		// If the import has a package name set, then that's the import package name,
		if (Resource.HasPackageName())
		{
			return Resource.GetPackageName();
		}
		// If our outer is null, then we have a package
		else if (Resource.OuterIndex.IsNull())
		{
			return Resource.ObjectName;
		}
		if (!Resource.OuterIndex.IsImport())
		{
			return NAME_None;
		}
		ImportIndex = Resource.OuterIndex.ToImport();
	}
	return NAME_None;
}

struct FExtSortPackageDependency
{
	FORCEINLINE bool operator()(const FExtPackageDependencyData::FPackageDependency& A, const FExtPackageDependencyData::FPackageDependency& B) const
	{
		if (int32 Comparison = A.PackageName.CompareIndexes(B.PackageName))
		{
			return Comparison < 0;
		}
		return static_cast<uint8>(A.Property) < static_cast<uint8>(B.Property);
	}
};

void FExtPackageDependencyData::LoadDependenciesFromPackageHeader(FName SourcePackageName, TConstArrayView<FObjectImport> ImportMap,
	TArray<FName>& SoftPackageReferenceList, TMap<FPackageIndex, TArray<FName>>& SearchableNames,
	TBitArray<>& ImportUsedInGame, TBitArray<>& SoftPackageUsedInGame,
	TArray<TPair<FName, UE::AssetRegistry::EExtraDependencyFlags>>& ExtraPackageDependencies)
{
	using namespace UE::AssetRegistry;

	FStringView ExternalActorFolder(FPackagePath::GetExternalActorsFolderName());
	TStringBuilder<FName::StringBufferSize> SourceStr(InPlace, SourcePackageName);
	FStringView ExternalActorWorldRelPath;
	if (int32 FolderIndex = UE::String::FindFirst(SourceStr, ExternalActorFolder, ESearchCase::IgnoreCase);
		FolderIndex != INDEX_NONE)
	{
		ExternalActorWorldRelPath = SourceStr.ToView().RightChop(FolderIndex + ExternalActorFolder.Len());
	}
	auto IsWorldOfExternalActor = [ExternalActorWorldRelPath](FName DependencyPackageName)
		{
			TStringBuilder<256> TargetStr(InPlace, DependencyPackageName);
			FStringView TargetMountPoint = FPathViews::GetMountPointNameFromPath(TargetStr);
			FStringView TargetRelativePath = FStringView(TargetStr).RightChop(TargetMountPoint.Len() + 1);
			return (INDEX_NONE !=
				UE::String::FindFirst(ExternalActorWorldRelPath, TargetRelativePath, ESearchCase::IgnoreCase));
		};

	PackageDependencies.Reset(ImportMap.Num() + SoftPackageReferenceList.Num());
	check(ImportMap.Num() == ImportUsedInGame.Num());
	for (int32 ImportIdx = 0; ImportIdx < ImportMap.Num(); ++ImportIdx)
	{
		FName DependencyPackageName = GetImportPackageName(ImportMap, ImportIdx);
		EDependencyProperty DependencyProperty = EDependencyProperty::Hard;
		bool bUsedInGame = ImportUsedInGame[ImportIdx];

		if (!ExternalActorWorldRelPath.IsEmpty())
		{
			bUsedInGame &= !IsWorldOfExternalActor(DependencyPackageName);
		}

		DependencyProperty |= bUsedInGame ? EDependencyProperty::Game : EDependencyProperty::None;
		PackageDependencies.Add({ DependencyPackageName, DependencyProperty });
	}

	// Sort and make unique to reduce data saved and processed
	PackageDependencies.Sort(FExtSortPackageDependency());

	int UniqueNum = Algo::Unique(PackageDependencies);
	PackageDependencies.SetNum(UniqueNum, EAllowShrinking::No);

	check(SoftPackageReferenceList.Num() == SoftPackageUsedInGame.Num());
	for (int32 SoftPackageIdx = 0; SoftPackageIdx < SoftPackageReferenceList.Num(); ++SoftPackageIdx)
	{
		FName DependencyPackageName = SoftPackageReferenceList[SoftPackageIdx];
		FAssetIdentifier AssetId(DependencyPackageName);
		EDependencyProperty DependencyProperty = EDependencyProperty::None;

		bool bUsedInGame = SoftPackageUsedInGame[SoftPackageIdx];
		if (!ExternalActorWorldRelPath.IsEmpty())
		{
			bUsedInGame &= !IsWorldOfExternalActor(DependencyPackageName);
		}

		DependencyProperty |= (bUsedInGame ? EDependencyProperty::Game : EDependencyProperty::None);

		// Don't need to remove duplicates here because SavePackage only writes unique elements into SoftPackageReferenceList
		PackageDependencies.Add({ DependencyPackageName, DependencyProperty });
	}

	for (const TPair<FName, EExtraDependencyFlags>& Pair : ExtraPackageDependencies)
	{
		FName DependencyPackageName = Pair.Key;
		EDependencyProperty DependencyProperty = EDependencyProperty::None;
		DependencyProperty |= EnumHasAnyFlags(Pair.Value, EExtraDependencyFlags::Build)
			? EDependencyProperty::Build : EDependencyProperty::None;

		if (!ExternalActorWorldRelPath.IsEmpty())
		{
			if (IsWorldOfExternalActor(DependencyPackageName))
			{
				continue;
			}
		}

		// Don't need to remove duplicates here because SavePackage only writes unique elements into PackageBuildDependencies
		PackageDependencies.Add({ DependencyPackageName, DependencyProperty });
	}

	SearchableNameDependencies.Reset(SearchableNames.Num());
	for (const TPair<FPackageIndex, TArray<FName>>& SearchableNameList : SearchableNames)
	{
		FName ObjectName;
		FName DependencyPackageName;

		// Find object and package name from linker
		FPackageIndex LinkerIndex = SearchableNameList.Key;
		if (LinkerIndex.IsExport())
		{
			// Package name has to be this package, take a guess at object name
			DependencyPackageName = SourcePackageName;
			ObjectName = FName(*FPackageName::GetLongPackageAssetName(DependencyPackageName.ToString()));
		}
		else if (LinkerIndex.IsImport())
		{
			int32 ImportIndex = LinkerIndex.ToImport();
			if (!ImportMap.IsValidIndex(ImportIndex))
			{
				continue;
			}
			const FObjectImport& Resource = ImportMap[ImportIndex];
			FPackageIndex OuterLinkerIndex = Resource.OuterIndex;
			if (!OuterLinkerIndex.IsNull())
			{
				ObjectName = Resource.ObjectName;
			}
			DependencyPackageName = GetImportPackageName(ImportMap, ImportIndex);
			if (DependencyPackageName.IsNone())
			{
				continue;
			}
		}
		else
		{
			continue;
		}

		FSearchableNamesDependency& Dependency = SearchableNameDependencies.Emplace_GetRef();
		Dependency.PackageName = DependencyPackageName;
		Dependency.ObjectName = ObjectName;
		Dependency.ValueNames = SearchableNameList.Value;
	}
}
