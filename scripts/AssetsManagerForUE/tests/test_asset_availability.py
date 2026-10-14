"""Server release availability, cached card scans and load-menu regressions."""

import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import unreal
except ImportError:
    unreal = types.ModuleType("unreal")
    unreal.log_warning = lambda text: None
    sys.modules["unreal"] = unreal

from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.sources import assetTools, ue_asset_service
from AssetsManagerForUE.utils import myWidget


class OfflineAssetToolsUI(assetTools.AssetToolsUI):
    def _startInitialLoad(self):
        pass

    def rememberSettings(self):
        pass

    def _requestAssetData(self):
        pass

    def _ensurePreviewWidgets(self):
        return False

    def infoMsg(self, icon, text):
        self.msg_label.setText(text)


class ReleaseAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset_release_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "角色"
        self.root.mkdir()
        self.target = Path(self.temporary.name) / "Project/Content"

    def package(self, relative, content=b"package"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def plan(self):
        return ue_asset_service.build_import_plan(str(self.root), str(self.target))

    def scan(self):
        results = []
        worker = ue_asset_service.AssetStateWorker(1, [("key", str(self.root))], str(self.target))
        worker.itemScanned.connect(lambda generation, key, plan: results.append(plan))
        worker.run()
        self.assertEqual(len(results), 1)
        return results[0]

    def test_absent_empty_and_sidecar_only_releases_are_unavailable(self):
        plan = self.plan()
        self.assertIs(plan["source_available"], False)
        self.assertIs(plan["ue_directory_exists"], False)
        (self.root / "UE/Content").mkdir(parents=True)
        plan = self.plan()
        self.assertIs(plan["source_available"], False)
        self.assertIs(plan["ue_directory_exists"], True)
        for extension in ("uexp", "ubulk", "uptnl"):
            self.package("UE/Content/角色." + extension)
        plan = self.plan()
        self.assertIs(plan["source_available"], False)
        self.assertIs(plan["ue_directory_exists"], True)
        self.assertEqual(plan["package_object_paths"], [])

    def test_main_package_is_available_even_when_not_loaded_into_project(self):
        for relative in ("UE/Content/角色/网格.uASSET", "UE/Content/地图.umap"):
            self.package(relative)
        plan = self.plan()
        self.assertIs(plan["source_available"], True)
        self.assertEqual(plan["state"], "missing")
        self.assertEqual(len(plan["package_object_paths"]), 2)

    def test_legacy_release_is_walked_once_without_traversing_fbx(self):
        self.package("UE/角色/网格.uasset")
        self.package("FBX/很深/模型.fbx")
        with mock.patch.object(ue_asset_service.os, "walk", wraps=os.walk) as walk:
            plan = self.plan()
        self.assertIs(plan["source_available"], True)
        self.assertEqual(walk.call_count, 1)
        self.assertEqual(walk.call_args.args[0], str(self.root / "UE"))

    def test_inaccessible_source_is_unknown_rather_than_unavailable(self):
        with mock.patch.object(ue_asset_service.os, "stat", side_effect=PermissionError("NAS denied")):
            plan = self.scan()
        self.assertIsNone(plan["source_available"])
        self.assertIn("NAS denied", plan["source_message"])
        self.assertEqual(plan["state"], "error")

    def test_disconnected_or_deleted_asset_root_is_unknown(self):
        self.root.rmdir()
        self.assertIsNone(self.scan()["source_available"])

    def test_walk_and_package_metadata_errors_are_not_silently_ignored(self):
        source = self.package("UE/Content/角色.uasset")
        original_scandir = os.scandir

        def inaccessible_directory(path):
            if os.fspath(path) == str(source.parent):
                raise PermissionError("release unreadable")
            return original_scandir(path)

        with mock.patch.object(ue_asset_service.os, "scandir", side_effect=inaccessible_directory):
            self.assertIsNone(self.scan()["source_available"])
        with mock.patch.object(ue_asset_service.os.path, "getsize", side_effect=PermissionError("metadata denied")):
            self.assertIsNone(self.scan()["source_available"])


class AssetCardAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset_card_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Library"
        self.target = Path(self.temporary.name) / "Project/Content"
        patcher = mock.patch.object(ue_asset_service, "_project_content_dir", return_value=str(self.target))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ue_asset_service, "resolve_placeable_object_path", return_value="/Game/Hero.Hero")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ui = OfflineAssetToolsUI(isSQL=False)
        self.ui.resize(1000, 500)
        self.ui.show()
        self.app.processEvents()

    def tearDown(self):
        self.ui.shutdownThreads()
        self.app.processEvents()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.ui.close()
        self.ui.deleteLater()
        self.app.processEvents()

    def row(self, name):
        icon = self.root / name / "Icon" / (name + ".png")
        icon.parent.mkdir(parents=True, exist_ok=True)
        return (20261014, name, name, "", "", "", "", str(icon), "")

    def package(self, name, relative="UE/Content/Hero.uasset", content=b"package"):
        path = self.root / name / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def wait_until(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.002)
        self.fail("background scan did not finish")

    def wait_scanned(self):
        self.wait_until(lambda: not self.ui._state_pending and not self.ui._state_jobs)

    def item(self, name):
        return next(self.ui.main_listWgt.item(index)
                    for index in range(self.ui.main_listWgt.count())
                    if self.ui.main_listWgt.item(index).name() == name)

    def menu_actions(self, item):
        captured = []
        self.ui.main_listWgt.doItemsLayout()
        point = self.ui.main_listWgt.visualItemRect(item).center()
        with mock.patch.object(QtWidgets.QMenu, "exec_", lambda menu, *args: captured.append(menu)):
            self.ui.show_menu(point)
        self.assertEqual(len(captured), 1)
        return {action.text(): action for action in captured[0].actions()}

    def test_load_menu_availability_and_directory_label_have_separate_rules(self):
        rows = [self.row(name) for name in ("red", "green", "gray", "empty", "sidecars")]
        self.package("green")
        (self.root / "empty/UE").mkdir()
        self.package("sidecars", "UE/Content/Hero.uexp")
        (self.root / "gray/Icon").rmdir()
        (self.root / "gray").rmdir()
        self.ui.listWidgetAddItems(rows)
        self.assertFalse(self.menu_actions(self.item("green"))["加载资产"].isEnabled())
        self.wait_scanned()
        for name, available, directory_exists in (
                ("red", False, False), ("green", True, True), ("gray", None, None),
                ("empty", False, True), ("sidecars", False, True)):
            item = self.item(name)
            self.assertIs(item.ueSourceAvailability(), available)
            self.assertIs(item.ueDirectoryExists(), directory_exists)
            actions = self.menu_actions(item)
            self.assertEqual(actions["加载资产"].isEnabled(), available is True)
            self.assertFalse(actions["在内容浏览器中定位"].isEnabled())
            self.assertIn(item.ueSourceMessage(), item.toolTip())
        self.assertEqual(self.item("green").ueState(), "missing")

    def test_sort_search_display_and_duplicate_source_cards_reuse_scans(self):
        row = self.row("Hero")
        self.package("Hero")
        duplicate = list(row)
        duplicate[7] = str(self.root / "Hero/Icon/another.png")
        with mock.patch.object(ue_asset_service, "build_import_plan", wraps=ue_asset_service.build_import_plan) as build:
            self.ui.listWidgetAddItems([row, tuple(duplicate)])
            self.wait_scanned()
            self.assertEqual(build.call_count, 1)
            self.ui._do_sort(1)
            self.ui.key_line.setText("absent")
            self.ui.search_asset()
            self.ui.key_line.clear()
            self.ui.search_asset()
            self.ui.viewThumbnailChange()
            self.ui.viewThumbnailChange()
            self.app.processEvents()
            self.assertEqual(build.call_count, 1)
            self.assertIs(self.item("Hero").ueSourceAvailability(), True)

    def test_view_rebuild_during_scan_does_not_cancel_or_start_another_scan(self):
        row = self.row("Hero")
        self.package("Hero")
        started = threading.Event()
        release = threading.Event()
        original_build = ue_asset_service.build_import_plan

        def delayed_build(*args):
            started.set()
            release.wait(5)
            return original_build(*args)

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=delayed_build) as build:
            try:
                self.ui.listWidgetAddItems([row])
                self.wait_until(started.is_set)
                generation = self.ui._state_generation
                self.ui._do_sort(1)
                self.ui.viewThumbnailChange()
                self.app.processEvents()
                self.assertEqual(build.call_count, 1)
                self.assertEqual(self.ui._state_generation, generation)
                self.assertEqual(len(self.ui._state_jobs), 1)
            finally:
                release.set()
            self.wait_scanned()
        self.assertIs(self.item("Hero").ueSourceAvailability(), True)

    def test_refresh_rechecks_added_and_removed_release(self):
        row = self.row("Hero")
        with mock.patch.object(ue_asset_service, "build_import_plan", wraps=ue_asset_service.build_import_plan) as build:
            self.ui.listWidgetAddItems([row])
            self.wait_scanned()
            self.assertIs(self.item("Hero").ueSourceAvailability(), False)
            source = self.package("Hero")
            self.ui.refresh_asset()
            self.wait_scanned()
            self.assertIs(self.item("Hero").ueSourceAvailability(), True)
            source.unlink()
            self.ui.refresh_asset()
            self.wait_scanned()
            self.assertIs(self.item("Hero").ueSourceAvailability(), False)
            self.assertEqual(build.call_count, 3)

    def test_refresh_during_old_scan_discards_stale_results_and_serializes_workers(self):
        row = self.row("Hero")
        self.package("Hero")
        started = threading.Event()
        release = threading.Event()
        original_build = ue_asset_service.build_import_plan
        calls = []

        def delayed_first_scan(*args):
            calls.append(args)
            plan = original_build(*args)
            if len(calls) == 1:
                started.set()
                release.wait(5)
            return plan

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=delayed_first_scan):
            try:
                self.ui.listWidgetAddItems([row])
                self.wait_until(started.is_set)
                (self.root / "Hero/UE/Content/Hero.uasset").unlink()
                self.ui.refresh_asset()
                self.app.processEvents()
                self.assertEqual(len(calls), 1)
                self.assertIsNone(self.item("Hero").ueSourceAvailability())
                self.assertEqual(len(self.ui._state_jobs), 1)
            finally:
                release.set()
            self.wait_scanned()
        self.assertEqual(len(calls), 2)
        self.assertIs(self.item("Hero").ueSourceAvailability(), False)

    def test_explicit_load_access_error_replaces_cached_availability_with_unknown(self):
        row = self.row("Hero")
        self.package("Hero")
        self.ui.listWidgetAddItems([row])
        self.wait_scanned()
        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=PermissionError("NAS offline")):
            self.ui.loadUEAsset(self.item("Hero"))
        self.ui.listWidgetAddItems()
        item = self.item("Hero")
        self.assertIsNone(item.ueSourceAvailability())
        self.assertFalse(self.menu_actions(item)["加载资产"].isEnabled())
        self.assertIn("NAS offline", item.toolTip())

    def test_explicit_load_rechecks_source_and_supersedes_old_scan_results(self):
        row = self.row("Hero")
        source = self.package("Hero")
        self.ui.listWidgetAddItems([row])
        self.wait_scanned()
        item = self.item("Hero")
        old_plan = dict(item.uePlan())
        source.unlink()
        with mock.patch.object(self.ui, "_showMissingUEPackageDialog") as dialog, \
                mock.patch.object(ue_asset_service, "AssetCopyWorker") as copy:
            self.ui.loadUEAsset(item)
        dialog.assert_called_once()
        copy.assert_not_called()
        self.assertIs(item.ueSourceAvailability(), False)
        key = self.ui._sourceCacheKey(str(source.parents[2]))
        self.ui._applyUEState(self.ui._state_generation, key, old_plan)
        self.ui.listWidgetAddItems()
        self.assertIs(self.item("Hero").ueSourceAvailability(), False)
        self.assertFalse(self.menu_actions(self.item("Hero"))["加载资产"].isEnabled())

    def test_loaded_plan_survives_rebuild_and_registers_when_card_is_filtered_out(self):
        row = self.row("Hero")
        self.package("Hero")
        self.ui.listWidgetAddItems([row])
        self.wait_scanned()
        plan = dict(self.item("Hero").uePlan(), state="ready", main_object_path="/Game/Hero.Hero")
        self.ui.key_line.setText("absent")
        self.ui.search_asset()
        with mock.patch.object(ue_asset_service, "refresh_asset_registry", return_value=plan) as register, \
                mock.patch.object(ue_asset_service, "sync_plan_to_content_browser", return_value=(True, "/Game/Hero.Hero")):
            self.ui._copy_item_key = str(row[7])
            self.ui._onCopyFinished(plan)
        register.assert_called_once()
        self.ui.key_line.clear()
        self.ui.search_asset()
        self.assertEqual(self.item("Hero").ueState(), "ready")
        self.assertIs(self.item("Hero").ueSourceAvailability(), True)

    def test_badge_is_opt_in_and_project_errors_do_not_change_source_availability(self):
        item = myWidget.Item()
        item.setItemsWidget(self.ui.main_listWgt)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 124, 164)
        image = QtGui.QImage(124, 164, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        item.paintUESourceAvailability(painter, option)
        painter.end()
        self.assertFalse(any(image.pixelColor(x, y).alpha() for x in range(124) for y in range(164)))
        item.setUESourceAvailability(True, "server ready", ue_directory_exists=True)
        item.setUEState("error", "project copy failed")
        self.assertIs(item.ueSourceAvailability(), True)
        self.assertIn("server ready", item.toolTip())
        self.assertIn("project copy failed", item.toolTip())

    def test_label_is_drawn_for_existing_empty_ue_directory_only(self):
        item = myWidget.Item()
        item.setItemsWidget(self.ui.main_listWgt)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 124, 164)
        for directory_exists in (True, False, None):
            # An existing empty directory is labelled even though it cannot load.
            item.setUESourceAvailability(False, "no main package", ue_directory_exists=directory_exists)
            image = QtGui.QImage(124, 164, QtGui.QImage.Format_ARGB32)
            image.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(image)
            item.paintUESourceAvailability(painter, option)
            painter.end()
            painted = any(image.pixelColor(x, y).alpha() for x in range(124) for y in range(164))
            self.assertEqual(painted, directory_exists is True)


if __name__ == "__main__":
    unittest.main()
