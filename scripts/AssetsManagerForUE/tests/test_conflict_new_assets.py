"""New server files have red icons and real load-selection checkboxes."""

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
try:
    import unreal
except ImportError:
    sys.modules["unreal"] = types.ModuleType("unreal")

from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.sources import sceneTools, ue_asset_service


class NewFilesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        for path in ("Mat/M_Shared.uasset", "Mat/M_New.uasset", "Mat/M_New.uexp", "Maps/New.umap"):
            source = self.root / "Library/Content" / path
            target = self.root / "Project/Content" / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"server release")
            if path == "Mat/M_Shared.uasset":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"local release")
            self.entries.append({"relative": path, "source": str(source), "target": str(target),
                                 "extension": source.suffix, "size": source.stat().st_size})
        self.plan = {"files": self.entries, "source_content_root": str(self.root / "Library/Content"),
                     "different_files": ["Mat/M_Shared.uasset"],
                     "missing_files": ["Mat/M_New.uasset", "Mat/M_New.uexp", "Maps/New.umap"]}
        self.external = self.enterContext(mock.patch.object(
            ue_asset_service, "get_external_asset_class_names", return_value=(["Material", "Material"], "")))
        self.local = self.enterContext(mock.patch.object(
            ue_asset_service, "project_asset_class_name", return_value=""))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def run_dialog(self, callback, plugin=False, plan=None):
        def execute(dialog):
            self.dialogs.append(dialog)
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            rows = {tree.topLevelItem(i).data(0, QtCore.Qt.UserRole): tree.topLevelItem(i)
                    for i in range(tree.topLevelItemCount())}
            buttons = {button.text(): button for button in dialog.findChildren(QtWidgets.QPushButton)}
            callback(dialog, tree, rows, buttons)
            return dialog.result()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", execute):
            return sceneTools.choose_ue_conflict_files(None, self.plan if plan is None else plan, plugin)

    def test_new_packages_sidecars_and_maps_have_red_icons_and_missing_marker(self):
        def verify(dialog, tree, rows, buttons):
            self.assertEqual(tree.topLevelItemCount(), 4)
            self.assertEqual(tree.topLevelItem(0).data(0, QtCore.Qt.UserRole + 1), "new")
            for path in self.plan["missing_files"]:
                row = rows[path]
                self.assertEqual(row.text(0), "")
                self.assertEqual(row.text(5), "缺失")
                self.assertTrue(row.flags() & QtCore.Qt.ItemIsUserCheckable)
                self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
                self.assertTrue(row.flags() & QtCore.Qt.ItemIsEnabled)
                color = row.icon(1).pixmap(16, 16).toImage().pixelColor(6, 11)
                self.assertGreater(color.red(), color.green() * 2)
                self.assertGreater(color.red(), color.blue() * 2)
                self.assertIn("勾选后加载", row.toolTip(0))
                self.assertIn("服务器：", row.toolTip(2))
            old = rows["Mat/M_Shared.uasset"]
            self.assertEqual(old.text(0), "")
            self.assertTrue(old.flags() & QtCore.Qt.ItemIsUserCheckable)
            color = old.icon(1).pixmap(16, 16).toImage().pixelColor(6, 11)
            self.assertGreater(color.blue(), color.red() * 2)
            hint = dialog.findChild(QtWidgets.QLabel, "UEConflictHint").text()
            summary = dialog.findChild(QtWidgets.QLabel, "UEConflictSelectionSummary").text()
            self.assertIn("3 个", hint)
            self.assertIn("红色图标", hint)
            self.assertIn("新增 0", summary)
            self.assertIn("已选择 0 / 4", summary)
            self.assertIn("覆盖 0，保留 1", summary)
            buttons["取消"].click()
        self.assertFalse(self.run_dialog(verify))

    def test_new_file_types_come_from_server_and_sidecars_inherit_primary_class(self):
        def verify(dialog, tree, rows, buttons):
            self.assertEqual(rows["Mat/M_New.uasset"].text(3), "材质")
            self.assertEqual(rows["Mat/M_New.uexp"].text(3), "材质")
            self.assertEqual(rows["Maps/New.umap"].text(3), "关卡")
            buttons["取消"].click()
        self.run_dialog(verify)
        self.external.assert_called_once()
        sources = self.external.call_args.args[0]
        self.assertIn(str(self.root / "Library/Content/Mat/M_New.uasset"), sources)

    def test_select_all_invert_and_header_include_missing_files(self):
        def verify(dialog, tree, rows, buttons):
            old = rows["Mat/M_Shared.uasset"]
            summary = dialog.findChild(QtWidgets.QLabel, "UEConflictSelectionSummary")
            buttons["全选"].click()
            self.assertEqual(old.checkState(0), QtCore.Qt.Checked)
            self.assertTrue(all(row.checkState(0) == QtCore.Qt.Checked for row in rows.values()))
            self.assertIn("已选择 4 / 4", summary.text())
            buttons["反选"].click()
            self.assertEqual(old.checkState(0), QtCore.Qt.Unchecked)
            self.assertTrue(all(row.checkState(0) == QtCore.Qt.Unchecked for row in rows.values()))
            self.assertIn("新增 0", summary.text())
            header = dialog.findChild(sceneTools._UEHeaderCheckBox)
            header.nextCheckState()
            self.assertEqual(old.checkState(0), QtCore.Qt.Checked)
            for path in self.plan["missing_files"]:
                self.assertEqual(rows[path].checkState(0), QtCore.Qt.Checked)
            buttons["加载选中项"].click()
        self.assertTrue(self.run_dialog(verify))
        self.assertEqual(self.plan["overwrite_files"], ["Mat/M_Shared.uasset"])
        self.assertEqual(self.plan["keep_existing_files"], [])
        self.assertEqual(len(self.plan["missing_files"]), 3)
        self.assertEqual(self.plan["skipped_missing_files"], [])

    def test_keep_all_clears_conflicts_but_new_files_never_enter_keep_list(self):
        def verify(dialog, tree, rows, buttons):
            buttons["全选"].click()
            buttons["全部保留并加载"].click()
        self.assertTrue(self.run_dialog(verify))
        self.assertEqual(self.plan["overwrite_files"], [])
        self.assertEqual(self.plan["keep_existing_files"], ["Mat/M_Shared.uasset"])
        self.assertEqual(len(self.plan["missing_files"]), 3)

    def test_cancel_keeps_plan_unchanged(self):
        before = copy.deepcopy(self.plan)
        self.assertFalse(self.run_dialog(lambda dialog, tree, rows, buttons: buttons["取消"].click()))
        self.assertEqual(self.plan, before)

    def test_no_conflicts_keeps_existing_direct_load_flow(self):
        self.plan["different_files"] = []
        with mock.patch.object(sceneTools._UEConflictDialog, "exec") as execute:
            self.assertFalse(sceneTools.choose_ue_conflict_files(None, self.plan))
            execute.assert_not_called()

    def test_component_files_use_same_new_markers_without_package_type_queries(self):
        def verify(dialog, tree, rows, buttons):
            self.assertEqual(tree.headerItem().text(1), "文件名")
            row = rows["Mat/M_New.uasset"]
            self.assertEqual(row.text(1), "M_New.uasset")
            self.assertEqual(row.text(0), "")
            self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
            self.assertNotIn("/Game/", row.text(2))
            buttons["全部保留并加载"].click()
        self.assertTrue(self.run_dialog(verify, plugin=True))
        self.external.assert_not_called()
        self.assertEqual(self.plan["keep_existing_files"], ["Mat/M_Shared.uasset"])

    def test_unchecked_missing_files_are_not_copied_or_removed_from_manifest(self):
        skipped = {"Mat/M_New.uasset", "Mat/M_New.uexp"}
        def verify(dialog, tree, rows, buttons):
            for path in skipped:
                rows[path].setCheckState(0, QtCore.Qt.Unchecked)
            rows["Maps/New.umap"].setCheckState(0, QtCore.Qt.Checked)
            rows["Mat/M_Shared.uasset"].setCheckState(0, QtCore.Qt.Checked)
            buttons["加载选中项"].click()
        self.assertTrue(self.run_dialog(verify))
        self.assertEqual(set(self.plan["skipped_missing_files"]), skipped)
        self.plan["package_object_paths"] = ["/Game/Mat/M_Shared.M_Shared", "/Game/Mat/M_New.M_New", "/Game/Maps/New.New"]
        worker = ue_asset_service.AssetCopyWorker(self.plan)
        completed, errors = [], []
        worker.finished.connect(completed.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(completed), 1)
        for entry in self.entries:
            target = Path(entry["target"])
            if entry["relative"] in skipped:
                self.assertFalse(target.exists())
            else:
                self.assertEqual(target.read_bytes(), Path(entry["source"]).read_bytes())
        self.assertEqual(len(completed[0]["files"]), 4)
        self.assertEqual(set(completed[0]["missing_files"]), skipped)

    def test_keep_existing_honors_unchecked_missing_files(self):
        def verify(dialog, tree, rows, buttons):
            rows["Mat/M_New.uasset"].setCheckState(0, QtCore.Qt.Checked)
            rows["Mat/M_New.uexp"].setCheckState(0, QtCore.Qt.Checked)
            rows["Maps/New.umap"].setCheckState(0, QtCore.Qt.Unchecked)
            rows["Mat/M_Shared.uasset"].setCheckState(0, QtCore.Qt.Checked)
            buttons["全部保留并加载"].click()
        self.assertTrue(self.run_dialog(verify))
        self.assertEqual(self.plan["overwrite_files"], [])
        self.assertEqual(self.plan["keep_existing_files"], ["Mat/M_Shared.uasset"])
        self.assertEqual(self.plan["skipped_missing_files"], ["Maps/New.umap"])

    def test_case_and_separator_variants_of_new_paths_only_appear_once(self):
        self.plan["missing_files"] += ["mat\\M_NEW.UASSET", "mat/m_shared.uasset"]
        def verify(dialog, tree, rows, buttons):
            self.assertEqual(tree.topLevelItemCount(), 4)
            self.assertEqual(sum(row.data(0, QtCore.Qt.UserRole + 1) == "new" for row in rows.values()), 3)
            buttons["全部保留并加载"].click()
        self.assertTrue(self.run_dialog(verify))
        self.assertEqual(self.plan["keep_existing_files"], ["Mat/M_Shared.uasset"])


if __name__ == "__main__":
    unittest.main()
