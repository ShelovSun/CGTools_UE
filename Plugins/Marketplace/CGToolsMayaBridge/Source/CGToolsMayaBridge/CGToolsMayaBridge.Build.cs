// Copyright CGTools. All Rights Reserved.

using UnrealBuildTool;

public class CGToolsMayaBridge : ModuleRules
{
    public CGToolsMayaBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "Projects",
                "Sockets",
                "Networking",
                "Json",
                "Slate",
                "SlateCore",
                "UnrealEd",
                "AssetTools",
                "ContentBrowser",
                "PythonScriptPlugin"
            }
        );
    }
}
