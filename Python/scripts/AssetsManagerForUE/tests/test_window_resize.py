"""Real Qt resize events, native sizing dispatch, and content hit testing."""

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.utils.ue_window_style import UEWindowResizeBorder, apply_ue_stylesheet


class WindowResizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = QtWidgets.QWidget()
        self.window.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.window.setMinimumSize(240, 180)
        self.window.setMaximumSize(800, 600)
        self.window.setGeometry(300, 250, 500, 350)
        self.content = QtWidgets.QPushButton("Content", self.window)
        self.content.setGeometry(50, 50, 200, 100)
        apply_ue_stylesheet(self.window)
        self.border = UEWindowResizeBorder(self.window)
        self.window.show()
        self.app.processEvents()
        self.enterContext(mock.patch.object(self.border, "grabMouse"))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def positions(self):
        edge = QtCore.Qt
        return [
            (QtCore.QPoint(1, 175), edge.LeftEdge, QtCore.QRect(320, 250, 480, 350)),
            (QtCore.QPoint(498, 175), edge.RightEdge, QtCore.QRect(300, 250, 520, 350)),
            (QtCore.QPoint(250, 1), edge.TopEdge, QtCore.QRect(300, 265, 500, 335)),
            (QtCore.QPoint(250, 348), edge.BottomEdge, QtCore.QRect(300, 250, 500, 365)),
            (QtCore.QPoint(1, 1), edge.LeftEdge | edge.TopEdge, QtCore.QRect(320, 265, 480, 335)),
            (QtCore.QPoint(498, 1), edge.RightEdge | edge.TopEdge, QtCore.QRect(300, 265, 520, 335)),
            (QtCore.QPoint(1, 348), edge.LeftEdge | edge.BottomEdge, QtCore.QRect(320, 250, 480, 365)),
            (QtCore.QPoint(498, 348), edge.RightEdge | edge.BottomEdge, QtCore.QRect(300, 250, 520, 365)),
        ]

    def send_mouse(self, kind, point, global_point, button, buttons):
        event = QtGui.QMouseEvent(kind, QtCore.QPointF(point), QtCore.QPointF(global_point),
                                 button, buttons, QtCore.Qt.NoModifier)
        self.app.sendEvent(self.border, event)

    def drag(self, point, delta):
        origin = self.border.mapToGlobal(point)
        self.send_mouse(QtCore.QEvent.MouseButtonPress, point, origin,
                        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.send_mouse(QtCore.QEvent.MouseMove, point + delta, origin + delta,
                        QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        self.send_mouse(QtCore.QEvent.MouseButtonRelease, point + delta, origin + delta,
                        QtCore.Qt.LeftButton, QtCore.Qt.NoButton)

    def test_all_edges_and_corners_resize_with_opposite_edge_anchored(self):
        with mock.patch.object(self.border, "_start_system_resize", return_value=False):
            for point, edges, expected in self.positions():
                with self.subTest(edges=edges):
                    self.window.setGeometry(300, 250, 500, 350)
                    self.assertEqual(self.border._edges_at(point), edges)
                    self.drag(point, QtCore.QPoint(20, 15))
                    self.assertEqual(self.window.geometry(), expected)
                    self.assertIsNone(self.border._drag_origin)

    def test_native_resize_receives_correct_edges(self):
        handle = mock.Mock()
        handle.startSystemResize.return_value = True
        with mock.patch.object(self.window, "windowHandle", return_value=handle):
            for point, edges, _ in self.positions():
                with self.subTest(edges=edges):
                    self.send_mouse(QtCore.QEvent.MouseButtonPress, point, self.border.mapToGlobal(point),
                                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
                    handle.startSystemResize.assert_called_with(edges)
                    self.assertIsNone(self.border._drag_origin)
        self.border.grabMouse.assert_not_called()

    def test_resize_ring_does_not_intercept_content(self):
        for point, _, _ in self.positions():
            self.assertTrue(self.border.mask().contains(point))
        self.assertFalse(self.border.mask().contains(QtCore.QPoint(100, 80)))
        self.assertIs(self.window.childAt(QtCore.QPoint(100, 80)), self.content)
        self.assertFalse(self.border._edges_at(QtCore.QPoint(100, 80)))
        self.window.resize(620, 430)
        self.assertEqual(self.border.size(), self.window.size())
        self.assertTrue(self.border.mask().contains(QtCore.QPoint(618, 200)))
        self.assertFalse(self.border.mask().contains(QtCore.QPoint(300, 200)))

    def test_minimum_and_maximum_keep_opposite_corner_fixed(self):
        with mock.patch.object(self.border, "_start_system_resize", return_value=False):
            self.drag(QtCore.QPoint(1, 1), QtCore.QPoint(2000, 2000))
            self.assertEqual(self.window.geometry(), QtCore.QRect(560, 420, 240, 180))
            self.window.setGeometry(300, 250, 500, 350)
            self.drag(QtCore.QPoint(1, 1), QtCore.QPoint(-2000, -2000))
            self.assertEqual(self.window.geometry(), QtCore.QRect(0, 0, 800, 600))
            self.window.setGeometry(300, 250, 500, 350)
            self.drag(QtCore.QPoint(498, 348), QtCore.QPoint(2000, 2000))
            self.assertEqual(self.window.geometry(), QtCore.QRect(300, 250, 800, 600))

    def test_maximized_and_fullscreen_disable_then_restore_resize(self):
        for state in (QtCore.Qt.WindowMaximized, QtCore.Qt.WindowFullScreen):
            self.window.setWindowState(state)
            self.app.processEvents()
            self.assertTrue(self.border.isHidden())
            self.assertFalse(self.border._edges_at(QtCore.QPoint(1, 1)))
            self.window.showNormal()
            self.app.processEvents()
            self.assertFalse(self.border.isHidden())
            self.assertTrue(self.border._edges_at(QtCore.QPoint(1, 1)))

    def test_hover_cursors_and_fixed_dimension(self):
        for point, edges, _ in self.positions():
            self.send_mouse(QtCore.QEvent.MouseMove, point, self.border.mapToGlobal(point),
                            QtCore.Qt.NoButton, QtCore.Qt.NoButton)
            self.assertIn(self.border.cursor().shape(), (QtCore.Qt.SizeHorCursor, QtCore.Qt.SizeVerCursor,
                                                        QtCore.Qt.SizeFDiagCursor, QtCore.Qt.SizeBDiagCursor))
        self.window.setFixedWidth(500)
        self.assertFalse(self.border._edges_at(QtCore.QPoint(1, 175)))
        self.assertEqual(self.border._edges_at(QtCore.QPoint(1, 1)), QtCore.Qt.TopEdge)

    def test_assets_manager_installs_border_above_content_after_resize(self):
        from AssetsManagerForUE.AssetsManagerForUE import AssetsManagerUI

        with mock.patch.object(AssetsManagerUI, "readLoginSetting", return_value={"user": "test", "password": "test"}), \
                mock.patch.object(AssetsManagerUI, "readSettings", return_value=(None, None, 0)), \
                mock.patch.object(AssetsManagerUI, "_prepareOpenGLSurface"), \
                mock.patch.object(AssetsManagerUI, "rememberSettings"):
            window = AssetsManagerUI()
            try:
                window.resize(900, 600)
                window.show()
                self.app.processEvents()
                border = window._resize_border
                self.assertIs(window.childAt(QtCore.QPoint(1, 100)), border)
                self.assertIs(window.childAt(QtCore.QPoint(window.width() - 2, 100)), border)
                window.resize(1000, 650)
                self.app.processEvents()
                self.assertEqual(border.size(), window.size())
                self.assertIs(window.childAt(QtCore.QPoint(1, 100)), border)
                self.assertFalse(border.mask().contains(window.rect().center()))
                self.assertFalse(window._startup_load_enabled)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
