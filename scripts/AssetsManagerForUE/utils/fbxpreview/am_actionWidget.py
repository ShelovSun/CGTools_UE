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

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

__all__ = ["AssetActionWidget"]


_SORT_VALUE_ROLE = int(QtCore.Qt.UserRole) + 1


class AssetActionWidget(QtWidgets.QWidget):
    """资产动作浏览器。

    actionActivated(str): 选中动作时发出其 .fbx 全路径;空字符串表示回到绑定文件静态预览。
    """

    actionActivated = QtCore.Signal(str)
    loadActionRequested = QtCore.Signal(str)
    importActionRequested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(AssetActionWidget, self).__init__(parent)
        self._action_dir = ""
        self._load_busy = False
        self._build_ui()
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
            "QTreeWidget::item:hover{background:rgb(55,58,64);}"
            "QHeaderView::section{height:21px; padding:0px 4px; background:rgb(82,82,82);"
            " color:white; border:0px; border-right:1px solid rgb(55,55,55);}")
        self._list.setIndentation(0)
        self._list.setColumnCount(3)
        self._list.setHeaderLabels([u"名字", u"修改日期", u"大小"])
        self._list.setRootIsDecorated(False)
        self._list.setItemsExpandable(False)
        self._list.setUniformRowHeights(True)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)

        header = self._list.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, QtCore.Qt.AscendingOrder)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.sectionClicked.connect(self._on_header_clicked)
        self._sort_column = 0
        self._sort_order = QtCore.Qt.AscendingOrder
        outer.addWidget(self._list, 1)

    # ------------------------------------------------------------------ 对外接口
    def setLoadBusy(self, busy):
        self._load_busy = bool(busy)

    def clear(self):
        """清空动作列表,显示占位提示。"""
        self._action_dir = ""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._list.blockSignals(True)
        self._list.clear()
        self._add_hint(u"未选择资产")
        self._list.blockSignals(False)

    def setAsset(self, rig_fbx_path):
        """根据绑定文件路径填充 Animations 下该资产的 Action 动作列表(递归)。"""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._list.blockSignals(True)
        self._list.clear()

        action_dir = self._derive_action_dir(rig_fbx_path)
        self._action_dir = action_dir or ""

        fbx_files = self._scan_actions(action_dir)
        # 顶部:回到绑定文件静态预览
        top = QtWidgets.QTreeWidgetItem([u"资产预览", "", ""])
        top.setData(0, QtCore.Qt.UserRole, "")
        self._list.addTopLevelItem(top)

        if not action_dir or not os.path.isdir(action_dir):
            self._add_hint(u"无 Action 目录")
        elif not fbx_files:
            self._add_hint(u"该资产无动作 (.fbx)")
        else:
            for rel, full, mtime, size in fbx_files:
                it = QtWidgets.QTreeWidgetItem([
                    rel,
                    self._format_mtime(mtime),
                    self._format_size(size),
                ])
                it.setData(0, QtCore.Qt.UserRole, full)
                it.setData(0, _SORT_VALUE_ROLE, rel.lower())
                it.setData(1, _SORT_VALUE_ROLE, mtime if mtime is not None else -1.0)
                it.setData(2, _SORT_VALUE_ROLE, size if size is not None else -1)
                it.setToolTip(0, full)
                self._list.addTopLevelItem(it)

            self._sort_action_items()

        self._list.blockSignals(False)

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
        if not action_dir or not os.path.isdir(action_dir):
            return []
        out = []
        for cur, _dirs, files in os.walk(action_dir):
            for fn in files:
                if fn.lower().endswith(".fbx"):
                    full = os.path.join(cur, fn).replace("\\", "/")
                    rel = os.path.relpath(full, action_dir).replace("\\", "/")
                    try:
                        stat = os.stat(full)
                        mtime = float(stat.st_mtime)
                        size = int(stat.st_size)
                    except OSError:
                        mtime = None
                        size = None
                    out.append((rel, full, mtime, size))
        out.sort(key=lambda rf: rf[0].lower())
        return out

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
        selected_path = None
        current = self._list.currentItem()
        if current is not None:
            selected_path = current.data(0, QtCore.Qt.UserRole)

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
            if selected_path and item.data(0, QtCore.Qt.UserRole) == selected_path:
                self._list.setCurrentItem(item)
        # take/insert 后重新应用当前搜索词，避免排序使已过滤条目重新显示。
        self._apply_filter()

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
            it.setHidden(bool(kw) and kw not in it.text(0).lower())

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

        path = os.path.normpath(str(path))
        folder = os.path.dirname(path)
        self._list.setCurrentItem(item)

        menu = QtWidgets.QMenu(self._list)
        open_folder_action = menu.addAction(u"打开文件夹")
        open_folder_action.setEnabled(os.path.isdir(folder))
        package_path = os.path.splitext(path)[0] + ".uasset"
        load_action = menu.addAction(u"加载动作")
        load_action.setEnabled(not self._load_busy and os.path.isfile(package_path))
        load_action.setToolTip(u"加载同名 UE 动画包：{0}".format(package_path))
        import_action = menu.addAction(u"导入动作FBX")
        import_action.setEnabled(not self._load_busy and os.path.isfile(path))
        menu.setToolTipsVisible(True)

        chosen = menu.exec_(self._list.viewport().mapToGlobal(point))
        if chosen == open_folder_action:
            self._open_action_folder(path)
        elif chosen == load_action and load_action.isEnabled():
            self.loadActionRequested.emit(package_path.replace("\\", "/"))
        elif chosen == import_action and import_action.isEnabled():
            self.importActionRequested.emit(path.replace("\\", "/"))

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
