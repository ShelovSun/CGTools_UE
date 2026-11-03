#include "SCGToolsPublisherBatchWindow.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Animation/AnimSequence.h"
#include "Animation/Skeleton.h"
#include "AssetCompilingManager.h"
#include "Engine/StaticMesh.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "NiagaraSystem.h"
#include "RenderingThread.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/SWindow.h"

// Render the actual native panels, without invoking any publish/write action.
// Run with UnrealEditor -RenderOffscreen (the NullRHI suite skips this test).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsPublisherBatchPreviewTest,
    "CGTools.Publisher.Batch.NativeWindowPreview",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter | EAutomationTestFlags::NonNullRHI)

bool FCGToolsPublisherBatchPreviewTest::RunTest(const FString& Parameters)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Local mesh preview fixture"), Cube)) { return false; }
    FAssetCompilingManager::Get().FinishAllCompilation();
    TArray<TStrongObjectPtr<UPackage>> Packages;
    TStrongObjectPtr<USkeleton> Skeleton(NewObject<USkeleton>());
    TArray<TArray<FAssetData>> Selections;
    Selections.SetNum(3);
    const auto Package = [&](const FString& Path)
    {
        Packages.Emplace(CreatePackage(*Path));
        return Packages.Last().Get();
    };
    for (int32 Index = 1; Index <= 4; ++Index)
    {
        const FString Name = FString::Printf(TEXT("JinBiQian_A%d"), Index);
        UStaticMesh* Mesh = DuplicateObject<UStaticMesh>(Cube, Package(TEXT("/Game/Assets/Props/JinBiQian/") + Name), FName(*Name));
        Selections[0].Add(FAssetData(Mesh));
    }
    for (const FString& Name : { FString(TEXT("Idle")), FString(TEXT("Walk")) })
    {
        UAnimSequence* Animation = NewObject<UAnimSequence>(Package(TEXT("/Game/BatchPreview/") + Name), FName(*Name), RF_Public | RF_Standalone);
        Animation->SetSkeleton(Skeleton.Get());
        Selections[1].Add(FAssetData(Animation));
    }
    for (const FString& Name : { FString(TEXT("NS_Hit")), FString(TEXT("NS_Fire")) })
    {
        UNiagaraSystem* Effect = NewObject<UNiagaraSystem>(Package(TEXT("/Game/BatchPreview/") + Name), FName(*Name), RF_Public | RF_Standalone);
        Selections[2].Add(FAssetData(Effect));
    }
    const FString Output = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/BatchPreview"));
    IFileManager::Get().MakeDirectory(*Output, true);
    for (int32 Index = 0; Index < Selections.Num(); ++Index)
    {
        const TSharedRef<SWindow> Window = SNew(SWindow)
            .Title(FText::FromString(FString::Printf(TEXT("批量发布（%d 个资产）"), Selections[Index].Num())))
            .ClientSize(FVector2D(1240, 720)).AutoCenter(EAutoCenter::None).ScreenPosition(FVector2D(20, 20))
            [ SNew(SCGToolsPublisherBatchWindow).Assets(Selections[Index]) ];
        FSlateApplication::Get().AddWindow(Window);
        FSlateApplication::Get().Tick(ESlateTickType::All);
        FlushRenderingCommands();
        TArray<FColor> Pixels;
        FIntVector Size = FIntVector::ZeroValue;
        const bool bCaptured = FSlateApplication::Get().TakeScreenshot(Window, Pixels, Size);
        TestTrue(TEXT("The real batch window can be captured"), bCaptured && Size.X > 0 && Size.Y > 0);
        if (bCaptured && Size.X > 0 && Size.Y > 0)
        {
            TArray64<uint8> Png;
            FImageUtils::PNGCompressImageArray(Size.X, Size.Y, Pixels, Png);
            const FString Filename = Output / FString::Printf(TEXT("%d.png"), Index);
            TestTrue(TEXT("The native UI preview is saved"), FFileHelper::SaveArrayToFile(Png, *Filename));
            UE_LOG(LogTemp, Display, TEXT("Batch preview screenshot: %s"), *Filename);
        }
        Window->RequestDestroyWindow();
        FSlateApplication::Get().Tick();
    }
    return true;
}
#endif
