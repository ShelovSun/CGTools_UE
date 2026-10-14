#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""服务器蓝图库浏览、整分类加载与关卡拖放页。"""

from __future__ import absolute_import

import hashlib
import os
import time
import uuid

try:
    import unreal
except ImportError:
    unreal = None

from PySide6 import QtCore, QtGui, QtWidgets

from ..utils import messageBox, myWidget
from ..utils.source_folder_menu import add_open_source_folder_action
from . import ue_asset_service


BLUEPRINT_CONTENT_CANDIDATES = (
    r"Y:\MCCTools\src\UE574\BlueprintFun\Content",
    r"\\fznas.diandian.info\AC\MCCTools\src\UE574\BlueprintFun\Content",
)
BLUEPRINT_LIBRARY_RELATIVE = os.path.join("Assets", "Blueprints")
_FLAT = "border-style: flat; background: transparent;"
_SCAN_POOL = QtCore.QThreadPool()
_SCAN_POOL.setMaxThreadCount(1)


def _forward(path):
    return str(path or "").replace("\\", "/")


def _thumbnail_paths(source_file):
    """按源路径、大小和修改时间生成稳定的本机缩略图缓存键。"""
    try:
        stat = os.stat(source_file)
        fingerprint = u"{0}|{1}|{2}".format(
            os.path.normcase(os.path.abspath(source_file)),
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )
    except OSError:
        fingerprint = os.path.normcase(os.path.abspath(source_file))
    digest = hashlib.sha1(fingerprint.encode("utf-8", "surrogatepass")).hexdigest()
    root = os.path.join(os.environ.get("TEMP") or os.getcwd(),
                        "AssetsManagerBlueprintThumbnails")
    png = os.path.join(root, digest + ".png")
    return png, png + ".no_thumbnail"


class _ScanSignals(QtCore.QObject):
    loaded = QtCore.Signal(int, object)
    failed = QtCore.Signal(int, str)


class _LibraryScanTask(QtCore.QRunnable):
    """后台扫描网络蓝图库；不调用任何 unreal API 或 Qt 控件。"""

    def __init__(self, generation, candidates, project_content_dir):
        super(_LibraryScanTask, self).__init__()
        self.signals = _ScanSignals()
        self.generation = int(generation)
        self.candidates = tuple(candidates)
        self.project_content_dir = str(project_content_dir)
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            content_root = ""
            for candidate in self.candidates:
                if self.cancelled:
                    return
                try:
                    if os.path.isdir(candidate):
                        content_root = os.path.abspath(os.path.normpath(candidate))
                        break
                except OSError:
                    continue
            if not content_root:
                raise RuntimeError(
                    u"无法访问蓝图库：{0}".format(self.candidates[0]))

            library_root = os.path.join(content_root, BLUEPRINT_LIBRARY_RELATIVE)
            if not os.path.isdir(library_root):
                raise RuntimeError(u"没有找到蓝图目录：{0}".format(library_root))

            categories = []
            category_names = sorted(
                (name for name in os.listdir(library_root)
                 if os.path.isdir(os.path.join(library_root, name))),
                key=str.lower,
            )
            for category_name in category_names:
                if self.cancelled:
                    return
                category_folder = os.path.join(library_root, category_name)
                plan = ue_asset_service.build_folder_import_plan(
                    category_folder, content_root, self.project_content_dir)
                assets = []
                # 卡片区只显示分类根目录中的资源，与 ExtContentBrowser 选中该目录时
                # 的资产视图一致。build_folder_import_plan 仍会递归收集整个分类，
                # 因而 EditSet/Input/Joystick 等子目录虽然不被摊平成当前卡片，加载时
                # 仍会随分类一起复制，蓝图引用不会缺失。
                for filename in sorted(os.listdir(category_folder), key=str.lower):
                    if self.cancelled:
                        return
                    source_file = os.path.abspath(os.path.join(category_folder, filename))
                    if (not os.path.isfile(source_file)
                            or os.path.splitext(filename)[1].lower() != ".uasset"):
                        continue
                    relative = os.path.relpath(source_file, content_root)
                    object_path = ue_asset_service.object_path_for_source_file(
                        source_file, content_root)
                    try:
                        modified = int(os.path.getmtime(source_file))
                    except OSError:
                        modified = 0
                    thumbnail, no_thumbnail = _thumbnail_paths(source_file)
                    assets.append({
                        "name": os.path.splitext(filename)[0],
                        "source_file": source_file,
                        "relative": _forward(relative),
                        "object_path": object_path,
                        "modified": modified,
                        "thumbnail": thumbnail,
                        "no_thumbnail": no_thumbnail,
                    })
                assets.sort(key=lambda value: (
                    value["relative"].lower(), value["name"].lower()))
                categories.append({
                    "name": category_name,
                    "folder": category_folder,
                    "content_root": content_root,
                    "plan": plan,
                    "assets": assets,
                })

            self.signals.loaded.emit(self.generation, {
                "content_root": content_root,
                "library_root": library_root,
                "categories": categories,
            })
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))


class BlueprintToolsUI(QtWidgets.QWidget):
    """与资产页一致的蓝图分类和资产卡片浏览器。"""

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace(
        "\\", "/").replace("sources", "")

    def __init__(self, parent=None):
        super(BlueprintToolsUI, self).__init__(parent)
        self.isList = False
        self._scan_generation = 0
        self._scan_task = None
        self._library_payload = {}
        self._categories = {}
        self._copy_thread = None
        self._copy_worker = None
        self._copy_category = ""
        self._backup_thread = None
        self._backup_worker = None
        self._replacement = None
        self._thumbnail_generation = 0
        self._thumbnail_queue = []
        self._thumbnail_bridge_error_reported = False
        self._fallback_icon = self._ensureFallbackIcon()
        self._buildUI()
        QtCore.QTimer.singleShot(0, self.refreshLibrary)

    # ------------------------------------------------------------------ UI
    def _buildUI(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(3)
        category_label = QtWidgets.QLabel(u"蓝图分类")
        category_label.setStyleSheet(
            "font-weight:bold; color:#d7d7d7; padding:4px 5px; background:#252628;")
        left_layout.addWidget(category_label)
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setSpacing(3)
        self.category_list.setMinimumWidth(145)
        left_layout.addWidget(self.category_list, 1)
        splitter.addWidget(left)

        center = QtWidgets.QWidget()
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(2)
        self.display_button = self._toolButton("display_list.png", u"表单显示")
        toolbar.addWidget(self.display_button)
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(64, 200)
        self.size_slider.setValue(120)
        self.size_slider.setMaximumWidth(250)
        self.size_slider.setToolTip(u"缩放蓝图卡片")
        toolbar.addWidget(self.size_slider)
        self.refresh_button = self._toolButton("refresh.png", u"刷新蓝图库")
        toolbar.addWidget(self.refresh_button)
        self.load_button = QtWidgets.QPushButton(u"加载蓝图")
        self.load_button.setMinimumHeight(27)
        self.load_button.setToolTip(u"加载所选卡片所属分类的全部蓝图及依赖包")
        self.load_button.setStyleSheet(
            "QPushButton{background:#256f3a; font-weight:bold; padding:3px 12px;}"
            "QPushButton:hover{background:#2f8b49;}"
            "QPushButton:disabled{background:#454545; color:#888;}")
        toolbar.addWidget(self.load_button)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(u"搜索当前分类的蓝图…")
        self.search_edit.addAction(
            QtGui.QIcon("%s/icon/search.png" % self.scriptsPath),
            QtWidgets.QLineEdit.LeadingPosition)
        toolbar.addWidget(self.search_edit, 1)
        center_layout.addLayout(toolbar)

        self.card_list = myWidget.MainQListWiget()
        self.card_list.setSortingEnabled(False)
        self.card_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.card_list.setListColumns(
            (u"修改日期", u"蓝图名", u"分类", u"服务器文件"),
            (0, 1, 2, 8),
            (135, 220, 130, 520),
            ("datetime", None, None, None),
            ("center", "left", "left", "left"),
        )
        self.blueprint_list_header = myWidget.AssetListHeader(self.card_list)
        self.blueprint_list_header.setClickable(False)
        self.blueprint_list_header.setSortIndicator(-1, False)
        self.blueprint_list_header.hide()
        self.card_list.setListHeader(self.blueprint_list_header)
        center_layout.addWidget(self.blueprint_list_header)
        center_layout.addWidget(self.card_list, 1)
        splitter.addWidget(center)
        splitter.setSizes([175, 760])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

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
        self.blueprint_list_header.setVisible(self.isList)
        self._updateDisplayButton()

        self.category_list.currentItemChanged.connect(self._categoryChanged)
        self.display_button.clicked.connect(self.toggleDisplayMode)
        self.size_slider.valueChanged.connect(self._sizeChanged)
        self.size_slider.sliderReleased.connect(self._rememberSettings)
        self.refresh_button.clicked.connect(self.refreshLibrary)
        self.load_button.clicked.connect(self.loadBlueprintCategory)
        self.search_edit.returnPressed.connect(self._rebuildCards)
        self.search_edit.textChanged.connect(self._searchTextChanged)
        self.card_list.customContextMenuRequested.connect(self._showContextMenu)
        self.card_list.itemSelectionChanged.connect(self._selectionChanged)
        self.card_list.assetDropRequested.connect(self._placeBlueprint)
        self.card_list.assetDragRejected.connect(self._dragRejected)

    def _toolButton(self, icon_name, tooltip):
        button = QtWidgets.QPushButton()
        button.setFixedSize(25, 25)
        button.setIconSize(QtCore.QSize(22, 22))
        button.setIcon(QtGui.QIcon("%s/icon/%s" % (self.scriptsPath, icon_name)))
        button.setToolTip(tooltip)
        button.setStyleSheet(_FLAT)
        return button

    def _ensureFallbackIcon(self):
        cache_root = os.path.join(os.environ.get("TEMP") or os.getcwd(),
                                  "AssetsManagerBlueprintThumbnails")
        # v2 不再绘制中文文字，避免 UE 内嵌 Python/Qt 找不到指定中文字体时
        # 把“蓝图类”渲染成方格。文件名带版本可绕过旧占位图缓存。
        path = os.path.join(cache_root, "Blueprint_Generic_v3.png")
        if os.path.isfile(path):
            return path
        try:
            os.makedirs(cache_root, exist_ok=True)
            pixmap = QtGui.QPixmap(256, 256)
            pixmap.fill(QtGui.QColor(25, 26, 28))
            painter = QtGui.QPainter(pixmap)
            gradient = QtGui.QLinearGradient(0, 0, 0, 256)
            gradient.setColorAt(0.0, QtGui.QColor(45, 47, 51))
            gradient.setColorAt(1.0, QtGui.QColor(26, 27, 29))
            painter.setBrush(gradient)
            painter.setPen(QtGui.QPen(QtGui.QColor(10, 10, 10), 3))
            painter.drawRoundedRect(QtCore.QRectF(7, 7, 242, 242), 7, 7)

            # 简化的 Blueprint 节点图形；即使系统字体不可用，节点和连线仍可辨认。
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtGui.QPen(QtGui.QColor(47, 156, 220), 7,
                                      QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            painter.drawLine(48, 82, 81, 105)
            painter.drawLine(175, 106, 209, 82)
            painter.drawLine(48, 177, 81, 153)
            painter.drawLine(175, 152, 209, 177)
            painter.setPen(QtGui.QPen(QtGui.QColor(11, 42, 64), 3))
            painter.setBrush(QtGui.QColor(31, 119, 176))
            painter.drawRoundedRect(QtCore.QRectF(77, 70, 102, 116), 10, 10)
            painter.setPen(QtGui.QPen(QtGui.QColor(130, 211, 255), 3))
            painter.setBrush(QtGui.QColor(24, 71, 101))
            for center in ((43, 78), (213, 78), (43, 181), (213, 181)):
                painter.drawEllipse(QtCore.QPointF(*center), 11, 11)

            # 内部只画几何逻辑连线，不使用任何文字字形，从根本上规避方格乱码。
            painter.setPen(QtGui.QPen(QtGui.QColor(225, 241, 251), 4,
                                      QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            painter.drawLine(101, 108, 151, 108)
            painter.drawLine(101, 108, 101, 147)
            painter.drawLine(101, 147, 151, 147)
            painter.setBrush(QtGui.QColor(225, 241, 251))
            for center in ((96, 108), (156, 108), (96, 147), (156, 147)):
                painter.drawEllipse(QtCore.QPointF(*center), 6, 6)
            painter.end()
            if pixmap.save(path, "PNG"):
                return path
        except Exception:
            pass
        return "%s/icon/Default.png" % self.scriptsPath

    # ------------------------------------------------------------ 扫描/分类
    def refreshLibrary(self):
        if self._operationIsRunning():
            self.infoMsg("warning", u"正在加载蓝图分类，完成后才能刷新")
            return
        self._rememberSettings()
        self._scan_generation += 1
        generation = self._scan_generation
        if self._scan_task is not None:
            self._scan_task.cancel()
        self.category_list.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.card_list.clear()
        self.infoMsg("info", u"正在后台扫描服务器蓝图库…")
        try:
            project_content = ue_asset_service.project_content_dir()
        except Exception as exc:
            self.category_list.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.infoMsg("error", str(exc))
            return
        task = _LibraryScanTask(
            generation, BLUEPRINT_CONTENT_CANDIDATES, project_content)
        task.signals.loaded.connect(self._scanFinished)
        task.signals.failed.connect(self._scanFailed)
        self._scan_task = task
        _SCAN_POOL.start(task)

    def _scanFinished(self, generation, payload):
        if generation != self._scan_generation:
            return
        self._scan_task = None
        self._library_payload = payload or {}
        categories = self._library_payload.get("categories") or []
        self._categories = {value["name"]: value for value in categories}
        self.category_list.blockSignals(True)
        self.category_list.clear()
        selected_row = 0
        for row, category in enumerate(categories):
            item = QtWidgets.QListWidgetItem(category["name"])
            item.setData(QtCore.Qt.UserRole, category["name"])
            item.setToolTip(category["folder"])
            item.setIcon(QtGui.QIcon("%s/icon/folder.svg" % self.scriptsPath))
            self.category_list.addItem(item)
            if category["name"] == self._preferred_category:
                selected_row = row
        self.category_list.blockSignals(False)
        self.category_list.setEnabled(True)
        self.refresh_button.setEnabled(True)
        if categories:
            self.category_list.setCurrentRow(selected_row)
        else:
            self.card_list.clear()
            self.infoMsg("warning", u"蓝图目录中没有分类文件夹")

    def _scanFailed(self, generation, error):
        if generation != self._scan_generation:
            return
        self._scan_task = None
        self.category_list.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.category_list.clear()
        self.card_list.clear()
        self.infoMsg("error", error)

    def _categoryChanged(self, current, previous=None):
        del previous
        if current is None:
            self.card_list.clear()
            return
        self._preferred_category = str(current.data(QtCore.Qt.UserRole) or current.text())
        self._rememberSettings()
        self._rebuildCards()

    def _currentCategory(self):
        item = self.category_list.currentItem()
        if item is None:
            return ""
        return str(item.data(QtCore.Qt.UserRole) or item.text())

    def _rebuildCards(self):
        category_name = self._currentCategory()
        category = self._categories.get(category_name)
        self.card_list.clear()
        self.blueprint_list_header.setVisible(self.isList)
        if not category:
            return
        keyword = self.search_edit.text().strip().lower()
        rows = []
        visible_assets = []
        for asset in category.get("assets") or []:
            relative_parent = os.path.dirname(os.path.relpath(
                asset["source_file"], category["folder"]))
            detail = category_name if relative_parent in ("", ".") else relative_parent
            if keyword and keyword not in asset["name"].lower() and keyword not in detail.lower():
                continue
            icon_path = asset["thumbnail"] if os.path.isfile(asset["thumbnail"]) else self._fallback_icon
            rows.append((
                asset["modified"], asset["name"], detail,
                "", "", "", "", icon_path,
                asset["source_file"], category_name, asset["object_path"],
            ))
            visible_assets.append(asset)

        self.card_list.setItems(rows)
        self.card_list.setIsList(self.isList)
        self.card_list.setItemSize(self.size_slider.value())
        self.card_list.addItems("")
        self.card_list.setMode()
        self._applyCategoryState(category_name)
        self._queueThumbnails(visible_assets)
        plan = category.get("plan") or {}
        self.infoMsg("info", u"{0}：{1} 个蓝图资源；{2}".format(
            category_name, len(rows), plan.get("message") or u"等待加载"))

    def _searchTextChanged(self, text):
        if not text:
            self._rebuildCards()

    # --------------------------------------------------------------- 卡片状态
    def _itemsForCategory(self, category_name):
        items = []
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            try:
                if str(item.itemData()[9]) == str(category_name):
                    items.append(item)
            except (IndexError, TypeError, RuntimeError):
                pass
        return items

    def _applyCategoryState(self, category_name):
        category = self._categories.get(category_name) or {}
        plan = category.get("plan") or {}
        state = plan.get("state") or "missing"
        message = plan.get("message") or u"等待加载整个分类"
        for item in self._itemsForCategory(category_name):
            item.setUEState(state, message, plan)
            object_path = item.itemData()[10] if state == "ready" else ""
            item.setUEMainObjectPath(object_path)
        self._selectionChanged()

    def _setCategoryProgress(self, category_name, percent, message):
        category = self._categories.get(category_name) or {}
        plan = category.get("plan") or {}
        plan["state"] = "importing"
        plan["message"] = message
        for item in self._itemsForCategory(category_name):
            item.setUEProgress(percent, message)

    def _selectionChanged(self):
        self.load_button.setEnabled(
            self.card_list.currentItem() is not None
            and not self._operationIsRunning())

    def _operationIsRunning(self):
        return bool(
            (self._copy_thread is not None and self._copy_thread.isRunning())
            or (self._backup_thread is not None and self._backup_thread.isRunning()))

    def _setOperationControls(self, enabled):
        self.category_list.setEnabled(bool(enabled))
        self.refresh_button.setEnabled(bool(enabled))
        if enabled:
            self._selectionChanged()
        else:
            self.load_button.setEnabled(False)

    # ------------------------------------------------------------- 缩略图缓存
    def _queueThumbnails(self, assets):
        self._thumbnail_generation += 1
        generation = self._thumbnail_generation
        self._thumbnail_queue = [
            value for value in assets
            if not os.path.isfile(value["thumbnail"])
            and not os.path.isfile(value["no_thumbnail"])
        ]
        if self._thumbnail_queue:
            QtCore.QTimer.singleShot(0, lambda: self._exportNextThumbnail(generation))

    def _exportNextThumbnail(self, generation):
        if generation != self._thumbnail_generation or not self._thumbnail_queue:
            return
        asset = self._thumbnail_queue.pop(0)
        success, error = ue_asset_service.export_external_asset_thumbnail(
            asset["source_file"], asset["thumbnail"])
        if success and os.path.isfile(asset["thumbnail"]):
            self._updateCardThumbnail(asset["source_file"], asset["thumbnail"])
        elif (u"没有保存嵌入缩略图" in error or u"缩略图表为空" in error
              or u"没有可读取" in error or u"数据为空" in error):
            try:
                os.makedirs(os.path.dirname(asset["no_thumbnail"]), exist_ok=True)
                with open(asset["no_thumbnail"], "w", encoding="utf-8") as stream:
                    stream.write("no embedded thumbnail\n")
            except OSError:
                pass
        elif (u"低于 1.2.0" in error or u"未启用 CGToolsAssetBridge" in error):
            self._thumbnail_queue = []
            if not self._thumbnail_bridge_error_reported:
                self._thumbnail_bridge_error_reported = True
                self.infoMsg("warning", error + u"；当前暂用通用蓝图图标")
            return
        QtCore.QTimer.singleShot(8, lambda: self._exportNextThumbnail(generation))

    def _updateCardThumbnail(self, source_file, thumbnail):
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            try:
                data = list(item.itemData())
                if os.path.normcase(data[8]) != os.path.normcase(source_file):
                    continue
                data[7] = thumbnail
                item.setItemData(tuple(data))
                item.update()
                item.requestThumbnailLoad()
                break
            except (IndexError, TypeError, RuntimeError):
                continue

    # ------------------------------------------------------------- 整分类加载
    def _showContextMenu(self, point):
        item = self.card_list.itemAt(point)
        if item is None:
            return
        self.card_list.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        add_open_source_folder_action(menu, os.path.dirname(str(item.itemData()[8])))
        menu.addSeparator()
        load_action = QtGui.QAction(u"加载蓝图", self)
        available = self._scan_task is None and not self._operationIsRunning()
        load_action.setEnabled(available)
        load_action.setToolTip(u"加载该卡片所属分类的全部蓝图文件")
        locate_action = QtGui.QAction(u"在内容浏览器中定位", self)
        open_action = QtGui.QAction(u"打开资源", self)
        open_action.setToolTip(u"在 UE 中打开所选资源的蓝图编辑器")
        menu.setToolTipsVisible(True)
        menu.addAction(load_action)
        menu.addSeparator()
        menu.addAction(locate_action)
        menu.addAction(open_action)
        ready = available and item.ueState() == "ready" and bool(item.ueMainObjectPath())
        locate_action.setEnabled(ready)
        open_action.setEnabled(ready)
        load_action.triggered.connect(
            lambda checked=False, selected=item: self.loadBlueprintCategory(selected))
        locate_action.triggered.connect(
            lambda checked=False, selected=item: self.locateBlueprint(selected))
        open_action.triggered.connect(
            lambda checked=False, selected=item: self.openBlueprint(selected))
        menu.exec_(self.card_list.viewport().mapToGlobal(point))

    def loadBlueprintCategory(self, item=None):
        if isinstance(item, bool):
            item = None
        item = item or self.card_list.currentItem()
        if item is None:
            self.infoMsg("warning", u"请先选择一张蓝图卡片")
            return
        if self._operationIsRunning():
            self.infoMsg("warning", u"已有蓝图分类正在加载，请等待完成")
            return
        category_name = str(item.itemData()[9])
        category = self._categories.get(category_name) or {}
        plan = category.get("plan") or {}
        if not plan.get("files"):
            self.infoMsg("warning", plan.get("message") or u"该分类中没有 Unreal 包文件")
            return
        if plan.get("state") == "conflict":
            if self._confirmCategoryReplacement(category_name, plan):
                self._startCategoryReplacement(category_name, plan)
            return
        if plan.get("state") == "ready":
            self._registerCategoryPlan(category_name, plan)
            return

        self._startCategoryCopy(
            category_name, plan, u"准备加载整个分类：{0}".format(category_name))

    def _validatedReplacementPaths(self, plan):
        target_root = os.path.abspath(os.path.normpath(str(plan.get("target_root") or "")))
        target_folder = os.path.abspath(os.path.normpath(str(
            plan.get("target_folder") or "")))
        package_path = _forward(plan.get("package_path")).rstrip("/")
        try:
            inside_project = (
                target_root
                and target_folder != target_root
                and os.path.commonpath((target_root, target_folder)) == target_root)
        except ValueError:
            inside_project = False
        if not inside_project:
            raise RuntimeError(u"拒绝替换：分类目标不在当前工程 Content 内")
        if not package_path.lower().startswith("/game/assets/blueprints/"):
            raise RuntimeError(u"拒绝替换不安全的包路径：{0}".format(package_path))
        return target_folder, package_path

    def _confirmCategoryReplacement(self, category_name, plan):
        try:
            target_folder, package_path = self._validatedReplacementPaths(plan)
        except Exception as exc:
            self.infoMsg("error", str(exc))
            return False

        conflicts = list(plan.get("different_files") or [])
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(u"替换工程中的蓝图分类")
        box.setText(u"工程中已经存在不同版本的【{0}】。".format(category_name))
        box.setInformativeText(
            u"继续后将先备份当前分类，再强制删除整个包目录，然后从服务器重新加载。\n\n"
            u"包目录：{0}\n冲突文件：{1} 个\n\n"
            u"UE 会关闭这些资产的编辑器，并且可能清空撤销历史；引用这些蓝图的资源也可能暂时失效。"
            .format(package_path, len(conflicts)))
        if conflicts:
            box.setDetailedText(u"将被替换的同名文件：\n" + u"\n".join(conflicts))
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        box.setEscapeButton(QtWidgets.QMessageBox.Cancel)
        yes_button = box.button(QtWidgets.QMessageBox.Yes)
        if yes_button is not None:
            yes_button.setText(u"备份、删除并重新加载")
        cancel_button = box.button(QtWidgets.QMessageBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText(u"取消")
        box.setToolTip(target_folder)
        return box.exec() == QtWidgets.QMessageBox.Yes

    def _startCategoryReplacement(self, category_name, plan):
        try:
            target_folder, package_path = self._validatedReplacementPaths(plan)
            if unreal is None:
                raise RuntimeError(u"当前不在 Unreal Editor 中")

            # 先保存该目录内的脏包，让备份包含用户在编辑器里尚未落盘的修改。
            if unreal.EditorAssetLibrary.does_directory_exist(package_path):
                if not unreal.EditorAssetLibrary.save_directory(package_path, True, True):
                    raise RuntimeError(u"无法保存工程中的原蓝图，已取消替换")

            saved_root = os.path.abspath(os.path.normpath(str(
                unreal.Paths.convert_relative_path_to_full(
                    unreal.Paths.project_saved_dir()))))
            safe_name = u"".join(
                u"_" if char in u'<>:"/\\|?*' else char
                for char in str(category_name)) or u"BlueprintCategory"
            backup_name = u"{0}_{1}_{2}".format(
                time.strftime("%Y%m%d_%H%M%S"), safe_name, uuid.uuid4().hex[:8])
            backup_folder = os.path.join(
                saved_root, "AssetsManagerForUE", "BlueprintBackups", backup_name)
            self._replacement = {
                "category_name": category_name,
                "plan": plan,
                "target_folder": target_folder,
                "package_path": package_path,
                "backup_folder": backup_folder,
            }
        except Exception as exc:
            self._replacement = None
            self._applyCategoryState(category_name)
            self.infoMsg("error", u"准备替换蓝图失败：{0}".format(exc))
            return

        self._setCategoryProgress(
            category_name, 0, u"正在备份工程中的原蓝图…")
        self._setOperationControls(False)
        thread = QtCore.QThread()
        worker = ue_asset_service.FolderBackupWorker(target_folder, backup_folder)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._backupProgress)
        worker.finished.connect(self._backupFinished)
        worker.failed.connect(self._backupFailed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._backupThreadFinished)
        self._backup_thread = thread
        self._backup_worker = worker
        thread.start()

    def _backupProgress(self, percent, relative_name):
        replacement = self._replacement or {}
        category_name = replacement.get("category_name") or ""
        if not category_name:
            return
        message = u"正在备份原蓝图 {0}%：{1}".format(percent, relative_name)
        self._setCategoryProgress(category_name, percent, message)
        self.infoMsg("info", message)

    def _backupFinished(self, result):
        replacement = self._replacement or {}
        category_name = replacement.get("category_name") or ""
        plan = replacement.get("plan") or {}
        package_path = replacement.get("package_path") or ""
        target_folder = replacement.get("target_folder") or ""
        backup_folder = (result or {}).get("backup_folder") or replacement.get(
            "backup_folder") or ""
        if not category_name or not package_path:
            return

        try:
            self._setCategoryProgress(
                category_name, 100, u"备份完成，正在通过 UE 删除原蓝图…")
            deleted = True
            if unreal.EditorAssetLibrary.does_directory_exist(package_path):
                deleted = bool(unreal.EditorAssetLibrary.delete_directory(package_path))

            try:
                remaining_assets = list(unreal.EditorAssetLibrary.list_assets(
                    package_path, True, False))
            except Exception:
                remaining_assets = []
            remaining_package_files = []
            if os.path.isdir(target_folder):
                for root, _dirs, names in os.walk(target_folder):
                    for name in names:
                        if os.path.splitext(name)[1].lower() in ue_asset_service.PACKAGE_EXTENSIONS:
                            remaining_package_files.append(os.path.join(root, name))

            if remaining_assets or remaining_package_files:
                raise RuntimeError(
                    u"UE 未能完整删除原分类（注册资产 {0} 个，残留包文件 {1} 个）"
                    .format(len(remaining_assets), len(remaining_package_files)))
            if not deleted:
                # DeleteDirectory 可能只因空目录未能移除而返回 False；资产和包文件
                # 都已清空时可以安全继续，后续复制会重新创建目录。
                try:
                    unreal.log_warning(
                        u"蓝图资产已删除，但 UE 没有移除空目录：{0}".format(package_path))
                except Exception:
                    pass

            plan = ue_asset_service.query_filesystem_state(plan)
            if plan.get("state") not in ("missing", "partial") or plan.get(
                    "different_files"):
                raise RuntimeError(u"删除后仍检测到同名目标文件，已停止重新加载")
            plan["replacement_backup_path"] = _forward(backup_folder)
            category = self._categories.get(category_name)
            if category is not None:
                category["plan"] = plan
            self._replacement = None
            self._startCategoryCopy(
                category_name, plan, u"原蓝图已删除，正在重新加载服务器分类…")
        except Exception as exc:
            plan["state"] = "conflict"
            plan["message"] = u"删除原蓝图失败：{0}；备份位于 {1}".format(
                exc, _forward(backup_folder))
            category = self._categories.get(category_name)
            if category is not None:
                category["plan"] = plan
            self._replacement = None
            self._applyCategoryState(category_name)
            self.infoMsg("error", plan["message"])
            self._setOperationControls(not self._operationIsRunning())

    def _backupFailed(self, message):
        replacement = self._replacement or {}
        category_name = replacement.get("category_name") or ""
        plan = replacement.get("plan") or {}
        backup_folder = replacement.get("backup_folder") or ""
        plan["state"] = "conflict"
        plan["message"] = u"备份原蓝图失败，工程资产没有删除：{0}".format(message)
        if backup_folder:
            plan["incomplete_backup_path"] = _forward(backup_folder)
        category = self._categories.get(category_name)
        if category is not None:
            category["plan"] = plan
        self._replacement = None
        self._applyCategoryState(category_name)
        self.infoMsg("error", plan["message"])

    def _backupThreadFinished(self):
        self._backup_thread = None
        self._backup_worker = None
        # 正常情况下 _backupFinished 会先启动复制；即使 Qt 把 thread.finished
        # 更早派发，也要在替换上下文处理完之前保持界面锁定。
        if self._replacement is None and not self._operationIsRunning():
            self._setOperationControls(True)

    def _startCategoryCopy(self, category_name, plan, message):
        self._copy_category = category_name
        self._setCategoryProgress(category_name, 0, message)
        self._setOperationControls(False)
        thread = QtCore.QThread()
        worker = ue_asset_service.AssetCopyWorker(plan)
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
        message = u"正在加载整个分类 {0}%：{1}".format(percent, relative_name)
        self._setCategoryProgress(self._copy_category, percent, message)
        self.infoMsg("info", message)

    def _copyFinished(self, plan):
        self._registerCategoryPlan(self._copy_category, plan)

    def _registerCategoryPlan(self, category_name, plan):
        try:
            self._setCategoryProgress(category_name, 100, u"正在刷新 UE Asset Registry…")
            plan = ue_asset_service.refresh_asset_registry(
                plan, require_placeable=False)
        except Exception as exc:
            plan["state"] = "error"
            plan["message"] = u"UE 注册蓝图失败：{0}".format(exc)
        category = self._categories.get(category_name)
        if category is not None:
            category["plan"] = plan
        self._applyCategoryState(category_name)
        if plan.get("state") == "ready":
            backup_path = plan.get("replacement_backup_path") or ""
            suffix = u"；原版本备份：{0}".format(backup_path) if backup_path else ""
            self.infoMsg("info", u"{0}：整个分类加载完成{1}".format(
                category_name, suffix))
        else:
            self.infoMsg("error", plan.get("message") or u"蓝图分类加载失败")

    def _copyFailed(self, message):
        category = self._categories.get(self._copy_category) or {}
        plan = category.get("plan") or {}
        plan["state"] = "conflict" if (u"同名不同" in message or u"目标文件" in message) else "error"
        backup_path = plan.get("replacement_backup_path") or ""
        plan["message"] = (u"{0}；可从备份恢复：{1}".format(message, backup_path)
                           if backup_path else message)
        self._applyCategoryState(self._copy_category)
        self.infoMsg("error", plan["message"])

    def _copyThreadFinished(self):
        self._copy_thread = None
        self._copy_worker = None
        self._copy_category = ""
        if not self._operationIsRunning():
            self._setOperationControls(True)

    # -------------------------------------------------------------- 使用资源
    def locateBlueprint(self, item=None):
        item = item or self.card_list.currentItem()
        object_path = item.ueMainObjectPath() if item is not None else ""
        if not object_path or not ue_asset_service.sync_to_content_browser(object_path):
            self.infoMsg("warning", u"该蓝图尚未加载，或内容浏览器无法定位它")

    def openBlueprint(self, item=None):
        item = item or self.card_list.currentItem()
        object_path = item.ueMainObjectPath() if item is not None else ""
        if not object_path or unreal is None:
            self.infoMsg("warning", u"该蓝图尚未加载")
            return
        success, error = ue_asset_service.open_asset_editor(object_path)
        if success:
            self.infoMsg("info", u"已在 UE 中打开蓝图编辑器：{0}".format(object_path))
        else:
            self.infoMsg("error", error)
            QtWidgets.QMessageBox.warning(self, u"打开蓝图失败", error)

    def _placeBlueprint(self, payload):
        object_path = (payload or {}).get("object_path", "")
        position = None
        if "screen_x" in (payload or {}) and "screen_y" in (payload or {}):
            position = (payload["screen_x"], payload["screen_y"])
        success, error = ue_asset_service.place_asset_at_cursor(
            object_path, screen_position=position)
        if success:
            self.infoMsg("info", u"已放入关卡：{0}".format(object_path))
        else:
            self.infoMsg("warning", error or u"该蓝图不能放入当前关卡")

    def _dragRejected(self, text):
        text = str(text).replace(u"该资产", u"该蓝图资源").replace(
            u"加载资产", u"加载蓝图")
        self.infoMsg("warning", text)

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
        settings = QtCore.QSettings("AssetsManagerUE", "BlueprintLibrary")
        return (settings.value("thumbSize"), settings.value("category"),
                settings.value("isList"))

    def _rememberSettings(self):
        if not hasattr(self, "size_slider"):
            return
        settings = QtCore.QSettings("AssetsManagerUE", "BlueprintLibrary")
        settings.setValue("thumbSize", self.size_slider.value())
        settings.setValue("category", self._currentCategory())
        settings.setValue("isList", self.isList)

    def infoMsg(self, icon, text):
        messageBox.show_msg(self.message_icon, icon, self.message_label, str(text))

    def shutdownThreads(self):
        self._scan_generation += 1
        self._thumbnail_generation += 1
        self._thumbnail_queue = []
        if self._scan_task is not None:
            self._scan_task.cancel()
            self._scan_task = None
        for worker, thread in (
                (self._backup_worker, self._backup_thread),
                (self._copy_worker, self._copy_thread)):
            if worker is not None:
                worker.cancel()
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(1000)
        self._replacement = None
        self._backup_worker = None
        self._backup_thread = None
        self._copy_worker = None
        self._copy_thread = None
