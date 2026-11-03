"""Early exits must eliminate I/O without hiding load-time shared conflicts."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from AssetsManagerForUE.sources import ue_asset_service as service
from test_state_scan_priority import ScanPriorityFixture


class StateGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Library/Assets/Props/LanWangD2"
        self.content = Path(self.temp.name) / "Project/Content"
        self.source = self.root / "UE/Content"
        self.relative = "Assets/Props/LanWangD/LanWangD2.uasset"
        self.main = service._object_path_from_relative(self.relative)
        # Existing primary/legacy tests exercise the stage after the new
        # local-folder gate. Dedicated tests below remove this directory.
        self.local_folder = self.content / "Assets/Props/LanWangD2"
        self.local_folder.mkdir(parents=True)

    def package(self, relative, local=None):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"server bytes")
        if local is not None:
            target = self.content / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(local)

    def manifest(self):
        (self.root / "UE/asset_manifest.json").write_text(
            json.dumps({"mainObjectPath": self.main}), encoding="utf-8")

    def plan(self, fast=True):
        return service.build_import_plan(str(self.root), str(self.content),
                                         check_primary_first=fast)

    def test_missing_local_folder_skips_every_server_operation(self):
        self.local_folder.rmdir()
        with mock.patch.object(service, "find_source_content_root", side_effect=AssertionError("server probe")), \
                mock.patch.object(service, "_read_manifest", side_effect=AssertionError("manifest read")), \
                mock.patch.object(service.os, "walk", side_effect=AssertionError("directory walk")), \
                mock.patch.object(service.os.path, "getsize", side_effect=AssertionError("size read")):
            plan = self.plan()
        self.assertEqual(plan["check_stage"], "local_folder")
        self.assertEqual(plan["state"], "missing")
        self.assertTrue(plan["source_available"])
        self.assertIsNone(plan["ue_directory_exists"])
        self.assertEqual(plan["files"], [])
        self.assertTrue(plan["state_check_only"])

    def test_missing_local_folder_probes_only_one_local_directory(self):
        self.local_folder.rmdir()
        original = service.os.stat
        with mock.patch.object(service.os, "stat", wraps=original) as stat_call:
            plan = self.plan()
        self.assertEqual(plan["check_stage"], "local_folder")
        self.assertEqual([os.path.normcase(call.args[0]) for call in stat_call.call_args_list],
                         [os.path.normcase(str(self.local_folder))])

    def test_local_folder_permission_error_is_not_missing(self):
        original = service.os.stat
        def probe(path, *args, **kwargs):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(self.local_folder)):
                raise PermissionError("local directory inaccessible")
            return original(path, *args, **kwargs)
        with mock.patch.object(service.os, "stat", side_effect=probe), \
                mock.patch.object(service, "find_source_content_root") as source:
            with self.assertRaisesRegex(PermissionError, "directory inaccessible"):
                self.plan()
        source.assert_not_called()

    def test_explicit_load_bypasses_local_folder_gate(self):
        self.local_folder.rmdir()
        self.package("Assets/Props/LanWangD2/LanWangD2.uasset")
        plan = self.plan(fast=False)
        self.assertTrue(plan["source_available"])
        self.assertEqual(len(plan["files"]), 1)
        self.assertNotEqual(plan.get("check_stage"), "local_folder")

    def test_scene_local_folder_uses_the_same_early_exit(self):
        self.root = Path(self.temp.name) / "Library/Scenes/Props/Net"
        with mock.patch.object(service, "find_source_content_root", side_effect=AssertionError("server probe")):
            plan = self.plan()
        self.assertEqual(plan["check_stage"], "local_folder")
        self.assertEqual(plan["asset_local_folders"], ["/Game/Scenes/Props/Net"])

    def test_missing_main_with_manifest_skips_directory_walk_and_file_sizes(self):
        self.package(self.relative)
        self.manifest()
        with mock.patch.object(service.os, "walk", side_effect=AssertionError("directory walk")), \
                mock.patch.object(service.os.path, "getsize", side_effect=AssertionError("size read")):
            plan = self.plan()
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(plan["check_stage"], "primary")
        self.assertTrue(plan["source_available"])
        self.assertEqual(plan["asset_identity_paths"], [self.main])

    def test_legacy_different_parent_finds_exact_main_without_dependency_metadata(self):
        self.package(self.relative)
        self.package("Assets/Props/LanWangD/LanWangD.uasset", b"sibling")
        self.package("Assets/Props/LanWangD/Textures/T_Net.uasset", b"texture")
        self.package("Assets/MasterMaterial/blue.uasset", b"changed")
        with mock.patch.object(service.os.path, "getsize", side_effect=AssertionError("size read")), \
                mock.patch.object(service, "_is_package_file", wraps=service._is_package_file) as probe:
            plan = self.plan()
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(plan["asset_identity_paths"], [self.main])
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         [str(self.content / self.relative).replace("\\", "/")])
        self.assertTrue(plan["state_check_only"])

    def test_main_present_checks_all_dependencies_and_detects_conflicts(self):
        self.package(self.relative, b"server bytes")
        self.package("Assets/MasterMaterial/blue.uasset", b"different length")
        self.package("Assets/Textures/T_Missing.uasset")
        plan = self.plan()
        self.assertEqual(plan["state"], "conflict")
        self.assertIn("Assets/MasterMaterial/blue.uasset", plan["different_files"])
        self.assertIn("Assets/Textures/T_Missing.uasset", plan["missing_files"])
        self.assertEqual(plan["check_stage"], "files")

    def test_missing_dependencies_do_not_read_server_file_sizes(self):
        self.package(self.relative, b"server bytes")
        for index in range(30):
            self.package("Assets/Textures/T_%03d.uasset" % index)
        with mock.patch.object(service.os.path, "getsize", wraps=service.os.path.getsize) as sizes:
            plan = self.plan()
        source_reads = [call.args[0] for call in sizes.call_args_list
                        if str(call.args[0]).startswith(str(self.source).replace("\\", "/"))]
        self.assertEqual(len(source_reads), 1)
        self.assertEqual(plan["state"], "partial")

    def test_explicit_load_still_hashes_shared_conflicts_when_main_is_missing(self):
        self.package(self.relative)
        self.package("Assets/MasterMaterial/blue.uasset", b"local_ bytes")
        self.assertEqual(len(b"local_ bytes"), len(b"server bytes"))
        plan = service.query_filesystem_state(self.plan(fast=False), verify_content=True)
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(plan["different_files"], ["Assets/MasterMaterial/blue.uasset"])
        self.assertEqual(len(plan["files"]), 2)

    def test_legacy_unknown_mesh_name_at_asset_root_is_supported(self):
        self.relative = "Assets/Props/LanWangD2/UnrelatedMesh.uasset"
        self.package(self.relative)
        with mock.patch.object(service.os.path, "getsize", side_effect=AssertionError("size read")):
            plan = self.plan()
        self.assertEqual(plan["asset_identity_paths"],
                         [service._object_path_from_relative(self.relative)])
        self.assertEqual(plan["state"], "missing")

    def test_multiple_body_packages_do_not_report_complete_when_one_is_missing(self):
        for name, local in [("BodyA", b"server bytes"), ("BodyB", None)]:
            self.package("Assets/Props/LanWangD2/" + name + ".uasset", local)
        plan = self.plan()
        self.assertEqual(plan["state"], "partial")
        self.assertTrue(plan["asset_present"])
        self.assertEqual(len(plan["missing_files"]), 1)

    def test_folder_asset_checks_dependencies_when_namesake_missing_but_another_mesh_exists(self):
        self.package("Assets/Props/LanWangD2/LanWangD2.uasset")
        self.package("Assets/Props/LanWangD2/BodyB.uasset", b"server bytes")
        self.package("Assets/MasterMaterial/blue.uasset", b"different local size")
        plan = self.plan()
        self.assertEqual(plan["check_stage"], "files")
        self.assertTrue(plan["asset_present"])
        self.assertEqual(plan["state"], "conflict")
        self.assertIn("Assets/Props/LanWangD2/LanWangD2.uasset", plan["missing_files"])
        self.assertIn("Assets/MasterMaterial/blue.uasset", plan["different_files"])

    def test_explicit_manifest_wins_over_same_name_sibling(self):
        self.package(self.relative)
        self.package("Assets/Props/LanWangD2/LanWangD2.uasset", b"server bytes")
        self.manifest()
        self.assertEqual(self.plan()["state"], "missing")

    def test_stale_manifest_cannot_establish_source_availability(self):
        self.package("Assets/MasterMaterial/blue.uasset")
        self.manifest()
        with mock.patch.object(service.os, "walk", wraps=service.os.walk) as walk:
            plan = self.plan()
        walk.assert_called_once()
        self.assertEqual(plan["check_stage"], "files")

    def test_refresh_observes_new_main_and_changed_dependencies(self):
        self.package(self.relative)
        self.assertEqual(self.plan()["state"], "missing")
        self.package(self.relative, b"server bytes")
        self.assertEqual(self.plan()["state"], "ready")
        self.package("Assets/MasterMaterial/New.uasset")
        self.assertEqual(self.plan()["state"], "partial")

    def test_map_main_and_legacy_ue_root_are_supported(self):
        self.source = self.root / "UE"
        self.relative = "Assets/Props/LanWangD2/LanWangD2.umap"
        self.package(self.relative)
        with mock.patch.object(service.os.path, "getsize", side_effect=AssertionError("size read")):
            self.assertEqual(self.plan()["state"], "missing")

    def test_local_permission_error_is_not_treated_as_absence(self):
        self.package(self.relative)
        original = service.os.stat
        target = os.path.normcase(os.path.abspath(self.content / self.relative))

        def stat_file(path, *args, **kwargs):
            if os.path.normcase(os.path.abspath(path)) == target:
                raise PermissionError("project file is inaccessible")
            return original(path, *args, **kwargs)

        with mock.patch.object(service.os, "stat", side_effect=stat_file):
            with self.assertRaises(PermissionError):
                self.plan()

    def test_copy_worker_rejects_a_short_circuit_result(self):
        self.package(self.relative)
        errors = []
        worker = service.AssetCopyWorker(self.plan())
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(len(errors), 1)
        self.assertFalse((self.content / self.relative).exists())


class StateGateUITests(ScanPriorityFixture):
    def test_unpublished_cards_never_enter_filesystem_worker_on_both_pages(self):
        for scene in (False, True):
            ui = self.make_ui(scene=scene)
            rows = [(20261028, "Draft%03d" % i, "", "", "未开始", "", "",
                     str(self.root / ("Draft%03d/Icon/p.png" % i)), "", None, "")
                    for i in range(120)]
            with mock.patch.object(service, "build_import_plan") as build:
                ui.main_listWgt.setItems(rows)
                ui.main_listWgt.addItems()
                ui.scanUEAssetStates()
                self.app.processEvents()
            build.assert_not_called()
            self.assertFalse(ui._state_jobs)
            self.assertFalse(ui._state_requests)
            self.assertEqual(ui.main_listWgt.item(0).uePlan()["check_stage"], "database")

    def test_database_status_change_rechecks_previously_skipped_card(self):
        for status in ("制作中", "已完成"):
            with self.subTest(status=status):
                ui = self.make_ui()
                row = [20261028, "Hero", "", "", "", "", "",
                       str(self.root / "Hero/Icon/Hero.png"), "", "未开始", ""]
                ui.main_listWgt.setItems([tuple(row)])
                ui.main_listWgt.addItems()
                ui.scanUEAssetStates()
                self.assertEqual(ui.main_listWgt.item(0).uePlan()["check_stage"], "database")
                ui.main_listWgt.updateStatusData("Hero", (9,), status)
                with mock.patch.object(service, "build_import_plan", side_effect=lambda root, *args, **kwargs: {
                        "asset_root": root, "state": "missing", "source_available": True}) as build:
                    ui.scanUEAssetStates()
                    self.wait_until(lambda: not ui._state_jobs)
                build.assert_called_once()
                self.assertTrue(build.call_args.kwargs["check_primary_first"])
                item = ui.main_listWgt.item(0)
                ui.main_listWgt.setCurrentItem(item)
                self.assertTrue(ui.load_button.isEnabled())
                self.assertEqual(item.isUEPublished(), status == "已完成")
                ui.main_listWgt.updateStatusData("Hero", (9,), "未开始")
                with mock.patch.object(service, "build_import_plan") as build:
                    ui.scanUEAssetStates()
                build.assert_not_called()
                self.assertFalse(ui.load_button.isEnabled())
                self.assertFalse(item.ueSourceAvailability())

    def test_in_progress_missing_local_folder_enables_load_without_server_access(self):
        ui = self.make_ui()
        row = (20261029, "Hero", "", "", "", "", "",
               str(self.root / "Library/Assets/Props/Hero/Icon/Hero.png"), "", "制作中", "")
        ui.main_listWgt.setItems([row])
        ui.main_listWgt.addItems()
        with mock.patch.object(service, "find_source_content_root", side_effect=AssertionError("server probe")), \
                mock.patch.object(service, "_read_manifest", side_effect=AssertionError("manifest read")), \
                mock.patch.object(service.os, "walk", side_effect=AssertionError("directory walk")):
            ui.scanUEAssetStates()
            self.wait_until(lambda: not ui._state_jobs)
        item = ui.main_listWgt.item(0)
        ui.main_listWgt.setCurrentItem(item)
        self.assertEqual(item.uePlan()["check_stage"], "local_folder")
        self.assertTrue(item.ueSourceAvailability())
        self.assertTrue(ui.load_button.isEnabled())
        self.assertFalse(item.isUEPublished())


if __name__ == "__main__":
    unittest.main()
