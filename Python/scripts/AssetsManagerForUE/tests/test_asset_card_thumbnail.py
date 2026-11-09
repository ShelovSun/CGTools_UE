"""Actual Qt image composition, worker affinity and card refresh/scroll safety."""

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.utils import asset_card_thumbnail as cards, myWidget


class AssetCardThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asset_skin_cards_")
        self.root = Path(self.temp.name)
        self.icon = self.root / "Assets/Characters/Hero/Icon/Hero.png"
        self.icon.parent.mkdir(parents=True)
        self.fbx = self.icon.parent.parent / "FBX"
        self.fbx.mkdir()
        self.write_image(self.icon, "magenta")
        self.views = []

    def tearDown(self):
        for view in self.views:
            view.clear()
            view.close()
        myWidget.Item.ThreadPool.waitForDone(5000)
        self.app.processEvents()
        self.temp.cleanup()

    def write_image(self, path, color, size=(150, 150)):
        image = QtGui.QImage(*size, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor(color))
        self.assertTrue(image.save(str(path)))
        return image

    def skin(self, name, color, paired=True, ext=".png"):
        path = self.icon.parent / ("Hero_" + name + ext)
        self.write_image(path, color)
        if paired:
            (self.fbx / (path.stem + ".FBX")).write_bytes(b"not parsed")
        return path

    def load(self, **kwargs):
        return cards.load_card_image(str(self.icon), "Hero", edge=150, **kwargs)

    def wait(self, condition, timeout=4):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.002)
        self.fail("Thumbnail callback did not finish")

    def item(self):
        view = myWidget.MainQListWiget()
        self.views.append(view)
        item = myWidget.Item()
        item.setItemData((20261109, "Hero", "英雄", "", "", "", "", str(self.icon), "", "已完成", ""))
        item.setItemsWidget(view)
        view.addItem(item)
        item.setVisibleInViewport(True)
        self.wait(lambda: not item._thumbnailLoading)
        return item

    def test_two_skins_match_maya_big_left_and_narrow_right(self):
        self.skin("A", "red")
        self.skin("B", "blue")
        image = self.load()
        rects = cards.surface_icon_rects(150, 2)
        self.assertEqual(image.size(), QtCore.QSize(150, 150))
        self.assertGreater(rects[0].width(), rects[1].width() * 2)
        self.assertEqual(image.pixelColor(rects[0].center()), QtGui.QColor("red"))
        self.assertEqual(image.pixelColor(rects[1].center()), QtGui.QColor("blue"))

    def test_four_skins_natural_order_and_unpaired_icons_ignored(self):
        self.skin("10", "blue")
        self.skin("2", "green", ext=".JPG")
        self.skin("1", "red")
        self.skin("3", "yellow")
        self.skin("0", "black", paired=False)
        image = self.load()
        for rect, color in zip(cards.surface_icon_rects(150, 4), ("red", "green", "yellow", "blue")):
            pixel = image.pixelColor(rect.center())
            expected = QtGui.QColor(color)
            self.assertLess(max(abs(pixel.red() - expected.red()), abs(pixel.green() - expected.green()),
                                abs(pixel.blue() - expected.blue())), 4)

    def test_single_or_unpaired_skin_keeps_database_icon(self):
        self.skin("1", "red")
        self.skin("2", "blue", paired=False)
        self.assertEqual(self.load().pixelColor(20, 20), QtGui.QColor("magenta"))

    def test_unrelated_path_does_not_scan_directories_and_single_image_keeps_aspect(self):
        path = self.root / "Scenes_Icon.png"
        self.write_image(path, "blue", size=(1000, 500))
        with mock.patch.object(cards, "discoverSurfaceVariants", side_effect=AssertionError("unrelated directory scan")):
            image = cards.load_card_image(str(path), "Hero", edge=150)
        self.assertEqual(image.size(), QtCore.QSize(150, 75))

    def test_cover_crops_at_center_instead_of_stretching(self):
        first = self.skin("A", "red")
        image = self.write_image(first, "red", size=(450, 150))
        painter = QtGui.QPainter(image)
        painter.fillRect(QtCore.QRect(190, 0, 70, 150), QtGui.QColor("green"))
        painter.end()
        image.save(str(first))
        self.skin("B", "blue")
        self.assertEqual(self.load().pixelColor(50, 75), QtGui.QColor("green"))

    def test_missing_main_icon_still_composes_and_corrupt_skin_falls_back(self):
        first = self.skin("A", "red")
        self.skin("B", "blue")
        self.icon.unlink()
        self.assertEqual(self.load().pixelColor(30, 30), QtGui.QColor("red"))
        self.write_image(self.icon, "magenta")
        first.write_bytes(b"broken png")
        self.assertEqual(self.load().pixelColor(30, 30), QtGui.QColor("magenta"))
        self.assertEqual(self.load().pixelColor(125, 75), QtGui.QColor("blue"))

    def test_worker_decodes_and_composes_off_gui_then_installs_on_gui(self):
        self.skin("A", "red")
        self.skin("B", "blue")
        main = threading.get_ident()
        threads, installed_threads = [], []
        original = cards.discoverSurfaceVariants
        original_install = myWidget.Item._thumbnailFromImage
        def discover(*args):
            threads.append(threading.get_ident())
            return original(*args)
        def install(item, image):
            installed_threads.append(threading.get_ident())
            return original_install(item, image)
        with mock.patch.object(cards, "discoverSurfaceVariants", side_effect=discover), \
                mock.patch.object(myWidget.Item, "_thumbnailFromImage", install):
            item = self.item()
        self.assertTrue(threads and all(thread != main for thread in threads))
        self.assertEqual(installed_threads, [main])
        self.assertEqual(item._srcPixmap.toImage().pixelColor(20, 20), QtGui.QColor("red"))
        self.assertEqual(item._srcPixmap.size(), QtCore.QSize(512, 512))
        with mock.patch.object(cards, "discoverSurfaceVariants", side_effect=AssertionError("paint IO")):
            view = item.itemsWidget()
            view.resize(360, 240)
            view.show()
            self.app.processEvents()
            view.grab()
            view.setItemSize(160)
            view.setMode()
            view.grab()
        self.assertFalse(item._thumbnailLoading)

    def test_hidden_worker_skips_before_any_directory_or_image_reads(self):
        worker = myWidget.ImageWorker()
        worker.setPath(str(self.icon))
        worker.setAssetName("Hero")
        worker.setShouldLoad(lambda: False)
        skipped, loaded = [], []
        worker.signals.skipped.connect(lambda: skipped.append(True))
        worker.signals.triggered.connect(loaded.append)
        with mock.patch.object(myWidget, "load_card_image", side_effect=AssertionError("hidden IO")):
            worker.run()
        self.assertEqual(skipped, [True])
        self.assertEqual(loaded, [])

    def test_scroll_away_during_discovery_stops_before_decoding(self):
        wanted = [True]
        def discover(*args):
            wanted[0] = False
            return [("1", "unused", "unused"), ("2", "unused", "unused")]
        with mock.patch.object(cards, "discoverSurfaceVariants", side_effect=discover), \
                mock.patch.object(cards, "_read_image", side_effect=AssertionError("stale decode")):
            self.assertIsNone(self.load(should_load=lambda: wanted[0]))

    def test_refresh_finds_new_skin_and_screenshot_does_not_leave_single_icon(self):
        self.skin("A", "red")
        item = self.item()
        self.assertEqual(item._srcPixmap.toImage().pixelColor(20, 20), QtGui.QColor("magenta"))
        self.skin("B", "blue")
        item.update()
        item.requestThumbnailLoad()
        self.wait(lambda: not item._thumbnailLoading)
        self.assertEqual(item._srcPixmap.toImage().pixelColor(20, 20), QtGui.QColor("red"))
        fresh = self.write_image(self.icon, "yellow")
        item.setThumbnailImage(fresh)
        self.wait(lambda: not item._thumbnailLoading)
        self.assertEqual(item._srcPixmap.toImage().pixelColor(20, 20), QtGui.QColor("red"))
        self.assertEqual(QtGui.QImage(str(self.icon)).pixelColor(20, 20), QtGui.QColor("yellow"))

    def test_deleted_card_ignores_queued_worker_result(self):
        item = self.item()
        view = item.itemsWidget()
        image = item._srcPixmap.toImage()
        view.clear()
        item._thumbnailFromImage(image)
        self.assertEqual(view.count(), 0)

    def test_inflight_old_composite_cannot_replace_fresh_screenshot(self):
        self.skin("A", "red")
        self.skin("B", "blue")
        item = self.item()
        entered, release = threading.Event(), threading.Event()
        original = myWidget.load_card_image
        calls = []
        def gated(*args):
            image = original(*args)
            calls.append(True)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            return image
        with mock.patch.object(myWidget, "load_card_image", side_effect=gated):
            item.update()
            item.requestThumbnailLoad()
            self.wait(entered.is_set)
            self.skin("A", "green")
            item.setThumbnailImage(self.write_image(self.icon, "yellow"))
            release.set()
            self.wait(lambda: len(calls) == 2 and not item._thumbnailLoading)
        self.assertEqual(item._srcPixmap.toImage().pixelColor(20, 20), QtGui.QColor("green"))


if __name__ == "__main__":
    unittest.main()
