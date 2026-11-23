#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AssetActionWidget —— 资产动作浏览器（置于资产详情的 FBX 预览下方）。

递归列出资产 ``Action`` 目录下的所有 ``.fbx`` 动作文件。点击某动作 -> 发 actionActivated,
由主面板通知 PreviewGLWidget 把该动作的骨骼动画套用到绑定文件上循环播放。

绑定文件位于 ``.../<project>/Assets/<type>/<asset>/FBX/<asset>.fbx``，动作库位于
``.../<project>/Animations/<type>/<asset>/Action``。动作文件一般只含骨骼动画、无网格。
"""

import datetime
import os
import threading

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

__all__ = ["AssetActionWidget"]


_SORT_VALUE_ROLE = int(QtCore.Qt.UserRole) + 1


def _scan_action_files(action_dir, cancelled):
    """Read metadata from scandir's cached entries, off the GUI thread."""
    result = dict(exists=False, files=[], error="")
    if not action_dir:
        return result
    pending = [(action_dir, "")]
    while pending and not cancelled.is_set():
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as entries:
                if not prefix:
                    result['exists'] = True
                for entry in entries:
                    if cancelled.is_set():
                        return result
                    relative = prefix + entry.name
                    if entry.is_dir():
                        if not entry.is_symlink():
                            pending.append((entry.path, relative + "/"))
                    elif entry.name.lower().endswith('.fbx'):
                        try:
                            stat = entry.stat()
                            mtime, size = float(stat.st_mtime), int(stat.st_size)
                        except OSError:
                            mtime = size = None
                        result['files'].append((relative, entry.path.replace('\\','/'), mtime, size))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            if not prefix:
                result['error'] = str(exc)
    result['files'].sort(key=lambda row: row[0].lower())
    return result


class _ActionScanSignals(QtCore.QObject):
    finished = QtCore.Signal(int, int, str, object)


class _ActionScanTask(QtCore.QRunnable):
    def __init__(self, token, generation, directory, cancelled):
        super().__init__()
        self.signals = _ActionScanSignals()
        self.token, self.generation = token, generation
        self.directory, self.cancelled = directory, cancelled

    def run(self):
        try:
            result = _scan_action_files(self.directory, self.cancelled)
        except Exception as exc:
            result = dict(exists=False, files=[], error=str(exc))
        self.signals.finished.emit(self.token, self.generation, self.directory, result)


class _ActionScanner(QtCore.QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        self.pool = QtCore.QThreadPool()
        self.pool.setMaxThreadCount(1)
        self.jobs = {}
        self.serial = 0

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def request(self, generation, directory, cancelled, callback):
        self.serial += 1
        task = _ActionScanTask(self.serial, generation, directory, cancelled)
        self.jobs[self.serial] = task
        task.signals.finished.connect(self._finished)
        task.signals.finished.connect(callback)
        self.pool.start(task)

    @QtCore.Slot(int, int, str, object)
    def _finished(self, token, _generation, _directory, _result):
        self.jobs.pop(token, None)


class AssetActionWidget(QtWidgets.QWidget):
    """资产动作浏览器。

    actionActivated(str): 选中动作时发出其 .fbx 全路径;空字符串表示回到绑定文件静态预览。
    """

    actionActivated = QtCore.Signal(str)
    loadActionRequested = QtCore.Signal(str)
    importActionRequested = QtCore.Signal(str)
    loadActionsRequested = QtCore.Signal(list)
    importActionsRequested = QtCore.Signal(list)

    def __init__(self, parent=None):
        super(AssetActionWidget, self).__init__(parent)
        self._action_dir = ""
        self._load_busy = False
        self._closed = False
        self._generation = 0
        self._cancelled = threading.Event()
        self._loading = False
        self._phase = None
        self._pending_rows = []
        self._build_ui()
        # One single-shot timer: debounce requests, then yield between UI batches.
        self._work_timer = QtCore.QTimer(self)
        self._work_timer.setSingleShot(True)
        self._work_timer.timeout.connect(self._advance_load)
        self.clear()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = QtWidgets.QLabel(u"动作库：")
        title_font = QtGui.QFont(u"Microsoft YaHei UI", 10)
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setFixedHeight(21)
        self._title.setStyleSheet(
            "color:rgb(200,200,200); background:rgb(29,29,29);")
        outer.addWidget(self._title)

        # 搜索框:按动作名过滤列表
        search_wrap = QtWidgets.QWidget(self)
        sl = QtWidgets.QHBoxLayout(search_wrap)
        sl.setContentsMargins(6, 2, 6, 2)
        sl.setSpacing(0)
        self._search = QtWidgets.QLineEdit(search_wrap)
        self._search.setPlaceholderText(u"搜索动作…")
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumHeight(24)
        self._search.setStyleSheet(
            "QLineEdit{background:rgb(45,46,49); border:1px solid rgb(60,61,64);"
            " border-radius:2px; padding:2px 5px; color:rgb(215,215,215);}"
            "QLineEdit:focus{border-color:rgb(70,125,209);}")
        self._search.textChanged.connect(self._apply_filter)
        sl.addWidget(self._search)
        outer.addWidget(search_wrap)

        self._list = QtWidgets.QTreeWidget(self)
        self._list.setStyleSheet(
            "QTreeWidget{background:rgb(35,36,39); border:none; color:rgb(215,215,215);}"
            "QTreeWidget::item{height:18px; padding:0px 3px; border:0px;}"
            "QTreeWidget::item:selected{background:rgb(70,125,209); color:white;}"
            "QTreeWidget::item:hover:!selected{background:rgb(55,58,64);}"
            "QHeaderView::section{height:21px; padding:0px 4px; background:rgb(82,82,82);"
            " color:white; border:0px; border-right:1px solid rgb(55,55,55);}")
        self._list.setIndentation(0)
        self._list.setColumnCount(3)
        self._list.setHeaderLabels([u"名字", u"修改日期", u"大小"])
        self._list.setRootIsDecorated(False)
        self._list.setItemsExpandable(False)
        self._list.setUniformRowHeights(True)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)

        header = self._list.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(1, QtCore.Qt.DescendingOrder)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.resizeSection(0, 200)
        header.resizeSection(1, 145)
        header.resizeSection(2, 75)
        header.sectionClicked.connect(self._on_header_clicked)
        self._sort_column = 1
        self._sort_order = QtCore.Qt.DescendingOrder
        outer.addWidget(self._list, 1)

    # ------------------------------------------------------------------ 对外接口
    def setLoadBusy(self, busy):
        self._load_busy = bool(busy)

    def clear(self):
        """清空动作列表,显示占位提示。"""
        if self._closed:
            return
        self._cancel_pending()
        self._action_dir = ""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._list.blockSignals(True)
        self._list.clear()
        self._add_hint(u"未选择资产")
        self._list.blockSignals(False)
        self._list.setEnabled(True)
        self._title.setText(u"动作库：")

    def _cancel_pending(self):
        self._generation += 1
        self._cancelled.set()
        self._work_timer.stop()
        self._phase = None
        self._pending_rows = []
        self._loading = False

    def shutdown(self):
        if not self._closed:
            self._closed = True
            self._cancel_pending()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def setAsset(self, rig_fbx_path):
        """Select immediately; discover this asset's actions in a bounded worker."""
        if self._closed:
            return
        self._cancel_pending()
        self._cancelled = threading.Event()
        self._title.setText(u"动作库：")
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._list.blockSignals(True)
        self._list.clear()

        action_dir = self._derive_action_dir(rig_fbx_path)
        self._action_dir = action_dir or ""

        # 顶部:回到绑定文件静态预览
        top = QtWidgets.QTreeWidgetItem([u"资产预览", "", ""])
        top.setData(0, QtCore.Qt.UserRole, "")
        self._list.addTopLevelItem(top)
        if not action_dir:
            self._add_hint(u"无 Action 目录")
        else:
            self._add_hint(u"正在读取动作…")
            self._loading = True
            self._phase = 'scan'
            self._work_timer.start(150)
        self._list.setEnabled(not self._loading)
        self._list.blockSignals(False)

    def _advance_load(self):
        if self._closed:
            return
        if self._phase == 'scan':
            self._phase = None
            _ActionScanner.instance().request(self._generation, self._action_dir,
                                             self._cancelled, self._scan_finished)
        elif self._phase == 'populate':
            self._populate_rows()

    @QtCore.Slot(int, int, str, object)
    def _scan_finished(self, _token, generation, directory, result):
        if self._closed or generation != self._generation or directory != self._action_dir:
            return
        self._list.clear()
        top = QtWidgets.QTreeWidgetItem([u"资产预览", "", ""])
        top.setData(0, QtCore.Qt.UserRole, "")
        self._list.addTopLevelItem(top)
        if result.get('error'):
            self._add_hint(u"动作目录读取失败，请重新选择资产重试")
        elif not result['exists']:
            self._add_hint(u"无 Action 目录")
        elif not result['files']:
            self._add_hint(u"该资产无动作 (.fbx)")
        else:
            column = self._sort_column
            def value(row):
                if column == 0:
                    return row[0].lower()
                return row[column+1] if row[column+1] is not None else -1
            self._pending_rows = sorted(result['files'], key=value,
                                        reverse=self._sort_order == QtCore.Qt.DescendingOrder)
            self._row_offset = 0
            self._phase = 'populate'
            self._work_timer.start(1)
            return
        self._finish_loading()

    def _populate_rows(self):
        clock = QtCore.QElapsedTimer()
        clock.start()
        blocked = self._list.blockSignals(True)
        self._list.setUpdatesEnabled(False)
        count = 0
        keyword = self._search.text().strip().lower()
        try:
            while (self._row_offset < len(self._pending_rows) and count < 128
                   and (count == 0 or clock.elapsed() < 4)):
                rel, full, mtime, size = self._pending_rows[self._row_offset]
                item = QtWidgets.QTreeWidgetItem([rel,self._format_mtime(mtime),self._format_size(size)])
                item.setData(0,QtCore.Qt.UserRole,full)
                item.setData(0,_SORT_VALUE_ROLE,rel.lower())
                item.setData(1,_SORT_VALUE_ROLE,mtime if mtime is not None else -1.0)
                item.setData(2,_SORT_VALUE_ROLE,size if size is not None else -1)
                item.setToolTip(0,full)
                self._list.addTopLevelItem(item)
                item.setHidden(bool(keyword) and keyword not in rel.lower())
                self._row_offset += 1
                count += 1
        finally:
            self._list.setUpdatesEnabled(True)
            self._list.blockSignals(blocked)
        if self._row_offset < len(self._pending_rows):
            self._title.setText(u"动作库：正在准备 {0}/{1}…".format(self._row_offset,len(self._pending_rows)))
            self._work_timer.start(1)
        else:
            self._finish_loading()

    def _finish_loading(self):
        self._loading = False
        self._phase = None
        self._pending_rows = []
        self._title.setText(u"动作库：")
        self._list.setEnabled(True)

    # ------------------------------------------------------------------ 内部
    def _derive_action_dir(self, rig_fbx_path):
        """模型留在 Assets；动作统一读取同一项目的 Animations 目录。"""
        if not rig_fbx_path:
            return ""
        path = str(rig_fbx_path).replace("\\", "/")
        fbx_index = path.lower().rfind("/fbx/")
        asset_root = path[:fbx_index] if fbx_index >= 0 else os.path.dirname(path)
        # 只替换资产根上方的 Assets 层，保留项目、类型、资产名及盘符/UNC 前缀。
        parts = asset_root.rsplit("/", 3)
        if len(parts) == 4 and parts[1].lower() == "assets":
            asset_root = "/".join((parts[0], "Animations", parts[2], parts[3]))
        return asset_root + "/Action" if asset_root else ""

    def _scan_actions(self, action_dir):
        """递归收集 .fbx，返回相对路径、全路径、修改时间戳和字节数。"""
        return _scan_action_files(action_dir, threading.Event())['files']

    @staticmethod
    def _format_mtime(mtime):
        """把文件时间戳格式化为本地时间。"""
        if mtime is None:
            return u"—"
        try:
            return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            return u"—"

    @staticmethod
    def _format_size(size):
        """以易读单位显示文件大小；排序仍使用原始字节数。"""
        if size is None:
            return u"—"
        value = float(size)
        units = ("B", "KB", "MB", "GB", "TB")
        unit = units[0]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                break
            value /= 1024.0
        if unit == "B":
            return "%d B" % int(value)
        return "%.1f %s" % (value, unit)

    def _on_header_clicked(self, column):
        """单击表头：首次选择该列升序，再次单击切换升/降序。"""
        if column == self._sort_column:
            self._sort_order = (
                QtCore.Qt.DescendingOrder
                if self._sort_order == QtCore.Qt.AscendingOrder
                else QtCore.Qt.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = QtCore.Qt.AscendingOrder
        self._list.header().setSortIndicator(self._sort_column, self._sort_order)
        self._sort_action_items()

    def _sort_action_items(self):
        """仅排序 FBX 行；“资产预览”和提示行保持原位。"""
        current = self._list.currentItem()
        selected = list(self._list.selectedItems())
        was_blocked = self._list.blockSignals(True)

        action_items = []
        for index in range(self._list.topLevelItemCount() - 1, -1, -1):
            item = self._list.topLevelItem(index)
            if item.data(0, QtCore.Qt.UserRole):
                action_items.append(self._list.takeTopLevelItem(index))

        column = self._sort_column
        action_items.sort(
            key=lambda item: item.data(column, _SORT_VALUE_ROLE),
            reverse=self._sort_order == QtCore.Qt.DescendingOrder,
        )

        # 第 0 行固定是“资产预览”；提示行只在没有动作时出现。
        for offset, item in enumerate(action_items, 1):
            self._list.insertTopLevelItem(offset, item)
        if current is not None:
            self._list.setCurrentItem(current, 0, QtCore.QItemSelectionModel.NoUpdate)
        for item in selected:
            item.setSelected(True)
        # take/insert 后重新应用当前搜索词，避免排序使已过滤条目重新显示。
        self._apply_filter()
        self._list.blockSignals(was_blocked)

    def _apply_filter(self, text=None):
        """按关键字隐藏不匹配的动作项(大小写不敏感子串匹配)。
        顶部"资产预览"始终可见;提示项(无 UserRole)不参与过滤。"""
        kw = (text if text is not None else self._search.text()).strip().lower()
        for i in range(self._list.topLevelItemCount()):
            it = self._list.topLevelItem(i)
            data = it.data(0, QtCore.Qt.UserRole)
            if data is None:
                continue  # 提示项
            if data == "":
                it.setHidden(False)  # 资产预览锚点始终可见
                continue
            hidden = bool(kw) and kw not in it.text(0).lower()
            if hidden:
                it.setSelected(False)
            it.setHidden(hidden)

    def _add_hint(self, text):
        it = QtWidgets.QTreeWidgetItem([text, "", ""])
        it.setFlags(QtCore.Qt.NoItemFlags)
        self._list.addTopLevelItem(it)

    def _on_item_clicked(self, item, _column=0):
        if item is None:
            return
        path = item.data(0, QtCore.Qt.UserRole)
        if path is None:
            return  # 提示项(无 UserRole)
        self.actionActivated.emit(str(path))

    def _show_context_menu(self, point):
        """动作条目右键菜单；“资产预览”和提示行不提供文件操作。"""
        item = self._list.itemAt(point)
        if item is None:
            return
        path = item.data(0, QtCore.Qt.UserRole)
        if not path:
            return

        if item.isSelected():
            self._list.setCurrentItem(item, 0, QtCore.QItemSelectionModel.NoUpdate)
        else:
            self._list.clearSelection()
            self._list.setCurrentItem(item)
            item.setSelected(True)
        paths = self._selected_action_paths()
        packages = [os.path.splitext(path)[0] + ".uasset" for path in paths]

        menu = QtWidgets.QMenu(self._list)
        open_folder_action = menu.addAction(u"打开文件夹")
        open_folder_action.setEnabled(any(os.path.isdir(os.path.dirname(path)) for path in paths))
        load_action = menu.addAction(u"加载动作")
        load_action.setEnabled(not self._load_busy and any(os.path.isfile(path) for path in packages))
        load_action.setToolTip(u"按列表顺序加载选中的 {0} 个同名 UE 动画包".format(len(packages)))
        import_action = menu.addAction(u"导入动作FBX")
        import_action.setEnabled(not self._load_busy and any(os.path.isfile(path) for path in paths))
        import_action.setToolTip(u"按列表顺序导入选中的 {0} 个 FBX".format(len(paths)))
        menu.setToolTipsVisible(True)

        chosen = menu.exec_(self._list.viewport().mapToGlobal(point))
        if chosen == open_folder_action:
            if len(paths) == 1:
                self._open_action_folder(paths[0])
            else:
                # Multiple selected files often share one Action directory.
                # Open each directory once instead of spawning duplicate windows.
                for folder in dict.fromkeys(os.path.dirname(path) for path in paths):
                    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
        elif chosen == load_action and load_action.isEnabled():
            if len(packages) == 1:
                self.loadActionRequested.emit(packages[0])
            else:
                self.loadActionsRequested.emit(packages)
        elif chosen == import_action and import_action.isEnabled():
            if len(paths) == 1:
                self.importActionRequested.emit(paths[0])
            else:
                self.importActionsRequested.emit(paths)

    def _selected_action_paths(self):
        """Snapshot visible selected files in the current displayed sort order."""
        paths = []
        for index in range(self._list.topLevelItemCount()):
            item = self._list.topLevelItem(index)
            path = item.data(0, QtCore.Qt.UserRole)
            if path and item.isSelected() and not item.isHidden():
                paths.append(os.path.normpath(str(path)).replace("\\", "/"))
        return paths

    @staticmethod
    def _open_action_folder(path):
        """用资源管理器打开动作所在目录，并优先选中该 FBX。"""
        path = os.path.normpath(path)
        if os.path.isfile(path):
            try:
                started = QtCore.QProcess.startDetached(
                    "explorer.exe", ["/select,", path])
                # 兼容不同 PySide 版本返回 bool 或 (bool, pid)。
                if isinstance(started, tuple):
                    started = started[0]
                if started:
                    return
            except Exception:
                pass

        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
