// Copyright Epic Games, Inc. All Rights Reserved.

#include "SequencerEaseTools.h"
#include "CrowdProjectMigrator.h"

#define LOCTEXT_NAMESPACE "FSequencerEaseToolsModule"

void FSequencerEaseToolsModule::StartupModule()
{
	// 注册控制台命令：CrowdMigrate <源Content下文件夹绝对路径> [目标子目录] [preview]
	// 用法示例：CrowdMigrate "D:/OtherProj/Content/Ge/hrw" "Imported/hrw" preview
	IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("CrowdMigrate"),
		TEXT("从一个【未打开】的 UE 工程迁移某文件夹及其依赖。用法：CrowdMigrate <绝对文件夹路径> [目标子目录] [preview]"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& Args)
		{
			if (Args.Num() > 0)
			{
				FString SubPath = (Args.Num() >= 2) ? Args[1] : TEXT("");
				bool bPreview = (Args.Num() >= 3) &&
					(Args[2] == TEXT("1") || Args[2] == TEXT("true") || Args[2] == TEXT("preview"));
				FCrowdProjectMigrator::ExecuteMigration(Args[0], SubPath, bPreview);
			}
			else
			{
				UE_LOG(LogTemp, Warning, TEXT("CrowdMigrate: 需要传入一个文件夹路径参数。"));
			}
		}));
}

void FSequencerEaseToolsModule::ShutdownModule()
{
	// This function may be called during shutdown to clean up your module.  For modules that support dynamic reloading,
	// we call this function before unloading the module.
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FSequencerEaseToolsModule, SequencerEaseTools)