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
        # Metadata is now read only for files that also exist in the project.
        self.target.mkdir(parents=True)
        (self.target / source.name).write_bytes(b"local package")
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
        return (20261014, name, name, "", "", "", "", str(icon), "", "已完成", "")

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

    def test_unpublished_database_status_skips_automatic_source_checks(self):
        rows = []
        for name in ("red", "green", "gray", "empty", "sidecars"):
            row = list(self.row(name))
            row[9] = "未开始" if name == "green" else "已完成"
            rows.append(tuple(row))
        self.package("green")
        (self.root / "empty/UE").mkdir()
        self.package("sidecars", "UE/Content/Hero.uexp")
        (self.root / "gray/Icon").rmdir()
        (self.root / "gray").rmdir()
        self.ui.listWidgetAddItems(rows)
        self.assertFalse(self.menu_actions(self.item("green"))["加载资产"].isEnabled())
        self.wait_scanned()
        for name, available, directory_exists in (
                ("red", False, False), ("green", False, None), ("gray", None, None),
                ("empty", False, True), ("sidecars", False, True)):
            item = self.item(name)
            self.assertIs(item.ueSourceAvailability(), available)
            self.assertIs(item.ueDirectoryExists(), directory_exists)
            self.assertEqual(item.isUEPublished(), name != "green")
            actions = self.menu_actions(item)
            self.assertEqual(actions["加载资产"].isEnabled(), available is True)
            self.assertFalse(actions["在内容浏览器中定位"].isEnabled())
            self.assertIn(item.ueSourceMessage(), item.toolTip())
        self.assertEqual(self.item("green").ueState(), "missing")

    def test_in_progress_and_completed_enable_load_entries_when_package_exists(self):
        cases = (("wip", "制作中", True), ("done", "已完成", True),
                 ("missing", "制作中", False), ("draft", "未开始", False),
                 ("blank", None, False))
        rows = []
        for name, status, _enabled in cases:
            row = list(self.row(name))
            row[9] = status
            rows.append(tuple(row))
            if name != "missing":
                self.package(name)
        self.ui.listWidgetAddItems(rows)
        self.wait_scanned()
        for name, status, enabled in cases:
            with self.subTest(status=status, name=name):
                item = self.item(name)
                self.ui.main_listWgt.setCurrentItem(item)
                self.assertEqual(item.ueSourceAvailability(), enabled)
                self.assertEqual(self.ui.load_button.isEnabled(), enabled)
                self.assertEqual(self.menu_actions(item)["加载资产"].isEnabled(), enabled)
                self.assertEqual(item.isUEPublished(), status == "已完成")

    def test_in_progress_toolbar_load_copies_existing_release(self):
        row = list(self.row("Hero"))
        row[9] = "制作中"
        source = self.package("Hero", content=b"work in progress package")
        self.ui.listWidgetAddItems([tuple(row)])
        self.wait_scanned()
        item = self.item("Hero")
        self.ui.main_listWgt.setCurrentItem(item)
        self.assertTrue(self.ui.load_button.isEnabled())
        with mock.patch.object(self.ui, "_registerLoadedPlan") as register:
            self.ui.load_button.click()
            self.wait_until(lambda: not self.ui._load_check.isRunning() and self.ui._copy_thread is None)
        register.assert_called_once()
        self.assertEqual((self.target / "Hero.uasset").read_bytes(), source.read_bytes())
        self.assertFalse(item.isUEPublished())

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

        def delayed_build(*args, **kwargs):
            started.set()
            release.wait(5)
            return original_build(*args, **kwargs)

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

        def delayed_first_scan(*args, **kwargs):
            calls.append(args)
            plan = original_build(*args, **kwargs)
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
            self.wait_until(lambda: not self.ui._load_check.isRunning())
        self.ui.listWidgetAddItems()
        item = self.item("Hero")
        self.assertIsNone(item.ueSourceAvailability())
        self.assertFalse(self.menu_actions(item)["加载资产"].isEnabled())
        self.assertIn("NAS offline", item.toolTip())

    def conflicting_release(self):
        row = self.row("Hero")
        files = {
            "Hero.uasset": (b"server_v1", b"local__v1"),
            "Mat/M_Hero.uasset": (b"server_material", b"local__material"),
            "Tex/T_New.uasset": (b"new_texture", None),
        }
        for relative, (server, local) in files.items():
            self.package("Hero", "UE/Content/" + relative, server)
            if local is not None:
                target = self.target / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(local)
        self.ui.listWidgetAddItems([row])
        self.wait_scanned()
        return self.item("Hero"), files

    def test_conflict_dialog_selectively_overwrites_and_loads_missing_packages(self):
        from AssetsManagerForUE.sources import sceneTools
        item, files = self.conflicting_release()

        def choose(dialog):
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            self.assertEqual(tree.topLevelItemCount(), 3)
            self.assertEqual(tree.headerItem().text(3), "类型")
            for index in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(index)
                if row.data(0, QtCore.Qt.UserRole) == "Tex/T_New.uasset":
                    self.assertEqual(row.text(0), "")
                    self.assertEqual(row.text(5), "缺失")
                    self.assertTrue(row.flags() & QtCore.Qt.ItemIsUserCheckable)
                    self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
                    row.setCheckState(0, QtCore.Qt.Checked)
                else:
                    self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
                self.assertTrue(row.text(4))
                self.assertTrue(row.text(5))
                self.assertIn("服务器：", row.toolTip(2))
                if row.data(0, QtCore.Qt.UserRole) == "Hero.uasset":
                    row.setCheckState(0, QtCore.Qt.Checked)
            button = next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                          if button.text() == "加载选中项")
            button.click()
            return dialog.result()

        with mock.patch.object(sceneTools._UEConflictDialog, "exec", choose), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]) as prepare, \
                mock.patch.object(self.ui, "_registerLoadedPlan") as register:
            self.ui.loadUEAsset(item)
            self.wait_until(lambda: not self.ui._load_check.isRunning() and self.ui._copy_thread is None)
        register.assert_called_once()
        finished = register.call_args.args[1]
        self.assertEqual(finished["overwrite_files"], ["Hero.uasset"])
        self.assertEqual(finished["keep_existing_files"], ["Mat/M_Hero.uasset"])
        self.assertEqual(finished["overwritten_files"], ["Hero.uasset"])
        self.assertEqual(finished["kept_existing_files"], ["Mat/M_Hero.uasset"])
        prepare.assert_called_once()
        self.assertEqual((self.target / "Hero.uasset").read_bytes(), files["Hero.uasset"][0])
        self.assertEqual((self.target / "Mat/M_Hero.uasset").read_bytes(), files["Mat/M_Hero.uasset"][1])
        self.assertEqual((self.target / "Tex/T_New.uasset").read_bytes(), files["Tex/T_New.uasset"][0])

    def test_conflict_keep_all_preserves_existing_and_still_loads_missing_packages(self):
        from AssetsManagerForUE.sources import sceneTools
        item, files = self.conflicting_release()

        def keep_all(dialog):
            # Even previously checked rows must be cleared by this button.
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "全选").click()
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "全部保留并加载").click()
            return dialog.result()

        with mock.patch.object(sceneTools._UEConflictDialog, "exec", keep_all), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]), \
                mock.patch.object(self.ui, "_registerLoadedPlan") as register:
            self.ui.loadUEAsset(item)
            self.wait_until(lambda: not self.ui._load_check.isRunning() and self.ui._copy_thread is None)
        register.assert_called_once()
        finished = register.call_args.args[1]
        self.assertEqual(finished["overwrite_files"], [])
        self.assertEqual(finished["overwritten_files"], [])
        self.assertEqual(set(finished["kept_existing_files"]), {"Hero.uasset", "Mat/M_Hero.uasset"})
        for relative, (server, local) in files.items():
            self.assertEqual((self.target / relative).read_bytes(), local if local is not None else server)

    def test_single_file_load_keeps_card_and_cached_plan_yellow_without_manual_refresh(self):
        from AssetsManagerForUE.sources import sceneTools
        item, files = self.conflicting_release()
        def choose(dialog):
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            for index in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(index)
                self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
                if row.data(0, QtCore.Qt.UserRole) == "Hero.uasset":
                    row.setCheckState(0, QtCore.Qt.Checked)
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "加载选中项").click()
            return dialog.result()
        library = mock.Mock()
        library.does_asset_exist.side_effect = lambda path: (self.target / (path.split(".", 1)[0].removeprefix("/Game/") + ".uasset")).is_file()
        engine = types.SimpleNamespace(EditorAssetLibrary=library, find_package=lambda name: None,
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: mock.Mock()))
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", choose), \
                mock.patch.object(ue_asset_service, "unreal", engine), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]), \
                mock.patch.object(ue_asset_service, "sync_plan_to_content_browser", return_value=(True, "/Game/Hero.Hero")):
            self.ui.loadUEAsset(item)
            self.wait_until(lambda: not self.ui._load_check.isRunning() and self.ui._copy_thread is None)
        self.assertEqual(item.ueState(), "conflict")
        self.assertEqual(item.uePlan()["different_files"], ["Mat/M_Hero.uasset"])
        self.assertEqual(item.uePlan()["missing_files"], ["Tex/T_New.uasset"])
        self.assertEqual((self.target / "Hero.uasset").read_bytes(), files["Hero.uasset"][0])
        self.assertEqual((self.target / "Mat/M_Hero.uasset").read_bytes(), files["Mat/M_Hero.uasset"][1])
        self.assertFalse((self.target / "Tex/T_New.uasset").exists())
        self.ui.listWidgetAddItems()
        self.assertEqual(self.item("Hero").ueState(), "conflict")

    def test_missing_asset_still_prompts_for_shared_conflicts_and_copies_main(self):
        from AssetsManagerForUE.sources import sceneTools
        self.root = self.root / "Assets/Props"
        item, files = self.conflicting_release()
        (self.target / "Hero.uasset").unlink()
        plan = ue_asset_service.build_import_plan(
            ue_asset_service.asset_root_from_item_data(item.itemData()), str(self.target))
        plan = ue_asset_service.query_filesystem_state(plan, verify_content=True)
        self.assertEqual(plan["state"], "missing")
        self.assertTrue(plan["different_files"])

        # Both pages must offer conflict choices even though the card is red.
        scene = mock.Mock()
        scene._state_closed = False
        scene._state_requests = {}
        scene._findItemByKey.return_value = None
        scene._chooseConflictFiles.return_value = False
        sceneTools.SceneToolsUI._onLoadChecked(scene, "Hero", dict(plan))
        scene._chooseConflictFiles.assert_called_once()

        def keep_all(dialog):
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "全选").click()
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "全部保留并加载").click()
            return dialog.result()

        with mock.patch.object(sceneTools._UEConflictDialog, "exec", keep_all), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]), \
                mock.patch.object(self.ui, "_registerLoadedPlan") as register:
            self.ui.loadUEAsset(item)
            self.wait_until(lambda: not self.ui._load_check.isRunning() and self.ui._copy_thread is None)
        register.assert_called_once()
        self.assertEqual((self.target / "Hero.uasset").read_bytes(), files["Hero.uasset"][0])
        self.assertEqual((self.target / "Mat/M_Hero.uasset").read_bytes(), files["Mat/M_Hero.uasset"][1])

    def test_conflict_cancel_does_not_start_copy_or_change_any_files(self):
        from AssetsManagerForUE.sources import sceneTools
        item, files = self.conflicting_release()

        def cancel(dialog):
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == "取消").click()
            return dialog.result()

        with mock.patch.object(sceneTools._UEConflictDialog, "exec", cancel), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites") as prepare, \
                mock.patch.object(ue_asset_service, "AssetCopyWorker") as worker:
            self.ui.loadUEAsset(item)
            self.wait_until(lambda: not self.ui._load_check.isRunning())
        worker.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(item.ueState(), "conflict")
        self.assertIsNone(self.ui._copy_thread)
        for relative, (_server, local) in files.items():
            if local is None:
                self.assertFalse((self.target / relative).exists())
            else:
                self.assertEqual((self.target / relative).read_bytes(), local)

    def test_shared_conflict_dialog_select_all_invert_and_scene_entry_point(self):
        from AssetsManagerForUE.sources import sceneTools
        item, _files = self.conflicting_release()
        plan = ue_asset_service.query_filesystem_state(dict(item.uePlan()), verify_content=True)

        def choose(dialog):
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            buttons = {button.text(): button for button in dialog.findChildren(QtWidgets.QPushButton)}
            conflicts = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                         if tree.topLevelItem(i).data(0, QtCore.Qt.UserRole + 1) == "conflict"]
            self.assertEqual(len(conflicts), 2)
            buttons["全选"].click()
            self.assertTrue(all(row.checkState(0) == QtCore.Qt.Checked for row in conflicts))
            buttons["反选"].click()
            self.assertTrue(all(row.checkState(0) == QtCore.Qt.Unchecked for row in conflicts))
            header = dialog.findChild(sceneTools._UEHeaderCheckBox)
            header.nextCheckState()
            self.assertTrue(all(row.checkState(0) == QtCore.Qt.Checked for row in conflicts))
            buttons["加载选中项"].click()
            return dialog.result()

        with mock.patch.object(sceneTools._UEConflictDialog, "exec", choose):
            self.assertTrue(sceneTools.SceneToolsUI._chooseConflictFiles(self.ui, plan))
        self.assertEqual(set(plan["overwrite_files"]), {"Hero.uasset", "Mat/M_Hero.uasset"})
        self.assertEqual(plan["keep_existing_files"], [])

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
            self.wait_until(lambda: not self.ui._load_check.isRunning())
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
        widget = myWidget.MainQListWiget()
        item = myWidget.Item()
        item.setItemsWidget(widget)
        row = list(self.row("Hero"))
        row[9] = "已完成"
        item.setItemData(tuple(row))
        item.setUESourceAvailability(True, "server ready", ue_directory_exists=True)
        # Other library pages do not opt into database badges.
        self.assertFalse(item.isUEPublished())
        self.assertFalse(self.badge_painted(item))
        widget.setUEPublishedStatusField(9, "已完成")
        item.setUEState("error", "project copy failed")
        self.assertTrue(item.isUEPublished())
        self.assertTrue(self.badge_painted(item))
        self.assertIs(item.ueSourceAvailability(), True)
        self.assertIn("server ready", item.toolTip())
        self.assertIn("project copy failed", item.toolTip())
        widget.deleteLater()

    def badge_painted(self, item):
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 124, 164)
        image = QtGui.QImage(124, 164, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        item.paintUEPublished(painter, option)
        painter.end()
        return any(image.constBits())

    def test_label_follows_ue_status_and_ignores_model_rig_and_directory(self):
        item = myWidget.Item()
        item.setItemsWidget(self.ui.main_listWgt)
        row = list(self.row("Hero"))
        for status in (None, "", "未开始", "制作中", "已完成", "ue", " UE ", "UE"):
            row[4], row[6], row[9] = "UE", "已完成", status
            item.setItemData(tuple(row))
            for directory_exists in (True, False, None):
                with self.subTest(status=status, directory_exists=directory_exists):
                    item.setUESourceAvailability(False, "no main package", ue_directory_exists=directory_exists)
                    self.assertEqual(item.isUEPublished(), status == "已完成")
                    self.assertEqual(self.badge_painted(item), status == "已完成")

    def test_label_is_visible_before_scan_and_safe_for_missing_row_data(self):
        item = myWidget.Item()
        item.setItemsWidget(self.ui.main_listWgt)
        row = list(self.row("Hero"))
        row[9] = "已完成"
        item.setItemData(tuple(row))
        self.assertIsNone(item.ueSourceAvailability())
        self.assertIsNone(item.ueDirectoryExists())
        self.assertTrue(self.badge_painted(item))
        for row_data in ((), {}, None):
            item._itemData = row_data
            self.assertFalse(item.isUEPublished())
            self.assertFalse(self.badge_painted(item))


if __name__ == "__main__":
    unittest.main()
