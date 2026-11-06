#include "CGToolsPublisherFileReview.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "Framework/Application/SlateApplication.h"
#include "ImageUtils.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "RenderingThread.h"
#include "Widgets/SWindow.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Text/STextBlock.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublishFileSelectionTest,
    "CGTools.Publisher.FileReview.SelectionBackupAndRetry",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublishFileSelectionTest::RunTest(const FString& Parameters)
{
    using namespace CGToolsPublisher;
    IFileManager& Files = IFileManager::Get();
    const FString Root = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/FileReview") / FGuid::NewGuid().ToString());
    const FString Stage = Root / TEXT("Stage"), Target = Root / TEXT("Server"), Backup = Target / TEXT("history");
    const auto Write = [&](const FString& Path, const FString& Value)
    { Files.MakeDirectory(*FPaths::GetPath(Path), true); return FFileHelper::SaveStringToFile(Value, *Path); };
    const auto Read = [](const FString& Path)
    { FString Value; FFileHelper::LoadFileToString(Value, *Path); return Value; };
    Write(Stage / TEXT("UE/Content/Model.uasset"), TEXT("new package"));
    Write(Stage / TEXT("UE/Content/Model.uexp"), TEXT("new companion"));
    Write(Stage / TEXT("UE/Project.uproject"), TEXT("same project"));
    Write(Stage / TEXT("Icon/Model.png"), TEXT("new icon"));
    Write(Target / TEXT("UE/Content/Model.uasset"), TEXT("old package"));
    Write(Target / TEXT("UE/Content/Model.uexp"), TEXT("old companion"));
    Write(Target / TEXT("UE/Project.uproject"), TEXT("same project"));
    Write(Target / TEXT("FBX/Other.fbx"), TEXT("unselected model"));
    for (const FString& Name : { FString(TEXT("Thumbs.db")), FString(TEXT("EHTHUMBS.DB")), FString(TEXT("ehthumbs_vista.db")),
        FString(TEXT("Desktop.ini")), FString(TEXT(".DS_Store")), FString(TEXT("._Model.png")), FString(TEXT("~$Model.fbx")),
        FString(TEXT("Model.uasset.CGToolsPublish_123.tmp")), FString(TEXT("Model.TEMP")) })
    {
        Write(Stage / TEXT("Icon") / Name, TEXT("new cache"));
        Write(Target / TEXT("Icon") / Name, TEXT("keep server cache"));
    }
    Write(Stage / TEXT("Icon/OnlyLocal.tmp"), TEXT("never upload"));
    const TArray<FString> Roots = { TEXT("UE"), TEXT("FBX"), TEXT("Icon") };
    auto Plan = BuildPublishFilePlan(Stage, Target, Roots);
    TestTrue(TEXT("Plan reads both sides without error"), Plan.Error.IsEmpty());
    TestEqual(TEXT("Conflict, added, missing and identical rows are all listed"), Plan.Files.Num(), 5);
    TestEqual(TEXT("No file is selected by default"), Plan.NumSelected(), 0);
    TestEqual(TEXT("Only differences with local output can be selected"), Plan.NumSelectable(), 3);
    auto Find = [](FPublishFilePlan& Value, const FString& Relative)
    { return *Value.Files.FindByPredicate([&](const auto& File) { return File->Relative == Relative; }); };
    TestTrue(TEXT("New icon is marked as a server-missing addition"), Find(Plan, TEXT("Icon/Model.png"))->Difference == EPublishFileDifference::Added);
    TestTrue(TEXT("Server-only model is marked missing locally"), Find(Plan, TEXT("FBX/Other.fbx"))->Difference == EPublishFileDifference::Missing);
    const auto Nothing = CommitPublishFiles(Plan, Backup);
    TestFalse(TEXT("No selection performs no publish"), Nothing.bSucceeded);
    TestEqual(TEXT("Cancelling or selecting nothing leaves old bytes intact"), Read(Target / TEXT("UE/Content/Model.uasset")), FString(TEXT("old package")));
    Plan.Select(Find(Plan, TEXT("UE/Content/Model.uasset")), true);
    TestEqual(TEXT("Selecting a UE package also selects its changed companion"), Plan.NumSelected(), 2);
    const auto Partial = CommitPublishFiles(Plan, Backup);
    TestTrue(TEXT("The selected package and companion can be published"), Partial.bSucceeded);
    TestFalse(TEXT("Skipping an addition does not mark the whole publish complete"), Partial.bComplete);
    TestEqual(TEXT("Exactly two selected files were written"), Partial.Copied, 2);
    TestEqual(TEXT("Unselected server file is preserved"), Read(Target / TEXT("FBX/Other.fbx")), FString(TEXT("unselected model")));
    TestFalse(TEXT("Unselected new icon is not uploaded"), Files.FileExists(*(Target / TEXT("Icon/Model.png"))));
    TestEqual(TEXT("Backup contains original package bytes"), Read(Partial.History / TEXT("UE/Content/Model.uasset")), FString(TEXT("old package")));
    TestEqual(TEXT("Backup contains original companion bytes"), Read(Partial.History / TEXT("UE/Content/Model.uexp")), FString(TEXT("old companion")));
    auto Retry = BuildPublishFilePlan(Stage, Target, Roots);
    TestEqual(TEXT("Retry compares actual files, leaving only the unselected addition"), Retry.NumSelectable(), 1);
    Retry.Select(Find(Retry, TEXT("Icon/Model.png")), true);
    const auto Finished = CommitPublishFiles(Retry, Backup);
    TestTrue(TEXT("Retry completes all current output differences"), Finished.bSucceeded && Finished.bComplete);
    TestEqual(TEXT("Retry copies only the remaining file"), Finished.Copied, 1);
    TestTrue(TEXT("A purely new file needs no old-file backup"), Finished.History.IsEmpty());
    TestEqual(TEXT("Server-only file is still retained after completion"), Read(Target / TEXT("FBX/Other.fbx")), FString(TEXT("unselected model")));
    TestEqual(TEXT("Ignored server cache remains untouched after publishing"), Read(Target / TEXT("Icon/Thumbs.db")), FString(TEXT("keep server cache")));
    TestFalse(TEXT("Staged temporary files are never uploaded"), Files.FileExists(*(Target / TEXT("Icon/OnlyLocal.tmp"))));
    const auto ExplicitRoots = BuildPublishFilePlan(Stage, Target, { TEXT("Icon/Thumbs.db"), TEXT("Icon/OnlyLocal.tmp"), TEXT("UE/Content/Model.uasset") });
    TestEqual(TEXT("Explicit file roots used by animation/VFX also exclude cache and temporary files"), ExplicitRoots.Files.Num(), 1);
    auto Identical = BuildPublishFilePlan(Stage, Target, Roots);
    const auto Unchanged = CommitPublishFiles(Identical, Backup);
    TestTrue(TEXT("Identical repeated output is complete without rewriting bytes"), Unchanged.bSucceeded && Unchanged.bComplete && Unchanged.Copied == 0);
    Write(Target / TEXT("UE/Content/Model.uasset"), TEXT("concurrent version"));
    TestFalse(TEXT("A previously identical file changing after review blocks completion"), CommitPublishFiles(Identical, Backup).bSucceeded);
    TestEqual(TEXT("A concurrent change is never overwritten"), Read(Target / TEXT("UE/Content/Model.uasset")), FString(TEXT("concurrent version")));
    TestFalse(TEXT("Relative roots cannot escape staging or the target"), BuildPublishFilePlan(Stage, Target, { TEXT("../Outside") }).Error.IsEmpty());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublishFileRollbackTest,
    "CGTools.Publisher.FileReview.ConcurrentChangesAndRollback",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublishFileRollbackTest::RunTest(const FString& Parameters)
{
    using namespace CGToolsPublisher;
    IFileManager& Files = IFileManager::Get();
    const FString Root = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/FileReview") / FGuid::NewGuid().ToString());
    const FString Stage = Root / TEXT("Stage"), Target = Root / TEXT("Server");
    const auto Write = [&](const FString& Path, const FString& Value)
    { Files.MakeDirectory(*FPaths::GetPath(Path), true); return FFileHelper::SaveStringToFile(Value, *Path); };
    const auto Read = [](const FString& Path)
    { FString Value; FFileHelper::LoadFileToString(Value, *Path); return Value; };
    for (const FString& Name : { FString(TEXT("A.fbx")), FString(TEXT("B.fbx")) })
    { Write(Stage / Name, TEXT("new")); Write(Target / Name, TEXT("old")); }
    auto Plan = BuildPublishFilePlan(Stage, Target, { TEXT("A.fbx"), TEXT("B.fbx") });
    for (const auto& File : Plan.Files) { Plan.Select(File, true); }
    Write(Target / TEXT("B.fbx"), TEXT("someone else"));
    TestFalse(TEXT("Concurrent changes reject the entire commit before any overwrite"), CommitPublishFiles(Plan, Target / TEXT("history")).bSucceeded);
    TestEqual(TEXT("The earlier file is untouched"), Read(Target / TEXT("A.fbx")), FString(TEXT("old")));
    Write(Target / TEXT("B.fbx"), TEXT("old"));
    Plan = BuildPublishFilePlan(Stage, Target, { TEXT("A.fbx"), TEXT("B.fbx") });
    for (const auto& File : Plan.Files) { Plan.Select(File, true); }
    TestTrue(TEXT("Failure fixture is read-only"), FPlatformFileManager::Get().GetPlatformFile().SetReadOnly(*(Target / TEXT("B.fbx")), true));
    const auto Failed = CommitPublishFiles(Plan, Target / TEXT("history"));
    FPlatformFileManager::Get().GetPlatformFile().SetReadOnly(*(Target / TEXT("B.fbx")), false);
    TestFalse(TEXT("A late write failure is reported"), Failed.bSucceeded);
    TestEqual(TEXT("Rollback restores a previously replaced file"), Read(Target / TEXT("A.fbx")), FString(TEXT("old")));
    TestEqual(TEXT("The failed file retains its original bytes"), Read(Target / TEXT("B.fbx")), FString(TEXT("old")));
    TestTrue(TEXT("The exact failed location and backup are reported"), Failed.Error.Contains(TEXT("B.fbx")) && !Failed.History.IsEmpty());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublishFileReviewWindowTest,
    "CGTools.Publisher.FileReview.NativeWindowAndCancel",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter | EAutomationTestFlags::NonNullRHI)

bool FCGToolsPublishFileReviewWindowTest::RunTest(const FString& Parameters)
{
    using namespace CGToolsPublisher;
    IFileManager& Files = IFileManager::Get();
    const FString Root = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/FileReviewPreview"));
    const FString Stage = Root / TEXT("Stage"), Target = Root / TEXT("Server");
    const auto Write = [&](const FString& Path, const FString& Value)
    { Files.MakeDirectory(*FPaths::GetPath(Path), true); return FFileHelper::SaveStringToFile(Value, *Path); };
    Write(Stage / TEXT("UE/Content/Scenes/StaticMesh/TXingChuanSongDai/TXing.uasset"), TEXT("new mesh"));
    Write(Target / TEXT("UE/Content/Scenes/StaticMesh/TXingChuanSongDai/TXing.uasset"), TEXT("old mesh"));
    Write(Stage / TEXT("Icon/TXing.png"), TEXT("new icon"));
    Write(Target / TEXT("FBX/Other.fbx"), TEXT("retained model"));
    Write(Stage / TEXT("UE/TXingChuanSongDai.uproject"), TEXT("same project"));
    Write(Target / TEXT("UE/TXingChuanSongDai.uproject"), TEXT("same project"));
    const auto Plan = MakeShared<FPublishFilePlan>(BuildPublishFilePlan(Stage, Target, { TEXT("UE"), TEXT("FBX"), TEXT("Icon") }));
    const TSharedRef<SWindow> Parent = SNew(SWindow).ClientSize(FVector2D(300, 100)) [ SNew(STextBlock).Text(FText::FromString(TEXT("File review fixture"))) ];
    FSlateApplication::Get().AddWindow(Parent);
    bool bCaptured = false;
    int32 ModalTicks = 0;
    const FDelegateHandle Driver = FSlateApplication::Get().GetOnModalLoopTickEvent().AddLambda([&](float)
    {
        const auto Modal = FSlateApplication::Get().GetActiveModalWindow();
        if (!Modal.IsValid() || ++ModalTicks < 3) { return; }
        TFunction<TSharedPtr<SWidget>(const TSharedRef<SWidget>&)> FindHeader;
        FindHeader = [&FindHeader](const TSharedRef<SWidget>& Widget) -> TSharedPtr<SWidget>
        {
            if (Widget->GetTag() == FName(TEXT("PublishFilesSelectAll"))) { return Widget; }
            FChildren* Children = Widget->GetChildren();
            for (int32 Index = 0; Index < Children->Num(); ++Index)
            {
                if (const auto Found = FindHeader(Children->GetChildAt(Index))) { return Found; }
            }
            return nullptr;
        };
        const auto HeaderWidget = FindHeader(Modal.ToSharedRef());
        if (TestTrue(TEXT("The file header contains a select-all checkbox"), HeaderWidget.IsValid()))
        {
            const auto Header = StaticCastSharedPtr<SCheckBox>(HeaderWidget);
            TestTrue(TEXT("Header starts unchecked"), Header->GetCheckedState() == ECheckBoxState::Unchecked);
            Header->ToggleCheckedState();
            TestEqual(TEXT("Header selects all publishable differences"), Plan->NumSelected(), Plan->NumSelectable());
            TestTrue(TEXT("Header reflects the all-selected state"), Header->GetCheckedState() == ECheckBoxState::Checked);
            TestFalse(TEXT("Header leaves identical and server-only rows unchecked"), Plan->Files.ContainsByPredicate([](const auto& File)
                { return !File->CanSelect() && File->bSelected; }));
            Header->ToggleCheckedState();
            TestEqual(TEXT("Clicking the checked header clears the selection"), Plan->NumSelected(), 0);
            Plan->Select(Plan->Files[0], true);
            TestTrue(TEXT("Selecting an individual row makes the header indeterminate"), Header->GetCheckedState() == ECheckBoxState::Undetermined);
            Header->ToggleCheckedState();
            TestEqual(TEXT("Clicking a partial header selects all differences"), Plan->NumSelected(), Plan->NumSelectable());
        }
        FlushRenderingCommands();
        TArray<FColor> Pixels; FIntVector Size = FIntVector::ZeroValue;
        bCaptured = FSlateApplication::Get().TakeScreenshot(Modal.ToSharedRef(), Pixels, Size);
        if (bCaptured)
        {
            TArray64<uint8> Png;
            FImageUtils::PNGCompressImageArray(Size.X, Size.Y, Pixels, Png);
            bCaptured = FFileHelper::SaveArrayToFile(Png, *(Root / TEXT("FileReview.png")));
        }
        Plan->SelectAll(false);
        Modal->RequestDestroyWindow();
    });
    const bool bAccepted = ReviewPublishFiles(Plan,
        TEXT("静态网格体：TXingChuanSongDai\n项目：BenBen　类型：StaticMesh\n目标：测试目录"), Parent);
    FSlateApplication::Get().GetOnModalLoopTickEvent().Remove(Driver);
    TestFalse(TEXT("Closing the actual review window cancels overwrite approval"), bAccepted);
    TestEqual(TEXT("The modal starts with no default selections"), Plan->NumSelected(), 0);
    TestTrue(TEXT("Actual file difference window renders and can be captured"), bCaptured);
    Parent->RequestDestroyWindow();
    FSlateApplication::Get().Tick();
    return true;
}
#endif
