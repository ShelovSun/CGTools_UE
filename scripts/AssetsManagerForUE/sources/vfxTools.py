#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""服务器 VFX 资产浏览、依赖闭包迁移与关卡拖放页。"""

from __future__ import absolute_import

import hashlib
import os

try:
    import unreal
except ImportError:
    unreal = None

from PySide6 import QtCore, QtGui, QtWidgets

from ..utils import messageBox, myWidget
from . import ue_asset_service


VFX_CONTENT_CANDIDATES = (
    r"Y:\MCCTools\src\UE574\VFX\Content",
    r"\\fznas.diandian.info\AC\MCCTools\src\UE574\VFX\Content",
)
VFX_LIBRARY_RELATIVE = "VFX"
VFX_CLASS_LABELS = {
    "NiagaraSystem": u"Niagara系统",
    "ParticleSystem": u"Cascade粒子系统（已弃用）",
}
_FLAT = "border-style: flat; background: transparent;"
_SCAN_POOL = QtCore.QThreadPool()
_SCAN_POOL.setMaxThreadCount(1)


def _forward(path):
    return str(path or "").replace("\\", "/")


def _thumbnail_paths(source_file):
    try:
        stat = os.stat(source_file)
        fingerprint = u"{0}|{1}|{2}".format(
            os.path.normcase(os.path.abspath(source_file)),
            int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        fingerprint = os.path.normcase(os.path.abspath(source_file))
    digest = hashlib.sha1(fingerprint.encode("utf-8", "surrogatepass")).hexdigest()
    root = os.path.join(os.environ.get("TEMP") or os.getcwd(),
                        "AssetsManagerVfxThumbnails")
    png = os.path.join(root, digest + ".png")
    return png, png + ".no_thumbnail"


class _ScanSignals(QtCore.QObject):
    loaded = QtCore.Signal(int, object)
    failed = QtCore.Signal(int, str)


class _LibraryScanTask(QtCore.QRunnable):
    """后台读取目录和轻量文件状态；不在子线程调用任何 unreal API。"""

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
                raise RuntimeError(u"无法访问特效库：{0}".format(self.candidates[0]))

            library_root = os.path.join(content_root, VFX_LIBRARY_RELATIVE)
            if not os.path.isdir(library_root):
                raise RuntimeError(u"没有找到特效目录：{0}".format(library_root))

            categories = []
            category_names = sorted(
                (name for name in os.listdir(library_root)
                 if os.path.isdir(os.path.join(library_root, name))),
                key=str.lower)
            for category_name in category_names:
                if self.cancelled:
                    return
                category_folder = os.path.join(library_root, category_name)
                assets = []
                # 与内容浏览器选中文件夹一致：卡片只列当前分类根部的 uasset；
                # Materials/Textures 等子目录不摊平成卡片，但依赖迁移会递归收集它们。
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
                    plan = ue_asset_service.build_single_package_import_plan(
                        source_file, content_root, self.project_content_dir)
                    assets.append({
                        "name": os.path.splitext(filename)[0],
                        "source_file": source_file,
                        "relative": _forward(relative),
                        "object_path": object_path,
                        "modified": modified,
                        "thumbnail": thumbnail,
                        "no_thumbnail": no_thumbnail,
                        "plan": plan,
                    })
                categories.append({
                    "name": category_name,
                    "folder": category_folder,
                    "content_root": content_root,
                    "assets": assets,
                })

            self.signals.loaded.emit(self.generation, {
                "content_root": content_root,
                "library_root": library_root,
                "categories": categories,
            })
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))


class VfxToolsUI(QtWidgets.QWidget):
    """与资产、蓝图页一致的服务器特效卡片浏览器。"""

    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace(
        "\\", "/").replace("sources", "")

    def __init__(self, parent=None):
        super(VfxToolsUI, self).__init__(parent)
        self.isList = False
        self._scan_generation = 0
        self._scan_task = None
        self._library_payload = {}
        self._categories = {}
        self._assets_by_source = {}
        self._copy_thread = None
        self._copy_worker = None
        self._copy_source = ""
        self._thumbnail_generation = 0
        self._thumbnail_queue = []
        self._thumbnail_bridge_error_reported = False
        self._fallback_icon = "%s/icon/Default.png" % self.scriptsPath
        self._buildUI()
        QtCore.QTimer.singleShot(0, self.refreshLibrary)

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
        category_label = QtWidgets.QLabel(u"特效分类")
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
        self.size_slider.setToolTip(u"缩放特效卡片")
        toolbar.addWidget(self.size_slider)
        self.refresh_button = self._toolButton("refresh.png", u"刷新特效库")
        toolbar.addWidget(self.refresh_button)
        self.load_button = QtWidgets.QPushButton(u"加载特效")
        self.load_button.setMinimumHeight(27)
        self.load_button.setToolTip(u"迁移所选特效及其全部材质、贴图和其他包依赖")
        self.load_button.setStyleSheet(
            "QPushButton{background:#256f3a; font-weight:bold; padding:3px 12px;}"
            "QPushButton:hover{background:#2f8b49;}"
            "QPushButton:disabled{background:#454545; color:#888;}")
        toolbar.addWidget(self.load_button)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(u"搜索当前分类的特效…")
        self.search_edit.addAction(
            QtGui.QIcon("%s/icon/search.png" % self.scriptsPath),
            QtWidgets.QLineEdit.LeadingPosition)
        toolbar.addWidget(self.search_edit, 1)
        center_layout.addLayout(toolbar)

        self.card_list = myWidget.MainQListWiget()
        self.card_list.setSortingEnabled(False)
        self.card_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.card_list.setListColumns(
            (u"修改日期", u"特效名", u"类型", u"服务器文件"),
            (0, 1, 2, 8),
            (135, 220, 190, 520),
            ("datetime", None, None, None),
            ("center", "left", "left", "left"))
        self.vfx_list_header = myWidget.AssetListHeader(self.card_list)
        self.vfx_list_header.setClickable(False)
        self.vfx_list_header.setSortIndicator(-1, False)
        self.vfx_list_header.hide()
        self.card_list.setListHeader(self.vfx_list_header)
        center_layout.addWidget(self.vfx_list_header)
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
        self.vfx_list_header.setVisible(self.isList)
        self._updateDisplayButton()

        self.category_list.currentItemChanged.connect(self._categoryChanged)
        self.display_button.clicked.connect(self.toggleDisplayMode)
        self.size_slider.valueChanged.connect(self._sizeChanged)
        self.size_slider.sliderReleased.connect(self._rememberSettings)
        self.refresh_button.clicked.connect(self.refreshLibrary)
        self.load_button.clicked.connect(self.loadVfx)
        self.search_edit.returnPressed.connect(self._rebuildCards)
        self.search_edit.textChanged.connect(self._searchTextChanged)
        self.card_list.customContextMenuRequested.connect(self._showContextMenu)
        self.card_list.itemSelectionChanged.connect(self._selectionChanged)
        self.card_list.assetDropRequested.connect(self._placeVfx)
        self.card_list.assetDragRejected.connect(self._dragRejected)

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
            self.infoMsg("warning", u"正在迁移特效，完成后才能刷新")
            return
        self._rememberSettings()
        self._scan_generation += 1
        generation = self._scan_generation
        if self._scan_task is not None:
            self._scan_task.cancel()
        self.category_list.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.card_list.clear()
        self.infoMsg("info", u"正在后台扫描服务器特效库…")
        try:
            project_content = ue_asset_service.project_content_dir()
        except Exception as exc:
            self.category_list.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.infoMsg("error", str(exc))
            return
        task = _LibraryScanTask(
            generation, VFX_CONTENT_CANDIDATES, project_content)
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

        # 文件系统线程只负责快速枚举，真实资产类型必须由 UE Asset Registry
        # 在主线程批量读取。只保留可作为完整特效使用的 NiagaraSystem 和旧版
        # Cascade ParticleSystem；材质、贴图、Emitter、模块等仍由依赖迁移带入。
        all_assets = [
            asset
            for category in categories
            for asset in (category.get("assets") or [])
        ]
        filtered_count = 0
        if all_assets:
            self.infoMsg("info", u"正在识别 Niagara 和 Cascade 特效类型…")
            QtWidgets.QApplication.processEvents()
            class_names, error = ue_asset_service.get_external_asset_class_names(
                [asset["source_file"] for asset in all_assets],
                self._library_payload.get("content_root") or "")
            if generation != self._scan_generation:
                return
            if error:
                self._scanFailed(generation, error)
                return
            for asset, class_name in zip(all_assets, class_names):
                short_name = str(class_name).rsplit(".", 1)[-1].rsplit("/", 1)[-1]
                asset["asset_class"] = short_name
                asset["type_label"] = VFX_CLASS_LABELS.get(short_name, "")
            for category in categories:
                original_assets = category.get("assets") or []
                category["assets"] = [
                    asset for asset in original_assets if asset.get("type_label")]
                filtered_count += len(original_assets) - len(category["assets"])
        self._library_payload["filtered_asset_count"] = filtered_count

        self._categories = {value["name"]: value for value in categories}
        self._assets_by_source = {}
        for category in categories:
            for asset in category.get("assets") or []:
                self._assets_by_source[os.path.normcase(asset["source_file"])] = asset
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
            self.infoMsg("warning", u"特效目录中没有分类文件夹")

    def _scanFailed(self, generation, error):
        if generation != self._scan_generation:
            return
        self._scan_task = None
        self.category_list.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.category_list.clear()
        self.card_list.clear()
        self.infoMsg("error", error)

    def _currentCategory(self):
        item = self.category_list.currentItem()
        return str(item.data(QtCore.Qt.UserRole) or item.text()) if item else ""

    def _categoryChanged(self, current, previous=None):
        del previous
        if current is None:
            self.card_list.clear()
            return
        self._preferred_category = str(current.data(QtCore.Qt.UserRole) or current.text())
        self._rememberSettings()
        self._rebuildCards()

    def _rebuildCards(self):
        category_name = self._currentCategory()
        category = self._categories.get(category_name)
        self.card_list.clear()
        self.vfx_list_header.setVisible(self.isList)
        if not category:
            return
        keyword = self.search_edit.text().strip().lower()
        rows = []
        visible_assets = []
        for asset in category.get("assets") or []:
            type_label = asset.get("type_label") or ""
            if (keyword and keyword not in asset["name"].lower()
                    and keyword not in type_label.lower()):
                continue
            icon_path = asset["thumbnail"] if os.path.isfile(asset["thumbnail"]) else self._fallback_icon
            rows.append((
                asset["modified"], asset["name"], type_label,
                "", "", "", "", icon_path,
                asset["source_file"], category_name, asset["object_path"]))
            visible_assets.append(asset)

        self.card_list.setItems(rows)
        self.card_list.setIsList(self.isList)
        self.card_list.setItemSize(self.size_slider.value())
        self.card_list.addItems("")
        self.card_list.setMode()
        for asset in visible_assets:
            self._applyAssetState(asset)
        self._queueThumbnails(visible_assets)
        ready_count = sum(
            1 for asset in visible_assets
            if (asset.get("plan") or {}).get("state") == "ready")
        hidden_count = int(self._library_payload.get("filtered_asset_count") or 0)
        hidden_text = (u"；已隐藏 {0} 个非系统资源".format(hidden_count)
                       if hidden_count else "")
        self.infoMsg("info", u"{0}：{1} 个 Niagara/Cascade 特效；已加载 {2} 个{3}".format(
            category_name, len(rows), ready_count, hidden_text))

    def _searchTextChanged(self, text):
        if not text:
            self._rebuildCards()

    # --------------------------------------------------------------- 卡片状态
    def _assetForItem(self, item):
        if item is None:
            return None
        try:
            return self._assets_by_source.get(os.path.normcase(str(item.itemData()[8])))
        except (IndexError, TypeError, RuntimeError):
            return None

    def _itemForSource(self, source_file):
        source_key = os.path.normcase(str(source_file))
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            try:
                if os.path.normcase(str(item.itemData()[8])) == source_key:
                    return item
            except (IndexError, TypeError, RuntimeError):
                pass
        return None

    def _applyAssetState(self, asset):
        item = self._itemForSource(asset.get("source_file"))
        if item is None:
            return
        plan = asset.get("plan") or {}
        state = plan.get("state") or "missing"
        message = plan.get("message") or u"等待加载特效"
        item.setUEState(state, message, plan)
        item.setUEMainObjectPath(asset.get("object_path") if state == "ready" else "")
        self._selectionChanged()

    def _setAssetProgress(self, asset, percent, message):
        plan = asset.get("plan") or {}
        plan["state"] = "importing"
        plan["message"] = message
        asset["plan"] = plan
        item = self._itemForSource(asset.get("source_file"))
        if item is not None:
            item.setUEProgress(percent, message)

    def _selectionChanged(self):
        self.load_button.setEnabled(
            self.card_list.currentItem() is not None
            and not self._operationIsRunning())

    def _operationIsRunning(self):
        return bool(self._copy_thread is not None and self._copy_thread.isRunning())

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
            and not os.path.isfile(value["no_thumbnail"])]
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
                self.infoMsg("warning", error + u"；当前暂用通用特效图标")
            return
        QtCore.QTimer.singleShot(8, lambda: self._exportNextThumbnail(generation))

    def _updateCardThumbnail(self, source_file, thumbnail):
        item = self._itemForSource(source_file)
        if item is None:
            return
        try:
            data = list(item.itemData())
            data[7] = thumbnail
            item.setItemData(tuple(data))
            item.update()
            item.requestThumbnailLoad()
        except (IndexError, TypeError, RuntimeError):
            pass

    # ------------------------------------------------------------- 依赖迁移
    def _showContextMenu(self, point):
        item = self.card_list.itemAt(point)
        if item is None:
            return
        self.card_list.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        load_action = QtGui.QAction(u"加载特效", self)
        load_action.setToolTip(u"迁移该特效及其引用的材质、贴图和其他资产包")
        locate_action = QtGui.QAction(u"在内容浏览器中定位", self)
        open_action = QtGui.QAction(u"打开资源", self)
        menu.addAction(load_action)
        menu.addSeparator()
        menu.addAction(locate_action)
        menu.addAction(open_action)
        ready = item.ueState() == "ready" and bool(item.ueMainObjectPath())
        locate_action.setEnabled(ready)
        open_action.setEnabled(ready)
        load_action.triggered.connect(
            lambda checked=False, selected=item: self.loadVfx(selected))
        locate_action.triggered.connect(
            lambda checked=False, selected=item: self.locateVfx(selected))
        open_action.triggered.connect(
            lambda checked=False, selected=item: self.openVfx(selected))
        menu.exec_(self.card_list.viewport().mapToGlobal(point))

    def loadVfx(self, item=None):
        if isinstance(item, bool):
            item = None
        item = item or self.card_list.currentItem()
        asset = self._assetForItem(item)
        if asset is None:
            self.infoMsg("warning", u"请先选择一张特效卡片")
            return
        if self._operationIsRunning():
            self.infoMsg("warning", u"已有特效正在迁移，请等待完成")
            return

        content_root = self._library_payload.get("content_root") or ""
        self.infoMsg("info", u"正在解析特效的材质、贴图和包依赖…")
        QtWidgets.QApplication.processEvents()
        plan = ue_asset_service.build_external_dependency_import_plan(
            asset["source_file"], content_root)
        asset["plan"] = plan
        self._applyAssetState(asset)

        missing = plan.get("missing_dependencies") or []
        if missing:
            shown = u"\n".join(str(value) for value in missing[:12])
            suffix = u"\n……" if len(missing) > 12 else ""
            text = u"{0}\n\n缺失依赖：\n{1}{2}".format(
                plan.get("message") or u"特效依赖不完整", shown, suffix)
            QtWidgets.QMessageBox.warning(self, u"无法加载特效", text)
            self.infoMsg("error", plan.get("message"))
            return
        if plan.get("state") == "error" or not plan.get("files"):
            text = plan.get("message") or u"没有解析到可迁移的特效文件"
            QtWidgets.QMessageBox.warning(self, u"无法加载特效", text)
            self.infoMsg("error", text)
            return
        if plan.get("state") == "conflict":
            conflicts = plan.get("different_files") or []
            shown = u"\n".join(str(value) for value in conflicts[:12])
            text = u"工程中已有同名但内容不同的文件，为保护工程，本次不会覆盖。\n\n{0}".format(shown)
            QtWidgets.QMessageBox.warning(self, u"特效迁移冲突", text)
            self.infoMsg("warning", plan.get("message"))
            return
        if plan.get("state") == "ready":
            self._registerPlan(asset, plan)
            return

        package_count = len(plan.get("package_object_paths") or [])
        total_bytes = sum(int(entry.get("size", 0)) for entry in plan.get("files") or [])
        reply = QtWidgets.QMessageBox.question(
            self, u"迁移特效",
            u"将把特效“{0}”及其依赖迁移到当前工程的相同 Content 路径。\n\n"
            u"包数量：{1}\n文件大小：{2:.1f} MB\n\n是否继续？".format(
                asset["name"], package_count, total_bytes / (1024.0 * 1024.0)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes)
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self._startCopy(asset, plan)

    def _startCopy(self, asset, plan):
        self._copy_source = asset["source_file"]
        self._setAssetProgress(asset, 0, u"准备迁移特效及依赖…")
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
        asset = self._assets_by_source.get(os.path.normcase(self._copy_source))
        if asset is None:
            return
        message = u"正在迁移特效 {0}%：{1}".format(percent, relative_name)
        self._setAssetProgress(asset, percent, message)
        self.infoMsg("info", message)

    def _copyFinished(self, plan):
        asset = self._assets_by_source.get(os.path.normcase(self._copy_source))
        if asset is not None:
            self._registerPlan(asset, plan)

    def _registerPlan(self, asset, plan):
        try:
            self._setAssetProgress(asset, 100, u"正在刷新 UE Asset Registry…")
            plan = ue_asset_service.refresh_asset_registry(plan, require_placeable=True)
        except Exception as exc:
            plan["state"] = "error"
            plan["message"] = u"UE 注册特效失败：{0}".format(exc)
        asset["plan"] = plan
        self._applyAssetState(asset)
        if plan.get("state") == "ready":
            object_path = plan.get("main_object_path") or asset.get("object_path") or ""
            if object_path and ue_asset_service.sync_to_content_browser(object_path):
                self.infoMsg(
                    "info", u"{0}：迁移完成，已在内容浏览器中定位，可以拖入关卡".format(
                        asset["name"]))
            else:
                self.infoMsg(
                    "warning", u"{0}：迁移完成，但内容浏览器自动定位失败".format(
                        asset["name"]))
        else:
            QtWidgets.QMessageBox.warning(
                self, u"加载特效失败", plan.get("message") or u"UE 无法注册该特效")
            self.infoMsg("error", plan.get("message") or u"加载特效失败")

    def _copyFailed(self, message):
        asset = self._assets_by_source.get(os.path.normcase(self._copy_source))
        if asset is not None:
            plan = asset.get("plan") or {}
            plan["state"] = "conflict" if u"同名不同" in message else "error"
            plan["message"] = message
            asset["plan"] = plan
            self._applyAssetState(asset)
        QtWidgets.QMessageBox.warning(self, u"特效迁移失败", str(message))
        self.infoMsg("error", message)

    def _copyThreadFinished(self):
        self._copy_thread = None
        self._copy_worker = None
        self._copy_source = ""
        self._setOperationControls(True)

    # -------------------------------------------------------------- 使用资源
    def locateVfx(self, item=None):
        item = item or self.card_list.currentItem()
        object_path = item.ueMainObjectPath() if item is not None else ""
        if not object_path or not ue_asset_service.sync_to_content_browser(object_path):
            self.infoMsg("warning", u"该特效尚未加载，或内容浏览器无法定位它")

    def openVfx(self, item=None):
        item = item or self.card_list.currentItem()
        object_path = item.ueMainObjectPath() if item is not None else ""
        if not object_path or unreal is None:
            self.infoMsg("warning", u"该特效尚未加载")
            return
        try:
            asset = unreal.EditorAssetLibrary.load_asset(object_path)
            if asset is None:
                raise RuntimeError(u"UE 无法加载 {0}".format(object_path))
            unreal.get_editor_subsystem(
                unreal.AssetEditorSubsystem).open_editor_for_asset(asset)
            self.infoMsg("info", u"已打开：{0}".format(object_path))
        except Exception as exc:
            self.infoMsg("error", u"打开特效失败：{0}".format(exc))

    def _placeVfx(self, payload):
        object_path = (payload or {}).get("object_path", "")
        position = None
        if "screen_x" in (payload or {}) and "screen_y" in (payload or {}):
            position = (payload["screen_x"], payload["screen_y"])
        success, error = ue_asset_service.place_asset_at_cursor(
            object_path, screen_position=position)
        if success:
            self.infoMsg("info", u"已放入关卡：{0}".format(object_path))
        else:
            self.infoMsg("warning", error or u"该特效不能放入当前关卡")

    def _dragRejected(self, text):
        text = str(text).replace(u"该资产", u"该特效").replace(
            u"加载资产", u"加载特效")
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
        settings = QtCore.QSettings("AssetsManagerUE", "VfxLibrary")
        return (settings.value("thumbSize"), settings.value("category"),
                settings.value("isList"))

    def _rememberSettings(self):
        if not hasattr(self, "size_slider"):
            return
        settings = QtCore.QSettings("AssetsManagerUE", "VfxLibrary")
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
        if self._copy_worker is not None:
            self._copy_worker.cancel()
        if self._copy_thread is not None and self._copy_thread.isRunning():
            self._copy_thread.quit()
            self._copy_thread.wait(1000)
        self._copy_worker = None
        self._copy_thread = None
