"""Bridge prerequisite copying, missing-release detection and shared FBX import."""

import base64
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import unreal
except ImportError:
    unreal = types.ModuleType("unreal")
    sys.modules["unreal"] = unreal

from AssetsManagerForUE.sources import asset_fbx_service, maya_bridge_service, ue_asset_service


class Skeleton:
    pass


class MayaBridgeRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="maya_bridge_recovery_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.server = self.root / "Server"
        self.asset = self.server / "GOF/Assets/Props/Yu015QiePian"
        self.asset.mkdir(parents=True)
        self.content = self.root / "Project/Content"
        self.relative = "Assets/Props/Yu015QiePian/Yu015QiePian_Skeleton.uasset"
        self.request = {"project_name": "GOF", "asset_type": "Props", "asset_name": "Yu015QiePian",
                        "skeleton_path": "/Game/Assets/Props/Yu015QiePian/Yu015QiePian_Skeleton.Yu015QiePian_Skeleton"}
        self.engine = types.SimpleNamespace(Skeleton=Skeleton, log_warning=mock.Mock(),
                                             load_asset=mock.Mock(return_value=Skeleton()), ScopedSlowTask=mock.MagicMock(),
                                             EditorAssetLibrary=mock.Mock())
        self.engine.ScopedSlowTask.return_value.__enter__.return_value.should_cancel.return_value = False
        for patcher in (
            mock.patch.object(maya_bridge_service, "unreal", self.engine),
            mock.patch.object(maya_bridge_service, "commonSetting", return_value={"rootPath": str(self.server)}),
            mock.patch.object(ue_asset_service, "_project_content_dir", return_value=str(self.content)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.refresh = mock.patch.object(ue_asset_service, "refresh_asset_registry",
                                         side_effect=lambda plan, **kwargs: dict(plan, state="ready")).start()
        self.addCleanup(mock.patch.stopall)

    def release(self):
        package = self.asset / "UE/Content" / self.relative
        package.parent.mkdir(parents=True)
        package.write_bytes(b"published skeleton package")
        return package

    def test_source_path_uses_message_project_type_name_and_shared_root(self):
        result = maya_bridge_service.recover_asset("describe", self.request)
        self.assertEqual(result["asset_root"], self.asset.as_posix())
        self.assertEqual(result["status"], "ready")

    def test_no_ue_empty_ue_and_sidecar_only_are_explicitly_unavailable(self):
        for mode in ("absent", "empty", "sidecars"):
            if mode != "absent":
                folder = self.asset / "UE/Content"
                folder.mkdir(parents=True, exist_ok=True)
                if mode == "sidecars":
                    (folder / "Only.uexp").write_bytes(b"no main package")
            result = maya_bridge_service.recover_asset("load", self.request)
            self.assertEqual(result["status"], "missing_ue", mode)
            self.assertFalse(self.content.exists())

    def test_published_asset_is_copied_registered_and_skeleton_checked(self):
        package = self.release()
        result = maya_bridge_service.recover_asset("load", self.request)
        self.assertEqual(result["status"], "ready")
        self.assertEqual((self.content / self.relative).read_bytes(), package.read_bytes())
        self.refresh.assert_called_once()
        self.assertEqual(self.refresh.call_args.kwargs, {"require_placeable": False})
        self.engine.load_asset.assert_called_once_with(self.request["skeleton_path"])

    def test_same_existing_release_is_registered_without_copying(self):
        package = self.release()
        target = self.content / self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(package.read_bytes())
        with mock.patch.object(maya_bridge_service, "_copy_asset") as copy:
            self.assertEqual(maya_bridge_service.recover_asset("load", self.request)["status"], "ready")
        copy.assert_not_called()

    def test_conflicting_existing_files_are_kept_and_registered(self):
        self.release()
        target = self.content / self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"user version")
        with mock.patch.object(maya_bridge_service, "_copy_asset") as copy:
            result = maya_bridge_service.recover_asset("load", self.request)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(target.read_bytes(), b"user version")
        copy.assert_not_called()
        self.refresh.assert_called_once()

    def test_shared_material_conflict_keeps_project_version_and_copies_missing_skeleton(self):
        skeleton = self.release()
        relative = "Assets/MasterMaterial/Textures/black.uasset"
        material = self.asset / "UE/Content" / relative
        material.parent.mkdir(parents=True)
        material.write_bytes(b"source material")
        existing = self.content / relative
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"X" * material.stat().st_size)
        before = existing.stat().st_mtime_ns

        result = maya_bridge_service.recover_asset("load", self.request)

        self.assertEqual(result["status"], "ready")
        self.assertEqual((self.content / self.relative).read_bytes(), skeleton.read_bytes())
        self.assertEqual(existing.read_bytes(), b"X" * material.stat().st_size)
        self.assertEqual(existing.stat().st_mtime_ns, before)
        registered_plan = self.refresh.call_args.args[0]
        self.assertIn(relative, registered_plan["kept_existing_files"])
        self.assertEqual(registered_plan["overwritten_files"], [])
        self.assertEqual(registered_plan["created_files"], [(self.content / self.relative).as_posix()])
        self.assertFalse(list(self.content.rglob("*.cgtools_*")))
        self.engine.load_asset.assert_called_once_with(self.request["skeleton_path"])

    def test_kept_conflicts_still_require_the_expected_skeleton(self):
        self.release()
        target = self.content / self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"user version")
        self.engine.load_asset.return_value = None
        with self.assertRaisesRegex(RuntimeError, "仍未找到指定骨架"):
            maya_bridge_service.recover_asset("load", self.request)
        self.assertEqual(target.read_bytes(), b"user version")
        self.refresh.assert_called_once()

    def test_copy_failure_rolls_back_and_does_not_register(self):
        self.release()
        with mock.patch.object(ue_asset_service, "_replace_with_retry", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                maya_bridge_service.recover_asset("load", self.request)
        self.assertFalse((self.content / self.relative).exists())
        self.refresh.assert_not_called()

    def test_copied_files_without_expected_skeleton_do_not_report_success(self):
        self.release()
        self.engine.load_asset.return_value = None
        with self.assertRaisesRegex(RuntimeError, "仍未找到指定骨架"):
            maya_bridge_service.recover_asset("load", self.request)

    def test_inaccessible_asset_is_not_mislabeled_as_no_ue(self):
        self.asset.rmdir()
        with self.assertRaises(FileNotFoundError):
            maya_bridge_service.recover_asset("load", self.request)

    def test_fallback_runs_the_shared_import_fbx_operation_and_rechecks_skeleton(self):
        with mock.patch.object(asset_fbx_service, "import_asset", return_value={"destination": "/Game/Assets/Props/Yu015QiePian"}) as importer:
            result = maya_bridge_service.recover_asset("import_fbx", self.request)
        importer.assert_called_once_with(self.asset.as_posix(), "Props", "Yu015QiePian")
        self.assertEqual(result["status"], "ready")
        self.refresh.assert_not_called()
        self.engine.load_asset.assert_called_once_with(self.request["skeleton_path"])

    def test_invalid_path_components_are_rejected(self):
        for name in ("../Other", "A/B", "A\\B", "", "C:"):
            with self.assertRaises(ValueError):
                maya_bridge_service.asset_context(dict(self.request, asset_name=name))

    def test_encoded_errors_reach_native_caller_with_the_actual_reason(self):
        payload = base64.b64encode(json.dumps(self.request).encode()).decode()
        with mock.patch.object(asset_fbx_service, "import_asset", side_effect=OSError("找不到资产 FBX")):
            encoded = maya_bridge_service.invoke("import_fbx", payload)
        result = json.loads(base64.b64decode(encoded))
        self.assertEqual(result["status"], "error")
        self.assertIn("找不到资产 FBX", result["message"])


class SharedFbxImportTests(unittest.TestCase):
    def test_import_uses_existing_skeletal_options_and_moves_materials_inside_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "FBX").mkdir()
            (root / "FBX/Hero.fbx").write_bytes(b"fbx")
            functions = mock.Mock()
            task = functions.buildImportTask.return_value
            task.get_editor_property.return_value = ["/Game/Assets/Characters/Hero/Hero.Hero"]
            library = mock.Mock()
            library.does_directory_exist.return_value = False
            material = mock.Mock()
            material.get_class.return_value.get_name.return_value = "Material"
            material.get_name.return_value = "Skin"
            material.get_path_name.return_value = "/Game/Assets/Characters/Hero/Skin.Skin"
            library.list_assets.return_value = [material.get_path_name()]
            library.find_asset_data.return_value.get_asset.return_value = material
            with mock.patch.object(asset_fbx_service.assetFunctions, "AssetFunctions", return_value=functions), \
                    mock.patch.object(asset_fbx_service, "unreal", types.SimpleNamespace(EditorAssetLibrary=library)):
                result = asset_fbx_service.import_asset(str(root), "Characters", "Hero")
            functions.buildImportTask.assert_called_once_with((root / "FBX/Hero.fbx").as_posix(),
                "/Game/Assets/Characters/Hero", functions.buildSkeletalMeshImportOptions.return_value)
            functions.executeImportTasks.assert_called_once_with([task])
            library.rename_asset.assert_called_once_with(material.get_path_name(), "/Game/Assets/Characters/Hero/Material/Skin.Skin")
            self.assertEqual(result["destination"], "/Game/Assets/Characters/Hero")

    def test_missing_asset_fbx_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(FileNotFoundError, "找不到资产 FBX"):
                asset_fbx_service.import_asset(root, "Props", "Yu015QiePian")


if __name__ == "__main__":
    unittest.main()
