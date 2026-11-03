#include "SCGToolsPublisherBatchWindow.h"

#include "AssetThumbnail.h"
#include "CGToolsPublisherAssetFolder.h"
#include "Containers/Ticker.h"
#include "Framework/Application/SlateApplication.h"
#include "Misc/MessageDialog.h"
#include "Misc/Paths.h"
#include "SCGToolsAnimationPublisherWindow.h"
#include "SCGToolsPublisherWindow.h"
#include "SCGToolsVfxPublisherWindow.h"
#include "Styling/AppStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CGToolsPublisherBatchWindow"

TArray<TArray<int32>> CGToolsPublisher::MakePublishGroups(const TArray<FAssetData>& Assets,
    const FString& AssetsFolder, const FString& ScenesFolder)
{
    TArray<TArray<int32>> Groups;
    const ECGToolsPublisherKind Kind = GetSelectionKind(Assets);
    if (Kind == ECGToolsPublisherKind::None) { return Groups; }
    TMap<FString, int32> Owners;
    for (int32 Index = 0; Index < Assets.Num(); ++Index)
    {
        FString Type, Folder, Name, Error;
        const FString Package = Assets[Index].PackageName.ToString();
        const bool bMeshFolder = Kind == ECGToolsPublisherKind::StaticMesh
            ? ResolveStaticAssetFolder(Package, AssetsFolder, ScenesFolder, Type, Folder, Name, Error)
            : Kind == ECGToolsPublisherKind::SkeletalMesh
                && ResolveSkeletalAssetFolder(Package, AssetsFolder, Type, Folder, Name, Error);
        const FString Key = (bMeshFolder ? Folder : Assets[Index].GetSoftObjectPath().ToString()).ToLower();
        if (const int32* Existing = Owners.Find(Key)) { Groups[*Existing].Add(Index); }
        else { Owners.Add(Key, Groups.Num()); Groups.Add({ Index }); }
    }
    return Groups;
}

int32 CGToolsPublisher::FindFolderRepresentative(const TArray<FAssetData>& Assets, const TArray<int32>& Members,
    const FString& AssetsFolder, const FString& ScenesFolder)
{
    if (Members.IsEmpty()) { return INDEX_NONE; }
    FString Type, Folder, Name, Error;
    const FAssetData& First = Assets[Members[0]];
    const ECGToolsPublisherKind Kind = GetSelectionKind({ First });
    const bool bResolved = Kind == ECGToolsPublisherKind::StaticMesh
        ? ResolveStaticAssetFolder(First.PackageName.ToString(), AssetsFolder, ScenesFolder, Type, Folder, Name, Error)
        : Kind == ECGToolsPublisherKind::SkeletalMesh
            && ResolveSkeletalAssetFolder(First.PackageName.ToString(), AssetsFolder, Type, Folder, Name, Error);
    if (bResolved)
    {
        for (int32 Index : Members)
        { if (Assets[Index].AssetName.ToString().Equals(Name, ESearchCase::IgnoreCase)) { return Index; } }
    }
    return Members[0];
}

namespace
{
    bool SameSettings(const FCGToolsPublisherSharedSettings& A, const FCGToolsPublisherSharedSettings& B)
    {
        return A.Project == B.Project && A.Type == B.Type && A.Directory == B.Directory
            && A.bIcon == B.bIcon && A.bFbx == B.bFbx && A.bTextures == B.bTextures && A.bNotifyMaya == B.bNotifyMaya;
    }
}

void SCGToolsPublisherBatchWindow::Construct(const FArguments& InArgs)
{
    DialogState = InArgs._DialogState.IsValid() ? InArgs._DialogState : MakeShared<FCGToolsPublisherDialogState>(1, InArgs._Assets.Num());
    PanelFactory = InArgs._PanelFactory;
    ConfirmBatch = InArgs._ConfirmBatch;
    FCGToolsPublisherConfig Config;
    const ECGToolsPublisherKind Kind = CGToolsPublisher::GetSelectionKind(InArgs._Assets);
    if (!PanelFactory && (Kind == ECGToolsPublisherKind::StaticMesh || Kind == ECGToolsPublisherKind::SkeletalMesh))
    {
        Config = SCGToolsPublisherWindow::LoadConfig();
    }
    for (const FAssetData& Asset : InArgs._Assets)
    {
        TSharedPtr<FItem> Item = MakeShared<FItem>();
        Item->Asset = Asset;
        Items.Add(Item);
    }
    for (TArray<int32>& Members : CGToolsPublisher::MakePublishGroups(InArgs._Assets, Config.AssetsFolder, Config.ScenesFolder))
    {
        const int32 GroupIndex = Groups.Num();
        FGroup& Group = Groups.AddDefaulted_GetRef();
        Group.Members = MoveTemp(Members);
        Group.Representative = CGToolsPublisher::FindFolderRepresentative(InArgs._Assets, Group.Members, Config.AssetsFolder, Config.ScenesFolder);
        for (int32 Index : Group.Members) { Items[Index]->Group = GroupIndex; }
    }
    ThumbnailPool = MakeShared<FAssetThumbnailPool>(32);
    Status = FString::Printf(TEXT("已选择 %d 个资产，共 %d 个发布项"), Items.Num(), Groups.Num());
    ChildSlot
    [
        SNew(SBorder).Padding(12)
        [
            SNew(SVerticalBox)
            + SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
            [ SNew(STextBlock).Text(LOCTEXT("SharedSettings", "项目、类型和发布选项应用于全部资产；点击左侧资产可分别调整名称或截图。")) ]
            + SVerticalBox::Slot().FillHeight(1)
            [
                SNew(SSplitter)
                + SSplitter::Slot().Value(0.27f).MinSize(240)
                [
                    SAssignNew(AssetList, SListView<TSharedPtr<FItem>>)
                    .ListItemsSource(&Items).SelectionMode(ESelectionMode::Single)
                    .OnGenerateRow(this, &SCGToolsPublisherBatchWindow::GenerateRow)
                    .OnSelectionChanged(this, &SCGToolsPublisherBatchWindow::SelectItem)
                    .IsEnabled_Lambda([this]() { return !bRunning; })
                ]
                + SSplitter::Slot().Value(0.73f).MinSize(680)
                [
                    SNew(SVerticalBox)
                    + SVerticalBox::Slot().AutoHeight().Padding(10, 0, 0, 4)
                    [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(GetGroupDescription()); }).AutoWrapText(true) ]
                    + SVerticalBox::Slot().FillHeight(1)
                    [ SAssignNew(DetailBox, SBox).IsEnabled_Lambda([this]() { return !bRunning; }) ]
                    + SVerticalBox::Slot().AutoHeight().Padding(12, 6)
                    [
                        SNew(SBox).MaxDesiredHeight(170)
                        [ SNew(SScrollBox) + SScrollBox::Slot()
                            [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(SelectedItem.IsValid() ? SelectedItem->Detail : FString()); }).AutoWrapText(true) ] ]
                    ]
                ]
            ]
            + SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
            [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(Status); }).AutoWrapText(true) ]
            + SVerticalBox::Slot().AutoHeight()
            [ SNew(SProgressBar).Percent_Lambda([this]() { return Work.IsEmpty() ? 0.0f : static_cast<float>(Next) / Work.Num(); }) ]
            + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0, 10, 0, 0)
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 10, 0)
                [ SNew(SButton).Text_Lambda([this]() { return bRunning ? LOCTEXT("Stop", "停止后续发布") : LOCTEXT("Close", "关闭"); }).OnClicked(this, &SCGToolsPublisherBatchWindow::OnStopOrClose) ]
                + SHorizontalBox::Slot().AutoWidth()
                [ SNew(SButton).ButtonStyle(FAppStyle::Get(), "PrimaryButton").Text(LOCTEXT("PublishAll", "批量发布"))
                    .IsEnabled_Lambda([this]() { return !bRunning && !Items.IsEmpty(); }).OnClicked(this, &SCGToolsPublisherBatchWindow::OnStart) ]
            ]
        ]
    ];
    if (!Items.IsEmpty()) { AssetList->SetSelection(Items[0]); }
}

SCGToolsPublisherBatchWindow::~SCGToolsPublisherBatchWindow()
{
    FTSTicker::GetCoreTicker().RemoveTicker(Ticker);
}

FCGToolsPublisherPanelHandle& SCGToolsPublisherBatchWindow::GetPanel(int32 Index)
{
    FCGToolsPublisherPanelHandle& Handle = Items[Index]->Handle;
    if (!Handle.Panel.IsValid())
    {
        if (PanelFactory) { Handle = PanelFactory(Items[Index]->Asset); }
        else
        {
            Handle.State = MakeShared<FCGToolsPublisherDialogState>();
            Handle.State->bEmbedded = true;
            const ECGToolsPublisherKind Kind = CGToolsPublisher::GetSelectionKind({ Items[Index]->Asset });
            if (Kind == ECGToolsPublisherKind::Animation)
            {
                const TSharedRef<SCGToolsAnimationPublisherWindow> Panel = SNew(SCGToolsAnimationPublisherWindow).AssetData(Items[Index]->Asset).DialogState(Handle.State);
                Handle.Panel = Panel; Handle.Widget = Panel;
            }
            else if (Kind == ECGToolsPublisherKind::Vfx)
            {
                const TSharedRef<SCGToolsVfxPublisherWindow> Panel = SNew(SCGToolsVfxPublisherWindow).AssetData(Items[Index]->Asset).DialogState(Handle.State);
                Handle.Panel = Panel; Handle.Widget = Panel;
            }
            else
            {
                const TSharedRef<SCGToolsPublisherWindow> Panel = SNew(SCGToolsPublisherWindow).AssetData(Items[Index]->Asset).DialogState(Handle.State);
                Handle.Panel = Panel; Handle.Widget = Panel;
            }
        }
    }
    return Handle;
}

void SCGToolsPublisherBatchWindow::SelectItem(TSharedPtr<FItem> Item, ESelectInfo::Type)
{
    if (!Item.IsValid() || bRunning) { return; }
    if (SelectedItem.IsValid())
    {
        SharedSettings = SelectedItem->Handle.Panel->GetSharedSettings();
        Groups[SelectedItem->Group].RecordLabel = SelectedItem->Handle.Panel->GetRecordLabel();
    }
    SelectedItem = Item;
    FCGToolsPublisherPanelHandle& Handle = GetPanel(Items.IndexOfByKey(Item));
    Handle.Panel->ApplySharedSettings(SharedSettings);
    Handle.Panel->SetRecordLabel(Groups[Item->Group].RecordLabel);
    DetailBox->SetContent(Handle.Widget.ToSharedRef());
}

TSharedRef<ITableRow> SCGToolsPublisherBatchWindow::GenerateRow(TSharedPtr<FItem> Item, const TSharedRef<STableViewBase>& Owner)
{
    Item->Thumbnail = MakeShared<FAssetThumbnail>(Item->Asset, 48, 48, ThumbnailPool);
    FAssetThumbnailConfig ThumbnailConfig;
    // Keep UE's class icon visible until the pooled thumbnail is rendered.
    ThumbnailConfig.bAllowFadeIn = true;
    ThumbnailConfig.bAllowRealTimeOnHovered = false;
    ThumbnailConfig.ThumbnailLabel = EThumbnailLabel::NoLabel;
    return SNew(STableRow<TSharedPtr<FItem>>, Owner).Padding(6)
    [
        SNew(SHorizontalBox)
        + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
        [ SNew(SBox).WidthOverride(48).HeightOverride(48) [ Item->Thumbnail->MakeThumbnailWidget(ThumbnailConfig) ] ]
        + SHorizontalBox::Slot().FillWidth(1)
        [
            SNew(SVerticalBox)
            + SVerticalBox::Slot().AutoHeight()
            [ SNew(STextBlock).Text(FText::FromName(Item->Asset.AssetName)).ToolTipText(FText::FromString(Item->Asset.PackageName.ToString())).AutoWrapText(true) ]
            + SVerticalBox::Slot().AutoHeight().Padding(0, 4)
            [ SNew(STextBlock).Text_Lambda([this, Item]() { return GetResultText(Item); }).ColorAndOpacity_Lambda([this, Item]() { return GetResultColor(Item); }) ]
        ]
    ];
}

FText SCGToolsPublisherBatchWindow::GetResultText(const TSharedPtr<FItem>& Item) const
{
    switch (Item->Result)
    {
    case EResult::Checking: return LOCTEXT("Checking", "检查中");
    case EResult::Ready: return LOCTEXT("Ready", "准备发布");
    case EResult::Publishing: return LOCTEXT("Publishing", "发布中");
    case EResult::Succeeded: return LOCTEXT("Succeeded", "发布成功");
    case EResult::Warning: return LOCTEXT("Warning", "已发布，有提示");
    case EResult::Failed: return LOCTEXT("Failed", "未完成，点击查看原因");
    default: return LOCTEXT("Waiting", "待发布");
    }
}

FSlateColor SCGToolsPublisherBatchWindow::GetResultColor(const TSharedPtr<FItem>& Item) const
{
    switch (Item->Result)
    {
    case EResult::Failed: return FLinearColor(1.0f, 0.25f, 0.2f);
    case EResult::Warning: return FLinearColor(1.0f, 0.7f, 0.15f);
    case EResult::Succeeded: return FLinearColor(0.25f, 0.85f, 0.4f);
    case EResult::Publishing: case EResult::Checking: case EResult::Ready: return FLinearColor(0.3f, 0.7f, 1.0f);
    default: return FSlateColor::UseSubduedForeground();
    }
}

FString SCGToolsPublisherBatchWindow::GetGroupDescription() const
{
    if (!SelectedItem.IsValid()) { return FString(); }
    const FGroup& Group = Groups[SelectedItem->Group];
    return Group.Members.Num() > 1
        ? FString::Printf(TEXT("%d 个模型各自生成 FBX/Icon，UE 包合并发布；中文名共用。文件夹名的 FBX/Icon 使用：%s"), Group.Members.Num(), *Items[Group.Representative]->Asset.AssetName.ToString())
        : FString();
}

void SCGToolsPublisherBatchWindow::SetGroupResult(int32 Index, EResult Result, const FString& Detail)
{
    for (int32 Member : Groups[Index].Members) { Items[Member]->Result = Result; Items[Member]->Detail = Detail; }
}

FReply SCGToolsPublisherBatchWindow::OnStart()
{
    if (bRunning || !SelectedItem.IsValid()) { return FReply::Handled(); }
    SharedSettings = SelectedItem->Handle.Panel->GetSharedSettings();
    Groups[SelectedItem->Group].RecordLabel = SelectedItem->Handle.Panel->GetRecordLabel();
    if (!SameSettings(SharedSettings, LastRunSettings)) { for (FGroup& Group : Groups) { Group.bCompleted = false; } }
    LastRunSettings = SharedSettings;
    Work.Reset(); Destinations.Reset(); Next = 0; NextMember = 0;
    for (int32 Index = 0; Index < Groups.Num(); ++Index)
    {
        if (Groups[Index].bCompleted)
        {
            for (int32 Member : Groups[Index].Members)
            {
                ICGToolsPublisherPanel& Panel = *GetPanel(Member).Panel;
                Panel.SetRecordLabel(Groups[Index].RecordLabel);
                if (Panel.GetPerAssetSettingsKey() != Items[Member]->PublishedSettingsKey)
                { Groups[Index].bCompleted = false; }
            }
        }
        if (!Groups[Index].bCompleted)
        { Work.Add(Index); Groups[Index].ValidationError.Reset(); SetGroupResult(Index, EResult::Waiting, FString()); }
        else { Destinations.Add(Groups[Index].Destination.Replace(TEXT("\\"), TEXT("/")).ToLower(), Index); }
    }
    if (Work.IsEmpty()) { Status = TEXT("全部发布项已完成。"); return FReply::Handled(); }
    bRunning = true; bStopRequested = false; bValidationFailed = false;
    DialogState->bPublishing = true; Phase = EPhase::Validate;
    Status = TEXT("正在检查全部发布项…");
    const TWeakPtr<SCGToolsPublisherBatchWindow> WeakBatchWindow = StaticCastSharedRef<SCGToolsPublisherBatchWindow>(AsShared());
    Ticker = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([WeakBatchWindow](float Delta)
    {
        const TSharedPtr<SCGToolsPublisherBatchWindow> Self = WeakBatchWindow.Pin();
        return Self.IsValid() && Self->Step(Delta);
    }));
    return FReply::Handled();
}

bool SCGToolsPublisherBatchWindow::Step(float)
{
    if (!bRunning) { return false; }
    if (bInStep) { return true; }
    TGuardValue<bool> Guard(bInStep, true);
    if (bStopRequested || IsEngineExitRequested()) { Finish(TEXT("已停止；已完成的发布结果保留，剩余项尚未发布。")); return false; }
    if (Phase == EPhase::Validate && Next < Work.Num())
    {
        const int32 Index = Work[Next];
        FGroup& Group = Groups[Index];
        SetGroupResult(Index, EResult::Checking, FString());
        const int32 Member = Group.Members[NextMember++];
        FCGToolsPublisherPanelHandle& Handle = GetPanel(Member);
        Handle.Panel->ApplySharedSettings(SharedSettings);
        Handle.Panel->SetRecordLabel(Group.RecordLabel);
        FString Error, Destination;
        if (!Handle.Panel->ValidateBatch(Destination, Error))
        { Group.ValidationError += Items[Member]->Asset.AssetName.ToString() + TEXT("：") + Error + TEXT("\n"); }
        if (NextMember == 1) { Group.Destination = Destination; }
        else if (!Destination.IsEmpty() && !Destination.Equals(Group.Destination, ESearchCase::IgnoreCase))
        { Group.ValidationError += TEXT("同一资产文件夹的发布目录不一致。\n"); }
        for (int32 Earlier = 0; Earlier < NextMember - 1; ++Earlier)
        {
            if (Items[Group.Members[Earlier]]->Asset.AssetName == Items[Member]->Asset.AssetName)
            { Group.ValidationError += TEXT("模型重名，FBX/Icon 会覆盖，请先修改模型名：") + Items[Member]->Asset.AssetName.ToString() + TEXT("\n"); }
        }
        if (NextMember < Group.Members.Num()) { return true; }
        if (!Group.ValidationError.IsEmpty())
        { bValidationFailed = true; SetGroupResult(Index, EResult::Failed, Group.ValidationError); }
        else
        {
            FString Key = Group.Destination.Replace(TEXT("\\"), TEXT("/"));
            FPaths::CollapseRelativeDirectories(Key); Key.ToLowerInline();
            if (const int32* Existing = Destinations.Find(Key))
            {
                bValidationFailed = true;
                Error = TEXT("所选资产的发布目标重复，请调整名称或类型后重试：\n") + Group.Destination;
                SetGroupResult(Index, EResult::Failed, Error); SetGroupResult(*Existing, EResult::Failed, Error);
            }
            else { Destinations.Add(Key, Index); SetGroupResult(Index, EResult::Ready, TEXT("发布目标：\n") + Group.Destination); }
        }
        ++Next; NextMember = 0;
        Status = FString::Printf(TEXT("正在检查发布项 %d / %d"), Next, Work.Num());
        return true;
    }
    if (Phase == EPhase::Validate)
    {
        if (bValidationFailed) { Finish(TEXT("校验未通过，尚未发布。点击未完成项查看原因，修改后再次批量发布。")); return false; }
        FString Confirmation = FString::Printf(TEXT("是否批量发布 %d 个发布项（所选共 %d 个资产）？\n\n项目：%s\n类型：%s\n"), Work.Num(), Items.Num(), *SharedSettings.Project, *SharedSettings.Type);
        if (!SharedSettings.Directory.IsEmpty()) { Confirmation += TEXT("目标目录：") + SharedSettings.Directory + TEXT("\n"); }
        Confirmation += TEXT("\n同名内容将按原发布规则备份并覆盖；源资产位置保留。\n每个所选模型分别生成 FBX/Icon；同文件夹只迁移一次 UE 包。\n动画始终尝试生成 .ma，反求失败仍发布 .uasset 和 .fbx。\n\n");
        for (int32 Index : Work)
        {
            Confirmation += Items[Groups[Index].Representative]->Asset.AssetName.ToString() + TEXT(" → ") + Groups[Index].Destination + TEXT("\n");
        }
        const bool bConfirmed = ConfirmBatch ? ConfirmBatch(Confirmation)
            : FMessageDialog::Open(EAppMsgType::YesNo, FText::FromString(Confirmation), LOCTEXT("ConfirmAll", "确认批量发布")) == EAppReturnType::Yes;
        if (!bConfirmed) { Finish(TEXT("已取消，本次尚未发布。")); return false; }
        Phase = EPhase::Publish; Next = 0;
        return true;
    }
    if (Next < Work.Num())
    {
        const int32 Index = Work[Next];
        FGroup& Group = Groups[Index];
        const TSharedPtr<FItem> Item = Items[Group.Representative];
        Status = FString::Printf(TEXT("正在发布 %d / %d：%s"), Next + 1, Work.Num(), *Item->Asset.AssetName.ToString());
        SetGroupResult(Index, EResult::Publishing, Status);
        AssetList->RequestScrollIntoView(Item);
        FCGToolsPublisherPanelHandle& Handle = GetPanel(Group.Representative);
        TArray<TSharedPtr<ICGToolsPublisherPanel>> Panels;
        for (int32 Member : Group.Members) { Panels.Add(GetPanel(Member).Panel); }
        Handle.Panel->SetGroupPanels(Panels);
        Handle.State->Result = ECGToolsPublisherDialogResult::Cancelled;
        Handle.State->Error.Reset(); Handle.State->Completion.Reset(); Handle.State->bWarning = false;
        TGuardValue<bool> ExecutionGuard(Handle.State->bBatchExecution, true);
        Handle.Panel->PublishBatch();
        Group.bCompleted = Handle.State->Result == ECGToolsPublisherDialogResult::Published;
        if (Group.bCompleted)
        {
            for (int32 Member : Group.Members)
            { Items[Member]->PublishedSettingsKey = GetPanel(Member).Panel->GetPerAssetSettingsKey(); }
        }
        SetGroupResult(Index, Group.bCompleted ? (Handle.State->bWarning ? EResult::Warning : EResult::Succeeded) : EResult::Failed,
            Group.bCompleted ? Handle.State->Completion : Handle.State->Error.IsEmpty() ? TEXT("发布已取消或未完成，请检查 Output Log 后重试。") : Handle.State->Error);
        UE_LOG(LogTemp, Display, TEXT("CGTools batch: %s\n%s"), *Item->Asset.GetSoftObjectPath().ToString(), *Item->Detail);
        ++Next;
        return true;
    }
    int32 Completed = 0;
    for (const FGroup& Group : Groups) { Completed += Group.bCompleted ? 1 : 0; }
    Finish(FString::Printf(TEXT("批量发布结束：完成 %d 项，未完成 %d 项。点击资产查看详细结果；再次发布仅处理未完成项。"), Completed, Groups.Num() - Completed));
    return false;
}

void SCGToolsPublisherBatchWindow::Finish(const FString& Message)
{
    Status = Message; Phase = EPhase::Idle; bRunning = false; DialogState->bPublishing = false;
    FTSTicker::GetCoreTicker().RemoveTicker(Ticker);
    Ticker.Reset();
}

FReply SCGToolsPublisherBatchWindow::OnStopOrClose()
{
    if (bRunning) { bStopRequested = true; Status = TEXT("将在当前发布结束后停止，保留已完成结果…"); }
    else if (const TSharedPtr<SWindow> Window = FSlateApplication::Get().FindWidgetWindow(AsShared()))
    { Window->RequestDestroyWindow(); }
    return FReply::Handled();
}

#undef LOCTEXT_NAMESPACE
