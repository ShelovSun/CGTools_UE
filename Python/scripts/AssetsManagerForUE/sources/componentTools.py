#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""服务器 C++ 组件库浏览、安装和重启页。"""

from __future__ import absolute_import

import os

from PySide6 import QtCore, QtGui, QtWidgets

from ..utils import messageBox, myWidget
from ..utils.source_folder_menu import add_open_source_folder_action
from . import component_service


_FLAT = "border-style: flat; background: transparent;"
_SCAN_POOL = QtCore.QThreadPool()
_SCAN_POOL.setMaxThreadCount(1)


class _MarkdownBrowser(QtWidgets.QTextBrowser):
    """显示本地 Markdown，并为文档中的本地 GIF 提供逐帧刷新。"""

    def __init__(self, parent=None):
        super(_MarkdownBrowser, self).__init__(parent)
        self._movies = []
        self._image_sizes = {}
        self._fit_timer = QtCore.QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fitImages)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet(
            "QTextBrowser{background:#181818; color:#d7d7d7; padding:12px;}"
            "QScrollBar:vertical{background:#202020; width:12px;}"
            "QScrollBar::handle:vertical{background:#555; min-height:24px;}"
        )
        self.document().setDefaultStyleSheet(
            "body{color:#d7d7d7; font-family:'Microsoft YaHei UI'; font-size:14px;}"
            "h1,h2,h3,h4{color:#f0f0f0;}"
            "a{color:#58a6ff;}"
            "blockquote{color:#b8b8b8; background:#242424;}"
            "pre{color:#ddd; background:#242424;}"
            "code{color:#efb366; background:#242424;}"
            "table{border-collapse:collapse;}"
            "th,td{border:1px solid #555; padding:5px;}"
        )
        self.anchorClicked.connect(self._openLink)

    def showMarkdown(self, document_path, text):
        self._stopMovies()
        self._image_sizes = {}
        base_folder = os.path.dirname(os.path.abspath(document_path))
        self.document().setBaseUrl(
            QtCore.QUrl.fromLocalFile(base_folder + os.path.sep))
        self.setMarkdown(text)
        self._prepareImages(base_folder)
        self.moveCursor(QtGui.QTextCursor.Start)
        self._fit_timer.start(0)

    def clearMarkdown(self):
        self._stopMovies()
        self._image_sizes = {}
        self.clear()

    def resizeEvent(self, event):
        super(_MarkdownBrowser, self).resizeEvent(event)
        self._fit_timer.start(80)

    def _imageFragments(self):
        fragments = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    if char_format.isImageFormat():
                        image_format = char_format.toImageFormat()
                        fragments.append((
                            fragment.position(), fragment.length(),
                            str(image_format.name()), image_format,
                        ))
                iterator += 1
            block = block.next()
        return fragments

    @staticmethod
    def _localImagePath(source, base_folder):
        source = str(source or "").strip()
        if not source:
            return ""
        url = QtCore.QUrl(source)
        if url.isLocalFile():
            return os.path.normpath(url.toLocalFile())
        normalized = source.replace("/", os.path.sep)
        if os.path.isabs(normalized):
            return os.path.normpath(normalized)
        if url.scheme():
            return ""
        try:
            decoded = QtCore.QUrl.fromPercentEncoding(source.encode("utf-8"))
        except (TypeError, UnicodeError):
            decoded = source
        decoded = str(decoded).split("#", 1)[0].split("?", 1)[0]
        return os.path.normpath(os.path.join(
            base_folder, decoded.replace("/", os.path.sep)))

    def _prepareImages(self, base_folder):
        seen_sources = set()
        for _position, _length, source, _image_format in self._imageFragments():
            if not source or source in seen_sources:
                continue
            seen_sources.add(source)
            image_path = self._localImagePath(source, base_folder)
            if not image_path or not os.path.isfile(image_path):
                continue

            reader = QtGui.QImageReader(image_path)
            size = reader.size()
            if size.isValid():
                self._image_sizes[source] = QtCore.QSize(size)

            raw_url = QtCore.QUrl(source)
            resolved_url = self.document().baseUrl().resolved(raw_url)
            resource_urls = (raw_url, resolved_url)
            if image_path.lower().endswith(".gif"):
                self._startGif(image_path, resource_urls)
                continue

            image = reader.read()
            if not image.isNull():
                for resource_url in resource_urls:
                    self.document().addResource(
                        QtGui.QTextDocument.ImageResource, resource_url, image)

    def _startGif(self, image_path, resource_urls):
        movie = QtGui.QMovie(image_path, parent=self)
        if not movie.isValid():
            return
        movie.setCacheMode(QtGui.QMovie.CacheAll)
        movie.frameChanged.connect(
            lambda _frame, current=movie, urls=resource_urls:
            self._updateGifFrame(current, urls))
        self._movies.append(movie)
        movie.start()

    def _updateGifFrame(self, movie, resource_urls):
        if movie not in self._movies:
            return
        pixmap = movie.currentPixmap()
        if pixmap.isNull():
            return
        for resource_url in resource_urls:
            self.document().addResource(
                QtGui.QTextDocument.ImageResource, resource_url, pixmap)
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()

    def _stopMovies(self):
        for movie in self._movies:
            movie.stop()
            movie.deleteLater()
        self._movies = []

    def _fitImages(self):
        maximum_width = max(160, self.viewport().width() - 36)
        keep_anchor = QtGui.QTextCursor.KeepAnchor
        for position, length, source, image_format in self._imageFragments():
            natural_size = self._image_sizes.get(source)
            if not natural_size or natural_size.width() <= 0:
                continue
            width = min(natural_size.width(), maximum_width)
            height = int(round(
                natural_size.height() * float(width) / natural_size.width()))
            if (int(image_format.width()) == width
                    and int(image_format.height()) == height):
                continue
            image_format.setWidth(width)
            image_format.setHeight(height)
            cursor = QtGui.QTextCursor(self.document())
            cursor.setPosition(position)
            cursor.setPosition(position + length, keep_anchor)
            cursor.mergeCharFormat(image_format)

    def _openLink(self, url):
        if not url.scheme() and not url.path() and url.fragment():
            self.scrollToAnchor(url.fragment())
            return
        target = self.document().baseUrl().resolved(url)
        QtGui.QDesktopServices.openUrl(target)


class _ComponentCardList(myWidget.MainQListWiget):
    def mouseDoubleClickEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            event.accept()
            return
        super(_ComponentCardList, self).mouseDoubleClickEvent(event)


class _ScanSignals(QtCore.QObject):
    loaded = QtCore.Signal(int, object)
    failed = QtCore.Signal(int, str)


class _ComponentScanTask(QtCore.QRunnable):
    """后台扫描网络组件库；不在子线程中调用任何 Unreal API 或 Qt 控件。"""

    def __init__(self, generation, candidates, plugins_dir):
        super(_ComponentScanTask, self).__init__()
        self.signals = _ScanSignals()
        self.generation = int(generation)
        self.candidates = tuple(candidates)
        self.plugins_dir = str(plugins_dir)
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            payload = component_service.scan_component_library(
                self.candidates,
                self.plugins_dir,
                cancelled=lambda: self.cancelled,
            )
            if not self.cancelled:
                self.signals.loaded.emit(self.generation, payload)
        except Exception as exc:
            if not self.cancelled:
                self.signals.failed.emit(self.generation, str(exc))


class ComponentToolsUI(QtWidgets.QWidget):
    """与资产、蓝图页一致的组件分类卡片浏览器。"""

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace(
        "\\", "/").replace("sources", "")

    def __init__(self, parent=None):
        super(ComponentToolsUI, self).__init__(parent)
        self.isList = False
        self._scan_generation = 0
        self._scan_task = None
        self._library_payload = {}
        self._categories = {}
        self._category_items = {}
        self._component_items = {}
        self._categories_by_folder = {}
        self._components_by_folder = {}
        self._copy_thread = None
        self._copy_worker = None
        self._copy_folder = ""
        self._copy_stage_replacement = False
        self._current_document_path = ""
        self._fallback_icon = "%s/icon/component.png" % self.scriptsPath
        self._folder_icon = "%s/icon/floder.png" % self.scriptsPath
        self._buildUI()
        QtCore.QTimer.singleShot(0, self.refreshLibrary)

    # ------------------------------------------------------------------ UI
    def _buildUI(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        self.content_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.content_splitter.setHandleWidth(3)
        self.content_splitter.setChildrenCollapsible(False)
        root.addWidget(self.content_splitter, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(3)
        category_label = QtWidgets.QLabel(u"组件分类")
        category_label.setStyleSheet(
            "font-weight:bold; color:#d7d7d7; padding:4px 5px; background:#252628;")
        left_layout.addWidget(category_label)
        self.category_list = QtWidgets.QTreeWidget()
        self.category_list.setHeaderHidden(True)
        self.category_list.setIndentation(16)
        self.category_list.setIconSize(QtCore.QSize(16, 16))
        self.category_list.setUniformRowHeights(True)
        self.category_list.setStyleSheet(
            "QTreeWidget{background:#1a1a1a; color:#b1b1b1; font-size:13px; border:0;}"
            "QTreeWidget::item{padding:5px 2px;}"
            "QTreeWidget::item:selected{background:#343a40; color:#f3f3f3;}"
            "QTreeWidget::item:hover{background:#303030;}"
        )
        self.category_list.setMinimumWidth(145)
        left_layout.addWidget(self.category_list, 1)
        self.content_splitter.addWidget(left)

        center = QtWidgets.QWidget()
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(2)
        self.parent_button = self._toolButton("back.png", u"返回上一级文件夹")
        self.parent_button.setEnabled(False)
        toolbar.addWidget(self.parent_button)
        self.display_button = self._toolButton("display_list.png", u"表单显示")
        toolbar.addWidget(self.display_button)
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(64, 200)
        self.size_slider.setValue(120)
        self.size_slider.setMaximumWidth(250)
        self.size_slider.setToolTip(u"缩放组件卡片")
        toolbar.addWidget(self.size_slider)
        self.refresh_button = self._toolButton("refresh.png", u"刷新组件库")
        toolbar.addWidget(self.refresh_button)
        self.load_button = QtWidgets.QPushButton(u"加载组件")
        self.load_button.setMinimumHeight(27)
        self.load_button.setToolTip(u"把所选组件完整复制到当前 UE 工程的 Plugins 目录")
        self.load_button.setStyleSheet(
            "QPushButton{background:#256f3a; font-weight:bold; padding:3px 12px;}"
            "QPushButton:hover{background:#2f8b49;}"
            "QPushButton:disabled{background:#454545; color:#888;}")
        toolbar.addWidget(self.load_button)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(u"搜索当前文件夹中的文件夹或组件…")
        self.search_edit.addAction(
            QtGui.QIcon("%s/icon/search.png" % self.scriptsPath),
            QtWidgets.QLineEdit.LeadingPosition)
        toolbar.addWidget(self.search_edit, 1)
        center_layout.addLayout(toolbar)

        self.card_list = _ComponentCardList()
        self.card_list.setSortingEnabled(False)
        self.card_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.card_list.setListColumns(
            (u"修改日期", u"名称", u"分类", u"目录"),
            (0, 1, 2, 8),
            (135, 230, 140, 520),
            ("datetime", None, None, None),
            ("center", "left", "left", "left"),
        )
        self.component_list_header = myWidget.AssetListHeader(self.card_list)
        self.component_list_header.setClickable(False)
        self.component_list_header.setSortIndicator(-1, False)
        self.component_list_header.hide()
        self.card_list.setListHeader(self.component_list_header)
        center_layout.addWidget(self.component_list_header)
        center_layout.addWidget(self.card_list, 1)
        self.content_splitter.addWidget(center)

        self.documentation_panel = QtWidgets.QWidget()
        self.documentation_panel.setMinimumWidth(340)
        self.documentation_panel.setStyleSheet(
            "QWidget#componentDocumentationPanel{"
            "background:#181818; border-left:1px solid #3d3d3d;}"
        )
        self.documentation_panel.setObjectName("componentDocumentationPanel")
        documentation_layout = QtWidgets.QVBoxLayout(self.documentation_panel)
        documentation_layout.setContentsMargins(0, 0, 0, 0)
        documentation_layout.setSpacing(0)

        documentation_header = QtWidgets.QWidget()
        documentation_header.setStyleSheet(
            "QWidget{background:#252628; border-bottom:1px solid #3d3d3d;}"
        )
        documentation_header_layout = QtWidgets.QHBoxLayout(documentation_header)
        documentation_header_layout.setContentsMargins(9, 5, 5, 5)
        documentation_header_layout.setSpacing(6)
        self.documentation_title = QtWidgets.QLabel(u"使用说明")
        self.documentation_title.setStyleSheet(
            "font-weight:bold; color:#e1e1e1; border:0; background:transparent;")
        self.documentation_title.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse)
        documentation_header_layout.addWidget(self.documentation_title, 1)
        self.documentation_external_button = QtWidgets.QPushButton(u"外部打开")
        self.documentation_external_button.setToolTip(u"使用系统默认程序打开当前 Markdown")
        self.documentation_external_button.setMinimumHeight(25)
        documentation_header_layout.addWidget(self.documentation_external_button)
        self.documentation_close_button = QtWidgets.QPushButton(u"关闭")
        self.documentation_close_button.setToolTip(u"关闭使用说明面板")
        self.documentation_close_button.setMinimumHeight(25)
        documentation_header_layout.addWidget(self.documentation_close_button)
        documentation_layout.addWidget(documentation_header)

        self.documentation_browser = _MarkdownBrowser(self.documentation_panel)
        documentation_layout.addWidget(self.documentation_browser, 1)
        self.content_splitter.addWidget(self.documentation_panel)
        self.documentation_panel.hide()

        self.content_splitter.setSizes([175, 760, 0])
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 1)

        message_row = QtWidgets.QHBoxLayout()
        message_row.setSpacing(8)
        self.message_icon = QtWidgets.QLabel()
        self.message_icon.setFixedSize(15, 15)
        self.message_icon.setScaledContents(True)
        message_row.addWidget(self.message_icon)
        self.message_label = QtWidgets.QLabel()
        self.message_label.setMaximumHeight(18)
        message_row.addWidget(self.message_label, 1)
        root.addLayout(message_row)

        thumb_size, category_name, is_list = self._readSettings()
        if thumb_size is not None:
            try:
                self.size_slider.setValue(int(thumb_size))
            except (TypeError, ValueError):
                pass
        self._preferred_category = str(category_name or "")
        self.isList = str(is_list).lower() == "true" if is_list is not None else False
        self.component_list_header.setVisible(self.isList)
        self._updateDisplayButton()

        self.category_list.currentItemChanged.connect(self._categoryChanged)
        self.parent_button.clicked.connect(self._goToParentCategory)
        self.display_button.clicked.connect(self.toggleDisplayMode)
        self.size_slider.valueChanged.connect(self._sizeChanged)
        self.size_slider.sliderReleased.connect(self._rememberSettings)
        self.refresh_button.clicked.connect(self.refreshLibrary)
        self.load_button.clicked.connect(self.loadComponent)
        self.search_edit.returnPressed.connect(self._rebuildCards)
        self.search_edit.textChanged.connect(self._searchTextChanged)
        self.card_list.customContextMenuRequested.connect(self._showContextMenu)
        self.card_list.itemSelectionChanged.connect(self._selectionChanged)
        self.card_list.itemDoubleClicked.connect(self._enterFolder)
        self.card_list.assetDragRejected.connect(self._dragRejected)
        self.documentation_external_button.clicked.connect(
            self._openCurrentDocumentExternally)
        self.documentation_close_button.clicked.connect(
            self._closeDocumentationPanel)

    def _toolButton(self, icon_name, tooltip):
        button = QtWidgets.QPushButton()
        button.setFixedSize(25, 25)
        button.setIconSize(QtCore.QSize(22, 22))
        button.setIcon(QtGui.QIcon("%s/icon/%s" % (self.scriptsPath, icon_name)))
        button.setToolTip(tooltip)
        button.setStyleSheet(_FLAT)
        return button

    # ------------------------------------------------------------ 扫描/分类
    def refreshLibrary(self):
        if self._operationIsRunning():
            self.infoMsg("warning", u"正在加载组件，完成后才能刷新")
            return
        self._rememberSettings()
        self._scan_generation += 1
        generation = self._scan_generation
        if self._scan_task is not None:
            self._scan_task.cancel()
            self._scan_task = None
        self.category_list.setEnabled(False)
        self.parent_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.card_list.clear()
        self.infoMsg("info", u"正在后台扫描服务器组件库…")
        try:
            plugins_dir = component_service.project_plugins_directory()
        except Exception as exc:
            self.category_list.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self._updateParentButton()
            self.infoMsg("error", str(exc))
            return
        task = _ComponentScanTask(
            generation, component_service.COMPONENT_ROOT_CANDIDATES, plugins_dir)
        task.signals.loaded.connect(self._scanFinished)
        task.signals.failed.connect(self._scanFailed)
        self._scan_task = task
        _SCAN_POOL.start(task)

    def _scanFinished(self, generation, payload):
        if generation != self._scan_generation:
            return
        self._scan_task = None
        self._library_payload = payload or {}
        self._categories = {}
        self._category_items = {}
        self._component_items = {}
        self._categories_by_folder = {}
        self._components_by_folder = {}
        self.category_list.blockSignals(True)
        self.category_list.clear()
        folder_icon = QtGui.QIcon(self._folder_icon)
        component_icon = QtGui.QIcon(self._fallback_icon)

        def add_category(category, parent=None):
            category_path = category["path"]
            self._categories[category_path] = category
            self._categories_by_folder[os.path.normcase(category["folder"])] = category
            item = QtWidgets.QTreeWidgetItem([category["name"]])
            item.setData(0, QtCore.Qt.UserRole, category_path)
            item.setData(0, QtCore.Qt.UserRole + 1, category["folder"])
            item.setToolTip(0, category["folder"])
            item.setIcon(0, folder_icon)
            if parent is None:
                self.category_list.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._category_items[category_path] = item
            for child in category.get("categories") or []:
                add_category(child, item)
            for component in category.get("components") or []:
                self._components_by_folder[os.path.normcase(component["folder"])] = component
                component_item = QtWidgets.QTreeWidgetItem([component["name"]])
                component_item.setData(0, QtCore.Qt.UserRole, component["path"])
                component_item.setData(0, QtCore.Qt.UserRole + 1, component["folder"])
                component_item.setToolTip(0, component["folder"])
                component_item.setIcon(0, component_icon)
                item.addChild(component_item)
                self._component_items[component["path"]] = component_item

        root_category = {
            "name": u"组件库",
            "path": ".",
            "folder": self._library_payload.get("root") or "",
            "categories": self._library_payload.get("categories") or [],
            "components": self._library_payload.get("components") or [],
        }
        add_category(root_category)
        self.category_list.collapseAll()
        self.category_list.blockSignals(False)
        self.category_list.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self._navigateToCategory(self._preferred_category or ".")

    def _scanFailed(self, generation, error):
        if generation != self._scan_generation:
            return
        self._scan_task = None
        self.category_list.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.parent_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self._categories = {}
        self._category_items = {}
        self._component_items = {}
        self._categories_by_folder = {}
        self._components_by_folder = {}
        self.category_list.clear()
        self.card_list.clear()
        self.infoMsg("error", error)

    def _categoryChanged(self, current, previous=None):
        del previous
        if current is None:
            self.card_list.clear()
            return
        # 目录和组件均使用相对路径作为标识，允许不同层级出现同名节点。
        self._preferred_category = str(current.data(0, QtCore.Qt.UserRole) or ".")
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._rememberSettings()
        self._updateParentButton()
        self._rebuildCards()

    def _currentCategory(self):
        item = self.category_list.currentItem()
        if item is None:
            return ""
        if str(item.data(0, QtCore.Qt.UserRole)) in self._component_items:
            item = item.parent()
        return str(item.data(0, QtCore.Qt.UserRole) or ".")

    def _navigateToCategory(self, category_path):
        item = self._category_items.get(category_path)
        if item is None:
            item = self._component_items.get(category_path)
        if item is None:
            item = self._category_items.get(".")
        if item is None:
            return
        self._selectTreeItem(item)

    def _selectTreeItem(self, item, rebuild=True):
        """定位树节点；卡片同步选择时不重建当前列表，保留筛选和滚动位置。"""
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        if rebuild:
            self.category_list.setCurrentItem(item)
        elif self.category_list.currentItem() != item:
            signals_blocked = self.category_list.blockSignals(True)
            try:
                self.category_list.setCurrentItem(item)
            finally:
                self.category_list.blockSignals(signals_blocked)
            self._preferred_category = str(item.data(0, QtCore.Qt.UserRole) or ".")
            self._rememberSettings()
        self.category_list.scrollToItem(item)

    def _enterFolder(self, item):
        if self._scan_task is not None or self._operationIsRunning():
            return
        category = self._categories_by_folder.get(self._folderForItem(item))
        if category is not None:
            self._navigateToCategory(category["path"])

    def _goToParentCategory(self):
        current = self._category_items.get(self._currentCategory())
        if current is not None and current.parent() is not None:
            self._navigateToCategory(str(current.parent().data(0, QtCore.Qt.UserRole)))

    def _updateParentButton(self):
        current = self._category_items.get(self._currentCategory())
        self.parent_button.setEnabled(
            current is not None and current.parent() is not None
            and self.category_list.isEnabled()
            and not self._operationIsRunning())

    def _rebuildCards(self):
        # clear() 可能在删除旧卡片前发出选择变化；重建期间不要把树选回旧组件。
        signals_blocked = self.card_list.blockSignals(True)
        try:
            self._populateCards()
        finally:
            self.card_list.blockSignals(signals_blocked)
        self._selectionChanged()

    def _populateCards(self):
        category_name = self._currentCategory()
        category = self._categories.get(category_name)
        self.card_list.clear()
        self.component_list_header.setVisible(self.isList)
        if not category:
            return
        keyword = self.search_edit.text().strip().lower()
        rows = []
        entries = ((category.get("categories") or [])
                   + (category.get("components") or []))
        entries = [entry for entry in entries
                   if not keyword or keyword in entry["name"].lower()]
        category_label = category_name if category_name != "." else category["name"]
        for entry in entries:
            is_component = "plan" in entry
            icon_path = ((entry.get("icon") or self._fallback_icon)
                         if is_component else self._folder_icon)
            rows.append((
                entry.get("modified", 0), entry["name"], category_label,
                "", "", "", "", icon_path,
                entry["folder"], category_name, entry["folder"],
            ))

        self.card_list.setItems(rows)
        self.card_list.setIsList(self.isList)
        self.card_list.setItemSize(self.size_slider.value())
        self.card_list.addItems("")
        self.card_list.setMode()
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            item.setDragEnabled(False)
            item.setUEMainObjectPath("")
            component = self._componentForItem(item)
            if component:
                plan = component.get("plan") or {}
                item.setUEState(
                    plan.get("state") or "missing",
                    plan.get("message") or u"等待加载组件",
                    plan,
                )
                item.setUEMainObjectPath("")
            else:
                item.setUEState(
                    "folder", u"左键双击进入文件夹：{0}".format(item.itemData()[10]))
        selected = self.category_list.currentItem()
        selected_path = str(selected.data(0, QtCore.Qt.UserRole)) if selected else ""
        if selected_path in self._component_items:
            component_item = self._component_items[selected_path]
            item = self._itemForFolder(component_item.data(0, QtCore.Qt.UserRole + 1))
            if item is not None:
                self.card_list.setCurrentItem(item)
                self.card_list.scrollToItem(item)
        components = [entry for entry in entries if "plan" in entry]
        ready_count = sum((entry["plan"].get("state") == "ready") for entry in components)
        self.infoMsg("info", u"{0}：{1} 个文件夹，{2} 个组件；已加载 {3} 个".format(
            category_label, len(entries) - len(components), len(components), ready_count))

    def _searchTextChanged(self, text):
        if not text:
            self._rebuildCards()

    # --------------------------------------------------------------- 卡片状态
    def _componentForItem(self, item):
        return self._components_by_folder.get(self._folderForItem(item))

    @staticmethod
    def _folderForItem(item):
        if item is None:
            return ""
        try:
            return os.path.normcase(str(item.itemData()[10]))
        except (IndexError, TypeError, RuntimeError):
            return ""

    def _itemForFolder(self, folder):
        key = os.path.normcase(str(folder or ""))
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            try:
                if os.path.normcase(str(item.itemData()[10])) == key:
                    return item
            except (IndexError, TypeError, RuntimeError):
                pass
        return None

    def _applyComponentState(self, component):
        if not component:
            return
        item = self._itemForFolder(component.get("folder"))
        if item is None:
            return
        plan = component.get("plan") or {}
        item.setUEState(
            plan.get("state") or "missing",
            plan.get("message") or u"等待加载组件",
            plan,
        )
        item.setDragEnabled(False)
        item.setUEMainObjectPath("")
        self._selectionChanged()

    def _setComponentProgress(self, folder, percent, message):
        component = self._components_by_folder.get(os.path.normcase(str(folder or "")))
        if component is not None:
            plan = component.get("plan") or {}
            plan["state"] = "importing"
            plan["message"] = message
        item = self._itemForFolder(folder)
        if item is not None:
            item.setUEProgress(percent, message)
            item.setDragEnabled(False)

    def _selectionChanged(self):
        selected = self.card_list.currentItem()
        component = self._componentForItem(selected)
        if selected is not None:
            tree_item = (self._component_items.get(component["path"]) if component
                         else self._category_items.get(self._currentCategory()))
            if tree_item is not None:
                self._selectTreeItem(tree_item, rebuild=False)
        self._updateParentButton()
        self.load_button.setEnabled(
            component is not None
            and self._scan_task is None
            and not self._operationIsRunning())

    def _operationIsRunning(self):
        return bool(self._copy_thread is not None and self._copy_thread.isRunning())

    def _setOperationControls(self, enabled):
        self.category_list.setEnabled(bool(enabled))
        self.refresh_button.setEnabled(bool(enabled))
        self._updateParentButton()
        if enabled:
            self._selectionChanged()
        else:
            self.load_button.setEnabled(False)

    # -------------------------------------------------------------- 加载组件
    def _showContextMenu(self, point):
        item = self.card_list.itemAt(point)
        if item is None:
            return
        self.card_list.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        add_open_source_folder_action(menu, str(item.itemData()[10]))
        menu.addSeparator()
        if self._folderForItem(item) in self._categories_by_folder:
            open_action = menu.addAction(u"进入文件夹")
            open_action.setEnabled(self._scan_task is None and not self._operationIsRunning())
            open_action.triggered.connect(
                lambda checked=False, selected=item: self._enterFolder(selected))
            menu.exec_(self.card_list.viewport().mapToGlobal(point))
            return
        load_action = QtGui.QAction(u"加载组件", self)
        load_action.setToolTip(u"复制整个组件文件夹到当前 UE 工程 Plugins")
        load_action.setEnabled(not self._operationIsRunning())
        load_action.triggered.connect(
            lambda checked=False, selected=item: self.loadComponent(selected))
        menu.addAction(load_action)
        usage_action = QtGui.QAction(u"使用说明", self)
        usage_action.setToolTip(u"打开组件文件夹中的第一个 Markdown 使用说明文档")
        usage_action.triggered.connect(
            lambda checked=False, selected=item: self.openUsageInstructions(selected))
        menu.addAction(usage_action)
        menu.exec_(self.card_list.viewport().mapToGlobal(point))

    def openUsageInstructions(self, item=None):
        """在组件页右侧显示组件根目录中的第一个 Markdown 文档。"""
        if isinstance(item, bool):
            item = None
        item = item or self.card_list.currentItem()
        component = self._componentForItem(item)
        if component is None:
            self.infoMsg("warning", u"请先选择一张组件卡片")
            return

        component_folder = str(component.get("folder") or "")
        try:
            documents = [
                os.path.join(component_folder, filename)
                for filename in os.listdir(component_folder)
                if (filename.lower().endswith(".md")
                    and os.path.isfile(os.path.join(component_folder, filename)))
            ]
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self,
                u"使用说明",
                u"无法读取组件目录：\n{0}\n\n{1}".format(
                    component_folder, exc),
            )
            return

        if not documents:
            QtWidgets.QMessageBox.warning(
                self,
                u"使用说明",
                u"该组件还没有使用说明文档，请联系制作者",
            )
            return

        document_path = sorted(
            documents,
            key=lambda path: os.path.basename(path).lower(),
        )[0]
        try:
            markdown_text = self._readMarkdown(document_path)
        except (OSError, UnicodeError) as exc:
            QtWidgets.QMessageBox.warning(
                self,
                u"使用说明",
                u"无法读取使用说明文档：\n{0}\n\n{1}".format(
                    document_path, exc),
            )
            return

        self._current_document_path = document_path
        self.documentation_title.setText(u"{0} — {1}".format(
            component.get("name") or os.path.basename(component_folder),
            os.path.basename(document_path),
        ))
        self.documentation_title.setToolTip(document_path)
        self.documentation_browser.showMarkdown(document_path, markdown_text)
        self.documentation_panel.show()
        QtCore.QTimer.singleShot(0, self._resizeDocumentationPanel)

    @staticmethod
    def _readMarkdown(document_path):
        """兼容工具库中常见的 UTF-8 与旧 GB18030 Markdown。"""
        decoding_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                with open(document_path, "r", encoding=encoding) as stream:
                    return stream.read()
            except UnicodeDecodeError as exc:
                decoding_error = exc
        if decoding_error is not None:
            raise decoding_error
        raise OSError(u"无法读取文档")

    def _resizeDocumentationPanel(self):
        if not self.documentation_panel.isVisible():
            return
        total_width = max(760, self.content_splitter.width())
        current_sizes = self.content_splitter.sizes()
        left_width = 175
        if current_sizes:
            left_width = max(145, min(240, current_sizes[0] or 175))
        remaining = max(600, total_width - left_width)
        documentation_width = max(340, int(remaining * 0.48))
        card_width = max(300, remaining - documentation_width)
        self.content_splitter.setSizes(
            [left_width, card_width, documentation_width])

    def _closeDocumentationPanel(self):
        if not self.documentation_panel.isVisible():
            return
        current_sizes = self.content_splitter.sizes()
        left_width = current_sizes[0] if current_sizes else 175
        content_width = sum(current_sizes[1:]) if len(current_sizes) > 1 else 760
        self.documentation_browser.clearMarkdown()
        self.documentation_panel.hide()
        self.documentation_title.setText(u"使用说明")
        self.documentation_title.setToolTip("")
        self._current_document_path = ""
        self.content_splitter.setSizes([left_width, content_width, 0])

    def _openCurrentDocumentExternally(self):
        document_path = self._current_document_path
        if not document_path or not os.path.isfile(document_path):
            QtWidgets.QMessageBox.warning(
                self,
                u"使用说明",
                u"当前使用说明文档已不存在或暂时无法访问",
            )
            return
        if not QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(document_path)):
            QtWidgets.QMessageBox.warning(
                self,
                u"使用说明",
                u"无法使用外部程序打开文档：\n{0}".format(document_path),
            )

    def loadComponent(self, item=None):
        if isinstance(item, bool):
            item = None
        item = item or self.card_list.currentItem()
        component = self._componentForItem(item)
        if component is None:
            self.infoMsg("warning", u"请先选择一张组件卡片")
            return
        if self._operationIsRunning():
            self.infoMsg("warning", u"已有组件正在加载，请等待完成")
            return
        previous = component.get("plan") or {}
        try:
            plan = component_service.build_component_plan(
                component["category"], component["folder"], previous["plugins_dir"])
            plan = component_service.query_component_state(plan, verify_content=True)
        except Exception as exc:
            self.infoMsg("error", u"检查组件失败：{0}".format(exc))
            return
        component["plan"] = plan
        self._applyComponentState(component)
        state = plan.get("state") or "error"
        if state == "error":
            self.infoMsg("error", plan.get("message") or u"组件发布内容无效")
            return
        if state == "ready":
            self.infoMsg("info", u"{0} 已在当前工程 Plugins 中".format(
                component["name"]))
            return
        if state == "conflict":
            if not self._chooseConflictFiles(plan):
                return
            self._startCopy(component, plan, stage_replacement=bool(plan.get("overwrite_files")))
            return
        self._startCopy(component, plan, stage_replacement=False)

    def _chooseConflictFiles(self, plan):
        from .sceneTools import choose_ue_conflict_files
        return choose_ue_conflict_files(self, plan, plugin_files=True)

    def _confirmReplacement(self, component, plan):
        different = list(plan.get("different_files") or [])
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(u"更新工程组件")
        box.setText(u"工程中已经存在不同版本的【{0}】。".format(component["name"]))
        box.setInformativeText(
            u"UE 运行期间不能安全覆盖可能正在使用的插件 DLL。\n\n"
            u"继续后会先把服务器版本复制到安全暂存目录；复制完成时再次询问，"
            u"确认重启后才会替换工程组件。原版本会备份到工程 Saved 目录。\n\n"
            u"目标：{0}\n不同文件：{1} 个".format(
                plan.get("target_folder") or "", len(different)))
        if different:
            box.setDetailedText(u"检测到的不同文件：\n" + u"\n".join(different))
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        box.setEscapeButton(QtWidgets.QMessageBox.Cancel)
        yes_button = box.button(QtWidgets.QMessageBox.Yes)
        if yes_button is not None:
            yes_button.setText(u"暂存新版本")
        cancel_button = box.button(QtWidgets.QMessageBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText(u"取消")
        return box.exec() == QtWidgets.QMessageBox.Yes

    def _startCopy(self, component, plan, stage_replacement=False):
        self._copy_folder = component["folder"]
        self._copy_stage_replacement = bool(stage_replacement)
        message = (u"正在暂存新版本，完成后重启替换…" if stage_replacement
                   else u"正在复制组件到当前工程 Plugins…")
        self._setComponentProgress(self._copy_folder, 0, message)
        self._setOperationControls(False)
        thread = QtCore.QThread()
        worker = component_service.ComponentCopyWorker(
            plan, stage_replacement=stage_replacement)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._copyProgress)
        worker.finished.connect(self._copyFinished)
        worker.failed.connect(self._copyFailed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._copyThreadFinished)
        self._copy_thread = thread
        self._copy_worker = worker
        thread.start()

    def _copyProgress(self, percent, relative_name):
        prefix = u"正在暂存组件" if self._copy_stage_replacement else u"正在加载组件"
        message = u"{0} {1}%：{2}".format(prefix, percent, relative_name)
        self._setComponentProgress(self._copy_folder, percent, message)
        self.infoMsg("info", message)

    def _copyFinished(self, plan):
        component = self._components_by_folder.get(
            os.path.normcase(str(self._copy_folder or "")))
        if component is None:
            return
        component["plan"] = plan
        if plan.get("install_mode") == "replace_after_exit":
            plan["state"] = "importing"
            plan["message"] = u"选定更新已暂存，等待重启替换"
            self._applyComponentState(component)
            self._promptRestart(component, plan, replacing=True)
            return

        self._applyComponentState(component)
        if plan.get("state") == "ready" or plan.get("load_completed"):
            self.infoMsg("info", u"{0}：{1}".format(component["name"], plan.get("message") or u"组件已复制到工程 Plugins"))
            if plan.get("created_files"):
                self._promptRestart(component, plan, replacing=False)
        else:
            self.infoMsg("error", plan.get("message") or u"组件加载后校验失败")

    def _copyFailed(self, message):
        component = self._components_by_folder.get(
            os.path.normcase(str(self._copy_folder or "")))
        if component is not None:
            plan = component.get("plan") or {}
            plan["state"] = "error"
            plan["message"] = str(message)
            self._applyComponentState(component)
        self.infoMsg("error", u"加载组件失败：{0}".format(message))

    def _copyThreadFinished(self):
        self._copy_thread = None
        self._copy_worker = None
        self._copy_folder = ""
        self._copy_stage_replacement = False
        self._setOperationControls(True)

    def _promptRestart(self, component, plan, replacing=False):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(u"重启 Unreal Editor")
        if replacing:
            box.setText(u"【{0}】选定更新已暂存完成，是否立即重启 UE 并替换？".format(
                component["name"]))
            box.setInformativeText(
                u"确认后会先弹出 UE 的未保存内容对话框；UE 完全退出后才应用选中的覆盖文件，"
                u"未选中的文件保留工程版本，然后重新打开当前 .uproject。原版本会备份到工程 Saved 目录。")
        else:
            box.setText(u"【{0}】已加载到工程 Plugins，是否立即重启 UE？".format(
                component["name"]))
            box.setInformativeText(
                u"新组件需要重启 Unreal Editor 才能被发现和加载。选择“稍后重启”不会撤销已复制的组件。")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        box.setEscapeButton(QtWidgets.QMessageBox.No)
        yes_button = box.button(QtWidgets.QMessageBox.Yes)
        if yes_button is not None:
            yes_button.setText(u"立即重启")
        no_button = box.button(QtWidgets.QMessageBox.No)
        if no_button is not None:
            no_button.setText(u"稍后重启" if not replacing else u"取消替换")

        if box.exec() != QtWidgets.QMessageBox.Yes:
            if replacing:
                component_service.discard_staged_component(
                    plan.get("staging_folder"), plan.get("plugins_dir"))
                plan.pop("staging_folder", None)
                plan.pop("install_mode", None)
                plan["state"] = "conflict"
                plan["message"] = u"工程中仍是原版本；本次替换已取消"
                self._applyComponentState(component)
                self.infoMsg("warning", plan["message"])
            else:
                self.infoMsg("info", u"组件已加载；将在下次启动 UE 时生效")
            return

        success, error = component_service.restart_editor(
            plan if replacing else None)
        if success:
            self.infoMsg("info", u"正在退出并重新打开当前 UE 工程…")
            return
        if replacing:
            component_service.discard_staged_component(
                plan.get("staging_folder"), plan.get("plugins_dir"))
            plan.pop("staging_folder", None)
            plan.pop("install_mode", None)
            plan["state"] = "conflict"
            plan["message"] = u"组件未替换：{0}".format(error)
            self._applyComponentState(component)
        self.infoMsg("warning", error)

    def _dragRejected(self, text):
        del text
        self.infoMsg("warning", u"组件卡片是 UE 插件安装包，不能直接拖入关卡；加载并重启 UE 后，请从内容浏览器或添加组件面板使用插件提供的资源")

    # ------------------------------------------------------------ 显示/设置
    def toggleDisplayMode(self):
        self.isList = not self.isList
        self._updateDisplayButton()
        self._rebuildCards()
        self._rememberSettings()

    def _updateDisplayButton(self):
        if self.isList:
            self.display_button.setIcon(
                QtGui.QIcon("%s/icon/display_icon.png" % self.scriptsPath))
            self.display_button.setToolTip(u"缩略图显示")
        else:
            self.display_button.setIcon(
                QtGui.QIcon("%s/icon/display_list.png" % self.scriptsPath))
            self.display_button.setToolTip(u"表单显示")

    def _sizeChanged(self, value):
        if self.isList:
            return
        self.card_list.setItemSize(value)
        self.card_list.setIconSize(QtCore.QSize(value, value))
        self.card_list.setGridSize(QtCore.QSize(
            value + self.card_list.DEF_SPACING,
            value + self.card_list.DEF_SPACING + self.card_list.textAreaHeight()))

    def _readSettings(self):
        settings = QtCore.QSettings("AssetsManagerUE", "ComponentLibrary")
        return (settings.value("thumbSize"), settings.value("category"),
                settings.value("isList"))

    def _rememberSettings(self):
        if not hasattr(self, "size_slider"):
            return
        settings = QtCore.QSettings("AssetsManagerUE", "ComponentLibrary")
        settings.setValue("thumbSize", self.size_slider.value())
        current = self.category_list.currentItem()
        settings.setValue("category", str(current.data(0, QtCore.Qt.UserRole))
                          if current is not None else "")
        settings.setValue("isList", self.isList)

    def infoMsg(self, icon, text):
        messageBox.show_msg(self.message_icon, icon, self.message_label, str(text))

    def shutdownThreads(self):
        if hasattr(self, "documentation_browser"):
            self.documentation_browser.clearMarkdown()
        self._scan_generation += 1
        if self._scan_task is not None:
            self._scan_task.cancel()
            self._scan_task = None
        if self._copy_worker is not None:
            self._copy_worker.cancel()
        if self._copy_thread is not None and self._copy_thread.isRunning():
            self._copy_thread.quit()
            self._copy_thread.wait(1000)
        self._copy_worker = None
        self._copy_thread = None
