#include "SequencerEaseToolsBPLibrary.h"
#include "MovieScene.h"
#include "MovieSceneBinding.h"
#include "Tracks/MovieScene3DTransformTrack.h"
#include "Sections/MovieScene3DTransformSection.h"
#include "Tracks/MovieScene3DPathTrack.h"
#include "Sections/MovieScene3DPathSection.h"
#include "MovieSceneTrack.h"
#include "MovieSceneFolder.h"
#include "MovieSceneSequence.h"
#include "MovieSceneSpawnable.h"
#include "MovieScenePossessable.h"
#include "Misc/FrameNumber.h"
#include "Misc/FrameRate.h"
#include "Misc/FrameTime.h"
#include "LevelSequence.h"
#include "Engine/StaticMeshActor.h"
#include "Components/StaticMeshComponent.h"
#include "CineCameraActor.h"
#include "CineCameraComponent.h"
#include "Camera/CameraTypes.h"
#include "Channels/MovieSceneDoubleChannel.h"
#include "Channels/MovieSceneFloatChannel.h"
#include "Tracks/MovieSceneFloatTrack.h"
#include "Sections/MovieSceneFloatSection.h"
#include "Tracks/MovieScene3DAttachTrack.h"
#include "Sections/MovieScene3DAttachSection.h"
#include "Bindings/MovieSceneSpawnableActorBinding.h"
#include "Bindings/MovieSceneCustomBinding.h"
#include "MovieSceneBindingReferences.h"
#include "LevelEditorSequencerIntegration.h"
#include "ISequencer.h"

// ============================================================================
// 帧号转换辅助：用户在蓝图里输入的是"显示帧"(DisplayRate)，
// 而 MovieScene 内部 FFrameNumber 存储的是 TickResolution 下的 tick。
// 必须转换，否则 1000 显示帧会被写成 1000 ticks，在界面上只显示为第 1 帧。
// ============================================================================
static FFrameNumber ConvertDisplayFrameToTickFrame(UMovieScene* MovieScene, int32 InDisplayFrame)
{
    if (!MovieScene)
    {
        return FFrameNumber(InDisplayFrame);
    }

    const FFrameRate DisplayRate = MovieScene->GetDisplayRate();
    const FFrameRate TickResolution = MovieScene->GetTickResolution();

    if (DisplayRate == TickResolution)
    {
        return FFrameNumber(InDisplayFrame);
    }

    return ConvertFrameTime(FFrameTime(InDisplayFrame), DisplayRate, TickResolution).RoundToFrame();
}

static int32 ConvertTickFrameToDisplayFrame(UMovieScene* MovieScene, FFrameNumber InTickFrame)
{
    if (!MovieScene)
    {
        return InTickFrame.Value;
    }

    const FFrameRate DisplayRate = MovieScene->GetDisplayRate();
    const FFrameRate TickResolution = MovieScene->GetTickResolution();

    if (DisplayRate == TickResolution)
    {
        return InTickFrame.Value;
    }

    return ConvertFrameTime(FFrameTime(InTickFrame), TickResolution, DisplayRate).RoundToFrame().Value;
}

void USequencerEaseToolsBPLibrary::SetSectionEaseIn(
    UMovieSceneSection* Section,
    int32 FrameCount
)
{
    if (!Section)
    {
        return;
    }

    Section->Modify();

    Section->Easing.bManualEaseIn = true;

    Section->Easing.ManualEaseInDuration = FrameCount;

    Section->MarkAsChanged();
}

void USequencerEaseToolsBPLibrary::SetSectionEaseOut(
    UMovieSceneSection* Section,
    int32 FrameCount
)
{
    if (!Section)
    {
        return;
    }

    Section->Modify();

    Section->Easing.bManualEaseOut = true;

    Section->Easing.ManualEaseOutDuration = FrameCount;

    Section->MarkAsChanged();
}

void USequencerEaseToolsBPLibrary::SetSectionEaseInOut(
    UMovieSceneSection* Section,
    int32 EaseInFrames,
    int32 EaseOutFrames
)
{
    if (!Section)
    {
        return;
    }

    Section->Modify();

    Section->Easing.bManualEaseIn = true;
    Section->Easing.ManualEaseInDuration = EaseInFrames;

    Section->Easing.bManualEaseOut = true;
    Section->Easing.ManualEaseOutDuration = EaseOutFrames;

    Section->MarkAsChanged();
}

void USequencerEaseToolsBPLibrary::AutoSetEaseFromOverlap(
    UMovieSceneSection* SectionA,
    UMovieSceneSection* SectionB
)
{
    if (!SectionA || !SectionB)
    {
        return;
    }

    SectionA->Modify();
    SectionB->Modify();

    TRange<FFrameNumber> RangeA = SectionA->GetRange();
    TRange<FFrameNumber> RangeB = SectionB->GetRange();

    if (!RangeA.HasLowerBound() || !RangeA.HasUpperBound())
    {
        return;
    }

    if (!RangeB.HasLowerBound() || !RangeB.HasUpperBound())
    {
        return;
    }

    int32 AStart = RangeA.GetLowerBoundValue().Value;
    int32 AEnd = RangeA.GetUpperBoundValue().Value;

    int32 BStart = RangeB.GetLowerBoundValue().Value;
    int32 BEnd = RangeB.GetUpperBoundValue().Value;

    int32 OverlapStart = FMath::Max(AStart, BStart);
    int32 OverlapEnd = FMath::Min(AEnd, BEnd);

    int32 OverlapFrames = OverlapEnd - OverlapStart;

    if (OverlapFrames <= 0)
    {
        return;
    }

    SectionA->Easing.bManualEaseOut = true;
    SectionA->Easing.ManualEaseOutDuration = OverlapFrames;

    SectionB->Easing.bManualEaseIn = true;
    SectionB->Easing.ManualEaseInDuration = OverlapFrames;

    SectionA->MarkAsChanged();
    SectionB->MarkAsChanged();
}

void USequencerEaseToolsBPLibrary::CopyTransformBindingInfo(
    const FMovieSceneBindingProxy& SourceBinding,
    const FMovieSceneBindingProxy& TargetBinding,
    bool bCopyFollow
)
{
    if (!SourceBinding.Sequence || !TargetBinding.Sequence)
    {
        return;
    }

    UMovieScene* SourceMovieScene = SourceBinding.Sequence->GetMovieScene();
    UMovieScene* TargetMovieScene = TargetBinding.Sequence->GetMovieScene();

    if (!SourceMovieScene || !TargetMovieScene)
    {
        return;
    }

    FMovieSceneBinding* SourceBindingPtr = SourceMovieScene->FindBinding(SourceBinding.BindingID);
    FMovieSceneBinding* TargetBindingPtr = TargetMovieScene->FindBinding(TargetBinding.BindingID);

    if (!SourceBindingPtr || !TargetBindingPtr)
    {
        return;
    }

    UMovieScene3DTransformTrack* SourceTransformTrack = nullptr;
    for (UMovieSceneTrack* Track : SourceBindingPtr->GetTracks())
    {
        SourceTransformTrack = Cast<UMovieScene3DTransformTrack>(Track);
        if (SourceTransformTrack)
        {
            break;
        }
    }

    if (!SourceTransformTrack)
    {
        return;
    }

    UMovieScene3DTransformTrack* TargetTransformTrack = nullptr;
    for (UMovieSceneTrack* Track : TargetBindingPtr->GetTracks())
    {
        TargetTransformTrack = Cast<UMovieScene3DTransformTrack>(Track);
        if (TargetTransformTrack)
        {
            break;
        }
    }

    if (!TargetTransformTrack)
    {
        TargetTransformTrack = NewObject<UMovieScene3DTransformTrack>(TargetMovieScene, NAME_None, RF_Transactional);
        TargetBindingPtr->AddTrack(*TargetTransformTrack, TargetMovieScene);
    }

    TargetMovieScene->Modify();

    // 复制一份，避免 RemoveSection 改动轨道内部数组导致 range-for 迭代器失效(触发 Array.h 的 Ensure)
    TArray<UMovieSceneSection*> TargetSections = TargetTransformTrack->GetAllSections();
    for (UMovieSceneSection* Section : TargetSections)
    {
        TargetTransformTrack->RemoveSection(*Section);
    }

    // 逐通道复制 transform 关键帧（时间 + 值 + 默认值）。
    // 注意：不能直接 DuplicateObject 整个 Section —— 其 ChannelProxy 缓存仍指向源 Section 的通道指针，
    // 加到目标 Track 后求值回退到默认(0/0/1)。这里显式复制每个 double 通道的键数据。
    auto CopyTransformSection = [](UMovieScene3DTransformSection* Dst, const UMovieScene3DTransformSection* Src)
    {
        if (!Dst || !Src)
        {
            return;
        }
        Dst->SetRange(Src->GetRange());

        FMovieSceneChannelProxy& SrcProxy = Src->GetChannelProxy();
        FMovieSceneChannelProxy& DstProxy = Dst->GetChannelProxy();
        const int32 NumChannels = FMath::Min(SrcProxy.NumChannels(), DstProxy.NumChannels());
        for (int32 i = 0; i < NumChannels; ++i)
        {
            FMovieSceneDoubleChannel* SrcCh = SrcProxy.GetChannel<FMovieSceneDoubleChannel>(i);
            FMovieSceneDoubleChannel* DstCh = DstProxy.GetChannel<FMovieSceneDoubleChannel>(i);
            if (!SrcCh || !DstCh)
            {
                continue;
            }

            DstCh->Reset();
            if (SrcCh->GetDefault().IsSet())
            {
                DstCh->SetDefault(SrcCh->GetDefault().GetValue());
            }

            TArrayView<const FFrameNumber> Times = SrcCh->GetTimes();
            TArrayView<const FMovieSceneDoubleValue> Values = SrcCh->GetValues();
            const int32 N = FMath::Min(Times.Num(), Values.Num());
            if (N > 0)
            {
                TArray<FFrameNumber> KeyTimes;
                KeyTimes.Reserve(N);
                TArray<FMovieSceneDoubleValue> KeyValues;
                KeyValues.Reserve(N);
                for (int32 k = 0; k < N; ++k)
                {
                    KeyTimes.Add(Times[k]);
                    KeyValues.Add(Values[k]);
                }
                DstCh->AddKeys(KeyTimes, KeyValues);
            }
        }
        Dst->InvalidateChannelProxy();
    };

    const TArray<UMovieSceneSection*>& SourceSections = SourceTransformTrack->GetAllSections();
    for (UMovieSceneSection* SourceSection : SourceSections)
    {
        UMovieScene3DTransformSection* TransformSection = Cast<UMovieScene3DTransformSection>(SourceSection);
        if (TransformSection)
        {
            UMovieScene3DTransformSection* NewSection = NewObject<UMovieScene3DTransformSection>(TargetTransformTrack, NAME_None, RF_Transactional);
            TargetTransformTrack->AddSection(*NewSection);
            CopyTransformSection(NewSection, TransformSection);
        }
    }

    TargetMovieScene->MarkAsChanged();

    UMovieScene3DPathTrack* SourcePathTrack = nullptr;
    for (UMovieSceneTrack* Track : SourceBindingPtr->GetTracks())
    {
        SourcePathTrack = Cast<UMovieScene3DPathTrack>(Track);
        if (SourcePathTrack)
        {
            break;
        }
    }

    if (SourcePathTrack)
    {
        UMovieScene3DPathTrack* TargetPathTrack = nullptr;
        for (UMovieSceneTrack* Track : TargetBindingPtr->GetTracks())
        {
            TargetPathTrack = Cast<UMovieScene3DPathTrack>(Track);
            if (TargetPathTrack)
            {
                break;
            }
        }

        if (!TargetPathTrack)
        {
            TargetPathTrack = NewObject<UMovieScene3DPathTrack>(TargetMovieScene, NAME_None, RF_Transactional);
            TargetBindingPtr->AddTrack(*TargetPathTrack, TargetMovieScene);
        }

        // 复制一份，避免 RemoveSection 改动轨道内部数组导致 range-for 迭代器失效
        TArray<UMovieSceneSection*> TargetPathSections = TargetPathTrack->GetAllSections();
        for (UMovieSceneSection* Section : TargetPathSections)
        {
            TargetPathTrack->RemoveSection(*Section);
        }

        const TArray<UMovieSceneSection*>& SourcePathSections = SourcePathTrack->GetAllSections();
        for (UMovieSceneSection* SourceSection : SourcePathSections)
        {
            UMovieScene3DPathSection* PathSection = Cast<UMovieScene3DPathSection>(SourceSection);
            if (PathSection)
            {
                UMovieScene3DPathSection* NewSection = DuplicateObject<UMovieScene3DPathSection>(PathSection, TargetPathTrack);
                if (!bCopyFollow)
                {
                    NewSection->bFollow = false;
                }
                TargetPathTrack->AddSection(*NewSection);
                NewSection->InvalidateChannelProxy();
            }
        }

        TargetMovieScene->MarkAsChanged();
    }
}

void USequencerEaseToolsBPLibrary::RemoveSpawnableOrPossessable(
    const FMovieSceneBindingProxy& Binding
)
{
    if (!Binding.Sequence)
    {
        return;
    }

    UMovieScene* MovieScene = Binding.Sequence->GetMovieScene();
    if (!MovieScene)
    {
        return;
    }

    FMovieSceneBinding* BindingPtr = MovieScene->FindBinding(Binding.BindingID);
    if (!BindingPtr)
    {
        return;
    }

    MovieScene->Modify();

    FMovieSceneSpawnable* Spawnable = MovieScene->FindSpawnable(Binding.BindingID);
    if (Spawnable)
    {
        MovieScene->RemoveSpawnable(Binding.BindingID);
    }
    else
    {
        FMovieScenePossessable* Possessable = MovieScene->FindPossessable(Binding.BindingID);
        if (Possessable)
        {
            MovieScene->RemovePossessable(Binding.BindingID);
        }
    }

    MovieScene->MarkAsChanged();
}

void USequencerEaseToolsBPLibrary::MatchSectionLength(
    const FMovieSceneBindingProxy& SourceBinding,
    const FMovieSceneBindingProxy& TargetBinding
)
{
    if (!SourceBinding.Sequence || !TargetBinding.Sequence)
    {
        return;
    }

    UMovieScene* SourceMovieScene = SourceBinding.Sequence->GetMovieScene();
    UMovieScene* TargetMovieScene = TargetBinding.Sequence->GetMovieScene();

    if (!SourceMovieScene || !TargetMovieScene)
    {
        return;
    }

    FMovieSceneBinding* SourceBindingPtr = SourceMovieScene->FindBinding(SourceBinding.BindingID);
    FMovieSceneBinding* TargetBindingPtr = TargetMovieScene->FindBinding(TargetBinding.BindingID);

    if (!SourceBindingPtr || !TargetBindingPtr)
    {
        return;
    }

    TMap<UClass*, TRange<FFrameNumber>> SourceTrackRanges;

    for (UMovieSceneTrack* Track : SourceBindingPtr->GetTracks())
    {
        const TArray<UMovieSceneSection*>& Sections = Track->GetAllSections();
        for (UMovieSceneSection* Section : Sections)
        {
            if (!Section)
            {
                continue;
            }

            TRange<FFrameNumber> SectionRange = Section->GetRange();
            // 跳过空范围，避免污染合并结果
            if (SectionRange.IsEmpty())
            {
                continue;
            }

            UClass* TrackClass = Track->GetClass();

            TRange<FFrameNumber>* ExistingRangePtr = SourceTrackRanges.Find(TrackClass);
            if (ExistingRangePtr)
            {
                // 用 Hull 合并两个范围：可正确处理无限/开放边界(Open)，
                // 直接调用 GetLowerBoundValue/GetUpperBoundValue 在 Open 边界上会触发断言崩溃
                *ExistingRangePtr = TRange<FFrameNumber>::Hull(*ExistingRangePtr, SectionRange);
            }
            else
            {
                SourceTrackRanges.Add(TrackClass, SectionRange);
            }
        }
    }

    TargetMovieScene->Modify();

    for (UMovieSceneTrack* TargetTrack : TargetBindingPtr->GetTracks())
    {
        UClass* TrackClass = TargetTrack->GetClass();

        TRange<FFrameNumber>* TargetRangePtr = SourceTrackRanges.Find(TrackClass);
        if (TargetRangePtr)
        {
            const TArray<UMovieSceneSection*>& TargetSections = TargetTrack->GetAllSections();
            for (UMovieSceneSection* Section : TargetSections)
            {
                Section->Modify();
                Section->SetRange(*TargetRangePtr);
                Section->MarkAsChanged();
            }
        }
    }

    TargetMovieScene->MarkAsChanged();
}

// 公共辅助：在指定 binding 上添加 3D 附加轨道 + 3D 变换轨道，并按 ParentBinding 长度对齐 section。
// 返回 true 表示成功。失败时 TargetMovieScene 保持不变。
static bool AddAttachAndTransformTrackImpl(
    const FMovieSceneBindingProxy& TargetBinding,
    const FMovieSceneBindingProxy& ParentBinding,
    const FTransform& Transform,
    int32 FrameNumber,
    const FString& FolderPath,
    UClass* ExpectedClass,   // 仅用于早返回时的合法性检查（可传 nullptr 表示不检查）
    FMovieSceneBindingProxy& OutReturn
)
{
    OutReturn = FMovieSceneBindingProxy();

    if (!TargetBinding.Sequence || !TargetBinding.BindingID.IsValid())
    {
        return false;
    }
    if (!ParentBinding.Sequence || !ParentBinding.BindingID.IsValid())
    {
        return false;
    }

    UMovieScene* TargetMovieScene = TargetBinding.Sequence->GetMovieScene();
    UMovieScene* ParentMovieScene = ParentBinding.Sequence->GetMovieScene();
    if (!TargetMovieScene || !ParentMovieScene)
    {
        return false;
    }

    FMovieSceneBinding* TargetBindingPtr = TargetMovieScene->FindBinding(TargetBinding.BindingID);
    FMovieSceneBinding* ParentBindingPtr = ParentMovieScene->FindBinding(ParentBinding.BindingID);
    if (!TargetBindingPtr || !ParentBindingPtr)
    {
        return false;
    }

    // === 计算 section 长度：取 ParentBinding 上第一个非空 section 的范围 ===
    TRange<FFrameNumber> SectionRange = TRange<FFrameNumber>::Empty();
    for (UMovieSceneTrack* Track : ParentBindingPtr->GetTracks())
    {
        if (!Track)
        {
            continue;
        }
        for (UMovieSceneSection* Sec : Track->GetAllSections())
        {
            if (Sec && !Sec->GetRange().IsEmpty())
            {
                SectionRange = Sec->GetRange();
                break;
            }
        }
        if (!SectionRange.IsEmpty())
        {
            break;
        }
    }
    if (SectionRange.IsEmpty())
    {
        // ParentBinding 没有任何 section：退回到 MovieScene 的播放范围
        SectionRange = TargetMovieScene->GetPlaybackRange();
        if (SectionRange.IsEmpty())
        {
            SectionRange = TRange<FFrameNumber>(FFrameNumber(0), FFrameNumber(100));
        }
    }

    TargetMovieScene->Modify();

    // === 1. 3D 附加轨道 ===
    UMovieScene3DAttachTrack* AttachTrack = NewObject<UMovieScene3DAttachTrack>(TargetMovieScene, NAME_None, RF_Transactional);
    if (AttachTrack)
    {
        TargetBindingPtr->AddTrack(*AttachTrack, TargetMovieScene);

        UMovieScene3DAttachSection* AttachSection = NewObject<UMovieScene3DAttachSection>(AttachTrack, NAME_None, RF_Transactional);
        if (AttachSection)
        {
            AttachSection->SetRange(SectionRange);
            // 附加目标 = ParentBinding
            FMovieSceneObjectBindingID AttachBindingID = UE::MovieScene::FRelativeObjectBindingID(ParentBinding.BindingID);
            AttachSection->SetConstraintBindingID(AttachBindingID);
            AttachTrack->AddSection(*AttachSection);
        }
    }

    // === 2. 3D 变换轨道 ===
    UMovieScene3DTransformTrack* TransformTrack = NewObject<UMovieScene3DTransformTrack>(TargetMovieScene, NAME_None, RF_Transactional);
    if (TransformTrack)
    {
        TargetBindingPtr->AddTrack(*TransformTrack, TargetMovieScene);

        UMovieScene3DTransformSection* TransformSection = NewObject<UMovieScene3DTransformSection>(TransformTrack, NAME_None, RF_Transactional);
        if (TransformSection)
        {
            TransformSection->SetRange(SectionRange);
            TransformTrack->AddSection(*TransformSection);

            // 在 FrameNumber 处 K 入 Transform（按 location/rotation/scale 9 通道）
            const FFrameNumber KeyFrame = ConvertDisplayFrameToTickFrame(TargetMovieScene, FrameNumber);
            FMovieSceneChannelProxy& Proxy = TransformSection->GetChannelProxy();
            const int32 NumChannels = Proxy.NumChannels();

            #define SAFE_SET_CHANNEL(Index, Value) \
                do { \
                    if ((Index) < NumChannels) { \
                        FMovieSceneDoubleChannel* Ch = Proxy.GetChannel<FMovieSceneDoubleChannel>(Index); \
                        if (Ch) { AddKeyToChannel(Ch, KeyFrame, (Value), EMovieSceneKeyInterpolation::Auto); } \
                    } \
                } while(0)

            const FVector& Loc = Transform.GetLocation();
            SAFE_SET_CHANNEL(0, Loc.X);
            SAFE_SET_CHANNEL(1, Loc.Y);
            SAFE_SET_CHANNEL(2, Loc.Z);

            FRotator Rotator = Transform.GetRotation().Rotator();
            SAFE_SET_CHANNEL(3, Rotator.Roll);
            SAFE_SET_CHANNEL(4, Rotator.Pitch);
            SAFE_SET_CHANNEL(5, Rotator.Yaw);

            const FVector& Scale = Transform.GetScale3D();
            SAFE_SET_CHANNEL(6, Scale.X);
            SAFE_SET_CHANNEL(7, Scale.Y);
            SAFE_SET_CHANNEL(8, Scale.Z);

            #undef SAFE_SET_CHANNEL

            TransformSection->InvalidateChannelProxy();
        }
    }

    // === 3. （可选）把 binding 移到指定文件夹 ===
    if (!FolderPath.IsEmpty())
    {
        TArray<FString> FolderPathStrings;
        FolderPath.ParseIntoArray(FolderPathStrings, TEXT("/"), true);

        TArray<FName> FolderPathNames;
        for (const FString& PathString : FolderPathStrings)
        {
            FolderPathNames.Add(FName(*PathString));
        }

        TArray<UMovieSceneFolder*> RootFolders;
        RootFolders.Append(TargetMovieScene->GetRootFolders());

        UMovieSceneFolder* TargetFolder = UMovieSceneFolder::GetFolderWithPath(FolderPathNames, RootFolders, TargetMovieScene->GetRootFolders());

        if (!TargetFolder)
        {
            TargetFolder = NewObject<UMovieSceneFolder>(TargetMovieScene);
            TargetFolder->SetFolderName(FolderPathNames.Last());

            if (FolderPathNames.Num() > 1)
            {
                TArray<FName> ParentPathNames = FolderPathNames;
                ParentPathNames.RemoveAt(FolderPathNames.Num() - 1);
                UMovieSceneFolder* ParentFolder = UMovieSceneFolder::GetFolderWithPath(ParentPathNames, RootFolders, TargetMovieScene->GetRootFolders());
                if (ParentFolder)
                {
                    ParentFolder->AddChildFolder(TargetFolder);
                }
                else
                {
                    TargetMovieScene->AddRootFolder(TargetFolder);
                }
            }
            else
            {
                TargetMovieScene->AddRootFolder(TargetFolder);
            }
        }

        if (TargetFolder)
        {
            TargetFolder->AddChildObjectBinding(TargetBinding.BindingID);
        }
    }

    TargetMovieScene->MarkAsChanged();

    OutReturn = TargetBinding;
    return true;
}

FMovieSceneBindingProxy USequencerEaseToolsBPLibrary::CreateSpawnableStaticMesh(
    const FMovieSceneBindingProxy& TargetBinding,
    const FMovieSceneBindingProxy& ParentBinding,
    const FTransform& Transform,
    int32 FrameNumber,
    const FString& FolderPath
)
{
    FMovieSceneBindingProxy Out;
    AddAttachAndTransformTrackImpl(TargetBinding, ParentBinding, Transform, FrameNumber, FolderPath, AStaticMeshActor::StaticClass(), Out);
    return Out;
}

FMovieSceneBindingProxy USequencerEaseToolsBPLibrary::CreateSpawnableCineCamera(
    const FMovieSceneBindingProxy& TargetBinding,
    const FMovieSceneBindingProxy& ParentBinding,
    const FTransform& Transform,
    int32 FrameNumber,
    const FString& FolderPath
)
{
    FMovieSceneBindingProxy Out;
    AddAttachAndTransformTrackImpl(TargetBinding, ParentBinding, Transform, FrameNumber, FolderPath, ACineCameraActor::StaticClass(), Out);
    return Out;
}

bool USequencerEaseToolsBPLibrary::SetupCineCameraParams(
    const FMovieSceneBindingProxy& Binding,
    int32 FrameNumber
)
{
    if (!Binding.Sequence || !Binding.BindingID.IsValid())
    {
        return false;
    }

    ULevelSequence* LevelSequence = Cast<ULevelSequence>(Binding.Sequence);
    if (!LevelSequence)
    {
        return false;
    }

    UMovieScene* MovieScene = LevelSequence->GetMovieScene();
    if (!MovieScene)
    {
        return false;
    }

    // 尝试获取 ACineCameraActor 对象模板/实例
    // 路径 1：Spawnable（旧式 / 兼容模式）
    // 路径 2：现代 UE 5.4+ —— "Add Spawnable From Class" 把绑定注册为 Possessable，
    //         但对象模板保存在 UMovieSceneSpawnableActorBinding 轨道上
    ACineCameraActor* CameraActor = nullptr;

    // --- 路径 1：查找 Spawnable ---
    if (FMovieSceneSpawnable* Spawnable = MovieScene->FindSpawnable(Binding.BindingID))
    {
        if (UObject* ObjectTemplate = Spawnable->GetObjectTemplate())
        {
            CameraActor = Cast<ACineCameraActor>(ObjectTemplate);
        }
    }

    // --- 路径 2：现代 UE 5.4+ —— "Add Spawnable From Class" 把绑定注册为自定义绑定
    //         (UMovieSceneSpawnableActorBinding)，对象模板保存在 BindingReferences 中，
    //         而非 Spawnables 数组或 Tracks 中。需通过 GetCustomBinding 遍历获取。
    if (!CameraActor)
    {
        // 注意：ULevelSequence 只 override 了 const GetBindingReferences()，会隐藏基类非 const 重载。
        // 通过基类指针调用以选到非 const 版本（返回 FMovieSceneBindingReferences*）。
        if (FMovieSceneBindingReferences* BindingRefs = static_cast<UMovieSceneSequence*>(LevelSequence)->GetBindingReferences())
        {
            for (int32 Index = 0; ; ++Index)
            {
                UMovieSceneCustomBinding* CustomBinding = BindingRefs->GetCustomBinding(Binding.BindingID, Index);
                if (!CustomBinding)
                {
                    break;
                }
                if (UMovieSceneSpawnableActorBinding* SpawnableBinding = Cast<UMovieSceneSpawnableActorBinding>(CustomBinding))
                {
                    if (UObject* Obj = SpawnableBinding->GetObjectTemplate())
                    {
                        CameraActor = Cast<ACineCameraActor>(Obj);
                        if (CameraActor)
                        {
                            break;
                        }
                    }
                }
            }
        }
    }

    if (!CameraActor)
    {
        return false;
    }

    UCineCameraComponent* CamComp = CameraActor->GetCineCameraComponent();
    if (!CamComp)
    {
        return false;
    }

    // === 只设置用户指定的 4 个值 ===
    auto ApplyCameraParams = [&](UCineCameraComponent* InCamComp, UObject* InOwner)
    {
        if (!InCamComp)
        {
            return;
        }
        InCamComp->Modify();
        if (InOwner)
        {
            InOwner->Modify();
        }

        // --- 胶片背板: Sensor Width / Height ---
        FCameraFilmbackSettings Filmback;
        Filmback.SensorWidth = 22.540001f;
        Filmback.SensorHeight = 20.43f;
        InCamComp->SetFilmback(Filmback);

        // --- 焦距 / 光圈 ---
        InCamComp->SetCurrentFocalLength(80.0f);
        InCamComp->SetCurrentAperture(22.0f);

        UE_LOG(LogTemp, Log, TEXT("SetupCineCameraParams ApplyCameraParams: Owner=%s FocalLength=%.2f Aperture=%.2f"),
            InOwner ? *InOwner->GetName() : TEXT("<none>"),
            InCamComp->CurrentFocalLength,
            InCamComp->CurrentAperture);

        // 广播属性变更通知，让 Details 面板和视口刷新
        FPropertyChangedEvent PropertyChangedEvent(nullptr);
        FCoreUObjectDelegates::OnObjectPropertyChanged.Broadcast(InCamComp, PropertyChangedEvent);
        if (InOwner)
        {
            FCoreUObjectDelegates::OnObjectPropertyChanged.Broadcast(InOwner, PropertyChangedEvent);
        }
    };

    // 辅助：确保 CurrentFocalLength / CurrentAperture 属性轨道存在，并将其默认值/关键帧设为目标值。
    // 注意：这些属性属于 UCineCameraComponent，所以轨道必须建在 CameraComponent 子绑定上（裸名路径）。
    // 千万不要在 Actor 绑定上建 "CameraComponent.CurrentFocalLength" 跨组件轨道——销毁/关闭定序器时
    // 会解析到已销毁的 CameraComponent，导致悬空指针崩溃。
    TSet<FGuid> ProcessedBindings;
    TFunction<void(const FGuid&)> ApplyCameraPropertyTracks = [&](const FGuid& InBindingID)
    {
        if (!InBindingID.IsValid() || ProcessedBindings.Contains(InBindingID))
        {
            return;
        }
        ProcessedBindings.Add(InBindingID);

        FMovieSceneBinding* BindingPtr = MovieScene->FindBinding(InBindingID);
        if (!BindingPtr)
        {
            return;
        }

        // 判定该 binding 解析出的对象类型：只有 UCineCameraComponent 绑定才允许创建属性轨道。
        bool bIsComponentBinding = false;
        if (FMovieSceneSpawnable* Sp = MovieScene->FindSpawnable(InBindingID))
        {
            if (UObject* T = Sp->GetObjectTemplate())
            {
                bIsComponentBinding = T->IsA<UCineCameraComponent>();
            }
        }
        else if (const FMovieScenePossessable* Poss = MovieScene->FindPossessable(InBindingID))
        {
            const UClass* PossClass = Poss->GetPossessedObjectClass();
            bIsComponentBinding = (PossClass && PossClass->IsChildOf<UCineCameraComponent>());
        }
        else if (FMovieSceneBindingReferences* BindingRefs = static_cast<UMovieSceneSequence*>(LevelSequence)->GetBindingReferences())
        {
            for (int32 Index = 0; ; ++Index)
            {
                UMovieSceneCustomBinding* CB = BindingRefs->GetCustomBinding(InBindingID, Index);
                if (!CB)
                {
                    break;
                }
                if (UMovieSceneSpawnableActorBinding* SB = Cast<UMovieSceneSpawnableActorBinding>(CB))
                {
                    if (UObject* T = SB->GetObjectTemplate())
                    {
                        bIsComponentBinding = T->IsA<UCineCameraComponent>();
                    }
                    break;
                }
            }
        }

        if (!bIsComponentBinding)
        {
            // Actor 绑定：不在这里建轨道，递归到子 Possessable（CameraComponent）。
            const int32 PossessableCount = MovieScene->GetPossessableCount();
            for (int32 Idx = 0; Idx < PossessableCount; ++Idx)
            {
                FMovieScenePossessable& Possessable = MovieScene->GetPossessable(Idx);
                if (Possessable.GetParent() == InBindingID)
                {
                    ApplyCameraPropertyTracks(Possessable.GetGuid());
                }
            }
            return;
        }

        UE_LOG(LogTemp, Log, TEXT("SetupCineCameraParams PropertyTrack: Binding=%s is CameraComponent binding, using bare property names."),
            *InBindingID.ToString());

        auto EnsureFloatTrack = [&](FName PropName, float Value)
        {
            UMovieSceneFloatTrack* FloatTrack = nullptr;
            for (UMovieSceneTrack* Track : BindingPtr->GetTracks())
            {
                if (UMovieSceneFloatTrack* FT = Cast<UMovieSceneFloatTrack>(Track))
                {
                    if (FT->GetPropertyName() == PropName)
                    {
                        FloatTrack = FT;
                        break;
                    }
                }
            }

            const bool bWasFound = (FloatTrack != nullptr);
            if (!FloatTrack)
            {
                FloatTrack = NewObject<UMovieSceneFloatTrack>(MovieScene, NAME_None, RF_Transactional);
                BindingPtr->AddTrack(*FloatTrack, MovieScene);
            }

            FloatTrack->Modify();
            // 组件绑定上必须是裸名（例如 CurrentFocalLength），不能带 CameraComponent. 前缀
            FloatTrack->SetPropertyNameAndPath(PropName, PropName.ToString());

            // 移除旧 section，创建新的无限范围 section
            TArray<UMovieSceneSection*> SectionsCopy = FloatTrack->GetAllSections();
            for (UMovieSceneSection* Section : SectionsCopy)
            {
                FloatTrack->RemoveSection(*Section);
            }

            UMovieSceneFloatSection* FloatSection = Cast<UMovieSceneFloatSection>(FloatTrack->CreateNewSection());
            if (!FloatSection)
            {
                FloatSection = NewObject<UMovieSceneFloatSection>(FloatTrack, NAME_None, RF_Transactional);
            }
            FloatSection->SetRange(TRange<FFrameNumber>::All());
            FloatTrack->AddSection(*FloatSection);

            FMovieSceneFloatChannel& Channel = FloatSection->GetChannel();
            Channel.Reset();
            Channel.SetDefault(Value);
            const FFrameNumber KeyFrame = ConvertDisplayFrameToTickFrame(MovieScene, FrameNumber);
            AddKeyToChannel(&Channel, KeyFrame, Value, EMovieSceneKeyInterpolation::Auto);
            FloatSection->InvalidateChannelProxy();

            UE_LOG(LogTemp, Log, TEXT("SetupCineCameraParams PropertyTrack: Prop=%s Value=%.2f FoundExisting=%d KeyDisplayFrame=%d TickFrame=%d"),
                *PropName.ToString(), Value, bWasFound ? 1 : 0, FrameNumber, KeyFrame.Value);
        };

        EnsureFloatTrack(FName("CurrentFocalLength"), 80.0f);
        EnsureFloatTrack(FName("CurrentAperture"),   22.0f);
    };

    // 1) 写入对象模板（持久化）
    ApplyCameraParams(CamComp, CameraActor);
    ApplyCameraPropertyTracks(Binding.BindingID);

    // 2) 写入当前已生成到世界中的实时 actor / component 实例（立即可见）
    //    通过活动 Sequencer 拿到绑定对应的实时对象；若序列未打开则跳过（仅模板生效）。
    //    递归处理子 Possessable（例如 CameraComponent 子绑定）。
    TSet<FGuid> ProcessedLiveBindings;
    TFunction<void(const FGuid&)> ApplyToLiveBindings = [&](const FGuid& InBindingID)
    {
        if (!InBindingID.IsValid() || ProcessedLiveBindings.Contains(InBindingID))
        {
            return;
        }
        ProcessedLiveBindings.Add(InBindingID);

        FLevelEditorSequencerIntegration& Integration = FLevelEditorSequencerIntegration::Get();
        for (TWeakPtr<ISequencer> WeakSeq : Integration.GetSequencers())
        {
            TSharedPtr<ISequencer> Seq = WeakSeq.Pin();
            if (!Seq)
            {
                continue;
            }
            if (Seq->GetRootMovieSceneSequence() != LevelSequence)
            {
                continue;
            }
            TArrayView<TWeakObjectPtr<>> BoundObjects = Seq->FindBoundObjects(InBindingID, Seq->GetFocusedTemplateID());
            UE_LOG(LogTemp, Log, TEXT("SetupCineCameraParams FindBoundObjects: Binding=%s Count=%d"),
                *InBindingID.ToString(), BoundObjects.Num());
            for (const TWeakObjectPtr<>& WeakObj : BoundObjects)
            {
                UObject* Obj = WeakObj.Get();
                if (ACineCameraActor* LiveCam = Cast<ACineCameraActor>(Obj))
                {
                    ApplyCameraParams(LiveCam->GetCineCameraComponent(), LiveCam);
                }
                else if (UCineCameraComponent* LiveComp = Cast<UCineCameraComponent>(Obj))
                {
                    ApplyCameraParams(LiveComp, LiveComp->GetOwner());
                }
            }
        }

        // 递归子 Possessable
        const int32 PossessableCount = MovieScene->GetPossessableCount();
        for (int32 Idx = 0; Idx < PossessableCount; ++Idx)
        {
            FMovieScenePossessable& Possessable = MovieScene->GetPossessable(Idx);
            if (Possessable.GetParent() == InBindingID)
            {
                ApplyToLiveBindings(Possessable.GetGuid());
            }
        }
    };
    ApplyToLiveBindings(Binding.BindingID);

    MovieScene->MarkAsChanged();
    return true;
}

// ============================================================================
// SetTransformKey — 在绑定上查找或创建变换轨道，清旧帧，K 入 Transform
// ============================================================================
bool USequencerEaseToolsBPLibrary::SetTransformKey(
    const FMovieSceneBindingProxy& Binding,
    const FTransform& Transform,
    int32 FrameNumber
)
{
    if (!Binding.Sequence || !Binding.BindingID.IsValid())
    {
        return false;
    }

    UMovieScene* MovieScene = Binding.Sequence->GetMovieScene();
    if (!MovieScene)
    {
        return false;
    }

    FMovieSceneBinding* BindingPtr = MovieScene->FindBinding(Binding.BindingID);
    if (!BindingPtr)
    {
        return false;
    }

    // === 1. 查找已有的 3D 变换轨道 ===
    UMovieScene3DTransformTrack* TransformTrack = nullptr;
    for (UMovieSceneTrack* Track : BindingPtr->GetTracks())
    {
        if (UMovieScene3DTransformTrack* Existing = Cast<UMovieScene3DTransformTrack>(Track))
        {
            TransformTrack = Existing;
            break;
        }
    }

    MovieScene->Modify();

    // === 2. 若无则创建（无限范围，与 UE 自带行为一致）===
    if (!TransformTrack)
    {
        TransformTrack = NewObject<UMovieScene3DTransformTrack>(MovieScene, NAME_None, RF_Transactional);
        if (TransformTrack)
        {
            BindingPtr->AddTrack(*TransformTrack, MovieScene);
        }
    }

    if (!TransformTrack)
    {
        return false;
    }
    TransformTrack->Modify();

    // === 3. 清除所有旧 Section（连带关键帧）===
    {
        TArray<UMovieSceneSection*> SectionsCopy = TransformTrack->GetAllSections();
        for (UMovieSceneSection* Section : SectionsCopy)
        {
            TransformTrack->RemoveSection(*Section);
        }
    }

    // === 4. 创建新的无限范围 Section 并 K 帧 ===
    UMovieScene3DTransformSection* TransformSection = NewObject<UMovieScene3DTransformSection>(TransformTrack, NAME_None, RF_Transactional);
    if (!TransformSection)
    {
        return false;
    }

    // 无限范围 = 覆盖整个时间轴，与 UE 自带 Add Key 行为一致
    TransformSection->SetRange(TRange<FFrameNumber>::All());
    TransformTrack->AddSection(*TransformSection);

    // K 入 Transform（9 通道：Location XYZ / Rotation RollPitchYaw / Scale XYZ）
    const FFrameNumber KeyFrame = ConvertDisplayFrameToTickFrame(MovieScene, FrameNumber);
    FMovieSceneChannelProxy& Proxy = TransformSection->GetChannelProxy();
    const int32 NumChannels = Proxy.NumChannels();

    UE_LOG(LogTemp, Log, TEXT("SetTransformKey: Binding=%s InputFrame=%d TickFrame=%d"),
        *Binding.BindingID.ToString(), FrameNumber, KeyFrame.Value);

    auto SetChannel = [&](int32 Index, double Value)
    {
        if (Index >= NumChannels)
        {
            return;
        }
        FMovieSceneDoubleChannel* Ch = Proxy.GetChannel<FMovieSceneDoubleChannel>(Index);
        if (!Ch)
        {
            UE_LOG(LogTemp, Warning, TEXT("SetTransformKey Channel[%d]: failed to get FMovieSceneDoubleChannel"), Index);
            return;
        }
        const int32 PrevKeys = Ch->GetNumKeys();
        AddKeyToChannel(Ch, KeyFrame, Value, EMovieSceneKeyInterpolation::Auto);
        const int32 NewKeys = Ch->GetNumKeys();
        if (NewKeys > 0)
        {
            TArrayView<const FFrameNumber> Times = Ch->GetData().GetTimes();
            const int32 TickFrame = Times.Num() > 0 ? Times[0].Value : INDEX_NONE;
            const int32 DispFrame = (TickFrame != INDEX_NONE)
                ? ConvertTickFrameToDisplayFrame(MovieScene, Times[0])
                : INDEX_NONE;
            UE_LOG(LogTemp, Log, TEXT("SetTransformKey Channel[%d]: PrevKeys=%d NewKeys=%d TickFrame=%d (DisplayFrame=%d)"),
                Index, PrevKeys, NewKeys, TickFrame, DispFrame);
        }
    };

    const FVector Loc = Transform.GetLocation();
    SetChannel(0, Loc.X);
    SetChannel(1, Loc.Y);
    SetChannel(2, Loc.Z);

    const FRotator Rotator = Transform.GetRotation().Rotator();
    SetChannel(3, Rotator.Roll);
    SetChannel(4, Rotator.Pitch);
    SetChannel(5, Rotator.Yaw);

    const FVector Scale = Transform.GetScale3D();
    SetChannel(6, Scale.X);
    SetChannel(7, Scale.Y);
    SetChannel(8, Scale.Z);

    TransformSection->InvalidateChannelProxy();

    MovieScene->MarkAsChanged();
    return true;
}

// ============================================================================
// SetAttachTo — 将 B 附加到 A（改已有附加轨道 或 新建）
// ============================================================================
bool USequencerEaseToolsBPLibrary::SetAttachTo(
    const FMovieSceneBindingProxy& TargetBinding,
    const FMovieSceneBindingProxy& AttachToBinding,
    int32 StartFrame,
    int32 EndFrame
)
{
    if (!TargetBinding.Sequence || !TargetBinding.BindingID.IsValid())
    {
        UE_LOG(LogTemp, Warning, TEXT("SetAttachTo failed: TargetBinding is invalid (Sequence=%p, BindingID valid=%d)"),
            (void*)TargetBinding.Sequence.Get(), TargetBinding.BindingID.IsValid());
        return false;
    }
    if (!AttachToBinding.Sequence || !AttachToBinding.BindingID.IsValid())
    {
        UE_LOG(LogTemp, Warning, TEXT("SetAttachTo failed: AttachToBinding is invalid (Sequence=%p, BindingID valid=%d)"),
            (void*)AttachToBinding.Sequence.Get(), AttachToBinding.BindingID.IsValid());
        return false;
    }

    UMovieScene* MovieScene = TargetBinding.Sequence->GetMovieScene();
    if (!MovieScene)
    {
        UE_LOG(LogTemp, Warning, TEXT("SetAttachTo failed: TargetBinding Sequence has no MovieScene"));
        return false;
    }

    FMovieSceneBinding* TargetBindingPtr = MovieScene->FindBinding(TargetBinding.BindingID);
    if (!TargetBindingPtr)
    {
        UE_LOG(LogTemp, Warning, TEXT("SetAttachTo failed: TargetBinding ID %s not found in MovieScene"),
            *TargetBinding.BindingID.ToString());
        return false;
    }

    // 构造相对绑定 ID（指向 A）。A、B 同序列时默认 SequenceID 解析为本序列。
    const FMovieSceneObjectBindingID AttachBindingID =
        UE::MovieScene::FRelativeObjectBindingID(AttachToBinding.BindingID);

    UE_LOG(LogTemp, Log, TEXT("SetAttachTo: Target=%s AttachTo=%s AttachToGUID=%s"),
        *TargetBinding.BindingID.ToString(),
        *AttachToBinding.BindingID.ToString(),
        *AttachBindingID.GetGuid().ToString());

    // === 附加 section 的起止帧由蓝图参数直接指定（显示帧 -> tick）===
    const int32 ActualStart = FMath::Min(StartFrame, EndFrame);
    const int32 ActualEnd   = FMath::Max(StartFrame, EndFrame);

    TRange<FFrameNumber> SectionRange;
    if (ActualStart < ActualEnd)
    {
        // 关键：蓝图传入的是显示帧，MovieScene 内部 FFrameNumber 是 tick，必须转换
        const FFrameNumber TickStart = ConvertDisplayFrameToTickFrame(MovieScene, ActualStart);
        const FFrameNumber TickEnd   = ConvertDisplayFrameToTickFrame(MovieScene, ActualEnd);
        SectionRange = TRange<FFrameNumber>(TickStart, TickEnd);
    }
    else
    {
        // 起止帧相同或无效：退回到 MovieScene 播放范围（已是 tick），避免生成空 section
        SectionRange = MovieScene->GetPlaybackRange();
        if (SectionRange.IsEmpty())
        {
            // 兜底：用转换后的 0~100 显示帧，避免写成几十个 tick 导致区间不可见
            SectionRange = TRange<FFrameNumber>(
                ConvertDisplayFrameToTickFrame(MovieScene, 0),
                ConvertDisplayFrameToTickFrame(MovieScene, 100));
        }
    }

    UE_LOG(LogTemp, Log, TEXT("SetAttachTo: StartFrame=%d EndFrame=%d -> SectionRange ticks [%d, %d)  display[%d, %d)"),
        StartFrame, EndFrame,
        SectionRange.HasLowerBound() ? SectionRange.GetLowerBoundValue().Value : INDEX_NONE,
        SectionRange.HasUpperBound() ? SectionRange.GetUpperBoundValue().Value : INDEX_NONE,
        SectionRange.HasLowerBound() ? ConvertTickFrameToDisplayFrame(MovieScene, SectionRange.GetLowerBoundValue()) : INDEX_NONE,
        SectionRange.HasUpperBound() ? ConvertTickFrameToDisplayFrame(MovieScene, SectionRange.GetUpperBoundValue()) : INDEX_NONE);

    // === 查找 B 上已有的 3D 附加轨道 ===
    UMovieScene3DAttachTrack* AttachTrack = nullptr;
    for (UMovieSceneTrack* Track : TargetBindingPtr->GetTracks())
    {
        if (UMovieScene3DAttachTrack* Existing = Cast<UMovieScene3DAttachTrack>(Track))
        {
            AttachTrack = Existing;
            break;
        }
    }

    MovieScene->Modify();

    auto ApplyAttachBinding = [&](UMovieScene3DAttachSection* AttachSection) -> bool
    {
        if (!AttachSection)
        {
            return false;
        }
        AttachSection->Modify();
        AttachSection->SetConstraintBindingID(AttachBindingID);
        AttachSection->SetRange(SectionRange);
        AttachSection->MarkAsChanged();
        UE_LOG(LogTemp, Log, TEXT("SetAttachTo Section: Applied ConstraintBindingID=%s Range=[%d, %d)"),
            *AttachSection->GetConstraintBindingID().GetGuid().ToString(),
            AttachSection->GetRange().HasLowerBound() ? AttachSection->GetRange().GetLowerBoundValue().Value : INDEX_NONE,
            AttachSection->GetRange().HasUpperBound() ? AttachSection->GetRange().GetUpperBoundValue().Value : INDEX_NONE);
        return true;
    };

    if (AttachTrack)
    {
        // 已有：把其所有 section 的约束目标改为 A，并设置起止帧
        AttachTrack->Modify();
        bool bSetAny = false;
        for (UMovieSceneSection* Section : AttachTrack->GetAllSections())
        {
            if (UMovieScene3DAttachSection* AttachSection = Cast<UMovieScene3DAttachSection>(Section))
            {
                bSetAny |= ApplyAttachBinding(AttachSection);
            }
        }
        // 若该轨道没有任何 section，补一个
        if (!bSetAny)
        {
            UMovieScene3DAttachSection* AttachSection =
                NewObject<UMovieScene3DAttachSection>(AttachTrack, NAME_None, RF_Transactional);
            if (ApplyAttachBinding(AttachSection))
            {
                AttachTrack->AddSection(*AttachSection);
            }
        }
        AttachTrack->MarkAsChanged();
    }
    else
    {
        // 没有：创建附加轨道并绑定到 A
        AttachTrack = NewObject<UMovieScene3DAttachTrack>(MovieScene, NAME_None, RF_Transactional);
        if (!AttachTrack)
        {
            UE_LOG(LogTemp, Warning, TEXT("SetAttachTo failed: Failed to create UMovieScene3DAttachTrack"));
            return false;
        }
        TargetBindingPtr->AddTrack(*AttachTrack, MovieScene);

        UMovieScene3DAttachSection* AttachSection =
            NewObject<UMovieScene3DAttachSection>(AttachTrack, NAME_None, RF_Transactional);
        if (ApplyAttachBinding(AttachSection))
        {
            AttachTrack->AddSection(*AttachSection);
        }
        AttachTrack->MarkAsChanged();
    }

    MovieScene->MarkAsChanged();
    return true;
}

bool USequencerEaseToolsBPLibrary::EnableSpawnableDespawnLogging(
    ULevelSequence* Sequence
)
{
    if (!Sequence)
    {
        return false;
    }

    ULevelSequence* LevelSequence = Sequence;

    UMovieScene* MovieScene = LevelSequence->GetMovieScene();
    if (!MovieScene)
    {
        return false;
    }

    // 找到活动 Sequencer（序列当前须处于打开状态，才能拿到实时生成的 actor）
    TSharedPtr<ISequencer> ActiveSeq;
    FLevelEditorSequencerIntegration& Integration = FLevelEditorSequencerIntegration::Get();
    for (TWeakPtr<ISequencer> WeakSeq : Integration.GetSequencers())
    {
        TSharedPtr<ISequencer> Seq = WeakSeq.Pin();
        if (Seq && Seq->GetRootMovieSceneSequence() == LevelSequence)
        {
            ActiveSeq = Seq;
            break;
        }
    }

    if (!ActiveSeq)
    {
        UE_LOG(LogTemp, Warning, TEXT("EnableSpawnableDespawnLogging: Sequence not currently open in Sequencer; open it first."));
        return false;
    }

    // 收集当前所有已生成的 actor，建立 "actor 名 -> binding GUID" 映射（按名过滤，因为 world 级回调会收到所有 actor）
    TSharedRef<TMap<FString, FString>> TrackedActors = MakeShared<TMap<FString, FString>>();
    const UMovieScene* ConstMovieScene = MovieScene;
    UWorld* World = nullptr;
    int32 TrackCount = 0;
    for (const FMovieSceneBinding& Binding : ConstMovieScene->GetBindings())
    {
        TArrayView<TWeakObjectPtr<>> BoundObjects =
            ActiveSeq->FindBoundObjects(Binding.GetObjectGuid(), ActiveSeq->GetFocusedTemplateID());
        for (const TWeakObjectPtr<>& WeakObj : BoundObjects)
        {
            if (AActor* Actor = Cast<AActor>(WeakObj.Get()))
            {
                TrackedActors->Add(Actor->GetName(), Binding.GetObjectGuid().ToString());
                World = Actor->GetWorld();
                ++TrackCount;
                UE_LOG(LogTemp, Log, TEXT("[DespawnLog] Tracking actor '%s' (Binding=%s)"),
                    *Actor->GetName(), *Binding.GetObjectGuid().ToString());
            }
        }
    }

    if (World && TrackCount > 0)
    {
        // UWorld::OnActorDestroyed 是非 dynamic 多播，支持 lambda；整局只挂一次，
        // 在回调里按 actor 名过滤，只记录我们追踪的 spawnable 的销毁瞬间及其附加父组件状态。
        World->AddOnActorDestroyedHandler(
            FOnActorDestroyed::FDelegate::CreateLambda(
                [TrackedActors](AActor* DestroyedActor)
                {
                    if (!DestroyedActor)
                    {
                        return;
                    }
                    const FString* BindingGuid = TrackedActors->Find(DestroyedActor->GetName());
                    if (!BindingGuid)
                    {
                        return; // 不是我们追踪的 actor
                    }

                    FString ParentInfo = TEXT("<none>");
                    if (USceneComponent* Root = DestroyedActor->GetRootComponent())
                    {
                        if (USceneComponent* ParentComp = Root->GetAttachParent())
                        {
                            const bool bParentValid = ParentComp->GetOwner() && IsValid(ParentComp->GetOwner());
                            ParentInfo = FString::Printf(TEXT("%s (%s) OwnerValid=%d"),
                                *ParentComp->GetName(),
                                *GetNameSafe(ParentComp->GetOwner()),
                                bParentValid ? 1 : 0);
                        }
                    }
                    UE_LOG(LogTemp, Warning,
                        TEXT("[DespawnLog] Actor '%s' (Binding=%s) destroyed. RootAttachParent=%s"),
                        *DestroyedActor->GetName(), **BindingGuid, *ParentInfo);
                }));
    }

    UE_LOG(LogTemp, Log, TEXT("[DespawnLog] Total tracked actors: %d"), TrackCount);
    return TrackCount > 0;
}