#include "CrowdProjectMigrateLibrary.h"
#include "CrowdProjectMigrator.h"

void UCrowdProjectMigrateLibrary::MigrateFromProjectFolder(const FString& SourceFolderPath, const FString& DestinationSubPath, bool bPreviewOnly)
{
	UE_LOG(LogTemp, Warning, TEXT("[CrowdProjectMigrate] MigrateFromProjectFolder: src='%s', sub='%s', preview=%d"),
		*SourceFolderPath, *DestinationSubPath, (int32)bPreviewOnly);

	FCrowdProjectMigrator::ExecuteMigration(SourceFolderPath, DestinationSubPath, bPreviewOnly);
}
