#include "CrowdProjectMigrator.h"

DEFINE_LOG_CATEGORY_STATIC(LogCrowdProjectMigrate, Warning, All);

#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFilemanager.h"
#include "UObject/LinkerLoad.h"
#include "UObject/ObjectResource.h"
#include "UObject/Package.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectThreadContext.h"
#include "UObject/Linker.h"
#include "Misc/PackagePath.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/AssetIdentifier.h"
#include "Misc/ScopedSlowTask.h"
#include "Misc/MessageDialog.h"
#include "Widgets/SWindow.h"
#include "Framework/Application/SlateApplication.h"
#include "CrowdMigrationDialog.h"
#include "PackageTools.h"
#include "ContentBrowserModule.h"
#include "IContentBrowserSingleton.h"

#define LOCTEXT_NAMESPACE "CrowdProjectMigrator"

// 把所有详细日志通过 LogTemp 也输出一遍，确保用户即使没有把
// "LogCrowdProjectMigrate" 类别加到 Output Log 过滤器也能看到。
#define CPM_LOG(Format, ...) \
	do { \
		UE_LOG(LogCrowdProjectMigrate, Warning, Format, ##__VA_ARGS__); \
		UE_LOG(LogTemp,            Warning, Format, ##__VA_ARGS__); \
	} while (0)

// 包名（/Game/ge/hrw/X） -> 源工程磁盘文件（优先 .uasset，否则 .umap）。
FString FCrowdProjectMigrator::PackageNameToFile(const FString& SourceContentDir, const FString& PackageName)
{
	FString Rel = PackageName;
	Rel.RemoveFromStart(TEXT("/Game/"));
	Rel.ReplaceInline(TEXT("/"), TEXT("\\"));

	FString AsUasset = FPaths::Combine(SourceContentDir, Rel + TEXT(".uasset"));
	if (FPaths::FileExists(AsUasset))
	{
		return AsUasset;
	}
	FString AsUmap = FPaths::Combine(SourceContentDir, Rel + TEXT(".umap"));
	if (FPaths::FileExists(AsUmap))
	{
		return AsUmap;
	}
	return AsUasset;
}

// 从给定文件夹向上查找 .uproject，解析源工程根目录 / Content 目录 / 选中文件夹相对 Content 的路径。
bool FCrowdProjectMigrator::ResolveSourceProject(const FString& InFolder, FString& OutProjectRoot, FString& OutContentDir, FString& OutSelectedRel)
{
	FString Path = InFolder;
	FPaths::NormalizeDirectoryName(Path);

	FString Cur = Path;
	bool bFound = false;
	while (!Cur.IsEmpty())
	{
		TArray<FString> Up;
		IFileManager::Get().FindFiles(Up, *(Cur / TEXT("*.uproject")), true, false);
		if (Up.Num() > 0)
		{
			OutProjectRoot = Cur;
			bFound = true;
			break;
		}
		FString Parent = FPaths::GetPath(Cur);
		if (Parent == Cur)
		{
			break;
		}
		Cur = Parent;
	}
	if (!bFound)
	{
		return false;
	}

	OutContentDir = OutProjectRoot / TEXT("Content");

	FString NormContent = OutContentDir;
	FPaths::NormalizeDirectoryName(NormContent);
	if (!Path.StartsWith(NormContent))
	{
		return false; // 选中路径不在 Content 目录下
	}

	OutSelectedRel = Path.RightChop(NormContent.Len());
	while (OutSelectedRel.StartsWith(TEXT("/")) || OutSelectedRel.StartsWith(TEXT("\\")))
	{
		OutSelectedRel.RightChopInline(1);
	}
	FPaths::NormalizeFilename(OutSelectedRel);
	return true;
}

// 枚举选中文件夹下的所有 .uasset / .umap，转为 /Game/ 包名（去扩展名）。
void FCrowdProjectMigrator::EnumerateSelectedPackages(const FString& ContentDir, const FString& SelectedRel, TArray<FString>& OutPackages)
{
	FString Root = FPaths::Combine(ContentDir, SelectedRel);

	TArray<FString> Files;
	IFileManager::Get().FindFilesRecursive(Files, *Root, TEXT("*.uasset"), true, false);

	TArray<FString> Maps;
	IFileManager::Get().FindFilesRecursive(Maps, *Root, TEXT("*.umap"), true, false);
	Files.Append(Maps);

	CPM_LOG(TEXT("EnumerateSelectedPackages: Root='%s' -> %d files"), *Root, Files.Num());

	for (const FString& F : Files)
	{
		// 手动剥离 ContentDir 前缀（不用 MakePathRelativeTo，后者在含 "Content" 字符串的路径上会出错）。
		FString Rel = F;
		if (Rel.StartsWith(ContentDir))
		{
			Rel.RightChopInline(ContentDir.Len());
		}
		while (Rel.StartsWith(TEXT("/")) || Rel.StartsWith(TEXT("\\")))
		{
			Rel.RightChopInline(1);
		}
		FPaths::NormalizeFilename(Rel);
		Rel.ReplaceInline(TEXT("\\"), TEXT("/"));

		FString Pkg = TEXT("/Game/") + Rel;
		if (Pkg.EndsWith(TEXT(".uasset")))
		{
			Pkg.LeftChopInline(7);
		}
		else if (Pkg.EndsWith(TEXT(".umap")))
		{
			Pkg.LeftChopInline(5);
		}
		OutPackages.AddUnique(Pkg);
	}
}

// 在源工程的 Saved / Intermediate 中查找最新的 AssetRegistry.bin 并加载。
TSharedPtr<FAssetRegistryState> FCrowdProjectMigrator::LoadSourceRegistry(const FString& ProjectRoot)
{
	TArray<FString> Found;
	IFileManager::Get().FindFilesRecursive(Found, *(ProjectRoot / TEXT("Saved")), TEXT("AssetRegistry.bin"), true, false);

	TArray<FString> Found2;
	IFileManager::Get().FindFilesRecursive(Found2, *(ProjectRoot / TEXT("Intermediate")), TEXT("AssetRegistry.bin"), true, false);
	Found.Append(Found2);

	CPM_LOG(TEXT("LoadSourceRegistry: searching under %s, found %d AssetRegistry.bin"), *ProjectRoot, Found.Num());

	if (Found.Num() == 0)
	{
		return nullptr;
	}

	// 选最新的那份。
	Found.Sort([](const FString& A, const FString& B)
	{
		return IFileManager::Get().GetTimeStamp(*A) > IFileManager::Get().GetTimeStamp(*B);
	});

	auto State = MakeShared<FAssetRegistryState>();
	if (FAssetRegistryState::LoadFromDisk(*Found[0], FAssetRegistryLoadOptions(), *State))
	{
		return State;
	}
	return nullptr;
}

// 兜底：读取 uasset 头文件的 Import 表，拿到对 /Game/ 下其它包的硬依赖。
void FCrowdProjectMigrator::GatherPackageHardDependencies(const FString& SourceContentDir, const FString& PackageName, TArray<FString>& OutDeps)
{
	FString File = PackageNameToFile(SourceContentDir, PackageName);
	UE_LOG(LogCrowdProjectMigrate, Verbose, TEXT("GatherHardDeps: pkg=%s -> file=%s (exists=%d)"), *PackageName, *File, FPaths::FileExists(File));
	if (!FPaths::FileExists(File))
	{
		return;
	}

	UPackage* TmpPackage = NewObject<UPackage>(nullptr, *FPaths::GetBaseFilename(File), RF_Transient);
	FUObjectSerializeContext* LoadContext = FUObjectThreadContext::Get().GetSerializeContext();
	FPackagePath PackagePath = FPackagePath::FromLocalPath(File);

	FLinkerLoad* Linker = FLinkerLoad::CreateLinker(LoadContext, TmpPackage, PackagePath, LOAD_NoVerify, nullptr, nullptr);
	UE_LOG(LogCrowdProjectMigrate, Verbose, TEXT("GatherHardDeps: CreateLinker result=%p importMapSize=%d"), (void*)Linker, Linker ? Linker->ImportMap.Num() : 0);
	if (Linker)
	{
		// CreateLinker 内部已经把 Linker 挂到 TmpPackage 上（见 FLinkerLoad::FinalizeCreation）。
		for (const FObjectImport& Imp : Linker->ImportMap)
		{
#if WITH_EDITORONLY_DATA
			FString DepName = Imp.PackageName.ToString();
#else
			FString DepName;
#endif
			if (!DepName.IsEmpty() && DepName.StartsWith(TEXT("/Game/")) && DepName != PackageName)
			{
				OutDeps.AddUnique(DepName);
			}
		}
		// 由 FLinkerManager 正确接管并释放 Linker（直接 delete 会触发断言）。
		ResetLoaders(TmpPackage);
	}
	TmpPackage->MarkAsGarbage();
}

// 从选中包出发，BFS 展开 /Game/ 依赖闭包。
void FCrowdProjectMigrator::ExpandDependencies(const FString& SourceContentDir, const TArray<FString>& SelectedPackages, TSet<FString>& OutClosure, TSharedPtr<FAssetRegistryState> Registry)
{
	TQueue<FString> Queue;
	for (const FString& P : SelectedPackages)
	{
		Queue.Enqueue(P);
		OutClosure.Add(P);
	}

	FString Cur;
	while (Queue.Dequeue(Cur))
	{
		TArray<FString> Deps;
		if (Registry.IsValid())
		{
			TArray<FAssetIdentifier> Ids;
			Registry->GetDependencies(FAssetIdentifier(FName(*Cur)), Ids, UE::AssetRegistry::EDependencyCategory::All);
			for (const FAssetIdentifier& Id : Ids)
			{
				if (Id.PackageName.IsNone())
				{
					continue; // 跳过搜索名等非包依赖
				}
				FString Dep = Id.PackageName.ToString();
				if (Dep.StartsWith(TEXT("/Game/")))
				{
					Deps.AddUnique(Dep);
				}
			}
		}
		else
		{
			GatherPackageHardDependencies(SourceContentDir, Cur, Deps);
		}

		for (const FString& D : Deps)
		{
			if (!OutClosure.Contains(D))
			{
				OutClosure.Add(D);
				Queue.Enqueue(D);
			}
		}
	}
}

// 根据闭包构建资产清单，并标记与当前工程的冲突。
void FCrowdProjectMigrator::BuildAssetList(const FString& SourceContentDir, const FString& DestContentDir, const TSet<FString>& Closure, TArray<FCrowdMigrationAsset>& OutAssets)
{
	CPM_LOG(TEXT("BuildAssetList: SourceContentDir='%s', closure size=%d"), *SourceContentDir, Closure.Num());

	int32 Missed = 0;
	for (const FString& Pkg : Closure)
	{
		FCrowdMigrationAsset A;
		A.PackageName = Pkg;

		FString Rel = Pkg;
		Rel.RemoveFromStart(TEXT("/Game/"));
		Rel.ReplaceInline(TEXT("/"), TEXT("\\"));
		A.RelativePath = Rel;

		FString AsUasset = FPaths::Combine(SourceContentDir, Rel + TEXT(".uasset"));
		FString AsUmap = FPaths::Combine(SourceContentDir, Rel + TEXT(".umap"));
		if (FPaths::FileExists(AsUmap))
		{
			A.SourceFile = AsUmap;
			A.bIsMap = true;
		}
		else if (FPaths::FileExists(AsUasset))
		{
			A.SourceFile = AsUasset;
			A.bIsMap = false;
		}
		else
		{
			// 只对前 5 个缺失打详细日志，避免淹没 Output Log。
			if (Missed < 5)
			{
				CPM_LOG(TEXT("  [Missed %d] Pkg='%s' -> tried: '%s' / '%s'"),
					Missed, *Pkg, *AsUasset, *AsUmap);
			}
			Missed++;
			continue; // 源文件缺失（可能是引擎/插件引用），跳过
		}

		A.DestFile = FPaths::Combine(DestContentDir, Rel + (A.bIsMap ? TEXT(".umap") : TEXT(".uasset")));
		A.bConflict = FPaths::FileExists(A.DestFile);
		A.bOverwrite = false;

		OutAssets.Add(MoveTemp(A));
	}

	CPM_LOG(TEXT("BuildAssetList: built %d assets, %d missed (no .uasset/.umap on disk)"),
		OutAssets.Num(), Missed);
}

// 弹出冲突确认对话框。
FCrowdMigrationDialogResult FCrowdProjectMigrator::ShowConflictDialog(TArray<FCrowdMigrationAsset>& Assets)
{
	FCrowdMigrationDialogResult Result;

	TSharedRef<SCrowdMigrationDialog> Dialog = SNew(SCrowdMigrationDialog).Assets(&Assets);

	TSharedRef<SWindow> Window = SNew(SWindow)
		.Title(LOCTEXT("Title", "跨工程迁移 - 冲突确认"))
		.ClientSize(FVector2D(940, 720))
		.SupportsMinimize(false)
		.SupportsMaximize(false)
		[
			Dialog
		];

	Dialog->OwnerWindow = Window;
	FSlateApplication::Get().AddModalWindow(Window, nullptr);

	Result.bConfirmed = Dialog->WasConfirmed();
	Result.bPreviewOnly = Dialog->bPreviewOnly;
	Result.DestinationSubPath = Dialog->DestinationSubPath;
	// 去掉首尾分隔符，避免拼路径时出现双斜杠。
	Result.DestinationSubPath.TrimStartAndEndInline();
	while (Result.DestinationSubPath.StartsWith(TEXT("/")) || Result.DestinationSubPath.StartsWith(TEXT("\\")))
	{
		Result.DestinationSubPath.RightChopInline(1);
	}
	while (Result.DestinationSubPath.EndsWith(TEXT("/")) || Result.DestinationSubPath.EndsWith(TEXT("\\")))
	{
		Result.DestinationSubPath.LeftChopInline(1);
	}
	return Result;
}

// 根据"目标子目录"重算 DestFile 与 bConflict。
void FCrowdProjectMigrator::ApplyDestinationSubPath(TArray<FCrowdMigrationAsset>& Assets, const FString& DestContentDir, const FString& SelectedRel, const FString& SubPath)
{
	if (SubPath.IsEmpty())
	{
		return; // 保持原路径，无需重算
	}

	FString NormSel = SelectedRel;
	FPaths::NormalizeFilename(NormSel); // 统一为正斜杠

	for (FCrowdMigrationAsset& A : Assets)
	{
		// 取源包相对 Content 的内部路径（去掉选中文件夹前缀）。
		FString Inner = A.RelativePath;
		Inner.ReplaceInline(TEXT("\\"), TEXT("/"));
		FPaths::NormalizeFilename(Inner);
		if (Inner.StartsWith(NormSel) && !NormSel.IsEmpty())
		{
			Inner.RightChopInline(NormSel.Len());
			while (Inner.StartsWith(TEXT("/")))
			{
				Inner.RightChopInline(1);
			}
		}

		// DestRel = SubPath / Inner
		FString DestRel = SubPath;
		DestRel.ReplaceInline(TEXT("\\"), TEXT("/"));
		FPaths::NormalizeFilename(DestRel);
		if (!Inner.IsEmpty())
		{
			DestRel = DestRel / Inner;
		}
		FPaths::NormalizeFilename(DestRel);

		A.DestFile = FPaths::Combine(DestContentDir, DestRel + (A.bIsMap ? TEXT(".umap") : TEXT(".uasset")));
		A.bConflict = FPaths::FileExists(A.DestFile);
	}
}

// 按用户选择执行复制，然后刷新目标 AssetRegistry。
void FCrowdProjectMigrator::PerformCopy(const TArray<FCrowdMigrationAsset>& Assets, const FString& DestRoot)
{
	int32 Copied = 0, Skipped = 0, Failed = 0;
	TArray<FString> FailedList;

	FScopedSlowTask Progress((float)Assets.Num(), LOCTEXT("Copying", "正在迁移资产..."));
	Progress.MakeDialog();

	IPlatformFile& PF = FPlatformFileManager::Get().GetPlatformFile();

	// 用于去重：同一个目标包如果被多个 .uasset 引用了（侧车文件、ExternalActors 等），
	// 只对每个包调用一次 ResetLoaders 即可。
	TSet<FString> UnloadedPackages;

	auto TryReleaseFileLock = [&UnloadedPackages](const FString& FilePath)
	{
		FString PackageName;
		if (!FPackageName::TryConvertFilenameToLongPackageName(FilePath, PackageName))
		{
			return;
		}
		if (UnloadedPackages.Contains(PackageName))
		{
			return;
		}
		if (UPackage* Pkg = FindPackage(nullptr, *PackageName))
		{
			// ResetLoaders 释放 linker，也就释放 .uasset 文件的独占句柄。
			// 这会清空内存中的资产数据；如果资产仍被编辑器引用，编辑器会在下次访问时重新加载。
			ResetLoaders(Pkg);
		}
		UnloadedPackages.Add(PackageName);
	};

	for (const FCrowdMigrationAsset& A : Assets)
	{
		Progress.EnterProgressFrame(1);

		// 冲突且用户未选择覆盖 -> 跳过
		if (A.bConflict && !A.bOverwrite)
		{
			Skipped++;
			continue;
		}

		FString DestDir = FPaths::GetPath(A.DestFile);
		IFileManager::Get().MakeDirectory(*DestDir, true);

		// UE 编辑器中已打开的 .uasset 会独占文件句柄；先尝试释放再复制。
		TryReleaseFileLock(A.DestFile);

		if (!PF.CopyFile(*A.DestFile, *A.SourceFile))
		{
			CPM_LOG(TEXT("[Failed] '%s' -> '%s'  (源存在=%d)"),
				*A.SourceFile, *A.DestFile, FPaths::FileExists(A.SourceFile) ? 1 : 0);
			FailedList.Add(A.RelativePath + (A.bIsMap ? TEXT(".umap") : TEXT(".uasset")));
			Failed++;
			continue;
		}
		Copied++;

		// 地图需要额外拷贝侧车文件
		if (A.bIsMap)
		{
			// _BuiltData.uasset
			FString Built = A.SourceFile.LeftChop(5) + TEXT("_BuiltData.uasset");
			if (FPaths::FileExists(Built))
			{
				FString DestBuilt = A.DestFile.LeftChop(5) + TEXT("_BuiltData.uasset");
				TryReleaseFileLock(DestBuilt);
				IFileManager::Get().MakeDirectory(*FPaths::GetPath(DestBuilt), true);
				if (!PF.CopyFile(*DestBuilt, *Built))
				{
					CPM_LOG(TEXT("[Failed sidecar] '%s' -> '%s'"), *Built, *DestBuilt);
				}
			}

			// ExternalActors / ExternalObjects 目录
			FString RelNoExt = A.RelativePath; // 例如 ge/hrw/Level
			for (const FString& Sub : { TEXT("ExternalActors"), TEXT("ExternalObjects") })
			{
				FString SrcSub = FPaths::Combine(FPaths::GetPath(A.SourceFile), Sub, RelNoExt);
				if (FPaths::DirectoryExists(SrcSub))
				{
					TArray<FString> SubFiles;
					IFileManager::Get().FindFilesRecursive(SubFiles, *SrcSub, TEXT("*"), true, false);
					for (const FString& SF : SubFiles)
					{
						FString DestSF = FPaths::Combine(FPaths::GetPath(A.DestFile), Sub, RelNoExt, FPaths::GetCleanFilename(SF));
						TryReleaseFileLock(DestSF);
						IFileManager::Get().MakeDirectory(*FPaths::GetPath(DestSF), true);
						if (!PF.CopyFile(*DestSF, *SF))
						{
							CPM_LOG(TEXT("[Failed ext] '%s' -> '%s'"), *SF, *DestSF);
						}
					}
				}
			}
		}
	}

	// 刷新目标工程的 AssetRegistry，使新资产立即出现在 Content Browser。
	FAssetRegistryModule::GetRegistry().ScanPathsSynchronous(TArray<FString>{ DestRoot }, true);

	// 关键步骤：覆盖成功后，编辑器内存里还留有旧 UPackage 对象。
	// 需要用 Resource 一级的 ReloadPackages 强行关闭打开的编辑器、清空旧对象、从磁盘重新加载。
	{
		TArray<UPackage*> StalePackages;
		for (const FCrowdMigrationAsset& A : Assets)
		{
			if (A.bConflict && !A.bOverwrite)
			{
				continue; // 没被覆盖的，不需要刷新
			}
			FString PackageName;
			if (!FPackageName::TryConvertFilenameToLongPackageName(A.DestFile, PackageName))
			{
				continue;
			}
			if (UPackage* Pkg = FindPackage(nullptr, *PackageName))
			{
				StalePackages.AddUnique(Pkg);
			}
		}
		if (StalePackages.Num() > 0)
		{
			CPM_LOG(TEXT("Reloading %d stale packages via UPackageTools::ReloadPackages..."), StalePackages.Num());
			UPackageTools::ReloadPackages(StalePackages);
		}
	}

	// 导航 Content Browser 到迁移过来的文件夹下。
	// 如果资产太多（>=10个），随机挑一个导航过去。
	{
		TArray<FString> AssetsToSync;
		for (const FCrowdMigrationAsset& A : Assets)
		{
			if (!A.bConflict || A.bOverwrite)
			{
				AssetsToSync.AddUnique(TEXT("/Game/") + A.RelativePath.Replace(TEXT("\\"), TEXT("/")));
			}
		}
		if (AssetsToSync.Num() > 0)
		{
			// 多于 10 个取随机
			TArray<FString> FinalSelection;
			if (AssetsToSync.Num() >= 10)
			{
				FinalSelection.Add(AssetsToSync[FMath::RandRange(0, AssetsToSync.Num() - 1)]);
			}
			else
			{
				FinalSelection = AssetsToSync;
			}

			// 把包名转为 FAssetData
			FAssetRegistryModule& ARM = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
			TArray<FAssetData> AssetDataList;
			for (const FString& PkgName : FinalSelection)
			{
				TArray<FAssetData> OutAssets;
				ARM.Get().GetAssetsByPackageName(FName(*PkgName), OutAssets);
				if (OutAssets.Num() > 0)
				{
					AssetDataList.Add(OutAssets[0]);
				}
			}
			if (AssetDataList.Num() > 0)
			{
				FContentBrowserModule& CB = FModuleManager::LoadModuleChecked<FContentBrowserModule>("ContentBrowser");
				CB.Get().SyncBrowserToAssets(AssetDataList);
			}
		}
	}

	// 组装失败文件列表（最多列 20 个，避免弹窗太高）。
	FString FailedDetail;
	if (FailedList.Num() > 0)
	{
		FailedDetail = TEXT("\n\n失败的文件：\n");
		int32 ShowCount = FMath::Min(20, FailedList.Num());
		for (int32 i = 0; i < ShowCount; i++)
		{
			FailedDetail += TEXT("  - ") + FailedList[i] + TEXT("\n");
		}
		if (FailedList.Num() > ShowCount)
		{
			FailedDetail += FString::Printf(TEXT("  ……还有 %d 个，详见 Output Log（CrowdProjectMigrate）"), FailedList.Num() - ShowCount);
		}
		FailedDetail += TEXT("\n提示：失败通常是因为目标 .uasset 已被 UE 编辑器加载/锁定，可关闭相关资产后重试。");
	}

	// 如果触发了 GC，提示用户：Content Browser 里的资产缩略图/列表会重新加载。
	const bool bDidGC = (Copied > 0);
	FString ReloadNote = bDidGC
		? TEXT("\n\n提示：已强制刷新内存中的旧对象。若蓝图编辑器内仍显示旧内容，关闭对应标签页重新打开即可看到源工程的版本。")
		: TEXT("");

	FMessageDialog::Open(EAppMsgType::Ok, FText::Format(
		LOCTEXT("Result", "迁移完成：新增/覆盖 {0} 个，跳过 {1} 个（冲突未覆盖），失败 {2} 个。\n目标根目录：{3}{4}{5}"),
		FText::AsNumber(Copied),
		FText::AsNumber(Skipped),
		FText::AsNumber(Failed),
		FText::FromString(DestRoot),
		FText::FromString(FailedDetail),
		FText::FromString(ReloadNote)));
}

// 主入口。
void FCrowdProjectMigrator::ExecuteMigration(const FString& SourceFolder, const FString& DestinationSubPath, bool bPreviewOnly)
{
	CPM_LOG(TEXT("=== CrowdProjectMigrate START ==="));
	CPM_LOG(TEXT("SourceFolder: %s"), *SourceFolder);
	CPM_LOG(TEXT("DestinationSubPath: '%s', PreviewOnly: %d"), *DestinationSubPath, (int32)bPreviewOnly);

	FString ProjectRoot, ContentDir, SelectedRel;
	if (!ResolveSourceProject(SourceFolder, ProjectRoot, ContentDir, SelectedRel))
	{
		CPM_LOG(TEXT("ResolveSourceProject FAILED for: %s"), *SourceFolder);
		FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(
			TEXT("无法解析源工程：\n")
			TEXT("  1) 路径向上未找到 .uproject 文件；或\n")
			TEXT("  2) 所选路径不在工程的 Content 目录下。\n\n")
			+ SourceFolder));
		return;
	}

	CPM_LOG(TEXT("Resolve OK | ProjectRoot=%s | ContentDir=%s | SelectedRel=%s"),
		*ProjectRoot, *ContentDir, *SelectedRel);

	// 优先用源工程自己的 AssetRegistry.bin（完整依赖图），失败则走 Import 表兜底。
	TSharedPtr<FAssetRegistryState> Registry = LoadSourceRegistry(ProjectRoot);
	CPM_LOG(TEXT("LoadSourceRegistry: %s"), Registry.IsValid() ? TEXT("OK") : TEXT("FAILED (will use fallback)"));

	TArray<FString> Selected;
	EnumerateSelectedPackages(ContentDir, SelectedRel, Selected);
	CPM_LOG(TEXT("Enumerated %d packages in selected folder"), Selected.Num());
	if (Selected.Num() == 0)
	{
		FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(
			TEXT("所选文件夹下没有找到任何 .uasset / .umap 资产：\n")
			+ FPaths::Combine(ContentDir, SelectedRel)));
		return;
	}

	TSet<FString> Closure;
	ExpandDependencies(ContentDir, Selected, Closure, Registry);
	CPM_LOG(TEXT("Dependency closure size: %d (selected seed: %d)"), Closure.Num(), Selected.Num());

	TArray<FCrowdMigrationAsset> Assets;
	BuildAssetList(ContentDir, FPaths::ProjectContentDir(), Closure, Assets);
	if (Assets.Num() == 0)
	{
		// 之前这里静默返回，用户完全不知道发生了什么——现在补上提示。
		FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(
			TEXT("依赖闭包已计算出，但所有对应文件在磁盘上不存在。\n")
			TEXT("可能原因：\n")
			TEXT("  1) 源工程路径含中文/特殊字符导致文件查找失败；\n")
			TEXT("  2) AssetRegistry.bin 引用了已被删除的资产；\n")
			TEXT("  3) 源路径不在预期位置。\n\n")
			TEXT("请检查 Output Log（类别 CrowdProjectMigrate）获取详细信息。")));
		return;
	}

	// 弹窗：用户选择覆盖项、目标子目录以及是否仅预览。
	CPM_LOG(TEXT("Opening conflict dialog with %d assets..."), Assets.Num());
	FCrowdMigrationDialogResult Result = ShowConflictDialog(Assets);
	CPM_LOG(TEXT("Dialog result: confirmed=%d preview=%d subpath='%s'"),
		(int32)Result.bConfirmed, (int32)Result.bPreviewOnly, *Result.DestinationSubPath);
	if (!Result.bConfirmed)
	{
		CPM_LOG(TEXT("User cancelled migration."));
		return; // 用户取消
	}

	// 应用"目标子目录"重定位（会刷新 DestFile 与冲突标记）。
	const FString EffectiveSubPath = Result.DestinationSubPath.IsEmpty() ? DestinationSubPath : Result.DestinationSubPath;
	ApplyDestinationSubPath(Assets, FPaths::ProjectContentDir(), SelectedRel, EffectiveSubPath);

	// 仅预览：不复制，直接给出依赖汇总。
	if (Result.bPreviewOnly || bPreviewOnly)
	{
		int32 Conflicts = 0;
		for (const FCrowdMigrationAsset& A : Assets)
		{
			if (A.bConflict)
			{
				Conflicts++;
			}
		}
		const FString DestRoot = EffectiveSubPath.IsEmpty()
			? FPaths::Combine(FPaths::ProjectContentDir(), SelectedRel)
			: FPaths::Combine(FPaths::ProjectContentDir(), EffectiveSubPath);
		const FString DestRootAbs = FPaths::ConvertRelativePathToFull(DestRoot);

		FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(
			FString::Printf(
				TEXT("【预览模式】未复制任何文件。\n\n")
				TEXT("将迁移 %d 个资产（含其完整依赖闭包），其中目标已存在、会冲突 %d 个。\n")
				TEXT("目标根目录：%s%s\n\n")
				TEXT("取消预览后再次运行并取消“仅预览”勾选，即可真正复制。"),
				Assets.Num(), Conflicts, *DestRootAbs,
				EffectiveSubPath.IsEmpty() ? TEXT("（保持原路径）") : TEXT("（已重定位到指定子目录）"))));
		return;
	}

	const FString DestRoot = EffectiveSubPath.IsEmpty()
		? FPaths::Combine(FPaths::ProjectContentDir(), SelectedRel)
		: FPaths::Combine(FPaths::ProjectContentDir(), EffectiveSubPath);
	const FString DestRootAbs = FPaths::ConvertRelativePathToFull(DestRoot);
	CPM_LOG(TEXT("Performing copy to: %s"), *DestRootAbs);
	PerformCopy(Assets, DestRootAbs);
	CPM_LOG(TEXT("=== CrowdProjectMigrate END (success) ==="));
}

#undef LOCTEXT_NAMESPACE
