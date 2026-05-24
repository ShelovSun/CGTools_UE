#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 自定义一些QtWidgets

import os
import math
from . import imagesequence
from my_vendor import six
from PySide2 import QtGui
from PySide2 import QtCore
from PySide2 import QtWidgets

scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('widgets', '')
tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))


class MyThread(QtCore.QThread):
    signal = QtCore.Signal()

    def __init__(self):
        super(MyThread, self).__init__()

    def run(self):
        self.signal.emit()


class MyDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self):
        QtWidgets.QStyledItemDelegate.__init__(self)
        self._itemsWidget = None

    def paint(self, painter, option, index):
        # print("items paint")
        item = self.itemsWidget().itemFromIndex(index)
        item.paint(painter, option, index)

    def sizeHint(self, option, index):
        """如果设置了paint一定需要sizeHint"""
        item = self.itemsWidget().itemFromIndex(index)
        return item.sizeHint()

    def itemsWidget(self):
        return self._itemsWidget

    def setItemsWidget(self, itemsWidget):
        self._itemsWidget = itemsWidget


class WorkerSignals(QtCore.QObject):
    triggered = QtCore.Signal(object)


class ImageWorker(QtCore.QRunnable):
    """A convenience class for loading an image in a thread."""

    def __init__(self, *args):
        QtCore.QRunnable.__init__(self, *args)

        self._path = None
        self.signals = WorkerSignals()

    def setPath(self, path):
        """
        Set the image path to be processed.

        :type path: str
        """
        self._path = path

    def run(self):
        """The starting point for the thread."""
        try:
            if self._path:
                image = QtGui.QImage(six.text_type(self._path))
                self.signals.triggered.emit(image)
        except Exception as error:
            print("Cannot load thumbnail image:%s" % error)


class Pixmap(QtGui.QPixmap):

    def __init__(self, *args):
        QtGui.QPixmap.__init__(self, *args)
        self._color = None

    def setColor(self, color):
        """
        给pixmap着色
        :type color: QtGui.QColor
        :rtype: None
        """
        if not self.isNull():
            painter = QtGui.QPainter(self)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
            painter.setBrush(color)  # 定义用于填充形状的颜色或图案
            painter.setPen(color)  # 定义用于绘制线条或边界的颜色或点画
            painter.drawRect(self.rect())
            painter.end()


class GlobalSignals(QtCore.QObject):
    """"""
    sliderChanged = QtCore.Signal(float)


class WorkerSignals(QtCore.QObject):
    """"""
    triggered = QtCore.Signal(object)


class PreviewLabel(QtWidgets.QLabel):
    """
    预览窗口
    """

    def __init__(self, framsWgt=None):
        super(PreviewLabel, self).__init__()
        self.iconPath = ""
        self.__isAnim = False
        self._imageSequence = None
        self.framsWgt = framsWgt
        self.pixmap = None
        self.typePixmap = None
        self._isMoveing = False
        # self.setScaledContents(True)# 图片自适应label
        self.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.setStyleSheet(
            "background-color: qradialgradient(spread:pad, cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 rgba("
            "35, 36, 39, 100),  stop:1 rgba(35, 36, 39, 255));")

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.mouse_start_pos = e.pos()
            self._isMoveing = True

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._isMoveing = False

    def mouseMoveEvent(self, e):
        # print("mouse move")
        if self._isMoveing:
            point = e.pos() - self.mouse_start_pos
            # print(point)
            transform = QtGui.QTransform()
            transform.translate(point.x(), point.y())
            self.pixmap = self.pixmap.transformed(transform)
            self.setPixmap(self.pixmap)

    def mouseDoubleClickEvent(self, e):
        t = QtGui.QTransform()
        t.translate(5.1, 5.1)
        self.pixmap = self.pixmap.transformed(t)
        self.setPixmap(self.pixmap)

    def wheelEvent(self, e):
        # print("wheel")
        super(PreviewLabel, self).wheelEvent(e)
        if self.iconPath == "":
            return
        else:
            angle = e.angleDelta() / 8
            angleY = angle.y()
            transform = QtGui.QTransform()
            if angleY > 0:
                transform.scale(1.1, 1.1)
            else:
                transform.scale(0.9, 0.9)
            self.pixmap = self.pixmap.transformed(transform)
            self.setPixmap(self.pixmap)
            # self.adjustSize()
            # self.update()

    def resizeEvent(self, e):
        """  """
        # print("resize event")
        if self.pixmap:
            # print(self.pixmap)
            self.pixmap = self.pixmap.scaled(self.rect().width(),
                                             self.rect().height(),
                                             QtCore.Qt.KeepAspectRatio,
                                             QtCore.Qt.SmoothTransformation)
            self.setPixmap(self.pixmap)

    def clear(self):
        super(PreviewLabel, self).clear()
        self.iconPath = ""
        self.pixmap = None
        self.__isAnim = False
        self._imageSequence = None

    def setPreviewPixmap(self, path, type=None):
        """
        new setpixmap
        :param path:
        :param type:
        :return:
        """
        self.iconPath = path
        self.pixmap = QtGui.QPixmap(path)
        self.pixmap = self.pixmap.scaled(self.rect().width(),
                                         self.rect().height(),
                                         QtCore.Qt.KeepAspectRatio,
                                         QtCore.Qt.SmoothTransformation)

        if type is not None and os.path.isfile("%s/icon/%s.png" % (scriptsPath, type)):
            self.typePixmap = QtGui.QPixmap("%s/icon/%s.png" % (scriptsPath, type))

        self.paintTypeIcon()
        self.setPixmap(self.pixmap)

    def isAnim(self):
        return self.__isAnim

    def setAnim(self, path, type=None):
        self.setPreviewPixmap(path, type)
        self.__isAnim = True

    def enterEvent(self, e):
        # print("enter")
        if self.__isAnim:
            seq_path = self.iconPath.replace('thumbnail.jpg', 'sequence')
            self._play(seq_path)

    def leaveEvent(self, e):
        # print("leave")
        if self._imageSequence is not None:
            self._imageSequence.stop()

    def _play(self, path):
        """ Start playing the movie."""
        movie = None
        if os.path.isfile(path) and path.lower().endswith(".gif"):
            movie = QtGui.QMovie(path)
            self.setMovie(movie)
        elif os.path.isdir(path):
            movie = imagesequence.ImageSequence(path)
            movie.frameChanged.connect(self.__frameChanged)
            self._imageSequence = movie
        if movie:
            movie.start()

    def __frameChanged(self, frame=None):
        """ Triggered when the movie object updates to the given frame."""
        isAppRunning = bool(QtWidgets.QApplication.instance())
        if not isAppRunning:
            return
        if self._imageSequence is not None:
            self.pixmap = self._imageSequence.currentPixmap()
            self.pixmap = self.pixmap.scaled(self.rect().width(),
                                             self.rect().height(),
                                             QtCore.Qt.KeepAspectRatio,
                                             QtCore.Qt.SmoothTransformation)
            fn = self._imageSequence.currentFrameNumber()
            fc = self._imageSequence.frameCount()
            try:
                self.setPixmap(self.pixmap)
                self.framsWgt.setText(str(fn) + " / " + str(fc))
            except Exception as e:
                print(e)

    def paintTypeIcon(self):
        painter = QtGui.QPainter(self.pixmap)
        typePixmap = self.typePixmap
        if typePixmap:
            painter.drawPixmap(10, 10, typePixmap)
            painter.setPen(QtCore.Qt.NoPen)

    def paintPlayhead(self):
        """
        Paint the playhead if the item has an image sequence.
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        painter = QtGui.QPainter(self.pixmap)

        if self._imageSequence and self.underMouse():  # 如果有图片序列 和 鼠标下

            count = self._imageSequence.frameCount()
            current = self._imageSequence.currentFrameNumber()

            if count > 0:
                percent = float((count + current) + 1) / count - 1
            else:
                percent = 0

            r = self.rect()
            color = QtGui.QColor(255, 255, 255, 220)

            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(color))

            if percent <= 0:
                width = 0
            elif percent >= 1:
                width = r.width()
            else:
                width = (percent * r.width()) - 1

            height = 3
            if r.height() > r.width():
                y = r.y() + r.height() - (height - 1) - (r.height() - r.width())
            else:
                y = r.y() + r.height() - (height - 1)

            painter.drawRect(r.x(), y, width, height)


class MainQListWiget(QtWidgets.QListWidget):
    dragSignal = QtCore.Signal()

    DEF_SPACING = 8

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('widgets', '')

    def __init__(self):
        super(MainQListWiget, self).__init__()
        self._itemsDict = ()
        self._isList = False
        self._itemSize = 120
        self._currentItem = None
        self.setDragEnabled(False)  # ? 不起作用
        self.setDragDropMode(QtWidgets.QAbstractItemView.NoDragDrop)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setSortingEnabled(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setTextElideMode(QtCore.Qt.ElideNone)
        self.setMouseTracking(True)
        self._delegate = MyDelegate()
        self._delegate.setItemsWidget(self)
        self.setItemDelegate(self._delegate)

    def dragLeaveEvent(self, e):
        self.dragSignal.emit()

    def mouseMoveEvent(self, e):
        # print("mouseMoveEvent")
        super(MainQListWiget, self).mouseMoveEvent(e)
        item = self.itemAt(e.pos())
        if self.isList():
            return
        else:
            self.itemUpdateEvent(item, e)

    def leaveEvent(self, event):
        if self._currentItem:
            self.itemMouseLeaveEvent(self._currentItem, event)
            self._currentItem = None

    def itemUpdateEvent(self, item, event):
        if id(self._currentItem) != id(item):
            if self._currentItem:
                self.itemMouseLeaveEvent(self._currentItem, event)
                self._currentItem = None
            if item and not self._currentItem:
                self._currentItem = item
                self.itemMouseEnterEvent(item, event)

    def itemMouseEnterEvent(self, item, event):
        item.mouseEnterEvent(event)

    def itemMouseLeaveEvent(self, item, event):
        item.mouseLeaveEvent(event)

    # def resizeEvent(self, e):
    #     super(MyQListWiget, self).resizeEvent(e)
    #     self.updateIcons()
    #
    # def wheelEvent(self, e):
    #     super(MyQListWiget, self).wheelEvent(e)
    #     self.updateIcons()

    def items(self):
        return self._itemsDict

    def setItems(self, _list):
        self._itemsDict = _list

    def isList(self):
        return self._isList

    def setIsList(self, value):
        self._isList = value

    def itemSize(self):
        return self._itemSize

    def setItemSize(self, itemSize):
        self._itemSize = itemSize

    def setListMode(self):
        """列表显示"""
        # print("_viewList")
        self.setViewMode(QtWidgets.QListView.ListMode)
        self.setGridSize(QtCore.QSize(2000, 25))
        self.setSpacing(1)
        self.setAlternatingRowColors(True)

    def setIconMode(self):
        """缩略图显示"""
        # print("_viewThumb")
        self.setIconSize(QtCore.QSize(self._itemSize, self._itemSize))
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setGridSize(QtCore.QSize(self._itemSize + self.DEF_SPACING, self._itemSize + self.DEF_SPACING + 40))
        self.setSpacing(2)  # 不起作用
        self.setWordWrap(True)
        self.setAlternatingRowColors(False)
        # self.setStyleSheet(self._thumbStyleSheet())

    def setMode(self):
        """整理下"""
        if self._isList:
            self.setListMode()
        else:
            self.setIconMode()

    def addItems(self, keyWords=u""):
        """
        Add the given items to this widget.
        :type keyWords: str
        """
        for item in self._itemsDict:
            _item = Item()
            if item[1].lower().find(keyWords.lower()) != -1 or (item[2] and item[2].find(keyWords) != -1):
                _item.setItemData(item)
                _item.setItemsWidget(self)
                _item.setText(item[1])
                self.addItem(_item)


class Item(QtWidgets.QListWidgetItem):
    """The Item is used to hold rows of information for an item view."""

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('widgets', '')

    ICON_PATH = None
    TYPE_ICON_PATH = None

    ThreadPool = QtCore.QThreadPool()
    THUMBNAIL_PATH = ""

    MAX_ICON_SIZE = 256

    DEFAULT_FONT_SIZE = 12
    DEFAULT_PLAYHEAD_COLOR = QtGui.QColor(255, 255, 255, 220)
    DEFAULT_COLOR = QtGui.QColor(40, 41, 43, 255)
    DEFAULT_TEXT_BG_COLOR = QtGui.QColor(30, 30, 30, 255)
    DEFAULT_HOVER_COLOR = QtGui.QColor(50, 50, 50, 255)
    DEFAULT_SELECTED_COLOR = QtGui.QColor(0, 112, 224, 255)
    DEFAULT_BORDER_SIZE = 1.5

    THUMBNAIL_COLUMN = 0
    ENABLE_THUMBNAIL_THREAD = True
    PAINT_SLIDER = False

    _TYPE_PIXMAP_CACHE = {}

    _globalSignals = GlobalSignals()
    sliderChanged = _globalSignals.sliderChanged

    def __init__(self, *args):
        QtWidgets.QListWidgetItem.__init__(self, *args)

        self._url = None
        self._path = None
        self._size = None
        self._rect = None
        self._textColumnOrder = []

        self._data = {}
        self._itemData = {}
        self._isload = False

        self._icon = {}
        self._fonts = {}
        self._thread = None
        self._pixmap = {}
        self._pixmapRect = None
        self._pixmapScaled = None

        self._iconPath = None
        self._typePixmap = None

        self._thumbnailIcon = None

        self._underMouse = False
        self._searchText = None
        self._infoWidget = None

        self._groupItem = None
        self._groupColumn = 0

        self._mimeText = None
        self._itemsWidget = None
        self._stretchToWidget = None

        self._dragEnabled = True

        self.textColor = QtGui.QColor(255, 255, 255, 180)
        self.textSelectedColor = QtGui.QColor(255, 255, 255, 255)

        self._imageSequence = None
        self._imageSequencePath = ""

        self._sliderDown = False
        self._sliderValue = 0.0
        self._sliderPreviousValue = 0.0
        self._sliderPosition = None
        self._sliderEnabled = False

        self._worker = ImageWorker()
        self._worker.setAutoDelete(False)
        self._worker.signals.triggered.connect(self._thumbnailFromImage)
        self._workerStarted = False

    def __eq__(self, other):
        return id(other) == id(self)

    def __ne__(self, other):
        return id(other) != id(self)

    def __hash__(self):
        return hash(id(self))

    def __del__(self):
        """
        Make sure the sequence is stopped when deleted.

        :rtype: None
        """
        self.stop()

    def columnFromLabel(self, label):
        if self.treeWidget():
            return self.treeWidget().columnFromLabel(label)
        else:
            return None

    def labelFromColumn(self, column):
        if self.treeWidget():
            return self.treeWidget().labelFromColumn(column)
        else:
            return None

    def mimeText(self):
        """
        Return the mime text for drag and drop.

        :rtype: str
        """
        return self._mimeText or self.text(0)

    def setMimeText(self, text):
        """
        Set the mime text for drag and drop.

        :type text: str
        :rtype: None
        """
        self._mimeText = text

    def setloaded(self):
        self._isload = True

    def isload(self):
        return self._isload

    def setHidden(self, value):
        """
        Set the item hidden.

        :type value: bool
        :rtype: None
        """
        QtWidgets.QListWidgetItem.setHidden(self, value)
        row = self.treeWidget().indexFromItem(self).row()
        self.itemsWidget().listView().setRowHidden(row, value)

    def setDragEnabled(self, value):
        """
        Set True if the item can be dragged.

        :type value: bool
        :rtype: None
        """
        self._dragEnabled = value

    def dragEnabled(self):
        """
        Return True if the item can be dragged.

        :rtype: bool
        """
        return self._dragEnabled

    def setIcon(self, iconpath):
        """
        Set the icon to be displayed in the given column.
        设置显示列的icon
        :type column: int or str
        :type icon: QtGui.QIcon
        :type color: QtGui.QColor or None
        :rtype: None
        """
        # Safe guard for when the class is being used without the gui.
        isAppRunning = bool(QtWidgets.QApplication.instance())
        if not isAppRunning:
            return

        if isinstance(iconpath, six.string_types):
            if not os.path.exists(iconpath):
                icon = QtGui.QIcon("%s/icon/Default.png" % self.scriptsPath)
            else:
                icon = QtGui.QIcon(iconpath)
        else:
            icon = iconpath

        QtWidgets.QListWidgetItem.setIcon(self, icon)

        self.updateIcon()  # 清除 pixmap cache

    def setItemData(self, data):
        """
        Set the given dictionary as the data for the item.

        :type data: dict
        :rtype: None
        """
        self._itemData = data
        self.setImageSequencePath()

    def itemData(self):
        """
        Return the item data for this item.

        :rtype: dict
        """
        return self._itemData

    def name(self):
        """
        Return text for the Name column.

        :rtype: str
        """
        return self.itemData()[1]

    def zh_name(self):
        """
        :return: chname
        """
        return self.itemData()[2]

    def update(self):
        """
        Refresh the visual state of the icon.

        :rtype: None
        """
        self.updateIcon()
        self.updateFrame()

    def updateIcon(self):
        """
        Clear the pixmap cache for the item.
        清除 pixmap cache
        :rtype: None
        """
        self.clearCache()

    def clearCache(self):
        """
        清理 thumbnail cache.
        """
        self._pixmap = {}
        self._pixmapRect = None
        self._pixmapScaled = None
        self._thumbnailIcon = None

    def dpi(self):
        """
        Used for high resolution devices.

        :rtype: int
        """
        return 1

    def selectionChanged(self):
        """
        Triggered when an item has been either selected or deselected.

        :rtype: None
        """
        self.resetSlider()

    def setItemsWidget(self, wgt):
        self._itemsWidget = wgt

    def itemsWidget(self):
        """
        Returns the items widget that contains the items.    得到 itemWidget

        :rtype: ItemsWidget
        """
        return self._itemsWidget

    def searchText(self):
        """
        Return the search string used for finding the item.

        :rtype: str
        """
        if not self._searchText:
            self._searchText = six.text_type(self._data)

        return self._searchText

    def setStretchToWidget(self, widget):
        """
        Set the width of the item to the width of the given widget.

        :type widget: QtWidgets.QWidget
        :rtype: None
        """
        self._stretchToWidget = widget

    def stretchToWidget(self):
        """
        Return the sretchToWidget.

        :rtype: QtWidgets.QWidget
        """
        return self._stretchToWidget

    def setSize(self, size):
        """
        Set the size for the item.

        :type size: QtCore.QSize
        :rtype: None
        """
        self._size = size

    def sizeHint(self):
        """
        Return the current size of the item.

        :type column: int
        :rtype: QtCore.QSize
        """
        size = self._itemsWidget.itemSize()
        if not self._itemsWidget.isList():
            iconSize = QtCore.QSize(size, size + 40)
        else:
            iconSize = QtCore.QSize(2000, 20)
        return iconSize

    def thumbnailPath(self):
        """
        Return the thumbnail path on disk. 返回微缩图路径

        :rtype: None or str
        """
        return ""

    def _thumbnailFromImage(self, image):
        """
        Called after the given image object has finished loading.
        当 image 结束 loading 后调用：清理 -> 设置新的 icon
        :type image: QtGui.QImage
        :rtype: None
        """
        self.clearCache()  # 清理pixmap

        pixmap = QtGui.QPixmap()
        pixmap.convertFromImage(image)
        icon = QtGui.QIcon(pixmap)

        self._thumbnailIcon = icon
        if self.itemsWidget():
            self.itemsWidget().update()

    def defaultThumbnailPath(self):
        """
        Get the default thumbnail path.

        :rtype: str
        """
        return self.THUMBNAIL_PATH

    def defaultThumbnailIcon(self):
        """
        Get the default thumbnail icon.

        :rtype: QtGui.QIcon
        """
        return QtGui.QIcon(self.defaultThumbnailPath())

    def thumbnailIcon(self):
        """
        Return the thumbnail icon.
        返回 self._thumbnailIcon
        :rtype: QtGui.QIcon
        """
        thumbnailPath = self.thumbnailPath()

        if not self._thumbnailIcon:  # 如果没有 self._thumbnailIcon
            if self.ENABLE_THUMBNAIL_THREAD and not self._workerStarted:  #
                self._workerStarted = True
                self._worker.setPath(thumbnailPath)
                self.ThreadPool.start(self._worker)  # 开始进程池 ImageWorker
                self._thumbnailIcon = self.defaultThumbnailIcon()
            else:
                self._thumbnailIcon = QtGui.QIcon(thumbnailPath)

        return self._thumbnailIcon

    def icon(self):
        """
        Overriding the icon method to add support for the thumbnail icon.
        重写 icon 添加 thumbnail icon 支持
        :type column: int
        :rtype: QtGui.QIcon
        """
        icon = QtWidgets.QListWidgetItem.icon(self)

        if not icon == self.THUMBNAIL_COLUMN:
            icon = self.thumbnailIcon()

        return icon

    def pixmap(self):
        """
        Return the pixmap for the given column.
        :type column: int
        :rtype: QtWidgets.QPixmap
        """
        if not self._pixmap:
            icon = self.icon()
            if icon:
                size = QtCore.QSize(self.MAX_ICON_SIZE, self.MAX_ICON_SIZE)
                iconSize = icon.actualSize(size)
                self._pixmap = icon.pixmap(iconSize)
        return self._pixmap

    def padding(self):
        """
        Return the padding/border size for the item.

        :rtype: int
        """
        return 2

    def textHeight(self):
        """
        Return the height of the text for the item.

        :rtype: int
        """
        return self.itemsWidget().itemTextHeight()

    def textAlignment(self):
        """
        Return the text alignment for the label in the given column.

        :type column: int
        :rtype: QtCore.Qt.AlignmentFlag
        """
        return QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom

    # -----------------------------------------------------------------------
    # Support for mouse and key events
    # -----------------------------------------------------------------------

    def underMouse(self):
        """Return True if the item is under the mouse cursor."""
        return self._underMouse

    def contextMenu(self, menu):
        """
        Return the context menu for the item.

        Reimplement in a subclass to return a custom context menu for the item.

        :rtype: QtWidgets.QMenu
        """
        pass

    def dropEvent(self, event):
        """
        Reimplement in a subclass to receive drop events for the item.

        :type event: QtWidgets.QDropEvent
        :rtype: None
        """

    def mouseLeaveEvent(self, event):
        """
        Reimplement in a subclass to receive mouse leave events for the item.
        鼠标出
        :type event: QtWidgets.QMouseEvent
        :rtype: None
        """
        # print("mouse Leave Event")
        self._underMouse = False  # 鼠标下为假
        self.stop()

    def mouseEnterEvent(self, event):
        """
        Reimplement in a subclass to receive mouse enter events for the item.
        重执行 鼠标进
        :type event: QtWidgets.QMouseEvent
        :rtype: None
        """
        # print("mouse Enter Event")
        self._underMouse = True  # 鼠标下为真
        if not self.itemsWidget().isList():
            self.play()

    def mouseMoveEvent(self, event):
        """
        Reimplement in a subclass to receive mouse move events for the item.

        :type event: QtWidgets.QMouseEvent
        :rtype: None
        """
        self.sliderEvent(event)
        self.imageSequenceEvent(event)

    def mousePressEvent(self, event):
        """
        Reimplement in a subclass to receive mouse press events for the item.

        :type event: QtWidgets.QMouseEvent
        :rtype: None
        """
        if event.button() == QtCore.Qt.MidButton:
            if self.isSliderEnabled():
                self.setSliderDown(True)
                self._sliderPosition = event.pos()

    def mouseReleaseEvent(self, event):
        """
        Reimplement in a subclass to receive mouse release events for the item.

        :type event: QtWidgets.QMouseEvent
        :rtype: None
        """
        if self.isSliderDown():
            self._sliderPosition = None
            self._sliderPreviousValue = self.sliderValue()

    def keyPressEvent(self, event):
        """
        Reimplement in a subclass to receive key press events for the item.

        :type event: QtWidgets.QKeyEvent
        :rtype: None
        """
        pass

    def keyReleaseEvent(self, event):
        """
        Reimplement in a subclass to receive key release events for the item.

        :type event: QtWidgets.QKeyEvent
        :rtype: None
        """
        pass

    # -----------------------------------------------------------------------
    # Support for custom painting
    # -----------------------------------------------------------------------

    def rect(self):
        """
        Return the rect for the current paint frame.

        :rtype: QtCore.QRect
        """
        return self._rect

    def setRect(self, rect):
        """
        Set the rect for the current paint frame.

        :type rect: QtCore.QRect
        :rtype: None
        """
        self._rect = rect

    def visualRect(self, option):
        """
        Return the visual rect for the item.

        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: QtCore.QRect
        """
        return QtCore.QRect(option.rect)

    def iconPercent(self):
        itemsize = float('%.2f' % (self._itemsWidget.itemSize()))
        return itemsize / (itemsize + 40.00)

    def backgroundColor(self, visualRect):
        linearGradient = QtGui.QLinearGradient(QtCore.QPointF(0, visualRect.y()),
                                               QtCore.QPointF(0, visualRect.y() + visualRect.height()))
        # linearGradient.setColorAt(0, QtGui.QColor(35, 35, 35, 255))
        linearGradient.setColorAt(self.iconPercent(), QtGui.QColor(60, 62, 64, 255))
        linearGradient.setColorAt(self.iconPercent() + 0.01, self.DEFAULT_TEXT_BG_COLOR)
        return linearGradient

    def backgroundHoverColor(self, visualRect):
        linearGradient = QtGui.QLinearGradient(QtCore.QPointF(0, visualRect.y()),
                                               QtCore.QPointF(0, visualRect.y() + visualRect.height()))
        linearGradient.setColorAt(self.iconPercent(), QtGui.QColor(62, 64, 66, 255))
        linearGradient.setColorAt(self.iconPercent() + 0.01, self.DEFAULT_HOVER_COLOR)
        return linearGradient

    def backgroundSelectedColor(self, visualRect):
        linearGradient = QtGui.QLinearGradient(QtCore.QPointF(0, visualRect.y()),
                                               QtCore.QPointF(0, visualRect.y() + visualRect.height()))
        linearGradient.setColorAt(self.iconPercent(), QtGui.QColor(65, 69, 75, 255))
        linearGradient.setColorAt(self.iconPercent() + 0.01, self.DEFAULT_SELECTED_COLOR)
        return linearGradient

    def paint(self, painter, option, index):
        """
        Paint performs low-level painting for the item.

        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :type index: QtCore.QModelIndex
        :rtype: None
        """
        self.setRect(QtCore.QRect(option.rect))

        painter.save()

        try:
            self.paintBackground(painter, option, index)
            self.paintIcon(painter, option, index)
            self.paintText(painter, option, index)
            self.paintTypeIcon(painter, option)
            if self.imageSequence():
                self.paintPlayhead(painter, option)

        finally:
            painter.restore()

    def paintBackground(self, painter, option, index):
        """
        Draw the background for the item.
        绘制背景
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :type index: QtCore.QModelIndex
        """
        isSelected = option.state & QtWidgets.QStyle.State_Selected
        isMouseOver = option.state & QtWidgets.QStyle.State_MouseOver
        painter.setPen(QtGui.QPen(QtCore.Qt.NoPen))

        visualRect = self.visualRect(option)

        if not self.itemsWidget().isList():
            if isSelected:
                color = self.backgroundSelectedColor(visualRect)
            elif isMouseOver:
                color = self.backgroundHoverColor(visualRect)
            else:
                color = self.backgroundColor(visualRect)
        else:
            if isSelected:
                color = self.DEFAULT_SELECTED_COLOR
            elif isMouseOver:
                color = self.DEFAULT_HOVER_COLOR
            else:
                color = self.DEFAULT_COLOR
        painter.setBrush(QtGui.QBrush(color))
        painter.drawRect(visualRect)

    def paintSlider(self, painter, option, index):
        """
        Draw the virtual slider for the item.
        绘制进度条
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :type index: QtCore.QModelIndex
        """
        if not self.PAINT_SLIDER:
            return

        if not self.itemsWidget().isIconView():
            return

        # Draw slider background
        painter.setPen(QtGui.QPen(QtCore.Qt.NoPen))

        rect = self.visualRect(option)

        color = self.itemsWidget().backgroundColor().toRgb()
        color.setAlpha(75)
        painter.setBrush(QtGui.QBrush(color))

        height = rect.height()

        ratio = self.sliderValue()

        if ratio < 0:
            width = 0
        elif ratio > 100:
            width = rect.width()
        else:
            width = rect.width() * (float(ratio) / 100)

        rect.setWidth(width)
        rect.setHeight(height)

        painter.drawRect(rect)

        # Draw slider value
        rect = self.visualRect(option)
        rect.setY(rect.y() + (4 * self.dpi()))

        color = self.itemsWidget().textColor().toRgb()
        color.setAlpha(220)
        pen = QtGui.QPen(color)
        align = QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter

        painter.setPen(pen)
        painter.drawText(rect, align, str(self.sliderValue()) + "%")

    def iconRect(self, option):
        """
        Return the icon rect for the item.

        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: QtCore.QRect
        """
        padding = self.padding()
        rect = self.visualRect(option)
        width = rect.width()
        height = rect.height()

        width -= padding
        height -= padding

        rect.setWidth(width)
        rect.setHeight(height)

        x = 0
        x += float(padding) / 2
        x += float((width - rect.width())) / 2

        y = float((height - rect.height())) / 2
        y += float(padding) / 2

        rect.translate(x, y)
        return rect

    def scalePixmap(self, pixmap, rect):
        """
        Scale the given pixmap to the give rect size.

        This method will cache the scaled pixmap if called with the same size.

        :type pixmap: QtGui.QPixmap
        :type rect: QtCore.QRect
        :rtype: QtGui.QPixmap
        """
        rectChanged = True

        if self._pixmapRect:
            widthChanged = self._pixmapRect.width() != rect.width()
            heightChanged = self._pixmapRect.height() != rect.height()

            rectChanged = widthChanged or heightChanged

        if not self._pixmapScaled or rectChanged:
            self._pixmapScaled = pixmap.scaled(
                rect.width(),
                rect.height(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )

            self._pixmapRect = rect

        return self._pixmapScaled

    def paintIcon(self, painter, option, index, align=None):
        """
        Draw the icon for the item.
        绘制 item 的 icon
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        if self.itemsWidget().isList():
            pass
        else:
            pixmap = QtGui.QPixmap(self.itemData()[7])
            if self.imageSequence() and self.underMouse():
                pixmap = self.imageSequence().currentPixmap()

            if not pixmap:
                return

            rect = self.iconRect(option)  # Return the icon rect for the item.
            pixmap = self.scalePixmap(pixmap, rect)

            pixmapRect = QtCore.QRect(rect)
            pixmapRect.setWidth(pixmap.width())
            pixmapRect.setHeight(pixmap.height())

            align = QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter

            x, y = 0, 0
            pixmapRect.translate(x, y)
            painter.drawPixmap(pixmapRect, pixmap)

    def drawIconBorder(self, painter, option):
        """
        Draw a border around the icon.

        :type painter: QtWidgets.QPainter
        :type pixmapRect: QtWidgets.QRect
        :rtype: None
        """
        pixmapRect = QtCore.QRect(option.rect)
        pixmapRect.setX(pixmapRect.x() - self.DEFAULT_BORDER_SIZE)
        pixmapRect.setY(pixmapRect.y() - self.DEFAULT_BORDER_SIZE)
        pixmapRect.setWidth(pixmapRect.width() + self.DEFAULT_BORDER_SIZE)
        pixmapRect.setHeight(pixmapRect.height() + self.DEFAULT_BORDER_SIZE)

        isSelected = option.state & QtWidgets.QStyle.State_Selected
        isMouseOver = option.state & QtWidgets.QStyle.State_MouseOver
        painter.setPen(QtGui.QPen(QtCore.Qt.NoPen))

        if isSelected:
            color = self.DEFAULT_SELECTED_COLOR
        elif isMouseOver:
            color = self.DEFAULT_HOVER_COLOR
        else:
            color = self.DEFAULT_COLOR

        painter.setBrush(QtGui.QBrush(color))
        painter.drawRect(pixmapRect)

    def fontSize(self):
        """
        Return the font size for the item.

        :rtype: int
        """
        return self.DEFAULT_FONT_SIZE

    def font(self, column):
        """
        Return the font for the given column.

        :type column: int
        :rtype: QtWidgets.QFont
        """
        default = QtWidgets.QTreeWidgetItem.font(self, column)

        font = self._fonts.get(column, default)

        font.setPixelSize(self.fontSize() * self.dpi())
        return font

    def setFont(self, column, font):
        """
        Set the font for the given column.

        :type column: int
        :type font: QtWidgets.QFont
        :rtype: Noen
        """
        self._fonts[column] = font

    def paintText(self, painter, option, index):
        """
        Draw the text for the item.

        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        visualRect = self.visualRect(option)
        rect = QtCore.QRect(visualRect)
        align = self.textAlignment()

        isSelected = option.state & QtWidgets.QStyle.State_Selected
        if isSelected:
            color = self.textSelectedColor
        else:
            color = self.textColor

        pen = QtGui.QPen(color)
        painter.setPen(pen)
        if self.zh_name():
            zh_name = self.zh_name()
        else:
            zh_name = ""
        if self.itemsWidget().isList():
            text = self.name() + "       " + zh_name
        else:
            text = self.name() + "\n" + zh_name
        painter.drawText(rect, align, text)

    def countGRPNum(self):
        path = self._itemData[7].split("Icon")[0]
        directory = QtCore.QDir("%sMod" % path)
        int_list = directory.entryList(['*.ma'], QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                       QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
        return str(len(int_list) - 1)

    def paintNum(self, painter, option):
        """
        Draw the text for the item.
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        rect = QtCore.QRect(option.rect)
        pen = QtGui.QPen(self.textColor)
        painter.setPen(pen)
        text = self.countGRPNum()
        itemSize = self._itemsWidget.itemSize()
        painter.drawText(rect.x() + itemSize - 15, rect.y() + itemSize - 5, text)

    def textWidth(self, column):
        text = self.text(column)

        font = self.font(column)
        metrics = QtGui.QFontMetricsF(font)
        textWidth = metrics.width(text)
        return textWidth

    # ------------------------------------------------------------------------
    # Support for middle mouse slider
    # ------------------------------------------------------------------------

    def setSliderEnabled(self, enabled):
        """
        Set if middle mouse slider is enabled.

        :type enabled: bool
        """
        self._sliderEnabled = enabled

    def isSliderEnabled(self):
        """
        Return true if middle mouse slider is enabled.

        :rtype: bool
        """
        return self._sliderEnabled

    def sliderEvent(self, event):
        """
        Called when the mouse moves while the middle mouse button is held down.

        :param event: QtGui.QMouseEvent
        """
        if self.isSliderDown():
            value = (event.pos().x() - self.sliderPosition().x()) / 1.5
            value = math.ceil(value) + self.sliderPreviousValue()
            try:
                self.setSliderValue(value)
            except Exception:
                self.setSliderDown(False)

    def resetSlider(self):
        """Reset the slider value to zero."""
        self._sliderValue = 0.0
        self._sliderPreviousValue = 0.0

    def setSliderDown(self, down):
        """Called when the middle mouse button is released."""
        self._sliderDown = down
        if not down:
            self._sliderPosition = None
            self._sliderPreviousValue = self.sliderValue()

    def isSliderDown(self):
        """
        Return True if blending.

        :rtype: bool
        """
        return self._sliderDown

    def setSliderValue(self, value):
        """
        Set the blend value.

        :type value: float
        :rtype: bool
        """
        if self.isSliderEnabled():

            self._sliderValue = value

            if self.PAINT_SLIDER:
                self.update()

            self.sliderChanged.emit(value)

            if self.PAINT_SLIDER:
                self.update()

            logger.debug("Blending:" + str(value))

    def sliderValue(self):
        """
        Return the blend value.

        :rtype: float
        """
        return self._sliderValue

    def sliderPreviousValue(self):
        """
        :rtype: float
        """
        return self._sliderPreviousValue

    def sliderPosition(self):
        """
        :rtype: QtGui.QPoint
        """
        return self._sliderPosition

    # ------------------------------------------------------------------------
    # Support animated image sequence
    # ------------------------------------------------------------------------

    def imageSequenceEvent(self, event):  # 被 鼠标移动事件调用
        """
        :type event: QtCore.QEvent
        :rtype: None
        """
        if self.imageSequence():
            if self.rect():
                x = event.pos().x() - self.rect().x()
                width = self.rect().width()
                percent = 1.0 - (float(width - x) / float(width))
                frame = int(self.imageSequence().frameCount() * percent)
                self.imageSequence().jumpToFrame(frame)
                self.updateFrame()

    def resetImageSequence(self):
        self._imageSequence = None

    def imageSequence(self):
        """
        :rtype: studioqt.ImageSequence
        """
        return self._imageSequence

    def setImageSequence(self, value):
        """
        :type value: studioqt.ImageSequence  设置了 ImageSequence
        """
        self._imageSequence = value

    def setImageSequencePath(self):
        """
        :type path: str
        """
        self._imageSequencePath = self.itemData()[7].replace('thumbnail.jpg', 'sequence')

    def imageSequencePath(self):
        """
        :rtype: str
        """
        return self._imageSequencePath

    def stop(self):
        """Stop playing the image sequence movie."""
        if self.imageSequence():
            self.imageSequence().stop()

    def play(self):
        """Start playing the image sequence movie."""
        # print("Play Animation")
        self.resetImageSequence()
        path = self.imageSequencePath() or self.thumbnailPath()
        # print("path:", path)
        movie = None

        if os.path.isfile(path) and path.lower().endswith(".gif"):
            movie = QtGui.QMovie(path)
            movie.setCacheMode(QtGui.QMovie.CacheAll)
            movie.frameChanged.connect(self.updateFrame)

        elif os.path.isdir(path):
            if not self.imageSequence():
                movie = imagesequence.ImageSequence(path)
                movie.frameChanged.connect(self.updateFrame)

        if movie:
            self.setImageSequence(movie)
            self.imageSequence().start()

    def updateFrame(self):
        """
        Triggered when the movie object updates the current frame.
        """
        if self.imageSequence():
            pixmap = self.imageSequence().currentPixmap()
            self.setIcon(QtGui.QIcon(pixmap))

    def playheadColor(self):
        """
        Return the playhead color.

        :rtype: QtGui.Color
        """
        return self.DEFAULT_PLAYHEAD_COLOR

    def paintPlayhead(self, painter, option):
        """
        Paint the playhead if the item has an image sequence.

        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        imageSequence = self.imageSequence()

        if imageSequence and self.underMouse():  # 如果有图片序列 和 鼠标下

            count = imageSequence.frameCount()
            current = imageSequence.currentFrameNumber()

            if count > 0:
                percent = float((count + current) + 1) / count - 1
            else:
                percent = 0

            r = self.iconRect(option)
            c = self.playheadColor()

            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(c))

            if percent <= 0:
                width = 0
            elif percent >= 1:
                width = r.width()
            else:
                width = (percent * r.width()) - 1

            height = 3 * self.dpi()
            y = r.y() + r.height() - (height - 1)

            painter.drawRect(r.x(), y, width, height)

    def typeIconPath(self):
        """
        Return the type icon path on disc.

        :rtype: path or None
        """
        if self.TYPE_ICON_PATH is None:
            return self.ICON_PATH

        return self.TYPE_ICON_PATH

    def typePixmap(self):
        """
        Return the type pixmap for the plugin.

        :rtype: QtWidgets.QPixmap
        """
        path = self.typeIconPath()
        pixmap = self._TYPE_PIXMAP_CACHE.get(path)

        if not pixmap and path and os.path.exists(path):
            self._TYPE_PIXMAP_CACHE[path] = QtGui.QPixmap(path)

        return self._TYPE_PIXMAP_CACHE.get(path)

    def typeIconRect(self, option):
        """
        Return the type icon rect.

        :rtype: QtGui.QRect
        """
        padding = 2 * self.dpi()
        r = self.iconRect(option)

        x = r.x() + padding
        y = r.y() + padding
        rect = QtCore.QRect(x, y, 13 * self.dpi(), 13 * self.dpi())

        return rect

    def paintTypeIcon(self, painter, option):
        """
        Draw the item type icon at the top left.
        左上角角标
        :type painter: QtWidgets.QPainter
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: None
        """
        rect = self.typeIconRect(option)
        typePixmap = self.typePixmap()
        if typePixmap:
            painter.setOpacity(0.5)
            painter.drawPixmap(rect, typePixmap)
            painter.setOpacity(1)
