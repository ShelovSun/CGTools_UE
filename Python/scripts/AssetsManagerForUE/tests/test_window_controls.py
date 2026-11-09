"""Exercise the actual title buttons and window states with Qt mouse events."""

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PySide6 import QtCore, QtTest, QtWidgets
from AssetsManagerForUE.AssetsManagerForUE import AssetsManagerUI
from AssetsManagerForUE.utils.ue_window_style import UEWindowTitleBar


class WindowControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        for name, value in (
                ("readLoginSetting", {"user": "test", "password": "test"}),
                ("readSettings", (None, None, 0)),
                ("_prepareOpenGLSurface", None),
                ("rememberSettings", None)):
            self.enterContext(mock.patch.object(AssetsManagerUI, name, return_value=value))
        self.window = AssetsManagerUI()
        self.window.setGeometry(100, 100, 1000, 650)
        self.window.show()
        self.app.processEvents()
        self.bar = self.window.title_bar

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def click(self, button):
        QtTest.QTest.mouseClick(button, QtCore.Qt.LeftButton)
        self.app.processEvents()

    def capture(self, name, widget):
        directory = os.environ.get("CGTOOLS_WINDOW_CONTROLS_CAPTURE")
        if directory:
            path = Path(directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path)))

    def test_three_visible_buttons_receive_clicks_and_title_stays_centered(self):
        buttons = (self.bar.minimize_button, self.bar.maximize_button, self.bar.close_button)
        centers = []
        for button in buttons:
            self.assertTrue(button.isVisible())
            center = button.mapTo(self.window, button.rect().center())
            centers.append(center.x())
            self.assertIs(self.window.childAt(center), button)
        self.assertEqual(centers, sorted(centers))
        title_center = self.bar.title_label.mapTo(self.window, self.bar.title_label.rect().center())
        self.assertLessEqual(abs(title_center.x() - self.window.rect().center().x()), 1)
        self.assertFalse(self.window._startup_load_enabled)
        self.capture("AssetsManager.png", self.window)
        self.capture("TitleBar.png", self.bar)
        self.click(self.bar.close_button)
        self.assertFalse(self.window.isVisible())

    def test_maximize_and_restore_preserve_geometry_and_resize_border(self):
        original = self.window.geometry()
        self.click(self.bar.maximize_button)
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.window._resize_border.isHidden())
        self.assertEqual(self.bar.maximize_button.toolTip(), "还原")
        self.capture("TitleBarMaximized.png", self.bar)
        self.click(self.bar.maximize_button)
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.geometry(), original)
        self.assertFalse(self.window._resize_border.isHidden())
        self.assertEqual(self.bar.maximize_button.toolTip(), "最大化")

    def test_minimize_and_restore_normal_window(self):
        original = self.window.geometry()
        self.click(self.bar.minimize_button)
        self.assertTrue(self.window.isMinimized())
        self.window.showNormal()
        self.app.processEvents()
        self.assertFalse(self.window.isMinimized())
        self.assertEqual(self.window.geometry(), original)

    def test_minimize_maximized_window_and_restore_maximized_state(self):
        self.click(self.bar.maximize_button)
        self.click(self.bar.minimize_button)
        self.assertTrue(self.window.isMinimized())
        self.window.showMaximized()
        self.app.processEvents()
        self.assertFalse(self.window.isMinimized())
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.bar.maximize_button.toolTip(), "还原")
        self.click(self.bar.maximize_button)
        self.assertFalse(self.window.isMaximized())

    def test_double_click_and_maximize_button_share_the_same_state(self):
        QtTest.QTest.mouseDClick(self.bar, QtCore.Qt.LeftButton, pos=self.bar.rect().center())
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.bar.maximize_button.toolTip(), "还原")
        self.click(self.bar.maximize_button)
        self.assertFalse(self.window.isMaximized())
        self.click(self.bar.maximize_button)
        QtTest.QTest.mouseDClick(self.bar, QtCore.Qt.LeftButton, pos=self.bar.rect().center())
        self.app.processEvents()
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.bar.maximize_button.toolTip(), "最大化")

    def test_external_window_state_changes_update_controls(self):
        for state in (QtCore.Qt.WindowMaximized, QtCore.Qt.WindowFullScreen):
            self.window.setWindowState(state)
            self.app.processEvents()
            self.assertEqual(self.bar.maximize_button.toolTip(), "还原")
            self.assertEqual(self.bar.maximize_button.accessibleName(), "还原")
            self.click(self.bar.maximize_button)
            self.assertFalse(self.window.isMaximized())
            self.assertFalse(self.window.isFullScreen())
            self.assertEqual(self.bar.maximize_button.toolTip(), "最大化")

    def test_shared_dialog_keeps_only_close_and_rejects_on_click(self):
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        layout = QtWidgets.QVBoxLayout(dialog)
        bar = UEWindowTitleBar(dialog, "Dialog", close_callback=dialog.reject)
        layout.addWidget(bar)
        rejected = mock.Mock()
        dialog.rejected.connect(rejected)
        dialog.show()
        self.app.processEvents()
        try:
            self.assertIsNone(bar.minimize_button)
            self.assertIsNone(bar.maximize_button)
            self.assertTrue(bar.close_button.isVisible())
            self.click(bar.close_button)
            rejected.assert_called_once_with()
            self.assertFalse(dialog.isVisible())
        finally:
            dialog.close()
            dialog.deleteLater()

    def attach_native_owner(self):
        if os.name != "nt" or self.app.platformName() != "windows":
            self.skipTest("Requires Windows native ownership, as used by UE Slate")
        owner = QtWidgets.QWidget()
        owner.setGeometry(70, 90, 1100, 720)
        owner.show()
        self.app.processEvents()
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        api.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        api.SetWindowLongPtrW(int(self.window.winId()), -8, int(owner.winId()))
        self.addCleanup(owner.deleteLater)
        self.addCleanup(owner.close)
        return owner

    def test_owned_minimize_shows_only_caption_at_owner_bottom_left_and_follows_owner(self):
        owner = self.attach_native_owner()
        original = self.window.geometry()
        self.click(self.bar.minimize_button)
        controller = self.window._window_minimizer
        strip = controller._bar
        self.assertTrue(controller._collapsed)
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.isMinimized())
        self.assertEqual(self.window.geometry(), original)
        self.assertTrue(strip.isVisible())
        self.assertEqual(strip.height(), UEWindowTitleBar.HEIGHT + 2)
        expected = owner.mapToGlobal(QtCore.QPoint(2, owner.height() - strip.height() - 2))
        self.assertEqual(strip.pos(), expected)
        for button in (strip.title_bar.minimize_button, strip.title_bar.maximize_button,
                       strip.title_bar.close_button):
            self.assertTrue(button.isVisible())
            self.assertIs(strip.childAt(button.mapTo(strip, button.rect().center())), button)
        self.assertEqual(strip.title_bar.maximize_button.toolTip(), "还原窗口")
        self.assertEqual(strip.title_bar.maximize_button.accessibleName(), "还原窗口")
        self.capture("OwnedMinimizedStrip.png", strip)
        owner.setGeometry(130, 140, 1050, 680)
        QtTest.QTest.qWait(250)
        self.app.processEvents()
        self.assertEqual(strip.pos(), owner.mapToGlobal(
            QtCore.QPoint(2, owner.height() - strip.height() - 2)))
        self.click(strip.title_bar.minimize_button)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.geometry(), original)
        self.assertFalse(strip.isVisible())
        self.assertFalse(controller._timer.isActive())

    def test_owned_strip_middle_button_restores_saved_normal_and_maximized_states(self):
        self.attach_native_owner()
        normal = self.window.geometry()
        self.click(self.bar.maximize_button)
        self.click(self.bar.minimize_button)
        controller = self.window._window_minimizer
        self.assertTrue(controller._collapsed)
        self.assertTrue(self.window.isMaximized())
        self.click(controller._bar.title_bar.maximize_button)
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.window.isVisible())
        self.click(self.bar.maximize_button)
        self.assertEqual(self.window.geometry(), normal)
        self.click(self.bar.minimize_button)
        self.click(controller._bar.title_bar.maximize_button)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.geometry(), normal)
        self.assertFalse(controller._collapsed)
        self.assertFalse(controller._bar.isVisible())
        self.assertFalse(controller._timer.isActive())

    def test_owned_strip_double_click_reopen_and_close_leave_no_orphan(self):
        self.attach_native_owner()
        self.click(self.bar.minimize_button)
        controller = self.window._window_minimizer
        strip = controller._bar
        QtTest.QTest.mouseDClick(strip.title_bar, QtCore.Qt.LeftButton,
                                pos=strip.title_bar.rect().center())
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(controller._collapsed)
        self.click(self.bar.minimize_button)
        self.window.show()
        self.app.processEvents()
        self.assertFalse(strip.isVisible())
        self.assertFalse(controller._collapsed)
        self.click(self.bar.minimize_button)
        self.click(strip.title_bar.close_button)
        self.assertFalse(self.window.isVisible())
        self.assertFalse(strip.isVisible())
        self.assertFalse(controller._timer.isActive())


if __name__ == "__main__":
    unittest.main()
