#include "CGToolsPublisherMeshExport.h"

#include "AssetExportTask.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Exporters/Exporter.h"
#include "Exporters/FbxExportOption.h"
#include "Exporters/SkeletalMeshExporterFBX.h"
#include "Exporters/StaticMeshExporterFBX.h"
#include "HAL/PlatformFile.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/Paths.h"

bool CGToolsPublisher::ExportMeshFbx(
    UObject* Asset,
    const FString& DestinationFile,
    FString& OutError)
{
    IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
    PlatformFile.CreateDirectoryTree(*FPaths::GetPath(DestinationFile));

    UAssetExportTask* Task = NewObject<UAssetExportTask>();
    Task->Object = Asset;
    if (Asset && Asset->IsA<USkeletalMesh>())
    {
        Task->Exporter = NewObject<USkeletalMeshExporterFBX>(Task);
    }
    else if (Asset && Asset->IsA<UStaticMesh>())
    {
        Task->Exporter = NewObject<UStaticMeshExporterFBX>(Task);
        // Automated FBX export reads Task->Options. Use a task-owned override so
        // publishing excludes collision without changing the mesh or editor settings.
        UFbxExportOption* Options = NewObject<UFbxExportOption>(Task);
        Options->Collision = false;
        Task->Options = Options;
    }
    else
    {
        OutError = TEXT("当前资产不是可发布的静态网格体或骨架网格体。");
        return false;
    }
    Task->Filename = DestinationFile;
    Task->bSelected = false;
    Task->bReplaceIdentical = true;
    Task->bPrompt = false;
    Task->bAutomated = true;
    Task->bUseFileArchive = false;
    Task->bWriteEmptyFiles = false;

    if (!UExporter::RunAssetExportTask(Task)
        || !PlatformFile.FileExists(*DestinationFile)
        || PlatformFile.FileSize(*DestinationFile) <= 0)
    {
        OutError = FString::Printf(TEXT("FBX 导出失败：%s"), *DestinationFile);
        if (Task->Errors.Num() > 0)
        {
            OutError += TEXT("\n") + FString::Join(Task->Errors, TEXT("\n"));
        }
        return false;
    }
    return true;
}
