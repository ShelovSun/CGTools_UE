// Copyright CGTools. All Rights Reserved.

#include "MayaActionImporter.h"

#include "Animation/Skeleton.h"
#include "Animation/AnimSequence.h"
#include "AssetImportTask.h"
#include "AssetToolsModule.h"
#include "CGToolsMayaBridgeLog.h"
#include "ContentBrowserModule.h"
#include "Containers/Ticker.h"
#include "IContentBrowserSingleton.h"
#include "MayaAssetRecovery.h"
#include "Factories/FbxImportUI.h"
#include "IAssetTools.h"
#include "Misc/MessageDialog.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "ObjectTools.h"
#include "UObject/GCObjectScopeGuard.h"
#include "UObject/SoftObjectPath.h"

namespace
{
FTSTicker::FDelegateHandle PendingAnimationFocus;

FString NormalizeSkeletonObjectPath(FString Path)
{
    Path.ReplaceInline(TEXT("\\"), TEXT("/"));
    Path.TrimStartAndEndInline();

    int32 LastSlash = INDEX_NONE;
    Path.FindLastChar(TEXT('/'), LastSlash);
    const int32 ObjectSeparator = Path.Find(
        TEXT("."),
        ESearchCase::CaseSensitive,
        ESearchDir::FromStart,
        LastSlash + 1);
    if (ObjectSeparator == INDEX_NONE)
    {
        const FString AssetName = FPackageName::GetLongPackageAssetName(Path);
        if (!AssetName.IsEmpty())
        {
            Path += TEXT(".") + AssetName;
        }
    }
    return Path;
}

FString NormalizeDestinationPath(FString Path)
{
    Path.ReplaceInline(TEXT("\\"), TEXT("/"));
    Path.TrimStartAndEndInline();
    while (Path.RemoveFromEnd(TEXT("/")))
    {
    }
    return Path;
}
}

FMayaActionImporter::FMayaActionImporter(const FMayaBridgeSettings& InSettings)
    : Settings(InSettings)
{
}

void FMayaActionImporter::PromptAndImport(const FMayaBridgeMessage& Message)
{
    check(IsInGameThread());

    const FText DialogTitle = FText::FromString(TEXT("Maya 动作发布"));
    const EAppReturnType::Type Answer = FMessageDialog::Open(
        EAppMsgType::YesNo,
        FText::FromString(BuildPrompt(Message)),
        DialogTitle);
    if (Answer != EAppReturnType::Yes)
    {
        UE_LOG(
            LogCGToolsMayaBridge,
            Log,
            TEXT("User ignored Maya publish event %s."),
            *Message.EventId);
        return;
    }

    int32 ImportedCount = 0;
    TArray<FString> Failures;
    TArray<FAssetData> ImportedAnimations;
    TMap<FString, FString> RecoveryFailures;
    for (FMayaPublishedAction Action : Message.Actions)
    {
        if (Action.ProjectName.IsEmpty() && Message.ProjectNames.Num() == 1)
        {
            Action.ProjectName = Message.ProjectNames[0];
        }
        FString Error;
        if (!FPaths::FileExists(Action.FbxPath))
        {
            Failures.Add(FString::Printf(TEXT("%s / %s: 动作 FBX 不存在或无法访问：%s"),
                *Action.AssetName, *Action.ActionName, *Action.FbxPath));
            continue;
        }
        FString SkeletonPath;
        FString AnimationPath;
        Settings.ResolveImportPaths(Action, SkeletonPath, AnimationPath);
        SkeletonPath = NormalizeSkeletonObjectPath(SkeletonPath);
        if (!NormalizeDestinationPath(AnimationPath).StartsWith(TEXT("/Game/")))
        {
            Failures.Add(FString::Printf(TEXT("%s / %s: 无效的动作导入目录：%s"),
                *Action.AssetName, *Action.ActionName, *AnimationPath));
            continue;
        }
        const FString RecoveryKey = (Action.ProjectName + TEXT("/") + Action.AssetType + TEXT("/")
            + Action.AssetName + TEXT("|") + SkeletonPath).ToLower();
        if (const FString* PreviousFailure = RecoveryFailures.Find(RecoveryKey))
        {
            Error = *PreviousFailure;
        }
        else if (!FMayaAssetRecovery::EnsureSkeleton(Action, SkeletonPath, Error))
        {
            RecoveryFailures.Add(RecoveryKey, Error);
        }
        if (!Error.IsEmpty())
        {
            Failures.Add(FString::Printf(TEXT("%s / %s: %s"), *Action.AssetName, *Action.ActionName, *Error));
            continue;
        }
        if (ImportAction(Action, Error, ImportedAnimations))
        {
            ++ImportedCount;
        }
        else
        {
            Failures.Add(FString::Printf(TEXT("%s / %s: %s"), *Action.AssetName, *Action.ActionName, *Error));
        }
    }

    UE_LOG(
        LogCGToolsMayaBridge,
        Log,
        TEXT("Maya publish event %s finished: %d imported, %d failed."),
        *Message.EventId,
        ImportedCount,
        Failures.Num());

    if (!Failures.IsEmpty())
    {
        const FString FailureText = FString::Printf(
            TEXT("成功导入 %d/%d 个动作。\n\n%s\n\n详细信息请查看 LogCGToolsMayaBridge。"),
            ImportedCount,
            Message.Actions.Num(),
            *FString::Join(Failures, TEXT("\n")));
        FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(FailureText), DialogTitle);
    }

    // Asset recovery can change the browser selection before animation import.
    // Always finish the entire batch by selecting the actual imported sequences.
    FocusImportedAnimations(ImportedAnimations);
}

bool FMayaActionImporter::ImportAction(
    const FMayaPublishedAction& Action,
    FString& OutError,
    TArray<FAssetData>& OutImportedAnimations) const
{
    FString FbxPath = Action.FbxPath;
    FPaths::NormalizeFilename(FbxPath);
    if (!FPaths::FileExists(FbxPath))
    {
        OutError = FString::Printf(TEXT("FBX does not exist or is not accessible: %s"), *FbxPath);
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("%s"), *OutError);
        return false;
    }

    FString SkeletonPath;
    FString AnimationPath;
    Settings.ResolveImportPaths(Action, SkeletonPath, AnimationPath);
    SkeletonPath = NormalizeSkeletonObjectPath(SkeletonPath);
    AnimationPath = NormalizeDestinationPath(AnimationPath);

    if (!AnimationPath.StartsWith(TEXT("/Game/"), ESearchCase::CaseSensitive))
    {
        OutError = FString::Printf(TEXT("invalid animation destination: %s"), *AnimationPath);
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("%s"), *OutError);
        return false;
    }

    UObject* SkeletonObject = FSoftObjectPath(SkeletonPath).TryLoad();
    USkeleton* Skeleton = Cast<USkeleton>(SkeletonObject);
    if (Skeleton == nullptr)
    {
        OutError = FString::Printf(TEXT("导入动作失败，没有找到骨骼路径：%s"), *SkeletonPath);
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("%s"), *OutError);
        return false;
    }

    const FString DestinationName = ObjectTools::SanitizeObjectName(Action.ActionName);
    if (DestinationName.IsEmpty())
    {
        OutError = TEXT("action_name does not produce a valid Unreal asset name");
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("%s"), *OutError);
        return false;
    }

    UAssetImportTask* ImportTask = NewObject<UAssetImportTask>();
    TGCObjectScopeGuard<UAssetImportTask> ImportTaskGuard(ImportTask);
    UFbxImportUI* ImportOptions = NewObject<UFbxImportUI>(ImportTask);

    ImportOptions->MeshTypeToImport = FBXIT_Animation;
    ImportOptions->bAutomatedImportShouldDetectType = false;
    ImportOptions->bImportAsSkeletal = true;
    ImportOptions->bImportMesh = false;
    ImportOptions->bImportAnimations = true;
    ImportOptions->bImportMaterials = false;
    ImportOptions->bImportTextures = false;
    ImportOptions->Skeleton = Skeleton;
    ImportOptions->OverrideAnimationName = DestinationName;

    ImportTask->Filename = FbxPath;
    ImportTask->DestinationPath = AnimationPath;
    ImportTask->DestinationName = DestinationName;
    ImportTask->bAutomated = true;
    ImportTask->bAsync = false;
    ImportTask->bSave = true;
    ImportTask->bReplaceExisting = Settings.bReplaceExisting;
    ImportTask->bReplaceExistingSettings = Settings.bReplaceExisting;
    ImportTask->Options = ImportOptions;

    TArray<UAssetImportTask*> ImportTasks;
    ImportTasks.Add(ImportTask);
    FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
    AssetToolsModule.Get().ImportAssetTasks(ImportTasks);

    TArray<FAssetData> ActionAnimations;
    const auto AddAnimation = [&ActionAnimations](UObject* Object)
    {
        if (UAnimSequence* Animation = Cast<UAnimSequence>(Object))
        {
            ActionAnimations.AddUnique(FAssetData(Animation));
        }
    };
    for (UObject* Object : ImportTask->GetObjects())
    {
        AddAnimation(Object);
    }
    for (const FString& ObjectPath : ImportTask->ImportedObjectPaths)
    {
        AddAnimation(FSoftObjectPath(ObjectPath).TryLoad());
    }
    if (ActionAnimations.IsEmpty())
    {
        OutError = FString::Printf(
            TEXT("Unreal did not return an imported animation for %s"),
            *FbxPath);
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("%s"), *OutError);
        return false;
    }
    for (const FAssetData& Animation : ActionAnimations)
    {
        OutImportedAnimations.AddUnique(Animation);
    }

    UE_LOG(
        LogCGToolsMayaBridge,
        Log,
        TEXT("Imported %s as %s/%s using skeleton %s."),
        *FbxPath,
        *AnimationPath,
        *DestinationName,
        *SkeletonPath);
    return true;
}

void FMayaActionImporter::FocusImportedAnimations(const TArray<FAssetData>& ImportedAnimations)
{
    if (!ImportedAnimations.IsEmpty())
    {
        CancelPendingFocus();
        // New asset folders reach the Content Browser data source on later
        // editor ticks. Syncing inside the import call can select nothing.
        PendingAnimationFocus = FTSTicker::GetCoreTicker().AddTicker(
            FTickerDelegate::CreateLambda([ImportedAnimations](float)
            {
                PendingAnimationFocus.Reset();
                FContentBrowserModule& Browser = FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));
                Browser.Get().SyncBrowserToAssets(ImportedAnimations, false, true);
                UE_LOG(LogCGToolsMayaBridge, Log, TEXT("Focused Content Browser on %d imported animation(s)."), ImportedAnimations.Num());
                return false;
            }), 0.1f);
    }
}

void FMayaActionImporter::CancelPendingFocus()
{
    if (PendingAnimationFocus.IsValid())
    {
        FTSTicker::RemoveTicker(PendingAnimationFocus);
        PendingAnimationFocus.Reset();
    }
}

FString FMayaActionImporter::BuildPrompt(const FMayaBridgeMessage& Message) const
{
    TArray<FString> Lines;
    Lines.Reserve(Message.Actions.Num());
    for (const FMayaPublishedAction& Action : Message.Actions)
    {
        Lines.Add(FString::Printf(
            TEXT("- [%s] %s / %s / %s\n  %s"),
            *Action.ProjectName,
            *Action.AssetType,
            *Action.AssetName,
            *Action.ActionName,
            *Action.FbxPath));
    }

    return FString::Printf(
        TEXT("Maya 发布了 %d 个动作，是否立即全部导入？\n\n%s"),
        Message.Actions.Num(),
        *FString::Join(Lines, TEXT("\n")));
}
