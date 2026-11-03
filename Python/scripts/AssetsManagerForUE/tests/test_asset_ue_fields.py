"""Check new database fields without shifting icon/note or sorting the wrong field."""

import sqlite3
import types
import unittest
from unittest import mock

from test_status_editing import LocalConnection
from AssetsManagerForUE.sources import assetTools, asset_backend


class AssetUEFieldsTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        columns = ("date", "name", "zh_name", "mod_artist", "mod_status",
                   "rig_artist", "rig_status", "icon", "note", "ue_status", "ue_artist", "type")
        self.database.execute("CREATE TABLE asset ({0})".format(
            ", ".join('"asset.{0}" TEXT'.format(column) for column in columns)))
        self.rows = [
            ("20260101", "Hero", "角色", "模型人", "制作中", "绑定人", "已完成",
             "Y:/Hero/Icon/Hero.png", "A备注", "已完成", "Z人员", "Characters"),
            ("20260102", "Prop", "道具", "其他模型", "已完成", "其他绑定", "未开始",
             "Y:/Prop/Icon/Prop.png", "Z备注", "制作中", "A人员", "Props"),
        ]
        self.database.executemany("INSERT INTO asset VALUES ({0})".format(
            ", ".join("?" for _ in columns)), self.rows)
        self.connection = LocalConnection(self.database)
        self.enterContext(mock.patch("psycopg2.connect", return_value=self.connection))
        self.enterContext(mock.patch.object(assetTools, "databaseHost", return_value="local.test"))

    def test_asset_page_reads_ue_fields_without_shifting_existing_package_fields(self):
        rows = assetTools._fetch_database("user", "password", "Project", "Characters")
        self.assertEqual(rows, [self.rows[0][:-1]])
        self.assertEqual((rows[0][7], rows[0][8], rows[0][9], rows[0][10]),
                         ("Y:/Hero/Icon/Hero.png", "A备注", "已完成", "Z人员"))

    def test_native_backend_returns_independent_ue_fields_and_filters_type(self):
        with mock.patch.object(asset_backend, "_login", return_value=("user", "password")), \
                mock.patch("AssetsManagerForUE.config.databaseHost", return_value="local.test"):
            rows = asset_backend.query_assets("Project", "Characters")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["mod_status"], rows[0]["rig_status"], rows[0]["ue_status"], rows[0]["ue_artist"]),
                         ("制作中", "已完成", "已完成", "Z人员"))
        self.assertEqual((rows[0]["icon"], rows[0]["folder"]), ("Y:/Hero/Icon/Hero.png", "Y:/Hero"))

    def test_ue_columns_and_note_sort_by_their_own_values(self):
        for column, first_name in ((7, "Prop"), (8, "Prop"), (9, "Hero")):
            with self.subTest(column=column):
                page = types.SimpleNamespace(_current_sort=(column, False))
                rows = assetTools.AssetToolsUI._sort_data(page, [row[:-1] for row in self.rows])
                self.assertEqual(rows[0][1], first_name)


if __name__ == "__main__":
    unittest.main()
