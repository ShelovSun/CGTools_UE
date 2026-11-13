# -*- coding: utf-8 -*-
"""Shared Explorer action for server library source folders."""

import os
import sys

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
    folder = os.path.normpath(str(folder)) if folder else ""
    if not folder or not os.path.isdir(folder):
        QtWidgets.QMessageBox.warning(
            parent, u"打开文件夹", u"服务器源文件夹不存在或无法访问：\n{0}".format(folder))
        return False
    if sys.platform == 'win32':
        # QDesktopServices uses the Windows shell/association handoff and can
        # wait even when the NAS directory itself responds immediately.
        # Send the folder as one argument directly to Explorer; don't wait for
        # the Explorer process or shell window to finish opening.
        explorer = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'explorer.exe')
        try:
            started = QtCore.QProcess.startDetached(explorer, [folder])
            opened = bool(started[0] if isinstance(started, tuple) else started)
        except (OSError, RuntimeError):
            opened = False
    else:
        opened = QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
    if not opened:
        QtWidgets.QMessageBox.warning(
            parent, u"打开文件夹", u"无法打开服务器源文件夹：\n{0}".format(folder))
        return False
    return True
