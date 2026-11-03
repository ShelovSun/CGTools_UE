#include "CGToolsPublisherBatch.h"

#include "Animation/AnimSequence.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "SCGToolsVfxPublisherWindow.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Engine/Texture2D.h"
#include "Misc/AutomationTest.h"
#include "NiagaraSystem.h"
#include "Particles/ParticleSystem.h"
#endif

ECGToolsPublisherKind CGToolsPublisher::GetSelectionKind(const TArray<FAssetData>& Assets)
{
    if (Assets.IsEmpty())
    {
        return ECGToolsPublisherKind::None;
    }
    const FAssetData& First = Assets[0];
    for (const FAssetData& Asset : Assets)
    {
        if (!Asset.IsValid() || Asset.AssetClassPath != First.AssetClassPath)
        {
            return ECGToolsPublisherKind::None;
        }
    }
    if (First.IsInstanceOf<UStaticMesh>(EResolveClass::Yes))
    {
        return ECGToolsPublisherKind::StaticMesh;
    }
    if (First.IsInstanceOf<USkeletalMesh>(EResolveClass::Yes))
    {
        return ECGToolsPublisherKind::SkeletalMesh;
    }
    if (First.IsInstanceOf<UAnimSequence>(EResolveClass::Yes))
    {
        return ECGToolsPublisherKind::Animation;
    }
    return CGToolsVfxPublisher::IsEffectAsset(First)
        ? ECGToolsPublisherKind::Vfx : ECGToolsPublisherKind::None;
}

FCGToolsPublisherBatch::FCGToolsPublisherBatch(TArray<FAssetData> InAssets, FShowDialog InShowDialog)
    : Assets(MoveTemp(InAssets)), ShowDialog(MoveTemp(InShowDialog))
{
}

void FCGToolsPublisherBatch::Start()
{
    if (bFinished || CurrentState.IsValid())
    {
        return;
    }
    if (!ShowDialog || Assets.IsEmpty())
    {
        Cancel();
        return;
    }
    CurrentState = MakeShared<FCGToolsPublisherDialogState>(1, Assets.Num());
    ShowDialog(Assets, CurrentState.ToSharedRef());
}

void FCGToolsPublisherBatch::OnDialogClosed(const TSharedRef<FCGToolsPublisherDialogState>& State)
{
    if (bFinished || CurrentState != State || State->bPublishing)
    {
        return;
    }
    Cancel();
}

void FCGToolsPublisherBatch::Cancel()
{
    bFinished = true;
    CurrentState.Reset();
    Assets.Reset();
    ShowDialog = nullptr;
}

TSharedPtr<FCGToolsPublisherBatch> CGToolsPublisher::RunBatch(TArray<FAssetData> Assets,
    FCGToolsPublisherBatch::FShowDialog ShowDialog)
{
    if (GetSelectionKind(Assets) == ECGToolsPublisherKind::None)
    {
        return nullptr;
    }
    const TSharedRef<FCGToolsPublisherBatch> Batch =
        MakeShared<FCGToolsPublisherBatch>(MoveTemp(Assets), MoveTemp(ShowDialog));
    Batch->Start();
    return Batch;
}

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherSelectionTest,
    "CGTools.Publisher.Batch.HomogeneousSelection",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherSelectionTest::RunTest(const FString& Parameters)
{
    using CGToolsPublisher::GetSelectionKind;
    // Registry data exercises the menu rules without loading or modifying assets.
    const auto Asset = [](UClass* Class, const TCHAR* Name)
    {
        return FAssetData(FName(*(FString(TEXT("/Game/BatchTest/")) + Name)),
            FName(TEXT("/Game/BatchTest")), FName(Name), Class->GetClassPathName());
    };
    const TArray<TPair<UClass*, ECGToolsPublisherKind>> Types = {
        { UStaticMesh::StaticClass(), ECGToolsPublisherKind::StaticMesh },
        { USkeletalMesh::StaticClass(), ECGToolsPublisherKind::SkeletalMesh },
        { UAnimSequence::StaticClass(), ECGToolsPublisherKind::Animation },
        { UNiagaraSystem::StaticClass(), ECGToolsPublisherKind::Vfx },
        { UParticleSystem::StaticClass(), ECGToolsPublisherKind::Vfx }
    };
    TestTrue(TEXT("Empty selection is disabled"), GetSelectionKind({}) == ECGToolsPublisherKind::None);
    for (const auto& Type : Types)
    {
        const FAssetData A = Asset(Type.Key, TEXT("First"));
        TestTrue(TEXT("Single supported asset is enabled"), GetSelectionKind({ A }) == Type.Value);
        TestTrue(TEXT("Same-type multi-selection is enabled"),
            GetSelectionKind({ A, Asset(Type.Key, TEXT("Second")), Asset(Type.Key, TEXT("Third")) }) == Type.Value);
        TestTrue(TEXT("Invalid item disables the whole selection"),
            GetSelectionKind({ A, FAssetData() }) == ECGToolsPublisherKind::None);
        for (const auto& Other : Types)
        {
            if (Other.Key != Type.Key)
            {
                TestTrue(TEXT("Mixed supported classes are disabled"),
                    GetSelectionKind({ A, Asset(Other.Key, TEXT("Other")) }) == ECGToolsPublisherKind::None);
            }
        }
    }
    const FAssetData Texture = Asset(UTexture2D::StaticClass(), TEXT("Texture"));
    TestTrue(TEXT("Unsupported type stays disabled"), GetSelectionKind({ Texture, Texture }) == ECGToolsPublisherKind::None);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherBatchTest,
    "CGTools.Publisher.Batch.SingleSelectionWindow",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FCGToolsPublisherBatchTest::RunTest(const FString& Parameters)
{
    TArray<FAssetData> Selection;
    for (int32 Index = 0; Index < 3; ++Index)
    {
        const FString Name = FString::Printf(TEXT("Item%d"), Index);
        Selection.Emplace(FName(*(TEXT("/Game/BatchTest/") + Name)),
            FName(TEXT("/Game/BatchTest")), FName(*Name), UAnimSequence::StaticClass()->GetClassPathName());
    }
    const TArray<FAssetData> Original = Selection;
    int32 Calls = 0;
    TSharedPtr<FCGToolsPublisherDialogState> Current;
    const TSharedPtr<FCGToolsPublisherBatch> Batch = CGToolsPublisher::RunBatch(Selection,
        [&](const TArray<FAssetData>& Assets, const TSharedRef<FCGToolsPublisherDialogState>& State)
    {
        TestEqual(TEXT("One window receives every selected asset"), Assets.Num(), 3);
        for (int32 Index = 0; Index < Assets.Num(); ++Index)
        { TestEqual(TEXT("The original order is preserved"), Assets[Index].AssetName, Original[Index].AssetName); }
        TestEqual(TEXT("The window retains the original total"), State->Count, 3);
        Current = State; ++Calls;
        Selection.Reset();
    });
    TestEqual(TEXT("Multi-selection opens exactly one window"), Calls, 1);
    Batch->Start();
    TestEqual(TEXT("Repeated Start cannot duplicate an active window"), Calls, 1);
    Current->Result = ECGToolsPublisherDialogResult::Published;
    Current->bPublishing = true;
    Batch->OnDialogClosed(Current.ToSharedRef());
    TestFalse(TEXT("A live publish cannot release the selection"), Batch->IsFinished());
    Current->bPublishing = false;
    Batch->OnDialogClosed(Current.ToSharedRef());
    Batch->OnDialogClosed(Current.ToSharedRef());
    TestTrue(TEXT("Closing the shared window releases the selection"), Batch->IsFinished());
    TestEqual(TEXT("Closing never opens a per-asset followup dialog"), Calls, 1);
    CGToolsPublisher::RunBatch({ Original[0], FAssetData() }, [&](const TArray<FAssetData>&, const TSharedRef<FCGToolsPublisherDialogState>&)
    { AddError(TEXT("Invalid mixed selection must not open a window")); });
    const TSharedPtr<FCGToolsPublisherBatch> Single = CGToolsPublisher::RunBatch({ Original[0] },
        [&](const TArray<FAssetData>& Assets, const TSharedRef<FCGToolsPublisherDialogState>& State)
    { TestEqual(TEXT("Single selection retains the existing single panel"), Assets.Num(), 1); TestFalse(TEXT("Single is not a batch"), State->IsBatch()); });
    Single->Cancel();
    return true;
}
#endif
