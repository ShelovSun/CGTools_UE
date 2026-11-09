#include "SCGToolsPublisherWindow.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "AssetCompilingManager.h"
#include "Engine/StaticMesh.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SEditableText.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherStaticModelOutputsTest,
    "CGTools.Publisher.Batch.StaticModelOutputs",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherStaticModelOutputsTest::RunTest(const FString& Parameters)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Engine mesh fixture"), Cube)) { return false; }
    FAssetCompilingManager::Get().FinishAllCompilation();
    const FString Root = FPaths::ProjectSavedDir() / TEXT("Automation/StaticModelOutputs") / FGuid::NewGuid().ToString();
    const auto MakePanel = [&](const FString& Name, FColor Color)
    {
        auto State = MakeShared<FCGToolsPublisherDialogState>();
        State->bEmbedded = true;
        auto Panel = SNew(SCGToolsPublisherWindow).AssetData(FAssetData(Cube)).DialogState(State);
        Panel->AssetData = FAssetData(FName(*(TEXT("/Game/Scenes/StaticMesh/TXingChuanSongDai/") + Name)),
            FName(TEXT("/Game/Scenes/StaticMesh/TXingChuanSongDai")), FName(*Name), UStaticMesh::StaticClass()->GetClassPathName());
        Panel->AssetNameTextBox->SetText(FText::FromString(TEXT("TXingChuanSongDai")));
        Panel->CustomIconSize = FIntPoint(8, 8);
        Panel->CustomIconPixels.Init(Color, 64);
        return Panel;
    };
    auto First = MakePanel(TEXT("zhi"), FColor::Red);
    auto Second = MakePanel(TEXT("TXing"), FColor::Green);
    auto Third = MakePanel(TEXT("ShiZi"), FColor::Blue);
    First->SetGroupPanels({ First, Second, Third });
    FString Error;
    TestTrue(TEXT("Actual static batch exports FBX and per-panel icons"), First->ExportMeshOutputs(Root / TEXT("Batch"), true, true, Error));
    TestTrue(TEXT("Export completed without error"), Error.IsEmpty());
    for (const TCHAR* Name : { TEXT("zhi"), TEXT("TXing"), TEXT("ShiZi") })
    {
        TestTrue(TEXT("Every selected model has its FBX"), IFileManager::Get().FileSize(*(Root / TEXT("Batch/FBX") / (FString(Name) + TEXT(".fbx")))) > 0);
        TestTrue(TEXT("Every selected model has its Icon"), IFileManager::Get().FileSize(*(Root / TEXT("Batch/Icon") / (FString(Name) + TEXT(".png")))) > 0);
    }
    TestFalse(TEXT("No synthetic folder FBX"), FPaths::FileExists(Root / TEXT("Batch/FBX/TXingChuanSongDai.fbx")));
    TestFalse(TEXT("No synthetic folder Icon"), FPaths::FileExists(Root / TEXT("Batch/Icon/TXingChuanSongDai.png")));
    TArray<uint8> Red, Green, Blue;
    FFileHelper::LoadFileToArray(Red, *(Root / TEXT("Batch/Icon/zhi.png")));
    FFileHelper::LoadFileToArray(Green, *(Root / TEXT("Batch/Icon/TXing.png")));
    FFileHelper::LoadFileToArray(Blue, *(Root / TEXT("Batch/Icon/ShiZi.png")));
    TestTrue(TEXT("Each model keeps its own captured icon"), Red != Green && Red != Blue && Green != Blue);
    TestEqual(TEXT("Database icon points at an emitted file"), First->GetOutputBaseName(), FString(TEXT("zhi")));
    First->SelectedProject = MakeShared<FString>(TEXT("Fixture"));
    First->SelectedType = MakeShared<FString>(TEXT("StaticMesh"));
    First->TypeTextBox->SetText(FText::FromString(TEXT("StaticMesh")));
    First->Config.RootPath = TEXT("C:/Fixture");
    First->Config.Host = TEXT("unused.test");
    First->Config.Projects = { TEXT("Fixture") };
    First->Config.Error.Reset();
    First->RefreshTargetPath();
    TestTrue(TEXT("Target display uses the real model filename"), First->TargetPathText->GetText().ToString().Contains(TEXT("FBX/zhi.fbx")));

    First->SetGroupPanels({ First });
    TestTrue(TEXT("A one-model group within a batch also uses its own name"), First->ExportMeshOutputs(Root / TEXT("One"), false, true, Error));
    TestTrue(TEXT("Icon-only export creates the requested model"), FPaths::FileExists(Root / TEXT("One/Icon/zhi.png")));
    TestFalse(TEXT("Unchecked FBX option emits no FBX"), FPaths::FileExists(Root / TEXT("One/FBX/zhi.fbx")));

    auto Canonical = MakePanel(TEXT("TXingChuanSongDai"), FColor::White);
    First->SetGroupPanels({ First, Canonical });
    TestTrue(TEXT("An actual selected folder-named model is exported"), First->ExportMeshOutputs(Root / TEXT("ActualCanonical"), false, true, Error));
    TestTrue(TEXT("Actual canonical icon exists"), FPaths::FileExists(Root / TEXT("ActualCanonical/Icon/TXingChuanSongDai.png")));

    First->SetGroupPanels({ First, First });
    TestFalse(TEXT("Duplicate basenames cannot silently overwrite one another"), First->ExportMeshOutputs(Root / TEXT("Duplicate"), true, true, Error));
    First->SetGroupPanels({ First, Second });
    First->bSkeletalMeshPublish = true;
    TestEqual(TEXT("Skeletal output naming is retained"), First->GetOutputBaseName(), FString(TEXT("TXingChuanSongDai")));
    TestTrue(TEXT("Existing skeletal naming branch retains representative and model icons"), First->ExportMeshOutputs(Root / TEXT("SkeletalNaming"), false, true, Error));
    TestTrue(TEXT("Skeletal naming retains folder icon"), FPaths::FileExists(Root / TEXT("SkeletalNaming/Icon/TXingChuanSongDai.png")));
    AddInfo(TEXT("Local staged outputs: ") + Root);
    return true;
}
#endif
