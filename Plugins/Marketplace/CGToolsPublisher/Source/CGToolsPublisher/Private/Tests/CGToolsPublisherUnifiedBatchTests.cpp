#include "SCGToolsPublisherBatchWindow.h"
#include "SCGToolsPublisherWindow.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Animation/AnimSequence.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "NiagaraSystem.h"
#include "Particles/ParticleSystem.h"
#include "Types/SlateAttributeMetaData.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/Text/STextBlock.h"

namespace
{
    FAssetData BatchAsset(UClass* Class, const FString& Package)
    {
        return FAssetData(FName(*Package), FName(*FPaths::GetPath(Package)),
            FName(*FPaths::GetCleanFilename(Package)), Class->GetClassPathName());
    }

    class FBatchPanelFixture : public ICGToolsPublisherPanel
    {
    public:
        FCGToolsPublisherSharedSettings Settings;
        TSharedPtr<FCGToolsPublisherDialogState> State = MakeShared<FCGToolsPublisherDialogState>();
        FString Name;
        FString Label;
        FString OverrideDestination;
        int32 PublishCalls = 0;
        int32 PeerCount = 0;
        bool bInvalid = false;
        bool bFail = false;
        bool bWarning = false;
        bool bPartial = false;
        bool bReviewsFiles = false;
        TFunction<void()> DuringPublish;
        virtual FCGToolsPublisherSharedSettings GetSharedSettings() const override { return Settings; }
        virtual void ApplySharedSettings(const FCGToolsPublisherSharedSettings& InSettings) override { Settings = InSettings; }
        virtual FString GetRecordLabel() const override { return Label; }
        virtual void SetRecordLabel(const FString& Value) override { Label = Value; }
        virtual void SetGroupPanels(const TArray<TSharedPtr<ICGToolsPublisherPanel>>& Panels) override { PeerCount = Panels.Num(); }
        virtual bool ReviewsPublishFiles() const override { return bReviewsFiles; }
        virtual bool ValidateBatch(FString& Destination, FString& Error) override
        {
            if (bInvalid || Settings.Project.IsEmpty() || Settings.Type.IsEmpty())
            { Error = TEXT("Fixture validation failure"); return false; }
            Destination = OverrideDestination.IsEmpty() ? TEXT("C:/BatchFixture/") + Name : OverrideDestination;
            return true;
        }
        virtual void PublishBatch() override
        {
            ++PublishCalls;
            if (DuringPublish) { DuringPublish(); }
            if (bFail) { State->Error = TEXT("Fixture export failure and location"); return; }
            State->Result = ECGToolsPublisherDialogResult::Published;
            State->bWarning = bWarning;
            State->bPartial = bPartial;
            State->Completion = bWarning ? TEXT("uasset/fbx published; .ma bake failed at fixture path") : TEXT("Fixture published");
        }
    };
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherGroupingTest,
    "CGTools.Publisher.Batch.FolderGroupingAndCanonicalModel",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherGroupingTest::RunTest(const FString& Parameters)
{
    using namespace CGToolsPublisher;
    for (UClass* Class : { UStaticMesh::StaticClass(), USkeletalMesh::StaticClass() })
    {
        TArray<FAssetData> Assets = {
            BatchAsset(Class, TEXT("/Game/Assets/Props/Coins/A")),
            BatchAsset(Class, TEXT("/Game/Assets/Props/Coins/Meshes/B")),
            BatchAsset(Class, TEXT("/Game/Assets/Props/Coins/Coins")),
            BatchAsset(Class, TEXT("/Game/Assets/Props/Other/C")),
        };
        TArray<TArray<int32>> Groups = MakePublishGroups(Assets);
        TestEqual(TEXT("An owning folder is migrated only once"), Groups.Num(), 2);
        TestEqual(TEXT("All selected models remain members"), Groups[0].Num(), 3);
        TestEqual(TEXT("The folder-named model wins even when it is not first"), FindFolderRepresentative(Assets, Groups[0]), 2);
        TestEqual(TEXT("A group without a folder-named model uses the first selection"), FindFolderRepresentative(Assets, { 0, 1 }), 0);
    }
    const TArray<FAssetData> EqualNames = {
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Assets/Props/Coins/A")),
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Scenes/Props/Coins/B"))
    };
    TestEqual(TEXT("Different source folders with the same leaf name are never merged"), MakePublishGroups(EqualNames).Num(), 2);
    for (UClass* Class : { UAnimSequence::StaticClass(), UNiagaraSystem::StaticClass(), UParticleSystem::StaticClass() })
    {
        const TArray<FAssetData> Assets = {
            BatchAsset(Class, TEXT("/Game/Effects/A")), BatchAsset(Class, TEXT("/Game/Effects/B")) };
        TestEqual(TEXT("Animations and effects keep individual output files"), MakePublishGroups(Assets).Num(), 2);
    }
    TestEqual(TEXT("Mixed types have no publish plan"), MakePublishGroups({ EqualNames[0], BatchAsset(UAnimSequence::StaticClass(), TEXT("/Game/Effects/B")) }).Num(), 0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherUnifiedWindowTest,
    "CGTools.Publisher.Batch.SharedSettingsAndExecution",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherUnifiedWindowTest::RunTest(const FString& Parameters)
{
    const TArray<FAssetData> Assets = {
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Assets/Props/Coins/A")),
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Assets/Props/Coins/B")),
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Assets/Props/Coins/Coins")),
        BatchAsset(UStaticMesh::StaticClass(), TEXT("/Game/Assets/Props/Other/Other"))
    };
    TMap<FName, TSharedPtr<FBatchPanelFixture>> Fixtures;
    int32 Confirmations = 0;
    bool bApprove = true;
    const auto Factory = [&Fixtures](const FAssetData& Asset)
    {
        FCGToolsPublisherPanelHandle Handle;
        TSharedPtr<FBatchPanelFixture> Fixture = MakeShared<FBatchPanelFixture>();
        Fixture->Name = FPaths::GetCleanFilename(Asset.PackagePath.ToString());
        Fixture->State->bEmbedded = true;
        Fixtures.Add(Asset.AssetName, Fixture);
        Handle.Panel = Fixture; Handle.State = Fixture->State;
        Handle.Widget = SNew(STextBlock).Text(FText::FromName(Asset.AssetName));
        return Handle;
    };
    const auto MakeWindow = [&](const TArray<FAssetData>& Selection)
    {
        Fixtures.Reset(); Confirmations = 0;
        return SNew(SCGToolsPublisherBatchWindow).Assets(Selection).PanelFactory(Factory)
            .ConfirmBatch([&](const FString&) { ++Confirmations; return bApprove; });
    };
    const auto SetSettings = [&](const TSharedRef<SCGToolsPublisherBatchWindow>& Window)
    {
        auto& Settings = Fixtures[Window->SelectedItem->Asset.AssetName]->Settings;
        Settings.Project = TEXT("ProjectA"); Settings.Type = TEXT("Props");
        Settings.bIcon = false; Settings.bTextures = true; Settings.bNotifyMaya = true;
    };
    const auto IsVisible = [](const TSharedRef<SWidget>& Widget)
    {
        FSlateAttributeMetaData::UpdateOnlyVisibilityAttributes(*Widget,
            FSlateAttributeMetaData::EInvalidationPermission::AllowInvalidationIfConstructed);
        return Widget->GetVisibility().IsVisible();
    };
    const auto Drain = [&](const TSharedRef<SCGToolsPublisherBatchWindow>& Window)
    {
        int32 Ticks = 0;
        while (Window->bRunning && ++Ticks < 60) { Window->Step(0); }
        TestFalse(TEXT("The finite batch returns to idle"), Window->bRunning);
        TestFalse(TEXT("Close is unlocked after the batch"), Window->DialogState->bPublishing);
        TestFalse(TEXT("No progress bar remains after success, failure, cancellation or stopping"), IsVisible(Window->ProgressBar.ToSharedRef()));
    };

    const TSharedRef<SCGToolsPublisherBatchWindow> Window = MakeWindow(Assets);
    TestEqual(TEXT("Every selection is listed"), Window->Items.Num(), 4);
    TestEqual(TEXT("Panels are created lazily"), Fixtures.Num(), 1);
    TestFalse(TEXT("An idle batch has no progress bar"), IsVisible(Window->ProgressBar.ToSharedRef()));
    SetSettings(Window);
    Fixtures[FName(TEXT("A"))]->Label = TEXT("Shared folder Chinese name");
    Window->AssetList->SetSelection(Window->Items[1]);
    TestEqual(TEXT("A row switch retains the selected project"), Fixtures[FName(TEXT("B"))]->Settings.Project, FString(TEXT("ProjectA")));
    TestTrue(TEXT("Export options are shared"), !Fixtures[FName(TEXT("B"))]->Settings.bIcon && Fixtures[FName(TEXT("B"))]->Settings.bTextures);
    TestEqual(TEXT("A shared record label follows the owning folder"), Fixtures[FName(TEXT("B"))]->Label, FString(TEXT("Shared folder Chinese name")));
    Window->GetPanel(2); Window->GetPanel(3);
    Fixtures[FName(TEXT("Other"))]->bFail = true;
    Fixtures[FName(TEXT("Coins"))]->DuringPublish = [&]()
    {
        TestTrue(TEXT("The outer window stays locked while a panel pumps Slate"), Window->DialogState->bPublishing);
        TestTrue(TEXT("The active batch displays its progress"), IsVisible(Window->ProgressBar.ToSharedRef()));
        TestTrue(TEXT("The panel knows its batch confirmation was accepted"), Fixtures[FName(TEXT("Coins"))]->State->bBatchExecution);
        const int32 OtherCalls = Fixtures[FName(TEXT("Other"))]->PublishCalls;
        Window->Step(0); // A nested progress tick must not start another export.
        TestEqual(TEXT("Nested steps cannot publish the next item"), Fixtures[FName(TEXT("Other"))]->PublishCalls, OtherCalls);
    };
    Window->OnStart(); Drain(Window);
    TestEqual(TEXT("Exactly one confirmation covers the entire batch"), Confirmations, 1);
    TestEqual(TEXT("The folder-named representative exports once"), Fixtures[FName(TEXT("Coins"))]->PublishCalls, 1);
    TestEqual(TEXT("All models are supplied for separate FBX/Icon exports"), Fixtures[FName(TEXT("Coins"))]->PeerCount, 3);
    TestEqual(TEXT("A nonrepresentative does not migrate the folder again"), Fixtures[FName(TEXT("A"))]->PublishCalls, 0);
    TestTrue(TEXT("A grouped success updates every member"), Window->Items[0]->Result == SCGToolsPublisherBatchWindow::EResult::Succeeded && Window->Items[1]->Result == SCGToolsPublisherBatchWindow::EResult::Succeeded);
    TestTrue(TEXT("Failure retains its exact reason"), Window->Items[3]->Detail.Contains(TEXT("Fixture export failure")));
    TestTrue(TEXT("Partial results count every selected asset and describe the grouped work"),
        Window->Status.Contains(TEXT("完成 3 个资产，未完成 1 个资产（共 2 个发布项）")));
    Fixtures[FName(TEXT("Other"))]->bFail = false;
    Fixtures[FName(TEXT("Other"))]->bWarning = true;
    Window->OnStart(); Drain(Window);
    TestEqual(TEXT("A retry leaves successful exports alone"), Fixtures[FName(TEXT("Coins"))]->PublishCalls, 1);
    TestEqual(TEXT("Only the failure is retried"), Fixtures[FName(TEXT("Other"))]->PublishCalls, 2);
    TestTrue(TEXT("A Maya warning remains a published result with detail"), Window->Items[3]->Result == SCGToolsPublisherBatchWindow::EResult::Warning && Window->Items[3]->Detail.Contains(TEXT(".ma bake failed")));
    TestTrue(TEXT("Successful retry includes assets completed in an earlier attempt"),
        Window->Status.Contains(TEXT("完成 4 个资产，未完成 0 个资产（共 2 个发布项）")));
    Window->OnStart();
    TestFalse(TEXT("Starting an already completed batch keeps progress hidden"), IsVisible(Window->ProgressBar.ToSharedRef()));
    TestTrue(TEXT("The completed asset count survives a no-op retry"), Window->Status.Contains(TEXT("完成 4 个资产")));

    Fixtures[FName(TEXT("B"))]->Label = TEXT("Changed folder label");
    Window->OnStart(); Drain(Window);
    TestEqual(TEXT("Editing a completed folder queues that folder again"), Fixtures[FName(TEXT("Coins"))]->PublishCalls, 2);
    TestEqual(TEXT("Editing one folder leaves the other completed folder alone"), Fixtures[FName(TEXT("Other"))]->PublishCalls, 2);

    const TSharedRef<SCGToolsPublisherBatchWindow> Grouped = MakeWindow({ Assets[0], Assets[1] });
    SetSettings(Grouped); Grouped->OnStart(); Drain(Grouped);
    TestTrue(TEXT("Two models in one folder are reported as two successful assets"),
        Grouped->Status.Contains(TEXT("完成 2 个资产，未完成 0 个资产（共 1 个发布项）")));
    Grouped->AssetList->SetSelection(Grouped->Items[1]);
    TestTrue(TEXT("Selecting a nonrepresentative after completion keeps its published result"),
        Grouped->Items[1]->Result == SCGToolsPublisherBatchWindow::EResult::Succeeded
        && Grouped->Items[1]->Detail == TEXT("Fixture published"));
    TestFalse(TEXT("Switching completed models cannot restore the batch progress bar"), IsVisible(Grouped->ProgressBar.ToSharedRef()));

    const TSharedRef<SCGToolsPublisherBatchWindow> Invalid = MakeWindow({ Assets[0], Assets[3] });
    SetSettings(Invalid); Invalid->GetPanel(1);
    Fixtures[FName(TEXT("Other"))]->bInvalid = true;
    Invalid->OnStart(); Drain(Invalid);
    TestEqual(TEXT("Preflight failures do not ask for approval"), Confirmations, 0);
    TestEqual(TEXT("Nothing is exported when any preflight fails"), Fixtures[FName(TEXT("A"))]->PublishCalls, 0);

    const TSharedRef<SCGToolsPublisherBatchWindow> Duplicate = MakeWindow({ Assets[0], Assets[3] });
    SetSettings(Duplicate); Duplicate->GetPanel(1);
    Fixtures[FName(TEXT("A"))]->OverrideDestination = TEXT("C:/BatchFixture/Same");
    Fixtures[FName(TEXT("Other"))]->OverrideDestination = TEXT("c:\\batchfixture\\Same");
    Duplicate->OnStart(); Drain(Duplicate);
    TestEqual(TEXT("Case/slash aliases cannot overwrite another selected output"), Confirmations, 0);
    TestEqual(TEXT("Target collision causes no exports"), Fixtures[FName(TEXT("Other"))]->PublishCalls, 0);

    bApprove = false;
    const TSharedRef<SCGToolsPublisherBatchWindow> Cancelled = MakeWindow({ Assets[0], Assets[3] });
    SetSettings(Cancelled); Cancelled->OnStart(); Drain(Cancelled);
    TestEqual(TEXT("No never-approved exports run"), Fixtures[FName(TEXT("A"))]->PublishCalls, 0);
    bApprove = true;

    const TSharedRef<SCGToolsPublisherBatchWindow> Stopped = MakeWindow({ Assets[0], Assets[3] });
    SetSettings(Stopped);
    Fixtures[FName(TEXT("A"))]->DuringPublish = [&]() { Stopped->OnStopOrClose(); };
    Stopped->OnStart(); Drain(Stopped);
    TestEqual(TEXT("Stopping retains the current completed export"), Fixtures[FName(TEXT("A"))]->PublishCalls, 1);
    TestEqual(TEXT("Stopping leaves the next export untouched"), Fixtures[FName(TEXT("Other"))]->PublishCalls, 0);

    const TSharedRef<SCGToolsPublisherBatchWindow> Reviewed = MakeWindow({ Assets[0], Assets[1] });
    SetSettings(Reviewed);
    Fixtures[FName(TEXT("A"))]->bReviewsFiles = true;
    Fixtures[FName(TEXT("A"))]->bPartial = true;
    Reviewed->OnStart(); Drain(Reviewed);
    TestEqual(TEXT("A file-reviewing publisher does not use a generic batch overwrite confirmation"), Confirmations, 0);
    TestTrue(TEXT("Partial file selection is shown on every grouped model"),
        Reviewed->Items[0]->Result == SCGToolsPublisherBatchWindow::EResult::Partial
        && Reviewed->Items[1]->Result == SCGToolsPublisherBatchWindow::EResult::Partial);
    TestFalse(TEXT("Partial output cannot mark a group completed"), Reviewed->Groups[0].bCompleted);
    Fixtures[FName(TEXT("A"))]->bPartial = false;
    Reviewed->OnStart(); Drain(Reviewed);
    TestEqual(TEXT("A partially published group is reviewed again on retry"), Fixtures[FName(TEXT("A"))]->PublishCalls, 2);
    TestTrue(TEXT("Publishing the remaining differences completes the group"), Reviewed->Groups[0].bCompleted);

    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Real mesh panel fixture"), Cube)) { return false; }
    for (const bool bEmbedded : { false, true })
    {
        const TSharedRef<FCGToolsPublisherDialogState> State = MakeShared<FCGToolsPublisherDialogState>();
        State->bEmbedded = bEmbedded;
        const TSharedRef<SCGToolsPublisherWindow> Panel = SNew(SCGToolsPublisherWindow).AssetData(FAssetData(Cube)).DialogState(State);
        const TSharedRef<SWidget> ProgressContainer = Panel->ProgressBar->GetParentWidget().ToSharedRef();
        const TSharedRef<SWidget> StatusContainer = Panel->StatusText->GetParentWidget().ToSharedRef();
        TestFalse(TEXT("A ready model panel has no empty progress track"), IsVisible(ProgressContainer));
        TestEqual(TEXT("Embedded model panels never show a duplicate ready/status row"), IsVisible(StatusContainer), !bEmbedded);
        Panel->bIsPublishing = true;
        TestEqual(TEXT("Only a standalone publishing panel shows its own progress"), IsVisible(ProgressContainer), !bEmbedded);
        Panel->SetProgress(1.0f, FText::FromString(TEXT("发布完成")));
        Panel->bIsPublishing = false;
        TestFalse(TEXT("Model progress disappears at completion"), IsVisible(ProgressContainer));
        TestEqual(TEXT("The standalone model retains its completed status text"), Panel->StatusText->GetText().ToString(), FString(TEXT("发布完成")));
    }
    return true;
}
#endif
