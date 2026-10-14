"""UE browser/editor calls, including APIs that return no Python value."""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from AssetsManagerForUE.sources import ue_asset_service


class EditorActionTests(unittest.TestCase):
    def setUp(self):
        self.asset = object()
        self.registry = mock.Mock()
        self.registry.is_loading_assets.return_value = False
        self.library = mock.Mock()
        self.library.load_asset.return_value = self.asset
        # SyncBrowserToObjects is void in UE 5.7, not a boolean result.
        self.library.sync_browser_to_objects.return_value = None
        self.utility = mock.Mock()
        self.subsystem = mock.Mock(spec=["open_editor_for_assets"])
        self.subsystem.open_editor_for_assets.return_value = True
        self.engine = types.SimpleNamespace(
            EditorAssetLibrary=self.library,
            EditorUtilityLibrary=self.utility,
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: self.registry),
            AssetEditorSubsystem=object(),
            get_editor_subsystem=mock.Mock(return_value=self.subsystem),
        )
        self.patch = mock.patch.object(ue_asset_service, "unreal", self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.path = "/Game/VFX/Team1/火/NS_Hit.NS_Hit"

    def test_sync_focuses_folder_before_selecting_normalized_object_path(self):
        calls = mock.Mock()
        calls.attach_mock(self.utility.sync_browser_to_folders, "folder")
        calls.attach_mock(self.library.sync_browser_to_objects, "asset")
        self.assertTrue(ue_asset_service.sync_to_content_browser("Game/VFX/Team1/火/NS_Hit"))
        self.assertEqual(calls.mock_calls, [
            mock.call.folder(["/Game/VFX/Team1/火"]), mock.call.asset([self.path])])

    def test_loading_registry_returns_retryable_failure_without_syncing(self):
        self.registry.is_loading_assets.return_value = True
        self.assertFalse(ue_asset_service.sync_to_content_browser(self.path))
        self.library.load_asset.assert_not_called()
        self.utility.sync_browser_to_folders.assert_not_called()
        self.library.sync_browser_to_objects.assert_not_called()

    def test_sync_failure_does_not_report_success_or_raise(self):
        self.library.load_asset.return_value = None
        self.assertFalse(ue_asset_service.sync_to_content_browser(self.path))
        self.library.sync_browser_to_objects.assert_not_called()
        self.library.load_asset.return_value = self.asset
        self.library.sync_browser_to_objects.side_effect = RuntimeError("browser unavailable")
        self.assertFalse(ue_asset_service.sync_to_content_browser(self.path))

    def test_sync_without_optional_folder_api_keeps_object_sync(self):
        del self.engine.EditorUtilityLibrary
        self.assertTrue(ue_asset_service.sync_to_content_browser(self.path))
        self.library.sync_browser_to_objects.assert_called_once_with([self.path])

    def test_plan_sync_still_locates_existing_dependency_when_main_is_missing(self):
        dependency = "/Game/VFX/Team1/火/Mat/M_Hit.M_Hit"
        self.library.does_asset_exist.side_effect = [False, True]
        result = ue_asset_service.sync_plan_to_content_browser({
            "main_object_path": self.path, "package_object_paths": [self.path, dependency]})
        self.assertEqual(result, (True, dependency))
        self.library.sync_browser_to_objects.assert_called_once_with([dependency])

    def test_open_uses_exposed_plural_api_and_checks_success(self):
        self.assertEqual(ue_asset_service.open_asset_editor(self.path), (True, ""))
        self.engine.get_editor_subsystem.assert_called_once_with(self.engine.AssetEditorSubsystem)
        self.subsystem.open_editor_for_assets.assert_called_once_with([self.asset])

    def test_open_editor_declined_is_a_failure_with_resource_path(self):
        self.subsystem.open_editor_for_assets.return_value = False
        success, error = ue_asset_service.open_asset_editor(self.path)
        self.assertFalse(success)
        self.assertIn(self.path, error)

    def test_open_missing_asset_and_subsystem_errors_are_reported(self):
        self.library.load_asset.return_value = None
        success, error = ue_asset_service.open_asset_editor(self.path)
        self.assertFalse(success)
        self.assertIn("无法加载", error)
        self.subsystem.open_editor_for_assets.assert_not_called()
        self.library.load_asset.return_value = self.asset
        self.subsystem.open_editor_for_assets.side_effect = RuntimeError("editor unavailable")
        success, error = ue_asset_service.open_asset_editor(self.path)
        self.assertFalse(success)
        self.assertIn("editor unavailable", error)

    def test_no_engine_or_empty_path_does_not_attempt_editor_calls(self):
        self.assertFalse(ue_asset_service.sync_to_content_browser(""))
        self.assertFalse(ue_asset_service.open_asset_editor("")[0])
        with mock.patch.object(ue_asset_service, "unreal", None):
            self.assertFalse(ue_asset_service.sync_to_content_browser(self.path))
            self.assertFalse(ue_asset_service.open_asset_editor(self.path)[0])
        self.library.load_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
