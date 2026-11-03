#include "CGToolsPublisherMeshExport.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "AssetCompilingManager.h"
#include "AssetExportTask.h"
#include "Engine/StaticMesh.h"
#include "Exporters/Exporter.h"
#include "Exporters/FbxExportOption.h"
#include "Exporters/StaticMeshExporterFBX.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "PhysicsEngine/BodySetup.h"
#include "UObject/StrongObjectPtr.h"

namespace
{
    bool FbxContains(const TArray<uint8>& Bytes, const ANSICHAR* Token)
    {
        const int32 Length = FCStringAnsi::Strlen(Token);
        for (int32 Index = 0; Index + Length <= Bytes.Num(); ++Index)
        {
            if (FMemory::Memcmp(Bytes.GetData() + Index, Token, Length) == 0)
            {
                return true;
            }
        }
        return false;
    }

    bool ExportCollisionControl(UStaticMesh* Mesh, const FString& Filename)
    {
        UAssetExportTask* Task = NewObject<UAssetExportTask>();
        Task->Object = Mesh;
        Task->Exporter = NewObject<UStaticMeshExporterFBX>(Task);
        UFbxExportOption* Options = NewObject<UFbxExportOption>(Task);
        Options->Collision = true;
        Options->bExportSourceMesh = false;
        Options->bASCII = false;
        Task->Options = Options;
        Task->Filename = Filename;
        Task->bAutomated = true;
        Task->bPrompt = false;
        Task->bReplaceIdentical = true;
        return UExporter::RunAssetExportTask(Task);
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCGToolsStaticFbxCollisionTest,
    "CGTools.Publisher.MeshFbx.StaticCollisionExcluded",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FCGToolsStaticFbxCollisionTest::RunTest(const FString& Parameters)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Local engine cube fixture"), Cube))
    {
        return false;
    }
    FAssetCompilingManager::Get().FinishAllCompilation();
    TStrongObjectPtr<UStaticMesh> Mesh(DuplicateObject<UStaticMesh>(
        Cube, GetTransientPackage(), TEXT("CGToolsCollisionFixture")));
    UBodySetup* Body = NewObject<UBodySetup>(Mesh.Get());
    FKBoxElem Box;
    Box.X = Box.Y = Box.Z = 120.0f;
    Body->AggGeom.BoxElems.Add(Box);
    FKSphereElem Sphere;
    Sphere.Radius = 80.0f;
    Body->AggGeom.SphereElems.Add(Sphere);
    Mesh->SetBodySetup(Body);
    const bool bDefaultCollision = GetDefault<UFbxExportOption>()->Collision;

    const FString Output = FPaths::ProjectSavedDir() / TEXT("Automation/CGToolsPublisher/FbxCollision");
    IFileManager::Get().MakeDirectory(*Output, true);
    for (const TCHAR* ControlName : { TEXT("ControlBefore"), TEXT("ControlAfter") })
    {
        const FString ControlFile = Output / (FString(ControlName) + TEXT(".fbx"));
        TestTrue(TEXT("Native control exports successfully with collision enabled"),
            ExportCollisionControl(Mesh.Get(), ControlFile));
        TArray<uint8> Control;
        TestTrue(TEXT("Control FBX is readable"), FFileHelper::LoadFileToArray(Control, *ControlFile));
        TestTrue(TEXT("Control proves the fixture exports collision geometry"), FbxContains(Control, "UCX_"));

        FString Error;
        const FString PublishedFile = Output / (FString(ControlName) + TEXT("_Published.fbx"));
        TestTrue(TEXT("Real publisher FBX export succeeds"),
            CGToolsPublisher::ExportMeshFbx(Mesh.Get(), PublishedFile, Error));
        TestTrue(TEXT("No publisher export error"), Error.IsEmpty());
        TArray<uint8> Published;
        TestTrue(TEXT("Published FBX is readable"), FFileHelper::LoadFileToArray(Published, *PublishedFile));
        TestTrue(TEXT("Render geometry is retained"), FbxContains(Published, "PolygonVertexIndex"));
        TestFalse(TEXT("Published FBX contains no UE collision nodes"), FbxContains(Published, "UCX_"));
    }
    TestTrue(TEXT("Source BodySetup is retained"), Mesh->GetBodySetup() == Body);
    TestEqual(TEXT("Source box collision is retained"), Body->AggGeom.BoxElems.Num(), 1);
    TestEqual(TEXT("Source sphere collision is retained"), Body->AggGeom.SphereElems.Num(), 1);
    TestEqual(TEXT("Editor default collision export option is unchanged"),
        bool(GetDefault<UFbxExportOption>()->Collision), bDefaultCollision);
    AddInfo(FString::Printf(TEXT("Local FBX artifacts: %s"), *Output));
    return true;
}
#endif
