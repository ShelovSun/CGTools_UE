#include "AssetRegistryRepairLibrary.h"

#include "ContentBrowserModule.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Modules/ModuleManager.h"

#define LOCTEXT_NAMESPACE "AssetRegistryRepair"

namespace
{
    static constexpr int32 RepairDefaultModifiedWithinMinutes = 0;
    static constexpr bool RepairDefaultIncludeMaps = false;
    static constexpr bool RepairDefaultForceLoadMissingPackages = true;
    static constexpr int32 RepairDefaultMaxPackagesToLoad = 2000;
    static constexpr int32 RepairDefaultMaxAssetsToSync = 5;

    static TArray<FString> NormalizeSelectedPaths(const TArray<FString>& SelectedPaths)
    {
        TArray<FString> Result;

        for (FString Path : SelectedPaths)
        {
            Path.TrimStartAndEndInline();
            Path.ReplaceInline(TEXT("\\"), TEXT("/"));
            Path.RemoveFromEnd(TEXT("/"));

            if (Path.Equals(TEXT("/All/Game"), ESearchCase::IgnoreCase))
            {
                Path = TEXT("/Game");
            }
            else if (Path.StartsWith(TEXT("/All/Game/"), ESearchCase::IgnoreCase))
            {
                Path = FString(TEXT("/Game")) + Path.Mid(9);
            }

            if (Path == TEXT("/Game") || Path.StartsWith(TEXT("/Game/")))
            {
                Result.AddUnique(Path);
            }
        }

        return Result;
    }

    static void LogRepairResult(const FAssetRegistryRepairResult& Result)
    {
        if (Result.bCanceled)
        {
            UE_LOG(
                LogTemp,
                Warning,
                TEXT("Asset Registry Repair canceled. %s"),
                *Result.Message
            );
            return;
        }

        if (!Result.bSucceeded)
        {
            UE_LOG(
                LogTemp,
                Warning,
                TEXT("Asset Registry Repair failed. %s"),
                *Result.Message
            );
            return;
        }

        UE_LOG(
            LogTemp,
            Display,
            TEXT("Asset Registry Repair finished. %s"),
            *Result.Message
        );
    }
}

class FAssetRegistryRepairModule : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        if (FModuleManager::Get().IsModuleLoaded(TEXT("ContentBrowser")))
        {
            RegisterContentBrowserMenuExtender();
            return;
        }

        FModuleManager::Get().OnModulesChanged().AddRaw(
            this,
            &FAssetRegistryRepairModule::HandleModulesChanged
        );
    }

    virtual void ShutdownModule() override
    {
        FModuleManager::Get().OnModulesChanged().RemoveAll(this);
        UnregisterContentBrowserMenuExtender();
    }

private:
    FDelegateHandle PathViewExtenderDelegateHandle;

    void HandleModulesChanged(FName ModuleName, EModuleChangeReason ChangeReason)
    {
        if (
            ModuleName == TEXT("ContentBrowser")
            && ChangeReason == EModuleChangeReason::ModuleLoaded
            && !PathViewExtenderDelegateHandle.IsValid()
            )
        {
            RegisterContentBrowserMenuExtender();
        }
    }

    void RegisterContentBrowserMenuExtender()
    {
        FContentBrowserModule& ContentBrowserModule =
            FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));

        TArray<FContentBrowserMenuExtender_SelectedPaths>& MenuExtenders =
            ContentBrowserModule.GetAllPathViewContextMenuExtenders();

        MenuExtenders.Add(
            FContentBrowserMenuExtender_SelectedPaths::CreateRaw(
                this,
                &FAssetRegistryRepairModule::ExtendPathViewContextMenu
            )
        );

        PathViewExtenderDelegateHandle = MenuExtenders.Last().GetHandle();
    }

    void UnregisterContentBrowserMenuExtender()
    {
        if (!PathViewExtenderDelegateHandle.IsValid())
        {
            return;
        }

        if (!FModuleManager::Get().IsModuleLoaded(TEXT("ContentBrowser")))
        {
            PathViewExtenderDelegateHandle.Reset();
            return;
        }

        FContentBrowserModule& ContentBrowserModule =
            FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));

        TArray<FContentBrowserMenuExtender_SelectedPaths>& MenuExtenders =
            ContentBrowserModule.GetAllPathViewContextMenuExtenders();

        MenuExtenders.RemoveAll(
            [this](const FContentBrowserMenuExtender_SelectedPaths& Delegate)
            {
                return Delegate.GetHandle() == PathViewExtenderDelegateHandle;
            }
        );

        PathViewExtenderDelegateHandle.Reset();
    }

    TSharedRef<FExtender> ExtendPathViewContextMenu(const TArray<FString>& SelectedPaths)
    {
        TSharedRef<FExtender> Extender = MakeShared<FExtender>();

        const TArray<FString> GamePaths = NormalizeSelectedPaths(SelectedPaths);

        if (GamePaths.Num() == 0)
        {
            return Extender;
        }

        Extender->AddMenuExtension(
            TEXT("PathContextBulkOperations"),
            EExtensionHook::After,
            nullptr,
            FMenuExtensionDelegate::CreateRaw(
                this,
                &FAssetRegistryRepairModule::AddRepairMenuEntries,
                GamePaths
            )
        );

        return Extender;
    }

    void AddRepairMenuEntries(FMenuBuilder& MenuBuilder, TArray<FString> SelectedPaths)
    {
        MenuBuilder.BeginSection(
            TEXT("AssetRegistryRepair"),
            LOCTEXT("AssetRegistryRepairSection", "\u8D44\u4EA7\u6CE8\u518C\u8868\u4FEE\u590D")
        );

        MenuBuilder.AddMenuEntry(
            LOCTEXT(
                "RepairSelectedFoldersWithMapsLabel",
                "\u4FEE\u590D\u8D44\u4EA7\u663E\u793A"
            ),
            LOCTEXT(
                "RepairSelectedFoldersWithMapsTooltip",
                "\u91CD\u65B0\u626B\u63CF\u5E76\u6062\u590D\u5F53\u524D\u9009\u4E2D\u6587\u4EF6\u5939\u4E0B\u7684\u8D44\u4EA7\u548C\u5730\u56FE\u3002"
            ),
            FSlateIcon(),
            FUIAction(
                FExecuteAction::CreateRaw(
                    this,
                    &FAssetRegistryRepairModule::ExecuteRepairSelectedFolders,
                    SelectedPaths,
                    RepairDefaultModifiedWithinMinutes,
                    RepairDefaultIncludeMaps
                )
            )
        );

        MenuBuilder.EndSection();
    }

    void ExecuteRepairSelectedFolders(
        TArray<FString> SelectedPaths,
        int32 ModifiedWithinMinutes,
        bool bIncludeMaps
    )
    {
        const TArray<FString> GamePaths = NormalizeSelectedPaths(SelectedPaths);

        if (GamePaths.Num() == 0)
        {
            UE_LOG(
                LogTemp,
                Warning,
                TEXT("Asset Registry Repair: no valid /Game folder selected.")
            );
            return;
        }

        const FAssetRegistryRepairResult Result =
            UAssetRegistryRepairLibrary::RepairAssetRegistryFromDiskInFolders(
                GamePaths,
                ModifiedWithinMinutes,
                bIncludeMaps,
                RepairDefaultForceLoadMissingPackages,
                RepairDefaultMaxPackagesToLoad,
                RepairDefaultMaxAssetsToSync
            );

        LogRepairResult(Result);
    }
};

IMPLEMENT_MODULE(FAssetRegistryRepairModule, AssetRegistryRepair)

#undef LOCTEXT_NAMESPACE