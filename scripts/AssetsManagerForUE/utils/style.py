#!/usr/bin/env python
# -*- coding: utf-8 -*-
from PySide2 import QtUiTools, QtWidgets, QtCore, QtGui
import os

DEF_SPACING = 8
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')


def _get_viewThumbnail_bttn(displayThumb_bttn, isList):
    """
    displayThumb_bttn  的初显示状态
    :return:
    """
    if isList:
        displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % scriptsPath))
        displayThumb_bttn.setToolTip("缩略图显示")
    else:
        displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % scriptsPath))
        displayThumb_bttn.setToolTip("表单显示")


def _viewList(listWgt):
    """
    列表显示
    :return:
    """
    # print("_viewList")
    listWgt.setIconSize(QtCore.QSize(20, 20))
    listWgt.setViewMode(QtWidgets.QListView.ListMode)
    listWgt.setGridSize(QtCore.QSize(2000, 25))
    listWgt.setSpacing(1)
    listWgt.setAlternatingRowColors(True)
    # listWgt.setStyleSheet(
    #     "QListWidget:item:selected,QListWidget:item:hover{border: 1.5px solid #666666;}" +
    #     "QListWidget:item{border-radius: 0px;background-color: rgb(60, 62, 64);border: 0px solid #1e1e1e;}")


def _viewThumb(listWgt, sizeSlider):
    """
    缩略图显示
    :return:
    """
    # print("_viewThumb")
    itemSize = sizeSlider.value()
    listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
    listWgt.setViewMode(QtWidgets.QListView.IconMode)
    listWgt.setGridSize(QtCore.QSize(itemSize + DEF_SPACING, itemSize + DEF_SPACING + 40))
    listWgt.setSpacing(2)  # 不起作用
    listWgt.setWordWrap(True)
    listWgt.setAlternatingRowColors(False)
    # listWgt.setStyleSheet(
    #     "QListWidget:item:hover{background-color: qlineargradient(spread:pad, y1:0, y2:1, stop:0.75 rgb(62, 64, 66), stop:0.76 rgb(40, 40, 40));border: 1.5px solid #666666;}" +
    #     "QListWidget:item:selected{background-color: qlineargradient(spread:pad, y1:0, y2:1, stop:0.75 rgb(65, 69, 75), stop:0.76 rgb(82, 133, 166));border: 1.5px solid rgb(82, 133, 166);}" +
    #     "QListWidget:item{border-radius: 8px;background-color: qlineargradient(spread:pad, y1:0, y2:1, stop:0 rgb(35, 35, 35), stop:0.75 rgb(60, 62, 64), stop:0.76 rgb(30, 30, 30));border: 1.5px solid #1e1e1e;}")


def get_viewThumbnail_listwgt(isList):
    """
    main_listWgt  的显示状态
    :return:
    """
    if isList :
        _viewList()
    else:
        _viewThumb()
