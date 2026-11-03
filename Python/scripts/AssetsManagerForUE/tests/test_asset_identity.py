"""A shared migration dependency must never stand in for the selected asset."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from AssetsManagerForUE.sources import ue_asset_service as service


class AssetIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset_identity_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "GOF/Assets/Props/LanWangD2"
        self.content = Path(self.temporary.name) / "Project/Content"
        self.root.mkdir(parents=True)
        self.classes = {}
        self.library = mock.Mock()
        self.library.does_asset_exist.side_effect = lambda p: p in self.classes
        self.registry = mock.Mock()
        self.registry.get_assets_by_path.side_effect = lambda folder, recursive=True: [
            types.SimpleNamespace(package_name=p.split(".")[0], asset_name=p.rsplit(".", 1)[-1])
            for p in self.classes if p.lower().startswith(folder.lower() + "/")]
        engine = types.SimpleNamespace(
            EditorAssetLibrary=self.library,
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: self.registry))
        for patch in [mock.patch.object(service, "unreal", engine),
                      mock.patch.object(service, "_asset_class_name", side_effect=self.classes.get),
                      mock.patch.object(service, "_is_actor_blueprint", return_value=True),
                      mock.patch.object(service, "_project_content_dir", return_value=str(self.content))]:
            patch.start()
            self.addCleanup(patch.stop)

    def package(self, relative, local=None, class_name="Texture2D"):
        source = self.root / "UE/Content" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"server package")
        path = service._object_path_from_relative(relative)
        if local is not None:
            target = self.content / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(local)
            self.classes[path] = class_name
        return path

    def plan(self):
        return service.build_import_plan(str(self.root), str(self.content))

    def card(self, plan):
        row = [None] * 8
        row[7] = str(self.root / "Icon/LanWangD2.png")
        return types.SimpleNamespace(
            itemData=lambda: row, uePlan=lambda: plan,
            ueMainObjectPath=lambda: plan.get("main_object_path", ""))

    def release(self, local=None):
        main = self.package("Assets/Props/LanWangD/LanWangD2.uasset", local, "SkeletalMesh")
        blue = self.package("Assets/MasterMaterial/blue.uasset", b"old blue")
        return main, blue

    def test_shared_blue_alone_is_missing_and_cannot_locate_or_drag(self):
        main, blue = self.release()
        plan = self.plan()
        self.assertEqual(plan["state"], "missing")
        self.assertFalse(plan["asset_present"])
        self.assertIn("Assets/MasterMaterial/blue.uasset", plan["different_files"])
        self.assertEqual(plan["asset_identity_paths"], [main])
        self.assertNotIn(blue, plan["asset_object_paths"])
        card = self.card(plan)
        self.assertEqual(service.resolve_local_card_browser_asset(card), "")
        self.assertEqual(service.resolve_local_card_drag(card)[0], "")
        self.assertEqual(service.sync_plan_to_content_browser(plan), (False, ""))
        self.library.sync_browser_to_objects.assert_not_called()

    def test_identical_shared_dependency_alone_is_also_missing(self):
        self.package("Assets/Props/LanWangD2/LanWangD2.uasset")
        self.package("Assets/MasterMaterial/blue.uasset", b"server package")
        plan = self.plan()
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(plan["different_files"], [])

    def test_own_texture_alone_does_not_mark_named_mesh_installed(self):
        self.release()
        self.package("Assets/Props/LanWangD/Textures/T_Wood.uasset", b"server package")
        self.assertEqual(self.plan()["state"], "missing")

    def test_old_main_in_historical_folder_wins_over_sibling_and_shared_meshes(self):
        main, _ = self.release(b"old mesh")
        self.package("Assets/Props/LanWangD/LanWangD.uasset", b"old sibling", "SkeletalMesh")
        self.package("Assets/Props/Other/BP_Other.uasset", b"old dependency", "Blueprint")
        plan = self.plan()
        self.assertEqual(plan["state"], "conflict")
        self.assertTrue(plan["asset_present"])
        with mock.patch.object(service, "build_import_plan", side_effect=AssertionError("server access")):
            self.assertEqual(service.resolve_local_card_browser_asset(self.card(plan)), main)
            self.assertEqual(service.resolve_local_card_drag(self.card(plan)), (main, ""))
            self.assertEqual(service.resolve_placeable_object_path(plan), main)

    def test_missing_main_does_not_drag_another_assets_mesh_dependency(self):
        self.release()
        self.package("Assets/Props/Other/SM_Other.uasset", b"old dependency", "StaticMesh")
        self.assertEqual(service.resolve_local_card_drag(self.card(self.plan()))[0], "")

    def test_manifest_can_explicitly_identify_a_different_folder(self):
        main = self.package("Imported/Mesh/SK_Net.uasset", b"old mesh", "SkeletalMesh")
        (self.root / "UE/asset_manifest.json").write_text(
            json.dumps({"mainObjectPath": main}), encoding="utf-8")
        self.package("Assets/MasterMaterial/blue.uasset", b"old blue")
        plan = self.plan()
        self.assertEqual(plan["asset_identity_paths"], [main])
        self.assertTrue(plan["asset_present"])
        self.assertEqual(service.resolve_local_card_browser_asset(self.card(plan)), main)

    def test_declared_missing_main_is_not_satisfied_by_shared_dependencies(self):
        self.release()
        (self.root / "UE/manifest.json").write_text(json.dumps({
            "mainObjectPath": "/Game/Assets/Props/LanWangD/LanWangD2.LanWangD2"}), encoding="utf-8")
        self.assertEqual(self.plan()["state"], "missing")

    def test_stale_inferred_blue_main_is_rejected(self):
        _main, blue = self.release()
        plan = self.plan()
        plan["main_object_path"] = blue
        self.assertEqual(service.resolve_local_card_browser_asset(self.card(plan)), "")

    def test_offline_or_empty_server_plan_still_locates_and_drags_local_old_mesh(self):
        main = self.package("Assets/Props/LanWangD2/SM_Old.uasset", b"old mesh", "StaticMesh")
        plan = {"state": "error", "target_root": str(self.content)}
        with mock.patch.object(service, "build_import_plan", side_effect=AssertionError("server access")):
            self.assertEqual(service.resolve_local_card_browser_asset(self.card(plan)), main)
            self.assertEqual(service.resolve_local_card_drag(self.card(plan)), (main, ""))

    def test_owned_material_skeleton_and_map_remain_locatable_without_placeable_mesh(self):
        for relative, class_name in [("M_Net.uasset", "Material"),
                                     ("Net_Skeleton.uasset", "Skeleton"),
                                     ("NetMap.umap", "World")]:
            with self.subTest(class_name=class_name):
                self.classes.clear()
                main = self.package("Assets/Props/LanWangD2/" + relative, b"old package", class_name)
                self.assertEqual(service.resolve_local_card_browser_asset(self.card(self.plan())), main)

    def test_scene_card_uses_same_ownership_rules(self):
        self.root = self.root.parents[2] / "Scenes/Props/LanWangD2"
        self.root.mkdir(parents=True)
        main = self.package("Scenes/Props/LanWangD2/LanWangD2.uasset")
        blue = self.package("Scenes/MasterMaterial/blue.uasset", b"old blue")
        plan = self.plan()
        self.assertEqual(plan["asset_identity_paths"], [main])
        self.assertNotIn(blue, plan["asset_object_paths"])
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(service.resolve_local_card_browser_asset(self.card(plan)), "")

    def test_complete_release_is_ready_without_using_unreal_on_scan_thread(self):
        self.package("Assets/Props/LanWangD2/SM_LanWangD2.uasset", b"server package", "StaticMesh")
        self.package("Assets/MasterMaterial/blue.uasset", b"server package")
        with mock.patch.object(service, "unreal", None):
            self.assertEqual(self.plan()["state"], "ready")


if __name__ == "__main__":
    unittest.main()
