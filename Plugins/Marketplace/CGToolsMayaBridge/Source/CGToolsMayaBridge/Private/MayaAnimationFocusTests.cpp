#if WITH_DEV_AUTOMATION_TESTS

#include "MayaActionImporter.h"

#include "ContentBrowserModule.h"
#include "Dom/JsonObject.h"
#include "IContentBrowserSingleton.h"
#include "IPythonScriptPlugin.h"
#include "Misc/AutomationTest.h"
#include "Misc/Base64.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
class FWaitForMayaAnimationSelection final : public IAutomationLatentCommand
{
public:
    FWaitForMayaAnimationSelection(FAutomationTestBase* InTest, const TArray<FAssetData>& InExpected)
        : Test(InTest), Expected(InExpected), Started(FPlatformTime::Seconds()) {}

    virtual bool Update() override
    {
        TArray<FAssetData> Selected;
        FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser")).Get().GetSelectedAssets(Selected);
        const bool bMatches = !Expected.IsEmpty() && Selected.Num() == Expected.Num()
            && !Expected.ContainsByPredicate([&Selected](const FAssetData& Asset) { return !Selected.Contains(Asset); });
        if (bMatches)
        {
            Test->AddInfo(TEXT("Content Browser selected both imported animations after the asset view refreshed."));
            return true;
        }
        if (FPlatformTime::Seconds() - Started < 15.0)
        {
            return false;
        }
        Test->AddError(FString::Printf(TEXT("Content Browser selected %d assets instead of the %d imported animations."), Selected.Num(), Expected.Num()));
        return true;
    }

private:
    FAutomationTestBase* Test;
    TArray<FAssetData> Expected;
    double Started;
};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMayaAnimationFocusIntegrationTest, "CGTools.MayaBridge.AnimationFocus",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FMayaAnimationFocusIntegrationTest::RunTest(const FString& Parameters)
{
    FString FixturePath;
    if (!FParse::Value(FCommandLine::Get(), TEXT("MayaBridgeFocusFixture="), FixturePath))
    {
        AddInfo(TEXT("Animation import integration requires an explicit disposable-project MayaBridgeFocusFixture."));
        return true;
    }
    FString Json;
    TSharedPtr<FJsonObject> Fixture;
    if (!FFileHelper::LoadFileToString(Json, *FixturePath)
        || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Fixture) || !Fixture)
    {
        AddError(TEXT("Cannot read the animation focus fixture."));
        return false;
    }
    FString ExpectedProject = FPaths::ConvertRelativePathToFull(Fixture->GetStringField(TEXT("project_dir")));
    FString ActualProject = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
    FPaths::NormalizeDirectoryName(ExpectedProject);
    FPaths::NormalizeDirectoryName(ActualProject);
    if (!TestEqual(TEXT("Only modify the fixture's disposable project"), ActualProject, ExpectedProject))
    {
        return false;
    }

    // Prepare either a missing Skeleton through the real recovery service, or
    // verify the existing-Skeleton case, without opening interactive dialogs.
    FPythonCommandEx Setup;
    Setup.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
    Setup.Flags = EPythonCommandFlags::Unattended;
    Setup.Command = FString::Printf(TEXT("exec(compile(__import__('pathlib').Path(__import__('base64').b64decode('%s').decode('utf-8')).read_text(encoding='utf-8'), 'maya_focus_setup', 'exec'))"),
        *FBase64::Encode(Fixture->GetStringField(TEXT("setup_script"))));
    IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
    if (!Python || !Python->ExecPythonCommandEx(Setup))
    {
        AddError(TEXT("Asset recovery setup failed: ") + Setup.CommandResult);
        return false;
    }

    FMayaPublishedAction Action;
    Action.ProjectName = TEXT("GOF");
    Action.AssetType = TEXT("Props");
    Action.AssetName = TEXT("Yu015QiePian");
    Action.FbxPath = Fixture->GetStringField(TEXT("fbx_path"));
    const FMayaBridgeSettings Settings;
    const FMayaActionImporter Importer(Settings);
    TArray<FAssetData> Animations;
    for (const TCHAR* Suffix : { TEXT("A"), TEXT("B") })
    {
        Action.ActionName = TEXT("BridgeFocus_") + Fixture->GetStringField(TEXT("mode")) + TEXT("_") + Suffix;
        FString Error;
        if (!TestTrue(TEXT("Native animation import succeeds"), Importer.ImportAction(Action, Error, Animations)))
        {
            AddError(Error);
            return false;
        }
    }
    TestEqual(TEXT("Batch collects exactly two actual animations"), Animations.Num(), 2);
    FMayaActionImporter::FocusImportedAnimations(Animations);
    ADD_LATENT_AUTOMATION_COMMAND(FWaitForMayaAnimationSelection(this, Animations));
    return true;
}

#endif
