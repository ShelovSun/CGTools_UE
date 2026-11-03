// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;


[SupportedTargetTypes(TargetType.Editor)] // 只限定编辑器编译，新建游戏项目跳过加载此模块规则
public class BlueprintComponentTools : ModuleRules
{
	public BlueprintComponentTools(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;
		
		PublicIncludePaths.AddRange(
			new string[] {
				// ... add public include paths required here ...
			}
			);
				
		
		PrivateIncludePaths.AddRange(
			new string[] {
				// ... add other private include paths required here ...
			}
			);
			
		
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
    "Core",
    "CoreUObject",
    "Engine",
      "UnrealEd",
    "InputCore"
				// ... add other public dependencies that you statically link with here ...
			}
			);
			
		
		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				
				
				"Slate",
				"SlateCore",
                "LevelEditor"
				// ... add private dependencies that you statically link with here ...	
			}
			);
		
		
		DynamicallyLoadedModuleNames.AddRange(
			new string[]
			{
				// ... add any modules that your module loads dynamically here ...
			}
			);
	}
}
