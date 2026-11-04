#pragma once

#if WITH_DEV_AUTOMATION_TESTS
#include "ContentBrowserModule.h"
#include "Framework/Application/SlateApplication.h"
#include "IContentBrowserSingleton.h"
#include "Misc/AutomationTest.h"
#include "Widgets/SWindow.h"

// Exercise a real browser in the isolated automation process, including its
// search and selection. No production browser or project is used.
class FCGToolsPublisherBrowserTestScope
{
public:
    explicit FCGToolsPublisherBrowserTestScope(const FAssetData& Seed)
        : Module(FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser")))
        , Browser(Module.Get())
    {
        const FName Instance(*FString::Printf(TEXT("CGToolsPublisherBrowserTest_%s"), *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
        FContentBrowserConfig Config;
        Config.bCanShowRealTimeThumbnails = false;
        Window = SNew(SWindow).Title(FText::FromString(TEXT("Publisher browser regression"))).ClientSize(FVector2D(900, 600));
        Window->SetContent(Browser.CreateContentBrowser(Instance, nullptr, &Config));
        FSlateApplication::Get().AddWindow(Window.ToSharedRef());
        Browser.SetPrimaryContentBrowser(Instance);
        Browser.SyncBrowserToAssets({ Seed }, false, false, Instance);
        Browser.SetSearchText(FText::FromName(Seed.AssetName));
        for (int32 Index = 0; Index < 3; ++Index) { FSlateApplication::Get().Tick(); }
        Browser.GetSelectedPathViewFolders(PathsBefore);
        PathsBefore.Sort();
        GetSelection(SelectionBefore);
        PathHandle = Module.GetOnAssetPathChanged().AddLambda([this](const FString&) { ++PathChanges; });
        SelectionHandle = Module.GetOnAssetSelectionChanged().AddLambda([this](const TArray<FAssetData>&, bool) { ++SelectionChanges; });
        SearchHandle = Module.GetOnSearchBoxChanged().AddLambda([this](const FText&, bool) { ++SearchChanges; });
        FilterHandle = Module.GetOnFilterChanged().AddLambda([this](const FARFilter&, bool) { ++FilterChanges; });
    }

    ~FCGToolsPublisherBrowserTestScope()
    {
        Module.GetOnAssetPathChanged().Remove(PathHandle);
        Module.GetOnAssetSelectionChanged().Remove(SelectionHandle);
        Module.GetOnSearchBoxChanged().Remove(SearchHandle);
        Module.GetOnFilterChanged().Remove(FilterHandle);
        FSlateApplication::Get().RequestDestroyWindow(Window.ToSharedRef());
        FSlateApplication::Get().Tick();
    }

    void VerifyUnchanged(FAutomationTestBase& Test) const
    {
        Test.TestTrue(TEXT("The real browser has an initial path"), !PathsBefore.IsEmpty());
        Test.TestTrue(TEXT("The real browser has an initial asset selection"), !SelectionBefore.IsEmpty());
        Test.TestEqual(TEXT("No browser path navigation"), PathChanges, 0);
        Test.TestEqual(TEXT("No browser selection change"), SelectionChanges, 0);
        Test.TestEqual(TEXT("No browser search change"), SearchChanges, 0);
        Test.TestEqual(TEXT("No browser filter change"), FilterChanges, 0);
        TArray<FString> PathsAfter;
        Browser.GetSelectedPathViewFolders(PathsAfter);
        PathsAfter.Sort();
        Test.TestTrue(TEXT("Current folders are preserved"), PathsAfter == PathsBefore);
        TArray<FString> SelectionAfter;
        GetSelection(SelectionAfter);
        Test.TestTrue(TEXT("Selected asset paths are preserved"), SelectionAfter == SelectionBefore);
    }

private:
    void GetSelection(TArray<FString>& Out) const
    {
        TArray<FAssetData> Assets;
        Browser.GetSelectedAssets(Assets);
        for (const FAssetData& Asset : Assets) { Out.Add(Asset.GetSoftObjectPath().ToString()); }
        Out.Sort();
    }
    FContentBrowserModule& Module;
    IContentBrowserSingleton& Browser;
    TSharedPtr<SWindow> Window;
    TArray<FString> PathsBefore;
    TArray<FString> SelectionBefore;
    FDelegateHandle PathHandle, SelectionHandle, SearchHandle, FilterHandle;
    int32 PathChanges = 0, SelectionChanges = 0, SearchChanges = 0, FilterChanges = 0;
};
#endif
