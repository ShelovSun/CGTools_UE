#include "CoreMinimal.h"

#include "Animation/Skeleton.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetToolsModule.h"
#include "ContentBrowserModule.h"
#include "Editor.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "IAssetTools.h"
#include "IContentBrowserSingleton.h"
#include "Materials/MaterialFunctionInterface.h"
#include "Materials/MaterialInterface.h"
#include "Misc/MessageDialog.h"
#include "Misc/PackageName.h"
#include "Misc/ScopedSlowTask.h"
#include "Modules/ModuleManager.h"
#include "NiagaraSystem.h"
#include "Particles/ParticleSystem.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "Subsystems/EditorAssetSubsystem.h"
#include "UObject/ObjectRedirector.h"
#include "UObject/Package.h"

#define LOCTEXT_NAMESPACE "CGToolsFolderOrganizer"

DEFINE_LOG_CATEGORY_STATIC(LogCGToolsFolderOrganizer, Log, All);

namespace CGToolsFolderOrganizer
{
    enum class EAssetBucket : uint8
    {
        MaterialFunction,
        Material,
        Mesh,
        Texture,
        RootEffect,
        Unclassified
    };

    struct FMovePlan
    {
        FAssetData Asset;
        FString OriginalPackageName;
        FString TargetFolder;
        FString TargetPackageName;
        EAssetBucket Bucket = EAssetBucket::Unclassified;
    };

    struct FScanSummary
    {
        int32 Scanned = 0;
        int32 RedirectorsSkipped = 0;
        int32 AlreadyOrganized = 0;
        int32 Unclassified = 0;
        int32 MaterialFunctionsToMove = 0;
        int32 MaterialsToMove = 0;
        int32 MeshesToMove = 0;
        int32 TexturesToMove = 0;
        int32 RootEffectsToMove = 0;
    };

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

    static bool CanOrganizeSelection(const TArray<FString>& SelectedPaths)
    {
        const TArray<FString> Paths = NormalizeSelectedPaths(SelectedPaths);
        return Paths.Num() == 1 && !Paths[0].Equals(TEXT("/Game"), ESearchCase::IgnoreCase);
    }

    static EAssetBucket ClassifyAsset(const FAssetData& Asset)
    {
        if (Asset.IsInstanceOf<UMaterialFunctionInterface>(EResolveClass::Yes))
        {
            return EAssetBucket::MaterialFunction;
        }

        if (Asset.IsInstanceOf<UMaterialInterface>(EResolveClass::Yes))
        {
            return EAssetBucket::Material;
        }

        if (
            Asset.IsInstanceOf<UStaticMesh>(EResolveClass::Yes)
            || Asset.IsInstanceOf<USkeletalMesh>(EResolveClass::Yes)
            || Asset.IsInstanceOf<USkeleton>(EResolveClass::Yes)
            || Asset.IsInstanceOf<UPhysicsAsset>(EResolveClass::Yes)
            )
        {
            return EAssetBucket::Mesh;
        }

        if (Asset.IsInstanceOf<UTexture>(EResolveClass::Yes))
        {
            return EAssetBucket::Texture;
        }

        if (
            Asset.IsInstanceOf<UNiagaraSystem>(EResolveClass::Yes)
            || Asset.IsInstanceOf<UParticleSystem>(EResolveClass::Yes)
            )
        {
            return EAssetBucket::RootEffect;
        }

        return EAssetBucket::Unclassified;
    }

    static FString GetTargetFolder(const FString& RootPath, EAssetBucket Bucket)
    {
        switch (Bucket)
        {
        case EAssetBucket::MaterialFunction:
            return RootPath / TEXT("M_F");
        case EAssetBucket::Material:
            return RootPath / TEXT("Mat");
        case EAssetBucket::Mesh:
            return RootPath / TEXT("Mesh");
        case EAssetBucket::Texture:
            return RootPath / TEXT("Tex");
        case EAssetBucket::RootEffect:
            return RootPath;
        default:
            return FString();
        }
    }

    static void CountMove(EAssetBucket Bucket, FScanSummary& Summary)
    {
        switch (Bucket)
        {
        case EAssetBucket::MaterialFunction:
            ++Summary.MaterialFunctionsToMove;
            break;
        case EAssetBucket::Material:
            ++Summary.MaterialsToMove;
            break;
        case EAssetBucket::Mesh:
            ++Summary.MeshesToMove;
            break;
        case EAssetBucket::Texture:
            ++Summary.TexturesToMove;
            break;
        case EAssetBucket::RootEffect:
            ++Summary.RootEffectsToMove;
            break;
        default:
            break;
        }
    }

    static bool PackageAlreadyExists(IAssetRegistry& AssetRegistry, const FString& PackageName)
    {
        TArray<FAssetData> ExistingAssets;
        if (AssetRegistry.GetAssetsByPackageName(FName(*PackageName), ExistingAssets) && ExistingAssets.Num() > 0)
        {
            return true;
        }

        if (FindPackage(nullptr, *PackageName) != nullptr)
        {
            return true;
        }

        return FPackageName::DoesPackageExist(PackageName);
    }

    static FString BuildConflictMessage(const FString& RootPath, const TArray<FString>& Conflicts)
    {
        constexpr int32 MaxDisplayedConflicts = 12;
        TArray<FString> DisplayedConflicts;
        const int32 DisplayCount = FMath::Min(Conflicts.Num(), MaxDisplayedConflicts);
        DisplayedConflicts.Reserve(DisplayCount + 1);

        for (int32 Index = 0; Index < DisplayCount; ++Index)
        {
            DisplayedConflicts.Add(FString::Printf(TEXT("- %s"), *Conflicts[Index]));
        }

        if (Conflicts.Num() > MaxDisplayedConflicts)
        {
            DisplayedConflicts.Add(
                FString::Printf(TEXT("- 另外还有 %d 个冲突"), Conflicts.Num() - MaxDisplayedConflicts)
            );
        }

        return FString::Printf(
            TEXT("无法整理文件夹：目标位置存在同名资产。\n\n文件夹：%s\n\n%s\n\n没有移动任何资产。请先重命名或移走冲突资产后再试。"),
            *RootPath,
            *FString::Join(DisplayedConflicts, TEXT("\n"))
        );
    }

    static FString BuildConfirmationMessage(
        const FString& RootPath,
        const FScanSummary& Summary,
        int32 TotalMoves
    )
    {
        return FString::Printf(
            TEXT(
                "即将整理特效文件夹：\n%s\n\n"
                "递归扫描资产：%d\n"
                "将移动资产：%d\n"
                "  材质函数 -> M_F：%d\n"
                "  材质 -> Mat：%d\n"
                "  静态/骨架网格体等 -> Mesh：%d\n"
                "  贴图 -> Tex：%d\n"
                "  Niagara/Cascade -> 文件夹根：%d\n\n"
                "已经位于正确目录：%d\n"
                "未命中整理规则并保持原位：%d\n"
                "跳过已有重定向器：%d\n\n"
                "将确保建立 M_F、Mat、Mesh、Tex 四个目录。\n"
                "移动会通过 UE 资产工具更新引用，并修复本次移动产生的重定向器。\n\n"
                "是否继续？"
            ),
            *RootPath,
            Summary.Scanned,
            TotalMoves,
            Summary.MaterialFunctionsToMove,
            Summary.MaterialsToMove,
            Summary.MeshesToMove,
            Summary.TexturesToMove,
            Summary.RootEffectsToMove,
            Summary.AlreadyOrganized,
            Summary.Unclassified,
            Summary.RedirectorsSkipped
        );
    }

    static bool EnsureDestinationFolders(const FString& RootPath)
    {
        if (!GEditor)
        {
            return false;
        }

        UEditorAssetSubsystem* EditorAssetSubsystem =
            GEditor->GetEditorSubsystem<UEditorAssetSubsystem>();
        if (!EditorAssetSubsystem)
        {
            return false;
        }

        const TArray<FString> DestinationFolders = {
            RootPath / TEXT("M_F"),
            RootPath / TEXT("Mat"),
            RootPath / TEXT("Mesh"),
            RootPath / TEXT("Tex")
        };

        for (const FString& DestinationFolder : DestinationFolders)
        {
            if (
                !EditorAssetSubsystem->DoesDirectoryExist(DestinationFolder)
                && !EditorAssetSubsystem->MakeDirectory(DestinationFolder)
                )
            {
                UE_LOG(
                    LogCGToolsFolderOrganizer,
                    Error,
                    TEXT("Failed to create destination folder: %s"),
                    *DestinationFolder
                );
                return false;
            }
        }

        return true;
    }

    static void FixRedirectorsCreatedByMoves(
        IAssetRegistry& AssetRegistry,
        IAssetTools& AssetTools,
        const TArray<FMovePlan>& Plans
    )
    {
        TSet<FName> OriginalPackageNames;
        for (const FMovePlan& Plan : Plans)
        {
            OriginalPackageNames.Add(FName(*Plan.OriginalPackageName));
        }

        TArray<UObjectRedirector*> Redirectors;
        for (const FName OriginalPackageName : OriginalPackageNames)
        {
            TArray<FAssetData> PackageAssets;
            AssetRegistry.GetAssetsByPackageName(OriginalPackageName, PackageAssets);

            for (const FAssetData& Asset : PackageAssets)
            {
                if (Asset.IsRedirector())
                {
                    if (UObjectRedirector* Redirector = Cast<UObjectRedirector>(Asset.GetAsset()))
                    {
                        Redirectors.AddUnique(Redirector);
                    }
                }
            }
        }

        if (Redirectors.Num() > 0)
        {
            AssetTools.FixupReferencers(
                Redirectors,
                true,
                ERedirectFixupMode::DeleteFixedUpRedirectors
            );
        }
    }
}

class FCGToolsFolderOrganizerModule : public IModuleInterface
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
            &FCGToolsFolderOrganizerModule::HandleModulesChanged
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
                &FCGToolsFolderOrganizerModule::ExtendPathViewContextMenu
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
        const TArray<FString> GamePaths =
            CGToolsFolderOrganizer::NormalizeSelectedPaths(SelectedPaths);

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
                &FCGToolsFolderOrganizerModule::AddOrganizerMenu,
                GamePaths
            )
        );

        return Extender;
    }

    void AddOrganizerMenu(FMenuBuilder& MenuBuilder, TArray<FString> SelectedPaths)
    {
        const bool bCanOrganize =
            CGToolsFolderOrganizer::CanOrganizeSelection(SelectedPaths);

        MenuBuilder.BeginSection(
            TEXT("CGToolsFolderOrganizer"),
            LOCTEXT("FolderOrganizerSection", "CGTools")
        );

        MenuBuilder.AddSubMenu(
            LOCTEXT("OrganizeFolderSubMenu", "整理文件夹"),
            LOCTEXT("OrganizeFolderSubMenuTooltip", "使用 CGTools 规则整理所选内容文件夹。"),
            FNewMenuDelegate::CreateRaw(
                this,
                &FCGToolsFolderOrganizerModule::PopulateOrganizerSubMenu,
                SelectedPaths
            ),
            FUIAction(
                FExecuteAction(),
                FCanExecuteAction::CreateLambda([bCanOrganize]() { return bCanOrganize; })
            ),
            NAME_None,
            EUserInterfaceActionType::Button
        );

        MenuBuilder.EndSection();
    }

    void PopulateOrganizerSubMenu(FMenuBuilder& MenuBuilder, TArray<FString> SelectedPaths)
    {
        MenuBuilder.AddMenuEntry(
            LOCTEXT("OrganizeVfxFolder", "整理特效文件夹"),
            LOCTEXT(
                "OrganizeVfxFolderTooltip",
                "递归按资产类型整理：材质函数到 M_F、材质到 Mat、网格体到 Mesh、贴图到 Tex，Niagara/Cascade 留在根目录。"
            ),
            FSlateIcon(),
            FUIAction(
                FExecuteAction::CreateRaw(
                    this,
                    &FCGToolsFolderOrganizerModule::ExecuteOrganizeVfxFolder,
                    SelectedPaths
                )
            )
        );
    }

    void ExecuteOrganizeVfxFolder(TArray<FString> SelectedPaths)
    {
        using namespace CGToolsFolderOrganizer;

        const TArray<FString> Paths = NormalizeSelectedPaths(SelectedPaths);
        if (Paths.Num() != 1 || Paths[0].Equals(TEXT("/Game"), ESearchCase::IgnoreCase))
        {
            FMessageDialog::Open(
                EAppMsgType::Ok,
                LOCTEXT(
                    "InvalidFolderSelection",
                    "请在内容浏览器左侧文件夹大纲中只选择一个 /Game 子文件夹；不能直接整理整个 /Game。"
                ),
                LOCTEXT("FolderOrganizerTitle", "整理文件夹")
            );
            return;
        }

        const FString RootPath = Paths[0];
        FAssetRegistryModule& AssetRegistryModule =
            FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
        IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();
        AssetRegistry.WaitForCompletion();
        AssetRegistry.ScanPathsSynchronous({ RootPath }, false);

        TArray<FAssetData> Assets;
        AssetRegistry.GetAssetsByPath(FName(*RootPath), Assets, true, false);

        FScanSummary Summary;
        Summary.Scanned = Assets.Num();
        TArray<FMovePlan> Plans;
        TArray<FString> Conflicts;
        TSet<FString> PlannedTargetPackages;

        for (const FAssetData& Asset : Assets)
        {
            if (Asset.IsRedirector())
            {
                ++Summary.RedirectorsSkipped;
                continue;
            }

            const EAssetBucket Bucket = ClassifyAsset(Asset);
            if (Bucket == EAssetBucket::Unclassified)
            {
                ++Summary.Unclassified;
                continue;
            }

            const FString TargetFolder = GetTargetFolder(RootPath, Bucket);
            const FString SourceFolder = Asset.PackagePath.ToString();
            if (SourceFolder.Equals(TargetFolder, ESearchCase::IgnoreCase))
            {
                ++Summary.AlreadyOrganized;
                continue;
            }

            FMovePlan Plan;
            Plan.Asset = Asset;
            Plan.OriginalPackageName = Asset.PackageName.ToString();
            Plan.TargetFolder = TargetFolder;
            Plan.TargetPackageName = TargetFolder / Asset.AssetName.ToString();
            Plan.Bucket = Bucket;

            const FString TargetKey = Plan.TargetPackageName.ToLower();
            if (PlannedTargetPackages.Contains(TargetKey))
            {
                Conflicts.AddUnique(Plan.TargetPackageName);
                continue;
            }

            PlannedTargetPackages.Add(TargetKey);
            if (PackageAlreadyExists(AssetRegistry, Plan.TargetPackageName))
            {
                Conflicts.AddUnique(Plan.TargetPackageName);
                continue;
            }

            CountMove(Bucket, Summary);
            Plans.Add(MoveTemp(Plan));
        }

        if (Conflicts.Num() > 0)
        {
            Conflicts.Sort();
            FMessageDialog::Open(
                EAppMsgType::Ok,
                FText::FromString(BuildConflictMessage(RootPath, Conflicts)),
                LOCTEXT("FolderOrganizerConflictTitle", "整理文件夹：发现冲突")
            );
            return;
        }

        const EAppReturnType::Type Confirmation = FMessageDialog::Open(
            EAppMsgType::YesNo,
            FText::FromString(BuildConfirmationMessage(RootPath, Summary, Plans.Num())),
            LOCTEXT("FolderOrganizerConfirmTitle", "整理特效文件夹")
        );
        if (Confirmation != EAppReturnType::Yes)
        {
            return;
        }

        TArray<UObject*> AssetsToMove;
        AssetsToMove.Reserve(Plans.Num());
        if (Plans.Num() > 0)
        {
            FScopedSlowTask LoadTask(
                Plans.Num(),
                LOCTEXT("LoadingAssets", "正在加载并验证待整理资产…")
            );
            LoadTask.MakeDialog(true);

            for (const FMovePlan& Plan : Plans)
            {
                LoadTask.EnterProgressFrame(1.0f, FText::FromName(Plan.Asset.AssetName));
                if (LoadTask.ShouldCancel())
                {
                    return;
                }

                UObject* AssetObject = Plan.Asset.GetAsset();
                if (!AssetObject)
                {
                    FMessageDialog::Open(
                        EAppMsgType::Ok,
                        FText::Format(
                            LOCTEXT(
                                "AssetLoadFailed",
                                "资产加载失败，整理已取消；尚未移动任何资产。\n\n{0}"
                            ),
                            FText::FromString(Plan.OriginalPackageName)
                        ),
                        LOCTEXT("FolderOrganizerFailedTitle", "整理文件夹失败")
                    );
                    return;
                }

                AssetsToMove.Add(AssetObject);
            }
        }

        if (!EnsureDestinationFolders(RootPath))
        {
            FMessageDialog::Open(
                EAppMsgType::Ok,
                LOCTEXT(
                    "CreateFoldersFailed",
                    "无法建立 M_F、Mat、Mesh、Tex 目标目录，整理已取消。请检查工程内容目录的写入权限。"
                ),
                LOCTEXT("FolderOrganizerFailedTitle2", "整理文件夹失败")
            );
            return;
        }

        bool bRenameSucceeded = true;
        if (Plans.Num() > 0)
        {
            TArray<FAssetRenameData> RenameData;
            RenameData.Reserve(Plans.Num());
            for (int32 Index = 0; Index < Plans.Num(); ++Index)
            {
                RenameData.Emplace(
                    TWeakObjectPtr<UObject>(AssetsToMove[Index]),
                    Plans[Index].TargetFolder,
                    Plans[Index].Asset.AssetName.ToString()
                );
            }

            IAssetTools& AssetTools =
                FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools")).Get();
            bRenameSucceeded = AssetTools.RenameAssets(RenameData);

            if (bRenameSucceeded)
            {
                FixRedirectorsCreatedByMoves(AssetRegistry, AssetTools, Plans);
            }
        }

        AssetRegistry.ScanPathsSynchronous({ RootPath }, true);
        FContentBrowserModule& ContentBrowserModule =
            FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));
        ContentBrowserModule.Get().SyncBrowserToFolders({ RootPath });

        if (!bRenameSucceeded)
        {
            UE_LOG(
                LogCGToolsFolderOrganizer,
                Warning,
                TEXT("Folder organization did not complete successfully: %s"),
                *RootPath
            );
            FMessageDialog::Open(
                EAppMsgType::Ok,
                LOCTEXT(
                    "RenameFailed",
                    "UE 未能完成全部资产移动。部分资产可能已经移动，请查看 Output Log，并重新检查该文件夹后再执行。"
                ),
                LOCTEXT("FolderOrganizerFailedTitle3", "整理文件夹未完成")
            );
            return;
        }

        UE_LOG(
            LogCGToolsFolderOrganizer,
            Display,
            TEXT("VFX folder organized: %s (%d assets moved)"),
            *RootPath,
            Plans.Num()
        );
        FMessageDialog::Open(
            EAppMsgType::Ok,
            FText::Format(
                LOCTEXT(
                    "OrganizationComplete",
                    "特效文件夹整理完成。\n\n移动资产：{0}\n保持原位的未识别资产：{1}\n\n内容浏览器已定位回所选文件夹。"
                ),
                FText::AsNumber(Plans.Num()),
                FText::AsNumber(Summary.Unclassified)
            ),
            LOCTEXT("FolderOrganizerCompleteTitle", "整理完成")
        );
    }
};

IMPLEMENT_MODULE(FCGToolsFolderOrganizerModule, CGToolsFolderOrganizer)

#undef LOCTEXT_NAMESPACE
