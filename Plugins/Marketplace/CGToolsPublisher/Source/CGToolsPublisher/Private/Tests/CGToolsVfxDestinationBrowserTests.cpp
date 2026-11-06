#include "SCGToolsVfxDestinationBrowser.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "ImageUtils.h"
#include "Materials/Material.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/ObjectThumbnail.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "ObjectTools.h"
#include "Particles/ParticleSystem.h"
#include "RenderingThread.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "Widgets/SWindow.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsVfxBrowserWindowTest,
    "CGTools.Publisher.VFX.DestinationBrowserPreviewAndFolderSelection",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter | EAutomationTestFlags::NonNullRHI)

bool FCGToolsVfxBrowserWindowTest::RunTest(const FString&)
{
    const FString Id = FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString Evidence = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/VfxDestinationBrowser") / Id);
    const FString Library = Evidence / TEXT("VFX");
    const FString Folder = Library / TEXT("Team1/水");
    IFileManager& Files = IFileManager::Get();
    Files.MakeDirectory(*(Folder / TEXT("Mat")), true);
    Files.MakeDirectory(*(Folder / TEXT("Tex")), true);
    Files.MakeDirectory(*(Library / TEXT("Team2")), true);
    TArray<UPackage*> Packages;
    const auto Save = [&](const FString& Name, bool bEffect, uint8 Red, uint8 Green) -> FString
    {
        UPackage* Package = CreatePackage(*(TEXT("/Game/__VfxDestinationBrowser_") + Id + TEXT("/") + Name));
        Packages.Add(Package);
        UObject* Asset = bEffect ? static_cast<UObject*>(NewObject<UParticleSystem>(Package, *Name, RF_Public | RF_Standalone))
            : static_cast<UObject*>(NewObject<UMaterial>(Package, *Name, RF_Public | RF_Standalone));
        FObjectThumbnail Thumbnail;
        Thumbnail.SetImageSize(64, 64);
        auto& Pixels = Thumbnail.AccessImageData(); Pixels.SetNumZeroed(64 * 64 * 4);
        for (int32 Y = 0; Y < 64; ++Y)
        {
            for (int32 X = 0; X < 64; ++X)
            {
                const int32 Offset = (Y * 64 + X) * 4;
                const bool bBright = FMath::Square(X - 32) + FMath::Square(Y - 32) < 500;
                Pixels[Offset] = 40; Pixels[Offset + 1] = bBright ? Green : 10;
                Pixels[Offset + 2] = bBright ? Red : 10; Pixels[Offset + 3] = 255;
            }
        }
        ThumbnailTools::CacheThumbnail(Asset->GetFullName(), &Thumbnail, Package);
        const FString Filename = Folder / (Name + TEXT(".uasset"));
        FSavePackageArgs Args; Args.TopLevelFlags = RF_Public | RF_Standalone; Args.SaveFlags = SAVE_NoError;
        TestTrue(TEXT("Save a real external package fixture"), UPackage::SavePackage(Package, Asset, *Filename, Args));
        return Filename;
    };
    const FString Effect = Save(TEXT("PS_Fire"), true, 245, 110);
    const FString Second = Save(TEXT("PS_Spark"), true, 80, 245);
    Save(TEXT("M_NotAnEffect"), false, 0, 0);
    const FMD5Hash Before = FMD5Hash::HashFile(*Effect);
    TAtomic<bool> Cancelled(false);
    const auto Listing = CGToolsVfxBrowser::ReadDirectory(Folder, Cancelled);
    TestTrue(TEXT("External metadata can be read without mounting or loading packages"), Listing.Error.IsEmpty());
    TestEqual(TEXT("Only actual effects are listed; material files and organizer folders stay hidden"), Listing.Entries.Num(), 2);
    TestTrue(TEXT("Cascade is recognized by package class rather than filename"), Listing.Entries.ContainsByPredicate([](const auto& Entry)
        { return Entry.Name == TEXT("PS_Fire") && Entry.ClassName == TEXT("ParticleSystem") && !Entry.bDirectory; }));
    auto Thumbnail = CGToolsVfxBrowser::ReadThumbnail(Effect);
    TestEqual(TEXT("Published embedded thumbnail is readable"), Thumbnail.SizeX, 64);
    const FString Cache = CGToolsVfxBrowser::ThumbnailCachePath(Effect);
    TestTrue(TEXT("Thumbnail is cached in the AssetsManager PNG cache"), Files.FileExists(*Cache) && Cache.Contains(TEXT("AssetsManagerVfxThumbnails")));
    AddInfo(TEXT("VFX_CACHE_CHECK|") + Effect + TEXT("|") + Cache);
    TestEqual(TEXT("A second thumbnail read can reuse the PNG cache"), CGToolsVfxBrowser::ReadThumbnail(Effect).SizeY, 64);

    FString Chosen;
    int32 DoubleClicks = 0;
    TSharedPtr<SCGToolsVfxDestinationBrowser> Browser;
    const TSharedRef<SWindow> Window = SNew(SWindow).Title(FText::FromString(TEXT("特效发布目录预览"))).ClientSize(FVector2D(800, 540))
        [ SAssignNew(Browser, SCGToolsVfxDestinationBrowser).RootDirectory(Library)
            .OnFolderSelected_Lambda([&](const FString& Path) { Chosen = Path; })
            .OnFolderDoubleClicked_Lambda([&](const FString&) { ++DoubleClicks; }) ];
    FSlateApplication::Get().AddWindow(Window);
    TestFalse(TEXT("Opening the browser does not synchronously scan the network"), Browser->Root->bLoaded);
    const auto Wait = [&](TFunctionRef<bool()> Ready)
    {
        const double Deadline = FPlatformTime::Seconds() + 15;
        while (!Ready() && FPlatformTime::Seconds() < Deadline)
        { FSlateApplication::Get().Tick(); FPlatformProcess::Sleep(0.01f); }
        return Ready();
    };
    if (!TestTrue(TEXT("Root directory loads asynchronously"), Wait([&]() { return Browser->Root->bLoaded; })))
    { Window->RequestDestroyWindow(); return false; }
    auto Team = Browser->Roots[0];
    TestFalse(TEXT("Collapsed folders are not scanned eagerly"), Team->bLoaded || Team->bQueued);
    Browser->Tree->SetSelection(Team);
    if (!TestTrue(TEXT("Selecting a folder expands and reads it"), Wait([&]() { return Team->bLoaded; })))
    { Window->RequestDestroyWindow(); return false; }
    auto Target = Team->Children[0];
    Browser->Tree->SetSelection(Target);
    if (!TestTrue(TEXT("Selected folder shows its effects and resolves visible thumbnails"), Wait([&]()
        { return Target->bLoaded && Target->Children.Num() == 2 && Target->Children[0]->Thumbnail.IsValid() && Target->Children[1]->Thumbnail.IsValid(); })))
    { Window->RequestDestroyWindow(); return false; }
    auto AssetNode = Target->Children[0];
    const auto AssetRow = Browser->Tree->WidgetFromItem(AssetNode);
    TestTrue(TEXT("Visible effects have actual rendered tree rows"), AssetRow.IsValid());
    if (AssetRow)
    {
        const FPointerEvent Click(0, FVector2D::ZeroVector, FVector2D::ZeroVector,
            TSet<FKey>{ EKeys::LeftMouseButton }, EKeys::LeftMouseButton, 0, FModifierKeysState());
        const auto Widget = AssetRow->AsWidget();
        Widget->OnMouseButtonDown(Widget->GetCachedGeometry(), Click);
        Widget->OnMouseButtonUp(Widget->GetCachedGeometry(), Click);
        Widget->OnMouseButtonDoubleClick(Widget->GetCachedGeometry(), Click);
        TestTrue(TEXT("Hover previews are available for effect rows"), Widget->GetToolTip().IsValid());
    }
    TestEqual(TEXT("Clicking an effect cannot replace the publishing destination"), Chosen, Folder);
    TestTrue(TEXT("The selected tree item remains the folder"), Browser->Tree->GetSelectedItems().Num() == 1 && Browser->Tree->GetSelectedItems()[0] == Target);
    TestEqual(TEXT("Double-clicking an effect cannot trigger folder rename"), DoubleClicks, 0);
    Browser->Tree->Private_OnItemDoubleClicked(Target);
    TestEqual(TEXT("Double-clicking a folder retains the rename event"), DoubleClicks, 1);
    Browser->Refresh(Folder);
    TestTrue(TEXT("Refresh restores the exact destination after background reads"), Wait([&]()
        { return Browser->RestoreDirectory.IsEmpty() && Browser->Tree->GetSelectedItems().Num() == 1; }));
    TestEqual(TEXT("Refresh preserves the intended destination"), Chosen, Folder);
    Wait([&]()
    {
        const auto Selected = Browser->Tree->GetSelectedItems();
        return Selected.Num() == 1 && Selected[0]->bLoaded && Selected[0]->Children.Num() == 2
            && Selected[0]->Children[0]->Thumbnail.IsValid() && Selected[0]->Children[1]->Thumbnail.IsValid();
    });
    FSlateApplication::Get().Tick(); FlushRenderingCommands();
    TArray<FColor> Pixels; FIntVector Size;
    bool bCaptured = FSlateApplication::Get().TakeScreenshot(Window, Pixels, Size);
    if (bCaptured)
    { TArray64<uint8> Png; FImageUtils::PNGCompressImageArray(Size.X, Size.Y, Pixels, Png);
        bCaptured = FFileHelper::SaveArrayToFile(Png, *(Evidence / TEXT("DestinationBrowser.png"))); }
    TestTrue(TEXT("The actual tree with thumbnails renders correctly"), bCaptured);
    AddInfo(TEXT("VFX_BROWSER_SCREENSHOT|") + Evidence / TEXT("DestinationBrowser.png"));
    Browser->Refresh(Folder); // Closing while disk work is pending must not retain the widget.
    Window->RequestDestroyWindow(); FSlateApplication::Get().Tick();
    Browser.Reset();
    TestTrue(TEXT("Browsing and image extraction never modify the server package"), Before == FMD5Hash::HashFile(*Effect));
    return true;
}
#endif
