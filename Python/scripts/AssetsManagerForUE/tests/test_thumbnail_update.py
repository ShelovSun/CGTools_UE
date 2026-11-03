"""Real Qt cards/files and asynchronous screenshot completion (native UI mocked)."""

import os
import threading
from pathlib import Path
from unittest import mock

from test_state_scan_priority import ScanPriorityFixture
from AssetsManagerForUE.utils import myWidget, thumbnail_update as thumbnails
from PySide6 import QtCore, QtGui, QtWidgets
import unreal


class ThumbnailUpdateTests(ScanPriorityFixture):
    def tearDown(self):
        self.wait_until(lambda: not thumbnails._UPDATES)
        super().tearDown()

    def image(self, color="red"):
        image = QtGui.QImage(80, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor(color))
        return image

    def destination(self, suffix="png", missing_icon_folder=False):
        path = self.root / "Hero" / "Icon" / ("Hero." + suffix)
        path.parent.parent.mkdir(exist_ok=True)
        if not missing_icon_folder:
            path.parent.mkdir(exist_ok=True)
        return path

    def capture_file(self):
        path = self.root / "capture.png"
        self.assertTrue(self.image().save(str(path), "PNG"))
        return path

    def card(self, ui, destination, name="Hero"):
        item = myWidget.Item()
        item.setItemData((20261029, name, "", "", "", "", "", str(destination), "", "未开始", ""))
        ui.main_listWgt.addItem(item)
        item.setItemsWidget(ui.main_listWgt)
        item.setVisibleInViewport(False, autoload=False)
        return item

    def test_menu_present_for_unloaded_asset_and_scene_with_no_icon(self):
        for scene in (False, True):
            ui = self.make_ui(scene=scene)
            path = self.destination()
            item = self.card(ui, path)
            ui.main_listWgt.doItemsLayout()
            menus = []
            with mock.patch.object(QtWidgets.QMenu, "exec_", lambda menu, *args: menus.append(menu)):
                ui.show_menu(ui.main_listWgt.visualItemRect(item).center())
            actions = {action.text(): action for action in menus[0].actions()}
            action = actions["更新缩略图"]
            self.assertTrue(action.isEnabled())
            self.assertFalse(action.icon().isNull())
            self.assertFalse(path.exists())

    def test_menu_disabled_without_a_usable_database_icon_path(self):
        ui = self.make_ui()
        for path in ("", "relative.png", str(self.root / "unsupported.exe")):
            menu = QtWidgets.QMenu(ui)
            item = self.card(ui, path)
            self.assertFalse(thumbnails.add_menu_action(menu, ui, item).isEnabled())

    def test_atomic_save_preserves_path_and_real_png_jpeg_encoding(self):
        for extension, magic in (("png", b"\x89PNG"), ("jpg", b"\xff\xd8")):
            path = self.destination(extension)
            self.image("blue").save(str(path))
            image = thumbnails.save_thumbnail(str(self.capture_file()), str(path))
            self.assertTrue(path.read_bytes().startswith(magic))
            self.assertGreater(image.pixelColor(10, 10).red(), 240)
            self.assertEqual(list(path.parent.glob("*." + extension)), [path])

    def test_missing_icon_directory_is_created_but_missing_asset_is_not(self):
        path = self.destination(missing_icon_folder=True)
        capture = self.capture_file()
        thumbnails.save_thumbnail(str(capture), str(path))
        self.assertTrue(path.is_file())
        absent = self.root / "Absent" / "Icon" / "Absent.png"
        with self.assertRaisesRegex(OSError, "资产文件夹不存在"):
            thumbnails.save_thumbnail(str(capture), str(absent))
        self.assertFalse(absent.parent.parent.exists())

    def test_encoding_and_commit_failure_leave_original_unchanged(self):
        path = self.destination()
        self.image("blue").save(str(path))
        original = path.read_bytes()
        capture = self.capture_file()
        with mock.patch.object(QtGui.QImage, "save", return_value=False):
            with self.assertRaisesRegex(OSError, "编码失败"):
                thumbnails.save_thumbnail(str(capture), str(path))
        self.assertEqual(path.read_bytes(), original)
        real_save_file = QtCore.QSaveFile

        class FailedCommit(real_save_file):
            def commit(self):
                self.cancelWriting()
                super().commit()
                return False

        with mock.patch.object(thumbnails.QtCore, "QSaveFile", FailedCommit):
            with self.assertRaisesRegex(OSError, "替换失败"):
                thumbnails.save_thumbnail(str(capture), str(path))
        self.assertEqual(path.read_bytes(), original)

    def test_refresh_changes_matching_cards_and_ignores_pending_old_decode(self):
        ui = self.make_ui()
        path = self.destination()
        item = self.card(ui, path)
        other = self.card(ui, self.root / "Other.png", "Other")
        other.setThumbnailImage(self.image("blue"))
        item._thumbnailLoading = True
        item._pendingThumbnailPath = str(path)
        ui.main_listWgt.setCurrentItem(item)
        thumbnails.refresh_cards(ui, str(path), self.image())
        self.assertTrue(item._thumbnailLoading)
        item._thumbnailFromImage(self.image("blue"))
        self.assertFalse(item._thumbnailLoading)
        self.assertEqual(item._srcPixmap.toImage().pixelColor(5, 5), QtGui.QColor("red"))
        self.assertEqual(other._srcPixmap.toImage().pixelColor(5, 5), QtGui.QColor("blue"))
        self.assertIs(ui.main_listWgt.currentItem(), item)
        self.assertEqual(ui.main_listWgt.count(), 2)

    def test_fresh_image_survives_skipped_worker_without_requeue(self):
        ui = self.make_ui()
        item = self.card(ui, self.destination())
        item._thumbnailLoading = True
        item.setThumbnailImage(self.image())
        item._isVisibleInViewport = True
        with mock.patch.object(item.ThreadPool, "start") as start:
            item._thumbnailLoadSkipped()
        start.assert_not_called()
        self.assertFalse(item._ignorePendingThumbnail)
        self.assertFalse(item._thumbnailLoading)

    def test_large_screenshot_keeps_full_file_and_bounds_the_card_cache(self):
        ui = self.make_ui()
        path = self.destination()
        item = self.card(ui, path)
        image = QtGui.QImage(2000, 1000, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        capture = self.root / "large.png"
        image.save(str(capture), "PNG")
        saved = thumbnails.save_thumbnail(str(capture), str(path))
        thumbnails.refresh_cards(ui, str(path), saved)
        self.assertEqual(QtGui.QImage(str(path)).size(), QtCore.QSize(2000, 1000))
        self.assertLessEqual(item._srcPixmap.width(), myWidget.Item.MAX_ICON_SIZE * 2)
        self.assertEqual(item._srcPixmap.width(), item._srcPixmap.height() * 2)

    def run_capture(self, ui, path, capture, write=None):
        library = type("Library", (), {"capture_screenshot_to_file": staticmethod(capture)})
        patches = [mock.patch.object(unreal, "CGToolsPublisherLibrary", library, create=True),
                   mock.patch.object(QtWidgets.QMessageBox, "warning")]
        if write is not None:
            patches.append(mock.patch.object(thumbnails, "save_thumbnail", side_effect=write))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            thumbnails.start_update(ui, str(path))
            self.assertFalse(ui.window().isVisible())
            self.wait_until(lambda: not thumbnails._UPDATES)
        self.assertTrue(ui.window().isVisible())
        self.assertIsNone(thumbnails._CAPTURING)

    def test_confirm_writes_in_background_and_refreshes_the_existing_card(self):
        ui = self.make_ui()
        path = self.destination()
        item = self.card(ui, path)
        owner_thread = threading.get_ident()
        real_save = thumbnails.save_thumbnail

        def capture(filename):
            self.assertFalse(ui.window().isVisible())
            self.image().save(filename, "PNG")
            return True, ""

        def save(source, destination):
            self.assertNotEqual(threading.get_ident(), owner_thread)
            return real_save(source, destination)

        self.run_capture(ui, path, capture, save)
        self.assertTrue(path.is_file())
        self.assertIs(ui.main_listWgt.item(0), item)
        self.assertEqual(item._srcPixmap.toImage().pixelColor(5, 5), QtGui.QColor("red"))

    def test_cancel_and_capture_exception_restore_window_and_keep_original(self):
        ui = self.make_ui()
        path = self.destination()
        self.image("blue").save(str(path))
        original = path.read_bytes()
        for capture in (lambda filename: (False, ""), mock.Mock(side_effect=RuntimeError("capture failed"))):
            self.run_capture(ui, path, capture)
            self.assertEqual(path.read_bytes(), original)

    def test_write_error_restores_window_and_keeps_original(self):
        ui = self.make_ui()
        path = self.destination()
        self.image("blue").save(str(path))
        original = path.read_bytes()
        self.run_capture(ui, path, lambda filename: (True, ""),
                         mock.Mock(side_effect=PermissionError("NAS denied")))
        self.assertEqual(path.read_bytes(), original)

    def test_navigation_during_save_does_not_update_an_unrelated_card(self):
        ui = self.make_ui()
        path = self.destination()
        self.card(ui, path)
        started, release = threading.Event(), threading.Event()
        real_save = thumbnails.save_thumbnail
        calls = []

        def capture(filename):
            calls.append(filename)
            self.image().save(filename, "PNG")
            return True, ""

        def save(source, destination):
            started.set()
            release.wait(4)
            return real_save(source, destination)

        library = type("Library", (), {"capture_screenshot_to_file": staticmethod(capture)})
        with mock.patch.object(unreal, "CGToolsPublisherLibrary", library, create=True), \
                mock.patch.object(thumbnails, "save_thumbnail", side_effect=save):
            thumbnails.start_update(ui, str(path))
            thumbnails.start_update(ui, str(path))  # Duplicate capture is ignored.
            self.wait_until(started.is_set)
            ui.main_listWgt.clear()
            other = self.card(ui, self.root / "Other.png", "Other")
            other.setThumbnailImage(self.image("blue"))
            thumbnails.start_update(ui, str(path))  # Duplicate save is also ignored.
            release.set()
            self.wait_until(lambda: not thumbnails._UPDATES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(other._srcPixmap.toImage().pixelColor(5, 5), QtGui.QColor("blue"))
        self.assertTrue(path.is_file())
