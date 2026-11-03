#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MovieSceneSection.h"
#include "MovieSceneBindingProxy.h"
#include "Engine/StaticMesh.h"
#include "Tracks/MovieScene3DPathTrack.h"

#include "SequencerEaseToolsBPLibrary.generated.h"

class ULevelSequence;

UCLASS()
class SEQUENCEREASETOOLS_API USequencerEaseToolsBPLibrary
    : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:

    UFUNCTION(BlueprintCallable, Category = "Sequencer Ease")
    static void SetSectionEaseIn(
        UMovieSceneSection* Section,
        int32 FrameCount
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Ease")
    static void SetSectionEaseOut(
        UMovieSceneSection* Section,
        int32 FrameCount
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Ease")
    static void SetSectionEaseInOut(
        UMovieSceneSection* Section,
        int32 EaseInFrames,
        int32 EaseOutFrames
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Ease")
    static void AutoSetEaseFromOverlap(
        UMovieSceneSection* SectionA,
        UMovieSceneSection* SectionB
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Binding")
    static void CopyTransformBindingInfo(
        const FMovieSceneBindingProxy& SourceBinding,
        const FMovieSceneBindingProxy& TargetBinding,
        bool bCopyFollow = true
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Binding")
    static void RemoveSpawnableOrPossessable(
        const FMovieSceneBindingProxy& Binding
    );

    UFUNCTION(BlueprintCallable, Category = "Sequencer Binding")
    static void MatchSectionLength(
        const FMovieSceneBindingProxy& SourceBinding,
        const FMovieSceneBindingProxy& TargetBinding
    );

    /**
     * 在 TargetBinding 上添加 3D 附加轨道 + 3D 变换轨道，并 K 入 Transform。
     * 适用流程：先在蓝图里用引擎自带的 "Add Spawnable From Instance" 节点创建 spawnable，
     * 拿到返回的 binding proxy 后传入本函数作为 TargetBinding。
     *
     * 行为：
     *  1. 在 TargetBinding 上添加 MovieScene3DAttachTrack + Section
     *     - Section 长度自动对齐 ParentBinding 上第一个 section 的范围
     *     - 附加目标 = ParentBinding（通过 ConstraintBindingID）
     *  2. 在 TargetBinding 上添加 MovieScene3DTransformTrack + Section
     *     - Section 长度同上
     *     - 在 FrameNumber 处 K 入 Transform
     *  3. （可选）把 TargetBinding 移到 FolderPath 指定的文件夹
     *
     * @param TargetBinding   要添加轨道的 binding（通常是 AddSpawnableFromInstance 的返回值）
     * @param ParentBinding   附加目标 + 长度参考来源
     * @param Transform       在 FrameNumber 处 K 入的变换值
     * @param FrameNumber     K 帧位置
     * @param FolderPath      （可选）文件夹路径，如 "Camera/Rig"
     * @return                返回 TargetBinding（保持接口一致）
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Spawnable", meta = (DisplayName = "Add Attach And Transform Track (Static Mesh)"))
    static FMovieSceneBindingProxy CreateSpawnableStaticMesh(
        const FMovieSceneBindingProxy& TargetBinding,
        const FMovieSceneBindingProxy& ParentBinding,
        const FTransform& Transform,
        int32 FrameNumber = 0,
        const FString& FolderPath = ""
    );

    /**
     * 同 CreateSpawnableStaticMesh，专为 CineCamera 留出独立节点（便于在蓝图中按用途分类）。
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Spawnable", meta = (DisplayName = "Add Attach And Transform Track (Cine Camera)"))
    static FMovieSceneBindingProxy CreateSpawnableCineCamera(
        const FMovieSceneBindingProxy& TargetBinding,
        const FMovieSceneBindingProxy& ParentBinding,
        const FTransform& Transform,
        int32 FrameNumber = 0,
        const FString& FolderPath = ""
    );

    /**
     * 检测绑定代理是否为 CineCameraActor 类型，若是则将相机参数设置为预设值：
     *
     *   胶片背板:     Custom
     *   感应器宽度:   22.54 mm
     *   感应器高度:   20.43 mm
     *   焦距:         80.0
     *   光圈:         22.0
     *
     * @param Binding      目标绑定代理（通常由 AddSpawnableFromClass(ACineCameraActor) 返回）
     * @param FrameNumber  在属性轨道上 K 帧的显示帧位置（默认 0）。若序列里已有对应属性轨道则修改它；没有则创建。
     * @return             true = 已成功设置（是 CineCameraActor）；false = 类型不匹配或失败
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Camera", meta = (DisplayName = "Set Cine Camera Default Params"))
    static bool SetupCineCameraParams(
        const FMovieSceneBindingProxy& Binding,
        int32 FrameNumber = 0
    );

    /**
     * 在绑定代理上设置/重置变换轨道：查找或创建 3D 变换轨道，
     * 清除所有旧关键帧，创建无限范围 Section（与 UE 自带行为一致），
     * 并在指定帧 K 入 Transform。
     *
     * @param Binding      目标绑定代理
     * @param Transform     要 K 入的变换值（Location / Rotation / Scale）
     * @param FrameNumber   K 帧位置
     * @return             true = 成功；false = 失败
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Transform", meta = (DisplayName = "Set Transform Key"))
    static bool SetTransformKey(
        const FMovieSceneBindingProxy& Binding,
        const FTransform& Transform,
        int32 FrameNumber = 0
    );

    /**
     * 将 B 代理附加到 A 代理（设置 3D 附加轨道）。
     * 若 B 已有附加轨道：直接把其 section 的约束目标改为 A，并重新设置起止帧。
     * 若 B 没有附加轨道：创建指定范围的附加轨道并绑定到 A。
     *
     * @param TargetBinding   B —— 被附加的绑定（要挂到 A 上的对象）
     * @param AttachToBinding A —— 附加目标
     * @param StartFrame      附加片段起始帧（默认 0）
     * @param EndFrame        附加片段结束帧（默认 100）
     * @return               true = 成功；false = 失败
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Binding", meta = (DisplayName = "Set Attach To"))
    static bool SetAttachTo(
        const FMovieSceneBindingProxy& TargetBinding,
        const FMovieSceneBindingProxy& AttachToBinding,
        int32 StartFrame = 0,
        int32 EndFrame = 100
    );

    /**
     * 给当前序列里所有已生成的 spawnable actor 挂上 OnDestroyed 日志钩子，
     * 用于诊断纯 spawnable 多层互相附加时在 despawn 阶段崩溃的问题。
     *
     * 钩子会在每个 actor 被销毁时打印：
     *   - actor 名 / 类
     *   - 销毁瞬间其 RootComponent 的附加父组件及父 actor（是否存在）
     * 据此可以判断是哪个 actor 销毁时，其附加父组件已被先行销毁（悬空指针）。
     *
     * @param Sequence   当前打开的 Level Sequence 绑定代理（用于定位对应的活动 Sequencer）
     * @return           true = 已为至少一个 actor 挂载日志钩子
     */
    UFUNCTION(BlueprintCallable, Category = "Sequencer Binding", meta = (DisplayName = "Enable Spawnable Despawn Logging"))
    static bool EnableSpawnableDespawnLogging(
        ULevelSequence* Sequence
    );
};