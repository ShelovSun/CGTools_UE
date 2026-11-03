"""Isolated adapter checks. Never launch Maya or write production data."""

import base64
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


class Animation:
    def get_name(self):
        return "待发布_Idle"

    def get_path_name(self):
        return "/Game/Test/待发布_Idle.待发布_Idle"


class SlowTask:
    def __init__(self, *args):
        self.cancel = False
        self.dialog = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def make_dialog(self, can_cancel):
        self.dialog = can_cancel

    def enter_progress_frame(self, *args):
        pass

    def should_cancel(self):
        return self.cancel


class PublisherMayaTests(unittest.TestCase):
    def setUp(self):
        self.asset = Animation()
        self.temp = tempfile.TemporaryDirectory(prefix="publisher_maya_test_")
        self.root = Path(self.temp.name)
        self.generated = self.root / "generated.ma"
        self.generated.write_bytes(b"//Maya ASCII 2022 scene\n// isolated baked fixture\n")
        self.destination = self.root / "Hero_自定义动作.ma"
        self.unreal = types.ModuleType("unreal")
        self.unreal.AnimSequence = Animation
        self.unreal.load_asset = mock.Mock(return_value=self.asset)
        self.unreal.log = mock.Mock()
        self.unreal.log_warning = mock.Mock()
        self.unreal.log_error = mock.Mock()
        self.unreal.ScopedSlowTask = SlowTask
        self.unreal.EditorUtilityLibrary = types.SimpleNamespace(
            get_selected_assets=mock.Mock(side_effect=AssertionError("Selection must not be queried"))
        )
        self.modules = mock.patch.dict(sys.modules, {"unreal": self.unreal})
        self.modules.start()
        path = Path(__file__).resolve().parents[1] / "Content/Python/cgtools_publisher_maya.py"
        spec = importlib.util.spec_from_file_location("publisher_maya_test_runtime", path)
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)

    def tearDown(self):
        self.modules.stop()
        self.temp.cleanup()

    def invoke(self, **overrides):
        request = {"operation": "bake", "object_path": self.asset.get_path_name(), "output_ma": str(self.destination)}
        request.update(overrides)
        encoded = base64.b64encode(json.dumps(request, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return json.loads(base64.b64decode(self.adapter.invoke(encoded)).decode("utf-8"))

    def success_result(self):
        return {"progress_result": {"status": "completed", "succeeded_jobs": 1},
                "jobs": [{"object_path": self.asset.get_path_name(), "output_scene": str(self.generated)}]}

    def fake_handoff(self, result):
        handoff = types.SimpleNamespace()

        def run(mode):
            self.assertEqual(mode, "bake")
            self.assertEqual(handoff.selected_source_assets(anim_only=True), [self.asset])
            return result

        handoff.run = run
        handoff.launch_bake_worker = mock.Mock(side_effect=AssertionError("Unexpected worker launch"))
        return handoff

    def test_current_animation_unicode_transport(self):
        handoff = self.fake_handoff(self.success_result())
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff), mock.patch.object(
            self.adapter.subprocess, "Popen", side_effect=AssertionError("Baking must not open Maya")
        ):
            self.assertTrue(self.invoke()["ok"])
        self.assertEqual(self.destination.read_bytes(), self.generated.read_bytes())
        self.unreal.load_asset.assert_called_once_with(self.asset.get_path_name())
        self.unreal.EditorUtilityLibrary.get_selected_assets.assert_not_called()

    def test_missing_share_is_clear(self):
        with mock.patch.object(self.adapter.os.path, "isfile", return_value=False):
            result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertIn("无法读取", result["message"])
        self.assertIn("fznas.diandian.info", result["message"])

    def test_wrong_or_unloadable_asset_never_loads_shared_code(self):
        with mock.patch.object(self.adapter, "_load_handoff_module") as loader:
            for asset in (None, object()):
                self.unreal.load_asset.return_value = asset
                self.assertFalse(self.invoke()["ok"])
            loader.assert_not_called()

    def test_cancel_failure_missing_result_and_false_success(self):
        for result, message in (
            ({"progress_result": {"status": "cancelled"}}, "安全取消"),
            ({"progress_result": {"status": "failed", "message": "找不到 mayapy"}}, "找不到 mayapy"),
            ({"progress_result": {"status": "completed", "succeeded_jobs": 0}}, "未完成"),
            ({"progress_result": {"status": "completed", "succeeded_jobs": 1}, "ue_export_errors": ["Rig 缺失"]}, "Rig 缺失"),
            (None, "没有返回结果"),
        ):
            with self.subTest(result=result), mock.patch.object(
                self.adapter, "_load_handoff_module", return_value=self.fake_handoff(result)
            ):
                response = self.invoke()
                self.assertFalse(response["ok"])
                self.assertIn(message, response["message"])
                self.assertFalse(self.destination.exists())

    def test_load_or_worker_exception_is_returned(self):
        with mock.patch.object(self.adapter, "_load_handoff_module", side_effect=RuntimeError("共享脚本接口变化")):
            self.assertIn("共享脚本接口变化", self.invoke()["message"])
        handoff = self.fake_handoff(None)
        handoff.run = mock.Mock(side_effect=RuntimeError("Worker 崩溃"))
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff):
            self.assertIn("Worker 崩溃", self.invoke()["message"])

    def test_registry_reads_custom_install_and_tolerates_inaccessible_keys(self):
        registry = types.SimpleNamespace(
            HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
            KEY_WOW64_64KEY=256, KEY_WOW64_32KEY=512, KEY_READ=1,
        )

        def open_key(hive, path, reserved, access):
            self.assertEqual(path, r"SOFTWARE\Autodesk\Maya\2022\Setup\InstallPath")
            if hive == registry.HKEY_LOCAL_MACHINE:
                raise PermissionError("isolated registry denial")
            if access != registry.KEY_READ | registry.KEY_WOW64_32KEY:
                raise FileNotFoundError("isolated empty registry view")
            return contextlib.nullcontext("custom Maya key")

        registry.OpenKey = mock.Mock(side_effect=open_key)
        registry.QueryValueEx = mock.Mock(return_value=("D:\\美术工具\\Autodesk\\Maya2022\\", 1))
        with mock.patch.dict(sys.modules, {"winreg": registry}):
            self.assertEqual(self.adapter._registry_maya_locations(), ["D:\\美术工具\\Autodesk\\Maya2022\\"])
        registry.QueryValueEx.assert_called_once_with("custom Maya key", "MAYA_INSTALL_LOCATION")
        self.assertEqual(registry.OpenKey.call_count, 6)

    def test_common_paths_only_probe_maya_2022_on_fixed_local_drives(self):
        kernel = types.SimpleNamespace(
            GetLogicalDrives=lambda: sum(1 << (ord(letter) - ord("A")) for letter in "CDY"),
            GetDriveTypeW=lambda path: 4 if path.value.startswith("Y:") else 3,
        )
        ctypes = types.SimpleNamespace(
            windll=types.SimpleNamespace(kernel32=kernel),
            c_wchar_p=lambda value: types.SimpleNamespace(value=value),
        )
        with mock.patch.dict(sys.modules, {"ctypes": ctypes}), mock.patch.object(self.adapter.os, "name", "nt"):
            locations = self.adapter._common_maya_locations()
        self.assertIn(os.path.join("D:/", "Program Files/Autodesk/Maya2022"), locations)
        self.assertFalse(any(path.startswith("Y:") for path in locations))
        self.assertTrue(all(path.endswith("Maya2022") for path in locations))

    def maya_environment(self, settings=None, registered=(), common=(), complete=(), partial=()):
        """Fake installations without accessing another drive or starting Maya."""
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        handoff = types.SimpleNamespace(
            read_settings=lambda: settings or {},
            SETTINGS_FILE_PATH="isolated/ue57_adv_retarget_handoff_settings.json",
        )
        exists = self.adapter.os.path.isfile
        programs = {os.path.normcase(os.path.join(path, name))
                    for path in complete for name in ("maya.exe", "mayapy.exe")}
        programs.update(os.path.normcase(path) for path in partial)
        stack.enter_context(mock.patch.dict(os.environ, {"MAYA_LOCATION": ""}))
        stack.enter_context(mock.patch.object(self.adapter, "_registry_maya_locations", return_value=list(registered)))
        stack.enter_context(mock.patch.object(self.adapter, "_common_maya_locations", return_value=list(common)))
        # Keep actual temp fixtures readable, but block real workstation Maya.
        stack.enter_context(mock.patch.object(
            self.adapter.os.path, "isfile",
            side_effect=lambda path: os.path.normcase(path) in programs
            or (str(path).startswith(str(self.root)) and exists(path)),
        ))
        handoff._find_maya_program = self.adapter._make_maya_finder(handoff)
        return handoff

    def test_registry_custom_drive_is_used_for_worker_and_visible_maya(self):
        root = os.path.normpath("D:/Pipeline Tools/美术/Maya2022")
        directory = os.path.join(root, "bin")
        handoff = self.maya_environment(registered=[root], complete=[directory])
        self.assertEqual(handoff._find_maya_program("mayapy.exe"), os.path.join(directory, "mayapy.exe"))
        # The visible launch uses the same resolver, and never runs another bake.
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff), mock.patch.object(
            self.adapter.subprocess, "Popen"
        ) as launch:
            response = self.invoke(operation="open_scene", scene_ma=str(self.generated))
        self.assertTrue(response["ok"], response["message"])
        self.assertEqual(launch.call_args.args[0], [os.path.join(directory, "maya.exe"), "-file", str(self.generated)])
        self.unreal.log.assert_called_once()

    def test_explicit_settings_accept_root_bin_or_executable_and_keep_precedence(self):
        root = os.path.normpath("D:/Custom Maya/Maya2022")
        directory = os.path.join(root, "bin")
        fallback = os.path.normpath("C:/Program Files/Autodesk/Maya2022")
        handoff = self.maya_environment(registered=[fallback], complete=[directory, os.path.join(fallback, "bin")])
        for value in (root, directory, directory + os.sep, '"' + directory + '"',
                      os.path.join(directory, "maya.exe"), os.path.join(directory, "mayapy.exe")):
            with self.subTest(value=value):
                handoff.read_settings = lambda: {"maya_location": value}
                finder = self.adapter._make_maya_finder(handoff)
                self.assertEqual(finder("maya.exe"), os.path.join(directory, "maya.exe"))
        handoff.read_settings = lambda: {"maya_location": "D:/Removed/Maya2022"}
        with mock.patch.dict(os.environ, {"MAYA_LOCATION": root}):
            finder = self.adapter._make_maya_finder(handoff)
            self.assertEqual(finder("mayapy.exe"), os.path.join(directory, "mayapy.exe"))

    def test_stale_or_partial_installs_fall_back_without_mixing_programs(self):
        incomplete = os.path.normpath("C:/Autodesk/Maya2022/bin")
        another = os.path.normpath("E:/Autodesk/Maya2022/bin")
        complete_root = os.path.normpath("D:/Autodesk/Maya2022")
        directory = os.path.join(complete_root, "bin")
        handoff = self.maya_environment(
            registered=["D:/Removed/Maya2022", os.path.dirname(incomplete), os.path.dirname(another)],
            common=[complete_root], complete=[directory],
            partial=[os.path.join(incomplete, "maya.exe"), os.path.join(another, "mayapy.exe")],
        )
        self.assertEqual(handoff._find_maya_program("maya.exe"), os.path.join(directory, "maya.exe"))
        self.assertEqual(handoff._find_maya_program("mayapy.exe"), os.path.join(directory, "mayapy.exe"))

    def test_missing_install_reports_checked_paths_and_repair_setting(self):
        directory = os.path.normpath("D:/Autodesk/Maya2022/bin")
        handoff = self.maya_environment(
            registered=[os.path.dirname(directory)], partial=[os.path.join(directory, "maya.exe")],
        )
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff), mock.patch.object(
            self.adapter.subprocess, "Popen"
        ) as launch:
            response = self.invoke(operation="open_scene", scene_ma=str(self.generated))
        self.assertFalse(response["ok"])
        for detail in (directory, "缺少 mayapy.exe", "MAYA_LOCATION", "maya_location", handoff.SETTINGS_FILE_PATH):
            self.assertIn(detail, response["message"])
        launch.assert_not_called()

    def test_real_shared_workflow_bakes_single_archive_without_opening(self):
        # Read the actual shared code, but replace FBX exports and the process
        # boundary. All manifests, rig fixtures and reports stay in a temp dir.
        handoff = self.adapter._load_handoff_module()
        exports = []
        manifests = []
        mesh = types.SimpleNamespace(get_path_name=lambda: "/Game/Test/Hero.Hero")
        maya_root = os.path.normpath("D:/Custom Maya/Maya2022")
        maya_bin = os.path.join(maya_root, "bin")
        original_isfile = os.path.isfile
        with tempfile.TemporaryDirectory(prefix="publisher_maya_") as root:
            root = Path(root)
            character = root / "Hero"
            (character / "FBX").mkdir(parents=True)
            (character / "Rig").mkdir()
            (character / "Rig/Hero_hi_rig.ma").write_text("isolated rig fixture", encoding="utf-8")
            mapping = character / "Hero_adv_retarget_mapping.json"
            mapping.write_text('{"fixture": true}', encoding="utf-8")

            def export(asset, destination):
                exports.append(asset)
                Path(destination).write_bytes(b"isolated FBX fixture")

            def launch(manifest_path, reports_dir):
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                manifests.append(manifest)
                self.assertEqual(handoff._find_maya_program("mayapy.exe"), os.path.join(maya_bin, "mayapy.exe"))
                Path(manifest["jobs"][0]["output_scene"]).write_bytes(self.generated.read_bytes())
                return object(), {"pid": 123, "log_path": str(Path(reports_dir) / "worker.log")}

            state = {"status": "completed", "succeeded_jobs": 1, "failed_jobs": 0}
            with mock.patch.multiple(
                handoff,
                read_settings=lambda: {"out_root": str(root / "Output")},
                get_preview_mesh=lambda asset: mesh,
                get_asset_import_source_file=lambda asset: str(character / "FBX/Hero.fbx"),
                get_skeleton_path=lambda asset: "/Game/Test/Hero_Skeleton.Hero_Skeleton",
                export_asset_to_fbx=export,
                launch_bake_worker=launch,
                _monitor_bake_worker=lambda *args: state,
            ), mock.patch.dict(os.environ, {"MAYA_LOCATION": ""}), mock.patch.object(
                self.adapter, "_registry_maya_locations", return_value=[maya_root]
            ), mock.patch.object(self.adapter, "_common_maya_locations", return_value=[]), mock.patch.object(
                self.adapter.os.path, "isfile", side_effect=lambda path:
                os.path.normcase(path) in {os.path.normcase(os.path.join(maya_bin, name)) for name in ("maya.exe", "mayapy.exe")}
                or original_isfile(path)
            ), mock.patch.object(handoff.subprocess, "Popen", side_effect=AssertionError("Must never launch Maya")), mock.patch.object(
                self.adapter, "_load_handoff_module", return_value=handoff
            ):
                result = self.invoke()
            self.assertTrue(result["ok"], result["message"])
            self.assertEqual(exports, [self.asset, mesh])
            self.assertEqual(len(manifests), 1)
            manifest = manifests[0]
            self.assertFalse(manifest["open_results"])
            self.assertEqual(manifest["mode"], "bake")
            self.assertEqual(manifest["maya_executable"], os.path.join(maya_bin, "maya.exe").replace("\\", "/"))
            self.assertEqual(len(manifest["jobs"]), 1)
            job = manifest["jobs"][0]
            self.assertEqual(job["object_path"], self.asset.get_path_name())
            self.assertEqual(job["asset_name"], self.asset.get_name())
            self.assertTrue(job["manual_mapping_present"])
            self.assertTrue(job["manual_mapping_sha256"])
            self.assertEqual(job["rig_scene"], str(character / "Rig/Hero_hi_rig.ma").replace("\\", "/"))
            self.assertIn("结果目录", result["message"])
            self.assertEqual(self.destination.read_bytes(), self.generated.read_bytes())
            self.unreal.EditorUtilityLibrary.get_selected_assets.assert_not_called()

    def test_missing_or_invalid_maya_output_cannot_report_success(self):
        for content in (None, b"", b"not a Maya scene"):
            with self.subTest(content=content):
                if content is None:
                    self.generated.unlink(missing_ok=True)
                else:
                    self.generated.write_bytes(content)
                with mock.patch.object(self.adapter, "_load_handoff_module", return_value=self.fake_handoff(self.success_result())):
                    self.assertFalse(self.invoke()["ok"])
                self.assertFalse(self.destination.exists())

    def test_wrong_animation_result_cannot_publish_another_scene(self):
        result = self.success_result()
        result["jobs"][0]["object_path"] = "/Game/Other.Other"
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=self.fake_handoff(result)):
            self.assertIn("不一致", self.invoke()["message"])
        self.assertFalse(self.destination.exists())

    def test_copy_failure_keeps_baked_archive_and_reports_failure(self):
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=self.fake_handoff(self.success_result())), mock.patch.object(
            self.adapter.shutil, "copyfile", side_effect=OSError("本地暂存写入失败")
        ):
            result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertIn("本地暂存写入失败", result["message"])
        self.assertTrue(self.generated.exists())

    def test_explicit_open_uses_published_filename_without_rebaking(self):
        handoff = types.SimpleNamespace(_find_maya_program=mock.Mock(return_value="isolated/maya.exe"), run=mock.Mock())
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff), mock.patch.object(
            self.adapter.subprocess, "Popen"
        ) as launch:
            result = self.invoke(operation="open_scene", scene_ma=str(self.generated))
        self.assertTrue(result["ok"])
        self.assertEqual(launch.call_args.args[0][:2], ["isolated/maya.exe", "-file"])
        self.assertEqual(Path(launch.call_args.args[0][2]).resolve(), self.generated.resolve())
        handoff.run.assert_not_called()

    def test_corrupted_staging_copy_is_rejected(self):
        def corrupt_copy(source, destination):
            Path(destination).write_bytes(b"truncated transfer")

        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=self.fake_handoff(self.success_result())), mock.patch.object(
            self.adapter.shutil, "copyfile", side_effect=corrupt_copy
        ):
            result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertIn("校验失败", result["message"])
        self.assertTrue(self.generated.exists())

    def test_missing_scene_or_maya_does_not_launch(self):
        handoff = types.SimpleNamespace(_find_maya_program=lambda name: "")
        with mock.patch.object(self.adapter, "_load_handoff_module", return_value=handoff), mock.patch.object(
            self.adapter.subprocess, "Popen"
        ) as launch:
            self.assertFalse(self.invoke(operation="open_scene", scene_ma=str(self.root / "missing.ma"))["ok"])
            self.assertIn("找不到 Maya", self.invoke(operation="open_scene", scene_ma=str(self.generated))["message"])
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
