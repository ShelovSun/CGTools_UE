#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared Unreal-style chrome for AssetsManagerForUE Qt windows."""

import os

from PySide6 import QtCore, QtGui, QtWidgets


def ue_stylesheet_path():
    package_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(package_root, "qss", "UE5.qss")


def load_ue_stylesheet():
    with open(ue_stylesheet_path(), "r", encoding="utf-8") as stylesheet_file:
        return stylesheet_file.read()


def apply_ue_stylesheet(widget, extra_stylesheet=""):
    """Apply the central UE theme to a top-level tool window or dialog."""
    widget.setProperty("ueStylesheetApplied", True)
    widget.setStyleSheet(load_ue_stylesheet() + str(extra_stylesheet or ""))


def unreal_logo_path():
    """Return the shared UE logo beside the engine Python tool packages."""
    package_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    scripts_root = os.path.dirname(package_root)
    shared_logo = os.path.join(scripts_root, "icon", "unrealengine_logo.png")
    if os.path.isfile(shared_logo):
        return shared_logo

    # Developer/package fallback. The formal deployment uses shared_logo.
    package_logo = os.path.join(package_root, "icon", "unrealengine_logo.png")
    if os.path.isfile(package_logo):
        return package_logo
    return shared_logo


def load_unreal_logo(size=20):
    pixmap = QtGui.QPixmap(unreal_logo_path())
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        int(size),
        int(size),
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )


def unreal_window_icon():
    path = unreal_logo_path()
    return QtGui.QIcon(path) if os.path.isfile(path) else QtGui.QIcon()


class _UEWindowControlButton(QtWidgets.QPushButton):
    """Paint window controls independently of the active font or icon theme."""

    def __init__(self, glyph, parent=None):
        super(_UEWindowControlButton, self).__init__(parent)
        self._glyph = glyph
        self._normal_glyph_color = QtGui.QColor()
        self._hover_glyph_color = QtGui.QColor()
        self.setProperty("ueWindowControl", True)
        self.setText("")

    def setGlyph(self, glyph):
        self._glyph = glyph
        self.update()

    def _get_normal_glyph_color(self):
        return self._normal_glyph_color

    def _set_normal_glyph_color(self, color):
        self._normal_glyph_color = QtGui.QColor(color)
        self.update()

    normalGlyphColor = QtCore.Property(
        QtGui.QColor,
        _get_normal_glyph_color,
        _set_normal_glyph_color,
    )

    def _get_hover_glyph_color(self):
        return self._hover_glyph_color

    def _set_hover_glyph_color(self, color):
        self._hover_glyph_color = QtGui.QColor(color)
        self.update()

    hoverGlyphColor = QtCore.Property(
        QtGui.QColor,
        _get_hover_glyph_color,
        _set_hover_glyph_color,
    )

    def paintEvent(self, event):
        super(_UEWindowControlButton, self).paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        color = (self._hover_glyph_color if self.underMouse()
                 else self._normal_glyph_color)
        painter.setPen(QtGui.QPen(color, 1.25))
        center = self.rect().center()
        radius = 4
        if self._glyph == "minimize":
            painter.drawLine(center.x() - radius, center.y() + 3,
                             center.x() + radius, center.y() + 3)
        elif self._glyph == "maximize":
            painter.drawRect(center.x() - radius, center.y() - radius,
                             radius * 2, radius * 2)
        elif self._glyph == "restore":
            # Offset outlines, with the rear outline hidden by the front one.
            painter.drawLine(center.x() - 1, center.y() - 5,
                             center.x() + 5, center.y() - 5)
            painter.drawLine(center.x() + 5, center.y() - 5,
                             center.x() + 5, center.y() + 1)
            painter.drawLine(center.x() + 3, center.y() + 1,
                             center.x() + 5, center.y() + 1)
            painter.drawRect(center.x() - 4, center.y() - 3, 7, 7)
        else:
            painter.drawLine(center.x() - radius, center.y() - radius,
                             center.x() + radius, center.y() + radius)
            painter.drawLine(center.x() + radius, center.y() - radius,
                             center.x() - radius, center.y() + radius)
        painter.end()


class UEWindowTitleBar(QtWidgets.QWidget):
    """Compact frameless title bar matching Unreal Editor's dark windows."""

    HEIGHT = 36

    def __init__(self, window, title, close_callback=None, allow_maximize=False,
                 allow_minimize=False, minimize_callback=None, maximize_callback=None):
        super(UEWindowTitleBar, self).__init__(window)
        self._window = window
        self._close_callback = close_callback or window.close
        self._allow_maximize = bool(allow_maximize)
        self._allow_minimize = bool(allow_minimize)
        self._maximize_callback = maximize_callback
        self._drag_offset = None
        self._title_background_color = QtGui.QColor()
        self._separator_color = QtGui.QColor()

        window.setProperty("ueFramelessWindow", True)
        self.setObjectName("UEWindowTitleBar")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Symmetric side holders keep the title centered in the whole window.
        left_holder = QtWidgets.QWidget(self)
        left_holder.setObjectName("UEWindowTitleSide")
        side_width = 36 + 34 * (self._allow_minimize + self._allow_maximize)
        left_holder.setFixedWidth(side_width)
        left_layout = QtWidgets.QHBoxLayout(left_holder)
        left_layout.setContentsMargins(2, 0, 6, 0)
        left_layout.setSpacing(0)

        self.logo_label = QtWidgets.QLabel(left_holder)
        self.logo_label.setObjectName("UEWindowLogo")
        self.logo_label.setFixedSize(28, 28)
        self.logo_label.setAlignment(QtCore.Qt.AlignCenter)
        self.logo_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        logo = load_unreal_logo(24)
        if not logo.isNull():
            self.logo_label.setPixmap(logo)
        left_layout.addWidget(self.logo_label)
        left_layout.addStretch(1)
        layout.addWidget(left_holder)

        self.title_label = QtWidgets.QLabel(str(title), self)
        self.title_label.setObjectName("UEWindowTitle")
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label, 1)

        right_holder = QtWidgets.QWidget(self)
        right_holder.setObjectName("UEWindowTitleSide")
        right_holder.setFixedWidth(side_width)
        right_layout = QtWidgets.QHBoxLayout(right_holder)
        right_layout.setContentsMargins(1, 2, 1, 2)
        right_layout.setSpacing(0)

        self.minimize_button = None
        self.maximize_button = None
        if self._allow_minimize:
            self.minimize_button = self._create_button(
                right_holder, "UEWindowMinimizeButton", "minimize",
                u"最小化", minimize_callback or window.showMinimized)
            right_layout.addWidget(self.minimize_button)
        if self._allow_maximize:
            self.maximize_button = self._create_button(
                right_holder, "UEWindowMaximizeButton", "maximize",
                u"最大化", self._toggle_maximized)
            right_layout.addWidget(self.maximize_button)
        self.close_button = self._create_button(
            right_holder, "UEWindowCloseButton", "close",
            u"关闭", self._close_callback)
        right_layout.addWidget(self.close_button)
        layout.addWidget(right_holder)
        window.installEventFilter(self)
        self._sync_window_controls()

        # A new tool window gets the shared theme as soon as it adopts this
        # title bar. Callers only need extra QSS for their own content widgets.
        if not window.property("ueStylesheetApplied"):
            apply_ue_stylesheet(window)

    @staticmethod
    def _create_button(parent, name, glyph, tooltip, callback):
        button = _UEWindowControlButton(glyph, parent)
        button.setObjectName(name)
        button.setFixedSize(34, 32)
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(callback)
        return button

    def _sync_window_controls(self):
        if self.maximize_button is not None:
            restore = self._window.isMaximized() or self._window.isFullScreen()
            self.maximize_button.setGlyph("restore" if restore else "maximize")
            tooltip = u"还原" if restore else u"最大化"
            self.maximize_button.setToolTip(tooltip)
            self.maximize_button.setAccessibleName(tooltip)

    def eventFilter(self, watched, event):
        if watched is self._window and event.type() == QtCore.QEvent.WindowStateChange:
            self._sync_window_controls()
        return super(UEWindowTitleBar, self).eventFilter(watched, event)

    def _toggle_maximized(self):
        if self._maximize_callback is not None:
            self._maximize_callback()
            return
        if self._window.isMaximized() or self._window.isFullScreen():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def setTitle(self, title):
        self.title_label.setText(str(title))

    def _get_title_background_color(self):
        return self._title_background_color

    def _set_title_background_color(self, color):
        self._title_background_color = QtGui.QColor(color)
        self.update()

    titleBackgroundColor = QtCore.Property(
        QtGui.QColor,
        _get_title_background_color,
        _set_title_background_color,
    )

    def _get_separator_color(self):
        return self._separator_color

    def _set_separator_color(self, color):
        self._separator_color = QtGui.QColor(color)
        self.update()

    separatorColor = QtCore.Property(
        QtGui.QColor,
        _get_separator_color,
        _set_separator_color,
    )

    def paintEvent(self, event):
        # AssetsManager's legacy UE5.qss contains a broad QWidget rule.  Paint
        # the chrome explicitly so that inherited rules cannot lift the title
        # bar back toward the content area's grey value.
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self._title_background_color)
        bottom_pen = QtGui.QPen(self._separator_color, 1)
        bottom_pen.setCosmetic(True)
        painter.setPen(bottom_pen)
        painter.drawLine(
            0,
            self.height() - 1,
            self.width() - 1,
            self.height() - 1,
        )
        painter.end()

    @staticmethod
    def _global_point(event):
        try:
            return event.globalPosition().toPoint()
        except AttributeError:
            return event.globalPos()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = (
                self._global_point(event)
                - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super(UEWindowTitleBar, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_offset is not None
                and event.buttons() & QtCore.Qt.LeftButton):
            if not self._window.isMaximized():
                self._window.move(self._global_point(event) - self._drag_offset)
            event.accept()
            return
        super(UEWindowTitleBar, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super(UEWindowTitleBar, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (self._allow_maximize
                and event.button() == QtCore.Qt.LeftButton):
            self._toggle_maximized()
            event.accept()
            return
        super(UEWindowTitleBar, self).mouseDoubleClickEvent(event)


class UEWindowFrameOverlay(QtWidgets.QWidget):
    """Three inset frame lines matching UE's black/grey/black window edge."""

    def __init__(self, parent):
        super(UEWindowFrameOverlay, self).__init__(parent)
        self._window = parent
        self._outer_border_color = QtGui.QColor()
        self._highlight_border_color = QtGui.QColor()
        self._inner_border_color = QtGui.QColor()
        self._outer_border_width = 1
        self.setObjectName("UEWindowFrameOverlay")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        parent.installEventFilter(self)
        self._sync_geometry()

    def _get_outer_border_color(self):
        return self._outer_border_color

    def _set_outer_border_color(self, color):
        self._outer_border_color = QtGui.QColor(color)
        self.update()

    outerBorderColor = QtCore.Property(
        QtGui.QColor,
        _get_outer_border_color,
        _set_outer_border_color,
    )

    def _get_highlight_border_color(self):
        return self._highlight_border_color

    def _set_highlight_border_color(self, color):
        self._highlight_border_color = QtGui.QColor(color)
        self.update()

    highlightBorderColor = QtCore.Property(
        QtGui.QColor,
        _get_highlight_border_color,
        _set_highlight_border_color,
    )

    def _get_inner_border_color(self):
        return self._inner_border_color

    def _set_inner_border_color(self, color):
        self._inner_border_color = QtGui.QColor(color)
        self.update()

    innerBorderColor = QtCore.Property(
        QtGui.QColor,
        _get_inner_border_color,
        _set_inner_border_color,
    )

    def _get_outer_border_width(self):
        return self._outer_border_width

    def _set_outer_border_width(self, width):
        self._outer_border_width = max(1, int(width))
        self.update()

    outerBorderWidth = QtCore.Property(
        int,
        _get_outer_border_width,
        _set_outer_border_width,
    )

    def _sync_geometry(self):
        self.setGeometry(self._window.rect())
        self.raise_()
        self.update()

    def eventFilter(self, watched, event):
        if watched is self._window and event.type() in (
                QtCore.QEvent.Resize,
                QtCore.QEvent.Show,
                QtCore.QEvent.WindowStateChange):
            self._sync_geometry()
        return False

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        outer_width = max(1, int(self._outer_border_width))
        outer_pen = QtGui.QPen(self._outer_border_color, outer_width)
        outer_pen.setCosmetic(True)
        outer_offset = max(0, outer_width // 2)
        outer = self.rect().adjusted(
            outer_offset,
            outer_offset,
            -outer_offset - 1,
            -outer_offset - 1,
        )
        painter.setPen(outer_pen)
        painter.drawRect(outer)

        highlight_pen = QtGui.QPen(self._highlight_border_color, 1)
        highlight_pen.setCosmetic(True)
        highlight = self.rect().adjusted(
            outer_width,
            outer_width,
            -outer_width - 1,
            -outer_width - 1,
        )
        painter.setPen(highlight_pen)
        painter.drawRect(highlight)

        inner_pen = QtGui.QPen(self._inner_border_color, 1)
        inner_pen.setCosmetic(True)
        inner_offset = outer_width + 1
        inner = self.rect().adjusted(
            inner_offset,
            inner_offset,
            -inner_offset - 1,
            -inner_offset - 1,
        )
        painter.setPen(inner_pen)
        painter.drawRect(inner)
        painter.end()


class UEWindowResizeBorder(QtWidgets.QWidget):
    """A thin input-only ring restoring all eight frameless resize directions."""

    BORDER_WIDTH = 6
    CORNER_EXTENT = 16

    def __init__(self, window):
        super(UEWindowResizeBorder, self).__init__(window)
        self._window = window
        self._drag_edges = QtCore.Qt.Edges()
        self._drag_origin = None
        self._drag_geometry = None
        self.setObjectName("UEWindowResizeBorder")
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setMouseTracking(True)
        window.installEventFilter(self)
        self._sync_geometry()

    def _sync_geometry(self):
        self.setGeometry(self._window.rect())
        inner = self.rect().adjusted(
            self.BORDER_WIDTH, self.BORDER_WIDTH,
            -self.BORDER_WIDTH, -self.BORDER_WIDTH)
        # The entire content area remains outside this widget's input region.
        self.setMask(QtGui.QRegion(self.rect()).subtracted(QtGui.QRegion(inner)))
        enabled = not (self._window.isMaximized() or self._window.isFullScreen())
        if not enabled:
            self._finish_resize()
        self.setVisible(enabled)
        self.raise_()

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show,
                                QtCore.QEvent.WindowStateChange):
                self._sync_geometry()
            elif event.type() == QtCore.QEvent.Hide:
                self._finish_resize()
        return False

    def _edges_at(self, point):
        edges = QtCore.Qt.Edges()
        if (not self.rect().contains(point) or self._window.isMaximized()
                or self._window.isFullScreen()):
            return edges
        x, y = point.x(), point.y()
        width, height = self.width(), self.height()
        if not (x < self.BORDER_WIDTH or x >= width - self.BORDER_WIDTH
                or y < self.BORDER_WIDTH or y >= height - self.BORDER_WIDTH):
            return edges
        if self._window.minimumWidth() < self._window.maximumWidth():
            if x < self.CORNER_EXTENT:
                edges |= QtCore.Qt.LeftEdge
            elif x >= width - self.CORNER_EXTENT:
                edges |= QtCore.Qt.RightEdge
        if self._window.minimumHeight() < self._window.maximumHeight():
            if y < self.CORNER_EXTENT:
                edges |= QtCore.Qt.TopEdge
            elif y >= height - self.CORNER_EXTENT:
                edges |= QtCore.Qt.BottomEdge
        return edges

    def _update_cursor(self, edges):
        horizontal = edges & (QtCore.Qt.LeftEdge | QtCore.Qt.RightEdge)
        vertical = edges & (QtCore.Qt.TopEdge | QtCore.Qt.BottomEdge)
        if horizontal and vertical:
            descending = edges in (QtCore.Qt.LeftEdge | QtCore.Qt.TopEdge,
                                   QtCore.Qt.RightEdge | QtCore.Qt.BottomEdge)
            self.setCursor(QtCore.Qt.SizeFDiagCursor if descending else QtCore.Qt.SizeBDiagCursor)
        elif horizontal:
            self.setCursor(QtCore.Qt.SizeHorCursor)
        elif vertical:
            self.setCursor(QtCore.Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def _start_system_resize(self, edges):
        handle = self._window.windowHandle()
        try:
            return bool(handle and handle.startSystemResize(edges))
        except (AttributeError, RuntimeError):
            return False

    def mousePressEvent(self, event):
        edges = self._edges_at(event.position().toPoint())
        if event.button() == QtCore.Qt.LeftButton and edges:
            self._update_cursor(edges)
            # Prefer Qt's native Windows sizing loop, including DPI handling.
            if not self._start_system_resize(edges):
                self._drag_edges = edges
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_geometry = QtCore.QRect(self._window.geometry())
                self.grabMouse()
            event.accept()
            return
        super(UEWindowResizeBorder, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None:
            if not event.buttons() & QtCore.Qt.LeftButton:
                self._finish_resize()
                return
            delta = event.globalPosition().toPoint() - self._drag_origin
            rect = self._drag_geometry
            left, top = rect.x(), rect.y()
            right, bottom = left + rect.width(), top + rect.height()
            minimum = self._window.minimumSize().expandedTo(self._window.minimumSizeHint())
            maximum = self._window.maximumSize().expandedTo(minimum)
            if self._drag_edges & QtCore.Qt.LeftEdge:
                left = min(max(left + delta.x(), right - maximum.width()), right - minimum.width())
            elif self._drag_edges & QtCore.Qt.RightEdge:
                right = min(max(right + delta.x(), left + minimum.width()), left + maximum.width())
            if self._drag_edges & QtCore.Qt.TopEdge:
                top = min(max(top + delta.y(), bottom - maximum.height()), bottom - minimum.height())
            elif self._drag_edges & QtCore.Qt.BottomEdge:
                bottom = min(max(bottom + delta.y(), top + minimum.height()), top + maximum.height())
            self._window.setGeometry(left, top, right - left, bottom - top)
            event.accept()
            return
        self._update_cursor(self._edges_at(event.position().toPoint()))
        super(UEWindowResizeBorder, self).mouseMoveEvent(event)

    def _finish_resize(self):
        self._drag_origin = None
        self._drag_geometry = None
        self._drag_edges = QtCore.Qt.Edges()
        if QtWidgets.QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def mouseReleaseEvent(self, event):
        self._finish_resize()
        super(UEWindowResizeBorder, self).mouseReleaseEvent(event)


class UEWindowResizeGrip(QtWidgets.QSizeGrip):
    """Small visible bottom-right resize handle for a frameless window."""

    def __init__(self, parent):
        super(UEWindowResizeGrip, self).__init__(parent)
        self._grip_color = QtGui.QColor()
        self.setObjectName("UEWindowResizeGrip")
        self.setFixedSize(16, 16)
        self.setToolTip(u"\u8c03\u6574\u7a97\u53e3\u5927\u5c0f")

    def _get_grip_color(self):
        return self._grip_color

    def _set_grip_color(self, color):
        self._grip_color = QtGui.QColor(color)
        self.update()

    gripColor = QtCore.Property(
        QtGui.QColor,
        _get_grip_color,
        _set_grip_color,
    )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setPen(QtGui.QPen(self._grip_color, 1))
        extent = min(self.width(), self.height())
        for offset in (4, 8, 12):
            painter.drawLine(
                extent - offset,
                extent - 2,
                extent - 2,
                extent - offset,
            )
        painter.end()
