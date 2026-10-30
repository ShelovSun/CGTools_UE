"""Offline regression checks for the VFX folder tree and asset cards."""

import copy
import os
import shutil
import sys
import tempfile
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

from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from AssetsManagerForUE.sources import vfxTools, blueprintTools, ue_asset_service
from AssetsManagerForUE.utils import myWidget


class OfflineVfxToolsUI(vfxTools.VfxToolsUI):
    def refreshLibrary(self):
        pass

    def _readSettings(self):
        return 120, None, False

    def _rememberSettings(self):
        pass

    def _queueThumbnails(self, assets):
        self.queued_assets = list(assets)

    def infoMsg(self, icon, text):
        self.message_label.setText(text)


class VfxLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vfx_library_tree_")
        self.addCleanup(self.temporary.cleanup)
        self.content = Path(self.temporary.name) / "Library/Content"
        self.root = self.content / "VFX"
        self.project = Path(self.temporary.name) / "Project/Content"
        for relative in (
            "NS_Root.uasset", "Team1/火/NS_Fire.uasset",
            "Team1/火/P_Legacy.uASSET", "Team1/火/Mat/M_Fire.uasset",
            "Team1/火/Tex/T_Fire.uasset", "Team1/火/E_Emitter.uasset",
            "Team1/火/NS_Fire/NS_Child.uasset", "Team2/火/NS_Fire.uasset",
            "Team1/多层/二级/三级/四级/NS_Deep.uasset",
        ):
            self.create_asset(relative)
        (self.root / "Team1/空文件夹").mkdir()
        (self.root / "Team1/火/readme.txt").write_text("not an asset", encoding="utf-8")
        self.payload = self.scan()
        self.assets = {}

        def collect(directory):
            for asset in directory["assets"]:
                self.assets[asset["path"]] = asset
                # Keep generated test thumbnails inside this test's temporary tree.
                asset["thumbnail"] = str(Path(self.temporary.name) / "Thumbnails" / (asset["path"] + ".png"))
                asset["no_thumbnail"] = asset["thumbnail"] + ".no_thumbnail"
            for child in directory["categories"]:
                collect(child)

        collect(self.payload)
        self.ui = None

    def tearDown(self):
        if self.ui is not None:
            self.ui.shutdownThreads()
            self.ui.close()
            self.ui.deleteLater()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def create_asset(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"external package payload")
        return path

    def scan(self, task=None):
        task = task or vfxTools._LibraryScanTask(7, [str(self.content)], str(self.project))
        results, errors = [], []
        task.signals.loaded.connect(lambda generation, payload: results.append(payload))
        task.signals.failed.connect(lambda generation, text: errors.append(text))
        task.run()
        self.assertEqual(errors, [])
        return results[0] if results else None

    @staticmethod
    def class_names(paths, content_root):
        classes = {"NS_": "/Script/Niagara.NiagaraSystem", "P_L": "ParticleSystem",
                   "M_F": "Material", "T_F": "Texture2D", "E_E": "NiagaraEmitter"}
        return [classes[Path(path).stem[:3]] for path in paths], ""

    def finish_scan(self):
        with mock.patch.object(ue_asset_service, "get_external_asset_class_names",
                               side_effect=self.class_names) as query:
            self.ui._scanFinished(self.ui._scan_generation, copy.deepcopy(self.payload))
        return query

    def build_ui(self, preferred=""):
        self.ui = OfflineVfxToolsUI()
        self.ui._preferred_category = preferred
        self.ui.resize(1100, 600)
        self.finish_scan()
        self.ui.show()
        self.app.processEvents()
        return self.ui

    def card(self, name):
        for index in range(self.ui.card_list.count()):
            item = self.ui.card_list.item(index)
            if item.name() == name:
                return item
        self.fail("Card not found: " + name)

    def double_click(self, name, button=QtCore.Qt.LeftButton):
        item = self.card(name)
        point = self.ui.card_list.visualItemRect(item).center()
        QtTest.QTest.mouseClick(self.ui.card_list.viewport(), button, QtCore.Qt.NoModifier, point)
        QtTest.QTest.mouseDClick(self.ui.card_list.viewport(), button, QtCore.Qt.NoModifier, point)
        self.app.processEvents()

    def test_scan_recurses_and_preserves_package_and_target_paths(self):
        path = "Team1/多层/二级/三级/四级/NS_Deep.uasset"
        self.assertEqual(len(self.assets), 7)
        asset = self.assets[path]
        self.assertEqual(asset["relative"], "VFX/" + path)
        self.assertEqual(asset["object_path"], "/Game/VFX/Team1/多层/二级/三级/四级/NS_Deep.NS_Deep")
        self.assertEqual(asset["plan"]["state"], "missing")
        target = Path(asset["plan"]["files"][0]["target"])
        self.assertEqual(target, self.project / "VFX" / path)
        self.assertEqual(self.payload["assets"][0]["path"], "NS_Root.uasset")

    def test_cancelled_scan_emits_no_result_or_error(self):
        task = vfxTools._LibraryScanTask(7, [str(self.content)], str(self.project))
        task.cancel()
        self.assertIsNone(self.scan(task))
        task = vfxTools._LibraryScanTask(7, [str(self.content)], str(self.project))
        original = ue_asset_service.build_single_package_import_plan

        def cancel_mid_scan(*args):
            task.cancel()
            return original(*args)

        with mock.patch.object(ue_asset_service, "build_single_package_import_plan",
                               side_effect=cancel_mid_scan):
            self.assertIsNone(self.scan(task))

    def test_recursive_type_filter_and_uniform_tree_icons(self):
        ui = self.build_ui()
        self.assertEqual(len(ui._asset_items), 6)
        self.assertEqual(ui._library_payload["filtered_asset_count"], 1)
        self.assertNotIn("Team1/火/Mat", ui._categories)
        self.assertNotIn("Team1/火/Tex", ui._categories)
        icon = ui._effect_icon.pixmap(16, 16).toImage()
        self.assertFalse(icon.isNull())
        self.assertNotEqual(icon, QtGui.QIcon(ui._folder_icon).pixmap(16, 16).toImage())
        for item in ui._asset_items.values():
            self.assertEqual(item.childCount(), 0)
            self.assertEqual(item.icon(0).pixmap(16, 16).toImage(), icon)
        self.assertTrue(all(not item.isExpanded() for item in ui._category_items.values()))
        self.assertEqual(ui._currentCategory(), ".")
        self.assertIsNotNone(ui._assetForItem(self.card("NS_Root")))

    def test_auxiliary_folder_names_hidden_at_any_depth_with_exact_case_insensitive_match(self):
        for relative in (
            "Tex/NS_HiddenRoot.uasset", "Team2/火/mAT/NS_HiddenMat.uasset",
            "Team1/火/M_F/NS_HiddenFunction.uasset", "Team1/火/Mesh/NS_HiddenMesh.uasset",
            "Team1/多层/二级/三级/tEX/NS_HiddenDeep.uasset",
            "Team1/火/Matinee/NS_Visible.uasset", "Team1/火/MeshVariants/NS_Visible.uasset",
        ):
            self.create_asset(relative)
        self.payload = self.scan()
        ui = self.build_ui("Team1/火")
        self.assertFalse(any("NS_Hidden" in path for path in ui._asset_items))
        self.assertFalse(any(path.rsplit("/", 1)[-1].casefold() in vfxTools.VFX_HIDDEN_FOLDER_NAMES
                             for path in ui._category_items))
        for is_list in (False, True):
            ui.isList = is_list
            ui._rebuildCards()
            names = {ui.card_list.item(index).name() for index in range(ui.card_list.count())}
            self.assertEqual(names, {"NS_Fire", "P_Legacy", "Matinee", "MeshVariants"})
        ui._navigateToCategory("Team1/火/Mat")
        self.assertEqual(ui._currentCategory(), ".")

    def test_hidden_auxiliary_files_remain_in_dependency_import_and_copy(self):
        selected = self.root / "Team1/火/NS_Fire.uasset"
        function = self.create_asset("Team1/火/M_F/MF_Function.uasset")
        mesh = self.create_asset("Team1/火/Mesh/SM_Plane.uasset")
        files = [selected, function, mesh,
                 self.root / "Team1/火/Mat/M_Fire.uasset", self.root / "Team1/火/Tex/T_Fire.uasset"]
        bulk = files[-1].with_suffix(".ubulk")
        bulk.write_bytes(b"texture bulk payload")
        self.payload = self.scan()
        ui = self.build_ui("Team1/火")
        self.assertNotIn("Team1/火/M_F", ui._categories)
        self.assertNotIn("Team1/火/Mesh", ui._categories)
        with mock.patch.object(ue_asset_service, "resolve_external_asset_dependencies",
                               return_value=([str(path) for path in files], [], "")):
            plan = ue_asset_service.build_external_dependency_import_plan(
                str(selected), str(self.content), project_content_dir=str(self.project))
        self.assertEqual({Path(entry["source"]) for entry in plan["files"]}, set(files + [bulk]))
        results, errors = [], []
        worker = ue_asset_service.AssetCopyWorker(plan)
        worker.finished.connect(results.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["state"], "ready")
        for source in files + [bulk]:
            target = self.project / source.relative_to(self.content)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_folder_single_click_right_double_click_and_left_double_click(self):
        ui = self.build_ui()
        point = ui.card_list.visualItemRect(self.card("Team1")).center()
        QtTest.QTest.mouseClick(ui.card_list.viewport(), QtCore.Qt.LeftButton,
                               QtCore.Qt.NoModifier, point)
        self.assertEqual(ui._currentCategory(), ".")
        self.double_click("Team1", QtCore.Qt.RightButton)
        self.assertEqual(ui._currentCategory(), ".")
        self.double_click("Team1")
        self.double_click("多层")
        self.double_click("二级")
        self.double_click("三级")
        self.double_click("四级")
        self.assertEqual(ui._currentCategory(), "Team1/多层/二级/三级/四级")
        self.assertEqual(ui.category_list.currentItem(), ui._category_items[ui._currentCategory()])
        self.assertTrue(ui._category_items["Team1/多层/二级"].isExpanded())
        self.assertFalse(ui._category_items["Team2"].isExpanded())
        ui.parent_button.click()
        self.assertEqual(ui._currentCategory(), "Team1/多层/二级/三级")

    def test_tree_leaf_and_right_card_synchronize_with_duplicate_names(self):
        ui = self.build_ui()
        path = "Team2/火/NS_Fire.uasset"
        ui._navigateToCategory(path)
        self.assertEqual(ui._currentCategory(), "Team2/火")
        self.assertEqual(ui.card_list.currentItem().itemData()[8], str(self.root / path))
        ui._navigateToCategory("Team1/火")
        ui.search_edit.setText("Cascade")
        ui._rebuildCards()
        card = self.card("P_Legacy")
        ui.card_list.setCurrentItem(card)
        self.assertEqual(ui.category_list.currentItem(), ui._asset_items["Team1/火/P_Legacy.uASSET"])
        self.assertEqual(ui.search_edit.text(), "Cascade")
        self.assertEqual(ui.card_list.currentItem(), card)
        self.assertEqual(ui._currentCategory(), "Team1/火")
        ui.parent_button.click()
        self.assertEqual(ui._currentCategory(), "Team1")
        self.assertEqual(ui.search_edit.text(), "")

    def test_same_stem_folder_and_asset_remain_distinct(self):
        ui = self.build_ui("Team1/火")
        self.assertIn("Team1/火/NS_Fire", ui._category_items)
        ui._navigateToCategory("Team1/火/NS_Fire.uasset")
        self.assertEqual(ui.card_list.currentItem().itemData()[8], str(self.root / "Team1/火/NS_Fire.uasset"))
        folder = ui._itemForSource(str(self.root / "Team1/火/NS_Fire"))
        ui._enterFolder(folder)
        self.assertEqual(ui._currentCategory(), "Team1/火/NS_Fire")
        self.assertIsNotNone(self.card("NS_Child"))

    def test_folder_cards_have_folder_icon_no_status_and_cannot_load_or_drag(self):
        ui = self.build_ui()
        folder = self.card("Team1")
        self.assertEqual(folder.itemData()[7], ui._folder_icon)
        self.assertTrue(ui._folder_icon.endswith("/icon/floder.png"))
        self.assertEqual(folder.ueState(), "folder")
        self.assertFalse(folder.dragEnabled())
        self.assertEqual(folder.ueMainObjectPath(), "")
        ui.card_list.setCurrentItem(folder)
        self.assertFalse(ui.load_button.isEnabled())
        with mock.patch.object(ue_asset_service, "build_external_dependency_import_plan") as plan:
            ui.loadVfx(folder)
            plan.assert_not_called()
        painter = mock.Mock()
        folder.paintUEStatus(painter, None)
        self.assertEqual(painter.mock_calls, [])
        self.assertEqual([asset["name"] for asset in ui.queued_assets], ["NS_Root"])

    def test_asset_thumbnails_and_ready_drag_state_survive_navigation(self):
        path = "Team1/火/NS_Fire.uasset"
        asset = self.assets[path]
        thumbnail = Path(asset["thumbnail"])
        thumbnail.parent.mkdir(parents=True)
        shutil.copyfile(Path(vfxTools.VfxToolsUI.scriptsPath) / "icon/Default.png", thumbnail)
        for entry in asset["plan"]["files"]:
            Path(entry["target"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["source"], entry["target"])
        asset["plan"]["state"] = "ready"
        ui = self.build_ui(path)
        item = ui.card_list.currentItem()
        self.assertEqual(item.itemData()[7], str(thumbnail))
        self.assertTrue(item.dragEnabled())
        self.assertEqual(item.ueState(), "ready")
        self.assertEqual(item.ueMainObjectPath(), asset["object_path"])
        self.assertTrue(ui.load_button.isEnabled())
        with mock.patch.object(ue_asset_service, "build_external_dependency_import_plan",
                               return_value=copy.deepcopy(asset["plan"])) as plan, \
                mock.patch.object(ui, "_registerPlan") as register:
            ui.load_button.click()
            plan.assert_called_once_with(asset["source_file"], str(self.content))
            self.assertEqual(register.call_args.args[0]["source_file"], asset["source_file"])
        ui._navigateToCategory("Team2/火")
        self.assertEqual(self.card("NS_Fire").ueState(), "missing")
        ui._navigateToCategory(path)
        self.assertEqual(ui.card_list.currentItem().ueState(), "ready")

    def test_list_mode_folder_entry_and_refresh_restore_leaf_path(self):
        path = "Team1/火/P_Legacy.uASSET"
        ui = self.build_ui(path)
        ui.toggleDisplayMode()
        self.assertTrue(ui.isList)
        self.assertEqual(ui.card_list.currentItem().name(), "P_Legacy")
        self.finish_scan()
        self.assertEqual(ui.category_list.currentItem(), ui._asset_items[path])
        ui.parent_button.click()
        ui.search_edit.setText("火")
        ui._rebuildCards()
        ui.card_list.setCurrentItem(self.card("火"))
        QtTest.QTest.keyClick(ui.card_list, QtCore.Qt.Key_Return)
        self.assertEqual(ui._currentCategory(), "Team1")
        self.double_click("火")
        self.assertEqual(ui._currentCategory(), "Team1/火")
        self.assertEqual(ui.search_edit.text(), "")

    def test_stale_results_and_failures_release_navigation(self):
        ui = self.build_ui("Team1/火")
        ui._scanFinished(ui._scan_generation - 1, {})
        ui._scanFailed(ui._scan_generation - 1, "stale")
        self.assertEqual(ui._currentCategory(), "Team1/火")
        ui._scanFailed(ui._scan_generation, "failed")
        self.assertEqual(ui.card_list.count(), 0)
        self.assertEqual(ui._assets_by_source, {})
        self.assertFalse(ui.parent_button.isEnabled())
        self.assertFalse(ui.load_button.isEnabled())
        ui._preferred_category = "Removed/Folder"
        self.finish_scan()
        self.assertEqual(ui._currentCategory(), ".")

    def test_type_bridge_failure_clears_previous_results(self):
        ui = self.build_ui("Team1/火")
        with mock.patch.object(ue_asset_service, "get_external_asset_class_names",
                               return_value=([], "bridge unavailable")):
            ui._scanFinished(ui._scan_generation, copy.deepcopy(self.payload))
        self.assertEqual(ui.category_list.topLevelItemCount(), 0)
        self.assertEqual(ui.message_label.text(), "bridge unavailable")
        self.assertFalse(ui.load_button.isEnabled())

    def test_refresh_setup_failure_releases_cancelled_scan(self):
        ui = self.build_ui("Team1/火")
        task = mock.Mock()
        ui._scan_task = task
        with mock.patch.object(ue_asset_service, "project_content_dir",
                               side_effect=RuntimeError("no project")):
            vfxTools.VfxToolsUI.refreshLibrary(ui)
        task.cancel.assert_called_once()
        self.assertIsNone(ui._scan_task)
        self.assertTrue(ui.category_list.isEnabled())
        self.assertTrue(ui.parent_button.isEnabled())
        self.assertFalse(ui.load_button.isEnabled())

    def test_rescan_during_process_events_skips_outdated_type_query(self):
        ui = self.build_ui()

        def rescan():
            ui._scan_generation += 1

        with mock.patch.object(QtWidgets.QApplication, "processEvents", side_effect=rescan), \
                mock.patch.object(ue_asset_service, "get_external_asset_class_names") as query:
            ui._scanFinished(ui._scan_generation, copy.deepcopy(self.payload))
        query.assert_not_called()

    def test_thumbnail_updates_only_affect_matching_asset_cards(self):
        ui = self.build_ui("Team1/火")
        path = "Team1/火/NS_Fire.uasset"
        thumbnail = Path(self.assets[path]["thumbnail"])
        thumbnail.parent.mkdir(parents=True)
        shutil.copyfile(Path(ui._fallback_icon), thumbnail)
        ui._updateCardThumbnail(str(self.root / path), str(thumbnail))
        item = ui._itemForSource(str(self.root / path))
        folder = ui._itemForSource(str(self.root / "Team1/火/NS_Fire"))
        self.assertEqual(item.itemData()[7], str(thumbnail))
        self.assertEqual(folder.itemData()[7], ui._folder_icon)
        self.assertEqual(folder.ueState(), "folder")

    def test_copy_completion_and_preloaded_effect_both_schedule_browser_sync(self):
        path = "Team1/火/NS_Fire.uasset"
        ui = self.build_ui(path)
        asset = ui._assetForItem(ui.card_list.currentItem())
        for entry in asset["plan"]["files"]:
            Path(entry["target"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["source"], entry["target"])
        for copied in (False, True):
            registered = copy.deepcopy(asset["plan"])
            registered["state"] = "ready"
            registered["main_object_path"] = asset["object_path"]
            input_plan = copy.deepcopy(registered)
            with mock.patch.object(ue_asset_service, "refresh_asset_registry", return_value=registered), \
                    mock.patch.object(ue_asset_service, "sync_to_content_browser", return_value=True) as sync, \
                    mock.patch.object(QtCore.QTimer, "singleShot") as timer:
                if copied:
                    ui._copy_source = asset["source_file"]
                    ui._copyFinished(input_plan)
                else:
                    with mock.patch.object(ue_asset_service, "build_external_dependency_import_plan",
                                           return_value=input_plan):
                        ui.loadVfx()
                sync.assert_not_called()
                self.assertIn("正在内容浏览器中定位", ui.message_label.text())
                timer.call_args.args[1]()
                sync.assert_called_once_with(asset["object_path"])
                self.assertIn("已在内容浏览器中定位", ui.message_label.text())

    def test_delayed_browser_sync_retries_then_stops_without_false_success(self):
        ui = self.build_ui("NS_Root.uasset")
        asset = ui._assetForItem(ui.card_list.currentItem())
        asset["plan"]["state"] = "ready"
        key = os.path.normcase(asset["source_file"])
        with mock.patch.object(ue_asset_service, "sync_to_content_browser", side_effect=[False, True]) as sync, \
                mock.patch.object(QtCore.QTimer, "singleShot") as timer:
            ui._syncVfxBrowser(key, ui._browser_sync_generation)
            self.assertNotIn("已在内容浏览器中定位", ui.message_label.text())
            timer.call_args.args[1]()
            self.assertEqual(sync.call_count, 2)
            self.assertIn("已在内容浏览器中定位", ui.message_label.text())
        with mock.patch.object(ue_asset_service, "sync_to_content_browser", return_value=False), \
                mock.patch.object(QtCore.QTimer, "singleShot") as timer:
            ui._syncVfxBrowser(key, ui._browser_sync_generation, attempt=19)
            timer.assert_not_called()
            self.assertIn("定位失败", ui.message_label.text())

    def test_manual_location_and_shutdown_cancel_outdated_browser_callbacks(self):
        ui = self.build_ui("NS_Root.uasset")
        asset = ui._assetForItem(ui.card_list.currentItem())
        asset["plan"]["state"] = "ready"
        ui._applyAssetState(asset)
        with mock.patch.object(QtCore.QTimer, "singleShot") as timer, \
                mock.patch.object(ue_asset_service, "sync_to_content_browser", return_value=True) as sync:
            ui.locateVfx()
            first_callback = timer.call_args.args[1]
            ui.locateVfx()
            second_callback = timer.call_args.args[1]
            first_callback()
            sync.assert_not_called()
            ui.shutdownThreads()
            second_callback()
            sync.assert_not_called()

    def test_vfx_and_blueprint_menus_disable_unloaded_and_busy_actions(self):
        ui = self.build_ui("NS_Root.uasset")
        item = ui.card_list.currentItem()
        point = ui.card_list.visualItemRect(item).center()
        menus = []

        def capture(menu, *args):
            menus.append({action.text(): action.isEnabled() for action in menu.actions() if action.text()})

        for show_menu, load_label in (
                (ui._showContextMenu, "加载特效"),
                (lambda point: blueprintTools.BlueprintToolsUI._showContextMenu(ui, point), "加载蓝图")):
            for state, busy in (("missing", False), ("ready", False), ("ready", True)):
                item.setUEState(state)
                item.setUEMainObjectPath("/Game/VFX/NS_Root.NS_Root" if state == "ready" else "")
                with mock.patch.object(QtWidgets.QMenu, "exec_", capture), \
                        mock.patch.object(ui, "_operationIsRunning", return_value=busy):
                    show_menu(point)
                self.assertEqual(menus[-1][load_label], not busy)
                self.assertEqual(menus[-1]["在内容浏览器中定位"], state == "ready" and not busy)
                self.assertEqual(menus[-1]["打开资源"], state == "ready" and not busy)

    def test_open_vfx_and_blueprint_show_editor_failures_and_success(self):
        ui = self.build_ui("NS_Root.uasset")
        item = ui.card_list.currentItem()
        item.setUEState("ready")
        item.setUEMainObjectPath("/Game/VFX/NS_Root.NS_Root")
        for open_editor in (ui.openVfx, lambda: blueprintTools.BlueprintToolsUI.openBlueprint(ui)):
            with mock.patch.object(ue_asset_service, "open_asset_editor", return_value=(False, "editor failed")), \
                    mock.patch.object(QtWidgets.QMessageBox, "warning") as warning:
                open_editor()
                warning.assert_called_once()
                self.assertEqual(ui.message_label.text(), "editor failed")
            with mock.patch.object(ue_asset_service, "open_asset_editor", return_value=(True, "")) as open_asset, \
                    mock.patch.object(QtWidgets.QMessageBox, "warning") as warning:
                open_editor()
                warning.assert_not_called()
                open_asset.assert_called_once_with(item.ueMainObjectPath())
                self.assertIn("已在 UE 中打开", ui.message_label.text())


if __name__ == "__main__":
    unittest.main()
