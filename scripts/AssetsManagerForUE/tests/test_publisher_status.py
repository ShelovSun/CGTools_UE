"""Exercise publisher metadata writes on isolated SQL, without server access."""

import base64
import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock


_WORKSPACE = Path(__file__).resolve().parents[5]
_ADAPTER = _WORKSPACE / "UE574/Plugins/Marketplace/CGToolsPublisher/Content/Python/cgtools_publisher_db.py"
_SPEC = importlib.util.spec_from_file_location("publisher_status_checks", _ADAPTER)
publisher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publisher)


class LocalCursor:
    def __init__(self, database):
        self.cursor = database.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, query, parameters):
        # Keep the actual field names, predicates and values; adapt only the
        # PostgreSQL schema prefix and parameter placeholder for local SQLite.
        query = query.replace("public.scene", "scene").replace("public.asset", "asset")
        self.cursor.execute(query.replace("%s", "?"), parameters)

    def fetchone(self):
        return self.cursor.fetchone()


class LocalConnection:
    def __init__(self, database):
        self.database = database
        self.commits = 0
        self.rollbacks = 0
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
        # Retain the local database so assertions can inspect committed rows.
        self.closed = True


class PublisherStatusTests(unittest.TestCase):
    def local_database(self, table, existing=False):
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = sqlite3.Row
        status = "mod_status" if table == "asset" else "status"
        artist = "mod_artist" if table == "asset" else "artist"
        columns = ["date", "name", "zh_name", artist, status, "icon", "type", "note"]
        if table == "asset":
            columns += ["rig_artist", "rig_status", "ue_artist", "ue_status"]
        database.execute("CREATE TABLE {0} ({1});".format(
            table, ", ".join('"{0}.{1}" TEXT'.format(table, column) for column in columns)))
        if existing:
            values = ["20260101", "Hero", "原中文名", "原制作人", "已完成",
                      "old/icon.png", "Characters", "保留审核备注"]
            if table == "asset":
                values += ["绑定制作人", "制作中", "原UE制作人", "制作中"]
            database.execute("INSERT INTO {0} VALUES ({1});".format(
                table, ", ".join("?" for _ in values)), values)
            database.commit()
        return database, LocalConnection(database), table + "." + ("ue_status" if table == "asset" else status)

    def invoke(self, connection, table, operation="write", overwrite=True,
               chinese_name="新中文名"):
        payload = {
            "project": "LocalTest", "asset_name": "Hero", "chinese_name": chinese_name,
            "asset_type": "Characters", "icon_path": "new/icon.png", "overwrite": overwrite,
        }
        request = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        with mock.patch.object(publisher, "_connect", return_value=(connection, "UE发布者")):
            response = publisher.invoke("{0}_{1}_record".format(operation, table), request)
        return json.loads(base64.b64decode(response).decode("utf-8"))

    def test_new_scene_and_asset_records_start_in_ue_status(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, status = self.local_database(table)
                result = self.invoke(connection, table)
                self.assertTrue(result["ok"], result)
                self.assertFalse(result["exists"])
                row = database.execute("SELECT * FROM " + table).fetchone()
                self.assertEqual(row[status], "已完成" if table == "asset" else "UE")
                if table == "asset":
                    self.assertEqual(row["asset.ue_artist"], "UE发布者")
                    self.assertEqual(row["asset.mod_status"], "未开始")
                    self.assertEqual(row["asset.mod_artist"], "")
                self.assertEqual(row[table + ".name"], "Hero")
                self.assertEqual(row[table + ".date"], publisher.datetime.datetime.now().strftime("%Y%m%d"))
                self.assertEqual(row[table + ".zh_name"], "新中文名")
                self.assertEqual(connection.commits, 1)
                self.assertTrue(connection.closed)

    def test_overwrite_marks_ue_and_preserves_notes_and_rig_state(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, status = self.local_database(table, existing=True)
                result = self.invoke(connection, table)
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["exists"])
                row = database.execute("SELECT * FROM " + table).fetchone()
                self.assertEqual(row[status], "已完成" if table == "asset" else "UE")
                self.assertEqual(row[table + ".date"], "20260101")
                self.assertEqual(row[table + ".zh_name"], "新中文名")
                self.assertEqual(row[table + ".note"], "保留审核备注")
                self.assertEqual(row[table + ".icon"], "new/icon.png")
                if table == "asset":
                    self.assertEqual(row["asset.ue_artist"], "UE发布者")
                    self.assertEqual(row["asset.mod_artist"], "原制作人")
                    self.assertEqual(row["asset.mod_status"], "已完成")
                    self.assertEqual(row["asset.rig_status"], "制作中")
                    self.assertEqual(row["asset.rig_artist"], "绑定制作人")
                self.assertEqual(connection.commits, 1)

    def test_blank_chinese_name_preserves_existing_name_and_creation_date(self):
        for table in ("scene", "asset"):
            for chinese_name in ("", " \t\n　", None):
                with self.subTest(table=table, chinese_name=chinese_name):
                    database, connection, status = self.local_database(table, existing=True)
                    result = self.invoke(connection, table, chinese_name=chinese_name)
                    self.assertTrue(result["ok"], result)
                    row = database.execute("SELECT * FROM " + table).fetchone()
                    self.assertEqual(row[table + ".date"], "20260101")
                    self.assertEqual(row[table + ".zh_name"], "原中文名")
                    self.assertEqual(row[table + ".icon"], "new/icon.png")
                    self.assertEqual(row[status], "已完成" if table == "asset" else "UE")
                    self.assertEqual(connection.commits, 1)

    def test_publish_never_replaces_existing_model_status_with_ue_status(self):
        for original in (None, "未开始", "制作中", "已完成", "UE"):
            with self.subTest(model_status=original):
                database, connection, _status = self.local_database("asset", existing=True)
                database.execute('UPDATE asset SET "asset.mod_status" = ?', (original,))
                database.commit()
                result = self.invoke(connection, "asset", chinese_name="")
                self.assertTrue(result["ok"], result)
                row = database.execute("SELECT * FROM asset").fetchone()
                self.assertEqual(row["asset.mod_status"], original)
                self.assertEqual(row["asset.mod_artist"], "原制作人")
                self.assertEqual(row["asset.ue_status"], "已完成")
                self.assertEqual(row["asset.ue_artist"], "UE发布者")

    def test_new_records_with_blank_chinese_name_get_creation_date(self):
        for table in ("scene", "asset"):
            for chinese_name in ("", " \t　", None):
                with self.subTest(table=table, chinese_name=chinese_name):
                    database, connection, status = self.local_database(table)
                    result = self.invoke(connection, table, chinese_name=chinese_name)
                    self.assertTrue(result["ok"], result)
                    self.assertFalse(result["exists"])
                    row = database.execute("SELECT * FROM " + table).fetchone()
                    self.assertEqual(row[table + ".zh_name"], "")
                    self.assertEqual(row[table + ".date"], publisher.datetime.datetime.now().strftime("%Y%m%d"))
                    self.assertEqual(row[status], "已完成" if table == "asset" else "UE")

    def test_blank_update_preserves_null_legacy_name_and_date(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, _status = self.local_database(table, existing=True)
                database.execute('UPDATE {0} SET "{0}.date" = NULL, "{0}.zh_name" = NULL'.format(table))
                database.commit()
                result = self.invoke(connection, table, chinese_name="")
                self.assertTrue(result["ok"], result)
                row = database.execute("SELECT * FROM " + table).fetchone()
                self.assertIsNone(row[table + ".date"])
                self.assertIsNone(row[table + ".zh_name"])

    def test_declined_overwrite_does_not_change_status_or_row(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, _status = self.local_database(table, existing=True)
                original = tuple(database.execute("SELECT * FROM " + table).fetchone())
                result = self.invoke(connection, table, overwrite=False)
                self.assertFalse(result["ok"])
                self.assertTrue(result["exists"])
                self.assertEqual(tuple(database.execute("SELECT * FROM " + table).fetchone()), original)
                self.assertEqual(connection.commits, 0)
                self.assertTrue(connection.closed)

    def test_failed_database_write_rolls_back_and_does_not_mark_ue(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, status = self.local_database(table, existing=True)
                database.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON {0} "
                                 "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END;".format(table))
                result = self.invoke(connection, table)
                self.assertFalse(result["ok"])
                self.assertIn("simulated write failure", result["error"])
                row = database.execute("SELECT * FROM " + table).fetchone()
                self.assertEqual(row[status], "制作中" if table == "asset" else "已完成")
                self.assertEqual(row[table + ".icon"], "old/icon.png")
                self.assertEqual(connection.commits, 0)
                self.assertEqual(connection.rollbacks, 1)
                self.assertTrue(connection.closed)

    def test_checking_a_record_does_not_change_its_status(self):
        for table in ("scene", "asset"):
            with self.subTest(table=table):
                database, connection, status = self.local_database(table, existing=True)
                result = self.invoke(connection, table, operation="check")
                self.assertTrue(result["ok"])
                self.assertTrue(result["exists"])
                self.assertEqual(database.execute("SELECT * FROM " + table).fetchone()[status],
                                 "制作中" if table == "asset" else "已完成")
                self.assertEqual(connection.commits, 0)


if __name__ == "__main__":
    unittest.main()
