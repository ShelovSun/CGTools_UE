using UnrealBuildTool;

public class CGToolsPublisher : ModuleRules
{
    public CGToolsPublisher(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine"
            }
        );

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "ApplicationCore",
                "AssetRegistry",
                "AssetTools",
                "ContentBrowser",
                "DesktopPlatform",
                "InputCore",
                "ImageCore",
                "Json",
                "MainFrame",
                "Niagara",
                "Projects",
                "PythonScriptPlugin",
                "RenderCore",
                "Slate",
                "SlateCore",
                "ToolMenus",
                "UnrealEd"
            }
        );

        if (Target.Platform == UnrealTargetPlatform.Win64)
        {
            PublicSystemLibraries.AddRange(
                new string[]
                {
                    "gdi32.lib",
                    "user32.lib"
                }
            );
        }
    }
}
