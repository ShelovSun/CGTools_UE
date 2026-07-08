#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 自定义一些QtWidgets

import os
import math
from . import imagesequence
from my_vendor import six
from PySide6 import QtGui
from PySide6 import QtCore
from PySide6 import QtWidgets

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
    skipped = QtCore.Signal()  # worker 开跑前判定 item 已不可视 -> 跳过本次加载


class ImageWorker(QtCore.QRunnable):
    """A convenience class for loading an image in a thread."""

    def __init__(self, *args):
        QtCore.QRunnable.__init__(self, *args)

        self._path = None
        self._size = 256  # 缩放上限（缩略图无需全分辨率，参考独立版 assetManager）
        self._shouldLoad = None  # 开跑前的可视性回调：返回 False 则跳过，把线程让给当前可见 item
        self.signals = WorkerSignals()

    def setShouldLoad(self, fn):
        """设置"是否仍需加载"的回调（通常为 lambda: item 仍在可视区）。"""
        self._shouldLoad = fn

    def setPath(self, path):
        """
        Set the image path to be processed.

        :type path: str
        """
        self._path = path

    def setSize(self, size):
        """目标缩放尺寸（像素）。"""
        self._size = size

    def run(self):
        """The starting point for the thread - 在工作线程里就把大图缩小。"""
        try:
            # 优先级关键：真正读图前再判一次该 item 是否仍需加载（仍在可视区）。
            # 快速滚动时，队列里目标已被划走的任务在此立即跳过，把有限线程让给当前可见区 -> 新区域优先刷新。
            shouldLoad = self._shouldLoad
            if shouldLoad is not None and not shouldLoad():
                self.signals.skipped.emit()
                return
            if not self._path or not os.path.exists(six.text_type(self._path)):
                self.signals.triggered.emit(None)
                return
            image = QtGui.QImage(six.text_type(self._path))
            # 优化：过大的图在后台线程缩小，主线程不再处理全分辨率大图（这是卡顿主因）
            if not image.isNull() and (image.width() > self._size * 2 or
                                       image.height() > self._size * 2):
                image = image.scaled(self._size * 2, self._size * 2,
                                     QtCore.Qt.KeepAspectRatio,
                                     QtCore.Qt.SmoothTransformation)
            self.signals.triggered.emit(image)
        except Exception as error:
            print("Cannot load thumbnail image:%s" % error)
            self.signals.triggered.emit(None)


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
    skipped = QtCore.Signal()  # worker 开跑前判定 item 已不可视 -> 跳过本次加载（运行时实际使用的是这个类）


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
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)  # 按像素平滑滚动(配合 wheelEvent 加速)
        self._delegate = MyDelegate()
        self._delegate.setItemsWidget(self)
        self.setItemDelegate(self._delegate)

        # 视口懒加载：滚动时优先加载"当前可见区"，而不是永远从上往下加载
        self.verticalScrollBar().valueChanged.connect(self._onScroll)
        self.horizontalScrollBar().valueChanged.connect(self._onScroll)
        self._scrollTimer = QtCore.QTimer()
        self._scrollTimer.setSingleShot(True)
        self._scrollTimer.timeout.connect(self._updateVisibleItems)

    def wheelEvent(self, event):
        """
        图标模式下默认滚轮太慢（大图标时一格滚轮只挪一点）：改为每格滚轮滚动约一个图标行高。
        列表模式保持默认。
        """
        if self.isList():
            super(MainQListWiget, self).wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        steps = event.angleDelta().y() / 120.0  # 一格标准滚轮 = 120
        rowHeight = self._itemSize + self.DEF_SPACING + 40  # 一个网格行高(图标+间隙+文字)
        bar.setValue(bar.value() - int(steps * rowHeight))
        event.accept()

    def _onScroll(self, value=None):
        """滚动事件：50ms 防抖，把一次连续滚动合并成一次可见区刷新。"""
        self._scrollTimer.stop()
        self._scrollTimer.start(50)

    def _updateVisibleItems(self):
        """
        计算当前可见区并按优先级触发缩略图加载 —— 解决"永远从上往下加载"的核心方法。
        优先级：① 真正可见的 item ② 下方预取带 ③ 上方预取带。
        快速滚动到新区域后新区域优先刷新；已划走的排队任务会在 worker 开跑前自动跳过。
        列表模式不画缩略图，直接跳过。
        """
        if self.isList():
            return
        count = self.count()
        if count == 0:
            return

        viewportRect = self.viewport().rect()

        # 定位真正可见的区块 [first_visible, last_visible]（item 顺序自上而下）
        firstVisible = -1
        lastVisible = -1
        for i in range(count):
            itemRect = self.visualItemRect(self.item(i))
            if viewportRect.intersects(itemRect):
                if firstVisible == -1:
                    firstVisible = i
                lastVisible = i
            elif firstVisible != -1:
                break  # 已越过可见区域，提前结束扫描

        if firstVisible == -1:
            return

        # 预取带：可视区上下各扩展约半屏
        span = lastVisible - firstVisible + 1
        pad = max(1, span // 2)
        lo = max(0, firstVisible - pad)
        hi = min(count - 1, lastVisible + pad)

        # 先统一标记可视状态（autoload=False：此刻不排活，下面按优先级统一排）
        for i in range(count):
            item = self.item(i)
            if item is not None:
                item.setVisibleInViewport(lo <= i <= hi, autoload=False)

        # 按优先级排活：① 真正可见 ② 下方预取 ③ 上方预取
        def _req(i):
            it = self.item(i)
            if it is not None:
                it.requestThumbnailLoad()
        for i in range(firstVisible, lastVisible + 1):
            _req(i)
        for i in range(lastVisible + 1, hi + 1):
            _req(i)
        for i in range(lo, firstVisible):
            _req(i)

        self.viewport().update()

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
        # 批量添加期间关闭刷新，减少逐个 addItem 触发的重绘
        self.setUpdatesEnabled(False)
        try:
            for item in self._itemsDict:
                _item = Item()
                if item[1].lower().find(keyWords.lower()) != -1 or (item[2] and item[2].find(keyWords) != -1):
                    _item.setItemData(item)
                    _item.setItemsWidget(self)
                    _item.setText(item[1])
                    self.addItem(_item)
        finally:
            self.setUpdatesEnabled(True)

        # 添加完成后立即按可见区优先级触发加载（首屏就从可见区开始，而非全表）
        self._updateVisibleItems()

    def clear(self):
        """
        重写 clear：清空前把所有 item 标记为不可视，使线程池中尚未执行的加载任务
        在排到时立即跳过（见 ImageWorker.run），避免旧数据的解码拖慢新数据。
        """
        for i in range(self.count()):
            try:
                item = self.item(i)
                if item is not None:
                    item.setVisibleInViewport(False, autoload=False)
            except Exception:
                pass
        if getattr(self, "_scrollTimer", None) is not None:
            self._scrollTimer.stop()
        super(MainQListWiget, self).clear()

    def resizeEvent(self, event):
        """窗口尺寸变化：重新计算可见区（换行后可见 item 集合会变）。"""
        super(MainQListWiget, self).resizeEvent(event)
        self._updateVisibleItems()

    def showEvent(self, event):
        """首次显示：触发一次可见区加载。"""
        super(MainQListWiget, self).showEvent(event)
        self._updateVisibleItems()


class Item(QtWidgets.QListWidgetItem):
    """The Item is used to hold rows of information for an item view."""

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('widgets', '')

    ICON_PATH = None
    TYPE_ICON_PATH = None

    ThreadPool = QtCore.QThreadPool()
    # 缩略图多来自磁盘/网络盘，瓶颈是 I/O 等待而非 CPU，适当提高并发可更快铺满可见区；
    # 配合 worker 的"开跑前判可视"，被快速滚动划走的旧任务会立即跳过，不会把线程占死。
    ThreadPool.setMaxThreadCount(8)
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
    _PLACEHOLDER_PIXMAP = None  # 首屏/解码中显示的占位图，类级共享，仅构建一次

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
        self._pixmapScaledKey = None  # 缩放缓存对应的源帧内容标识(pixmap.cacheKey())，帧变化时自动重缩

        self._srcPixmap = None        # 缓存的原始缩略图 pixmap，非悬停态复用，避免每次重绘从磁盘解码（滚动收益最大）
        self._srcPixmapPath = None    # _srcPixmap 对应的磁盘路径，路径变化时才重新解码
        self._curFramePixmap = None   # 悬停播放时的当前帧 pixmap，updateFrame 解码一次供 paintIcon 复用
        self._lastFrameNumber = -1    # 上一次已渲染的帧号，用于跳过重复帧

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

        self._isVisibleInViewport = False  # 懒加载：item 是否在可视区/预取带内（worker 开跑前据此判定是否跳过）

        self._worker = ImageWorker()
        self._worker.setAutoDelete(False)
        self._worker.signals.triggered.connect(self._thumbnailFromImage)
        self._worker.setShouldLoad(lambda: self._isVisibleInViewport)
        self._worker.signals.skipped.connect(self._thumbnailLoadSkipped)
        self._workerStarted = False
        self._thumbnailLoading = False    # 缩略图是否正在后台解码，避免每次重绘重复入队
        self._pendingThumbnailPath = None  # 当前后台正在解码的路径，回调时据此写回 _srcPixmapPath

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
        self._srcPixmap = None       # 数据变了：作废缓存的原图，让下次绘制按新路径重新加载
        self._srcPixmapPath = None
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
        self._srcPixmap = None       # 主动刷新：丢弃缓存原图，按最新磁盘内容重新加载
        self._srcPixmapPath = None
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
        清理 thumbnail cache（只清派生的缩放缓存，不清原图 _srcPixmap）。
        注意：
        - 不清 _curFramePixmap —— updateFrame 先写它再触发本方法，清了会导致 paintIcon 又去解码。
        - 不清 _srcPixmap —— 本方法在播放时每帧都被 setIcon 调用，清了会导致每次悬停结束都重新异步解码闪占位图。
          原图失效改在真正的刷新点（update / setItemData）处理。
        """
        self._pixmap = {}
        self._pixmapRect = None
        self._pixmapScaled = None
        self._pixmapScaledKey = None
        self._thumbnailIcon = None

    def repaintItem(self):
        """
        只重绘本 item 所在的可视区域，避免刷新整个视口。
        异步回调期间列表可能已被 clear/重排 -> 本 item 的 C++ 对象已销毁，
        此时 visualItemRect(self) 会抛 RuntimeError，捕获后安全放弃。
        """
        widget = self.itemsWidget()
        if not widget:
            return
        try:
            rect = widget.visualItemRect(self)
        except RuntimeError:
            return  # Internal C++ object (Item) already deleted
        if rect.isValid():
            widget.viewport().update(rect)

    def requestThumbnailLoad(self):
        """
        请求后台加载缩略图（进入可视区/预取或绘制时调用）。幂等：已缓存或正在加载则直接返回。
        仅当 item 在可视区(_isVisibleInViewport)时才真正排活；worker 开跑前会再判一次可视性，
        被快速滚动划走的任务会立即跳过，把线程让给当前可见区 -> 滚动到的新区域优先加载。
        """
        if not self.ENABLE_THUMBNAIL_THREAD or self._thumbnailLoading:
            return
        if not self._isVisibleInViewport:
            return
        thumbnailPath = self.itemData()[7]
        if not thumbnailPath:
            return
        if self._srcPixmap is not None and self._srcPixmapPath == thumbnailPath:
            return  # 已缓存该路径原图，无需再加载
        self._thumbnailLoading = True
        self._pendingThumbnailPath = thumbnailPath
        self._worker.setPath(thumbnailPath)
        self._worker.setSize(self.MAX_ICON_SIZE)
        self.ThreadPool.start(self._worker)

    def setVisibleInViewport(self, visible, autoload=True):
        """
        标记 item 是否在可视区/预取带内，用于懒加载与优先级控制。
        autoload=True 时一进入可视区就请求加载；批量标记可传 False，由调用方按优先级统一排活。
        """
        was = self._isVisibleInViewport
        self._isVisibleInViewport = visible
        if autoload and visible and not was:
            self.requestThumbnailLoad()

    def _thumbnailLoadSkipped(self):
        """
        worker 排到执行时该 item 已被滚出可视区 -> 本次跳过并复位加载标志；
        若期间又滚回可视区则重新排活。（skipped 信号经队列连接在主线程执行）
        """
        self._thumbnailLoading = False
        if self._isVisibleInViewport:
            self.requestThumbnailLoad()

    def _placeholderPixmap(self):
        """
        列表首屏/解码进行中显示的占位图（类级共享，仅构建一次）。
        icon 目录在 AssetsManagerForUE 根下，而 scriptsPath 可能指向其下的 utils，故按存在性尝试多个候选，
        兼容不同运行环境下 scriptsPath 的解析差异；都找不到则用空 pixmap，paintIcon 会跳过绘制（空白格）。
        """
        if Item._PLACEHOLDER_PIXMAP is None:
            for base in (os.path.dirname(self.scriptsPath), self.scriptsPath):
                path = "%s/icon/Default.png" % base
                if base and os.path.exists(path):
                    Item._PLACEHOLDER_PIXMAP = QtGui.QPixmap(path)
                    break
            if Item._PLACEHOLDER_PIXMAP is None:
                Item._PLACEHOLDER_PIXMAP = QtGui.QPixmap()
        return Item._PLACEHOLDER_PIXMAP

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
        后台线程解码完成后在主线程回调（QImage 已在子线程降采样）。
        写入 _srcPixmap 供 paintIcon 复用，并只重绘本 item。
        :type image: QtGui.QImage
        :rtype: None
        """
        self._thumbnailLoading = False
        # 异步回调期间列表可能已被 clear/重排 -> 本 item 的 C++ 对象已销毁；
        # 用一次 C++ 方法探测（Python 属性访问探测不到），已删则整段放弃，避免 use-after-delete。
        try:
            self.listWidget()
        except RuntimeError:
            return
        self.clearCache()  # 作废旧的缩放缓存，让新原图按当前 rect 重新缩放

        if image is None or image.isNull():
            # 文件缺失/解码失败：缓存占位图并记住路径，避免每次重绘都反复入队解码
            self._srcPixmap = self._placeholderPixmap()
        else:
            pixmap = QtGui.QPixmap()
            pixmap.convertFromImage(image)
            self._srcPixmap = pixmap
            self._thumbnailIcon = QtGui.QIcon(pixmap)

        self._srcPixmapPath = self._pendingThumbnailPath  # 记录实际解码的路径，路径若已变会自动重新加载

        if self.itemsWidget():
            self.repaintItem()  # 只刷新本 item，避免后台缩略图回调触发整个视口重绘

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
                self._worker.setSize(self.MAX_ICON_SIZE)  # 后台缩放到该尺寸上限
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
        图标只占单元格顶部的方形区域（高度=itemSize），底部 40px 留给文字，
        避免竖构图缩略图被拉高、盖住下面的文字栏。
        :type option: QtWidgets.QStyleOptionViewItem
        :rtype: QtCore.QRect
        """
        padding = self.padding()
        cell = self.visualRect(option)
        iconSize = self.itemsWidget().itemSize()  # 顶部方形区边长，与 iconPercent/sizeHint 的划分保持一致

        x = int(cell.x() + padding / 2.0)
        y = int(cell.y() + padding / 2.0)
        width = int(cell.width() - padding)
        height = int(iconSize - padding)
        return QtCore.QRect(x, y, width, height)

    def scalePixmap(self, pixmap, rect):
        """
        Scale the given pixmap to the give rect size.

        This method will cache the scaled pixmap if called with the same size.

        缓存键 = (源帧内容 cacheKey, rect 宽高)：同一帧同尺寸重绘直接命中；帧变化时 cacheKey
        变化自动触发重缩，因此播放期间不再需要每帧 clearCache（消除每帧的 SmoothTransformation）。
        :type pixmap: QtGui.QPixmap
        :type rect: QtCore.QRect
        :rtype: QtGui.QPixmap
        """
        key = pixmap.cacheKey()
        rectChanged = (self._pixmapRect is None
                       or self._pixmapRect.width() != rect.width()
                       or self._pixmapRect.height() != rect.height())

        if self._pixmapScaled is None or rectChanged or self._pixmapScaledKey != key:
            self._pixmapScaled = pixmap.scaled(
                rect.width(),
                rect.height(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )

            self._pixmapRect = rect
            self._pixmapScaledKey = key

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
            if self.imageSequence() and self.underMouse():
                # 悬停播放：复用 updateFrame 已解码好的当前帧，避免在绘制里再次从磁盘解码
                pixmap = self._curFramePixmap
                if not pixmap:
                    pixmap = self.imageSequence().currentPixmap()
                    self._curFramePixmap = pixmap
            else:
                thumbnailPath = self.itemData()[7]
                if self._srcPixmap is not None and self._srcPixmapPath == thumbnailPath:
                    # 已缓存原图：直接复用，路径不变不再解码（滚动/重绘收益最大）
                    pixmap = self._srcPixmap
                elif self.ENABLE_THUMBNAIL_THREAD:
                    # 尚未缓存：丢到后台线程解码，首屏不再在主线程一次性解一堆 JPEG 造成卡顿；
                    # 本次绘制先用占位图，解码完成后回调只重绘本 item。
                    self._isVisibleInViewport = True  # 正在绘制 = 确实可见
                    self.requestThumbnailLoad()
                    pixmap = self._placeholderPixmap()
                else:
                    # 关闭后台线程时的同步回退（保留原行为）
                    pixmap = QtGui.QPixmap(thumbnailPath)
                    self._srcPixmap = pixmap
                    self._srcPixmapPath = thumbnailPath

            if not pixmap:
                return

            rect = self.iconRect(option)  # Return the icon rect for the item.
            pixmap = self.scalePixmap(pixmap, rect)

            pixmapRect = QtCore.QRect(rect)
            pixmapRect.setWidth(pixmap.width())
            pixmapRect.setHeight(pixmap.height())
            pixmapRect.moveCenter(rect.center())  # 在图标区域内居中，避免左上角对齐导致偏移
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
        self._curFramePixmap = None   # 重置帧缓存，避免复用上一次悬停的旧帧
        self._lastFrameNumber = -1
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
        每帧只从磁盘解码一次并缓存到 _curFramePixmap 供 paintIcon 复用；帧号未变则整体跳过。
        """
        seq = self.imageSequence()
        if not seq:
            return

        frameNumber = seq.currentFrameNumber()
        # 鼠标 scrub 时相邻位置常落在同一帧，重复帧直接跳过，省一次解码+重绘
        if frameNumber == self._lastFrameNumber and self._curFramePixmap:
            return
        self._lastFrameNumber = frameNumber

        self._curFramePixmap = seq.currentPixmap()
        self.repaintItem()  # 只重绘本 item；不再 setIcon → 不再每帧 clearCache，scalePixmap 缓存得以生效

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
