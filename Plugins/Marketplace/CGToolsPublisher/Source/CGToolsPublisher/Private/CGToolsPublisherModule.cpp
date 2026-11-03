#include "CoreMinimal.h"

#include "Animation/AnimSequence.h"
#include "AssetRegistry/AssetData.h"
#include "Brushes/SlateImageBrush.h"
#include "CGToolsPublisherBatch.h"
#include "ContentBrowserMenuContexts.h"
#include "Containers/Ticker.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Framework/Application/SlateApplication.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Interfaces/IMainFrameModule.h"
#include "Interfaces/IPluginManager.h"
#include "Modules/ModuleManager.h"
#include "SCGToolsPublisherWindow.h"
#include "SCGToolsPublisherBatchWindow.h"
#include "SCGToolsAnimationPublisherWindow.h"
#include "SCGToolsVfxPublisherWindow.h"
#include "Styling/AppStyle.h"
#include "Styling/SlateStyle.h"
#include "Styling/SlateStyleRegistry.h"
#include "ToolMenus.h"
#include "Widgets/SWindow.h"

#define LOCTEXT_NAMESPACE "CGToolsPublisherModule"

class FCGToolsPublisherModule : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        RegisterPublisherStyle();
        UToolMenus::RegisterStartupCallback(
            FSimpleMulticastDelegate::FDelegate::CreateRaw(
                this,
                &FCGToolsPublisherModule::RegisterContentBrowserMenu
            )
        );
    }

    virtual void ShutdownModule() override
    {
        bShuttingDown = true;
        FTSTicker::GetCoreTicker().RemoveTicker(NextDialogTicker);
        NextDialogTicker.Reset();
        if (ActiveBatch.IsValid())
        {
            ActiveBatch->Cancel();
            ActiveBatch.Reset();
        }
        if (const TSharedPtr<SWindow> Window = ActivePublisherWindow.Pin())
        {
            Window->SetOnWindowClosed(FOnWindowClosed());
            Window->SetRequestDestroyWindowOverride(FRequestDestroyWindowOverride());
            if (FSlateApplication::IsInitialized())
            {
                FSlateApplication::Get().RequestDestroyWindow(Window.ToSharedRef());
            }
        }
        ActivePublisherWindow.Reset();
        UToolMenus::UnRegisterStartupCallback(this);
        UToolMenus::UnregisterOwner(this);
        if (PublisherStyle.IsValid())
        {
            FSlateStyleRegistry::UnRegisterSlateStyle(*PublisherStyle);
            PublisherStyle.Reset();
        }
    }

private:
    TSharedPtr<FSlateStyleSet> PublisherStyle;
    TSharedPtr<FCGToolsPublisherBatch> ActiveBatch;
    TWeakPtr<SWindow> ActivePublisherWindow;
    FTSTicker::FDelegateHandle NextDialogTicker;
    bool bShuttingDown = false;

    void RegisterPublisherStyle()
    {
        const TSharedPtr<IPlugin> Plugin =
            IPluginManager::Get().FindPlugin(TEXT("CGToolsPublisher"));
        if (!Plugin.IsValid())
        {
            return;
        }

        PublisherStyle = MakeShared<FSlateStyleSet>(TEXT("CGToolsPublisherStyle"));
        PublisherStyle->SetContentRoot(Plugin->GetBaseDir() / TEXT("Resources"));
        PublisherStyle->Set(
            TEXT("CGToolsPublisher.Publish"),
            new FSlateImageBrush(
                PublisherStyle->RootToContentDir(TEXT("pub_upload"), TEXT(".png")),
                FVector2D(16.0f, 16.0f)
            )
        );
        FSlateStyleRegistry::RegisterSlateStyle(*PublisherStyle);
    }

    void RegisterContentBrowserMenu()
    {
        FToolMenuOwnerScoped OwnerScoped(this);
        UToolMenu* Menu =
            UToolMenus::Get()->ExtendMenu(TEXT("ContentBrowser.AssetContextMenu"));
        Menu->AddDynamicSection(
            TEXT("CGToolsPublisher"),
            FNewToolMenuDelegate::CreateRaw(
                this,
                &FCGToolsPublisherModule::AddPublisherMenu
            ),
            FToolMenuInsert(TEXT("GetAssetActions"), EToolMenuInsertType::After)
        );
    }

    void AddPublisherMenu(UToolMenu* Menu)
    {
        const UContentBrowserAssetContextMenuContext* Context =
            Menu->FindContext<UContentBrowserAssetContextMenuContext>();
        if (!Context || Context->SelectedAssets.IsEmpty())
        {
            return;
        }

        // A separate ToolMenus section is rendered after legacy asset-action
        // extenders, so their entries cannot appear beneath the CGTools heading.
        FToolMenuSection& Section = Menu->AddSection(
            TEXT("CGToolsPublisher"),
            LOCTEXT("PublisherSection", "CGTools"),
            FToolMenuInsert(TEXT("GetAssetActions"), EToolMenuInsertType::After)
        );
        Section.AddSubMenu(
            TEXT("CGToolsPublisher.Publish"),
            LOCTEXT("PublishSubMenu", "发布UE资产"),
            LOCTEXT("PublishSubMenuTooltip", "把所选 UE 资产及依赖发布到 CGTools 服务器。"),
            FNewMenuDelegate::CreateRaw(
                this,
                &FCGToolsPublisherModule::PopulatePublisherSubMenu,
                Context->SelectedAssets
            ),
            false,
            PublisherStyle.IsValid()
                ? FSlateIcon(
                    PublisherStyle->GetStyleSetName(),
                    TEXT("CGToolsPublisher.Publish"),
                    TEXT("CGToolsPublisher.Publish")
                )
                : FSlateIcon(FAppStyle::GetAppStyleSetName(), "Icons.Upload")
        );
    }

    void PopulatePublisherSubMenu(FMenuBuilder& MenuBuilder, TArray<FAssetData> SelectedAssets)
    {
        const ECGToolsPublisherKind Kind = CGToolsPublisher::GetSelectionKind(SelectedAssets);
        const bool bIsStaticMesh = Kind == ECGToolsPublisherKind::StaticMesh;
        const bool bIsSkeletalMesh = Kind == ECGToolsPublisherKind::SkeletalMesh;
        const bool bIsEffect = Kind == ECGToolsPublisherKind::Vfx;
        const bool bIsAnimation = Kind == ECGToolsPublisherKind::Animation;

        // Keep every publishing command visible; Slate grays out commands that
        // do not support the current selection through their CanExecute action.
        MenuBuilder.AddMenuEntry(
            LOCTEXT("PublishStaticMesh", "静态网格体发布"),
            LOCTEXT(
                "PublishStaticMeshTooltip",
                "发布所选静态网格体、完整包依赖、Icon、FBX、Texture、项目文件及场景数据库记录。"
            ),
            FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.StaticMesh"),
            FUIAction(
                FExecuteAction::CreateRaw(
                    this,
                    &FCGToolsPublisherModule::OpenPublisherWindows,
                    SelectedAssets
                ),
                FCanExecuteAction::CreateLambda([bIsStaticMesh]()
                {
                    return bIsStaticMesh;
                })
            )
        );
        MenuBuilder.AddMenuEntry(
            LOCTEXT("PublishSkeletalMesh", "骨架网格体发布"),
            LOCTEXT(
                "PublishSkeletalMeshTooltip",
                "发布所选骨架网格体、完整包依赖、Icon、FBX、Texture、项目文件及资产数据库记录。"
            ),
            FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.SkeletalMesh"),
            FUIAction(
                FExecuteAction::CreateRaw(
                    this,
                    &FCGToolsPublisherModule::OpenPublisherWindows,
                    SelectedAssets
                ),
                FCanExecuteAction::CreateLambda([bIsSkeletalMesh]()
                {
                    return bIsSkeletalMesh;
                })
            )
        );
        MenuBuilder.AddMenuEntry(
            LOCTEXT("PublishAnimation", "动画序列发布"),
            LOCTEXT("PublishAnimationTooltip", "将所选动画序列复制为 .uasset 并导出 FBX 到项目动作库。"),
            FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.AnimSequence"),
            FUIAction(
                FExecuteAction::CreateRaw(this, &FCGToolsPublisherModule::OpenPublisherWindows, SelectedAssets),
                FCanExecuteAction::CreateLambda([bIsAnimation]() { return bIsAnimation; })
            )
        );
        MenuBuilder.AddMenuEntry(
            LOCTEXT("PublishVfx", "特效发布"),
            LOCTEXT("PublishVfxTooltip", "选择 VFX 工程目录，整理并发布 Niagara/Cascade 特效及依赖的副本，保留源资产位置。"),
            FSlateIcon(FAppStyle::GetAppStyleSetName(), "PlacementBrowser.Icons.VisualEffects"),
            FUIAction(
                FExecuteAction::CreateRaw(
                    this,
                    &FCGToolsPublisherModule::OpenPublisherWindows,
                    SelectedAssets
                ),
                FCanExecuteAction::CreateLambda([bIsEffect]() { return bIsEffect; })
            )
        );
    }

    void OpenPublisherWindows(TArray<FAssetData> SelectedAssets)
    {
        if (ActiveBatch.IsValid() && !ActiveBatch->IsFinished())
        {
            // Reopening the menu must not replace an in-progress dialog/queue.
            if (const TSharedPtr<SWindow> Window = ActivePublisherWindow.Pin())
            {
                Window->Restore();
                Window->BringToFront(true);
            }
            return;
        }
        const ECGToolsPublisherKind Kind = CGToolsPublisher::GetSelectionKind(SelectedAssets);
        if (Kind == ECGToolsPublisherKind::None)
        {
            return;
        }
        // Keep the MainFrame as parent across all items. Content Browser popup
        // windows disappear as soon as their command starts executing.
        IMainFrameModule& MainFrame =
            FModuleManager::LoadModuleChecked<IMainFrameModule>(TEXT("MainFrame"));
        TSharedPtr<SWindow> MainWindow = MainFrame.GetParentWindow();
        if (!MainWindow.IsValid())
        {
            MainWindow = FSlateApplication::Get().GetActiveTopLevelRegularWindow();
        }
        const TWeakPtr<SWindow> WeakMainWindow = MainWindow;
        ActiveBatch = CGToolsPublisher::RunBatch(MoveTemp(SelectedAssets),
            [this, Kind, WeakMainWindow](const TArray<FAssetData>& Assets, const TSharedRef<FCGToolsPublisherDialogState>& State)
        {
            const FAssetData& Asset = Assets[0];
            FText Title;
            FVector2D Size(860.0f, 570.0f);
            switch (Kind)
            {
            case ECGToolsPublisherKind::StaticMesh:
                Title = LOCTEXT("StaticMeshWindowTitle", "CGTools Publisher - 静态网格体发布");
                break;
            case ECGToolsPublisherKind::SkeletalMesh:
                Title = LOCTEXT("SkeletalMeshWindowTitle", "CGTools Publisher - 骨架网格体发布");
                break;
            case ECGToolsPublisherKind::Animation:
                Title = LOCTEXT("AnimationWindowTitle", "CGTools Publisher - 动画序列发布");
                Size = FVector2D(860.0f, 420.0f);
                break;
            case ECGToolsPublisherKind::Vfx:
                Title = LOCTEXT("VfxWindowTitle", "CGTools Publisher - 特效发布");
                Size = FVector2D(1000.0f, 560.0f);
                break;
            default:
                return;
            }
            Title = State->IsBatch()
                ? FText::Format(LOCTEXT("UnifiedBatchWindowTitle", "{0} - 批量发布（{1} 个资产）"),
                    Title, FText::AsNumber(State->Count))
                : FText::Format(LOCTEXT("AssetWindowTitle", "{0} - {1}"), Title, FText::FromName(Asset.AssetName));
            if (State->IsBatch()) { Size = FVector2D(1240.0f, 720.0f); }
            const TSharedRef<SWindow> Window = SNew(SWindow)
                .Title(Title).ClientSize(Size).SizingRule(ESizingRule::UserSized)
                .SupportsMinimize(true).SupportsMaximize(true);
            if (State->IsBatch())
            {
                Window->SetContent(SNew(SCGToolsPublisherBatchWindow).Assets(Assets).DialogState(State));
            }
            else if (Kind == ECGToolsPublisherKind::Animation)
            {
                Window->SetContent(SNew(SCGToolsAnimationPublisherWindow).AssetData(Asset).DialogState(State));
            }
            else if (Kind == ECGToolsPublisherKind::Vfx)
            {
                Window->SetContent(SNew(SCGToolsVfxPublisherWindow).AssetData(Asset).DialogState(State));
            }
            else
            {
                Window->SetContent(SNew(SCGToolsPublisherWindow).AssetData(Asset).DialogState(State));
            }
            // Publishing pumps Slate events. Do not let the titlebar close a
            // live export/upload and expose the next asset while it is running.
            Window->SetRequestDestroyWindowOverride(FRequestDestroyWindowOverride::CreateLambda(
                [State](const TSharedRef<SWindow>& ClosingWindow)
                {
                    if (!State->bPublishing)
                    {
                        FSlateApplication::Get().RequestDestroyWindow(ClosingWindow);
                    }
                }));
            Window->SetOnWindowClosed(FOnWindowClosed::CreateLambda(
                [this, State](const TSharedRef<SWindow>&)
                {
                    ActivePublisherWindow.Reset();
                    if (bShuttingDown || IsEngineExitRequested())
                    {
                        if (ActiveBatch.IsValid())
                        {
                            ActiveBatch->Cancel();
                            ActiveBatch.Reset();
                        }
                        return;
                    }
                    // Release the immutable selection after Slate finishes
                    // removing the closed native window.
                    NextDialogTicker = FTSTicker::GetCoreTicker().AddTicker(
                        FTickerDelegate::CreateLambda([this, State](float)
                        {
                            NextDialogTicker.Reset();
                            if (ActiveBatch.IsValid())
                            {
                                if (bShuttingDown || IsEngineExitRequested())
                                {
                                    ActiveBatch->Cancel();
                                }
                                else
                                {
                                    ActiveBatch->OnDialogClosed(State);
                                }
                                if (ActiveBatch->IsFinished())
                                {
                                    ActiveBatch.Reset();
                                }
                            }
                            return false;
                        }));
                }));
            ActivePublisherWindow = Window;
            if (const TSharedPtr<SWindow> Parent = WeakMainWindow.Pin())
            {
                FSlateApplication::Get().AddWindowAsNativeChild(Window, Parent.ToSharedRef());
            }
            else
            {
                FSlateApplication::Get().AddWindow(Window);
            }
        });
    }
};

IMPLEMENT_MODULE(FCGToolsPublisherModule, CGToolsPublisher)

#undef LOCTEXT_NAMESPACE
