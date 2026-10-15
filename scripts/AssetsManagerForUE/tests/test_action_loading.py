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

from PySide6 import QtWidgets
from AssetsManagerForUE.sources import action_service, ue_asset_service
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
            EditorLoadingAndSavingUtils=mock.Mock(), find_object=mock.Mock(return_value=None))
        self.animation = mock.Mock()
        self.animation.get_name.return_value = "BaSiTeV4_Walk"
        self.animation.get_path_name.return_value = self.context["package_name"] + ".BaSiTeV4_Walk"
        self.engine.EditorAssetLibrary.load_asset.return_value = self.animation
        self.engine.AssetRegistryHelpers.create_asset_data.return_value.is_u_asset.return_value = True
        for patcher in (
            mock.patch.object(ue_asset_service, "unreal", self.engine),
            mock.patch.object(ue_asset_service, "_project_content_dir", return_value=str(self.content)),
            mock.patch.object(ue_asset_service, "sync_to_content_browser", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.question_patch = mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No)
        self.question = self.question_patch.start()
        self.addCleanup(self.question_patch.stop)
        self.warning_patch = mock.patch.object(QtWidgets.QMessageBox, "warning")
        self.warning = self.warning_patch.start()
        self.addCleanup(self.warning_patch.stop)
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
        self.ui.loadActionFile(str(self.source))
        self.warning.assert_called_once()
        self.assertEqual(self.target.read_bytes(), old)
        self.assertIsNone(self.ui._copy_thread)

    def test_identical_existing_file_is_registered_without_another_copy(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.source.read_bytes())
        with mock.patch.object(ue_asset_service, "AssetCopyWorker") as copy_worker:
            self.ui.loadActionFile(str(self.source))
        copy_worker.assert_not_called()
        self.warning.assert_not_called()
        self.registry.scan_files_synchronous.assert_called_once()

    def test_missing_skeleton_is_reported_instead_of_claiming_the_animation_loaded(self):
        self.engine.EditorAssetLibrary.load_asset.return_value.get_editor_property.return_value = None
        self.ui.loadActionFile(str(self.source))
        self.wait_finished()
        self.warning.assert_called_once()
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


if __name__ == "__main__":
    unittest.main()
