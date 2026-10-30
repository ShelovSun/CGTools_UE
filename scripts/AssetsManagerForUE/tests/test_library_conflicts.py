"""All library load buttons honor per-file conflict choices using real temp files."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import test_asset_availability  # initializes the offline Unreal stub
from test_component_library import OfflineComponentToolsUI
from test_vfx_library import OfflineVfxToolsUI
from AssetsManagerForUE.sources import blueprintTools, component_service, sceneTools, ue_asset_service
from AssetsManagerForUE.utils import myWidget
from PySide6 import QtCore, QtWidgets


class OfflineBlueprintToolsUI(blueprintTools.BlueprintToolsUI):
    def refreshLibrary(self):
        pass

    def _readSettings(self):
        return 120, None, False

    def _rememberSettings(self):
        pass

    def _queueThumbnails(self, assets):
        pass


class LibraryConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="library_conflicts_")
        self.root = Path(self.temporary.name) / "项目 O'Brien"
        self.uis = []
        self.chooser_calls = 0

    def tearDown(self):
        for ui in self.uis:
            ui.shutdownThreads()
            ui.close()
            ui.deleteLater()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.temporary.cleanup()

    def wait_for_copy(self, ui):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.app.processEvents()
            if ui._copy_thread is None:
                return
            time.sleep(0.002)
        self.fail("copy thread did not finish")

    def write(self, file, content):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)

    def make_files(self, source, target, names):
        values = {}
        for index, relative in enumerate(names):
            server = b"server_version_" + str(index).encode()
            local = b"local__version_" + str(index).encode() if index < 2 else None
            self.write(source / relative, server)
            if local is not None:
                self.write(target / relative, local)
                # Even matching size + mtime cannot hide a conflict on click.
                shutil.copystat(source / relative, target / relative)
            values[relative] = (server, local)
        return values

    def chooser(self, choice, selected, plugin=False, missing=True):
        def execute(dialog):
            self.chooser_calls += 1
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            self.assertEqual(tree.topLevelItemCount(), 3 if missing else 2)
            self.assertEqual(sum(tree.topLevelItem(i).data(0, QtCore.Qt.UserRole + 1) == "new"
                                 for i in range(tree.topLevelItemCount())), int(missing))
            if plugin:
                self.assertEqual(tree.headerItem().text(1), "文件名")
                self.assertNotIn("/Game/", tree.topLevelItem(0).text(2))
            for index in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(index)
                self.assertEqual(row.checkState(0), QtCore.Qt.Unchecked)
                if (row.data(0, QtCore.Qt.UserRole) == selected
                        or row.data(0, QtCore.Qt.UserRole + 1) == "new"):
                    row.setCheckState(0, QtCore.Qt.Checked)
            label = {"partial": "加载选中项", "keep": "全部保留并加载", "cancel": "取消"}[choice]
            next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                 if button.text() == label).click()
            return dialog.result()
        return execute

    def populate_card(self, ui, source, path, category):
        row = (0, Path(source).stem, "", "", "", "", "", "", str(source), category, path)
        ui.card_list.setItems([row])
        ui.card_list.addItems("")
        ui.card_list.setCurrentRow(0)
        self.uis.append(ui)
        return ui.card_list.currentItem()

    def test_blueprint_and_vfx_partial_keep_and_cancel(self):
        for page in ("blueprint", "vfx"):
            for choice in ("partial", "keep", "cancel"):
                with self.subTest(page=page, choice=choice):
                    case = self.root / (page + "_" + choice)
                    content = case / "Library/Content"
                    target = case / "Project/Content"
                    prefix = "Assets/Blueprints/Team1" if page == "blueprint" else "VFX/Team1"
                    names = [prefix + "/BP_Main.uasset", prefix + "/Mat/M_Main.uasset", prefix + "/Tex/T_New.uasset"]
                    values = self.make_files(content, target, names)
                    path = ue_asset_service.object_path_for_source_file(content / names[0], content)
                    if page == "blueprint":
                        plan = ue_asset_service.build_folder_import_plan(content / prefix, content, target)
                        ui = OfflineBlueprintToolsUI()
                        ui._categories = {"Team1": {"folder": str(content / prefix),
                            "content_root": str(content), "plan": plan}}
                        self.populate_card(ui, content / names[0], path, "Team1")
                        load = ui.loadBlueprintCategory
                        register_name = "_registerCategoryPlan"
                        builder_patch = mock.patch.object(ui, "_startCategoryReplacement",
                                                         side_effect=AssertionError("whole category replacement"))
                    else:
                        plan = ue_asset_service._build_package_file_import_plan(
                            [content / name for name in names], content, content / names[0], target,
                            dependency_resolved=True)
                        ui = OfflineVfxToolsUI()
                        asset = {"name": "NS_Main", "path": "Team1/NS_Main.uasset",
                                 "source_file": str(content / names[0]), "object_path": path, "plan": plan}
                        ui._library_payload = {"content_root": str(content)}
                        ui._assets_by_source = {os.path.normcase(asset["source_file"]): asset}
                        self.populate_card(ui, content / names[0], path, "Team1")
                        load = ui.loadVfx
                        register_name = "_registerPlan"
                        builder_patch = mock.patch.object(ue_asset_service, "build_external_dependency_import_plan",
                                                         return_value=copy.deepcopy(plan))
                    with builder_patch, \
                            mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser(choice, names[0])), \
                            mock.patch.object(QtWidgets.QMessageBox, "question", side_effect=AssertionError("redundant confirmation")), \
                            mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]) as prepare, \
                            mock.patch.object(ui, register_name) as register:
                        load()
                        self.wait_for_copy(ui)
                    if choice == "cancel":
                        register.assert_not_called()
                        prepare.assert_not_called()
                    else:
                        register.assert_called_once()
                        finished = register.call_args.args[1]
                        self.assertEqual(finished["overwritten_files"], [names[0]] if choice == "partial" else [])
                        self.assertIn(names[1], finished["kept_existing_files"])
                        prepare.assert_called_once()
                    for index, (relative, (server, local)) in enumerate(values.items()):
                        file = target / relative
                        if choice == "cancel" and local is None:
                            self.assertFalse(file.exists())
                        else:
                            expected = server if (local is None or (choice == "partial" and index == 0)) else local
                            self.assertEqual(file.read_bytes(), expected)

    def component_fixture(self, suffix="component", missing=True):
        source = self.root / suffix / "Library/Team1/ExamplePlugin"
        plugins = self.root / suffix / "Project/Plugins"
        target = plugins / "ExamplePlugin"
        names = ["Binaries/Win64/Example.dll", "ExamplePlugin.uplugin", "Content/New.txt"]
        values = self.make_files(source, target, names)
        if not missing:
            (source / names[2]).unlink()
        self.write(target / "LocalOnly.txt", b"local only")
        plan = component_service.build_component_plan("Team1", source, plugins)
        component = {"name": "ExamplePlugin", "path": "Team1/ExamplePlugin", "category": "Team1",
                     "folder": str(source), "plan": plan}
        ui = OfflineComponentToolsUI()
        ui._components_by_folder = {os.path.normcase(str(source)): component}
        self.populate_card(ui, source, str(source), "Team1")
        return ui, component, source, target, values

    def test_component_partial_update_stages_then_merges_latest_local_files_after_exit(self):
        ui, component, source, target, values = self.component_fixture()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec",
                               self.chooser("partial", "Binaries/Win64/Example.dll", plugin=True)), \
                mock.patch.object(ui, "_promptRestart") as restart:
            ui.loadComponent()
            self.wait_for_copy(ui)
        restart.assert_called_once()
        self.assertTrue(restart.call_args.kwargs["replacing"])
        plan = restart.call_args.args[1]
        stage = Path(plan["staging_folder"])
        self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])
        self.assertEqual((stage / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][0])
        self.assertTrue((stage / "Content/New.txt").exists())
        self.assertFalse((stage / "ExamplePlugin.uplugin").exists())
        # These saves happen after staging, as they would during UE's save dialog.
        self.write(target / "ExamplePlugin.uplugin", b'{"FileVersion":3,"SavedAfterStaging":true}')
        self.write(target / "AfterStaging.txt", b"late local save")
        saved = target.parent.parent / "Saved"
        saved.mkdir()
        script = saved / "apply_component.ps1"
        lines = ["$ErrorActionPreference = 'Stop'",
                 "$logPath = " + component_service._ps_quote(str(saved / "merge.log"))]
        lines.extend(component_service._replacement_script_lines(plan, str(saved)))
        script.write_text("\n".join(lines), encoding="utf-8-sig")
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(script)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][0])
        self.assertEqual((target / "ExamplePlugin.uplugin").read_bytes(), b'{"FileVersion":3,"SavedAfterStaging":true}')
        self.assertEqual((target / "LocalOnly.txt").read_bytes(), b"local only")
        self.assertEqual((target / "AfterStaging.txt").read_bytes(), b"late local save")
        self.assertEqual((target / "Content/New.txt").read_bytes(), values["Content/New.txt"][0])
        backups = list((saved / "AssetsManagerForUE/ComponentBackups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])

    def test_component_keep_all_only_adds_missing_and_restart_depends_on_changes(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                ui, component, _source, target, values = self.component_fixture(str(missing), missing=missing)
                with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser("keep", "", plugin=True, missing=missing)), \
                        mock.patch.object(ui, "_promptRestart") as restart:
                    ui.loadComponent()
                    self.wait_for_copy(ui)
                self.assertEqual(restart.call_count, int(missing))
                plan = component["plan"]
                self.assertTrue(plan["load_completed"])
                self.assertEqual(plan["state"], "conflict")
                self.assertNotIn("staging_folder", plan)
                for relative in ("Binaries/Win64/Example.dll", "ExamplePlugin.uplugin"):
                    self.assertEqual((target / relative).read_bytes(), values[relative][1])
                self.assertEqual((target / "Content/New.txt").exists(), missing)

    def test_component_cancel_does_not_copy_stage_or_restart(self):
        ui, _component, _source, target, values = self.component_fixture()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser("cancel", "", plugin=True)), \
                mock.patch.object(ui, "_startCopy") as start, \
                mock.patch.object(ui, "_promptRestart") as restart:
            ui.loadComponent()
        start.assert_not_called()
        restart.assert_not_called()
        self.assertEqual(self.chooser_calls, 1)
        self.assertFalse((target / "Content/New.txt").exists())
        self.assertFalse((target.parent / ".AssetsManagerForUE_Staging").exists())
        self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])

    def test_component_unchecked_missing_file_is_neither_copied_nor_staged(self):
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                ui, component, _source, target, values = self.component_fixture("skip_" + str(overwrite))
                def choose(dialog):
                    tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
                    for index in range(tree.topLevelItemCount()):
                        row = tree.topLevelItem(index)
                        key = row.data(0, QtCore.Qt.UserRole)
                        row.setCheckState(0, QtCore.Qt.Checked if overwrite and key == "Binaries/Win64/Example.dll"
                                          else QtCore.Qt.Unchecked)
                    next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                         if button.text() == "加载选中项").click()
                    return dialog.result()
                with mock.patch.object(sceneTools._UEConflictDialog, "exec", choose), \
                        mock.patch.object(ui, "_promptRestart") as restart:
                    ui.loadComponent()
                    self.wait_for_copy(ui)
                self.assertFalse((target / "Content/New.txt").exists())
                plan = component["plan"]
                self.assertEqual(plan["skipped_missing_files"], ["Content/New.txt"])
                self.assertEqual(restart.call_count, int(overwrite))
                if overwrite:
                    staged = restart.call_args.args[1]
                    stage = Path(staged["staging_folder"])
                    self.assertFalse((stage / "Content/New.txt").exists())
                    self.assertEqual(staged["staged_files"], ["Binaries/Win64/Example.dll"])
                else:
                    self.assertTrue(plan["load_completed"])
                    self.assertIn("Content/New.txt", plan["missing_files"])
                self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])
    def test_unresolved_component_conflict_and_live_overwrite_are_rejected(self):
        _ui, component, _source, target, values = self.component_fixture()
        for stage, policies in ((True, {}), (False, {"overwrite_files": ["Binaries/Win64/Example.dll"],
                                                    "keep_existing_files": ["ExamplePlugin.uplugin"]})):
            plan = dict(component["plan"], **policies)
            worker = component_service.ComponentCopyWorker(plan, stage_replacement=stage)
            errors = []
            worker.failed.connect(errors.append)
            worker.run()
            self.assertEqual(len(errors), 1)
            self.assertFalse((target / "Content/New.txt").exists())
            self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])

    def test_cancelling_component_restart_discards_stage_and_preserves_original_plugin(self):
        ui, component, _source, target, values = self.component_fixture()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec",
                               self.chooser("partial", "Binaries/Win64/Example.dll", plugin=True)), \
                mock.patch.object(QtWidgets.QMessageBox, "exec", return_value=QtWidgets.QMessageBox.No), \
                mock.patch.object(component_service, "restart_editor") as restart:
            ui.loadComponent()
            self.wait_for_copy(ui)
        restart.assert_not_called()
        self.assertNotIn("staging_folder", component["plan"])
        self.assertFalse((target.parent / ".AssetsManagerForUE_Staging").exists())
        self.assertEqual((target / "Binaries/Win64/Example.dll").read_bytes(), values["Binaries/Win64/Example.dll"][1])
        self.assertFalse((target / "Content/New.txt").exists())


if __name__ == "__main__":
    unittest.main()
