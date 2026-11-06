#include "CGToolsPublisherFileReview.h"

#include "Async/Async.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/Paths.h"
#include "Misc/ScopedSlowTask.h"
#include "Styling/AppStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Views/SListView.h"

namespace CGToolsPublisher
{
    namespace
    {
        bool IsPublishCacheOrTemporaryFile(const FString& Filename)
        {
            const FString Name = FPaths::GetCleanFilename(Filename).ToLower();
            return Name == TEXT("thumbs.db") || Name == TEXT("ehthumbs.db") || Name == TEXT("ehthumbs_vista.db")
                || Name == TEXT("desktop.ini") || Name == TEXT(".ds_store")
                || Name.StartsWith(TEXT("._")) || Name.StartsWith(TEXT("~$"))
                || Name.EndsWith(TEXT(".tmp")) || Name.EndsWith(TEXT(".temp"));
        }

        bool Snapshot(const FString& Filename, int64& Size, FMD5Hash& Hash)
        {
            Size = IFileManager::Get().FileSize(*Filename);
            if (Size < 0) { return !IFileManager::Get().DirectoryExists(*Filename); }
            Hash = FMD5Hash::HashFile(*Filename);
            return Hash.IsValid() && IFileManager::Get().FileSize(*Filename) == Size;
        }

        bool Matches(const FString& Filename, int64 Size, const FMD5Hash& Hash)
        {
            int64 CurrentSize; FMD5Hash CurrentHash;
            return Snapshot(Filename, CurrentSize, CurrentHash) && CurrentSize == Size
                && (Size < 0 || CurrentHash == Hash);
        }

        FString PackageKey(const FString& Relative)
        {
            const FString Extension = FPaths::GetExtension(Relative).ToLower();
            return Extension == TEXT("uasset") || Extension == TEXT("umap") || Extension == TEXT("uexp")
                || Extension == TEXT("ubulk") || Extension == TEXT("uptnl")
                ? FPaths::ChangeExtension(Relative, TEXT("")).ToLower() : FString();
        }

        FText SizeText(int64 Size)
        {
            return Size < 0 ? FText::FromString(TEXT("缺失")) : FText::AsMemory(Size);
        }

        FText DifferenceText(EPublishFileDifference Difference)
        {
            switch (Difference)
            {
            case EPublishFileDifference::Conflict: return FText::FromString(TEXT("冲突"));
            case EPublishFileDifference::Added: return FText::FromString(TEXT("新增"));
            case EPublishFileDifference::Missing: return FText::FromString(TEXT("本次缺失，保留"));
            default: return FText::FromString(TEXT("一致，无需覆盖"));
            }
        }

        FSlateColor DifferenceColor(EPublishFileDifference Difference)
        {
            if (Difference == EPublishFileDifference::Conflict) { return FLinearColor(1.0f, 0.65f, 0.1f); }
            if (Difference == EPublishFileDifference::Added) { return FLinearColor(1.0f, 0.25f, 0.2f); }
            return FSlateColor::UseSubduedForeground();
        }

        class SPublishFileReview : public SCompoundWidget
        {
        public:
            SLATE_BEGIN_ARGS(SPublishFileReview) {}
                SLATE_ARGUMENT(TSharedPtr<FPublishFilePlan>, Plan)
                SLATE_ARGUMENT(FString, Label)
            SLATE_END_ARGS()

            bool bAccepted = false;
            void Construct(const FArguments& Args)
            {
                Plan = Args._Plan;
                ChildSlot
                [ SNew(SVerticalBox)
                    + SVerticalBox::Slot().AutoHeight().Padding(12)
                    [ SNew(STextBlock).Text(FText::FromString(Args._Label)).AutoWrapText(true) ]
                    + SVerticalBox::Slot().AutoHeight().Padding(12, 0, 12, 8)
                    [ SNew(STextBlock).Text(FText::FromString(TEXT("勾选要覆盖或新增的文件；未勾选的文件保留。UE 包及其配套文件一起选择。"))).AutoWrapText(true) ]
                    + SVerticalBox::Slot().AutoHeight().Padding(12, 0)
                    [ SNew(SHorizontalBox)
                        + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                        [ SNew(SBox).WidthOverride(48).Padding(FMargin(4, 0, 0, 0)).HAlign(HAlign_Left)
                            [ SNew(SCheckBox).Tag(TEXT("PublishFilesSelectAll"))
                                .ToolTipText(FText::FromString(TEXT("全选或取消全选可发布的冲突、新增文件")))
                                .IsEnabled_Lambda([this]() { return Plan->NumSelectable() > 0; })
                                .IsChecked_Lambda([this]()
                                {
                                    const int32 Selected = Plan->NumSelected();
                                    return Selected == 0 ? ECheckBoxState::Unchecked
                                        : Selected == Plan->NumSelectable() ? ECheckBoxState::Checked : ECheckBoxState::Undetermined;
                                })
                                .OnCheckStateChanged_Lambda([this](ECheckBoxState)
                                { Plan->SelectAll(Plan->NumSelected() < Plan->NumSelectable()); }) ] ]
                        + SHorizontalBox::Slot().FillWidth(1) [ SNew(STextBlock).Text(FText::FromString(TEXT("文件（相对发布目录）"))) ]
                        + SHorizontalBox::Slot().AutoWidth() [ SNew(SBox).WidthOverride(140) [ SNew(STextBlock).Text(FText::FromString(TEXT("差异"))) ] ]
                        + SHorizontalBox::Slot().AutoWidth() [ SNew(SBox).WidthOverride(110) [ SNew(STextBlock).Text(FText::FromString(TEXT("本次大小"))) ] ]
                        + SHorizontalBox::Slot().AutoWidth() [ SNew(SBox).WidthOverride(110) [ SNew(STextBlock).Text(FText::FromString(TEXT("服务器大小"))) ] ]
                    ]
                    + SVerticalBox::Slot().FillHeight(1).Padding(12, 6)
                    [ SNew(SListView<TSharedPtr<FPublishFile>>).ListItemsSource(&Plan->Files)
                        .SelectionMode(ESelectionMode::None)
                        .OnGenerateRow_Lambda([this](TSharedPtr<FPublishFile> File, const TSharedRef<STableViewBase>& Owner)
                        {
                            return SNew(STableRow<TSharedPtr<FPublishFile>>, Owner).Padding(4)
                            [ SNew(SHorizontalBox)
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                                [ SNew(SBox).WidthOverride(24) [ SNew(SCheckBox)
                                    .IsEnabled(File->CanSelect())
                                    .IsChecked_Lambda([File]() { return File->bSelected ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
                                    .OnCheckStateChanged_Lambda([this, File](ECheckBoxState State) { Plan->Select(File, State == ECheckBoxState::Checked); }) ] ]
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                                [ SNew(SBox).WidthOverride(24).HeightOverride(16)
                                    [ SNew(SImage).Image(FAppStyle::GetBrush("ClassIcon.Object")).ColorAndOpacity(DifferenceColor(File->Difference)) ] ]
                                + SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center)
                                [ SNew(STextBlock).Clipping(EWidgetClipping::ClipToBounds).Text(FText::FromString(File->Relative)).ToolTipText(FText::FromString(File->Source + TEXT("\n") + File->Target)) ]
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                                [ SNew(SBox).WidthOverride(140) [ SNew(STextBlock).Text(DifferenceText(File->Difference)).ColorAndOpacity(DifferenceColor(File->Difference)) ] ]
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                                [ SNew(SBox).WidthOverride(110) [ SNew(STextBlock).Text(SizeText(File->SourceSize)) ] ]
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                                [ SNew(SBox).WidthOverride(110) [ SNew(STextBlock).Text(SizeText(File->TargetSize)) ] ]
                            ];
                        }) ]
                    + SVerticalBox::Slot().AutoHeight().Padding(12)
                    [ SNew(SHorizontalBox)
                        + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
                        [ SNew(SButton).Text(FText::FromString(TEXT("全选"))).OnClicked_Lambda([this]()
                            { Plan->SelectAll(true); return FReply::Handled(); }) ]
                        + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 12, 0)
                        [ SNew(SButton).Text(FText::FromString(TEXT("全不选"))).OnClicked_Lambda([this]()
                            { Plan->SelectAll(false); return FReply::Handled(); }) ]
                        + SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center)
                        [ SNew(STextBlock).Text_Lambda([this]()
                            { return FText::FromString(FString::Printf(TEXT("已选 %d / %d 个可发布文件；共 %d 个文件"), Plan->NumSelected(), Plan->NumSelectable(), Plan->Files.Num())); }) ]
                        + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
                        [ SNew(SButton).ButtonStyle(FAppStyle::Get(), "PrimaryButton").Text(FText::FromString(TEXT("确定")))
                            .IsEnabled_Lambda([this]() { return Plan->NumSelected() > 0 || Plan->NumSelectable() == 0; })
                            .OnClicked_Lambda([this]() { bAccepted = true; Close(); return FReply::Handled(); }) ]
                        + SHorizontalBox::Slot().AutoWidth()
                        [ SNew(SButton).Text(FText::FromString(TEXT("取消"))).OnClicked_Lambda([this]() { Close(); return FReply::Handled(); }) ]
                    ]
                ];
            }
        private:
            TSharedPtr<FPublishFilePlan> Plan;
            void Close() { FSlateApplication::Get().FindWidgetWindow(AsShared())->RequestDestroyWindow(); }
        };
    }

    int32 FPublishFilePlan::NumSelectable() const
    {
        int32 Count = 0; for (const auto& File : Files) { Count += File->CanSelect() ? 1 : 0; } return Count;
    }

    int32 FPublishFilePlan::NumSelected() const
    {
        int32 Count = 0; for (const auto& File : Files) { Count += File->CanSelect() && File->bSelected ? 1 : 0; } return Count;
    }

    void FPublishFilePlan::Select(const TSharedPtr<FPublishFile>& Selected, bool bValue)
    {
        if (!Selected.IsValid() || !Selected->CanSelect()) { return; }
        const FString Key = PackageKey(Selected->Relative);
        for (const auto& File : Files)
        {
            if (File->CanSelect() && (File == Selected || (!Key.IsEmpty() && PackageKey(File->Relative) == Key)))
            { File->bSelected = bValue; }
        }
    }

    void FPublishFilePlan::SelectAll(bool bSelected)
    {
        for (const auto& File : Files) { File->bSelected = bSelected && File->CanSelect(); }
    }

    FPublishFilePlan BuildPublishFilePlan(const FString& Stage, const FString& Target, const TArray<FString>& Roots)
    {
        FPublishFilePlan Plan;
        TMap<FString, FString> Relatives;
        for (FString RelativeRoot : Roots)
        {
            RelativeRoot.ReplaceInline(TEXT("\\"), TEXT("/"));
            if (RelativeRoot.IsEmpty() || !FPaths::IsRelative(RelativeRoot) || RelativeRoot.Contains(TEXT("..")) || RelativeRoot.Contains(TEXT(":")))
            { Plan.Error = TEXT("无效的发布相对目录：") + RelativeRoot; return Plan; }
            for (const FString& Base : { Stage, Target })
            {
                const FString Path = FPaths::ConvertRelativePathToFull(Base / RelativeRoot);
                TArray<FString> Paths;
                if (IFileManager::Get().DirectoryExists(*Path)) { IFileManager::Get().FindFilesRecursive(Paths, *Path, TEXT("*"), true, false); }
                else if (IFileManager::Get().FileExists(*Path)) { Paths.Add(Path); }
                for (FString File : Paths)
                {
                    // Exclude OS caches and temporary files before hashing either side.
                    // Existing server files are neither listed nor changed by this publish.
                    if (IsPublishCacheOrTemporaryFile(File)) { continue; }
                    FPaths::MakePathRelativeTo(File, *(FPaths::ConvertRelativePathToFull(Base) + TEXT("/")));
                    Relatives.FindOrAdd(File.ToLower()) = File;
                }
            }
        }
        for (const auto& Pair : Relatives)
        {
            auto File = MakeShared<FPublishFile>();
            File->Relative = Pair.Value; File->Source = Stage / Pair.Value; File->Target = Target / Pair.Value;
            if (!Snapshot(File->Source, File->SourceSize, File->SourceHash) || !Snapshot(File->Target, File->TargetSize, File->TargetHash))
            { Plan.Error = TEXT("无法读取发布文件或文件正在变化：\n") + File->Source + TEXT("\n") + File->Target; return Plan; }
            File->Difference = File->SourceSize < 0 ? EPublishFileDifference::Missing : File->TargetSize < 0 ? EPublishFileDifference::Added
                : File->SourceSize == File->TargetSize && File->SourceHash == File->TargetHash ? EPublishFileDifference::Identical : EPublishFileDifference::Conflict;
            Plan.Files.Add(File);
        }
        Plan.Files.Sort([](const auto& A, const auto& B)
        { return A->Difference != B->Difference ? A->Difference < B->Difference : A->Relative < B->Relative; });
        if (!Plan.Files.ContainsByPredicate([](const auto& File) { return File->SourceSize >= 0; }))
        { Plan.Error = TEXT("没有找到本次可发布文件。"); }
        return Plan;
    }

    FPublishFilePlan PreparePublishFilePlan(const FString& Stage, const FString& Target, const TArray<FString>& Roots)
    {
        FScopedSlowTask Progress(1, FText::FromString(TEXT("正在比较本次发布和服务器文件…")));
        Progress.MakeDialog(false, false);
        auto Future = Async(EAsyncExecution::ThreadPool, [Stage, Target, Roots]() { return BuildPublishFilePlan(Stage, Target, Roots); });
        while (!Future.IsReady()) { Progress.TickProgress(); FPlatformProcess::Sleep(0.03f); }
        return Future.Get();
    }

    bool ReviewPublishFiles(const TSharedRef<FPublishFilePlan>& Plan, const FString& Label, const TSharedPtr<SWindow>& Parent)
    {
        const TSharedRef<SPublishFileReview> Review = SNew(SPublishFileReview).Plan(Plan).Label(Label);
        const TSharedRef<SWindow> Window = SNew(SWindow).Title(FText::FromString(TEXT("发布文件差异 - 勾选覆盖或新增")))
            .ClientSize(FVector2D(1180, 650)).SupportsMinimize(false).SupportsMaximize(true) [ Review ];
        FSlateApplication::Get().AddModalWindow(Window, Parent);
        return Review->bAccepted;
    }

    FPublishFileResult CommitPublishFiles(const FPublishFilePlan& Plan, const FString& BackupBase)
    {
        FPublishFileResult Result;
        if (!Plan.Error.IsEmpty()) { Result.Error = Plan.Error; return Result; }
        Result.Skipped = Plan.NumSelectable() - Plan.NumSelected();
        Result.bComplete = Result.Skipped == 0;
        IFileManager& Files = IFileManager::Get();
        TArray<TSharedPtr<FPublishFile>> Selected;
        for (const auto& File : Plan.Files)
        {
            if (File->SourceSize < 0) { continue; }
            if (!Matches(File->Source, File->SourceSize, File->SourceHash) || !Matches(File->Target, File->TargetSize, File->TargetHash))
            { Result.Error = TEXT("文件在确认期间已变化，尚未写入服务器，请重新比较：\n") + File->Relative; return Result; }
            if (File->CanSelect() && File->bSelected) { Selected.Add(File); }
        }
        if (Selected.IsEmpty() && Result.Skipped > 0) { Result.Error = TEXT("没有勾选文件，未修改服务器。"); return Result; }
        for (const auto& File : Selected)
        {
            if (File->TargetSize < 0) { continue; }
            if (Result.History.IsEmpty())
            { Result.History = BackupBase / (FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S")) + TEXT("_") + FGuid::NewGuid().ToString(EGuidFormats::Digits).Left(8)); }
            const FString Backup = Result.History / File->Relative;
            if (!Files.MakeDirectory(*FPaths::GetPath(Backup), true) || Files.Copy(*Backup, *File->Target, false, false) != COPY_OK
                || !Matches(Backup, File->TargetSize, File->TargetHash))
            { Result.Error = TEXT("备份失败，未修改服务器文件：\n") + File->Target + TEXT("\n备份：") + Backup; return Result; }
        }
        TArray<TSharedPtr<FPublishFile>> Applied;
        for (const auto& File : Selected)
        {
            if (!Matches(File->Source, File->SourceSize, File->SourceHash) || !Matches(File->Target, File->TargetSize, File->TargetHash))
            { Result.Error = TEXT("提交前文件发生变化：\n") + File->Relative; break; }
            const FString Temporary = File->Target + TEXT(".CGToolsPublish_") + FGuid::NewGuid().ToString(EGuidFormats::Digits) + TEXT(".tmp");
            if (!Files.MakeDirectory(*FPaths::GetPath(Temporary), true) || Files.Copy(*Temporary, *File->Source, false, false) != COPY_OK
                || !Matches(Temporary, File->SourceSize, File->SourceHash))
            { Files.Delete(*Temporary, false, false); Result.Error = TEXT("暂存上传或校验失败：\n") + File->Target; break; }
            if (!Matches(File->Target, File->TargetSize, File->TargetHash))
            { Files.Delete(*Temporary, false, false); Result.Error = TEXT("上传期间服务器文件发生变化：\n") + File->Target; break; }
            Applied.Add(File);
            const bool bMoved = Files.Move(*File->Target, *Temporary, File->TargetSize >= 0, false, false, true);
            Files.Delete(*Temporary, false, false);
            if (!bMoved || !Matches(File->Target, File->SourceSize, File->SourceHash))
            { Result.Error = TEXT("写入或校验失败：\n") + File->Target; break; }
            ++Result.Copied;
        }
        if (!Result.Error.IsEmpty())
        {
            for (int32 Index = Applied.Num() - 1; Index >= 0; --Index)
            {
                const auto& File = Applied[Index];
                // Preserve an independent concurrent change rather than overwriting it during recovery.
                const bool bOurs = Matches(File->Target, File->SourceSize, File->SourceHash);
                const bool bOriginal = Matches(File->Target, File->TargetSize, File->TargetHash);
                const bool bAbsent = Files.FileSize(*File->Target) < 0;
                if (bOriginal) { continue; }
                if ((!bOurs && !bAbsent) || !(File->TargetSize < 0 ? Files.Delete(*File->Target, false, false)
                    : Files.Copy(*File->Target, *(Result.History / File->Relative), true, false) == COPY_OK))
                { Result.Error += TEXT("\n恢复未完成，请检查文件及备份：") + File->Target; }
            }
            Result.Error += TEXT("\n本次备份：") + Result.History;
            return Result;
        }
        Result.bSucceeded = true;
        return Result;
    }

    bool ReviewAndCommitPublishFiles(const FString& Stage, const FString& Target, const TArray<FString>& Roots,
        const FString& BackupBase, const FString& Label, const TSharedPtr<SWindow>& Parent, FPublishFileResult& OutResult)
    {
        const auto Plan = MakeShared<FPublishFilePlan>(PreparePublishFilePlan(Stage, Target, Roots));
        if (!Plan->Error.IsEmpty()) { OutResult.Error = Plan->Error; return false; }
        if (!ReviewPublishFiles(Plan, Label, Parent)) { return false; }
        FScopedSlowTask Progress(1, FText::FromString(TEXT("正在备份并上传勾选的文件…")));
        Progress.MakeDialog(false, false);
        auto Future = Async(EAsyncExecution::ThreadPool, [Plan, BackupBase]() { return CommitPublishFiles(*Plan, BackupBase); });
        while (!Future.IsReady()) { Progress.TickProgress(); FPlatformProcess::Sleep(0.03f); }
        OutResult = Future.Get();
        return OutResult.bSucceeded;
    }
}
