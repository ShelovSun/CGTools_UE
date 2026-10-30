"""Disk replacement must also update loaded UE objects before reporting ready."""

import copy
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from AssetsManagerForUE.sources import ue_asset_service as service


class PackageReloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.relative = "Assets/Props/LanWangD/LanWangD2.uasset"
        self.name = "/Game/Assets/Props/LanWangD/LanWangD2"
        self.path = self.name + ".LanWangD2"
        self.source = self.root / "Server/Content" / self.relative
        self.target = self.root / "Project/Content" / self.relative
        self.source.parent.mkdir(parents=True)
        self.target.parent.mkdir(parents=True)
        self.source.write_bytes(b"server with material")
        self.target.write_bytes(b"old without material")
        self.plan = {
            "target_root": str(self.root / "Project/Content"),
            "files": [{"relative": self.relative, "source": str(self.source),
                       "target": str(self.target), "extension": ".uasset", "size": self.source.stat().st_size}],
            "package_object_paths": [self.path], "main_object_path": self.path,
            "overwrite_files": [self.relative], "overwritten_files": [],
        }
        self.package = mock.Mock()
        self.package.get_name.return_value = self.name
        self.loaded = {self.name: self.package}
        self.utils = mock.Mock()
        self.utils.get_dirty_content_packages.return_value = []
        self.utils.get_dirty_map_packages.return_value = []
        self.utils.reload_packages.return_value = (True, "")
        self.library = mock.Mock()
        self.library.does_asset_exist.return_value = True
        self.registry = mock.Mock()
        self.dialog = mock.Mock()
        self.dialog.show_message.return_value = "yes"
        self.engine = types.SimpleNamespace(
            EditorLoadingAndSavingUtils=self.utils, EditorAssetLibrary=self.library,
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: self.registry),
            find_package=mock.Mock(side_effect=self.loaded.get),
            ReloadPackagesInteractionMode=types.SimpleNamespace(ASSUME_POSITIVE="positive"),
            EditorDialog=self.dialog, AppMsgType=types.SimpleNamespace(YES_NO="yes_no"),
            AppReturnType=types.SimpleNamespace(YES="yes", NO="no"))
        self.patch = mock.patch.object(service, "unreal", self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        service._pending_package_reloads.clear()
        self.addCleanup(service._pending_package_reloads.clear)

    def copy(self, prepare=True):
        if prepare:
            self.assertEqual(service.prepare_plan_overwrites(self.plan), [])
        results, failures = [], []
        worker = service.AssetCopyWorker(self.plan)
        worker.finished.connect(results.append)
        worker.failed.connect(failures.append)
        worker.run()
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 1)
        return results[0]

    def test_real_copy_then_reload_precedes_ready_and_asset_resolution(self):
        plan = self.copy()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(plan["state"], "partial")
        events = []
        self.utils.reload_packages.side_effect = lambda *args: (events.append("reload") or True, "")
        with mock.patch.object(service, "resolve_placeable_object_path",
                               side_effect=lambda plan: events.append("resolve") or self.path):
            service.refresh_asset_registry(plan)
        self.assertEqual(events, ["reload", "resolve"])
        self.assertEqual(plan["state"], "ready")
        self.assertEqual(plan["reloaded_packages"], [self.name])
        self.utils.reload_packages.assert_called_once_with([self.package], "positive")
        self.assertEqual(service._pending_reloads_for_plan(plan), [])

    def test_sidecar_selection_reloads_its_package_once_and_excludes_kept_files(self):
        plan = dict(self.plan, overwritten_files=[self.relative, self.relative[:-7] + ".ubulk"],
                    kept_existing_files=["Assets/Props/Other.uasset"])
        service.reload_overwritten_packages(plan)
        self.utils.reload_packages.assert_called_once_with([self.package], "positive")
        self.assertEqual(plan["reloaded_packages"], [self.name])

    def test_sidecar_only_overwrite_is_prepared_and_reloaded(self):
        plan = dict(self.plan, overwrite_files=[self.relative[:-7] + ".ubulk"],
                    overwritten_files=[self.relative[:-7] + ".ubulk"])
        service.prepare_plan_overwrites(plan)
        service.reload_overwritten_packages(plan)
        self.utils.fully_load_packages.assert_called_once_with([self.package])
        self.utils.reload_packages.assert_called_once()

    def test_new_or_unloaded_packages_need_no_reload(self):
        service.reload_overwritten_packages(self.plan)
        self.utils.reload_packages.assert_not_called()
        self.loaded.clear()
        plan = dict(self.plan, overwritten_files=[self.relative])
        service.reload_overwritten_packages(plan)
        self.utils.reload_packages.assert_not_called()
        self.assertEqual(service._pending_reloads_for_plan(plan), [])

    def test_dirty_confirmation_happens_before_disk_replacement(self):
        self.utils.get_dirty_content_packages.return_value = [self.package]
        self.dialog.show_message.side_effect = lambda *args: (
            self.assertEqual(self.target.read_bytes(), b"old without material") or "yes")
        plan = self.copy()
        self.dialog.show_message.assert_called_once()
        self.assertEqual(plan["approved_dirty_reload_packages"], [self.name])
        service.reload_overwritten_packages(plan)
        self.utils.reload_packages.assert_called_once()
        self.utils.save_packages.assert_not_called()

    def test_declining_dirty_overwrite_preserves_disk_and_prevents_worker_copy(self):
        self.utils.get_dirty_content_packages.return_value = [self.package]
        self.dialog.show_message.return_value = "no"
        service.prepare_plan_overwrites(self.plan)
        self.assertTrue(self.plan["overwrite_cancelled"])
        worker = service.AssetCopyWorker(self.plan)
        failures = []
        worker.failed.connect(failures.append)
        worker.run()
        self.assertEqual(self.target.read_bytes(), b"old without material")
        self.assertEqual(len(failures), 1)
        self.utils.fully_load_packages.assert_not_called()

    def test_unconfirmed_edit_during_copy_does_not_get_discarded(self):
        plan = self.copy()
        self.utils.get_dirty_content_packages.return_value = [self.package]
        service.refresh_asset_registry(plan)
        self.utils.reload_packages.assert_not_called()
        self.assertEqual(plan["state"], "partial")
        self.assertIn("未保存修改", plan["reload_error"])

    def test_failure_stays_non_green_on_background_scan_and_retries_without_recopy(self):
        plan = self.copy()
        self.utils.reload_packages.return_value = (False, "package busy")
        service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "partial")
        self.assertIn("package busy", plan["message"])
        fresh = copy.deepcopy(self.plan)
        fresh["overwrite_files"] = []
        service.query_filesystem_state(fresh, verify_content=True)
        self.assertEqual(fresh["different_files"], [])
        self.assertEqual(fresh["state"], "partial")
        self.assertEqual(fresh["pending_reload_packages"], [self.name])
        self.utils.reload_packages.return_value = (True, "")
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=self.path):
            service.refresh_asset_registry(fresh)
        self.assertEqual(fresh["state"], "ready")
        self.assertEqual(self.utils.reload_packages.call_count, 2)

    def test_partial_native_success_with_error_is_not_reported_ready(self):
        plan = dict(self.plan, overwritten_files=[self.relative])
        self.utils.reload_packages.return_value = (True, "one package failed")
        service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "partial")
        self.assertIn("one package failed", plan["reload_error"])

    def test_native_exception_keeps_pending_state_and_does_not_resolve_old_object(self):
        plan = dict(self.plan, overwritten_files=[self.relative])
        self.utils.reload_packages.side_effect = RuntimeError("cannot reload")
        with mock.patch.object(service, "resolve_placeable_object_path") as resolve:
            service.refresh_asset_registry(plan)
        resolve.assert_not_called()
        self.assertEqual(plan["state"], "partial")
        self.assertEqual(service._pending_reloads_for_plan(plan), [self.name])

    def test_unrelated_project_with_same_package_name_has_independent_state(self):
        service._set_pending_package_reloads(self.plan, [self.name])
        other = dict(self.plan, target_root=str(self.root / "Other/Content"))
        self.assertEqual(service._pending_reloads_for_plan(other), [])

    def test_kept_same_size_conflict_stays_yellow_after_registry_refresh(self):
        self.source.write_bytes(b"server_v1")
        self.target.write_bytes(b"local__v1")
        self.plan.update(overwrite_files=[], keep_existing_files=[self.relative])
        plan = self.copy()
        self.assertEqual(plan["state"], "conflict")
        self.assertEqual(plan["different_files"], [self.relative])
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=self.path), \
                mock.patch.object(service, "query_filesystem_state", side_effect=AssertionError("UI thread must not rescan files")):
            service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "conflict")
        self.assertIn("仍有 1 个文件与服务器不同", plan["message"])
        self.assertEqual(self.target.read_bytes(), b"local__v1")

    def test_unchecked_missing_package_is_partial_instead_of_registry_error(self):
        relative = "Tex/T_New.uasset"
        source = self.root / "Server/Content" / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(b"new texture")
        target = self.root / "Project/Content" / relative
        self.plan["files"].append({"relative": relative, "source": str(source), "target": str(target),
                                   "extension": ".uasset", "size": source.stat().st_size})
        new_path = "/Game/Tex/T_New.T_New"
        self.plan["package_object_paths"].append(new_path)
        self.plan["skipped_missing_files"] = [relative]
        plan = self.copy()
        self.library.does_asset_exist.side_effect = lambda path: path != new_path
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=self.path):
            service.refresh_asset_registry(plan)
        self.assertFalse(target.exists())
        self.assertEqual(plan["state"], "partial")
        self.assertEqual(plan["missing_files"], [relative])
        self.assertIn("仍有 1 个文件缺失", plan["message"])
        self.assertNotIn("missing_packages", plan)

    def test_missing_sidecar_prevents_green_even_when_all_primary_packages_register(self):
        plan = self.copy()
        plan["missing_files"] = [self.relative[:-7] + ".ubulk"]
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=self.path):
            service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "partial")

    def test_non_placeable_category_keeps_remaining_conflict(self):
        plan = dict(self.plan, different_files=[self.relative], kept_existing_files=[self.relative])
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=""):
            service.refresh_asset_registry(plan, require_placeable=False)
        self.assertEqual(plan["state"], "conflict")

    def test_missing_asset_identity_stays_unloaded_after_registry_refresh(self):
        plan = dict(self.plan, asset_present=False, missing_files=[self.relative])
        with mock.patch.object(service, "resolve_placeable_object_path", return_value=""):
            service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "missing")

    def test_unexpected_unrecognized_package_is_still_an_error(self):
        plan = self.copy()
        self.library.does_asset_exist.return_value = False
        service.refresh_asset_registry(plan)
        self.assertEqual(plan["state"], "error")
        self.assertEqual(plan["missing_packages"], [self.path])


if __name__ == "__main__":
    unittest.main()
