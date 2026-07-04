#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <AssetsManager_UE>Created: 19/10/2020 by Sunxh<175702994@qq.com>

import os
import sys
import json

# 1. 清除所有NAS/Y盘相关的路径（避免使用错误的venv）
sys.path[:] = [p for p in sys.path if not any(x in p for x in [
    r"Y:\ACTools\Python\UE5.03",
    r"fznas.diandian.info",
    r"\\fznas",
    r"\\AC\ACTools\Python",
    r"E:\CGTools_for_UE\UE574\Python\venv"
])]

# 2. 添加venv路径（最前面）
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

# 3. 先导入PySide6验证路径正确
from PySide6 import QtWidgets, QtUiTools, QtCore, QtGui

if scriptsPath not in sys.path:
    sys.path.append(scriptsPath)

# 4. 导入子模块
from .sources import assetTools, sceneTools, actionTools, ShotsManager_UE
from .utils import jsonHelper
from .config import SMConfig


class AssetsManagerUI(QtWidgets.QWidget):
    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
    sm_temp = "{}/ShotManagerTemp".format(os.environ.get('APPDATA'))
    SM_SETTING_JSON = "{}/setting.json".format(sm_temp)
    VERSION = "3.0.5"
    jsonPath = 'Y:/ACTools/CGTools/for_Maya/AssetsManagerForMaya'  # 读maya的json

    def __init__(self, parent=None):
        super(AssetsManagerUI, self).__init__(parent)

        self.setWindowTitle('Assets Manager ' + self.VERSION)
        self.setWindowIcon(QtGui.QIcon('%s/icon/blank_ch.png' % self.scriptsPath))
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)

        try:
            self.user = self.readLoginSetting()['user']
            self.password = self.readLoginSetting()['password']
        except Exception as e:
            print(e)
            self.user = SMConfig().getPrefsValue("Info/user", "")
            self.password = SMConfig().getPrefsValue("Info/password", "")

        self.isSQL = True
        self.tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))
        f = QtCore.QFile('%s/ui/AssetsManager.ui' % self.scriptsPath)
        f.open(QtCore.QFile.ReadOnly)
        loader = QtUiTools.QUiLoader().load(f)
        self.ui = loader
        f.close()
        self.init_ui()

    def init_ui(self):
        self.layout().addWidget(self.ui)
        '''风格外观'''
        pos, size, tab = self.readSettings()
        # print(pos, size, tab)
        if pos is not None and size is not None:
            self.resize(size)
            self.move(pos)
        else:
            self.resize(950, 600)
            self.move(2000, 120)

        if tab is not None:
            self.ui.tabWidget.setCurrentIndex(tab)
        else:
            self.ui.tabWidget.setCurrentIndex(0)
        self.getStyleSheet()

        '''角标栏'''
        login_bttn = QtWidgets.QPushButton(self)
        login_bttn.setIcon(QtGui.QIcon("%s/icon/user.png" % self.scriptsPath))
        login_bttn.setMinimumWidth(100)
        setting_bttn = QtWidgets.QPushButton()
        setting_bttn.setMaximumSize(QtCore.QSize(20, 20))
        setting_bttn.setStyleSheet("border-style: flat; background: transparent;")
        setting_bttn.setIcon(QtGui.QIcon('%s/icon/setting.png' % self.scriptsPath))
        setting_bttn.clicked.connect(self.toolSetting_UI)
        hLayout = QtWidgets.QHBoxLayout()
        hLayout.setContentsMargins(0, 3, 10, 0)
        hLayout.addWidget(login_bttn)
        hLayout.addWidget(setting_bttn)
        Frame = QtWidgets.QFrame(self)
        Frame.setLayout(hLayout)
        self.ui.tabWidget.setCornerWidget(Frame, corner=QtCore.Qt.TopRightCorner)

        if self.user != "" and self.password != "":
            login_bttn.setText(self.user)
        else:
            login_bttn.setText(u"未登录")

        self.tabChange()
        self.ui.tabWidget.currentChanged.connect(self.tabChange)

    def readLoginSetting(self):
        """ """
        if os.path.isfile(self.SM_SETTING_JSON):
            f = open(self.SM_SETTING_JSON, 'rb')
            setting_data = json.loads(f.read())
            f.close()
        else:
            setting_data = {}
        return setting_data

    def getStyleSheet(self):
        style_sheet_path = '%s/qss/UE5.qss' % self.scriptsPath
        with open(style_sheet_path) as (file):
            str = file.read()
        self.setStyleSheet(str)

    def rememberSettings(self):
        settings = QtCore.QSettings('AssetsManagerUE', 'AssetsManagerUESettings')
        settings.setValue('pos', self.pos())
        settings.setValue('size', self.size())
        settings.setValue('tab', self.ui.tabWidget.currentIndex())

    @staticmethod
    def readSettings():
        settings = QtCore.QSettings('AssetsManagerUE', 'AssetsManagerUESettings')
        pos = settings.value('pos')
        size = settings.value('size')
        tab = settings.value('tab')

        return pos, size, tab

    def closeEvent(self, event):
        # 先停掉各 tab 子界面里残留的 QThread，避免重开时线程/旧窗口累积
        # （以及“QThread: Destroyed while thread is still running”崩溃）。
        self._stop_child_threads()
        self.rememberSettings()

    def _stop_child_threads(self):
        """停止各 tab 子界面持有的 QThread（MyThread 等），让旧窗口能被回收。"""
        for name in ('asset_page', 'scene_page', 'action_page', 'animation_page'):
            page = getattr(self.ui, name, None)
            layout = page.layout() if page is not None else None
            if layout is None:
                continue
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w is None:
                    continue
                for v in list(vars(w).values()):
                    if isinstance(v, QtCore.QThread):
                        try:
                            v.quit()
                            v.wait(500)
                        except Exception:
                            pass

    def tabChange(self):
        """
        切换tab
        :return:
        """
        if self.ui.tabWidget.currentIndex() == 0 and self.ui.asset_page.layout().count() == 0:
            self.ui.asset_page.layout().addWidget(assetTools.AssetToolsUI(self.isSQL,
                                                                          user=self.user,
                                                                          password=self.password))
        elif self.ui.tabWidget.currentIndex() == 1 and self.ui.scene_page.layout().count() == 0:
            self.ui.scene_page.layout().addWidget(sceneTools.SceneToolsUI(self.isSQL,
                                                                          user=self.user,
                                                                          password=self.password))
        elif self.ui.tabWidget.currentIndex() == 2 and self.ui.action_page.layout().count() == 0:
            self.ui.action_page.layout().addWidget(actionTools.ActionToolsUI())
        elif self.ui.tabWidget.currentIndex() == 3 and self.ui.animation_page.layout().count() == 0:
            self.ui.animation_page.layout().addWidget(ShotsManager_UE.ShotsManagerUEUI())

    def projectSetting(self):
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % self.jsonPath)
        return data

    def toolSetting_UI(self):
        Dialog = QtWidgets.QDialog(self)
        Dialog.resize(390, 95)
        Dialog.setWindowTitle(u"Enter Super User Password")
        font = QtGui.QFont()
        font.setFamily(u"Microsoft YaHei UI")
        font.setPointSize(10)
        label = QtWidgets.QLabel(Dialog)
        label.setText(u"*请输入管理员密码以获取修改权限：")
        label.setFont(font)
        label2 = QtWidgets.QLabel(Dialog)
        label2.setText(u"Password")
        label2.setFont(font)
        self.password_lineEdit = QtWidgets.QLineEdit(Dialog)
        self.password_lineEdit.setEchoMode(QtWidgets.QLineEdit.Password)
        bttnbox = QtWidgets.QDialogButtonBox(Dialog)
        bttnbox.setOrientation(QtCore.Qt.Horizontal)
        bttnbox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        lay = QtWidgets.QGridLayout(Dialog)
        lay.setContentsMargins(10, 5, 10, 10)
        lay.addWidget(label, 0, 0, 1, 2)
        lay.addWidget(label2, 1, 0, 1, 1)
        lay.addWidget(self.password_lineEdit, 1, 1, 1, 1)
        lay.addWidget(bttnbox, 2, 1, 1, 1)
        bttnbox.accepted.connect(self.toolSetting)
        bttnbox.rejected.connect(Dialog.reject)
        Dialog.exec_()

    def toolSetting(self):
        password = self.password_lineEdit.text()
        jsonPath = '%s/config/projectSetting.json' % self.scriptsPath
        if password == "999999":
            if os.path.isfile(jsonPath):
                os.startfile(jsonPath)
            else:
                print(u"没有找到设置文件")
        else:
            QtWidgets.QMessageBox.warning(self, u'提示', u'密码错误')

    # def is_CGTW(self):
    #     try:
    #         import cgtw2
    #         t_tw = cgtw2.tw()
    #         login = t_tw.login.is_login()
    #         if login:
    #             return True
    #         else:
    #             msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：",
    #                                         u"<h3>请先登入CGTeamWork !</h3>")
    #             msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
    #             msg.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    #             msg.exec_()
    #             return False
    #     except:
    #         msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：",
    #                                     u"<h3>请先登入CGTeamWork !  并且安装在C盘标准目录下！</h3>")
    #         msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
    #         msg.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    #         msg.exec_()
    #         return False


APP = None
if not QtWidgets.QApplication.instance():
    APP = QtWidgets.QApplication(sys.argv)

win = None


def showWindow():
    """在 UE 中以“浮于 UE 之上、随 UE 最小化/还原”的方式显示 Assets Manager。

    具体的窗口挂接（parent_external_window_to_slate）与事件驱动
    （register_slate_post_tick_callback）封装在共享模块 ue_qt_host 中。
    """
    global win
    try:
        win.close()
    except Exception:
        pass

    win = AssetsManagerUI()
    win.setAttribute(QtCore.Qt.WA_DeleteOnClose)

    import ue_qt_host
    ue_qt_host.host_window(win, app=QtWidgets.QApplication.instance())
