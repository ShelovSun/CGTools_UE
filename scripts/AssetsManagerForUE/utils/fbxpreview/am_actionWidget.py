#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AssetActionWidget —— 资产动作浏览器(置于右侧 FBX 预览下方,替代原属性栏)。

递归列出资产 ``Action`` 目录下的所有 ``.fbx`` 动作文件。点击某动作 -> 发 actionActivated,
由 am_main 通知 PreviewGLWidget 把该动作的骨骼动画套用到绑定文件(``FBX/<asset>.fbx``)上
循环播放(见 am_previewGLWidget.PreviewGLWidget.playAction / am_fbxMesh.combine)。

约定:绑定文件位于 ``.../<asset>/FBX/<asset>.fbx``,动作目录为把路径中的 ``/FBX/`` 换成
``/Action/`` 后的目录(``.../<asset>/Action``)。动作文件一般只含骨骼动画、无网格。
"""

import os

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

__all__ = ["AssetActionWidget"]


class AssetActionWidget(QtWidgets.QWidget):
    """资产动作浏览器。

    actionActivated(str): 选中动作时发出其 .fbx 全路径;空字符串表示回到绑定文件静态预览。
    """

    actionActivated = QtCore.Signal(str)
    importActionRequested = QtCore.Signal(str)  # 右键"导入动作"时发出该动作 .fbx 全路径

    _LIST_QSS = (
        "QListWidget{background-color: rgb(35,36,39); border:none; color: rgb(210,210,210);}"
        "QListWidget::item{padding:4px 6px;}"
        "QListWidget::item:selected{background-color: rgb(70,125,209); color: white;}"
        "QListWidget::item:hover{background-color: rgb(55,58,64);}"
    )

    _SEARCH_QSS = (
        "QLineEdit{background-color: rgb(45,46,49); border:1px solid rgb(60,61,64);"
        " border-radius:3px; padding:3px 6px; color: rgb(210,210,210);"
        " selection-background-color: rgb(70,125,209);}"
        "QLineEdit:focus{border:1px solid rgb(70,125,209);}"
    )

    def __init__(self, parent=None):
        super(AssetActionWidget, self).__init__(parent)
        self._action_dir = ""
        self._build_ui()
        self.clear()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = QtWidgets.QLabel(u"动作库：")
        font = QtGui.QFont(u"Microsoft YaHei UI", 10)
        font.setBold(True)
        self._title.setFont(font)
        self._title.setStyleSheet("color: rgb(200, 200, 200);background-color: rgb(29,29,29);")
        outer.addWidget(self._title)

        # 搜索框:按动作名过滤列表
        search_wrap = QtWidgets.QWidget(self)
        search_wrap.setStyleSheet("background-color: rgb(29,29,29);")
        sl = QtWidgets.QHBoxLayout(search_wrap)
        sl.setContentsMargins(6, 4, 6, 4)
        sl.setSpacing(0)
        self._search = QtWidgets.QLineEdit(search_wrap)
        self._search.setStyleSheet(self._SEARCH_QSS)
        self._search.setPlaceholderText(u"搜索动作…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        sl.addWidget(self._search)
        outer.addWidget(search_wrap)

        self._list = QtWidgets.QListWidget(self)
        self._list.setStyleSheet(self._LIST_QSS)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        outer.addWidget(self._list, 1)

    # ------------------------------------------------------------------ 对外接口
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
        """根据绑定文件路径(.../FBX/<asset>.fbx)填充其 Action 目录下的动作列表(递归)。"""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._list.blockSignals(True)
        self._list.clear()

        action_dir = self._derive_action_dir(rig_fbx_path)
        self._action_dir = action_dir or ""

        fbx_files = self._scan_actions(action_dir)
        # 顶部:回到绑定文件静态预览
        top = QtWidgets.QListWidgetItem(u"资产预览")
        top.setData(QtCore.Qt.UserRole, "")
        top.setForeground(QtGui.QColor(170, 200, 255))
        self._list.addItem(top)

        if not action_dir or not os.path.isdir(action_dir):
            self._add_hint(u"无 Action 目录")
        elif not fbx_files:
            self._add_hint(u"该资产无动作 (.fbx)")
        else:
            for rel, full in fbx_files:
                it = QtWidgets.QListWidgetItem(rel)
                it.setData(QtCore.Qt.UserRole, full)
                it.setToolTip(full)
                self._list.addItem(it)

        self._list.blockSignals(False)

    # ------------------------------------------------------------------ 内部
    def _derive_action_dir(self, rig_fbx_path):
        """绑定文件路径 -> 动作目录:把 '/FBX/' 换成 '/Action/' 取所在目录。
        无 '/FBX/' 锚点时回退到资产根下的 'Action'。"""
        if not rig_fbx_path:
            return ""
        p = rig_fbx_path.replace("\\", "/")
        if "/FBX/" in p:
            return os.path.dirname(p.replace("/FBX/", "/Action/", 1))
        # 回退:.../<asset>/<file>.fbx -> .../<asset>/Action
        root = os.path.dirname(os.path.dirname(p))
        return (root + "/Action") if root else ""

    def _scan_actions(self, action_dir):
        """递归收集 action_dir 下所有 .fbx,返回 [(相对路径, 全路径)],按相对路径排序。"""
        if not action_dir or not os.path.isdir(action_dir):
            return []
        out = []
        for cur, _dirs, files in os.walk(action_dir):
            for fn in files:
                if fn.lower().endswith(".fbx"):
                    full = os.path.join(cur, fn).replace("\\", "/")
                    rel = os.path.relpath(full, action_dir).replace("\\", "/")
                    out.append((rel, full))
        out.sort(key=lambda rf: rf[0].lower())
        return out

    def _apply_filter(self, text=None):
        """按关键字隐藏不匹配的动作项(大小写不敏感子串匹配)。
        顶部"资产预览"始终可见;提示项(无 UserRole)不参与过滤。"""
        kw = (text if text is not None else self._search.text()).strip().lower()
        for i in range(self._list.count()):
            it = self._list.item(i)
            data = it.data(QtCore.Qt.UserRole)
            if data is None:
                continue  # 提示项
            if data == "":
                it.setHidden(False)  # 资产预览锚点始终可见
                continue
            it.setHidden(bool(kw) and kw not in it.text().lower())

    def _add_hint(self, text):
        it = QtWidgets.QListWidgetItem(text)
        it.setFlags(QtCore.Qt.NoItemFlags)
        it.setForeground(QtGui.QColor(130, 130, 130))
        self._list.addItem(it)

    def _on_item_clicked(self, item):
        if item is None:
            return
        path = item.data(QtCore.Qt.UserRole)
        if path is None:
            return  # 提示项(无 UserRole)
        self.actionActivated.emit(str(path))

    def _on_context_menu(self, pos):
        """右键动作项 -> "导入动作"菜单，发 importActionRequested(该动作 .fbx 全路径)。"""
        item = self._list.itemAt(pos)
        if item is None:
            return
        path = item.data(QtCore.Qt.UserRole)
        if not path:
            return  # 空串(资产预览锚点)/None(提示项) 不显示导入菜单
        menu = QtWidgets.QMenu(self)
        act = QtGui.QAction(u"导入动作", self)
        act.triggered.connect(lambda checked=False, p=str(path): self.importActionRequested.emit(p))
        menu.addAction(act)
        menu.exec_(self._list.mapToGlobal(pos))
