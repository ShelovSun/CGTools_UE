#include "SCGToolsPublisherWindow.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "AssetCompilingManager.h"
#include "Engine/StaticMesh.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherMeshPromotionTest,
    "CGTools.Publisher.Batch.PerModelOutputsAndRollback",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherMeshPromotionTest::RunTest(const FString& Parameters)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Local mesh export fixture"), Cube)) { return false; }
    FAssetCompilingManager::Get().FinishAllCompilation();
    const FString Id = FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString TestRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/BatchOutputs") / Id);
    const FString Stage = TestRoot / TEXT("Stage");
    const FString Final = TestRoot / TEXT("Published");
    IFileManager& Files = IFileManager::Get();
    const auto Write = [&](const FString& Path, const FString& Value)
    {
        Files.MakeDirectory(*FPaths::GetPath(Path), true);
        return FFileHelper::SaveStringToFile(Value, *Path);
    };
    const auto Read = [](const FString& Path)
    {
        TArray<uint8> Bytes; FFileHelper::LoadFileToArray(Bytes, *Path); return Bytes;
    };
    TArray<TSharedPtr<ICGToolsPublisherPanel>> Panels;
    TArray<TStrongObjectPtr<UPackage>> Packages;
    for (const FString& Name : { FString(TEXT("Coin_A")), FString(TEXT("Coin_B")), FString(TEXT("Coins")) })
    {
        Packages.Emplace(CreatePackage(*(TEXT("/Game/Assets/Props/Coins/") + Name)));
        UStaticMesh* Mesh = DuplicateObject<UStaticMesh>(Cube, Packages.Last().Get(), FName(*Name));
        const TSharedRef<FCGToolsPublisherDialogState> State = MakeShared<FCGToolsPublisherDialogState>();
        State->bEmbedded = true;
        TSharedPtr<SCGToolsPublisherWindow> Panel = SNew(SCGToolsPublisherWindow).AssetData(FAssetData(Mesh)).DialogState(State);
        // Distinct per-model captures test that another model's icon is never reused.
        Panel->CustomIconSize = FIntPoint(2, 2);
        Panel->CustomIconPixels.Init(Panels.Num() == 0 ? FColor::Red : Panels.Num() == 1 ? FColor::Green : FColor::Blue, 4);
        Panels.Add(Panel);
    }
    TSharedPtr<SCGToolsPublisherWindow> A = StaticCastSharedPtr<SCGToolsPublisherWindow>(Panels[0]);
    TSharedPtr<SCGToolsPublisherWindow> Canonical = StaticCastSharedPtr<SCGToolsPublisherWindow>(Panels[2]);
    FString Error, History;
    A->SetGroupPanels({ Panels[0], Panels[1] });
    TestTrue(TEXT("A folder without an identically named selection exports a canonical alias"), A->ExportMeshOutputs(Stage, true, true, Error));
    for (const FString& Name : { FString(TEXT("Coin_A")), FString(TEXT("Coin_B")), FString(TEXT("Coins")) })
    {
        TestTrue(TEXT("Every selected model and the folder alias has FBX"), Files.FileSize(*(Stage / TEXT("FBX") / (Name + TEXT(".fbx")))) > 0);
        TestTrue(TEXT("Every selected model and the folder alias has Icon"), Files.FileSize(*(Stage / TEXT("Icon") / (Name + TEXT(".png")))) > 0);
    }
    TestTrue(TEXT("The fallback alias uses the first model's FBX bytes"), Read(Stage / TEXT("FBX/Coins.fbx")) == Read(Stage / TEXT("FBX/Coin_A.fbx")));
    TestTrue(TEXT("The fallback alias uses the first model's own screenshot"), Read(Stage / TEXT("Icon/Coins.png")) == Read(Stage / TEXT("Icon/Coin_A.png")));
    TestTrue(TEXT("Different model screenshots remain distinct"), Read(Stage / TEXT("Icon/Coin_A.png")) != Read(Stage / TEXT("Icon/Coin_B.png")));

    Canonical->SetGroupPanels(Panels);
    TestTrue(TEXT("A folder-named model takes the canonical filename without another alias"), Canonical->ExportMeshOutputs(Stage, true, true, Error));
    TestTrue(TEXT("The named model keeps its own icon"), Read(Stage / TEXT("Icon/Coins.png")) != Read(Stage / TEXT("Icon/Coin_A.png")));
    TArray<FString> Icons;
    Files.FindFiles(Icons, *(Stage / TEXT("Icon/*.png")), true, false);
    TestEqual(TEXT("No duplicate canonical icon is generated"), Icons.Num(), 3);

    Write(Stage / TEXT("UE/Content/Assets/Props/Coins/Coins.uasset"), TEXT("new UE fixture"));
    Write(Stage / TEXT("UE/Coins.uproject"), TEXT("new project fixture"));
    Write(Final / TEXT("UE/Content/Old.uasset"), TEXT("old UE fixture"));
    Write(Final / TEXT("UE/Coins.uproject"), TEXT("old project fixture"));
    Write(Final / TEXT("FBX/Coins.fbx"), TEXT("old canonical FBX"));
    Write(Final / TEXT("FBX/NotSelected.fbx"), TEXT("retained other model FBX"));
    Write(Final / TEXT("Icon/Coins.png"), TEXT("old canonical Icon"));
    Write(Final / TEXT("Icon/NotSelected.png"), TEXT("retained other model Icon"));
    Write(Final / TEXT("Texture/Old.png"), TEXT("old texture fixture"));
    TestTrue(TEXT("Promote all FBX/Icon files in the one folder transaction"), SCGToolsPublisherWindow::PromoteStagedPublish(TEXT("Coins"), Final, Stage,
        TEXT("Assets/Props/Coins/Coins.uasset"), true, true, false, History, Error));
    for (const FString& Name : { FString(TEXT("Coin_A")), FString(TEXT("Coin_B")), FString(TEXT("Coins")) })
    {
        TestTrue(TEXT("All model FBX bytes reach the target"), Read(Final / TEXT("FBX") / (Name + TEXT(".fbx"))) == Read(Stage / TEXT("FBX") / (Name + TEXT(".fbx"))));
        TestTrue(TEXT("All model Icon bytes reach the target"), Read(Final / TEXT("Icon") / (Name + TEXT(".png"))) == Read(Stage / TEXT("Icon") / (Name + TEXT(".png"))));
    }
    TestTrue(TEXT("Unselected model FBX is retained"), Files.FileExists(*(Final / TEXT("FBX/NotSelected.fbx"))));
    TestTrue(TEXT("Unselected model Icon is retained"), Files.FileExists(*(Final / TEXT("Icon/NotSelected.png"))));
    TestTrue(TEXT("The old canonical FBX has a recovery backup"), Files.FileSize(*(History / TEXT("FBX/Coins.fbx"))) > 0);
    TestTrue(TEXT("The old unselected icon is included in the folder backup"), Files.FileSize(*(History / TEXT("Icon/NotSelected.png"))) > 0);

    TMap<FString, TArray<uint8>> Snapshot;
    for (const FString& Directory : { FString(TEXT("UE")), FString(TEXT("FBX")), FString(TEXT("Icon")), FString(TEXT("Texture")) })
    {
        TArray<FString> Paths; Files.FindFilesRecursive(Paths, *(Final / Directory), TEXT("*"), true, false);
        for (const FString& Path : Paths) { Snapshot.Add(Path, Read(Path)); }
    }
    Write(Stage / TEXT("FBX/NewInFailedCommit.fbx"), TEXT("new model fixture"));
    Write(Stage / TEXT("Icon/NewInFailedCommit.png"), TEXT("new icon fixture"));
    // Force failure after UE and per-model outputs have already been copied.
    Write(Stage / TEXT("Texture"), TEXT("a file cannot serve as a texture directory"));
    TestFalse(TEXT("A failed folder commit reports failure"), SCGToolsPublisherWindow::PromoteStagedPublish(TEXT("Coins"), Final, Stage,
        TEXT("Assets/Props/Coins/Coins.uasset"), true, true, true, History, Error));
    for (const TPair<FString, TArray<uint8>>& Pair : Snapshot)
    { TestTrue(TEXT("Rollback restores exact old file bytes"), Read(Pair.Key) == Pair.Value); }
    TestFalse(TEXT("Rollback removes a newly introduced FBX"), Files.FileExists(*(Final / TEXT("FBX/NewInFailedCommit.fbx"))));
    TestFalse(TEXT("Rollback removes a newly introduced Icon"), Files.FileExists(*(Final / TEXT("Icon/NewInFailedCommit.png"))));

    Files.Delete(*(Stage / TEXT("FBX/Coins.fbx")));
    TestFalse(TEXT("A missing canonical output is rejected before modifying published files"), SCGToolsPublisherWindow::PromoteStagedPublish(TEXT("Coins"), Final, Stage,
        TEXT("Assets/Props/Coins/Coins.uasset"), true, true, false, History, Error));
    for (const TPair<FString, TArray<uint8>>& Pair : Snapshot)
    { TestTrue(TEXT("Missing staging output leaves the target intact"), Read(Pair.Key) == Pair.Value); }
    UE_LOG(LogTemp, Display, TEXT("Batch output artifacts: %s"), *TestRoot);
    return true;
}
#endif
