using UnrealBuildTool;

public class CGToolsFolderOrganizer : ModuleRules
{
    public CGToolsFolderOrganizer(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core"
            }
        );

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "CoreUObject",
                "Engine",
                "Slate",
                "SlateCore",
                "UnrealEd",
                "AssetRegistry",
                "AssetTools",
                "ContentBrowser",
                "Niagara"
            }
        );
    }
}
