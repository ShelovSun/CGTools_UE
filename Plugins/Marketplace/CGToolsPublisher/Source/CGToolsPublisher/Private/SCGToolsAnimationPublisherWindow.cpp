#include "SCGToolsAnimationPublisherWindow.h"
#include "CGToolsPublisherDatabase.h"
#include "CGToolsPublisherMayaBridge.h"

#include "Animation/AnimSequence.h"
#include "Animation/Skeleton.h"
#include "AssetExportTask.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Dom/JsonObject.h"
#include "Engine/SkeletalMesh.h"
#include "EditorFramework/AssetImportData.h"
#include "Exporters/AnimSequenceExporterFBX.h"
#include "Exporters/FbxExportOption.h"
#include "FileHelpers.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/MessageDialog.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "Misc/ScopedSlowTask.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SCGToolsPublisherAssetPreview.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Animation/AnimData/IAnimationDataController.h"
#include "Factories/AnimSequenceFactory.h"
#include "Misc/AutomationTest.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/SecureHash.h"
#include "ReferenceSkeleton.h"
#endif

#define LOCTEXT_NAMESPACE "CGToolsAnimationPublisher"

namespace
{
    const FString AnimationConfigPath = TEXT("Y:/MCCTools/config/ShotManager_config/commonSetting.json");
    const FString AnimationProjectRoot = TEXT("Y:/MCCProject");

    bool IsSafeComponent(const FString& Name)
    {
        if (Name.IsEmpty() || Name != Name.TrimStartAndEnd() || Name.EndsWith(TEXT(".")))
        {
            return false;
        }
        for (const TCHAR Character : Name)
        {
            if (Character < 32 || FString(TEXT("<>:\"/\\|?*")).Contains(FString::Chr(Character)))
            {
                return false;
            }
        }
        // Windows reserves these names even when they have an extension.
        const FString Base = Name.Left(Name.Find(TEXT(".")) == INDEX_NONE ? Name.Len() : Name.Find(TEXT("."))).ToUpper();
        if (Base == TEXT("CON") || Base == TEXT("PRN") || Base == TEXT("AUX") || Base == TEXT("NUL"))
        {
            return false;
        }
        return !(Base.Len() == 4 && (Base.StartsWith(TEXT("COM")) || Base.StartsWith(TEXT("LPT")))
            && Base[3] >= TEXT('1') && Base[3] <= TEXT('9'));
    }

    bool ReadAnimationProjects(const FString& ConfigFile, TArray<FString>& OutProjects, FString& OutError)
    {
        OutProjects.Reset();
        OutError.Reset();
        FString Json;
        if (!FFileHelper::LoadFileToString(Json, *ConfigFile))
        {
            OutError = FString::Printf(TEXT("无法读取项目配置：%s"), *ConfigFile);
            return false;
        }
        TSharedPtr<FJsonObject> Object;
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Object)
            || !Object.IsValid() || !Object->TryGetArrayField(TEXT("DataBase"), Values))
        {
            OutError = TEXT("commonSetting.json 无效或缺少 DataBase 项目列表。");
            return false;
        }
        for (const TSharedPtr<FJsonValue>& Value : *Values)
        {
            FString Project;
            if (Value.IsValid() && Value->TryGetString(Project) && IsSafeComponent(Project))
            {
                OutProjects.AddUnique(Project);
            }
        }
        if (OutProjects.IsEmpty())
        {
            OutError = TEXT("commonSetting.json 的 DataBase 项目列表为空或没有有效项目名。");
            return false;
        }
        return true;
    }

    USkeletalMesh* ResolveAnimationMesh(UAnimSequence* Animation)
    {
        if (!Animation)
        {
            return nullptr;
        }
        // The const overloads do not assign a guessed preview mesh to the source asset.
        if (USkeletalMesh* Mesh = static_cast<const UAnimationAsset*>(Animation)->GetPreviewMesh())
        {
            return Mesh;
        }
        USkeleton* Skeleton = Animation->GetSkeleton();
        if (!Skeleton)
        {
            return nullptr;
        }
        if (USkeletalMesh* Mesh = static_cast<const USkeleton*>(Skeleton)->GetPreviewMesh())
        {
            return Mesh;
        }
        // Without a preview, use an unambiguous mesh associated with this skeleton.
        // A shared skeleton may belong to several meshes, so never choose an arbitrary one.
        FARFilter Filter;
        Filter.ClassPaths.Add(USkeletalMesh::StaticClass()->GetClassPathName());
        Filter.bRecursiveClasses = true;
        TArray<FAssetData> Meshes;
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetAssets(Filter, Meshes);
        FAssetData Match;
        for (const FAssetData& Mesh : Meshes)
        {
            FString SkeletonPath;
            if (Mesh.GetTagValue(TEXT("Skeleton"), SkeletonPath)
                && FPackageName::ExportTextPathToObjectPath(SkeletonPath) == Skeleton->GetPathName())
            {
                if (Match.IsValid())
                {
                    return nullptr;
                }
                Match = Mesh;
            }
        }
        return Match.IsValid() ? Cast<USkeletalMesh>(Match.GetAsset()) : nullptr;
    }

    FString ResolveAnimationAssetName(UAnimSequence* Animation)
    {
        if (!Animation)
        {
            return FString();
        }
        // Preview meshes can be individual body parts named C, Body, etc.
        // The skeleton identifies the publishing asset shared by those meshes.
        if (const USkeleton* Skeleton = Animation->GetSkeleton())
        {
            FString AssetName = Skeleton->GetName();
            AssetName.RemoveFromEnd(TEXT("_Skeleton"), ESearchCase::IgnoreCase);
            if (!AssetName.IsEmpty())
            {
                return AssetName;
            }
        }
        if (const USkeletalMesh* Mesh = ResolveAnimationMesh(Animation))
        {
            return Mesh->GetName();
        }
        return FString();
    }

    struct FAnimationTarget
    {
        FString Project;
        FString AssetName;
        FString AssetDirectory;
        FString Directory;
        FString BaseName;
        FString Uasset;
        FString Fbx;
        FString Maya;
    };

    struct FAnimationPublishResult
    {
        bool bMayaPublished = false;
        FString MayaWarning;
    };

    using FAnimationAssetChecker = FCGToolsDatabaseResult (*)(const FString&, const FString&);

    FCGToolsDatabaseResult CheckAnimationAssetRecord(const FString& Project, const FString& AssetName)
    {
        // The database adapter reads the authoritative host from commonSetting
        // immediately before connecting; animation publishing only reads records.
        return FCGToolsPublisherDatabase::CheckAssetRecord(Project, AssetName, FString());
    }

    bool ValidateAnimationAsset(const FAnimationTarget& Target, FString& OutError,
        FAnimationAssetChecker CheckAsset)
    {
        if (!IFileManager::Get().DirectoryExists(*Target.AssetDirectory))
        {
            OutError = FString::Printf(TEXT("找不到资产“%s”：Assets 目录不存在或不可访问。\n%s"),
                *Target.AssetName, *Target.AssetDirectory);
            return false;
        }
        const FCGToolsDatabaseResult Record = CheckAsset(Target.Project, Target.AssetName);
        if (!Record.bOk)
        {
            OutError = FString::Printf(TEXT("无法检查资产“%s”的数据库记录（项目：%s）：\n%s"),
                *Target.AssetName, *Target.Project, *Record.Error);
            return false;
        }
        if (!Record.bExists)
        {
            OutError = FString::Printf(TEXT("找不到资产“%s”：项目“%s”的数据库中没有该资产记录。"),
                *Target.AssetName, *Target.Project);
            return false;
        }
        return true;
    }

    bool BuildAnimationTarget(const FString& Root, const FString& Project, const FString& Type,
        const FString& AssetName, const FString& ActionName, FAnimationTarget& OutTarget, FString& OutError,
        FAnimationAssetChecker CheckAsset = &CheckAnimationAssetRecord)
    {
        OutError.Reset();
        OutTarget = FAnimationTarget();
        if (!IsSafeComponent(Project) || !IsSafeComponent(AssetName) || !IsSafeComponent(ActionName))
        {
            OutError = TEXT("项目、资产名和动作名不能为空，不能包含路径分隔符、非法文件名字符、首尾空格或末尾句点。");
            return false;
        }
        if (Type != TEXT("Characters") && Type != TEXT("Props"))
        {
            OutError = TEXT("类型必须为 Characters 或 Props。");
            return false;
        }
        IFileManager& Files = IFileManager::Get();
        const FString ProjectDirectory = Root / Project;
        if (!Files.DirectoryExists(*ProjectDirectory))
        {
            OutError = FString::Printf(TEXT("项目不存在或目录不可访问：%s"), *ProjectDirectory);
            return false;
        }
        OutTarget.Project = Project;
        OutTarget.AssetName = AssetName;
        OutTarget.AssetDirectory = ProjectDirectory / TEXT("Assets") / Type / AssetName;
        OutTarget.Directory = ProjectDirectory / TEXT("Animations") / Type / AssetName / TEXT("Action");
        OutTarget.BaseName = AssetName + TEXT("_") + ActionName;
        FText InvalidNameReason;
        if (!FPackageName::IsValidObjectPath(TEXT("/Game/Animation/") + OutTarget.BaseName
            + TEXT(".") + OutTarget.BaseName, &InvalidNameReason))
        {
            OutError = TEXT("资产名或动作名不能用于 UE 动画资源名：") + InvalidNameReason.ToString();
            return false;
        }
        OutTarget.Uasset = OutTarget.Directory / (OutTarget.BaseName + TEXT(".uasset"));
        OutTarget.Fbx = OutTarget.Directory / (OutTarget.BaseName + TEXT(".fbx"));
        OutTarget.Maya = OutTarget.Directory / (OutTarget.BaseName + TEXT(".ma"));
        for (const FString& Directory : { ProjectDirectory / TEXT("Animations"),
            ProjectDirectory / TEXT("Animations") / Type,
            FPaths::GetPath(OutTarget.Directory), OutTarget.Directory })
        {
            if (Files.FileExists(*Directory))
            {
                OutError = TEXT("动画发布目录被同名文件占用：") + Directory;
                return false;
            }
        }
        if (Files.DirectoryExists(*OutTarget.Uasset) || Files.DirectoryExists(*OutTarget.Fbx)
            || Files.DirectoryExists(*OutTarget.Maya))
        {
            OutError = TEXT("发布路径被同名文件或文件夹占用。");
            return false;
        }
        return ValidateAnimationAsset(OutTarget, OutError, CheckAsset);
    }

    bool ExportAnimationFbx(UAnimSequence* Animation, const FString& Filename, FString& OutError)
    {
        USkeletalMesh* Mesh = ResolveAnimationMesh(Animation);
        if (!Mesh)
        {
            OutError = TEXT("没有找到动画关联的骨骼网格体，无法导出 FBX。请在动画编辑器中设置正确的预览网格体后重试。");
            return false;
        }
        // UE's exporter requires a preview mesh even with bExportPreviewMesh=false.
        // Assign it on a transient export copy, leaving the selected asset untouched.
        FObjectDuplicationParameters Duplication(Animation, GetTransientPackage());
        if (Animation->AssetImportData)
        {
            // Import metadata is read-only during export. Sharing it avoids an
            // unnecessary duplicate requiring PostLoad during animation compression.
            Duplication.DuplicationSeed.Add(Animation->AssetImportData, Animation->AssetImportData);
        }
        TStrongObjectPtr<UAnimSequence> ExportCopy(Cast<UAnimSequence>(StaticDuplicateObjectEx(Duplication)));
        if (!ExportCopy.IsValid())
        {
            OutError = TEXT("无法创建动画导出副本。");
            return false;
        }
        ExportCopy->SetPreviewMesh(Mesh, false);
        TStrongObjectPtr<UAssetExportTask> Task(NewObject<UAssetExportTask>());
        Task->Object = ExportCopy.Get();
        Task->Exporter = NewObject<UAnimSequenceExporterFBX>(Task.Get());
        UFbxExportOption* Options = NewObject<UFbxExportOption>(Task.Get());
        Options->bExportPreviewMesh = false;
        Options->bASCII = false;
        Task->Options = Options;
        Task->Filename = Filename;
        Task->bSelected = false;
        Task->bReplaceIdentical = true;
        Task->bPrompt = false;
        Task->bAutomated = true;
        Task->bUseFileArchive = false;
        Task->bWriteEmptyFiles = false;
        if (!UExporter::RunAssetExportTask(Task.Get()) || IFileManager::Get().FileSize(*Filename) <= 0)
        {
            OutError = FString::Printf(TEXT("动画 FBX 导出失败：%s"), *Filename);
            if (!Task->Errors.IsEmpty())
            {
                OutError += TEXT("\n") + FString::Join(Task->Errors, TEXT("\n"));
            }
            return false;
        }
        return true;
    }

    bool CommitAnimationFiles(const FAnimationTarget& Target, const FString& Staging, FString& OutError,
        bool bIncludeMaya = true)
    {
        IFileManager& Files = IFileManager::Get();
        TArray<FString> Destinations = { Target.Uasset, Target.Fbx };
        TArray<FString> Sources = { Staging / TEXT("Animation.uasset"), Staging / TEXT("Animation.fbx") };
        if (bIncludeMaya)
        {
            Destinations.Add(Target.Maya);
            Sources.Add(Staging / TEXT("Animation.ma"));
        }
        const FString BackupDirectory = Staging / TEXT("Previous");
        if (!Files.MakeDirectory(*BackupDirectory, true))
        {
            OutError = TEXT("无法创建动画发布备份目录：") + BackupDirectory;
            return false;
        }
        if (!Files.MakeDirectory(*Target.Directory, true))
        {
            OutError = TEXT("无法创建动画发布目录：") + Target.Directory;
            return false;
        }
        TArray<FString> Backups;
        for (int32 Index = 0; Index < Destinations.Num(); ++Index)
        {
            FString Backup;
            if (Files.FileExists(*Destinations[Index]))
            {
                Backup = BackupDirectory / FPaths::GetCleanFilename(Destinations[Index]);
                if (Files.Copy(*Backup, *Destinations[Index], false, false) != COPY_OK)
                {
                    OutError = FString::Printf(TEXT("无法备份同名文件：%s"), *Destinations[Index]);
                    return false;
                }
            }
            Backups.Add(Backup);
        }
        for (int32 Index = 0; Index < Destinations.Num(); ++Index)
        {
            if (Files.Copy(*Destinations[Index], *Sources[Index], true, false) == COPY_OK
                && Files.FileSize(*Destinations[Index]) == Files.FileSize(*Sources[Index]))
            {
                continue;
            }
            OutError = FString::Printf(TEXT("写入动画文件失败：%s"), *Destinations[Index]);
            for (int32 Restore = 0; Restore <= Index; ++Restore)
            {
                const bool bRestored = Backups[Restore].IsEmpty()
                    ? Files.Delete(*Destinations[Restore], false, false)
                    : Files.Copy(*Destinations[Restore], *Backups[Restore], true, false) == COPY_OK;
                if (!bRestored)
                {
                    OutError += FString::Printf(TEXT("\n恢复失败：%s\n备份：%s"),
                        *Destinations[Restore], *Backups[Restore]);
                }
            }
            return false;
        }
        return true;
    }

    bool SavePublishedAnimation(UAnimSequence* Animation, const FString& AssetName,
        const FString& Filename, FString& OutError)
    {
        // A disk-only rename leaves Package.NewFileName pointing at an object with
        // the old name. Content Browser rejects it because FAssetData::IsUAsset is
        // false. Save a separately named UE object; never rename the source asset.
        const FString PackageName = TEXT("/Temp/CGToolsAnimationPublish/")
            + FGuid::NewGuid().ToString(EGuidFormats::Digits) / AssetName;
        TStrongObjectPtr<UPackage> CopyPackage(CreatePackage(*PackageName));
        FObjectDuplicationParameters Duplication(Animation, CopyPackage.Get());
        Duplication.DestName = FName(*AssetName);
        if (Animation->AssetImportData)
        {
            // Compression during animation duplication may read import metadata
            // before its duplicate has completed PostLoad. Duplicate it afterwards.
            Duplication.DuplicationSeed.Add(Animation->AssetImportData, Animation->AssetImportData);
        }
        TStrongObjectPtr<UAnimSequence> Copy(Cast<UAnimSequence>(StaticDuplicateObjectEx(Duplication)));
        if (!Copy.IsValid())
        {
            OutError = TEXT("无法创建动画发布副本。");
            return false;
        }
        if (Animation->AssetImportData)
        {
            Copy->AssetImportData = DuplicateObject<UAssetImportData>(Animation->AssetImportData, Copy.Get());
            Copy->AssetImportData->ConditionalPostLoad();
        }
        // PreviewSkeletalMesh is DuplicateTransient; restore the associated mesh
        // on the published copy so Persona and thumbnails can still preview it.
        Copy->SetPreviewMesh(ResolveAnimationMesh(Animation), false);
        Copy->ClearFlags(RF_Transient);
        Copy->SetFlags(RF_Public | RF_Standalone);
        ON_SCOPE_EXIT { Copy->ClearFlags(RF_Standalone); };
        FSavePackageArgs SaveArgs;
        SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
        SaveArgs.SaveFlags = SAVE_NoError;
        if (!UPackage::SavePackage(CopyPackage.Get(), Copy.Get(), *Filename, SaveArgs))
        {
            OutError = FString::Printf(TEXT("无法保存动画发布副本：%s"), *Filename);
            return false;
        }
        return true;
    }

    using FAnimationMayaBaker = bool (*)(const FString&, const FString&, FString&);

    bool PublishAnimation(UAnimSequence* Animation, const FAnimationTarget& Target, FString& OutError,
        FAnimationPublishResult& OutResult, FAnimationMayaBaker BakeMaya = &CGToolsPublisher::BakeAnimationToMaya,
        FAnimationAssetChecker CheckAsset = &CheckAnimationAssetRecord)
    {
        OutError.Reset();
        OutResult = FAnimationPublishResult();
        if (!Animation || !Animation->GetSkeleton())
        {
            OutError = TEXT("选中的动画序列不存在或没有有效骨架，无法导出。");
            return false;
        }
        TUniquePtr<FScopedSlowTask> Progress = MakeUnique<FScopedSlowTask>(2.0f, LOCTEXT("PublishingAnimation", "正在发布动画序列…"));
        Progress->MakeDialog(false, false);
        Progress->EnterProgressFrame(1.0f, LOCTEXT("PrepareAnimation", "正在准备动画资产…"));
        UPackage* Package = Animation->GetOutermost();
        FString SourceFile;
        if ((Package->IsDirty() || !FPackageName::DoesPackageExist(Package->GetName(), &SourceFile))
            && !UEditorLoadingAndSavingUtils::SavePackages({ Package }, false))
        {
            OutError = TEXT("无法保存所选动画序列，发布已取消。");
            return false;
        }
        if (!FPackageName::DoesPackageExist(Package->GetName(), &SourceFile)
            || !SourceFile.EndsWith(TEXT(".uasset"), ESearchCase::IgnoreCase))
        {
            OutError = TEXT("找不到所选动画序列的 .uasset 源文件。");
            return false;
        }
        const FString Staging = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir()
            / TEXT("CGToolsPublisher/Animation") / FGuid::NewGuid().ToString(EGuidFormats::Digits));
        IFileManager& Files = IFileManager::Get();
        if (!Files.MakeDirectory(*Staging, true))
        {
            OutError = FString::Printf(TEXT("无法创建本地暂存目录：%s"), *Staging);
            return false;
        }
        bool bKeepStaging = false;
        ON_SCOPE_EXIT
        {
            if (!bKeepStaging)
            {
                Files.DeleteDirectory(*Staging, false, true);
            }
        };
        Progress->EnterProgressFrame(1.0f, LOCTEXT("ExportAnimation", "正在导出动画 FBX…"));
        if (!SavePublishedAnimation(Animation, Target.BaseName, Staging / TEXT("Animation.uasset"), OutError))
        {
            return false;
        }
        if (!ExportAnimationFbx(Animation, Staging / TEXT("Animation.fbx"), OutError))
        {
            return false;
        }
        // ADV must own its progress dialog to expose its safe Cancel button.
        Progress.Reset();
        const FString StagedMaya = Staging / TEXT("Animation.ma");
        FString MayaMessage;
        const bool bMayaReady = BakeMaya(Animation->GetPathName(), StagedMaya, MayaMessage)
            && Files.FileSize(*StagedMaya) > 0;
        if (!bMayaReady)
        {
            bKeepStaging = true;
            OutResult.MayaWarning = TEXT("Maya .ma 生成失败或已取消，本次未发布 .ma。\n") + MayaMessage
                + TEXT("\n.ma 目标位置：") + Target.Maya
                + TEXT("\n本地暂存保留在：") + Staging;
        }
        FScopedSlowTask UploadProgress(1.0f, LOCTEXT("UploadAnimation", "正在写入服务器动画目录…"));
        UploadProgress.MakeDialog(false, false);
        UploadProgress.EnterProgressFrame(1.0f);
        // Recheck the actual asset after confirmation/export/baking. The
        // Animations hierarchy can be absent and will be created at commit.
        if (!ValidateAnimationAsset(Target, OutError, CheckAsset))
        {
            return false;
        }
        // A failed/cancelled bake can leave a partial .ma in staging. Include
        // it only when the bridge explicitly reports a validated result.
        if (!CommitAnimationFiles(Target, Staging, OutError, bMayaReady))
        {
            // Retain local outputs and backups if a server write or recovery failed.
            bKeepStaging = true;
            OutError += TEXT("\n本地暂存与备份保留在：") + Staging;
            if (!OutResult.MayaWarning.IsEmpty())
            {
                OutError += TEXT("\n\n") + OutResult.MayaWarning;
            }
            return false;
        }
        OutResult.bMayaPublished = bMayaReady;
        return true;
    }
}

void SCGToolsAnimationPublisherWindow::Construct(const FArguments& InArgs)
{
    AssetData = InArgs._AssetData;
    DialogState = InArgs._DialogState.IsValid() ? InArgs._DialogState : MakeShared<FCGToolsPublisherDialogState>();
    TArray<FString> Projects;
    ReadAnimationProjects(AnimationConfigPath, Projects, ConfigError);
    for (const FString& Project : Projects)
    {
        ProjectOptions.Add(MakeShared<FString>(Project));
    }
    TypeOptions = { MakeShared<FString>(TEXT("Characters")), MakeShared<FString>(TEXT("Props")) };
    const FString DefaultAssetName = ResolveAnimationAssetName(Cast<UAnimSequence>(AssetData.GetAsset()));

    const auto MakeRow = [](const FText& Label, TSharedRef<SWidget> Widget) -> TSharedRef<SWidget>
    {
        return SNew(SHorizontalBox)
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 14, 0)
            [ SNew(SBox).WidthOverride(56) [ SNew(STextBlock).Text(Label) ] ]
            + SHorizontalBox::Slot().FillWidth(1.0f) [ Widget ];
    };
    const auto GenerateOption = [](TSharedPtr<FString> Option) -> TSharedRef<SWidget>
    {
        return SNew(STextBlock).Text(FText::FromString(Option.IsValid() ? *Option : FString()));
    };
    ChildSlot
    [
        SNew(SBorder).Padding(18.0f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 24, 0)
            [ SNew(SCGToolsPublisherAssetPreview).AssetData(AssetData) ]
            + SHorizontalBox::Slot().FillWidth(1.0f)
            [
                SNew(SVerticalBox)
                + SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 6)
                [
                    MakeRow(LOCTEXT("Project", "项目"),
                        SAssignNew(ProjectCombo, SComboBox<TSharedPtr<FString>>)
                        .OptionsSource(&ProjectOptions).InitiallySelectedItem(SelectedProject)
                        .OnGenerateWidget_Lambda(GenerateOption)
                        .OnSelectionChanged_Lambda([this](TSharedPtr<FString> Item, ESelectInfo::Type)
                        {
                            if (SelectedProject != Item)
                            {
                                SelectedProject = Item;
                                SelectedType.Reset();
                                if (TypeCombo.IsValid())
                                {
                                    TypeCombo->ClearSelection();
                                }
                            }
                        })
                        [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(SelectedProject.IsValid() ? *SelectedProject : FString()); }) ])
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 6)
                [
                    MakeRow(LOCTEXT("Type", "类型"),
                        SAssignNew(TypeCombo, SComboBox<TSharedPtr<FString>>)
                        .OptionsSource(&TypeOptions).InitiallySelectedItem(SelectedType)
                        .IsEnabled_Lambda([this]() { return SelectedProject.IsValid() && !bPublishing; })
                        .OnGenerateWidget_Lambda(GenerateOption)
                        .OnSelectionChanged_Lambda([this](TSharedPtr<FString> Item, ESelectInfo::Type) { SelectedType = Item; })
                        [ SNew(STextBlock).Text_Lambda([this]() { return FText::FromString(SelectedType.IsValid() ? *SelectedType : FString()); }) ])
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 6)
                [
                    MakeRow(LOCTEXT("AssetName", "资产名"),
                        SAssignNew(AssetNameTextBox, SEditableTextBox)
                        .Text(FText::FromString(DefaultAssetName))
                        .HintText(LOCTEXT("AssetNameHint", "未能解析资产名，请填写资产名")))
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 6)
                [
                    MakeRow(LOCTEXT("ActionName", "动作名"),
                        SAssignNew(ActionNameTextBox, SEditableTextBox).Text(FText::FromName(AssetData.AssetName)))
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(70, 6, 0, 6)
                [
                    SNew(SCheckBox)
                    .ToolTipText(LOCTEXT("NotifyMayaHint", "始终反求并发布 .ma；勾选后在发布完成时打开该 Maya 场景。"))
                    .IsChecked_Lambda([this]() { return bNotifyMaya ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
                    .OnCheckStateChanged_Lambda([this](ECheckBoxState State) { bNotifyMaya = State == ECheckBoxState::Checked; })
                    .IsEnabled_Lambda([this]() { return !bPublishing; })
                    [ SNew(STextBlock).Text(LOCTEXT("NotifyMayaAfterPublish", "发布完成通知Maya打开")) ]
                ]
                + SVerticalBox::Slot().AutoHeight().Padding(0, 6)
                [
                    SNew(STextBlock).Text(FText::FromString(ConfigError)).AutoWrapText(true)
                    .Visibility(ConfigError.IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible)
                    .ColorAndOpacity(FLinearColor(1.0f, 0.25f, 0.2f))
                ]
                + SVerticalBox::Slot().FillHeight(1.0f)
                + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0, 8, 0, 0)
                [
                    SNew(SHorizontalBox)
                    .Visibility(DialogState->bEmbedded ? EVisibility::Collapsed : EVisibility::Visible)
                    + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 10, 0)
                    [
                        SNew(SButton).Text(LOCTEXT("SkipCurrent", "跳过当前"))
                        .Visibility(DialogState->IsBatch() ? EVisibility::Visible : EVisibility::Collapsed)
                        .IsEnabled_Lambda([this]() { return !bPublishing; })
                        .OnClicked(this, &SCGToolsAnimationPublisherWindow::OnSkip)
                    ]
                    + SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 10, 0)
                    [
                        SNew(SBox).WidthOverride(90)
                        [ SNew(SButton).Text(LOCTEXT("Confirm", "确定")).HAlign(HAlign_Center)
                            .IsEnabled_Lambda([this]() { return ConfigError.IsEmpty() && SelectedProject.IsValid() && SelectedType.IsValid() && !bPublishing; })
                            .OnClicked(this, &SCGToolsAnimationPublisherWindow::OnConfirm) ]
                    ]
                    + SHorizontalBox::Slot().AutoWidth()
                    [
                        SNew(SBox).WidthOverride(DialogState->IsBatch() ? 120 : 90)
                        [ SNew(SButton).Text(DialogState->IsBatch() ? LOCTEXT("EndBatch", "结束批量发布") : LOCTEXT("Cancel", "取消"))
                            .HAlign(HAlign_Center).IsEnabled_Lambda([this]() { return !bPublishing; })
                            .OnClicked(this, &SCGToolsAnimationPublisherWindow::OnCancel) ]
                    ]
                ]
            ]
        ]
    ];
}

FReply SCGToolsAnimationPublisherWindow::OnConfirm()
{
    if (bPublishing || !SelectedProject.IsValid() || !SelectedType.IsValid())
    {
        return FReply::Handled();
    }
    FAnimationTarget Target;
    FString Error;
    if (!BuildAnimationTarget(AnimationProjectRoot, *SelectedProject, *SelectedType,
        AssetNameTextBox->GetText().ToString(), ActionNameTextBox->GetText().ToString(), Target, Error))
    {
        DialogState->Error = Error;
        if (!DialogState->bBatchExecution) { FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Error)); }
        return FReply::Handled();
    }
    FString DisplayDirectory = Target.Directory;
    FPaths::MakePlatformFilename(DisplayDirectory);
    FString Confirmation = FString::Printf(TEXT("是否导出动画“%s”到路径“%s”？"), *Target.BaseName, *DisplayDirectory);
    Confirmation += TEXT("\n\n将发布 .uasset、.fbx，并尝试反求发布 .ma。反求失败不会阻止前两项发布。");
    if (IFileManager::Get().FileExists(*Target.Uasset) || IFileManager::Get().FileExists(*Target.Fbx)
        || IFileManager::Get().FileExists(*Target.Maya))
    {
        Confirmation += TEXT("\n\n同名文件已存在，点击【Yes】将覆盖 .uasset 和 .fbx；.ma 仅在反求成功时覆盖，失败时保留旧文件。");
    }
    if (!DialogState->bBatchExecution && FMessageDialog::Open(EAppMsgType::YesNo, FText::FromString(Confirmation)) != EAppReturnType::Yes)
    {
        return FReply::Handled();
    }
    TGuardValue<bool> PublishingGuard(bPublishing, true);
    TGuardValue<bool> DialogPublishingGuard(DialogState->bPublishing, true);
    TStrongObjectPtr<UAnimSequence> Animation(Cast<UAnimSequence>(AssetData.GetAsset()));
    FAnimationPublishResult PublishResult;
    if (!PublishAnimation(Animation.Get(), Target, Error, PublishResult))
    {
        DialogState->Error = Error;
        if (!DialogState->bBatchExecution) { FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Error)); }
        return FReply::Handled();
    }
    FString Completion = FString::Printf(TEXT("动画发布完成：\n%s\n%s"), *Target.Uasset, *Target.Fbx);
    if (PublishResult.bMayaPublished)
    {
        Completion += TEXT("\n") + Target.Maya;
    }
    else
    {
        Completion += TEXT("\n\n") + PublishResult.MayaWarning;
        if (IFileManager::Get().FileExists(*Target.Maya))
        {
            Completion += TEXT("\n服务器同名旧 .ma 已保留且未更新，不属于本次发布结果。");
        }
        if (bNotifyMaya)
        {
            Completion += TEXT("\n本次未生成 .ma，已跳过通知 Maya 打开。");
        }
    }
    DialogState->bWarning = !PublishResult.bMayaPublished;
    if (bNotifyMaya && PublishResult.bMayaPublished)
    {
        FString MayaMessage;
        const bool bMayaOk = CGToolsPublisher::OpenPublishedMayaScene(Target.Maya, MayaMessage);
        Completion += TEXT("\n\n") + MayaMessage;
        if (!bMayaOk)
        {
            DialogState->bWarning = true;
            Completion += TEXT("\n\n三个动画文件均已发布成功。可在 Maya 中直接打开上述 .ma，无需重新发布或烘焙。");
        }
    }
    DialogState->Completion = Completion;
    if (!DialogState->bBatchExecution) { FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Completion)); }
    DialogState->Result = ECGToolsPublisherDialogResult::Published;
    CloseWindow();
    return FReply::Handled();
}

FReply SCGToolsAnimationPublisherWindow::OnCancel()
{
    if (!bPublishing)
    {
        CloseWindow();
    }
    return FReply::Handled();
}

void SCGToolsAnimationPublisherWindow::CloseWindow()
{
    if (DialogState->bEmbedded) { return; }
    const TSharedPtr<SWindow> Window = FSlateApplication::Get().FindWidgetWindow(AsShared());
    if (Window.IsValid())
    {
        FSlateApplication::Get().RequestDestroyWindow(Window.ToSharedRef());
    }
}

FCGToolsPublisherSharedSettings SCGToolsAnimationPublisherWindow::GetSharedSettings() const
{
    FCGToolsPublisherSharedSettings Settings;
    Settings.Project = SelectedProject.IsValid() ? *SelectedProject : FString();
    Settings.Type = SelectedType.IsValid() ? *SelectedType : FString();
    Settings.bNotifyMaya = bNotifyMaya;
    return Settings;
}

void SCGToolsAnimationPublisherWindow::ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings)
{
    const TSharedPtr<FString>* Project = ProjectOptions.FindByPredicate(
        [&Settings](const TSharedPtr<FString>& Item) { return *Item == Settings.Project; });
    ProjectCombo->SetSelectedItem(Project ? *Project : nullptr);
    const TSharedPtr<FString>* Type = TypeOptions.FindByPredicate(
        [&Settings](const TSharedPtr<FString>& Item) { return *Item == Settings.Type; });
    TypeCombo->SetSelectedItem(Type ? *Type : nullptr);
    bNotifyMaya = Settings.bNotifyMaya;
}

FString SCGToolsAnimationPublisherWindow::GetPerAssetSettingsKey() const
{
    const FString Name = AssetNameTextBox->GetText().ToString();
    return FString::Printf(TEXT("%d:"), Name.Len()) + Name + ActionNameTextBox->GetText().ToString();
}

bool SCGToolsAnimationPublisherWindow::ValidateBatch(FString& OutDestination, FString& OutError)
{
    OutDestination.Reset();
    OutError = ConfigError;
    if (!OutError.IsEmpty()) { return false; }
    if (!SelectedProject.IsValid() || !SelectedType.IsValid())
    { OutError = TEXT("请选择项目和类型。"); return false; }
    UAnimSequence* Animation = Cast<UAnimSequence>(AssetData.GetAsset());
    if (!Animation || !Animation->GetSkeleton())
    { OutError = TEXT("所选动画不存在或没有有效骨架。"); return false; }
    FAnimationTarget Target;
    if (!BuildAnimationTarget(AnimationProjectRoot, *SelectedProject, *SelectedType,
        AssetNameTextBox->GetText().ToString(), ActionNameTextBox->GetText().ToString(), Target, OutError))
    { return false; }
    OutDestination = Target.Uasset;
    return true;
}

FReply SCGToolsAnimationPublisherWindow::OnSkip()
{
    if (!bPublishing && DialogState->IsBatch())
    {
        DialogState->Result = ECGToolsPublisherDialogResult::Skipped;
        CloseWindow();
    }
    return FReply::Handled();
}

#if WITH_DEV_AUTOMATION_TESTS

namespace
{
    // Native regressions exercise real UE export and server-file transactions;
    // the licensed Maya process boundary is covered by isolated Python tests.
    FCGToolsDatabaseResult ExistingAnimationAssetFixture(const FString& Project, const FString& AssetName)
    {
        FCGToolsDatabaseResult Result;
        Result.bOk = true;
        Result.bExists = Project == TEXT("GOF")
            && (AssetName == TEXT("Hero") || AssetName == TEXT("BaSiTeV4"));
        return Result;
    }

    FCGToolsDatabaseResult MissingAnimationAssetFixture(const FString&, const FString&)
    {
        FCGToolsDatabaseResult Result;
        Result.bOk = true;
        return Result;
    }

    bool SaveMayaArchiveFixture(const FString& ObjectPath, const FString& Filename, FString& OutError)
    {
        return FFileHelper::SaveStringToFile(TEXT("//Maya ASCII 2022 scene\n// isolated native publication fixture\n"),
            *Filename, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsAnimationRulesTest, "CGTools.Publisher.Animation.ConfigAndTargetValidation",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsAnimationRulesTest::RunTest(const FString& Parameters)
{
    const FString TestRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir()
        / TEXT("CGToolsPublisher/Tests") / FGuid::NewGuid().ToString(EGuidFormats::Digits));
    IFileManager& Files = IFileManager::Get();
    Files.MakeDirectory(*TestRoot, true);
    ON_SCOPE_EXIT { Files.DeleteDirectory(*TestRoot, false, true); };
    const FString Config = TestRoot / TEXT("commonSetting.json");
    FFileHelper::SaveStringToFile(TEXT("{\"DataBase\":[\"GOF\",\"BenBen\",\"GOF\"]}"), *Config);
    TArray<FString> Projects;
    FString Error;
    TestTrue(TEXT("Read DataBase without requiring database host or other settings"), ReadAnimationProjects(Config, Projects, Error));
    TestEqual(TEXT("Duplicate projects appear once"), Projects.Num(), 2);
    TestEqual(TEXT("GOF is available"), Projects[0], FString(TEXT("GOF")));
    FFileHelper::SaveStringToFile(TEXT("{\"DataBase\":[]}"), *Config);
    TestFalse(TEXT("Reject an empty project list"), ReadAnimationProjects(Config, Projects, Error));
    FFileHelper::SaveStringToFile(TEXT("not JSON"), *Config);
    TestFalse(TEXT("Reject malformed configuration"), ReadAnimationProjects(Config, Projects, Error));
    TestFalse(TEXT("Report an unavailable config"), ReadAnimationProjects(TestRoot / TEXT("missing.json"), Projects, Error));

    FAnimationTarget Target;
    TestFalse(TEXT("Missing project fails"), BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Error identifies the project"), Error.Contains(TEXT("项目不存在")));
    TestFalse(TEXT("Missing project is not created"), Files.DirectoryExists(*(TestRoot / TEXT("GOF"))));
    Files.MakeDirectory(*(TestRoot / TEXT("GOF")), true);
    TestFalse(TEXT("Database entry without an Assets directory fails"), BuildAnimationTarget(TestRoot,
        TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Error identifies the missing asset and Assets path"),
        Error.Contains(TEXT("找不到资产“Hero”")) && Error.Contains(TEXT("Assets/Characters/Hero")));
    const FString AnimationDirectory = TestRoot / TEXT("GOF/Animations/Characters/Hero");
    Files.MakeDirectory(*AnimationDirectory, true);
    TestFalse(TEXT("An old Animations directory cannot replace a missing Assets directory"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    Files.DeleteDirectory(*(TestRoot / TEXT("GOF/Animations")), false, true);
    const FString AssetDirectory = TestRoot / TEXT("GOF/Assets/Characters/Hero");
    Files.MakeDirectory(*AssetDirectory, true);
    TestFalse(TEXT("An Assets directory without a database entry fails"), BuildAnimationTarget(TestRoot,
        TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("Walk"), Target, Error, &MissingAnimationAssetFixture));
    TestTrue(TEXT("Missing database entry identifies the asset and database"),
        Error.Contains(TEXT("找不到资产“Hero”")) && Error.Contains(TEXT("数据库")));
    const auto UnavailableDatabase = +[](const FString&, const FString&) -> FCGToolsDatabaseResult
    {
        FCGToolsDatabaseResult Result;
        Result.Error = TEXT("isolated database unavailable");
        return Result;
    };
    TestFalse(TEXT("A database connection failure blocks publication"), BuildAnimationTarget(TestRoot,
        TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("Walk"), Target, Error, UnavailableDatabase));
    TestTrue(TEXT("Database failure preserves the actual reason"), Error.Contains(TEXT("isolated database unavailable")));
    TestFalse(TEXT("Failed checks create no animation hierarchy"), Files.DirectoryExists(*(TestRoot / TEXT("GOF/Animations"))));
    TestTrue(TEXT("Assets directory and database entry permit the first animation publication"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("走路_01"), Target, Error, &ExistingAnimationAssetFixture));
    TestEqual(TEXT("Output matches requested animation library path"), Target.Directory, AnimationDirectory / TEXT("Action"));
    TestEqual(TEXT("The recheck uses the Assets directory"), Target.AssetDirectory, AssetDirectory);
    TestEqual(TEXT("Maya archive shares the publish basename"), Target.Maya, Target.Directory / TEXT("Hero_走路_01.ma"));
    TestFalse(TEXT("Validation does not create the Action folder before Yes"), Files.DirectoryExists(*Target.Directory));
    TestFalse(TEXT("Validation does not create Animations before Yes"), Files.DirectoryExists(*(TestRoot / TEXT("GOF/Animations"))));
    Files.MakeDirectory(*Target.Maya, true);
    TestFalse(TEXT("A directory occupying the .ma path rejects publication"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), TEXT("走路_01"), Target, Error, &ExistingAnimationAssetFixture));
    Files.DeleteDirectory(*Target.Maya, false, true);
    TestEqual(TEXT("Output combines asset and editable action name"), Target.BaseName, FString(TEXT("Hero_走路_01")));
    for (const FString& Invalid : { FString(), FString(TEXT("../outside")), FString(TEXT("A\\B")),
        FString(TEXT("A:B")), FString(TEXT("name.")), FString(TEXT(" name")), FString(TEXT("CON")), FString(TEXT("LPT1.txt")) })
    {
        TestFalse(TEXT("Reject invalid action names"), BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("Hero"), Invalid, Target, Error, &ExistingAnimationAssetFixture));
    }
    TestFalse(TEXT("Reject an invalid type"), BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Scenes"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    TestFalse(TEXT("Characters cannot publish under a missing Props asset directory"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Props"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    Files.MakeDirectory(*(TestRoot / TEXT("GOF/Assets/Props/Hero")), true);
    TestTrue(TEXT("Props use the same existence and auto-create rules"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Props"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    Files.MakeDirectory(*(TestRoot / TEXT("GOF/Animations/Props")), true);
    FFileHelper::SaveStringToFile(TEXT("occupied ancestor"), *(TestRoot / TEXT("GOF/Animations/Props/Hero")));
    TestFalse(TEXT("A file occupying a missing animation ancestor is reported before baking"),
        BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Props"), TEXT("Hero"), TEXT("Walk"), Target, Error, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Ancestor collision gives its location"), Error.Contains(TEXT("Animations/Props/Hero")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsAnimationExportTest, "CGTools.Publisher.Animation.ExportCopyAndPreserveSource",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsAnimationExportTest::RunTest(const FString& Parameters)
{
    const FString Id = FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString SourceRoot = TEXT("/Game/__CGToolsAnimationTest_") + Id;
    const FString SourceDirectory = FPackageName::LongPackageNameToFilename(SourceRoot);
    const FString TestRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests") / Id);
    IFileManager& Files = IFileManager::Get();
    ON_SCOPE_EXIT
    {
        Files.DeleteDirectory(*TestRoot, false, true);
        Files.DeleteDirectory(*SourceDirectory, false, true);
    };
    UPackage* SkeletonPackage = CreatePackage(*(SourceRoot / TEXT("BaSiTeV4_Skeleton")));
    USkeleton* Skeleton = NewObject<USkeleton>(SkeletonPackage, TEXT("BaSiTeV4_Skeleton"), RF_Public | RF_Standalone);
    {
        FReferenceSkeletonModifier Modifier(Skeleton);
        Modifier.Add(FMeshBoneInfo(TEXT("root"), TEXT("root"), INDEX_NONE), FTransform::Identity);
    }
    UPackage* AnimationPackage = CreatePackage(*(SourceRoot / TEXT("A_Source")));
    UAnimSequenceFactory* Factory = NewObject<UAnimSequenceFactory>();
    Factory->TargetSkeleton = Skeleton;
    UAnimSequence* Animation = Cast<UAnimSequence>(Factory->FactoryCreateNew(UAnimSequence::StaticClass(),
        AnimationPackage, TEXT("A_Source"), RF_Public | RF_Standalone, nullptr, GWarn));
    if (!TestNotNull(TEXT("Create animation fixture"), Animation))
    {
        return false;
    }
    IAnimationDataController& Controller = Animation->GetController();
    Controller.OpenBracket(LOCTEXT("Fixture", "Create animation publishing fixture"), false);
    Controller.SetFrameRate(FFrameRate(30, 1), false);
    Controller.SetNumberOfFrames(2, false);
    Controller.AddBoneCurve(TEXT("root"), false);
    Controller.SetBoneTrackKeys(TEXT("root"),
        TArray<FVector3f>({ FVector3f::ZeroVector, FVector3f(10, 0, 0), FVector3f(20, 0, 0) }),
        TArray<FQuat4f>({ FQuat4f::Identity, FQuat4f::Identity, FQuat4f::Identity }),
        TArray<FVector3f>({ FVector3f::OneVector, FVector3f::OneVector, FVector3f::OneVector }), false);
    Controller.NotifyPopulated();
    Controller.CloseBracket(false);

    // Reproduce a part mesh named C on the BaSiTeV4 skeleton reported by the user.
    UPackage* PreviewPackage = CreatePackage(*(SourceRoot / TEXT("Preview")));
    USkeletalMesh* Mesh = NewObject<USkeletalMesh>(PreviewPackage, TEXT("C"), RF_Transient);
    Mesh->SetSkeleton(Skeleton);
    Mesh->GetRefSkeleton() = Skeleton->GetReferenceSkeleton();
    Animation->SetPreviewMesh(Mesh, false);
    TestTrue(TEXT("FBX still resolves the animation's actual preview mesh"), ResolveAnimationMesh(Animation) == Mesh);
    TestEqual(TEXT("Publishing asset name comes from the skeleton, not preview mesh C"),
        ResolveAnimationAssetName(Animation), FString(TEXT("BaSiTeV4")));
    Animation->SetPreviewMesh(nullptr, false);
    Skeleton->SetPreviewMesh(Mesh, false);
    TestTrue(TEXT("Skeleton preview supplies the associated mesh when animation preview is absent"), ResolveAnimationMesh(Animation) == Mesh);
    TestEqual(TEXT("Skeleton preview mesh C does not override the publishing name"),
        ResolveAnimationAssetName(Animation), FString(TEXT("BaSiTeV4")));
    Skeleton->SetPreviewMesh(nullptr, false);
    TestEqual(TEXT("The publishing name is available even without a preview mesh"),
        ResolveAnimationAssetName(Animation), FString(TEXT("BaSiTeV4")));

    Skeleton->MarkPackageDirty();
    Animation->MarkPackageDirty();
    if (!TestTrue(TEXT("Save actual source packages"), UEditorLoadingAndSavingUtils::SavePackages({ SkeletonPackage, AnimationPackage }, false)))
    {
        return false;
    }
    const FString SourceFile = FPackageName::LongPackageNameToFilename(AnimationPackage->GetName(), TEXT(".uasset"));
    const FString OriginalPath = Animation->GetPathName();
    const FMD5Hash OriginalHash = FMD5Hash::HashFile(*SourceFile);
    Animation->SetPreviewMesh(Mesh, false);
    Files.MakeDirectory(*(TestRoot / TEXT("GOF/Assets/Characters/BaSiTeV4")), true);
    FAnimationTarget Target;
    FString Error;
    if (!TestTrue(TEXT("Resolve local publish target from the skeleton asset name"), BuildAnimationTarget(TestRoot,
        TEXT("GOF"), TEXT("Characters"), ResolveAnimationAssetName(Animation), TEXT("QCZM_Idle"), Target, Error, &ExistingAnimationAssetFixture)))
    {
        AddError(Error);
        return false;
    }
    TestEqual(TEXT("Published filename uses BaSiTeV4 instead of C"), Target.BaseName, FString(TEXT("BaSiTeV4_QCZM_Idle")));
    TestFalse(TEXT("First publication starts without an Animations directory"), Files.DirectoryExists(*(TestRoot / TEXT("GOF/Animations"))));
    FAnimationPublishResult PublishResult;
    if (!TestTrue(TEXT("Export real animated FBX, save uasset and commit Maya archive"),
        PublishAnimation(Animation, Target, Error, PublishResult, &SaveMayaArchiveFixture, &ExistingAnimationAssetFixture)))
    {
        AddError(Error);
        return false;
    }
    TestEqual(TEXT("Source object remains at original path"), Animation->GetPathName(), OriginalPath);
    TestTrue(TEXT("Source preview mesh is preserved"), static_cast<const UAnimationAsset*>(Animation)->GetPreviewMesh() == Mesh);
    TestTrue(TEXT("Source file is unchanged"), OriginalHash == FMD5Hash::HashFile(*SourceFile));
    TestTrue(TEXT("First publication creates Animations/type/asset/Action recursively"), Files.DirectoryExists(*Target.Directory));
    // Check overwrite before loading the output: LoadPackage can keep its file
    // open on Windows, which would prevent this test's own server-file copy.
    TestTrue(TEXT("Confirmed overwrite can replace all three output files"),
        PublishAnimation(Animation, Target, Error, PublishResult, &SaveMayaArchiveFixture, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Overwrite still preserves source file"), OriginalHash == FMD5Hash::HashFile(*SourceFile));
    TestTrue(TEXT("Maya archive is committed without requiring the UI open checkbox"), Files.FileSize(*Target.Maya) > 0);
    TestTrue(TEXT("Successful bake is marked as a current Maya publication"), PublishResult.bMayaPublished);
    FFileHelper::SaveStringToFile(TEXT("old uasset sentinel"), *Target.Uasset);
    FFileHelper::SaveStringToFile(TEXT("old FBX sentinel"), *Target.Fbx);
    const FMD5Hash OldUassetHash = FMD5Hash::HashFile(*Target.Uasset);
    const FMD5Hash OldFbxHash = FMD5Hash::HashFile(*Target.Fbx);
    const FMD5Hash PublishedMayaHash = FMD5Hash::HashFile(*Target.Maya);
    const auto FailMayaBake = +[](const FString&, const FString& Filename, FString& BakeError) -> bool
    {
        FFileHelper::SaveStringToFile(TEXT("partial failed Maya output"), *Filename);
        BakeError = TEXT("isolated bake failure");
        return false;
    };
    TestTrue(TEXT("Bake failure still publishes uasset and FBX"),
        PublishAnimation(Animation, Target, Error, PublishResult, FailMayaBake, &ExistingAnimationAssetFixture));
    TestFalse(TEXT("A retained old scene is not marked as a current Maya publication"), PublishResult.bMayaPublished);
    TestTrue(TEXT("Bake failure is explained separately"), PublishResult.MayaWarning.Contains(TEXT("isolated bake failure")));
    TestTrue(TEXT("Warning includes the Maya target"), PublishResult.MayaWarning.Contains(Target.Maya));
    TestTrue(TEXT("Nonfatal Maya failure is not a fatal publishing error"), Error.IsEmpty());
    TestTrue(TEXT("Bake failure still replaces the old uasset"), OldUassetHash != FMD5Hash::HashFile(*Target.Uasset));
    TestTrue(TEXT("Bake failure still replaces the old FBX"), OldFbxHash != FMD5Hash::HashFile(*Target.Fbx));
    TestTrue(TEXT("Bake failure preserves the previous Maya archive"), PublishedMayaHash == FMD5Hash::HashFile(*Target.Maya));
    FAnimationTarget FreshTarget;
    TestTrue(TEXT("Resolve fresh target for failed bake"), BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"),
        TEXT("BaSiTeV4"), TEXT("BakeFailedFresh"), FreshTarget, Error, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("A fresh publish also succeeds when Maya baking fails"),
        PublishAnimation(Animation, FreshTarget, Error, PublishResult, FailMayaBake, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Fresh publish has a uasset"), Files.FileSize(*FreshTarget.Uasset) > 0);
    TestTrue(TEXT("Fresh publish has an FBX"), Files.FileSize(*FreshTarget.Fbx) > 0);
    TestFalse(TEXT("A failed partial Maya output is never uploaded"), Files.FileExists(*FreshTarget.Maya));
    TestFalse(TEXT("Fresh failed bake cannot trigger Maya opening"), PublishResult.bMayaPublished);
    const FMD5Hash CommittedUassetHash = FMD5Hash::HashFile(*Target.Uasset);
    TestFalse(TEXT("Removing the database entry after confirmation blocks the final commit"),
        PublishAnimation(Animation, Target, Error, PublishResult, &SaveMayaArchiveFixture, &MissingAnimationAssetFixture));
    TestTrue(TEXT("Recheck failure identifies the missing asset"), Error.Contains(TEXT("找不到资产“BaSiTeV4”")));
    TestTrue(TEXT("A failed database recheck preserves published files"), CommittedUassetHash == FMD5Hash::HashFile(*Target.Uasset));
    Files.DeleteDirectory(*Target.AssetDirectory, false, true);
    TestFalse(TEXT("Removing Assets during publication also blocks the final commit"),
        PublishAnimation(Animation, Target, Error, PublishResult, &SaveMayaArchiveFixture, &ExistingAnimationAssetFixture));
    TestTrue(TEXT("Missing Assets recheck gives the source asset path"), Error.Contains(Target.AssetDirectory));
    TestTrue(TEXT("A failed directory recheck preserves published files"), CommittedUassetHash == FMD5Hash::HashFile(*Target.Uasset));
    Files.MakeDirectory(*Target.AssetDirectory, true);
    const FString MountRoot = TEXT("/CGToolsPublishedTest_") + Id + TEXT("/");
    FPackageName::RegisterMountPoint(MountRoot, TestRoot + TEXT("/"));
    ON_SCOPE_EXIT { FPackageName::UnRegisterMountPoint(MountRoot, TestRoot + TEXT("/")); };
    const FString PublishedPackageName = MountRoot + TEXT("GOF/Animations/Characters/BaSiTeV4/Action/") + Target.BaseName;
    UPackage* PublishedPackage = LoadPackage(nullptr, *PublishedPackageName, LOAD_None);
    UAnimSequence* PublishedAnimation = PublishedPackage
        ? FindObject<UAnimSequence>(PublishedPackage, *Target.BaseName) : nullptr;
    if (!TestNotNull(TEXT("Published filename resolves to a matching animation object"), PublishedAnimation))
    {
        return false;
    }
    TestTrue(TEXT("Published animation qualifies for Content Browser display"), FAssetData(PublishedAnimation).IsUAsset());
    TestTrue(TEXT("Published animation preserves its skeleton dependency"), PublishedAnimation->GetSkeleton() == Skeleton);
    TestEqual(TEXT("Published animation preserves its duration"), PublishedAnimation->GetPlayLength(), Animation->GetPlayLength());
    TestEqual(TEXT("Published animation preserves sampled keys"), PublishedAnimation->GetNumberOfSampledKeys(), Animation->GetNumberOfSampledKeys());
    TestTrue(TEXT("Published FBX is nonempty"), Files.FileSize(*Target.Fbx) > 1000);
    TArray<uint8> Fbx;
    FFileHelper::LoadFileToArray(Fbx, *Target.Fbx);
    const auto HasBytes = [&Fbx](const ANSICHAR* Text)
    {
        const int32 Length = FCStringAnsi::Strlen(Text);
        for (int32 Index = 0; Index + Length <= Fbx.Num(); ++Index)
        {
            if (FMemory::Memcmp(Fbx.GetData() + Index, Text, Length) == 0)
            {
                return true;
            }
        }
        return false;
    };
    TestTrue(TEXT("Export is an FBX document"), HasBytes("Kaydara FBX Binary"));
    TestTrue(TEXT("FBX contains animation curves"), HasBytes("AnimationCurve"));
    TestTrue(TEXT("FBX contains animated key times"), HasBytes("KeyTime"));
    TestTrue(TEXT("FBX contains the animated skeleton bone"), HasBytes("root"));
    FString RealFixturePath;
    if (FParse::Value(FCommandLine::Get(), TEXT("CGToolsAnimationFixture="), RealFixturePath))
    {
        UAnimSequence* RealAnimation = LoadObject<UAnimSequence>(nullptr, *RealFixturePath);
        if (!TestNotNull(TEXT("Load optional real production animation fixture"), RealAnimation))
        {
            return false;
        }
        const FString RealSource = FPackageName::LongPackageNameToFilename(RealAnimation->GetOutermost()->GetName(), TEXT(".uasset"));
        const FMD5Hash RealSourceHash = FMD5Hash::HashFile(*RealSource);
        FAnimationTarget RealTarget;
        if (!BuildAnimationTarget(TestRoot, TEXT("GOF"), TEXT("Characters"), TEXT("BaSiTeV4"),
                TEXT("PublishedRealFixture"), RealTarget, Error, &ExistingAnimationAssetFixture)
            || !PublishAnimation(RealAnimation, RealTarget, Error, PublishResult, &SaveMayaArchiveFixture, &ExistingAnimationAssetFixture))
        {
            AddError(Error);
            return false;
        }
        const FString RealOutputPackageName = MountRoot + TEXT("GOF/Animations/Characters/BaSiTeV4/Action/") + RealTarget.BaseName;
        UPackage* RealOutputPackage = LoadPackage(nullptr, *RealOutputPackageName, LOAD_None);
        UAnimSequence* RealOutput = RealOutputPackage
            ? FindObject<UAnimSequence>(RealOutputPackage, *RealTarget.BaseName) : nullptr;
        if (!TestNotNull(TEXT("Reload correctly named real production output"), RealOutput))
        {
            return false;
        }
        TestTrue(TEXT("Real production output qualifies for Content Browser"), FAssetData(RealOutput).IsUAsset());
        TestTrue(TEXT("Real production output retains its skeleton"), RealOutput->GetSkeleton() == RealAnimation->GetSkeleton());
        TestTrue(TEXT("Real production output retains its preview mesh"),
            static_cast<const UAnimationAsset*>(RealOutput)->GetPreviewMesh() == ResolveAnimationMesh(RealAnimation));
        TestEqual(TEXT("Real production output retains its duration"), RealOutput->GetPlayLength(), RealAnimation->GetPlayLength());
        TestEqual(TEXT("Real production output retains its samples"), RealOutput->GetNumberOfSampledKeys(), RealAnimation->GetNumberOfSampledKeys());
        TestTrue(TEXT("Real production source file remains unchanged"), RealSourceHash == FMD5Hash::HashFile(*RealSource));
        TestTrue(TEXT("Real production FBX is nonempty"), Files.FileSize(*RealTarget.Fbx) > 1000);
        AddInfo(TEXT("Real production animation published and independently reloaded with a matching primary asset name."));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsAnimationRollbackTest, "CGTools.Publisher.Animation.RestoreAllOutputsOnFailure",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsAnimationRollbackTest::RunTest(const FString& Parameters)
{
    const FString TestRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("CGToolsPublisher/Tests")
        / FGuid::NewGuid().ToString(EGuidFormats::Digits));
    const FString Staging = TestRoot / TEXT("Staging");
    IFileManager& Files = IFileManager::Get();
    Files.MakeDirectory(*Staging, true);
    ON_SCOPE_EXIT { Files.DeleteDirectory(*TestRoot, false, true); };
    FAnimationTarget Target;
    Target.Directory = TestRoot / TEXT("Action");
    Target.Uasset = Target.Directory / TEXT("Hero_Walk.uasset");
    Target.Fbx = Target.Directory / TEXT("Hero_Walk.fbx");
    Target.Maya = Target.Directory / TEXT("Hero_Walk.ma");
    Files.MakeDirectory(*Target.Directory, true);
    FFileHelper::SaveStringToFile(TEXT("original uasset"), *Target.Uasset);
    FFileHelper::SaveStringToFile(TEXT("original FBX"), *Target.Fbx);
    FFileHelper::SaveStringToFile(TEXT("original Maya"), *Target.Maya);
    const FMD5Hash UassetHash = FMD5Hash::HashFile(*Target.Uasset);
    const FMD5Hash FbxHash = FMD5Hash::HashFile(*Target.Fbx);
    const FMD5Hash MayaHash = FMD5Hash::HashFile(*Target.Maya);
    FFileHelper::SaveStringToFile(TEXT("new uasset"), *(Staging / TEXT("Animation.uasset")));
    // A missing second input forces an I/O failure after the first output was written.
    FString Error;
    TestFalse(TEXT("A failed second file prevents a successful publish"), CommitAnimationFiles(Target, Staging, Error));
    TestTrue(TEXT("First overwritten output is restored"), UassetHash == FMD5Hash::HashFile(*Target.Uasset));
    TestTrue(TEXT("Second output is preserved or restored"), FbxHash == FMD5Hash::HashFile(*Target.Fbx));
    TestTrue(TEXT("Third output remains unchanged"), MayaHash == FMD5Hash::HashFile(*Target.Maya));
    const FString ThirdFailureStaging = TestRoot / TEXT("ThirdFailure");
    Files.MakeDirectory(*ThirdFailureStaging, true);
    FFileHelper::SaveStringToFile(TEXT("new uasset"), *(ThirdFailureStaging / TEXT("Animation.uasset")));
    FFileHelper::SaveStringToFile(TEXT("new FBX"), *(ThirdFailureStaging / TEXT("Animation.fbx")));
    TestFalse(TEXT("Missing Maya input rolls back two written outputs"), CommitAnimationFiles(Target, ThirdFailureStaging, Error));
    TestTrue(TEXT("Third-file failure restores uasset"), UassetHash == FMD5Hash::HashFile(*Target.Uasset));
    TestTrue(TEXT("Third-file failure restores FBX"), FbxHash == FMD5Hash::HashFile(*Target.Fbx));
    TestTrue(TEXT("Third-file failure preserves Maya"), MayaHash == FMD5Hash::HashFile(*Target.Maya));
    const FString PairFailureStaging = TestRoot / TEXT("PairFailure");
    Files.MakeDirectory(*PairFailureStaging, true);
    FFileHelper::SaveStringToFile(TEXT("new uasset"), *(PairFailureStaging / TEXT("Animation.uasset")));
    TestFalse(TEXT("Required FBX failure still fails when Maya is excluded"),
        CommitAnimationFiles(Target, PairFailureStaging, Error, false));
    TestTrue(TEXT("Pair-only failure restores uasset"), UassetHash == FMD5Hash::HashFile(*Target.Uasset));
    TestTrue(TEXT("Pair-only failure preserves FBX"), FbxHash == FMD5Hash::HashFile(*Target.Fbx));
    TestTrue(TEXT("Pair-only failure never changes the old Maya scene"), MayaHash == FMD5Hash::HashFile(*Target.Maya));
    Files.Delete(*Target.Uasset);
    Files.Delete(*Target.Fbx);
    Files.Delete(*Target.Maya);
    TestFalse(TEXT("A new publish fails when its Maya input disappears"), CommitAnimationFiles(Target, ThirdFailureStaging, Error));
    TestFalse(TEXT("Failed new publish removes its first partial output"), Files.FileExists(*Target.Uasset));
    TestFalse(TEXT("Failed new publish has no second output"), Files.FileExists(*Target.Fbx));
    TestFalse(TEXT("Failed new publish has no Maya output"), Files.FileExists(*Target.Maya));
    return true;
}

#endif

#undef LOCTEXT_NAMESPACE
