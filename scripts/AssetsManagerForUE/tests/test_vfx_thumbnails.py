"""Thumbnail cache protocol, UE binding compatibility and non-blocking UI requests."""

import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if "unreal" not in sys.modules:
    sys.modules["unreal"] = types.ModuleType("unreal")

from PySide6 import QtWidgets
from AssetsManagerForUE.sources import ue_asset_service, vfx_thumbnail_cache, vfxTools


class VfxThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vfx_thumbnail_checks_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def asset(self, name):
        source = self.root / (name + ".uasset")
        source.write_bytes(b"unmodified source package")
        return {"source_file": str(source), "thumbnail": str(self.root / (name + ".png")),
                "no_thumbnail": str(self.root / (name + ".png.no_thumbnail"))}

    def worker(self, assets, export):
        job = self.root / "Job"
        job.mkdir(exist_ok=True)
        (job / "requests.json").write_text(json.dumps({
            "content_root": str(self.root), "assets": assets}), encoding="utf-8")
        fake = types.SimpleNamespace(CGToolsAssetBridgeLibrary=types.SimpleNamespace(
            export_external_vfx_thumbnail=export),
            SystemLibrary=types.SimpleNamespace(collect_garbage=lambda: None))
        script = Path(vfx_thumbnail_cache.__file__).with_name("vfx_thumbnail_worker.py")
        with mock.patch.dict(sys.modules, {"unreal": fake}), mock.patch.dict(
                os.environ, {"CGTOOLS_VFX_THUMBNAIL_JOB": str(job)}):
            spec = importlib.util.spec_from_file_location("vfx_worker_test", str(script))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.main(max_requests=len(assets))
        return [json.loads(line) for line in (job / "results.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_success_is_published_atomically_and_reused(self):
        asset = self.asset("旧特效")
        def export(source, root, destination):
            self.assertFalse(Path(asset["thumbnail"]).exists())
            Path(destination).write_bytes(b"generated PNG")
            return ""
        results = self.worker([asset], export)
        self.assertTrue(results[0]["success"])
        self.assertEqual(Path(asset["thumbnail"]).read_bytes(), b"generated PNG")
        self.assertEqual(vfx_thumbnail_cache.pending_assets([asset]), [])
        self.assertEqual(Path(asset["source_file"]).read_bytes(), b"unmodified source package")

    def test_missing_preview_is_negative_cached_but_io_errors_are_not(self):
        missing, offline = self.asset("NoImage"), self.asset("NetworkError")
        results = self.worker([missing, offline], lambda source, root, dest:
            "NO_THUMBNAIL|没有预览图" if source == missing["source_file"] else "ERROR|无法读取网络文件")
        self.assertFalse(any(result["success"] for result in results))
        self.assertTrue(Path(missing["no_thumbnail"]).exists())
        self.assertFalse(Path(offline["no_thumbnail"]).exists())
        self.assertEqual(vfx_thumbnail_cache.pending_assets([missing, offline]), [offline])

    def test_changed_source_never_gets_stale_positive_or_negative_cache(self):
        asset = self.asset("Changed")
        def export(source, root, destination):
            Path(source).write_bytes(b"updated package with different size")
            Path(destination).write_bytes(b"outdated PNG")
            return "NO_THUMBNAIL|没有预览图"
        result = self.worker([asset], export)[0]
        self.assertIn("读取期间", result["error"])
        self.assertFalse(Path(asset["thumbnail"]).exists())
        self.assertFalse(Path(asset["no_thumbnail"]).exists())

    def test_source_changed_since_scan_is_not_loaded(self):
        asset = self.asset("ChangedBeforeLoad")
        asset["source_signature"] = [0, 0]
        export = mock.Mock(return_value="")
        result = self.worker([asset], export)[0]
        export.assert_not_called()
        self.assertIn("服务器特效已更新", result["error"])

    def test_cache_key_changes_for_package_update_and_ignores_old_negative_cache(self):
        asset = self.asset("Fingerprint")
        old = vfxTools._thumbnail_paths(asset["source_file"])
        stat = Path(asset["source_file"]).stat()
        legacy_key = "{0}|{1}|{2}".format(os.path.normcase(os.path.abspath(asset["source_file"])),
                                          stat.st_size, stat.st_mtime_ns)
        self.assertEqual(Path(old[0]).stem, hashlib.sha1(legacy_key.encode("utf-8")).hexdigest())
        self.assertNotEqual(old[1], old[0] + ".no_thumbnail")
        Path(asset["source_file"]).write_bytes(b"new version of the package")
        self.assertNotEqual(old, vfxTools._thumbnail_paths(asset["source_file"]))

    def test_ue57_empty_string_result_means_success_only_if_png_exists(self):
        asset = self.asset("Binding")
        bridge = types.SimpleNamespace(export_external_asset_thumbnail=lambda src, dest: "")
        with mock.patch.object(ue_asset_service, "unreal", types.SimpleNamespace(CGToolsAssetBridgeLibrary=bridge)):
            self.assertFalse(ue_asset_service.export_external_asset_thumbnail(
                asset["source_file"], asset["thumbnail"])[0])
            Path(asset["thumbnail"]).write_bytes(b"PNG")
            self.assertTrue(ue_asset_service.export_external_asset_thumbnail(
                asset["source_file"], asset["thumbnail"])[0])

    def test_none_binding_result_reports_failure(self):
        bridge = types.SimpleNamespace(export_external_asset_thumbnail=lambda src, dest: None)
        with mock.patch.object(ue_asset_service, "unreal", types.SimpleNamespace(CGToolsAssetBridgeLibrary=bridge)):
            success, error = ue_asset_service.export_external_asset_thumbnail("missing.uasset", str(self.root / "missing.png"))
        self.assertFalse(success)
        self.assertIn("未生成缩略图", error)

    def test_helper_results_refresh_matching_card_and_no_image_is_quiet(self):
        cache = vfx_thumbnail_cache.VfxThumbnailCache(str(self.root))
        self.addCleanup(cache.stop)
        asset = self.asset("Ready")
        Path(asset["thumbnail"]).write_bytes(b"PNG")
        cache.job = self.root
        (self.root / "results.jsonl").write_text(json.dumps(dict(asset, success=True)) + "\n" +
            json.dumps(dict(self.asset("Absent"), success=False, error="NO_THUMBNAIL|empty")) + "\n", encoding="utf-8")
        ready, warnings = [], []
        cache.ready.connect(lambda source, png: ready.append((source, png)))
        cache.warning.connect(warnings.append)
        cache._readResults()
        cache._readResults()
        self.assertEqual(ready, [(asset["source_file"], asset["thumbnail"])])
        self.assertEqual(warnings, [])

    def test_partial_result_record_is_not_consumed_until_complete(self):
        cache = vfx_thumbnail_cache.VfxThumbnailCache(str(self.root))
        self.addCleanup(cache.stop)
        cache.job = self.root
        path = self.root / "results.jsonl"
        path.write_bytes(b'{"fatal":"restart required"}')
        cache._readResults()
        self.assertFalse(cache.disabled)
        self.assertEqual(cache.offset, 0)
        with path.open("ab") as stream:
            stream.write(b"\n")
        cache._readResults()
        self.assertTrue(cache.disabled)


if __name__ == "__main__":
    unittest.main()
