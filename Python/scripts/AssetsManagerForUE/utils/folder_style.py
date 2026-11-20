"""Shared flat folder geometry; native Qt views, no icon files or background jobs."""
from PySide6 import QtCore, QtGui, QtWidgets

FOLDER_THUMBNAIL = 'cgtools:folder'
FOLDER_BACK = QtGui.QColor('#8f7544')
FOLDER_FRONT = QtGui.QColor('#b59659')
FOLDER_BACKGROUND = QtGui.QColor('#202123')
_ICON = None


class _CollapsedTreeAccessibility(QtCore.QObject):
    @QtCore.Slot(QtCore.QModelIndex)
    def reset_cache(self, _index):
        # Qt 6.11 leaves its flattened accessible row cache unchanged on
        # collapse. A stale indexOfChild can make native UIA NextSibling loop.
        # Notify only this view, synchronously before another UIA query arrives.
        # This resets accessibility metadata, not the item model or selection.
        if QtGui.QAccessible.isActive():
            event = QtGui.QAccessibleTableModelChangeEvent(
                self.parent(), QtGui.QAccessibleTableModelChangeEvent.ModelReset)
            QtGui.QAccessible.updateAccessibility(event)


DIRECTORY_STYLE = (
    'QTreeWidget,QListWidget{background:#1a1a1a;color:#c7c7c7;font-size:13px;border:0;}'
    'QTreeWidget::item,QListWidget::item{height:20px;padding:0px 2px;}'
    'QTreeWidget::item:selected,QListWidget::item:selected{background:#343a40;color:#f0f0f0;}'
    'QTreeWidget::item:hover,QListWidget::item:hover{background:#2b2e31;}'
    'QTreeWidget::item:selected:hover,QListWidget::item:selected:hover{background:#343a40;}'
)


def _path(points):
    path = QtGui.QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    return path


_BACK = _path(((1, 3), (8, 3), (10, 5), (19, 5), (19, 15), (1, 15)))
_CLOSED = _path(((1, 6), (19, 6), (19, 15), (1, 15)))
_OPEN = _path(((4, 7), (20, 7), (17, 15), (1, 15)))


def paint_folder(painter, rect, opened=False):
    """Two flat fills of immutable paths, rendered sharply at any view/DPI size."""
    scale = min(rect.width() / 20.0, rect.height() / 16.0)
    if scale <= 0:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.translate(rect.center().x() - 10 * scale, rect.center().y() - 8 * scale)
    painter.scale(scale, scale)
    painter.fillPath(_BACK, FOLDER_BACK)
    painter.fillPath(_OPEN if opened else _CLOSED, FOLDER_FRONT)
    painter.restore()


def folder_icon():
    """One process-wide QIcon with native open/closed and DPI representations."""
    global _ICON
    if _ICON is None:
        icon = QtGui.QIcon()
        for dpr in (1.0, 1.5, 2.0):
            for opened, state in ((False, QtGui.QIcon.Off), (True, QtGui.QIcon.On)):
                pixmap = QtGui.QPixmap(round(16 * dpr), round(16 * dpr))
                pixmap.setDevicePixelRatio(dpr)
                pixmap.fill(QtCore.Qt.transparent)
                painter = QtGui.QPainter(pixmap)
                paint_folder(painter, QtCore.QRectF(0, 0, 16, 16), opened)
                painter.end()
                for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Active, QtGui.QIcon.Selected):
                    icon.addPixmap(pixmap, mode, state)
        _ICON = icon
    return _ICON


def style_directory_view(view):
    """Keep native arrows/selection/layout; configure once when constructing a view."""
    view.setIconSize(QtCore.QSize(16, 16))
    view.setStyleSheet(DIRECTORY_STYLE)
    if isinstance(view, QtWidgets.QTreeView):
        view.setIndentation(12)
        view.setUniformRowHeights(True)
        view.setAnimated(False)
        if not hasattr(view, '_cgtools_collapsed_accessibility'):
            cache = _CollapsedTreeAccessibility(view)
            view.collapsed.connect(cache.reset_cache)
            view._cgtools_collapsed_accessibility = cache
    else:
        view.setSpacing(0)
        view.setUniformItemSizes(True)
