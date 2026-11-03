#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CrowdProjectMigrateLibrary.generated.h"

/**
 * 蓝图可调用入口：从【未打开】的源工程迁移某个文件夹及其依赖到当前工程。
 *
 * @param SourceFolderPath  源工程里某个位于 Content 目录下的文件夹绝对路径，
 *                          例如 C:/Users/.../test2/Content/ge/hrw
 *                          函数会自动向上查找 .uproject 以确定源工程根目录。
 * @param DestinationSubPath 目标子目录（相对 /Game/）。留空=保持原路径；
 *                           非空=把选中文件夹整体重定位到该子目录（例如 "Imported/hrw"）。
 * @param bPreviewOnly      仅预览依赖、不复制任何文件。
 */
UCLASS()
class SEQUENCEREASETOOLS_API UCrowdProjectMigrateLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "CrossProjectMigrate", meta = (CallableWithoutWorldContext))
	static void MigrateFromProjectFolder(const FString& SourceFolderPath, const FString& DestinationSubPath = TEXT(""), bool bPreviewOnly = false);
};
