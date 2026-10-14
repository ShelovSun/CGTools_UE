"""Every database entry point takes its host from the shared configuration."""

import importlib.util
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
try:
    import unreal
except ImportError:
    unreal = types.ModuleType("unreal")
    unreal.log_warning = lambda text: None
    sys.modules["unreal"] = unreal

from AssetsManagerForUE import config
from AssetsManagerForUE.sources import assetTools, sceneTools, asset_backend

workspace = Path(__file__).resolve().parents[5]
publisher_path = workspace / "UE574/Plugins/Marketplace/CGToolsPublisher/Content/Python/cgtools_publisher_db.py"
publisher_spec = importlib.util.spec_from_file_location("publisher_db_host_checks", publisher_path)
publisher = importlib.util.module_from_spec(publisher_spec)
publisher_spec.loader.exec_module(publisher)


class DatabaseHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="database_host_")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "commonSetting.json"
        self.settings = {
            "DataBase": ["Project"], "rootPath": "Y:/MCCProject", "type": ["Characters"],
            "host": "smnas.diandian.info",
        }
        self.write_settings()
        for patcher in (
                mock.patch.object(config, "commonSettingPath", return_value=str(self.path)),
                mock.patch.object(config, "_COMMON_SETTING_CACHE", None),
                mock.patch.object(publisher, "_COMMON_SETTING_PATH", self.path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.connection = mock.Mock()
        self.connection.cursor.return_value.fetchall.return_value = []
        patcher = mock.patch.object(sceneTools.psycopg2, "connect", return_value=self.connection)
        self.connect = patcher.start()
        self.addCleanup(patcher.stop)

    def write_settings(self):
        self.path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")

    def assert_connection_host(self, expected="smnas.diandian.info"):
        self.assertEqual(self.connect.call_args.kwargs["host"], expected)
        self.assertEqual(self.connect.call_args.kwargs["port"], "5432")

    def test_host_is_trimmed_and_each_reader_uses_the_same_json(self):
        self.settings["host"] = "  smnas.diandian.info  "
        self.write_settings()
        self.assertEqual(config.databaseHost(), "smnas.diandian.info")
        self.assertEqual(publisher._database_host(), "smnas.diandian.info")

    def test_changed_json_takes_effect_even_after_general_settings_were_cached(self):
        config.commonSetting()
        self.settings["host"] = "changed-db.example.test"
        self.write_settings()
        self.assertEqual(config.databaseHost(), "changed-db.example.test")
        self.assertEqual(publisher._database_host(), "changed-db.example.test")
        self.assertEqual(config.commonSetting()["host"], "changed-db.example.test")

    def test_missing_empty_and_non_string_hosts_fail_instead_of_using_a_default(self):
        for value in (None, "", "  ", 123, False, []):
            with self.subTest(host=value):
                self.settings["host"] = value
                self.write_settings()
                for reader in (config.databaseHost, publisher._database_host):
                    with self.assertRaisesRegex(ValueError, "host"):
                        reader()
        del self.settings["host"]
        self.write_settings()
        with self.assertRaisesRegex(ValueError, "host"):
            config.databaseHost()

    def test_missing_or_invalid_json_does_not_reuse_a_cached_database_address(self):
        config.commonSetting()
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            config.databaseHost()
        with self.assertRaises(RuntimeError):
            publisher._database_host()
        self.path.write_text("{invalid json", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            config.databaseHost()
        with self.assertRaises(RuntimeError):
            publisher._database_host()

    def test_asset_query_reads_config_before_connecting(self):
        self.assertEqual(assetTools._fetch_database("test-user", "test-password", "Project", "Characters"), [])
        self.assert_connection_host()
        self.connection.close.assert_called_once()

    def test_background_startup_and_later_query_both_use_shared_host(self):
        startup = assetTools._StartupTask("test-user", "test-password", True, 0, 0)
        failures = []
        payloads = []
        startup.signals.failed.connect(failures.append)
        startup.signals.loaded.connect(payloads.append)
        startup.run()
        self.assertEqual(failures, [])
        self.assertEqual(len(payloads), 1)
        self.assert_connection_host()
        self.settings["host"] = "changed-db.example.test"
        self.write_settings()
        query = assetTools._QueryTask(2, "test-user", "test-password", "Project", "Characters")
        query.signals.failed.connect(lambda generation, text: failures.append(text))
        query.run()
        self.assertEqual(failures, [])
        self.assert_connection_host("changed-db.example.test")

    def test_scene_query_reads_shared_host(self):
        ui = types.SimpleNamespace(user="test-user", password="test-password")
        self.assertEqual(sceneTools.SceneToolsUI.get_database(ui, "Project", "StaticMesh"), [])
        self.assert_connection_host()

    def test_native_asset_backend_reads_shared_host(self):
        with mock.patch.object(asset_backend, "_login", return_value=("test-user", "test-password")):
            self.assertEqual(asset_backend.query_assets("Project", "Characters"), [])
        self.assert_connection_host()

    def test_publisher_reads_json_instead_of_stale_payload_host(self):
        with mock.patch.object(publisher, "_credentials", return_value=("test-user", "test-password")):
            connection, user = publisher._connect({"project": "Project", "host": "stale-db.example.test"})
        self.assertIs(connection, self.connection)
        self.assertEqual(user, "test-user")
        self.assert_connection_host()

    def test_bad_host_does_not_open_a_connection_in_any_database_entry_point(self):
        self.settings.pop("host")
        self.write_settings()
        with self.assertRaisesRegex(ValueError, "host"):
            assetTools._fetch_database("test-user", "test-password", "Project", "Characters")
        with mock.patch.object(asset_backend, "_login", return_value=("test-user", "test-password")):
            with self.assertRaisesRegex(ValueError, "host"):
                asset_backend.query_assets("Project", "Characters")
        with mock.patch("builtins.print"):
            ui = types.SimpleNamespace(user="test-user", password="test-password")
            self.assertIsNone(sceneTools.SceneToolsUI.get_database(ui, "Project", "StaticMesh"))
        with self.assertRaisesRegex(ValueError, "host"):
            publisher._connect({"project": "Project", "host": "stale-db.example.test"})
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
