"""A caption-only minimized window for frameless tools owned by Unreal."""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from .ue_window_style import UEWindowFrameOverlay, UEWindowTitleBar


class _MinimizedTitleBar(UEWindowTitleBar):
    def _sync_window_controls(self):
        # The compact window always restores the saved main window state.
        if self.maximize_button is not None:
            self.maximize_button.setGlyph("restore")
            self.maximize_button.setToolTip(u"还原窗口")
            self.maximize_button.setAccessibleName(u"还原窗口")

    def mouseMoveEvent(self, event):
        # The strip stays anchored to the owner rather than being draggable.
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._restore_callback()
            event.accept()
        else:
            super(_MinimizedTitleBar, self).mouseDoubleClickEvent(event)


class UEWindowMinimizeController(QtCore.QObject):
    """Hide the intact main UI and show only its controls at the UE bottom left.

    Win32's minimized frameless owned windows have no native caption to draw.
    A separate strip avoids clipping the content or changing its layout/geometry.
    The strip is owned directly by UE, so it follows UE's minimize/restore too.
    """

    WIDTH = 400
    MARGIN = 2

    def __init__(self, window):
        super(UEWindowMinimizeController, self).__init__(window)
        self._window = window
        self._bar = None
        self._owner_window = None
        self._owner_hwnd = 0
        self._collapsed = False
        self._restore_state = QtCore.Qt.WindowNoState
        self._restore_geometry = QtCore.QRect()
        self._api = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._position_bar)
        window.installEventFilter(self)

    def _find_owner(self):
        if os.name != "nt":
            return 0
        import ctypes
        from ctypes import wintypes

        if self._api is None:
            self._api = ctypes.WinDLL("user32", use_last_error=True)
            self._api.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            self._api.GetWindow.restype = wintypes.HWND
            self._api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self._api.GetClientRect.restype = wintypes.BOOL
            self._api.IsWindow.argtypes = [wintypes.HWND]
            self._api.IsWindow.restype = wintypes.BOOL
            self._api.IsIconic.argtypes = [wintypes.HWND]
            self._api.IsIconic.restype = wintypes.BOOL
            self._api.GetDpiForWindow.argtypes = [wintypes.HWND]
            self._api.GetDpiForWindow.restype = wintypes.UINT
        # UE parent_external_window_to_slate sets GWL_HWNDPARENT (owner),
        # not a QWidget parent. GW_OWNER is therefore the authoritative handle.
        return int(self._api.GetWindow(int(self._window.winId()), 4) or 0)

    def _owner_rect(self):
        import ctypes
        from ctypes import wintypes

        if (not self._api.IsWindow(self._owner_hwnd)
                or self._api.IsIconic(self._owner_hwnd)):
            return None
        rect = wintypes.RECT()
        if not self._api.GetClientRect(self._owner_hwnd, ctypes.byref(rect)):
            return None
        # Qt maps the native client's origin into logical screen coordinates;
        # client dimensions use the owner's actual per-monitor Windows DPI.
        origin = self._owner_window.mapToGlobal(QtCore.QPoint(0, 0))
        ratio = (self._api.GetDpiForWindow(self._owner_hwnd) or 96) / 96.0
        bounds = QtCore.QRect(origin, QtCore.QSize(
            round((rect.right - rect.left) / ratio),
            round((rect.bottom - rect.top) / ratio)))
        # Maximized Windows frames can extend a few invisible pixels beyond
        # the monitor. Keep the entire strip inside the visible work area.
        screen = QtGui.QGuiApplication.screenAt(bounds.center())
        if screen is not None:
            visible = bounds.intersected(screen.availableGeometry())
            if visible.isValid():
                return visible
        return bounds

    def _create_bar(self):
        bar = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        bar.setObjectName("AssetsManagerMinimizedWindow")
        bar.setWindowTitle(self._window.windowTitle())
        bar.setWindowIcon(self._window.windowIcon())
        root = QtWidgets.QVBoxLayout(bar)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        bar.title_bar = _MinimizedTitleBar(
            bar, self._window.windowTitle(), close_callback=self._window.close,
            allow_minimize=True, allow_maximize=True,
            minimize_callback=self.restore,
            maximize_callback=self.restore)
        bar.title_bar._restore_callback = self.restore
        bar.title_bar.minimize_button.setToolTip(u"还原")
        bar.title_bar.minimize_button.setAccessibleName(u"还原")
        root.addWidget(bar.title_bar)
        bar._frame_overlay = UEWindowFrameOverlay(bar)
        bar.setFixedSize(self.WIDTH, UEWindowTitleBar.HEIGHT + 2)
        bar.winId()
        self._bar = bar
        self._window.destroyed.connect(bar.deleteLater)

    def minimize(self):
        if self._collapsed:
            return
        owner = self._find_owner()
        if not owner:
            # A standalone window continues using normal taskbar minimization.
            self._window.showMinimized()
            return
        self._owner_hwnd = owner
        if self._owner_window is None or int(self._owner_window.winId()) != owner:
            qt_owner = QtWidgets.QWidget.find(owner)
            self._owner_window = (qt_owner.windowHandle() if qt_owner is not None
                                  else QtGui.QWindow.fromWinId(owner))
        if self._owner_window is None or self._owner_rect() is None:
            return
        # Slate sets only the native owner. Inform Qt as well, otherwise a
        # hide/show or maximize/restore can discard the native relationship.
        self._window.windowHandle().setTransientParent(self._owner_window)
        if self._bar is None:
            self._create_bar()
        self._bar.windowHandle().setTransientParent(self._owner_window)
        self._bar.title_bar.setTitle(self._window.windowTitle())
        self._position_bar()
        self._restore_state = self._window.windowState()
        normal = self._window.normalGeometry()
        self._restore_geometry = QtCore.QRect(
            normal if normal.isValid() else self._window.geometry())
        self._collapsed = True
        self._window.hide()
        self._bar.show()
        self._bar.raise_()
        self._timer.start()

    def _position_bar(self):
        if self._bar is None or self._owner_window is None:
            return
        rect = self._owner_rect()
        if rect is not None:
            width = min(self.WIDTH, max(self._bar.minimumSizeHint().width(),
                                       rect.width() - 2 * self.MARGIN))
            self._bar.setFixedWidth(width)
            self._bar.move(rect.left() + self.MARGIN,
                           rect.bottom() + 1 - self.MARGIN - self._bar.height())

    def restore(self):
        if not self._collapsed:
            return
        self._collapsed = False
        self._timer.stop()
        self._bar.hide()
        # Qt emulates maximization for some frameless/OpenGL windows. Showing
        # such a hidden window while still marked maximized can turn it into a
        # native-maximized HWND and overwrite its normal geometry. Show the
        # saved normal rectangle first, then reapply the requested window state.
        self._window.setWindowState(QtCore.Qt.WindowNoState)
        self._window.setGeometry(self._restore_geometry)
        self._window.showNormal()
        if self._restore_state & QtCore.Qt.WindowMaximized:
            self._window.showMaximized()
        elif self._restore_state & QtCore.Qt.WindowFullScreen:
            self._window.showFullScreen()
        self._window.raise_()
        self._window.activateWindow()

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() == QtCore.QEvent.Close:
                self._collapsed = False
                self._timer.stop()
                if self._bar is not None:
                    self._bar.hide()
            elif event.type() == QtCore.QEvent.Show and self._collapsed:
                # Reopening the main window through another entry clears the strip.
                self._collapsed = False
                self._timer.stop()
                self._bar.hide()
        return False
