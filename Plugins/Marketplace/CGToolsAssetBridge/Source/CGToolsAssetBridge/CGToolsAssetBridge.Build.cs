using UnrealBuildTool;

public class CGToolsAssetBridge : ModuleRules
{
    public CGToolsAssetBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine"
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "ApplicationCore",
            "AssetRegistry",
            "ImageWrapper",
            "ImageCore",
            "LevelEditor",
            "Niagara",
            "Slate",
            "SlateCore",
            "UnrealEd"
        });
    }
}
