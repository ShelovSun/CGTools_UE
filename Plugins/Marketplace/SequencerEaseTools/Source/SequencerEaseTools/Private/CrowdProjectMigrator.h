#pragma once

#include "CoreMinimal.h"
#include "AssetRegistry/AssetRegistryState.h"

/** 单个待迁移资产的描述。 */
struct FCrowdMigrationAsset
{
	FString PackageName;   // /Game/ge/hrw/Sub/Asset
	FString RelativePath;  // ge/hrw/Sub/Asset（不含扩展名）
	FString SourceFile;    // 源工程中的绝对文件路径
	FString DestFile;      // 当前工程中的绝对目标路径
	bool bIsMap = false;   // 是否为 .umap（需要额外拷贝侧车文件）
	bool bConflict = false;// 目标路径已存在同名文件
	bool bOverwrite = false;// 用户在对话框中的覆盖选择
};

/**
 * 冲突对话框的返回结果：是否确认、目标子目录、是否仅预览。
 * 把"放到指定子目录"和"仅预览不复制"两个增强选项从对话框回传给主流程。
 */
struct FCrowdMigrationDialogResult
{
	bool bConfirmed = false;
	bool bPreviewOnly = false;
	FString DestinationSubPath; // 留空表示保持原 /Game/ 路径；非空则把选中文件夹整体重定位到该子目录
};

/**
 * 核心迁移逻辑：解析未打开的源工程、计算依赖闭包、构建资产清单、
 * 弹出冲突对话框并执行复制。
 */
class FCrowdProjectMigrator
{
public:
	/**
	 * 主入口：解析 -> 计算闭包 -> 弹窗 -> 复制。
	 * @param SourceFolder       源工程里位于 Content 下的某个文件夹绝对路径。
	 * @param DestinationSubPath 目标子目录（相对于 /Game/）。留空=保持原路径；
	 *                           非空=把选中文件夹整体搬到此子目录下（例如 "Imported/hrw"）。
	 * @param bPreviewOnly       仅预览依赖、不复制任何文件。
	 */
	static void ExecuteMigration(const FString& SourceFolder, const FString& DestinationSubPath = TEXT(""), bool bPreviewOnly = false);

private:
	/** 从给定文件夹向上找 .uproject，解析出源工程根目录、Content 目录、以及选中文件夹相对 Content 的路径。 */
	static bool ResolveSourceProject(const FString& InFolder, FString& OutProjectRoot, FString& OutContentDir, FString& OutSelectedRel);

	/** 枚举选中文件夹下的所有 .uasset / .umap，转为 /Game/ 包名。 */
	static void EnumerateSelectedPackages(const FString& ContentDir, const FString& SelectedRel, TArray<FString>& OutPackages);

	/** 在源工程的 Saved / Intermediate 中查找最新的 AssetRegistry.bin 并加载为 FAssetRegistryState。 */
	static TSharedPtr<FAssetRegistryState> LoadSourceRegistry(const FString& ProjectRoot);

	/** 兜底方案：通过读取 uasset 头文件的 Import 表，拿到某个包对 /Game/ 下其它包的硬依赖。 */
	static void GatherPackageHardDependencies(const FString& SourceContentDir, const FString& PackageName, TArray<FString>& OutDeps);

	/** 从选中包出发，BFS 展开完整 /Game/ 依赖闭包。有 Registry 用 Registry，否则用 Import 表兜底。 */
	static void ExpandDependencies(const FString& SourceContentDir, const TArray<FString>& SelectedPackages, TSet<FString>& OutClosure, TSharedPtr<FAssetRegistryState> Registry);

	/** 包名 -> 源工程磁盘文件。 */
	static FString PackageNameToFile(const FString& SourceContentDir, const FString& PackageName);

	/** 根据闭包构建资产清单，并标记与当前工程的冲突。 */
	static void BuildAssetList(const FString& SourceContentDir, const FString& DestContentDir, const TSet<FString>& Closure, TArray<FCrowdMigrationAsset>& OutAssets);

	/** 弹出冲突确认对话框。返回结果包含确认状态、目标子目录和是否仅预览；对话框会就地修改 Assets 的 bOverwrite。 */
	static FCrowdMigrationDialogResult ShowConflictDialog(TArray<FCrowdMigrationAsset>& Assets);

	/**
	 * 根据"目标子目录"重算每个资产的 DestFile 与 bConflict。
	 * 逻辑：把 RelativePath 中选中文件夹前缀（SelectedRel）去掉得到内部相对路径，
	 *       再拼到 DestinationSubPath 之下；空子目录则保持原路径不变。
	 */
	static void ApplyDestinationSubPath(TArray<FCrowdMigrationAsset>& Assets, const FString& DestContentDir, const FString& SelectedRel, const FString& SubPath);

	/** 按用户选择执行复制（含地图侧车文件），然后刷新目标 AssetRegistry。 */
	static void PerformCopy(const TArray<FCrowdMigrationAsset>& Assets, const FString& DestRoot);
};
