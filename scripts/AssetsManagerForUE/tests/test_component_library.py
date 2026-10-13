"""Run with: python -B -m unittest discover -s <this tests directory> -v."""

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
from AssetsManagerForUE.sources import component_service, componentTools
from AssetsManagerForUE.utils import myWidget


class OfflineComponentToolsUI(componentTools.ComponentToolsUI):
    def refreshLibrary(self):
        pass

    def _readSettings(self):
        return 120, None, False

    def _rememberSettings(self):
        pass

    def infoMsg(self, icon, text):
        self.message_label.setText(text)


class ComponentLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="component_library_tree_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "CppComponent"
        self.plugins = Path(self.temporary.name) / "Project" / "Plugins"
        self.root.mkdir()
        self.create_plugin("Team3/其他/ExamplePlugin")
        self.create_plugin("Team3/攻击/阶段一/AttackPlugin", "AttackPlugin.uPLUGIN")
        self.create_plugin("Team4/其他/OtherPlugin")
        self.create_plugin("Team3/DirectPlugin")
        self.create_plugin("RootPlugin")
        (self.root / "Team3/空文件夹").mkdir()
        (self.root / "Team3/DescriptorDirectory/Fake.uplugin").mkdir(parents=True)
        hidden = self.root / "Team3/DirectPlugin/Content/Internal"
        hidden.mkdir(parents=True)
        (hidden / "Internal.uplugin").write_text("{}", encoding="utf-8")
        self.payload = component_service.scan_component_library(
            [str(self.root)], str(self.plugins))
        self.categories = {}
        self.components = {}

        def collect(category):
            self.categories[category["path"]] = category
            for child in category["categories"]:
                collect(child)
            for component in category["components"]:
                self.components[component["path"]] = component

        for category in self.payload["categories"]:
            collect(category)
        for component in self.payload["components"]:
            self.components[component["path"]] = component
        self.ui = None

    def tearDown(self):
        if self.ui is not None:
            self.ui.shutdownThreads()
            self.ui.close()
            self.ui.deleteLater()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def create_plugin(self, relative, descriptor=None):
        folder = self.root / relative
        folder.mkdir(parents=True)
        (folder / (descriptor or (folder.name + ".uplugin"))).write_text(
            '{"FileVersion": 3}', encoding="utf-8")
        (folder / "README.md").write_text("# Usage", encoding="utf-8")
        binaries = folder / "Binaries/Win64"
        binaries.mkdir(parents=True)
        (binaries / "Example.dll").write_bytes(b"plugin-payload")
        cache = folder / "Intermediate"
        cache.mkdir()
        (cache / "Example.obj").write_bytes(b"build-cache")
        if folder.name == "ExamplePlugin":
            shutil.copyfile(
                Path(componentTools.ComponentToolsUI.scriptsPath) / "icon/Default.png",
                folder / "ExamplePlugin.png")
        return folder

    def build_ui(self, preferred=""):
        self.ui = OfflineComponentToolsUI()
        self.ui._preferred_category = preferred
        self.ui.resize(1100, 600)
        self.ui._scanFinished(self.ui._scan_generation, self.payload)
        self.ui.show()
        self.app.processEvents()
        return self.ui

    def card(self, name):
        for index in range(self.ui.card_list.count()):
            item = self.ui.card_list.item(index)
            if item.name() == name:
                return item
        self.fail("Card not found: " + name)

    def click_card(self, name):
        item = self.card(name)
        point = self.ui.card_list.visualItemRect(item).center()
        QtTest.QTest.mouseClick(self.ui.card_list.viewport(), QtCore.Qt.LeftButton,
                               QtCore.Qt.NoModifier, point)
        self.app.processEvents()

    def double_click_card(self, name, button=QtCore.Qt.LeftButton):
        item = self.card(name)
        point = self.ui.card_list.visualItemRect(item).center()
        QtTest.QTest.mouseClick(self.ui.card_list.viewport(), button,
                               QtCore.Qt.NoModifier, point)
        QtTest.QTest.mouseDClick(self.ui.card_list.viewport(), button,
                                QtCore.Qt.NoModifier, point)
        self.app.processEvents()

    def test_scan_classifies_only_direct_descriptor_files(self):
        self.assertEqual(set(self.components), {
            "Team3/其他/ExamplePlugin", "Team3/攻击/阶段一/AttackPlugin",
            "Team4/其他/OtherPlugin", "Team3/DirectPlugin", "RootPlugin",
        })
        self.assertIn("Team3/DescriptorDirectory/Fake.uplugin", self.categories)
        self.assertNotIn("Team3/DirectPlugin/Content", self.categories)
        self.assertEqual(self.categories["Team3/空文件夹"]["components"], [])
        self.assertTrue(all("plan" not in category for category in self.categories.values()))

    def test_nested_plugin_install_keeps_original_payload_and_target(self):
        component = self.components["Team3/其他/ExamplePlugin"]
        plan = component["plan"]
        self.assertEqual(plan["target_folder"], str(self.plugins / "ExamplePlugin"))
        self.assertEqual(plan["category"], "Team3/其他")
        self.assertTrue(component["icon"].endswith("ExamplePlugin.png"))
        self.assertFalse(any("Intermediate" in row["relative"] for row in plan["files"]))
        result, errors = [], []
        worker = component_service.ComponentCopyWorker(plan)
        worker.finished.connect(result.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(result[0]["state"], "ready")
        self.assertEqual((self.plugins / "ExamplePlugin/Binaries/Win64/Example.dll").read_bytes(),
                         b"plugin-payload")
        self.assertFalse((self.plugins / "Team3").exists())

    def test_scan_supports_additional_depth(self):
        relative = "Team3/动画样条线/一级/二级/三级/四级/SplinePlugin"
        self.create_plugin(relative)
        payload = component_service.scan_component_library([str(self.root)], str(self.plugins))
        category = next(value for value in payload["categories"] if value["name"] == "Team3")
        for name in ["动画样条线", "一级", "二级", "三级", "四级"]:
            category = next(value for value in category["categories"] if value["name"] == name)
        self.assertEqual(category["components"][0]["path"], relative)

    def test_ambiguous_descriptors_remain_components_with_error(self):
        folder = self.create_plugin("Team3/Ambiguous", "One.uplugin")
        (folder / "Two.uplugin").write_text("{}", encoding="utf-8")
        payload = component_service.scan_component_library([str(self.root)], str(self.plugins))
        team = next(value for value in payload["categories"] if value["name"] == "Team3")
        component = next(value for value in team["components"] if value["name"] == "Ambiguous")
        self.assertEqual(component["plan"]["state"], "error")
        self.assertFalse(any(value["name"] == "Ambiguous" for value in team["categories"]))

    def test_scan_cancellation(self):
        calls = []

        def cancelled():
            calls.append(True)
            return len(calls) >= 5

        with self.assertRaisesRegex(RuntimeError, "操作已取消"):
            component_service.scan_component_library([str(self.root)], str(self.plugins),
                                                     cancelled=cancelled)

    def test_initial_tree_collapsed_and_folder_cards_neutral(self):
        ui = self.build_ui()
        self.assertEqual(ui._currentCategory(), ".")
        self.assertTrue(all(not item.isExpanded() for item in ui._category_items.values()))
        folder = self.card("Team3")
        self.assertEqual(folder.itemData()[7], ui._folder_icon)
        self.assertTrue(ui._folder_icon.endswith("/icon/floder.png"))
        self.assertFalse(QtGui.QImage(ui._folder_icon).isNull())
        self.assertEqual(folder.ueState(), "folder")
        ui.card_list.setCurrentItem(folder)
        self.assertFalse(ui.load_button.isEnabled())
        self.assertFalse(ui.parent_button.isEnabled())
        painter = mock.Mock()
        folder.paintUEStatus(painter, None)
        self.assertEqual(painter.mock_calls, [])

    def test_only_left_double_click_enters_folder_and_updates_tree(self):
        ui = self.build_ui()
        self.click_card("Team3")
        self.assertEqual(ui._currentCategory(), ".")
        self.double_click_card("Team3", QtCore.Qt.RightButton)
        self.assertEqual(ui._currentCategory(), ".")
        self.double_click_card("Team3")
        self.assertEqual(ui._currentCategory(), "Team3")
        self.double_click_card("攻击")
        self.double_click_card("阶段一")
        self.assertEqual(ui._currentCategory(), "Team3/攻击/阶段一")
        self.assertEqual(ui.category_list.currentItem().text(0), "阶段一")
        self.assertTrue(ui._category_items["Team3"].isExpanded())
        self.assertTrue(ui._category_items["Team3/攻击"].isExpanded())
        self.assertFalse(ui._category_items["Team4"].isExpanded())
        self.assertTrue(ui.parent_button.isEnabled())
        ui.parent_button.click()
        self.assertEqual(ui._currentCategory(), "Team3/攻击")

    def test_duplicate_names_and_tree_selection_show_correct_components(self):
        ui = self.build_ui()
        ui.category_list.setCurrentItem(ui._category_items["Team3/其他"])
        self.assertEqual(self.card("ExamplePlugin").ueState(), "missing")
        ui.category_list.setCurrentItem(ui._category_items["Team4/其他"])
        self.assertEqual(ui.card_list.count(), 1)
        self.assertIsNotNone(ui._componentForItem(self.card("OtherPlugin")))

    def test_component_selection_loads_and_folder_does_not(self):
        ui = self.build_ui("Team3")
        plugin = self.card("DirectPlugin")
        ui.card_list.setCurrentItem(plugin)
        self.assertTrue(ui.load_button.isEnabled())
        with mock.patch.object(ui, "_startCopy") as start_copy:
            ui.load_button.click()
            self.assertEqual(start_copy.call_args.args[0]["name"], "DirectPlugin")
        ui._enterFolder(plugin)
        self.assertEqual(ui._currentCategory(), "Team3")
        ui.card_list.setCurrentItem(self.card("其他"))
        self.assertFalse(ui.load_button.isEnabled())

    def test_preferred_path_refresh_and_missing_path_fallback(self):
        ui = self.build_ui("Team3/攻击/阶段一")
        self.assertEqual(ui._currentCategory(), "Team3/攻击/阶段一")
        ui._scanFinished(ui._scan_generation, self.payload)
        self.assertEqual(ui._currentCategory(), "Team3/攻击/阶段一")
        ui._preferred_category = "Removed/Folder"
        ui._scanFinished(ui._scan_generation, self.payload)
        self.assertEqual(ui._currentCategory(), ".")

    def test_list_mode_double_click_folder_entry_and_search_reset(self):
        ui = self.build_ui("Team3")
        ui.toggleDisplayMode()
        self.assertTrue(ui.isList)
        ui.search_edit.setText("其他")
        ui._rebuildCards()
        self.assertEqual(ui.card_list.count(), 1)
        ui.card_list.setCurrentItem(self.card("其他"))
        QtTest.QTest.keyClick(ui.card_list, QtCore.Qt.Key_Return)
        self.assertEqual(ui._currentCategory(), "Team3")
        self.double_click_card("其他")
        self.assertEqual(ui._currentCategory(), "Team3/其他")
        self.assertEqual(ui.search_edit.text(), "")
        plugin = self.card("ExamplePlugin")
        ui.card_list.setCurrentItem(plugin)
        ui.openUsageInstructions()
        self.assertTrue(ui.documentation_panel.isVisible())
        self.assertIn("Usage", ui.documentation_browser.toPlainText())

    def test_stale_scan_result_ignored_and_failure_clears_navigation(self):
        ui = self.build_ui("Team3")
        ui._scanFinished(ui._scan_generation - 1, {})
        self.assertEqual(ui._currentCategory(), "Team3")
        ui._scanFailed(ui._scan_generation, "Test scan failure")
        self.assertEqual(ui.card_list.count(), 0)
        self.assertEqual(ui._categories, {})
        self.assertFalse(ui.parent_button.isEnabled())
        self.assertFalse(ui.load_button.isEnabled())

    def test_refresh_setup_failure_releases_cancelled_scan(self):
        ui = self.build_ui("Team3")
        task = mock.Mock()
        ui._scan_task = task
        with mock.patch.object(component_service, "project_plugins_directory",
                               side_effect=RuntimeError("Test project failure")):
            componentTools.ComponentToolsUI.refreshLibrary(ui)
        task.cancel.assert_called_once()
        self.assertIsNone(ui._scan_task)
        self.assertTrue(ui.category_list.isEnabled())
        self.assertTrue(ui.parent_button.isEnabled())
        self.assertFalse(ui.load_button.isEnabled())

    def test_tree_uses_one_component_icon_and_cards_keep_custom_thumbnails(self):
        ui = self.build_ui()
        self.assertEqual(set(ui._component_items), set(self.components))
        expected_icon = QtGui.QIcon(ui._fallback_icon).pixmap(16, 16).toImage()
        self.assertFalse(expected_icon.isNull())
        for item in ui._component_items.values():
            self.assertEqual(item.childCount(), 0)
            self.assertEqual(item.icon(0).pixmap(16, 16).toImage(), expected_icon)
        self.assertFalse(QtGui.QImage(ui._fallback_icon).isNull())
        self.assertNotEqual(ui._fallback_icon, ui._folder_icon)
        self.assertEqual(ui._category_items["Team3"].icon(0).pixmap(16, 16).toImage(),
                         QtGui.QIcon(ui._folder_icon).pixmap(16, 16).toImage())
        ui._navigateToCategory("Team3/其他")
        self.assertEqual(self.card("ExamplePlugin").itemData()[7],
                         self.components["Team3/其他/ExamplePlugin"]["icon"])
        ui._navigateToCategory("Team3")
        self.assertEqual(self.card("DirectPlugin").itemData()[7], ui._fallback_icon)

    def test_tree_component_selection_shows_parent_and_selects_card(self):
        ui = self.build_ui()
        path = "Team3/其他/ExamplePlugin"
        ui._navigateToCategory(path)
        self.assertEqual(ui.category_list.currentItem(), ui._component_items[path])
        self.assertEqual(ui._currentCategory(), "Team3/其他")
        self.assertEqual(ui.card_list.currentItem().name(), "ExamplePlugin")
        self.assertTrue(ui.load_button.isEnabled())
        self.assertTrue(ui._category_items["Team3/其他"].isExpanded())
        self.assertFalse(ui._category_items["Team4"].isExpanded())

    def test_right_component_selection_syncs_tree_without_clearing_search(self):
        ui = self.build_ui("Team3")
        ui.search_edit.setText("Direct")
        ui._rebuildCards()
        item = self.card("DirectPlugin")
        self.click_card("DirectPlugin")
        self.assertEqual(ui.category_list.currentItem(),
                         ui._component_items["Team3/DirectPlugin"])
        self.assertEqual(ui.card_list.currentItem(), item)
        self.assertEqual(ui.search_edit.text(), "Direct")
        self.assertEqual(ui._currentCategory(), "Team3")
        self.double_click_card("DirectPlugin")
        self.assertEqual(ui._currentCategory(), "Team3")

    def test_parent_navigation_uses_displayed_folder_when_component_selected(self):
        ui = self.build_ui("Team3/攻击/阶段一/AttackPlugin")
        self.assertEqual(ui._currentCategory(), "Team3/攻击/阶段一")
        ui.parent_button.click()
        self.assertEqual(ui._currentCategory(), "Team3/攻击")
        ui._navigateToCategory("RootPlugin")
        self.assertEqual(ui.card_list.currentItem().name(), "RootPlugin")
        self.assertFalse(ui.parent_button.isEnabled())

    def test_component_leaf_selection_restored_after_refresh(self):
        path = "Team3/其他/ExamplePlugin"
        ui = self.build_ui(path)
        ui._scanFinished(ui._scan_generation, self.payload)
        self.assertEqual(ui.category_list.currentItem(), ui._component_items[path])
        self.assertEqual(ui.card_list.currentItem().name(), "ExamplePlugin")
        self.assertEqual(ui._currentCategory(), "Team3/其他")


if __name__ == "__main__":
    unittest.main()
