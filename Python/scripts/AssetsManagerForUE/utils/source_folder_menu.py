# -*- coding: utf-8 -*-
"""Shared Explorer action for server library source folders."""

import os

from PySide6 import QtCore, QtGui, QtWidgets


def add_open_source_folder_action(menu, folder):
    """Capture the selected card's source folder, independently of its UE state."""
    folder = os.path.normpath(str(folder)) if folder else ""
    menu.setToolTipsVisible(True)
    action = menu.addAction(u"打开文件夹")
    action.setToolTip(u"打开服务器源文件夹：{0}".format(folder))
    action.setEnabled(bool(folder) and os.path.isdir(folder))
    action.triggered.connect(
        lambda checked=False: open_source_folder(menu.parentWidget() or menu, folder))
    return action


def open_source_folder(parent, folder):
    if not folder or not os.path.isdir(folder):
        QtWidgets.QMessageBox.warning(
            parent, u"打开文件夹", u"服务器源文件夹不存在或无法访问：\n{0}".format(folder))
        return False
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
        QtWidgets.QMessageBox.warning(
            parent, u"打开文件夹", u"无法打开服务器源文件夹：\n{0}".format(folder))
        return False
    return True
