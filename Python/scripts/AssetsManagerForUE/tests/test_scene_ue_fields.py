"""Scene UE fields remain independent in SQL, table sorting, badges and loading."""
import sqlite3
from pathlib import Path
import types
from unittest import mock
import unittest

from test_status_editing import LocalConnection
from test_state_scan_priority import ScanPriorityFixture
from AssetsManagerForUE.sources import sceneTools, ue_asset_service


class SceneUEMigrationTests(unittest.TestCase):
    def test_legacy_migration_preserves_other_work_and_is_repeatable(self):
        sql = (Path(__file__).resolve().parents[1] / "migrations/20261103_add_scene_ue_fields.sql").read_text(encoding="utf-8")
        update = "UPDATE scene" + sql.split("UPDATE public.scene", 1)[1]
        with sqlite3.connect(":memory:") as db:
            db.execute('CREATE TABLE scene ("scene.name", "scene.status", "scene.artist", '
                       '"scene.ue_status", "scene.ue_artist", "scene.note", "scene.date")')
            rows = [
                ("Legacy", "UE", "原发布人", "未开始", "", "保留", 20260101),
                ("Independent", "UE", "模型人", "制作中", "UE人", "保留2", 20260102),
                ("Ordinary", "已完成", "模型甲", "未开始", "", "保留3", 20260103),
                ("Null", "UE", None, None, None, "保留4", 20260104),
            ]
            db.executemany("INSERT INTO scene VALUES (?,?,?,?,?,?,?)", rows)
            db.executescript(update)
            expected = [
                ("Legacy", "已完成", "原发布人", "已完成", "原发布人", "保留", 20260101),
                ("Independent", "已完成", "模型人", "制作中", "UE人", "保留2", 20260102),
                rows[2],
                ("Null", "已完成", None, "已完成", "", "保留4", 20260104),
            ]
            self.assertEqual(db.execute("SELECT * FROM scene").fetchall(), expected)
            db.executescript(update)
            self.assertEqual(db.execute("SELECT * FROM scene").fetchall(), expected)


class SceneUEQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        fields = ("date", "name", "zh_name", "artist", "status", "icon", "note", "ue_status", "ue_artist", "type")
        self.db.execute("CREATE TABLE scene ({0})".format(
            ",".join('"scene.{0}" TEXT'.format(field) for field in fields)))
        self.rows = [
            ("20260101", "Tree", "树", "模型甲", "制作中", "Y:/Tree/Icon/Tree.png", "Z备注", "已完成", "A人员", "Props"),
            ("20260102", "Rock", "石头", "模型乙", "已完成", "Y:/Rock/Icon/Rock.png", "A备注", "制作中", "Z人员", "Props"),
            ("20260103", "Quoted", "引号", "", "未开始", "", "", "未开始", "", "Props' OR 1=1--"),
        ]
        self.db.executemany("INSERT INTO scene VALUES (?,?,?,?,?,?,?,?,?,?)", self.rows)
        self.enterContext(mock.patch.object(sceneTools.psycopg2, "connect", return_value=LocalConnection(self.db)))
        self.enterContext(mock.patch.object(sceneTools, "databaseHost", return_value="local.test"))

    def query(self, record_type):
        return sceneTools.SceneToolsUI.get_database(types.SimpleNamespace(user="user", password="test"), "Project", record_type)

    def test_query_keeps_alias_icon_and_note_indices_and_appends_ue_fields(self):
        rows = self.query("Props")
        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(row[3:7], ("模型甲", "制作中", "模型甲", "制作中"))
        self.assertEqual(row[7:], ("Y:/Tree/Icon/Tree.png", "Z备注", "已完成", "A人员"))

    def test_type_query_is_parameterized(self):
        self.assertEqual([row[1] for row in self.query("Props' OR 1=1--")], ["Quoted"])


class SceneUEUITests(ScanPriorityFixture):
    def test_columns_sort_ue_fields_and_note_independently(self):
        ui = self.make_ui(scene=True, list_mode=True)
        widget = ui.main_listWgt
        self.assertEqual(widget.listFieldIndices(), (0, 1, 2, 3, 4, 9, 10, 8))
        self.assertEqual(widget.uePublishedStatusField(), 9)
        self.assertEqual(widget.uePublishedStatusValue(), "已完成")
        self.assertNotIn("UE", widget._statusColumns[4])
        self.assertEqual(widget._statusColumns[9], ("未开始", "制作中", "已完成"))
        self.assertEqual(widget._detailColumns[10], "artist")
        rows = [
            (20260101, "Tree", "", "", "制作中", "", "制作中", "", "Z备注", "已完成", "A人员"),
            (20260102, "Rock", "", "", "已完成", "", "已完成", "", "A备注", "制作中", "Z人员"),
        ]
        for column, expected in ((5, "Rock"), (6, "Tree"), (7, "Rock")):
            ui._current_sort = (column, False)
            self.assertEqual(ui._sort_scene_data(list(rows))[0][1], expected)

    def test_scene_loading_uses_ue_status_including_in_progress_and_badge_only_completed(self):
        ui = self.make_ui(scene=True)
        for model_status, ue_status in (("UE", "未开始"), ("已完成", None),
                                         ("未开始", "制作中"), ("未开始", "已完成")):
            with self.subTest(model_status=model_status, ue_status=ue_status):
                widget = ui.main_listWgt
                widget.clear()
                widget.setItems([(20261103, "Tree", "", "", model_status, "", model_status,
                                  str(self.root / "Scenes/Props/Tree/Icon/Tree.png"), "", ue_status, "")])
                widget.addItems()
                with mock.patch.object(ue_asset_service, "build_import_plan", return_value={
                        "state": "missing", "source_available": True}) as build:
                    ui.scanUEAssetStates()
                    self.wait_until(lambda: not ui._state_jobs)
                eligible = ue_status in ("制作中", "已完成")
                self.assertEqual(build.call_count, int(eligible))
                item = widget.item(0)
                widget.setCurrentItem(item)
                self.assertEqual(ui.load_button.isEnabled(), eligible)
                self.assertEqual(item.isUEPublished(), ue_status == "已完成")

    def test_only_ue_status_edit_restarts_publication_checks(self):
        ui = self.make_ui(scene=True)
        context = ui._statusContext()
        with mock.patch.object(ui, "scanUEAssetStates") as scan:
            ui._detailSaved((*context, "Tree", 4, "已完成"))
            scan.assert_not_called()
            ui._detailSaved((*context, "Tree", 9, "制作中"))
            scan.assert_called_once()
