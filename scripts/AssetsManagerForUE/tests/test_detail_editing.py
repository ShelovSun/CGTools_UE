"""Chinese-name/artist editing against local SQL and real Qt popups."""

import os
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from PySide6 import QtCore, QtTest, QtWidgets
from test_status_editing import LocalConnection, StatusPage
from AssetsManagerForUE.sources import status_edit_service as service
from AssetsManagerForUE.utils.cell_editors import ArtistPicker, NameEditor


class DetailDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.execute('CREATE TABLE asset ("asset.name", "asset.type", "asset.zh_name", '
                              '"asset.mod_artist", "asset.mod_status", "asset.rig_artist", '
                              '"asset.rig_status", "asset.note")')
        self.database.execute('CREATE TABLE scene ("scene.name", "scene.type", "scene.zh_name", '
                              '"scene.artist", "scene.status", "scene.note")')
        self.database.executemany("INSERT INTO asset VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("Hero", "Characters", "角色", "张三", "UE", "李四", "制作中", "保留备注"),
            ("Hero", "Props", "同名道具", "其他人", "未开始", "其他绑定", "未开始", "其他备注"),
        ])
        self.database.execute("INSERT INTO scene VALUES (?, ?, ?, ?, ?, ?)",
                              ("Tree", "Nature", None, "张三", "UE", "场景备注"))
        self.database.commit()
        self.conn = LocalConnection(self.database)
        self.connect = self.enterContext(mock.patch.object(psycopg2, "connect", return_value=self.conn))
        self.enterContext(mock.patch.object(service, "databaseHost", return_value="local.test"))

    def update(self, field, old, new, table="asset"):
        service.update_detail("user", "password", "Project", table,
                              "Characters" if table == "asset" else "Nature",
                              "Hero" if table == "asset" else "Tree", field, old, new)

    def test_asset_fields_only_update_requested_column_and_type(self):
        self.update(2, "角色", "巴斯特")
        self.update(3, "张三", "王五")
        self.update(5, "李四", "赵六")
        rows = self.database.execute("SELECT * FROM asset").fetchall()
        self.assertEqual(rows[0], ("Hero", "Characters", "巴斯特", "王五", "UE", "赵六", "制作中", "保留备注"))
        self.assertEqual(rows[1], ("Hero", "Props", "同名道具", "其他人", "未开始", "其他绑定", "未开始", "其他备注"))
        self.assertEqual(self.conn.commits, 3)
        self.assertTrue(self.conn.closed)

    def test_scene_name_null_and_artist_fields_are_supported(self):
        self.update(2, None, "树'中文名", table="scene")
        self.update(3, "张三", "王五", table="scene")
        self.assertEqual(self.database.execute("SELECT * FROM scene").fetchone(),
                         ("Tree", "Nature", "树'中文名", "王五", "UE", "场景备注"))

    def test_quotes_and_sql_text_are_saved_as_text_and_empty_name_is_allowed(self):
        value = "角色'; DROP TABLE asset;--"
        self.update(2, "角色", value)
        self.update(2, value, "")
        self.assertEqual(self.database.execute('SELECT "asset.zh_name" FROM asset LIMIT 1').fetchone()[0], "")
        self.assertEqual(self.database.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 2)

    def test_changed_value_and_write_failure_roll_back(self):
        with self.assertRaisesRegex(RuntimeError, "刷新"):
            self.update(2, "过期中文名", "新的名字")
        self.database.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON asset "
                              "BEGIN SELECT RAISE(ABORT, 'write denied'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "write denied"):
            self.update(5, "李四", "王五")
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 2)
        self.assertEqual(self.database.execute('SELECT "asset.zh_name", "asset.rig_artist" FROM asset LIMIT 1')
                         .fetchone(), ("角色", "李四"))

    def test_unsupported_fields_and_invalid_values_never_connect(self):
        for table, field, value in (("asset", 1, "Rename"), ("scene", 5, "Person"),
                                     ("asset", 2, None), ("asset", 3, "invalid\x00name")):
            with self.assertRaises(ValueError):
                self.update(field, "old", value, table)
        self.connect.assert_not_called()

    def test_shared_user_list_is_reloaded_grouped_and_validated(self):
        settings = {"user_list": {"资产": [" 张三 ", "李四", "张三", ""], "动画": ["王五"]}}
        with mock.patch.object(service, "commonSetting", return_value=settings) as read:
            self.assertEqual(service.read_artist_groups(), {"资产": ["张三", "李四"], "动画": ["王五"]})
            read.assert_called_once_with(force_reload=True)
        for value in (None, {}, [], {"资产": "张三"}, {"资产": [None]}, {"资产": []}):
            with mock.patch.object(service, "commonSetting", return_value={"user_list": value}):
                with self.assertRaises(ValueError):
                    service.read_artist_groups()


class DetailPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.page = StatusPage()
        self.widget = self.page.main_listWgt
        self.app.processEvents()
        self.write = self.enterContext(mock.patch.object(service, "update_detail"))
        self.status_write = self.enterContext(mock.patch.object(service, "update_status"))
        self.read = self.enterContext(mock.patch.object(service, "read_artist_groups",
                                                        return_value={"资产": ["张三", "李四"], "动画": ["王五"]}))
        self.warning = self.enterContext(mock.patch.object(QtWidgets.QMessageBox, "warning"))

    def tearDown(self):
        self.page.editor.shutdown()
        service._WRITE_POOL.waitForDone(2000)
        self.app.processEvents()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertTrue(condition())

    def point(self, field):
        rect = self.widget.visualItemRect(self.widget.item(0))
        column = self.widget.listFieldIndices().index(field)
        widths = self.widget.listColumnWidths()
        return QtCore.QPoint(rect.x() + sum(widths[:column]) + widths[column] // 2, rect.y() + 10)

    def name_editor(self):
        QtTest.QTest.mouseDClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.point(2))
        self.app.processEvents()
        popup = self.page.editor.detail_popup
        self.assertIsInstance(popup, NameEditor)
        return popup

    def artist_picker(self, field=3):
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.point(field))
        self.wait_until(lambda: not self.page.editor._artist_tasks)
        popup = self.page.editor.detail_popup
        self.assertIsInstance(popup, ArtistPicker)
        return popup

    def test_chinese_name_double_click_enter_saves_cache_and_search(self):
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.point(2))
        self.assertIsNone(self.page.editor.detail_popup)
        popup = self.name_editor()
        self.assertEqual(popup.line.text(), "角色")
        popup.line.setText("巴斯特")
        QtTest.QTest.keyClick(popup.line, QtCore.Qt.Key_Return)
        self.wait_until(lambda: self.write.called and self.page.editor.pending is None)
        self.assertEqual(self.widget.item(0).itemData()[2], "巴斯特")
        self.assertEqual(self.widget.items()[0][2], "巴斯特")
        self.write.assert_called_once_with("user", "password", "Project", "asset", "Characters",
                                          "Hero", 2, "角色", "巴斯特")
        self.widget.clear()
        self.widget.addItems("巴斯特")
        self.assertEqual(self.widget.count(), 1)

    def test_escape_cancels_without_focus_out_write(self):
        popup = self.name_editor()
        popup.line.setText("取消的修改")
        QtTest.QTest.keyClick(popup.line, QtCore.Qt.Key_Escape)
        self.app.processEvents()
        self.assertIsNone(self.page.editor.detail_popup)
        self.write.assert_not_called()
        self.assertEqual(self.widget.items()[0][2], "角色")

    def test_focus_out_saves_once_and_unchanged_text_does_not_write(self):
        popup = self.name_editor()
        popup.line.setText("新中文名")
        popup.line.clearFocus()
        self.wait_until(lambda: self.write.called and self.page.editor.pending is None)
        self.write.assert_called_once()
        popup = self.name_editor()
        QtTest.QTest.keyClick(popup.line, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.write.assert_called_once()

    def test_grouped_artist_list_filters_and_group_click_does_not_save(self):
        popup = self.artist_picker()
        self.assertEqual(popup.tree.topLevelItemCount(), 2)
        heading = popup.tree.topLevelItem(0)
        QtTest.QTest.mouseClick(popup.tree.viewport(), QtCore.Qt.LeftButton,
                                pos=popup.tree.visualItemRect(heading).center())
        self.write.assert_not_called()
        self.assertIs(self.page.editor.detail_popup, popup)
        popup.line.setText("王五")
        self.assertEqual(popup.tree.topLevelItemCount(), 1)
        child = popup.tree.topLevelItem(0).child(0)
        self.assertEqual(child.text(0), "王五")
        QtTest.QTest.mouseClick(popup.tree.viewport(), QtCore.Qt.LeftButton,
                                pos=popup.tree.visualItemRect(child).center())
        self.wait_until(lambda: self.write.called and self.page.editor.pending is None)
        self.assertEqual(self.widget.items()[0][3], "王五")
        self.assertEqual(self.widget.items()[0][5], "绑定制作人")
        self.assertEqual(self.write.call_args.args[-3:], (3, "模型制作人", "王五"))

    def test_rig_artist_edit_preserves_model_artist_and_both_statuses(self):
        popup = self.artist_picker(5)
        popup._choose(popup.tree.topLevelItem(0).child(1), 0)
        self.wait_until(lambda: self.write.called and self.page.editor.pending is None)
        row = self.widget.items()[0]
        self.assertEqual((row[3], row[4], row[5], row[6]), ("模型制作人", "未开始", "李四", "制作中"))
        self.assertEqual(self.write.call_args.args[-3:], (5, "绑定制作人", "李四"))

    def test_failed_detail_write_preserves_display_and_cache(self):
        self.write.side_effect = RuntimeError("permission denied")
        popup = self.name_editor()
        popup.line.setText("保存失败")
        QtTest.QTest.keyClick(popup.line, QtCore.Qt.Key_Return)
        self.wait_until(lambda: self.warning.called)
        self.assertEqual(self.widget.item(0).itemData()[2], "角色")
        self.assertEqual(self.widget.items()[0][2], "角色")
        self.assertTrue(self.widget._statusEditingEnabled)

    def test_context_switch_and_rebuild_cancel_active_name_editor(self):
        popup = self.name_editor()
        popup.line.setText("不能提交")
        self.page.editor.setLoading()
        self.page.scope = ("OtherProject", "Props")
        self.page.load()
        self.app.processEvents()
        self.write.assert_not_called()
        self.assertIsNone(self.page.editor.detail_popup)
        popup = self.name_editor()
        popup.line.setText("重建取消")
        self.widget.clear()
        self.widget.addItems()
        self.app.processEvents()
        self.write.assert_not_called()

    def test_personnel_load_failure_displays_error_without_writing(self):
        self.read.side_effect = RuntimeError("user_list unavailable")
        popup = self.artist_picker()
        self.assertIn("user_list unavailable", popup.message.text())
        self.assertEqual(popup.tree.topLevelItemCount(), 0)
        self.write.assert_not_called()

    def test_late_personnel_response_cannot_replace_new_popup(self):
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def read():
            if not started.is_set():
                started.set()
                finish.wait(2)
                return {"过期": ["旧人员"]}
            return {"最新": ["新人员"]}
        self.read.side_effect = read
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.point(3))
        self.wait_until(started.is_set)
        self.page.editor._closeDetail()
        QtTest.QTest.mouseClick(self.widget.viewport(), QtCore.Qt.LeftButton, pos=self.point(5))
        self.wait_until(lambda: bool(self.page.editor.detail_popup.groups))
        finish.set()
        self.wait_until(lambda: not self.page.editor._artist_tasks)
        self.assertEqual(self.page.editor.detail_popup.groups, {"最新": ["新人员"]})

    def test_scene_chinese_name_and_artist_aliases_update_without_changing_status(self):
        self.page.editor.shutdown()
        self.page.close()
        self.page = StatusPage("scene")
        self.widget = self.page.main_listWgt
        self.app.processEvents()
        popup = self.name_editor()
        popup.line.setText("树林")
        QtTest.QTest.keyClick(popup.line, QtCore.Qt.Key_Return)
        self.wait_until(lambda: self.write.called and self.page.editor.pending is None)
        popup = self.artist_picker()
        popup._choose(popup.tree.topLevelItem(0).child(0), 0)
        self.wait_until(lambda: self.page.editor.pending is None)
        row = self.widget.items()[0]
        self.assertEqual((row[2], row[3], row[5], row[4], row[8]),
                         ("树林", "张三", "张三", "未开始", "备注"))
        self.assertEqual(self.write.call_args.args[2:5], ("Project", "scene", "Characters"))


if __name__ == "__main__":
    unittest.main()
