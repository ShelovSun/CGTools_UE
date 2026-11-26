"""Grouped blueprint projects preserve their original /Game package paths."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_library_conflicts import OfflineBlueprintToolsUI
from AssetsManagerForUE.sources import blueprintTools, ue_asset_service
from AssetsManagerForUE.utils import myWidget
from PySide6 import QtCore, QtTest, QtWidgets


class BlueprintGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blueprint_groups_")
        self.root = Path(self.temp.name) / "BlueprintFun"
        self.target = Path(self.temp.name) / "Project/Content"
        self.root.mkdir()
        self.target.mkdir(parents=True)
        self.ui = None

    def tearDown(self):
        if self.ui:
            self.ui.shutdownThreads()
            self.ui.close()
            self.ui.deleteLater()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.temp.cleanup()

    def project(self, group="TA", category="阵列资源"):
        project = self.root / group if group else self.root
        content = project / "Content"
        folder = content / "Assets/Blueprints" / category
        folder.mkdir(parents=True)
        (folder / "SpeedCurve.uasset").write_bytes(b"curve package")
        (folder / "SpeedCurve.uexp").write_bytes(b"curve sidecar")
        (folder / "Dependencies").mkdir()
        (folder / "Dependencies/M_Material.uasset").write_bytes(b"dependency")
        (project / "GOF_library.uproject").write_text("{}", encoding="utf-8")
        return content, folder

    def scan(self):
        task = blueprintTools._LibraryScanTask(9, [str(self.root)], str(self.target))
        result, errors = [], []
        task.signals.loaded.connect(lambda generation, payload: result.append(payload))
        task.signals.failed.connect(lambda generation, error: errors.append(error))
        task.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        return result[0]

    def build_ui(self, payload, preferred=""):
        self.ui = OfflineBlueprintToolsUI()
        self.ui._preferred_category = preferred
        self.ui._scanFinished(self.ui._scan_generation, payload)
        self.ui.resize(1050, 620)
        self.ui.show()
        self.app.processEvents()
        return self.ui

    def test_grouped_scan_preserves_package_and_complete_category_plan(self):
        content, folder = self.project()
        payload = self.scan()
        category = payload["categories"][0]
        self.assertEqual([group["name"] for group in payload["groups"]], ["TA"])
        self.assertEqual(category["path"], "TA/阵列资源")
        self.assertEqual(category["content_root"], str(content))
        self.assertEqual([asset["name"] for asset in category["assets"]], ["SpeedCurve"])
        self.assertEqual(category["assets"][0]["object_path"],
                         "/Game/Assets/Blueprints/阵列资源/SpeedCurve.SpeedCurve")
        self.assertEqual({entry["relative"] for entry in category["plan"]["files"]}, {
            "Assets/Blueprints/阵列资源/SpeedCurve.uasset",
            "Assets/Blueprints/阵列资源/SpeedCurve.uexp",
            "Assets/Blueprints/阵列资源/Dependencies/M_Material.uasset",
        })

    def test_legacy_project_move_keeps_identity_and_relative_targets(self):
        self.project(group="")
        before = self.scan()["categories"][0]
        group = self.root / "TA"
        group.mkdir()
        for child in list(self.root.iterdir()):
            if child != group:
                child.rename(group / child.name)
        after = self.scan()["categories"][0]
        self.assertEqual(before["path"], after["path"])
        self.assertEqual(before["assets"][0]["object_path"], after["assets"][0]["object_path"])
        self.assertEqual([entry["target"] for entry in before["plan"]["files"]],
                         [entry["target"] for entry in after["plan"]["files"]])
        self.assertIn(os.path.join("TA", "Content"), after["content_root"])

    def test_multiple_groups_use_full_identity_for_same_category_names(self):
        self.project("TA")
        self.project("Team2")
        (self.root / "Unrelated/Content").mkdir(parents=True)
        payload = self.scan()
        self.assertEqual({value["path"] for value in payload["categories"]},
                         {"TA/阵列资源", "Team2/阵列资源"})
        ui = self.build_ui(payload)
        self.assertEqual(set(ui._categories), {"TA/阵列资源", "Team2/阵列资源"})

    def test_native_tree_folder_cards_navigation_without_rescanning(self):
        self.project()
        ui = self.build_ui(self.scan())
        root = ui.category_list.topLevelItem(0)
        self.assertEqual(root.text(0), "蓝图库")
        self.assertEqual(root.child(0).text(0), "TA")
        self.assertEqual(root.child(0).child(0).text(0), "阵列资源")
        self.assertEqual(ui.card_list.item(0).ueState(), "folder")
        ui.card_list.setCurrentRow(0)
        self.assertFalse(ui.load_button.isEnabled())
        with mock.patch.object(blueprintTools, "_LibraryScanTask", side_effect=AssertionError("extra scan")), \
                mock.patch.object(ue_asset_service, "build_folder_import_plan", side_effect=AssertionError("extra plan")):
            ui._enterFolder(ui.card_list.item(0))
            self.assertEqual(ui._currentCategory(), "TA")
            ui._enterFolder(ui.card_list.item(0))
            self.assertEqual(ui._currentCategory(), "TA/阵列资源")
            self.assertEqual(ui.card_list.item(0).name(), "SpeedCurve")
            for _ in range(8):
                root.child(0).setExpanded(False)
                root.child(0).setExpanded(True)
            self.app.processEvents()
            self.assertEqual(ui._currentCategory(), "TA/阵列资源")
        self.assertTrue(hasattr(ui.category_list, "_cgtools_collapsed_accessibility"))
        self.assertFalse(ui.category_list.isAnimated())

    def test_previous_flat_selection_migrates_and_stale_results_are_ignored(self):
        self.project()
        payload = self.scan()
        ui = self.build_ui(payload, "阵列资源")
        self.assertEqual(ui._currentCategory(), "TA/阵列资源")
        self.assertTrue(ui.category_list.topLevelItem(0).child(0).isExpanded())
        ui._scanFinished(ui._scan_generation - 1, {"categories": [], "groups": []})
        self.assertEqual(ui._currentCategory(), "TA/阵列资源")
        self.assertEqual(ui.card_list.count(), 1)

    def test_grouped_plan_copies_to_original_game_folder(self):
        self.project()
        category = self.scan()["categories"][0]
        done, errors = [], []
        worker = ue_asset_service.AssetCopyWorker(category["plan"])
        worker.finished.connect(done.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(done), 1)
        self.assertEqual((self.target / "Assets/Blueprints/阵列资源/SpeedCurve.uasset").read_bytes(), b"curve package")
        self.assertTrue((self.target / "Assets/Blueprints/阵列资源/Dependencies/M_Material.uasset").is_file())
        self.assertFalse((self.target / "TA").exists())

    def test_cancelled_scan_emits_no_result(self):
        self.project()
        task = blueprintTools._LibraryScanTask(1, [str(self.root)], str(self.target))
        task.cancel()
        result = []
        task.signals.loaded.connect(lambda *args: result.append(args))
        task.signals.failed.connect(lambda *args: result.append(args))
        task.run()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
