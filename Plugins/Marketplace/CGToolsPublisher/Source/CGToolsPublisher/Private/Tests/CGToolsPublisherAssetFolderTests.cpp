#include "CGToolsPublisherAssetFolder.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsSkeletalFolderNameTest,
    "CGTools.Publisher.AssetFolder.NameAndNestedMeshes",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsSkeletalFolderNameTest::RunTest(const FString& Parameters)
{
    for (const FString& Package : {
        FString(TEXT("/Game/Assets/Props/LanWangD/LanWangD2")),
        FString(TEXT("/Game/Assets/Props/LanWangD/Meshes/LanWangD2")) })
    {
        FString Type, Folder, Name, Error;
        TestTrue(TEXT("Resolve selected mesh's owning asset folder"),
            CGToolsPublisher::ResolveSkeletalAssetFolder(Package, TEXT("Assets"), Type, Folder, Name, Error));
        TestEqual(TEXT("Database asset uses the folder name"), Name, FString(TEXT("LanWangD")));
        TestEqual(TEXT("Type"), Type, FString(TEXT("Props")));
        TestEqual(TEXT("Migration root"), Folder, FString(TEXT("/Game/Assets/Props/LanWangD")));
    }
    FString Type, Folder, Name, Error;
    TestTrue(TEXT("Configured asset root and Unicode folders"), CGToolsPublisher::ResolveSkeletalAssetFolder(
        TEXT("/Game/Library/Characters/角色/Meshes/Body"), TEXT("Library"), Type, Folder, Name, Error));
    TestEqual(TEXT("Unicode folder name"), Name, FString(TEXT("角色")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsSkeletalInvalidFolderTest,
    "CGTools.Publisher.AssetFolder.RejectInvalidRoots",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsSkeletalInvalidFolderTest::RunTest(const FString& Parameters)
{
    for (const FString& Package : {
        FString(TEXT("/Game/Assets/Props/LooseMesh")),
        FString(TEXT("/Game/Scenes/Props/LanWangD/LanWangD2")),
        FString(TEXT("/Other/Assets/Props/LanWangD/LanWangD2")),
        FString(TEXT("/Game/Assets/Props/../LanWangD2")) })
    {
        FString Type, Folder, Name, Error;
        TestFalse(TEXT("Cannot publish outside a distinct asset folder"),
            CGToolsPublisher::ResolveSkeletalAssetFolder(Package, TEXT("Assets"), Type, Folder, Name, Error));
        TestTrue(TEXT("Failure includes the selected package"), Error.Contains(Package));
        TestTrue(TEXT("Failure clears the folder"), Folder.IsEmpty());
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsSkeletalFolderContentsTest,
    "CGTools.Publisher.AssetFolder.IncludeSiblingsAndChildren",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsSkeletalFolderContentsTest::RunTest(const FString& Parameters)
{
    const FString Folder = TEXT("/Game/Assets/Props/LanWangD");
    const FName Selected(TEXT("/Game/Assets/Props/LanWangD/LanWangD2"));
    TArray<FName> Packages = {Selected};
    TArray<FAssetData> Assets;
    for (const TCHAR* Package : {
        TEXT("/Game/Assets/Props/LanWangD/LanWangD"),
        TEXT("/Game/Assets/Props/LanWangD/LanWangD2"),
        TEXT("/Game/Assets/Props/LanWangD/Materials/M_Net"),
        TEXT("/Game/Assets/Props/LanWangD2/Other"),
        TEXT("/Game/Assets/MasterMaterial/blue") })
    {
        FAssetData Data;
        Data.PackageName = FName(Package);
        Assets.Add(Data);
    }
    FAssetData Redirector;
    Redirector.PackageName = FName(TEXT("/Game/Assets/Props/LanWangD/OldMesh"));
    Redirector.AssetClassPath = FTopLevelAssetPath(TEXT("/Script/CoreUObject"), TEXT("ObjectRedirector"));
    Assets.Add(Redirector);
    CGToolsPublisher::AddAssetFolderPackages(Folder, Assets, Packages);
    TestEqual(TEXT("Selected mesh, unreferenced sibling, and nested material are all roots"), Packages.Num(), 3);
    TestTrue(TEXT("Sibling mesh is explicitly migrated without depending on a reference"),
        Packages.Contains(FName(TEXT("/Game/Assets/Props/LanWangD/LanWangD"))));
    TestTrue(TEXT("Nested assets are included"),
        Packages.Contains(FName(TEXT("/Game/Assets/Props/LanWangD/Materials/M_Net"))));
    TestFalse(TEXT("Redirectors are not migrated"), Packages.Contains(Redirector.PackageName));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsStaticFolderNameTest,
    "CGTools.Publisher.AssetFolder.StaticNameAndNestedMeshes",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsStaticFolderNameTest::RunTest(const FString& Parameters)
{
    for (const FString& Root : { FString(TEXT("Assets")), FString(TEXT("Scenes")) })
    {
        for (const FString& Mesh : { FString(TEXT("JinBiQian_A1")), FString(TEXT("JinBiQian_A1_1a")),
            FString(TEXT("JinBiQian_S")), FString(TEXT("JinBiQian_Z")), FString(TEXT("Meshes/JinBiQian_A1")) })
        {
            const FString Package = TEXT("/Game/") + Root + TEXT("/Props/JinBiQian/") + Mesh;
            FString Type, Folder, Name, Error;
            TestTrue(TEXT("Static mesh resolves its owning library folder"),
                CGToolsPublisher::ResolveStaticAssetFolder(Package, TEXT("Assets"), TEXT("Scenes"), Type, Folder, Name, Error));
            TestEqual(TEXT("Every coin variant shares the same publish name"), Name, FString(TEXT("JinBiQian")));
            TestEqual(TEXT("Nested meshes retain the owning asset root"), Folder, TEXT("/Game/") + Root + TEXT("/Props/JinBiQian"));
            TestEqual(TEXT("Source type is preserved"), Type, FString(TEXT("Props")));
        }
    }
    FString Type, Folder, Name, Error;
    TestTrue(TEXT("Configured roots and Unicode names"), CGToolsPublisher::ResolveStaticAssetFolder(
        TEXT("/Game/EnvironmentLibrary/建筑/金币/Meshes/Coin_A"), TEXT("AssetLibrary"), TEXT("EnvironmentLibrary"),
        Type, Folder, Name, Error));
    TestEqual(TEXT("Unicode publish name"), Name, FString(TEXT("金币")));
    TestEqual(TEXT("Configured scene root"), Folder, FString(TEXT("/Game/EnvironmentLibrary/建筑/金币")));
    TestTrue(TEXT("Legacy imported folders use the immediate parent"), CGToolsPublisher::ResolveStaticAssetFolder(
        TEXT("/Game/Imported/Coins/Coin_A"), TEXT("Assets"), TEXT("Scenes"), Type, Folder, Name, Error));
    TestEqual(TEXT("Legacy folder name"), Name, FString(TEXT("Coins")));
    TestEqual(TEXT("Legacy migration root"), Folder, FString(TEXT("/Game/Imported/Coins")));
    TestTrue(TEXT("Legacy source does not impose a destination type"), Type.IsEmpty());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsStaticInvalidFolderTest,
    "CGTools.Publisher.AssetFolder.StaticRejectInvalidFolders",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsStaticInvalidFolderTest::RunTest(const FString& Parameters)
{
    for (const FString& Package : {
        FString(TEXT("/Game/Coin_A")),
        FString(TEXT("/Game/Assets/Props/LooseMesh")),
        FString(TEXT("/Game/Scenes/Props/LooseMesh")),
        FString(TEXT("/Game/Assets/Props/Coin//Coin_A")),
        FString(TEXT("/Game/Imported/../Coin_A")),
        FString(TEXT("/Game/Imported/./Coin_A")),
        FString(TEXT("/Other/Coins/Coin_A")),
        FString(TEXT("/GameOther/Coins/Coin_A")) })
    {
        FString Type = TEXT("stale"), Folder = TEXT("stale"), Name = TEXT("stale"), Error;
        TestFalse(TEXT("A publish unit requires a valid independent project folder"),
            CGToolsPublisher::ResolveStaticAssetFolder(Package, TEXT("Assets"), TEXT("Scenes"), Type, Folder, Name, Error));
        TestTrue(TEXT("Error identifies the selected package"), Error.Contains(Package));
        TestTrue(TEXT("Invalid paths clear the old folder"), Folder.IsEmpty());
        TestTrue(TEXT("Invalid paths clear the old name"), Name.IsEmpty());
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsStaticFolderContentsTest,
    "CGTools.Publisher.AssetFolder.StaticIncludeAllCoinVariants",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsStaticFolderContentsTest::RunTest(const FString& Parameters)
{
    const FString Folder = TEXT("/Game/Assets/Props/JinBiQian");
    TArray<FAssetData> Assets;
    for (const TCHAR* Package : {
        TEXT("/Game/Assets/Props/JinBiQian/JinBiQian_A1"),
        TEXT("/Game/Assets/Props/JinBiQian/JinBiQian_A1_1a"),
        TEXT("/Game/Assets/Props/JinBiQian/JinBiQian_S"),
        TEXT("/Game/Assets/Props/JinBiQian/JinBiQian_Z"),
        TEXT("/Game/Assets/Props/JinBiQian/Materials/M_Coin"),
        TEXT("/Game/Assets/Props/JinBiQianOther/OtherCoin"),
        TEXT("/Game/Assets/MasterMaterial/blue") })
    {
        FAssetData Data;
        Data.PackageName = FName(Package);
        Assets.Add(Data);
    }
    FAssetData Redirector;
    Redirector.PackageName = FName(*(Folder / TEXT("OldCoin")));
    Redirector.AssetClassPath = FTopLevelAssetPath(TEXT("/Script/CoreUObject"), TEXT("ObjectRedirector"));
    Assets.Add(Redirector);
    for (int32 SelectedIndex = 0; SelectedIndex < 4; ++SelectedIndex)
    {
        TArray<FName> Packages = { Assets[SelectedIndex].PackageName };
        CGToolsPublisher::AddAssetFolderPackages(Folder, Assets, Packages);
        TestEqual(TEXT("Every selection includes all four coins and the nested material"), Packages.Num(), 5);
        for (int32 Index = 0; Index < 5; ++Index)
        {
            TestTrue(TEXT("Unreferenced sibling variants are included"), Packages.Contains(Assets[Index].PackageName));
        }
        TestFalse(TEXT("Redirector is excluded"), Packages.Contains(Redirector.PackageName));
        TestFalse(TEXT("Similarly named folders are excluded"), Packages.Contains(Assets[5].PackageName));
        TestFalse(TEXT("Unrelated shared assets are left to native dependency gathering"), Packages.Contains(Assets[6].PackageName));
    }
    return true;
}
#endif
