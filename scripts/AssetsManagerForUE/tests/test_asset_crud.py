"""Maya add/delete parity against local SQL/temp directories and real Qt dialogs."""

import os
import sqlite3
import sys
import tempfile
import threading
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
    sys.modules["unreal"] = types.ModuleType("unreal")

from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.sources import asset_crud_service as service
from AssetsManagerForUE.sources import asset_crud_ui as ui
from AssetsManagerForUE.sources import assetTools, sceneTools, status_edit_service
from AssetsManagerForUE.utils import myWidget


class LocalCursor:
    def __init__(self, database):
        self.cursor = database.cursor()

    def execute(self, query, values):
        self.cursor.execute(query.replace('public."', '"').replace("%s", "?"), values)

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()


class LocalConnection:
    def __init__(self, database):
        self.database = database
        self.commits = self.rollbacks = 0
        self.closed = False

    def commit(self):
        self.commits += 1
        self.database.commit()

    def rollback(self):
        self.rollbacks += 1
        self.database.rollback()

    def close(self):
        self.closed = True


class StatusPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.isSQL = True
        self.user, self.password = "user", "password"
        self.scope = ("Project", "Characters")
        self.messages = []
        self.main_listWgt = myWidget.MainQListWiget()
        self.main_listWgt.setItems([
            ("20261015", name, "角色", "模型制作人", "未开始", "绑定制作人", "制作中", "", "备注", "未开始", "")
            for name in ("Hero", "Other")])
        self.main_listWgt.addItems()
        self.editor = status_edit_service.StatusEditor(self, "asset", lambda: self.scope)
        self.editor.setContext(*self.scope)

    def infoMsg(self, icon, text):
        self.messages.append((icon, text))


class Cursor(LocalCursor):
    def execute(self, query, values):
        if "pg_advisory_xact_lock" not in query:
            super().execute(query, values)


class Connection(LocalConnection):
    def cursor(self):
        return Cursor(self.database)


class CrudDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "Project/Assets/Characters").mkdir(parents=True)
        (self.root / "Project/Scenes/Nature").mkdir(parents=True)
        self.settings = {"rootPath": str(self.root), "DataBase": ["Project"],
                         "type": ["Characters", "Props"], "host": "local.test"}
        self.enterContext(mock.patch.object(service, "commonSetting", return_value=self.settings))
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE asset (' + ','.join('"asset.' + col + '"' for col in
            service.ROW_FIELDS["asset"] + ("type",)) + ')')
        self.db.execute('CREATE TABLE scene (' + ','.join('"scene.' + col + '"' for col in
            ("date", "name", "zh_name", "artist", "status", "icon", "note", "type")) + ')')
        self.conn = Connection(self.db)
        self.connect = self.enterContext(mock.patch.object(service, "_connect", return_value=self.conn))

    def add(self, table="asset", name="Hero", zh="角色'中文名"):
        return service.add_record("artist", "secret", table, "Project",
                                  "Characters" if table == "asset" else "Nature", name, zh)

    def delete(self, result, table="asset"):
        return service.delete_record("artist", "secret", table, "Project", result["type"], result["row"])

    def test_asset_creation_database_defaults_and_all_directories(self):
        result = self.add()
        row = result["row"]
        self.assertEqual(row[1:7], ("Hero", "角色'中文名", "artist", "未开始", "", "未开始"))
        self.assertEqual(row[9:], ("未开始", ""))
        self.assertEqual(row[0], int(time.strftime("%Y%m%d")))
        folder = self.root / "Project/Assets/Characters/Hero"
        self.assertEqual(row[7], (folder / "Icon/Hero.png").as_posix())
        self.assertEqual({p.name for p in folder.iterdir()}, set(service.SUBFOLDERS["asset"]))
        self.assertTrue((self.root / "Project/Animations/Characters/Hero/Action").is_dir())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 1)
        self.assertEqual(self.conn.commits, 1)
        self.assertTrue(self.conn.closed)

    def test_scene_creation_has_matching_artist_status_columns_and_no_animation(self):
        result = self.add("scene", "Tree", "树")
        row = result["row"]
        self.assertEqual(row[3:7], ("artist", "未开始", "artist", "未开始"))
        folder = self.root / "Project/Scenes/Nature/Tree"
        self.assertEqual({p.name for p in folder.iterdir()}, set(service.SUBFOLDERS["scene"]))
        self.assertFalse((self.root / "Project/Animations").exists())
        self.assertEqual(self.delete(result, "scene")["folder"], str(folder))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM scene").fetchone()[0], 0)

    def test_duplicate_preserves_existing_record_files_and_date(self):
        self.add()
        icon = self.root / "Project/Assets/Characters/Hero/Icon/Hero.png"
        icon.write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.add(zh="覆盖")
        self.assertEqual(icon.read_bytes(), b"existing")
        self.assertEqual(self.db.execute('SELECT "asset.zh_name" FROM asset').fetchone()[0], "角色'中文名")
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_parameterized_quotes_and_sql_text(self):
        self.add(name="Hero's", zh="'; DROP TABLE asset;--")
        self.assertEqual(self.db.execute('SELECT "asset.name", "asset.zh_name" FROM asset').fetchone(),
                         ("Hero's", "'; DROP TABLE asset;--"))

    def test_case_only_name_cannot_create_second_record_for_same_windows_folder(self):
        self.add(name="Hero")
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.add(name="hero")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 1)

    def test_directory_failure_rolls_back_record_and_only_new_empty_directories(self):
        existing = self.root / "Project/Assets/Characters/Hero/Original"
        existing.mkdir(parents=True)
        original = existing / "original.ma"
        original.write_bytes(b"keep")
        mkdir = service._mkdir
        def failing(path, created):
            if path.endswith(os.sep + "Rig"):
                raise OSError("permission denied at Rig")
            mkdir(path, created)
        with mock.patch.object(service, "_mkdir", side_effect=failing):
            with self.assertRaisesRegex(OSError, "permission denied"):
                self.add()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 0)
        self.assertEqual(original.read_bytes(), b"keep")
        self.assertEqual({p.name for p in existing.parent.iterdir()}, {"Original"})
        self.assertEqual(self.conn.rollbacks, 1)

    def test_insert_failure_creates_no_directories(self):
        self.db.execute("CREATE TRIGGER deny BEFORE INSERT ON asset BEGIN SELECT RAISE(ABORT, 'denied'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "denied"):
            self.add()
        self.assertFalse((self.root / "Project/Assets/Characters/Hero").exists())

    def test_bad_names_unknown_project_and_missing_project_do_not_connect(self):
        for name in ("", "..", "../Other", "A/B", "A\\B", "A:stream", "NUL", "COM1.ma", "Hero.", " Hero", "A\x00B"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.add(name=name)
        with self.assertRaises(ValueError):
            service.add_record("a", "b", "asset", "Unknown", "Characters", "Hero", "")
        self.settings["DataBase"].append("Missing")
        with self.assertRaisesRegex(ValueError, "项目目录不存在"):
            service.add_record("a", "b", "asset", "Missing", "Characters", "Hero", "")
        self.connect.assert_not_called()

    def test_options_follow_projects_and_scene_directories_asset_fallback(self):
        self.settings["DataBase"].append("Other")
        (self.root / "Other/Scenes/Building").mkdir(parents=True)
        self.assertEqual(service.read_add_options("scene", "Other")["types"], ["Building"])
        self.assertEqual(service.read_add_options("scene", "Project")["types"], ["Nature"])
        self.assertEqual(service.read_add_options("asset", "Other")["types"], ["Characters", "Props"])

    def test_delete_database_then_folder_are_separate_and_animations_preserved(self):
        result = self.add()
        deleted = self.delete(result)
        folder = Path(deleted["folder"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 0)
        self.assertTrue(folder.is_dir())
        self.assertTrue(deleted["folder_exists"])
        service.delete_folder("asset", deleted)
        self.assertFalse(folder.exists())
        self.assertTrue((self.root / "Project/Animations/Characters/Hero/Action").is_dir())

    def test_delete_matches_type_and_icon_and_rolls_back_ambiguous_rows(self):
        result = self.add()
        self.db.execute('INSERT INTO asset SELECT * FROM asset')
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "重名"):
            self.delete(result)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 2)
        self.db.execute('DELETE FROM asset WHERE rowid=(SELECT MAX(rowid) FROM asset)')
        self.db.execute('UPDATE asset SET "asset.type"=?', ("Props",))
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "不存在"):
            self.delete(result)
        self.db.execute('UPDATE asset SET "asset.type"=?, "asset.icon"=?', ("Characters", "changed.png"))
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "修改"):
            self.delete(result)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 1)

    def test_unsafe_icon_still_deletes_record_but_refuses_folder(self):
        result = self.add()
        self.db.execute('UPDATE asset SET "asset.icon"=?', (str(self.root / "Project/Assets/Icon/Hero.png"),))
        self.db.commit()
        row = list(result["row"])
        row[7] = str(self.root / "Project/Assets/Icon/Hero.png")
        result["row"] = row
        deleted = self.delete(result)
        self.assertIn("不一致", deleted["folder_error"])
        self.assertFalse(deleted["folder_exists"])
        with mock.patch.object(service.shutil, "rmtree") as remove:
            with self.assertRaises(ValueError):
                service.delete_folder("asset", deleted)
            remove.assert_not_called()

    def test_delete_path_rejects_local_content_other_asset_and_traversal(self):
        result = self.add()
        for icon in (str(self.root / "Content/Assets/Characters/Hero/Icon/Hero.png"),
                     str(self.root / "Project/Assets/Characters/Other/Icon/Hero.png"),
                     str(self.root / "Project/Assets/Characters/Hero/../Hero/Icon/Hero.png"), ""):
            row = list(result["row"])
            row[7] = icon
            with self.subTest(icon=icon), self.assertRaises(ValueError):
                service.validated_delete_folder(self.settings, "asset", "Project", "Characters", row)

    def test_folder_delete_failure_keeps_database_deleted(self):
        deleted = self.delete(self.add())
        with mock.patch.object(service.shutil, "rmtree", side_effect=OSError("access denied")):
            with self.assertRaisesRegex(OSError, "access denied"):
                service.delete_folder("asset", deleted)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 0)
        self.assertTrue(Path(deleted["folder"]).exists())

    def test_revalidate_changed_root_before_deleting_any_files(self):
        deleted = self.delete(self.add())
        self.settings["rootPath"] = str(self.root / "OtherRoot")
        with mock.patch.object(service.shutil, "rmtree") as remove:
            with self.assertRaisesRegex(ValueError, "不一致"):
                service.delete_folder("asset", deleted)
            remove.assert_not_called()

    def test_legacy_icon_with_equivalent_windows_short_root_is_valid(self):
        result = self.add()
        row = list(result["row"])
        row[7] = str(Path(self.tmp.name) / "Project/Assets/Characters/Hero/Icon/Hero.png")
        self.assertEqual(service.validated_delete_folder(self.settings, "asset", "Project", "Characters", row),
                         str(self.root / "Project/Assets/Characters/Hero"))

    def test_record_symlink_cannot_redirect_delete_to_another_asset(self):
        result = self.add()
        actual = self.root / "Project/Assets/Characters/Hero"
        destination = actual.with_name("Other")
        actual.rename(destination)
        try:
            actual.symlink_to(destination, target_is_directory=True)
        except OSError as exc:
            self.skipTest("symlink creation unavailable: " + str(exc))
        self.addCleanup(actual.unlink)
        with self.assertRaisesRegex(ValueError, "链接"):
            service.validated_delete_folder(self.settings, "asset", "Project", "Characters", result["row"])
        self.assertTrue(destination.is_dir())


class CrudUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.page = StatusPage()
        self.page._status_editor = self.page.editor
        self.page._load_check = mock.Mock(isRunning=lambda: False)
        self.page.add_bttn = QtWidgets.QPushButton(self.page)
        self.page.scriptsPath = str(Path(__file__).resolve().parents[1])
        self.controller = ui.RecordController(self.page, "asset", lambda: self.page.scope)
        self.controller.changed.connect(self.apply)
        self.changed = []
        self.warning = self.enterContext(mock.patch.object(QtWidgets.QMessageBox, "warning",
                                                          return_value=QtWidgets.QMessageBox.No))
        self.options = self.enterContext(mock.patch.object(service, "read_add_options", return_value={
            "projects": ["Project", "Other"], "project": "Project", "types": ["Characters", "Props"]}))
        self.created = tuple(self.page.main_listWgt.items()[0])
        self.result = {"project": "Project", "type": "Characters", "row": self.created,
                       "operation": "delete", "folder": "Y:/MCCProject/Project/Assets/Characters/Hero",
                       "folder_exists": True, "folder_error": ""}
        self.add = self.enterContext(mock.patch.object(service, "add_record", return_value={
            **self.result, "operation": "add"}))
        self.delete = self.enterContext(mock.patch.object(service, "delete_record", return_value=self.result))
        self.remove = self.enterContext(mock.patch.object(service, "delete_folder", return_value=self.result))

    def apply(self, result):
        self.changed.append(result)
        if (result["project"], result["type"]) == self.page.scope:
            self.page.main_listWgt.setItems(ui.apply_to_rows(self.page.main_listWgt.items(), result))

    def tearDown(self):
        self.controller.shutdown()
        ui._POOL.waitForDone(3000)
        self.app.processEvents()
        self.page.editor.shutdown()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(10, loop.quit)
            loop.exec()
        self.assertTrue(predicate())

    def open(self):
        self.page.add_bttn.click()
        self.wait_until(lambda: self.controller.dialog is not None and self.controller.dialog.types.isEnabled())
        return self.controller.dialog

    def test_add_dialog_defaults_nonmodal_icon_and_updates_rows(self):
        dialog = self.open()
        self.assertEqual(dialog.projects.currentText(), "Project")
        self.assertEqual(dialog.types.currentText(), "Characters")
        self.assertEqual(dialog.windowModality(), QtCore.Qt.NonModal)
        self.assertTrue(self.page.isEnabled())
        self.assertFalse(QtGui.QIcon(os.path.join(self.page.scriptsPath, "icon/add.png")).isNull())
        dialog.name.setText("Hero")
        dialog.zh_name.setText("新中文名")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).click()
        self.wait_until(lambda: not self.controller.busy and self.controller.dialog is None)
        self.add.assert_called_once_with("user", "password", "asset", "Project", "Characters", "Hero", "新中文名")
        self.assertEqual(len(self.changed), 1)
        self.assertEqual([row[1] for row in self.page.main_listWgt.items()], ["Other", "Hero"])

    def test_invalid_name_keeps_dialog_without_write(self):
        dialog = self.open()
        dialog.name.setText("../Wrong")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).click()
        self.add.assert_not_called()
        self.assertIn("字符", dialog.message.text())

    def test_add_failure_keeps_dialog_and_does_not_change_list(self):
        self.add.side_effect = OSError("database write denied")
        dialog = self.open()
        dialog.name.setText("Hero")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).click()
        self.wait_until(lambda: not self.controller.busy)
        self.assertIs(self.controller.dialog, dialog)
        self.assertIn("write denied", dialog.message.text())
        self.assertEqual(self.changed, [])

    def test_first_confirmation_no_is_a_complete_noop(self):
        self.controller.delete(self.created, self.page.scope)
        self.delete.assert_not_called()
        self.remove.assert_not_called()
        self.assertEqual(self.warning.call_args.args[-1], QtWidgets.QMessageBox.No)

    def test_second_confirmation_no_removes_record_but_keeps_folder(self):
        self.warning.side_effect = [QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No]
        self.controller.delete(self.created, self.page.scope)
        self.wait_until(lambda: not self.controller.busy)
        self.assertEqual(self.warning.call_count, 2)
        self.remove.assert_not_called()
        self.assertEqual([row[1] for row in self.page.main_listWgt.items()], ["Other"])
        self.assertIn("Hero", self.warning.call_args_list[0].args[2])
        self.assertIn(self.result["folder"], self.warning.call_args_list[1].args[2])

    def test_two_yeses_delete_folder_after_record_and_refresh(self):
        self.warning.return_value = QtWidgets.QMessageBox.Yes
        self.controller.delete(self.created, self.page.scope)
        self.wait_until(lambda: not self.controller.busy)
        self.delete.assert_called_once()
        self.remove.assert_called_once_with("asset", self.result)
        self.assertEqual(len(self.changed), 1)

    def test_database_failure_never_offers_or_deletes_folder(self):
        self.warning.return_value = QtWidgets.QMessageBox.Yes
        self.delete.side_effect = RuntimeError("write denied")
        self.controller.delete(self.created, self.page.scope)
        self.wait_until(lambda: not self.controller.busy)
        self.remove.assert_not_called()
        self.assertEqual(self.changed, [])
        self.assertIn("write denied", self.warning.call_args.args[2])

    def test_bad_folder_reports_partial_success_and_never_deletes_files(self):
        self.warning.return_value = QtWidgets.QMessageBox.Yes
        self.result["folder_error"] = "unsafe icon"
        self.controller.delete(self.created, self.page.scope)
        self.wait_until(lambda: not self.controller.busy)
        self.remove.assert_not_called()
        self.assertIn("数据表已删除", self.warning.call_args.args[2])
        self.assertIn("unsafe icon", self.warning.call_args.args[2])
        self.assertEqual(len(self.changed), 1)

    def test_folder_failure_reports_original_path_and_reason(self):
        self.warning.return_value = QtWidgets.QMessageBox.Yes
        self.remove.side_effect = OSError("permission denied")
        self.controller.delete(self.created, self.page.scope)
        self.wait_until(lambda: not self.controller.busy)
        self.assertIn("数据表已删除", self.warning.call_args.args[2])
        self.assertIn(self.result["folder"], self.warning.call_args.args[2])
        self.assertIn("permission denied", self.warning.call_args.args[2])

    def test_slow_delete_and_page_switch_keep_event_loop_responsive(self):
        main_thread = threading.get_ident()
        threads, ticks = [], []
        def slow(*args):
            threads.append(threading.get_ident())
            time.sleep(0.16)
            return self.result
        self.delete.side_effect = slow
        self.warning.side_effect = [QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No]
        self.controller.delete(self.created, self.page.scope)
        self.page.scope = ("Other", "Props")
        QtCore.QTimer.singleShot(10, lambda: ticks.append(True))
        self.wait_until(lambda: not self.controller.busy)
        self.assertTrue(ticks)
        self.assertNotEqual(threads, [main_thread])
        self.assertEqual([row[1] for row in self.page.main_listWgt.items()], ["Hero", "Other"])

    def test_shutdown_during_delete_suppresses_second_confirmation_and_ui_update(self):
        def slow(*args):
            time.sleep(0.1)
            return self.result
        self.delete.side_effect = slow
        self.warning.return_value = QtWidgets.QMessageBox.Yes
        self.controller.delete(self.created, self.page.scope)
        self.controller.shutdown()
        ui._POOL.waitForDone(2000)
        self.app.processEvents()
        self.assertEqual(self.warning.call_count, 1)
        self.remove.assert_not_called()
        self.assertEqual(self.changed, [])

    def test_menu_snapshots_and_rejects_stale_context(self):
        menu = QtWidgets.QMenu(self.page)
        action = self.controller.addDeleteAction(menu, self.page.main_listWgt.item(0))
        self.assertEqual(action.text(), "删除...")
        self.assertFalse(action.icon().isNull())
        self.page.scope = ("Other", "Props")
        action.trigger()
        self.warning.assert_not_called()

    def test_scene_dialog_and_menu_use_scene_table(self):
        self.controller.shutdown()
        self.controller = ui.RecordController(self.page, "scene", lambda: self.page.scope)
        dialog = self.open()
        self.assertIn("Add Scene", dialog.windowTitle())
        dialog.name.setText("Tree")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).click()
        self.wait_until(lambda: not self.controller.busy)
        self.assertEqual(self.add.call_args.args[2], "scene")

    def test_actual_pages_wire_toolbar_dialog_and_scoped_list_update(self):
        class OfflineAsset(assetTools.AssetToolsUI):
            def _startInitialLoad(self):
                pass

            def scanUEAssetStates(self):
                pass

            def _ensurePreviewWidgets(self):
                return False

            def rememberSettings(self):
                pass

        class OfflineScene(sceneTools.SceneToolsUI):
            def firstView(self):
                self.scene_isList = True

            def getItemsFromSQL(self):
                return []

            def scanUEAssetStates(self):
                pass

            def _ensureScenePreviewWidget(self):
                return False

            def rememberSettings(self):
                pass

        for table, page_type in (("asset", OfflineAsset), ("scene", OfflineScene)):
            with self.subTest(table=table):
                page = page_type(isSQL=True, user="user", password="password")
                try:
                    combo = page.project_comb if table == "asset" else page.proj_comb
                    combo.blockSignals(True)
                    page.type_listWgt.blockSignals(True)
                    combo.addItem("Project")
                    page.type_listWgt.addItem("Characters")
                    page.type_listWgt.setCurrentRow(0)
                    if hasattr(page, "init_ui_thread"):
                        page.init_ui_thread.wait(2000)
                    self.app.processEvents()
                    page.listWidgetAddItems([self.created])
                    page.add_bttn.click()
                    self.wait_until(lambda: page._record_controller.dialog is not None
                                    and page._record_controller.dialog.types.isEnabled())
                    self.assertFalse(page.add_bttn.icon().isNull())
                    page._record_controller.dialog.reject()
                    generation = getattr(page, "_query_generation", 0)
                    page._record_controller.changed.emit(self.result)
                    self.assertEqual(page.main_listWgt.count(), 0)
                    if table == "asset":
                        self.assertEqual(page._query_generation, generation + 1)
                    page._record_controller.changed.emit({**self.result, "operation": "add", "project": "Other"})
                    self.assertEqual(page.main_listWgt.count(), 0)
                finally:
                    page.shutdownThreads()
                    page.close()
                    page.deleteLater()
                    self.app.processEvents()

    def test_add_during_pending_type_query_requests_fresh_rows(self):
        page = mock.Mock()
        page._statusContext.return_value = ("Project", "Characters")
        page._status_editor.loading = True
        assetTools.AssetToolsUI._recordChanged(page, {**self.result, "operation": "add"})
        page._requestAssetData.assert_called_once()
        page.listWidgetAddItems.assert_not_called()


if __name__ == "__main__":
    unittest.main()
