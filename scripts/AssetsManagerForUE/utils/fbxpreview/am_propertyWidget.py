#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 资产属性栏:展示当前选中资产的字段(只读),置于右侧 FBX 预览下方。

import os

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

__all__ = ["AssetPropertyWidget"]


class AssetPropertyWidget(QtWidgets.QWidget):
    """ 资产属性栏(只读)。

    数据约定(与 am_main 的 itemData 一致):
        [0]创建日期 [1]资产名 [2]中文名 [3]模型制作 [4]模型状态
        [5]绑定制作 [6]绑定状态 [7]Icon 路径 [8]备注
    Scenes 表的 [3..6] 是 制作人/状态(查询里重复了两次),[8] 为备注。
    """

    def __init__(self, parent=None):
        super(AssetPropertyWidget, self).__init__(parent)
        self._build_ui()
        self.clear()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self._title = QtWidgets.QLabel(u"属性")
        font = QtGui.QFont(u"Microsoft YaHei UI", 10)
        font.setBold(True)
        self._title.setFont(font)
        self._title.setStyleSheet("color: rgb(200, 200, 200);")
        outer.addWidget(self._title)

        # 滚动区:面板拖矮 / 备注、路径过长时可滚动,不被裁切
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        content = QtWidgets.QWidget()
        self._form = QtWidgets.QFormLayout(content)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(6)
        self._form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
        self._form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 对外接口
    def clear(self):
        """ 清空属性栏,显示占位提示。 """
        self._clear_form()
        hint = QtWidgets.QLabel(u"未选择资产")
        hint.setStyleSheet("color: rgb(130, 130, 130);")
        self._form.addRow(hint)

    def setAsset(self, data, tab="Assets"):
        """ 用资产数据元组填充属性栏。

        :type data: list | tuple
        :type tab: str  -- "Assets" / "Scenes"
        """
        self._clear_form()
        if not data:
            self.clear()
            return

        def g(i):
            try:
                v = data[i]
            except (IndexError, TypeError):
                return ""
            return "" if v is None else str(v)

        # 资产根目录(从 Icon 路径推导;以带分隔符的 /Icon/ 为锚点)
        ip = g(7).replace("\\", "/")
        if "/Icon/" in ip:
            root = ip.rsplit("/Icon/", 1)[0]
        else:
            root = os.path.dirname(os.path.dirname(ip)) if ip else ""

        if tab == "Scenes":
            rows = [
                (u"场景名", g(1)),
                (u"中文名", g(2)),
                (u"创建日期", g(0)),
                (u"制作人员", g(3)),
                (u"状态", g(4)),
                (u"备注", g(8)),
            ]
        else:
            rows = [
                (u"资产名", g(1)),
                (u"中文名", g(2)),
                (u"创建日期", g(0)),
                (u"模型制作", g(3)),
                (u"模型状态", g(4)),
                (u"绑定制作", g(5)),
                (u"绑定状态", g(6)),
                (u"备注", g(8)),
            ]
        rows.append((u"路径", root))

        for label_text, value_text in rows:
            self._add_row(label_text, value_text)

    # ------------------------------------------------------------------ 内部
    def _add_row(self, label_text, value_text):
        label = QtWidgets.QLabel(label_text + u"：")
        label.setStyleSheet("color: rgb(150, 150, 150);")
        value = QtWidgets.QLabel(value_text if value_text else u"—")
        value.setWordWrap(True)
        value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        value.setStyleSheet("color: rgb(220, 220, 220);")
        self._form.addRow(label, value)

    def _clear_form(self):
        while self._form.rowCount() > 0:
            self._form.removeRow(0)
