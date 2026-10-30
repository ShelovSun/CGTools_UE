"""Filtering avoids unused Qt workers/NAS calls and preserves evidence of a hang."""

import threading
import time
from unittest import mock

from test_state_scan_priority import ScanPriorityFixture
from AssetsManagerForUE.sources import ue_asset_service
from AssetsManagerForUE.utils import myWidget, search_diagnostics
from PySide6 import QtCore, QtTest


class SearchResponsivenessTests(ScanPriorityFixture):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(search_diagnostics, "log_path", return_value=self.root / "search.log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        if search_diagnostics._ACTIVE is not None:
            search_diagnostics._ACTIVE.finish()
        super().tearDown()

    def row(self, name, chinese="", suffix="png"):
        return (20261029, name, chinese, "", "", "", "",
                str(self.root / name / "Icon" / (name + "." + suffix)), "", "未开始", "")

    def test_zero_and_small_results_create_only_matching_cards(self):
        ui = self.make_ui()
        rows = [self.row("Asset%04d" % i) for i in range(3195)]
        rows.append(self.row("ChuanSongDai", "传送带"))
        ui.main_listWgt.setItems(rows)
        original = myWidget.Item.__init__
        for keyword, expected in (("chuangsongdai", 0), ("CHUANSONGDAI", 1), ("传送", 1), ("", 3196)):
            with self.subTest(keyword=keyword):
                constructed = []

                def counted(item, *args):
                    constructed.append(item)
                    original(item, *args)

                ui.key_line.setText(keyword)
                with mock.patch.object(myWidget.Item, "__init__", counted), \
                        mock.patch.object(ui, "scanUEAssetStates"), \
                        mock.patch.object(ui.main_listWgt, "_updateVisibleItems"):
                    ui.search_asset()
                self.assertEqual(ui.main_listWgt.count(), expected)
                self.assertEqual(len(constructed), expected)
                self.assertEqual(len(ui.main_listWgt.items()), 3196)

    def test_enter_uses_memory_without_database_or_main_thread_nas_access(self):
        ui = self.make_ui()
        ui.main_listWgt.setItems([self.row("ChuanSongDai")])
        ui.key_line.setText("chuansongdai")
        with mock.patch.object(ui, "_requestAssetData") as query, \
                mock.patch.object(ui, "get_database") as sync_query, \
                mock.patch.object(ui, "scanUEAssetStates"), \
                mock.patch.object(ui.main_listWgt, "_updateVisibleItems"), \
                mock.patch.object(myWidget.os.path, "isfile", side_effect=AssertionError("GUI NAS stat")), \
                mock.patch.object(myWidget.os.path, "isdir", side_effect=AssertionError("GUI NAS stat")):
            QtTest.QTest.keyClick(ui.key_line, QtCore.Qt.Key_Return)
        query.assert_not_called()
        sync_query.assert_not_called()
        self.assertEqual(ui.main_listWgt.count(), 1)
        text = (self.root / "search.log").read_text(encoding="utf-8")
        for stage in ("clear_list", "clear_preview", "sort_data", "build_filtered_cards",
                      "layout", "schedule_state_checks", "waiting_for_ui_events"):
            self.assertIn(stage, text)

    def test_still_icon_hover_does_not_stat_server_and_sequence_path_is_preserved(self):
        ui = self.make_ui()
        for extension in ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "exr"):
            item = myWidget.Item()
            item.setItemData(self.row("Image", suffix=extension))
            item.setItemsWidget(ui.main_listWgt)
            ui.main_listWgt.addItem(item)
            with mock.patch.object(myWidget.os.path, "isfile", side_effect=AssertionError("GUI NAS stat")), \
                    mock.patch.object(myWidget.os.path, "isdir", side_effect=AssertionError("GUI NAS stat")):
                item.mouseEnterEvent(None)
        item.setItemData(self.row("Image", suffix="jpg")[:7] +
                         (str(self.root / "Image/thumbnail.jpg"), "", "未开始", ""))
        self.assertTrue(item.imageSequencePath().endswith("sequence"))
        movie = mock.Mock()
        with mock.patch.object(myWidget.os.path, "isdir", return_value=True), \
                mock.patch.object(myWidget.imagesequence, "ImageSequence", return_value=movie) as sequence:
            item.play()
        sequence.assert_called_once_with(item.imageSequencePath())
        movie.start.assert_called_once()

    def test_clear_stops_hover_movie_and_drops_deleted_card_reference(self):
        ui = self.make_ui()
        item = myWidget.Item()
        item.setItemData(self.row("Animated"))
        item.setItemsWidget(ui.main_listWgt)
        ui.main_listWgt.addItem(item)
        movie = mock.Mock()
        item.setImageSequence(movie)
        ui.main_listWgt._currentItem = item
        ui.main_listWgt.clear()
        movie.stop.assert_called_once()
        self.assertIsNone(ui.main_listWgt._currentItem)

    def test_search_does_not_wait_for_an_inflight_network_scan(self):
        ui = self.make_ui()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def build(root, target, cancelled=None, **kwargs):
            calls.append(root)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            return {"asset_root": root, "state": "missing", "source_available": False}

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build):
            self.populate(ui, ["Asset%03d" % i for i in range(50)])
            self.wait_until(entered.is_set)
            ui.key_line.setText("Asset049")
            try:
                start = time.perf_counter()
                ui.search_asset()
                self.assertLess(time.perf_counter() - start, 0.3)
                self.assertEqual(ui.main_listWgt.count(), 1)
                self.assertTrue(ui._state_jobs)
            finally:
                release.set()
            self.wait_until(lambda: not ui._state_jobs and not ui._state_requests)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1].endswith("Asset049"))

    def test_native_timeout_dump_survives_the_blocked_operation(self):
        path = self.root / "timeout.log"
        trace = search_diagnostics.SearchTrace("chuangsongdai", 3196, 3196, timeout=0.05, path=path)
        try:
            trace.mark("test_blocked_phase")
            threading.Event().wait(0.12)
        finally:
            trace.finish()
        text = path.read_text(encoding="utf-8")
        self.assertIn("Timeout", text)
        self.assertIn("test_native_timeout_dump_survives_the_blocked_operation", text)
        self.assertIn("test_blocked_phase", text)
        self.assertIn('"phase": "complete"', text)
        self.assertIsNone(search_diagnostics._ACTIVE)

    def test_completed_and_replaced_searches_cancel_their_own_watchdog(self):
        first = search_diagnostics.SearchTrace("first", 1, 1, timeout=0.05, path=self.root / "first.log")
        second = search_diagnostics.SearchTrace("second", 1, 1, timeout=0.05, path=self.root / "second.log")
        self.assertTrue(first._closed)
        first.finish()  # Must not cancel the new trace.
        self.assertIs(search_diagnostics._ACTIVE, second)
        second.finish()
        threading.Event().wait(0.08)
        self.assertNotIn("Timeout", (self.root / "second.log").read_text(encoding="utf-8"))

    def test_diagnostics_write_error_does_not_break_search(self):
        ui = self.make_ui()
        ui.main_listWgt.setItems([self.row("ChuanSongDai")])
        ui.key_line.setText("chuansongdai")
        with mock.patch("pathlib.Path.open", side_effect=PermissionError("local log denied")), \
                mock.patch.object(ui.main_listWgt, "_updateVisibleItems"), \
                mock.patch.object(ui, "scanUEAssetStates"):
            ui.search_asset()
        self.assertEqual(ui.main_listWgt.count(), 1)

    def test_closing_owner_before_completion_cancels_watchdog(self):
        owner = QtCore.QObject()
        trace = search_diagnostics.SearchTrace("closing", 1, 1, path=self.root / "closing.log")
        trace.finish_after_events(owner)
        owner.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertTrue(trace._closed)
        self.assertIsNone(search_diagnostics._ACTIVE)
