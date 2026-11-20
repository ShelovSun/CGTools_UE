"""Animation package copying and the optional asset prerequisite, with real I/O."""

import os
import sys
import tempfile
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

from PySide6 import QtCore, QtWidgets
from AssetsManagerForUE.sources import action_service, ue_asset_service, assetTools, sceneTools
from test_asset_availability import OfflineAssetToolsUI


def asset_data(package, name, asset_class):
    return types.SimpleNamespace(package_name=package, asset_name=name,
                                 asset_class_path=types.SimpleNamespace(asset_name=asset_class))


class ActionLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="action_load_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = mock.patch.dict(os.environ, LOCALAPPDATA=str(self.root))
        environment.start()
        self.addCleanup(environment.stop)
        self.server = self.root / "Server/GOF"
        self.source = self.server / "Animations/Characters/BaSiTeV4/Action/BaSiTeV4_Walk.uasset"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"new animation")
        self.content = self.root / "Project/Content"
        self.target = self.content / "Assets/Characters/BaSiTeV4/Action/BaSiTeV4_Walk.uasset"
        self.mesh_target = self.content / "Assets/Characters/BaSiTeV4/BaSiTeV4.uasset"
        self.has_mesh = True
        self.context = action_service.action_context(str(self.source))
        self.registry = mock.Mock()
        self.mesh_data = asset_data("/Game/Assets/Characters/BaSiTeV4/BaSiTeV4", "BaSiTeV4", "SkeletalMesh")
        self.animation_data = asset_data(self.context["package_name"], "BaSiTeV4_Walk", "AnimSequence")
        self.registry.get_assets_by_path.side_effect = lambda *args, **kwargs: (
            [self.mesh_data] if self.has_mesh or self.mesh_target.is_file() else [self.animation_data])
        self.registry.get_assets_by_package_name.return_value = [self.animation_data]
        self.engine = types.SimpleNamespace(
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: self.registry,
                                                       create_asset_data=mock.Mock()),
            EditorAssetLibrary=mock.Mock(),
            EditorLoadingAndSavingUtils=mock.Mock(), find_object=mock.Mock(return_value=None),
            find_package=mock.Mock(return_value=None))
        self.animation = mock.Mock()
        self.animation.get_name.return_value = "BaSiTeV4_Walk"
        self.animation.get_path_name.return_value = self.context["package_name"] + ".BaSiTeV4_Walk"
        self.engine.EditorAssetLibrary.load_asset.return_value = self.animation
        self.engine.AssetRegistryHelpers.create_asset_data.return_value.is_u_asset.return_value = True
        for patcher in (
            mock.patch.object(ue_asset_service, "unreal", self.engine),
            mock.patch.object(ue_asset_service, "_project_content_dir", return_value=str(self.content)),
            mock.patch.object(ue_asset_service, "sync_to_content_browser", return_value=True),
            mock.patch.object(ue_asset_service, "get_external_asset_class_names",
                              side_effect=lambda paths, root: (["AnimSequence" if "/Action/" in path
                                                                 else "Material" for path in paths], "")),
            mock.patch.object(ue_asset_service, "project_asset_class_name", return_value=""),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.question_patch = mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No)
        self.question = self.question_patch.start()
        self.addCleanup(self.question_patch.stop)
        self.warning_patch = mock.patch.object(QtWidgets.QMessageBox, "warning")
        self.warning = self.warning_patch.start()
        self.addCleanup(self.warning_patch.stop)
        self.information_patch = mock.patch.object(QtWidgets.QMessageBox, "information")
        self.information = self.information_patch.start()
        self.addCleanup(self.information_patch.stop)
        self.ui = OfflineAssetToolsUI(isSQL=False)
        self.app.processEvents()

    def tearDown(self):
        self.ui.shutdownThreads()
        self.ui.close()
        self.ui.deleteLater()
        self.app.processEvents()

    def wait_finished(self):
        deadline = time.monotonic() + 5
        while self.ui._copy_thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIsNone(self.ui._copy_thread, "copy worker must finish and release its thread")

    def publish_mesh(self):
        mesh = self.server / "Assets/Characters/BaSiTeV4/UE/Content/Assets/Characters/BaSiTeV4/BaSiTeV4.uasset"
        mesh.parent.mkdir(parents=True)
        mesh.write_bytes(b"mesh package")
        return mesh

    def test_existing_asset_loads_a_visible_correctly_named_animation(self):
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.question.assert_not_called()
        self.warning.assert_not_called()
        self.information.assert_called_once()
        self.assertEqual(self.information.call_args.args[1], "加载动作完成")
        self.assertIn(self.context["package_name"], self.information.call_args.args[2])
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertFalse(self.target.with_suffix(".fbx").exists())
        self.registry.scan_files_synchronous.assert_called_once_with([self.target.as_posix()], True)
        self.engine.EditorAssetLibrary.load_asset.assert_called_with(self.context["package_name"] + ".BaSiTeV4_Walk")
        ue_asset_service.sync_to_content_browser.assert_called_with(self.context["package_name"] + ".BaSiTeV4_Walk")
        self.animation.rename.assert_not_called()

    def legacy_animation(self):
        self.animation_data.asset_name = "OriginalWalk"
        self.animation.get_name.return_value = "OriginalWalk"

        def rename(name):
            self.animation.get_name.return_value = name
            self.animation.get_path_name.return_value = self.context["package_name"] + "." + name
            return True

        def save(packages, only_dirty):
            self.target.write_bytes(b"UE resaved animation with matching object name")
            return True

        self.animation.rename.side_effect = rename
        self.engine.EditorLoadingAndSavingUtils.save_packages.side_effect = save

    def test_legacy_name_is_repaired_backed_up_and_repeat_load_recognizes_resave(self):
        self.legacy_animation()
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_not_called()
        self.assertNotEqual(self.target.read_bytes(), self.source.read_bytes())
        backups = list((self.root / "Project/Saved/CGTools/ActionLoading/Backups").rglob("*.uasset"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.source.read_bytes())
        self.assertEqual(self.source.read_bytes(), b"new animation")
        self.animation.rename.assert_called_once_with("BaSiTeV4_Walk")
        ue_asset_service.sync_to_content_browser.assert_called_with(self.context["package_name"] + ".BaSiTeV4_Walk")
        plan = action_service.build_import_plan(str(self.source))
        self.assertEqual(plan["state"], "ready")
        self.ui.loadActionFile(str(self.source))
        self.warning.assert_not_called()
        self.animation.rename.assert_called_once()
        self.source.write_bytes(b"republished server animation")
        self.assertEqual(action_service.build_import_plan(str(self.source))["state"], "conflict")

    def test_modified_local_resave_remains_a_conflict(self):
        self.legacy_animation()
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.target.write_bytes(b"user edited animation")
        self.assertEqual(action_service.build_import_plan(str(self.source))["state"], "conflict")

    def test_repair_save_failure_restores_the_original_file_and_reports_error(self):
        self.legacy_animation()
        self.engine.EditorLoadingAndSavingUtils.save_packages.side_effect = lambda *args: False
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_called_once()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.animation.rename.assert_called_once_with("BaSiTeV4_Walk")
        self.assertIn("重启", str(self.warning.call_args))
        ue_asset_service.sync_to_content_browser.assert_not_called()

    def test_internal_name_collision_is_not_overwritten(self):
        self.legacy_animation()
        self.engine.find_object.return_value = mock.Mock()
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_called_once()
        self.animation.rename.assert_not_called()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_non_primary_asset_is_not_reported_as_visible(self):
        self.engine.AssetRegistryHelpers.create_asset_data.return_value.is_u_asset.return_value = False
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_called_once()
        ue_asset_service.sync_to_content_browser.assert_not_called()

    def test_action_only_folder_does_not_count_as_an_existing_asset_and_no_cancels(self):
        self.has_mesh = False
        self.target.parent.mkdir(parents=True)
        self.ui.loadActionFile(str(self.source))
        self.question.assert_called_once()
        self.assertFalse(self.target.exists())
        self.assertIsNone(self.ui._copy_thread)
        self.warning.assert_not_called()

    def test_yes_loads_prerequisite_and_action_in_the_same_transaction(self):
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        mesh = self.publish_mesh()
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.question.assert_called_once()
        self.warning.assert_not_called()
        self.assertEqual(self.mesh_target.read_bytes(), mesh.read_bytes())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.registry.scan_paths_synchronous.assert_called_once()
        self.registry.scan_files_synchronous.assert_called_once()

    def test_missing_prerequisite_release_reports_error_and_copies_nothing(self):
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        self.ui.loadActionFile(str(self.source))
        self.warning.assert_called_once()
        self.assertFalse(self.target.exists())
        self.assertIsNone(self.ui._copy_thread)

    def test_different_existing_animation_is_not_silently_overwritten(self):
        self.target.parent.mkdir(parents=True)
        old = b"old animation"
        self.target.write_bytes(old)
        self.assertEqual(len(old), self.source.stat().st_size)
        with mock.patch.object(self.ui, "_chooseConflictFiles", return_value=False) as choose:
            self.ui.loadActionFile(str(self.source))
        choose.assert_called_once()
        self.warning.assert_not_called()
        self.assertEqual(self.target.read_bytes(), old)
        self.assertIsNone(self.ui._copy_thread)

    def chooser(self, selected=(), include_missing=False, skip_missing=(), button="加载选中项", inspect=None):
        def execute(dialog):
            tree = dialog.findChild(QtWidgets.QTreeWidget, "UEConflictTree")
            rows = {tree.topLevelItem(i).data(0, QtCore.Qt.UserRole): tree.topLevelItem(i)
                    for i in range(tree.topLevelItemCount())}
            if inspect:
                inspect(dialog, rows)
            for relative, row in rows.items():
                wanted = (relative in selected or (include_missing
                    and row.data(0, QtCore.Qt.UserRole + 1) == "new" and relative not in skip_missing))
                row.setCheckState(0, QtCore.Qt.Checked if wanted else QtCore.Qt.Unchecked)
            next(widget for widget in dialog.findChildren(QtWidgets.QPushButton)
                 if widget.text() == button).click()
            return dialog.result()
        return execute

    def conflict_target(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(b"old animation")

    def publish_dependency(self, name, local=False):
        relative = "Assets/Characters/BaSiTeV4/" + name
        source = self.server / "Assets/Characters/BaSiTeV4/UE/Content" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"server dependency")
        target = self.content / relative
        if local:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"local_ dependency")
        return relative, source, target

    def test_action_conflict_uses_real_shared_dialog_and_selected_overwrite(self):
        self.conflict_target()
        relative = self.context["relative"]
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser([relative])), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites",
                                  wraps=ue_asset_service.prepare_plan_overwrites) as prepare:
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(prepare.call_args.args[0]["overwrite_files"], [relative])
        self.warning.assert_not_called()
        self.registry.scan_files_synchronous.assert_called_once()

    def test_shared_keep_all_loads_existing_animation_without_overwrite(self):
        self.conflict_target()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec",
                               self.chooser(button="全部保留并加载")), \
                mock.patch.object(action_service, "register_import", wraps=action_service.register_import) as register:
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.assertEqual(self.target.read_bytes(), b"old animation")
        self.assertIn("保留工程版本 1", register.call_args.args[0]["message"])
        self.warning.assert_not_called()
        ue_asset_service.sync_to_content_browser.assert_called_once()

    def test_real_dialog_cancel_copies_nothing_and_skips_overwrite_preparation(self):
        self.conflict_target()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser(button="取消")), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites") as prepare, \
                mock.patch.object(ue_asset_service, "AssetCopyWorker") as worker:
            self.ui.loadActionFile(str(self.source))
        prepare.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"old animation")
        self.warning.assert_not_called()

    def test_prerequisite_dialog_lists_conflicts_and_missing_and_copies_only_choices(self):
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        mesh = self.publish_mesh()
        replace, server, replaced = self.publish_dependency("Mat/Replace.uasset", local=True)
        keep, _, kept = self.publish_dependency("Mat/Keep.uasset", local=True)
        missing, _, added = self.publish_dependency("Tex/New.uasset")
        skip, _, skipped = self.publish_dependency("Tex/Skip.uasset")
        def inspect(dialog, rows):
            self.assertEqual(len(rows), 6)
            self.assertEqual(rows[replace].data(0, QtCore.Qt.UserRole + 1), "conflict")
            self.assertEqual(rows[missing].text(5), "缺失")
            self.assertIn(self.context["relative"], rows)
        with mock.patch.object(sceneTools._UEConflictDialog, "exec",
                               self.chooser([replace], include_missing=True, skip_missing=[skip], inspect=inspect)), \
                mock.patch.object(action_service, "register_import", wraps=action_service.register_import) as register:
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.assertEqual(replaced.read_bytes(), server.read_bytes())
        self.assertEqual(kept.read_bytes(), b"local_ dependency")
        self.assertTrue(added.exists())
        self.assertFalse(skipped.exists())
        self.assertEqual(self.mesh_target.read_bytes(), mesh.read_bytes())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        plan = register.call_args.args[0]
        self.assertEqual(plan["prerequisite_plan"]["missing_files"], [skip])
        self.assertEqual(plan["prerequisite_plan"]["different_files"], [keep])
        self.assertTrue(plan["prerequisite_plan"]["asset_present"])
        self.assertEqual(plan["prerequisite_plan"]["state"], "conflict")
        self.warning.assert_not_called()

    def test_cancelling_dirty_overwrite_starts_no_copy(self):
        self.conflict_target()
        def cancel(plan):
            plan["overwrite_cancelled"] = True
            return ["已取消覆盖，保留资产的未保存修改"]
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser([self.context["relative"]])), \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", side_effect=cancel), \
                mock.patch.object(ue_asset_service, "AssetCopyWorker") as worker:
            self.ui.loadActionFile(str(self.source))
        worker.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"old animation")
        self.warning.assert_not_called()

    def test_unchecked_missing_action_is_skipped_after_selected_prerequisite_copy(self):
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        self.publish_mesh()
        _, _, kept = self.publish_dependency("Mat/Keep.uasset", local=True)
        with mock.patch.object(sceneTools._UEConflictDialog, "exec",
                               self.chooser(include_missing=True, skip_missing=[self.context["relative"]])), \
                mock.patch.object(action_service, "register_import", wraps=action_service.register_import) as register:
            self.ui.loadActionFiles([str(self.source)])
            self.wait_batch()
        self.assertTrue(self.mesh_target.exists())
        self.assertFalse(self.target.exists())
        self.assertEqual(kept.read_bytes(), b"local_ dependency")
        self.assertTrue(register.call_args.args[0]["action_skipped"])
        self.assertEqual(self.ui._action_batch.results[0]["state"], "skipped")
        self.registry.scan_files_synchronous.assert_not_called()
        ue_asset_service.sync_to_content_browser.assert_not_called()
        self.warning.assert_not_called()

    def test_cancelled_conflict_in_batch_continues_to_later_actions(self):
        paths = self.batch_sources()
        self.conflict_target()
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser(button="取消")), \
                mock.patch.object(action_service, "register_import", side_effect=self.register_batch):
            self.ui.loadActionFiles([str(path) for path in paths])
            self.wait_batch()
        self.assertEqual([item["state"] for item in self.ui._action_batch.results],
                         ["skipped", "succeeded", "succeeded"])
        self.assertEqual(self.target.read_bytes(), b"old animation")
        self.warning.assert_not_called()

    def test_normalized_animation_keeps_are_preserved_during_prerequisite_conflict_choice(self):
        self.legacy_animation()
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        normalized = self.target.read_bytes()
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        self.publish_mesh()
        relative, server, target = self.publish_dependency("Mat/Replace.uasset", local=True)
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser([relative], include_missing=True)):
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.assertEqual(self.target.read_bytes(), normalized)
        self.assertEqual(target.read_bytes(), server.read_bytes())
        self.animation.rename.assert_called_once()
        self.warning.assert_not_called()

    def test_selected_action_overwrite_failure_restores_original_and_removes_new_sidecar(self):
        self.conflict_target()
        self.source.with_suffix(".uexp").write_bytes(b"new sidecar")
        original = ue_asset_service._replace_with_retry
        def fail_action(source, target, *args, **kwargs):
            if ".cgtools_tmp_" in str(source) and str(target) == self.target.as_posix():
                raise OSError("disk full")
            return original(source, target, *args, **kwargs)
        with mock.patch.object(sceneTools._UEConflictDialog, "exec", self.chooser([self.context["relative"]], include_missing=True)), \
                mock.patch.object(ue_asset_service, "_replace_with_retry", side_effect=fail_action):
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.assertEqual(self.target.read_bytes(), b"old animation")
        self.assertFalse(self.target.with_suffix(".uexp").exists())
        self.assertEqual(list(self.content.rglob("*.cgtools_tmp_*")), [])
        self.registry.scan_files_synchronous.assert_not_called()
        self.warning.assert_called_once()

    def test_identical_existing_file_is_registered_without_another_copy(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.source.read_bytes())
        with mock.patch.object(ue_asset_service, "AssetCopyWorker") as copy_worker:
            self.ui.loadActionFile(str(self.source))
        copy_worker.assert_not_called()
        self.warning.assert_not_called()
        self.information.assert_called_once()
        self.registry.scan_files_synchronous.assert_called_once()

    def test_missing_skeleton_is_reported_instead_of_claiming_the_animation_loaded(self):
        self.engine.EditorAssetLibrary.load_asset.return_value.get_editor_property.return_value = None
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_called_once()
        self.information.assert_not_called()
        ue_asset_service.sync_to_content_browser.assert_not_called()

    def test_copy_failure_does_not_register_or_leave_asset_or_action_files(self):
        self.has_mesh = False
        self.question.return_value = QtWidgets.QMessageBox.Yes
        self.publish_mesh()
        with mock.patch.object(ue_asset_service, "_replace_with_retry", side_effect=OSError("disk full")):
            self.ui.loadActionFile(str(self.source))
            self.wait_finished()
        self.warning.assert_called_once()
        self.registry.scan_files_synchronous.assert_not_called()
        self.assertFalse(self.mesh_target.exists())
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.content.rglob("*.cgtools_tmp_*")), [])

    def test_sidecars_are_loaded_with_the_animation_but_not_unrelated_packages(self):
        self.source.with_suffix(".uexp").write_bytes(b"sidecar")
        (self.source.parent / "Other.uasset").write_bytes(b"unrelated")
        plan = action_service.build_import_plan(str(self.source))
        self.assertEqual({Path(entry["source"]).name for entry in plan["files"]}, {self.source.name, self.source.with_suffix(".uexp").name})
        worker = ue_asset_service.AssetCopyWorker(plan)
        errors = []
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(self.target.with_suffix(".uexp").read_bytes(), b"sidecar")
        self.assertFalse((self.target.parent / "Other.uasset").exists())

    def test_props_nested_actions_and_uppercase_extensions_map_to_flat_action_folder(self):
        source = self.server / "Animations/Props/Sword/Action/Combat/Action/Strike.UASSET"
        context = action_service.action_context(str(source))
        self.assertEqual(context["relative"], "Assets/Props/Sword/Action/Strike.uasset")
        self.assertEqual(context["game_folder"], "/Game/Assets/Props/Sword")
        self.assertEqual(context["asset_root"], (self.server / "Assets/Props/Sword").as_posix())

    def test_invalid_animation_location_is_rejected_before_copying(self):
        with self.assertRaises(ValueError):
            action_service.build_import_plan(str(self.server / "Assets/Characters/Hero/Action/Walk.uasset"))

    def wait_batch(self):
        deadline = time.monotonic() + 8
        while (self.ui._action_batch.active or self.ui._copy_thread is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertFalse(self.ui._action_batch.active, 'batch must finish')
        self.assertIsNone(self.ui._copy_thread, 'copy thread must be released')

    def batch_sources(self):
        paths = [self.source]
        for name in ('BaSiTeV4_Run', 'BaSiTeV4_Jump'):
            path = self.source.with_name(name + '.uasset')
            path.write_bytes(name.encode('ascii'))
            paths.append(path)
        return paths

    def register_batch(self, plan):
        plan['message'] = 'registered ' + plan['action_context']['source_file']
        return plan

    def test_batch_load_waits_for_each_real_copy_and_deduplicates_files(self):
        paths = self.batch_sources()
        results, registered = [], []
        self.ui._action_batch.finished.connect(results.append)
        def register(plan):
            self.assertIsNotNone(self.ui._copy_thread)
            registered.append(Path(plan['action_context']['source_file']))
            return self.register_batch(plan)
        with mock.patch.object(action_service, 'register_import', side_effect=register):
            self.ui.loadActionFiles([str(path) for path in paths] + [str(paths[0])])
            self.wait_batch()
        self.assertEqual(registered, paths)
        self.assertEqual([item['state'] for item in results[0]['items']], ['succeeded'] * 3)
        for path in paths:
            self.assertEqual(self.target.with_name(path.name).read_bytes(), path.read_bytes())
        self.warning.assert_not_called()
        self.information.assert_called_once()
        self.assertEqual(self.information.call_args.args[1], "批量加载动作")
        self.assertIn("成功 3，跳过 0，失败 0", self.information.call_args.args[2])

    def test_one_conflict_and_one_missing_file_do_not_stop_later_actions(self):
        paths = self.batch_sources()
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'user edited animation')
        missing = paths[1].with_name('Missing.uasset')
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(action_service, 'register_import', side_effect=self.register_batch), \
                mock.patch.object(sceneTools._UEConflictDialog, 'exec', self.chooser(button='取消')):
            self.ui.loadActionFiles([str(paths[0]), str(missing), str(paths[2])])
            self.wait_batch()
        self.assertEqual([item['state'] for item in results[0]['items']], ['skipped', 'failed', 'succeeded'])
        self.assertEqual(self.target.read_bytes(), b'user edited animation')
        self.assertTrue(self.target.with_name(paths[2].name).is_file())
        self.warning.assert_called_once()
        self.information.assert_not_called()
        self.assertIn("【加载失败】", self.warning.call_args.args[2])
        self.assertIn(str(missing).replace('\\', '/'), self.warning.call_args.args[2])

    def test_registration_failure_advances_only_after_thread_exit(self):
        paths = self.batch_sources()[:2]
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(action_service, 'register_import', side_effect=[RuntimeError('missing skeleton'), self.register_batch(action_service.build_import_plan(str(paths[1])))]):
            self.ui.loadActionFiles([str(path) for path in paths])
            self.wait_batch()
        self.assertEqual([item['state'] for item in results[0]['items']], ['failed', 'succeeded'])
        self.assertIn('missing skeleton', results[0]['items'][0]['message'])
        self.warning.assert_called_once()

    def test_ready_files_and_declined_prerequisites_finish_without_a_worker(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.source.read_bytes())
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(action_service, 'register_import', side_effect=self.register_batch), mock.patch.object(ue_asset_service, 'AssetCopyWorker') as worker:
            self.ui.loadActionFiles([str(self.source)])
            self.wait_batch()
            worker.assert_not_called()
        self.assertEqual(results[-1]['items'][0]['state'], 'succeeded')
        self.has_mesh = False
        self.ui.loadActionFiles([str(self.source)])
        self.wait_batch()
        self.assertEqual(results[-1]['items'][0]['state'], 'skipped')

    def test_fbx_batch_continues_after_import_failure_and_preserves_order(self):
        paths = [str(path.with_suffix('.fbx')) for path in self.batch_sources()]
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(self.ui, 'importActionFile', side_effect=[True, RuntimeError('FBX mismatch'), True]) as importer:
            self.ui.importActionFiles(paths)
            self.wait_batch()
        self.assertEqual([call.args[0] for call in importer.call_args_list], [path.replace('\\', '/') for path in paths])
        self.assertEqual([item['state'] for item in results[0]['items']], ['succeeded', 'failed', 'succeeded'])
        self.warning.assert_called_once()

    def test_fbx_batch_uses_one_native_progress_and_restores_ui_before_failure_summary(self):
        import ue_qt_host
        paths = [str(path.with_suffix('.fbx')) for path in self.batch_sources()]
        native = mock.MagicMock()
        native.__enter__.return_value = native
        native.should_cancel.return_value = False
        engine = types.SimpleNamespace(ScopedSlowTask=mock.Mock(return_value=native))
        def run(_path):
            self.assertFalse(self.ui.isEnabled())
            self.assertGreater(ue_qt_host._STATE.suspend_depth, 0)
            if _path == paths[1].replace('\\', '/'):
                raise RuntimeError('bad animation')
            return True
        self.warning.side_effect = lambda *_args: self.assertTrue(self.ui.isEnabled())
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(self.ui, 'importActionFile', side_effect=run):
            self.ui.importActionFiles(paths)
        engine.ScopedSlowTask.assert_called_once_with(3, '批量导入动作 FBX')
        native.make_dialog.assert_called_once_with(True)
        self.assertEqual([call.args[1].split(']')[0] for call in native.enter_progress_frame.call_args_list],
                         ['[1/3', '[2/3', '[3/3'])
        native.__exit__.assert_called_once()
        self.assertTrue(self.ui.isEnabled())
        self.assertFalse(self.ui._action_batch.active)
        self.assertEqual(ue_qt_host._STATE.suspend_depth, 0)
        self.warning.assert_called_once()

    def test_native_cancel_keeps_completed_files_and_skips_remaining_files(self):
        paths = [str(path.with_suffix('.fbx')) for path in self.batch_sources()]
        native = mock.MagicMock()
        native.__enter__.return_value = native
        native.should_cancel.side_effect = [False, True]
        engine = types.SimpleNamespace(ScopedSlowTask=mock.Mock(return_value=native))
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(self.ui, 'importActionFile', return_value=True) as importer:
            self.ui.importActionFiles(paths)
        self.assertEqual(importer.call_count, 1)
        self.assertEqual([item['state'] for item in results[0]['items']], ['succeeded', 'skipped', 'skipped'])
        self.assertTrue(self.ui.isEnabled())
        self.warning.assert_not_called()

    def test_progress_creation_failure_releases_ui_and_reports_all_unstarted_files(self):
        import ue_qt_host
        paths = [str(path.with_suffix('.fbx')) for path in self.batch_sources()]
        native = mock.MagicMock()
        native.__enter__.return_value = native
        native.make_dialog.side_effect = RuntimeError('cannot show progress')
        engine = types.SimpleNamespace(ScopedSlowTask=mock.Mock(return_value=native))
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(self.ui, 'importActionFile') as importer:
            self.ui.importActionFiles(paths)
        importer.assert_not_called()
        self.assertTrue(self.ui.isEnabled())
        self.assertFalse(self.ui._action_batch.active)
        self.assertEqual(ue_qt_host._STATE.suspend_depth, 0)
        self.warning.assert_called_once()
        self.assertIn('cannot show progress', self.warning.call_args.args[2])

    def test_second_request_is_rejected_and_shutdown_cancels_unstarted_files(self):
        paths = self.batch_sources()
        self.ui.loadActionFiles([str(path) for path in paths])
        self.ui.loadActionFiles([str(paths[0])])
        self.ui.shutdownThreads()
        self.app.processEvents()
        self.assertFalse(self.ui._action_batch.active)
        self.assertFalse(self.target.exists())
        self.assertIsNone(self.ui._copy_thread)

    def fbx_import_fixture(self):
        path = self.source.with_suffix('.fbx')
        path.write_bytes(b'test FBX task input')
        animation = mock.Mock()
        animation.get_class.return_value.get_name.return_value = 'AnimSequence'
        animation.get_path_name.return_value = self.context['package_name'] + '.BaSiTeV4_Walk'
        animation.get_editor_property.return_value.get_path_name.return_value = (
            '/Game/Assets/Characters/BaSiTeV4/BaSiTeV4_Skeleton.BaSiTeV4_Skeleton')
        engine = types.SimpleNamespace(load_asset=mock.Mock(return_value=animation),
            EditorAssetLibrary=mock.Mock(), AnimationLibrary=mock.Mock(), log_warning=mock.Mock())
        engine.EditorAssetLibrary.save_asset.return_value = True
        engine.AnimationLibrary.get_num_keys.return_value = 36
        task = mock.Mock()
        task.get_objects.return_value = []
        task.get_editor_property.return_value = [self.context['package_name'] + '.BaSiTeV4_Walk']
        factory = mock.Mock()
        factory.buildImportTask.return_value = task
        return path, animation, engine, factory

    def test_fbx_reimport_uses_task_outputs_even_for_an_existing_animation(self):
        path, animation, engine, factory = self.fbx_import_fixture()
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.assertTrue(self.ui.importActionFile(str(path)))
        engine.AnimationLibrary.set_is_root_motion_lock_forced.assert_called_once_with(animation, True)
        engine.EditorAssetLibrary.save_asset.assert_called_once()
        factory.executeImportTasks.assert_called_once()

    def test_fbx_save_failure_returns_a_failure_instead_of_claiming_success(self):
        path, _animation, engine, factory = self.fbx_import_fixture()
        engine.EditorAssetLibrary.save_asset.return_value = False
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.assertFalse(self.ui.importActionFile(str(path)))
        self.assertIn('保存动作失败', self.ui.msg_label.text())

    def test_fbx_task_without_any_animation_is_reported_as_a_failure(self):
        path, _animation, engine, factory = self.fbx_import_fixture()
        factory.buildImportTask.return_value.get_editor_property.return_value = []
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.assertFalse(self.ui.importActionFile(str(path)))
        self.assertIn('未生成动画序列', self.ui.msg_label.text())

    def test_native_exception_with_current_task_output_is_saved_and_counted_as_warning(self):
        path, animation, engine, factory = self.fbx_import_fixture()
        factory.executeImportTasks.side_effect = RuntimeError('Unable to retrieve bone index for track: FaceJoint')
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.ui.importActionFiles([str(path)])
        self.assertEqual(results[0]['items'][0]['state'], 'warning')
        engine.EditorAssetLibrary.save_asset.assert_called_once()
        self.assertIn('成功 1（其中警告 1）', self.warning.call_args.args[2])
        self.assertIn('失败 0', self.warning.call_args.args[2])
        self.assertIn('FaceJoint', results[0]['items'][0]['message'])

    def test_existing_asset_without_any_current_task_output_cannot_claim_success(self):
        path, _animation, engine, factory = self.fbx_import_fixture()
        factory.executeImportTasks.side_effect = SystemError('returned NULL without setting an exception')
        factory.buildImportTask.return_value.get_editor_property.return_value = []
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.assertFalse(self.ui.importActionFile(str(path)))
        engine.load_asset.assert_called_once_with('/Game/Assets/Characters/BaSiTeV4/BaSiTeV4_Skeleton')
        engine.EditorAssetLibrary.save_asset.assert_not_called()
        self.assertIn('本次导入任务未返回动画输出', self.ui.msg_label.text())

    def test_task_object_is_valid_proof_even_if_its_path_array_is_empty(self):
        path, animation, engine, factory = self.fbx_import_fixture()
        factory.buildImportTask.return_value.get_editor_property.return_value = []
        factory.buildImportTask.return_value.get_objects.return_value = [animation]
        factory.executeImportTasks.side_effect = RuntimeError('native import warning')
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.assertTrue(self.ui.importActionFile(str(path)))
        engine.EditorAssetLibrary.save_asset.assert_called_once()
        self.assertIn('已导入并保存', self.ui.msg_label.text())

    def test_batch_save_failure_is_reported_separately_as_unsaved(self):
        path, _animation, engine, factory = self.fbx_import_fixture()
        engine.EditorAssetLibrary.save_asset.return_value = False
        results = []
        self.ui._action_batch.finished.connect(results.append)
        with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
            self.ui.importActionFiles([str(path)])
        self.assertEqual(results[0]['items'][0]['state'], 'unsaved')
        self.assertIn('未保存 1', self.warning.call_args.args[2])
        self.assertIn('失败 0', self.warning.call_args.args[2])

    def test_empty_animation_keys_and_wrong_skeleton_fail_validation_before_save(self):
        for invalid in ('empty_keys', 'wrong_skeleton'):
            path, _animation, engine, factory = self.fbx_import_fixture()
            if invalid == 'empty_keys':
                engine.AnimationLibrary.get_num_keys.return_value = 0
            else:
                _animation.get_editor_property.return_value.get_path_name.return_value = '/Game/Other_Skeleton.Other_Skeleton'
            with mock.patch.object(assetTools, 'unreal', engine), mock.patch.object(assetTools.assetFunctions, 'AssetFunctions', return_value=factory):
                self.assertFalse(self.ui.importActionFile(str(path)))
            engine.EditorAssetLibrary.save_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
