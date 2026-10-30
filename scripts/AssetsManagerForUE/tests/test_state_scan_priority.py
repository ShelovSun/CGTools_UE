"""Real Qt viewport/selection events with a gated, offline state scanner."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_asset_availability import OfflineAssetToolsUI
from AssetsManagerForUE.sources import sceneTools, ue_asset_service
from AssetsManagerForUE.utils import myWidget
from PySide6 import QtCore, QtTest, QtWidgets


class OfflineScene(sceneTools.SceneToolsUI):
    def firstView(self):
        pass

    def viewThumbnail(self):
        pass

    def _ensureScenePreviewWidget(self):
        return False

    def mainWightItemChanged(self):
        pass

    def rememberSettings(self):
        pass


class ScanPriorityFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="state_priority_")
        self.root = Path(self.temp.name)
        self.uis = []
        patch = mock.patch.object(ue_asset_service, "project_content_dir", return_value=str(self.root / "Content"))
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        for ui in self.uis:
            ui.shutdownThreads()
            ui.close()
            ui.deleteLater()
        myWidget.Item.ThreadPool.waitForDone(3000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.temp.cleanup()

    def wait_until(self, condition, timeout=4):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.002)
        self.fail("state scanner did not reach the expected point")

    def make_ui(self, scene=False, list_mode=False):
        if scene:
            with mock.patch.object(myWidget.MyThread, "start"):
                ui = OfflineScene(isSQL=False)
        else:
            ui = OfflineAssetToolsUI(isSQL=False)
        self.uis.append(ui)
        ui.resize(1050, 500)
        ui.show()
        widget = ui.main_listWgt
        widget.setIsList(list_mode)
        widget.setItemSize(120)
        widget.setMode()
        self.app.processEvents()
        return ui

    def populate(self, ui, names):
        widget = ui.main_listWgt
        widget.clear()
        rows = [(20261027, name, "", "", "UE" if isinstance(ui, OfflineScene) else "", "", "",
                 str(self.root / name / "Icon" / (name + ".png")), "", "已完成", "")
                for name in names]
        widget.setItems(rows)
        widget.addItems()
        widget.setMode()
        widget.doItemsLayout()
        ui.scanUEAssetStates()

class ScanPriorityTests(ScanPriorityFixture):
    def run_gated_scan(self, ui, interact):
        started, release = threading.Event(), threading.Event()
        calls = []

        def build(root, target, cancelled=None, **kwargs):
            calls.append(Path(root).name)
            if len(calls) == 1:
                started.set()
                if not release.wait(4):
                    raise RuntimeError("test gate timed out")
            return {"asset_root": root, "state": "missing", "source_available": False,
                    "ue_directory_exists": False, "source_message": "offline fixture"}

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build):
            try:
                self.populate(ui, ["Asset%03d" % index for index in range(60)])
                self.wait_until(started.is_set)
                expected = interact(ui)
            finally:
                release.set()
            self.wait_until(lambda: not ui._state_jobs and not ui._state_requests)
        return calls, expected

    def test_clicked_asset_is_next_on_asset_and_scene_pages(self):
        for scene in (False, True):
            with self.subTest(scene=scene):
                ui = self.make_ui(scene=scene)

                def click(page):
                    widget = page.main_listWgt
                    last = widget.item(widget.count() - 1)
                    widget.scrollToItem(last)
                    QtTest.QTest.mouseClick(widget.viewport(), QtCore.Qt.LeftButton,
                                           pos=widget.visualItemRect(last).center())
                    self.assertIs(widget.currentItem(), last)
                    return last.name()

                calls, chosen = self.run_gated_scan(ui, click)
                self.assertEqual(calls[1], chosen)
                self.assertEqual(len(calls), len(set(calls)))
                self.assertEqual(len(calls), 60)

    def test_scrolling_prioritizes_visible_cards_and_list_rows_on_both_pages(self):
        for scene in (False, True):
            for list_mode in (False, True):
                with self.subTest(scene=scene, list_mode=list_mode):
                    ui = self.make_ui(scene=scene, list_mode=list_mode)

                    def scroll(page):
                        widget = page.main_listWgt
                        widget.setCurrentRow(-1)
                        bar = widget.verticalScrollBar()
                        self.assertGreater(bar.maximum(), 0)
                        bar.setValue(bar.maximum())
                        self.wait_until(lambda: not widget._scrollTimer.isActive())
                        rect = widget.viewport().rect()
                        return [widget.item(i).name() for i in range(widget.count())
                                if rect.intersects(widget.visualItemRect(widget.item(i)))]

                    calls, visible = self.run_gated_scan(ui, scroll)
                    self.assertTrue(visible)
                    self.assertNotIn(calls[0], visible)
                    self.assertEqual(calls[1:1 + len(visible)], visible)
                    self.assertEqual(len(calls), len(set(calls)))

    def test_filter_drops_old_pending_assets_and_only_checks_the_new_results(self):
        for scene in (False, True):
            with self.subTest(scene=scene):
                ui = self.make_ui(scene=scene)

                def filter_cards(page):
                    # Same rebuilding path as search; the asset page keeps its
                    # generation, while the scene page cancels the old generation.
                    self.populate(page, ["Asset055", "Asset056"])
                    page.main_listWgt.setCurrentRow(1)
                    return page.main_listWgt.item(1).name()

                calls, chosen = self.run_gated_scan(ui, filter_cards)
                self.assertEqual(calls[1], chosen)
                self.assertEqual(set(calls[1:]), {"Asset055", "Asset056"})
                self.assertEqual(len(calls), 3)

    def test_worker_reorders_atomically_and_does_not_recheck_active_or_finished_items(self):
        worker = ue_asset_service.AssetStateWorker(7, [(name, name) for name in "ABCD"], "offline")
        entered, release = threading.Event(), threading.Event()
        calls = []

        def build(root, target, cancelled=None, **kwargs):
            calls.append(root)
            if root == "A":
                entered.set()
                release.wait(3)
            return {"asset_root": root}

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build):
            thread = threading.Thread(target=worker.run)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(worker.replace_requests(6, [("C", "C")]))
                self.assertTrue(worker.replace_requests(7, [(name, name) for name in "DABA"]))
            finally:
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(calls, ["A", "D", "B"])
        self.assertFalse(worker.replace_requests(7, [("C", "C")]))

    def test_cancelled_worker_cannot_be_revived_by_a_late_viewport_update(self):
        worker = ue_asset_service.AssetStateWorker(1, [("A", "A")], "offline")
        worker.cancel()
        self.assertFalse(worker.replace_requests(1, [("B", "B")]))
        with mock.patch.object(ue_asset_service, "build_import_plan") as build:
            worker.run()
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
