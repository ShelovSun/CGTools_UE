"""Local SQL and real Qt status-dropdown checks; never connect to the server."""

import os
import sqlite3
import sys
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

import psycopg2
from PySide6 import QtCore, QtTest, QtWidgets
from AssetsManagerForUE.sources import status_edit_service as service
from AssetsManagerForUE.sources import assetTools, sceneTools
from AssetsManagerForUE.utils import myWidget


class LocalCursor:
    def __init__(self, database):
        self.cursor = database.cursor()

    def execute(self, query, values):
        query = query.replace('public."', '"').replace("%s", "?")
        self.cursor.execute(query, values)

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def close(self):
        self.cursor.close()


class LocalConnection:
    def __init__(self, database):
        self.database = database
        self.commits = self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return LocalCursor(self.database)

    def commit(self):
        self.commits += 1
        self.database.commit()

    def rollback(self):
        self.rollbacks += 1
        self.database.rollback()

    def close(self):
        self.closed = True


class StatusDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.execute('CREATE TABLE asset ("asset.name", "asset.type", '
                              '"asset.mod_status", "asset.rig_status", "asset.note")')
        self.database.execute('CREATE TABLE scene ("scene.name", "scene.type", '
                              '"scene.status", "scene.note")')
        self.database.executemany("INSERT INTO asset VALUES (?, ?, ?, ?, ?)", [
            ("Hero's角色", "Characters", "未开始", "制作中", "保留备注"),
            ("Hero's角色", "Props", "未开始", "已完成", "其他类型"),
        ])
        self.database.execute("INSERT INTO scene VALUES (?, ?, ?, ?)",
                              ("Tree", "Nature", "已完成", "场景备注"))
        self.database.commit()
        self.conn = LocalConnection(self.database)
        self.connect = self.enterContext(mock.patch.object(
            psycopg2, "connect", return_value=self.conn))
        self.enterContext(mock.patch.object(service, "databaseHost", return_value="local.test"))

    def update(self, table="asset", field=4, old="未开始", new="UE", name="Hero's角色"):
        service.update_status("user", "password", "Project", table,
                              "Nature" if table == "scene" else "Characters",
                              name, field, old, new)

    def test_model_updates_only_selected_type_and_preserves_rig_and_notes(self):
        self.update()
        self.assertEqual(self.database.execute("SELECT * FROM asset").fetchall(), [
            ("Hero's角色", "Characters", "UE", "制作中", "保留备注"),
            ("Hero's角色", "Props", "未开始", "已完成", "其他类型"),
        ])
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual(self.conn.rollbacks, 0)
        self.assertTrue(self.conn.closed)
        self.assertEqual(self.connect.call_args.kwargs["host"], "local.test")
        self.assertEqual(self.connect.call_args.kwargs["database"], "Project")
        self.assertEqual(self.connect.call_args.kwargs["user"], "user")

    def test_rig_and_scene_columns_are_mapped_correctly(self):
        self.update(field=6, old="制作中", new="已完成")
        self.update(table="scene", old="已完成", new="UE", name="Tree")
        self.assertEqual(self.database.execute('SELECT "asset.mod_status", "asset.rig_status" '
                                              'FROM asset LIMIT 1').fetchone(), ("未开始", "已完成"))
        self.assertEqual(self.database.execute("SELECT * FROM scene").fetchone(),
                         ("Tree", "Nature", "UE", "场景备注"))

    def test_null_old_status_can_be_changed(self):
        self.database.execute('UPDATE scene SET "scene.status" = NULL')
        self.database.commit()
        self.update(table="scene", old=None, new="制作中", name="Tree")
        self.assertEqual(self.database.execute('SELECT "scene.status" FROM scene').fetchone()[0], "制作中")

    def test_stale_missing_and_duplicate_rows_roll_back(self):
        for name, old in (("missing", "未开始"), ("Hero's角色", "已完成")):
            with self.assertRaisesRegex(RuntimeError, "刷新"):
                self.update(name=name, old=old)
        self.database.execute("INSERT INTO asset SELECT * FROM asset LIMIT 1")
        self.database.commit()
        with self.assertRaisesRegex(RuntimeError, "重名"):
            self.update()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 3)
        self.assertEqual(self.database.execute('SELECT "asset.mod_status" FROM asset').fetchall(),
                         [("未开始",)] * 3)

    def test_database_error_rolls_back_and_keeps_original_status(self):
        self.database.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON asset "
                              "BEGIN SELECT RAISE(ABORT, 'write denied'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "write denied"):
            self.update()
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertTrue(self.conn.closed)
        self.assertEqual(self.database.execute('SELECT "asset.mod_status" FROM asset LIMIT 1').fetchone()[0], "未开始")

    def test_unsupported_fields_values_and_rig_ue_never_open_connection(self):
        for table, field, value in (("asset", 3, "UE"), ("asset", 6, "UE"),
                                     ("scene", 4, "injected"), ("injected", 4, "UE")):
            with self.assertRaises(ValueError):
                self.update(table=table, field=field, new=value)
        self.connect.assert_not_called()

    def test_connection_failure_does_not_hide_error(self):
        self.connect.side_effect = psycopg2.OperationalError("connection unavailable")
        with self.assertRaisesRegex(psycopg2.OperationalError, "unavailable"):
            self.update()


class StatusPage(QtWidgets.QWidget):
    def __init__(self, table="asset"):
        super().__init__()
        self.isSQL = True
        self.user, self.password = "user", "password"
        self.scope = ("Project", "Characters")
        self.messages = []
        self.main_listWgt = myWidget.MainQListWiget()
        widget = self.main_listWgt
        widget.setUEPublishedStatusField(4)
        widget.setSortingEnabled(False)
        widget.setIsList(True)
        if table == "scene":
            widget.setListColumns(("日期", "场景名", "中文名", "制作人", "状态", "备注"),
                                  (0, 1, 2, 3, 4, 8), (86, 180, 110, 78, 78, 180))
        widget.setListMode()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(widget)
        self.editor = service.StatusEditor(self, table, lambda: self.scope)
        self.load()
        self.resize(1000, 220)
        self.show()

    def load(self, status="未开始"):
        self.main_listWgt.clear()
        self.main_listWgt.setItems([
            ("20261015", name, "角色", "模型制作人", status, "绑定制作人", "制作中", "", "备注")
            for name in ("Hero", "Other")])
        self.main_listWgt.addItems()
        self.editor.setContext(*self.scope)

    def infoMsg(self, icon, text):
        self.messages.append((icon, text))


class StatusDropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.page = StatusPage()
        self.widget = self.page.main_listWgt
        self.app.processEvents()
        self.warning = self.enterContext(mock.patch.object(QtWidgets.QMessageBox, "warning"))
        # Catch every accidental database call in UI tests.
        self.write = self.enterContext(mock.patch.object(service, "update_status"))

    def tearDown(self):
        service._WRITE_POOL.waitForDone(2000)
        self.app.processEvents()
        self.page.editor.shutdown()
        self.widget._closeStatusMenu()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertTrue(condition())

    def cell_point(self, field=4):
        rect = self.widget.visualItemRect(self.widget.item(0))
        column = self.widget.listFieldIndices().index(field)
        widths = self.widget.listColumnWidths()
        return QtCore.QPoint(rect.left() + sum(widths[:column]) + widths[column] // 2,
                            rect.top() + 10)

    def open_menu(self, field=4):
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton,
                                pos=self.cell_point(field))
        self.app.processEvents()
        self.assertIsNotNone(self.widget._statusMenu)
        return self.widget._statusMenu

    def choose(self, value, field=4):
        menu = self.open_menu(field)
        action = next(action for action in menu.actions() if action.text() == value)
        QtTest.QTest.mouseClick(menu, QtCore.Qt.LeftButton,
                                pos=menu.actionGeometry(action).center())

    def test_single_click_has_maya_options_and_rig_excludes_ue(self):
        menu = self.open_menu()
        self.assertEqual([a.text() for a in menu.actions()], list(service.MODEL_STATUSES))
        self.assertTrue(menu.actions()[0].isChecked())
        self.widget._closeStatusMenu()
        menu = self.open_menu(6)
        self.assertEqual([a.text() for a in menu.actions()], list(service.BASE_STATUSES))
        self.assertIsNone(self.widget._assetDragItem)

    def test_commit_updates_cache_and_cell_only_after_success_and_survives_rebuild(self):
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def write(*args):
            started.set()
            finish.wait(2)
        self.write.side_effect = write
        item = self.widget.item(0)
        self.choose("UE")
        self.wait_until(started.is_set)
        self.assertFalse(self.widget._statusEditingEnabled)
        self.assertEqual(item.itemData()[4], "未开始")
        # GUI remains responsive while the database worker is blocked.
        self.assertIs(self.widget.currentItem(), item)
        finish.set()
        self.wait_until(lambda: self.page.editor.pending is None)
        self.assertEqual(item.itemData()[4], "UE")
        self.assertTrue(item.isUEPublished())
        self.assertEqual(self.widget.items()[0][4], "UE")
        self.assertEqual(self.widget.items()[1][4], "未开始")
        self.assertEqual(item.itemData()[6], "制作中")
        self.widget.clear()
        self.widget.addItems("Hero")
        self.assertEqual(self.widget.count(), 1)
        self.assertEqual(self.widget.item(0).itemData()[4], "UE")
        self.assertTrue(self.widget.item(0).isUEPublished())
        self.assertTrue(self.widget._statusEditingEnabled)
        self.write.assert_called_once_with("user", "password", "Project", "asset", "Characters",
                                          "Hero", 4, "未开始", "UE")

    def test_failed_save_reports_error_and_keeps_cache_and_display(self):
        self.write.side_effect = RuntimeError("permission denied")
        self.choose("UE")
        self.wait_until(lambda: self.page.editor.pending is None)
        self.assertEqual(self.widget.item(0).itemData()[4], "未开始")
        self.assertFalse(self.widget.item(0).isUEPublished())
        self.assertEqual(self.widget.items()[0][4], "未开始")
        self.assertTrue(self.widget._statusEditingEnabled)
        self.warning.assert_called_once()
        self.assertIn("permission denied", self.warning.call_args.args[2])

    def test_switch_project_during_save_does_not_change_same_named_row_in_new_project(self):
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def write(*args):
            started.set()
            finish.wait(2)
        self.write.side_effect = write
        self.choose("UE")
        self.wait_until(started.is_set)
        self.page.editor.setLoading()
        self.page.scope = ("OtherProject", "Props")
        self.page.load("已完成")
        finish.set()
        self.wait_until(lambda: self.page.editor.pending is None)
        self.assertEqual(self.widget.item(0).itemData()[4], "已完成")
        self.assertEqual(self.widget.items()[0][4], "已完成")
        self.assertEqual(self.write.call_args.args[2:5], ("Project", "asset", "Characters"))

    def test_selecting_same_value_and_editing_stale_scope_do_not_write(self):
        self.choose("未开始")
        self.page.scope = ("OtherProject", "Characters")
        self.choose("UE")
        self.app.processEvents()
        self.write.assert_not_called()

    def test_loading_clear_and_icon_view_close_menus_without_writing(self):
        menu = self.open_menu()
        action = menu.actions()[-1]
        self.widget.clear()
        action.trigger()
        self.write.assert_not_called()
        self.page.load()
        self.page.editor.setLoading()
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.cell_point())
        self.assertIsNone(self.widget._statusMenu)
        self.page.editor.setContext(*self.page.scope)
        self.open_menu()
        self.widget.setIsList(False)
        self.assertIsNone(self.widget._statusMenu)

    def test_scrolled_status_cell_uses_actual_visual_position(self):
        self.page.resize(450, 220)
        self.app.processEvents()
        self.widget.horizontalScrollBar().setValue(350)
        self.app.processEvents()
        self.open_menu()

    def test_scene_edit_updates_both_status_aliases_and_preserves_notes(self):
        self.page.editor.shutdown()
        self.page.close()
        self.page = StatusPage("scene")
        self.widget = self.page.main_listWgt
        self.app.processEvents()
        self.choose("UE")
        self.wait_until(lambda: self.page.editor.pending is None)
        row = self.widget.item(0).itemData()
        self.assertEqual((row[4], row[6], row[8]), ("UE", "UE", "备注"))
        self.assertEqual(self.widget.items()[0], row)

    def test_shutdown_ignores_completion_and_cannot_edit(self):
        self.page.editor.shutdown()
        self.page.editor.request(self.widget.item(0).itemData(), 4, "UE")
        self.assertFalse(self.widget._statusEditingEnabled)
        self.write.assert_not_called()

    def test_asset_page_restarts_read_that_might_contain_precommit_status(self):
        page = types.SimpleNamespace(
            _statusContext=lambda: ("Project", "Characters"), _query_generation=2,
            _query_tasks={2: object()}, _requestAssetData=mock.Mock())
        assetTools.AssetToolsUI._statusSaved(page, ("OtherProject", "Characters", "Hero", 4, "UE"))
        page._requestAssetData.assert_not_called()
        assetTools.AssetToolsUI._statusSaved(page, ("Project", "Characters", "Hero", 4, "UE"))
        page._requestAssetData.assert_called_once()

    def test_actual_asset_and_scene_pages_wire_statuses_to_current_database_context(self):
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

        for table, ui_class in (("asset", OfflineAsset), ("scene", OfflineScene)):
            with self.subTest(table=table):
                ui = ui_class(isSQL=True, user="user", password="password")
                try:
                    combo = ui.project_comb if table == "asset" else ui.proj_comb
                    combo.blockSignals(True)
                    ui.type_listWgt.blockSignals(True)
                    combo.addItem("PageProject")
                    ui.type_listWgt.addItem("Props")
                    ui.type_listWgt.setCurrentRow(0)
                    if hasattr(ui, "init_ui_thread"):
                        ui.init_ui_thread.wait(2000)
                    self.app.processEvents()
                    if table == "asset":
                        ui.isList = True
                    ui.listWidgetAddItems([self.widget.items()[0]])
                    self.assertEqual(ui._status_editor.context, ("PageProject", "Props"))
                    self.assertTrue(ui.main_listWgt._statusEditingEnabled)
                    self.assertEqual(ui.main_listWgt.uePublishedStatusField(), 4)
                    self.assertFalse(ui.main_listWgt.item(0).isUEPublished())
                    ui._status_editor.request(ui.main_listWgt.item(0).itemData(), 4, "UE")
                    self.wait_until(lambda: ui._status_editor.pending is None)
                    self.assertEqual(ui.main_listWgt.item(0).itemData()[4], "UE")
                    self.assertTrue(ui.main_listWgt.item(0).isUEPublished())
                    self.assertEqual(self.write.call_args.args[2:5], ("PageProject", table, "Props"))
                    self.assertEqual(ui.main_listWgt._detailColumns,
                                     {2: "text", 3: "artist", 5: "artist"}
                                     if table == "asset" else {2: "text", 3: "artist"})
                    ui.main_listWgt.setCurrentRow(0)
                    ui.preview_wgt = mock.Mock()
                    with mock.patch.object(service, "update_detail") as detail_write:
                        ui._status_editor.requestDetail(ui.main_listWgt.item(0).itemData(), 2, "新中文名")
                        self.wait_until(lambda: ui._status_editor.pending is None)
                        self.assertEqual(ui.main_listWgt.item(0).itemData()[2], "新中文名")
                        ui.preview_wgt.setTitle.assert_called_once_with("Hero", "新中文名")
                        self.assertEqual(detail_write.call_args.args[2:5], ("PageProject", table, "Props"))
                    ui._status_editor.request(ui.main_listWgt.item(0).itemData(), 4, "已完成")
                    self.wait_until(lambda: ui._status_editor.pending is None)
                    self.assertFalse(ui.main_listWgt.item(0).isUEPublished())
                finally:
                    ui.shutdownThreads()
                    if hasattr(ui, "init_ui_thread"):
                        ui.init_ui_thread.wait(2000)
                    ui.close()
                    ui.deleteLater()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
