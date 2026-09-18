#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <AssetsManager_UE>Created: 19/10/2020 by Sunxh<175702994@qq.com>
# 新版主窗：完整保留旧资产/场景页，并增加 UE 最终包和蓝图工具能力。

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
from PySide6 import QtWidgets, QtCore, QtGui

if scriptsPath not in sys.path:
    sys.path.append(scriptsPath)

# 4. 这里只导入轻量配置。各功能模块在对应 Tab 第一次打开时再导入，
# 避免点击菜单时把数据库、FBX/OpenGL 预览和所有工具一次性冷加载。
from .config import SMConfig, commonSettingPath


class AssetsManagerUI(QtWidgets.QWidget):
    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
    sm_temp = "{}/ShotManagerTemp".format(os.environ.get('APPDATA'))
    SM_SETTING_JSON = "{}/setting.json".format(sm_temp)
    VERSION = "4.3.2"
    def __init__(self, parent=None):
        super(AssetsManagerUI, self).__init__(parent)

        self.setWindowTitle('Assets Manager ' + self.VERSION)
        self.setWindowIcon(QtGui.QIcon('%s/icon/blank_ch.png' % self.scriptsPath))

        login = self.readLoginSetting()
        self.user = login.get('user', '')
        self.password = login.get('password', '')
        if not self.user or not self.password:
            # 兼容旧 ShotManager 登录存储，但不再用缺少 key 的异常控制流程，
            # 避免每次开窗都打印 KeyError('user')。
            try:
                prefs = SMConfig()
                self.user = self.user or prefs.getPrefsValue("Info/user", "")
                self.password = self.password or prefs.getPrefsValue("Info/password", "")
            except Exception:
                pass

        self.isSQL = True
        self.tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))
        self._prepareOpenGLSurface()
        self.build_ui()

    def _prepareOpenGLSurface(self):
        """在顶层窗口首次 show 前建立一个极小的 OpenGL 子控件。

        Qt 在已经显示的普通 QWidget 树中第一次动态加入 QOpenGLWidget 时，
        可能把顶层窗口从 RasterSurface 切成 OpenGLSurface，并销毁/重建原生
        HWND。这个 HWND 已经被 UE Slate 托管，所以用户会看到主窗口消失后
        再出现。保留这个 1x1、位于其他控件下方的 guard，可让 surface 类型
        在 Slate 托管之前一次确定；真实 FBX 预览仍然保持按需创建。
        """
        self._gl_surface_guard = None
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget

            guard = QOpenGLWidget(self)
            guard.setObjectName("AssetsManagerOpenGLSurfaceGuard")
            guard.setFixedSize(1, 1)
            guard.move(0, 0)
            guard.setFocusPolicy(QtCore.Qt.NoFocus)
            guard.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            # 此时父窗口尚未显示；显式 show 只负责提前传播 texture-child 状态。
            guard.show()
            guard.lower()
            self._gl_surface_guard = guard
        except Exception:
            # 没有 QtOpenGLWidgets 时，FBX 预览器本身也会走图片回退，不阻止主窗。
            pass

    def build_ui(self):
        """纯代码搭建主窗：资产/场景/蓝图/特效/组件五个懒加载页。"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(1, 3, 1, 1)

        self.tabWidget = QtWidgets.QTabWidget()
        root.addWidget(self.tabWidget)

        self._tab_initialized = set()
        self._tab_build_pending = set()
        self._startup_load_enabled = False
        self.asset_page = self._createLazyPage(u"正在准备资产工具…")
        self.scene_page = self._createLazyPage(u"正在准备场景工具…")
        self.blueprint_page = self._createLazyPage(u"正在准备蓝图工具…")
        self.vfx_page = self._createLazyPage(u"正在准备特效工具…")
        self.component_page = self._createLazyPage(u"正在准备组件工具…")
        self.tabWidget.addTab(self.asset_page, u"资产")
        self.tabWidget.addTab(self.scene_page, u"场景")
        self.tabWidget.addTab(self.blueprint_page, u"蓝图")
        self.tabWidget.addTab(self.vfx_page, u"特效")
        self.tabWidget.addTab(self.component_page, u"组件")

        '''风格外观 / 记忆的窗口位置大小与上次 tab'''
        pos, size, tab = self.readSettings()
        if pos is not None and size is not None:
            self.resize(size)
            self.move(pos)
        else:
            self.resize(950, 600)
            self.move(2000, 120)
        tab = int(tab) if tab is not None else 0
        if tab not in (0, 1, 2, 3, 4):
            tab = 0
        self.getStyleSheet()

        '''角标栏：登录 + 设置'''
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
        self.tabWidget.setCornerWidget(Frame, corner=QtCore.Qt.TopRightCorner)
        login_bttn.setText(self.user if (self.user != "" and self.password != "") else u"未登录")

        self.tabWidget.currentChanged.connect(self.tabChange)
        self.tabWidget.setCurrentIndex(tab)

    @staticmethod
    def _createLazyPage(message):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(message)
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("color:#9b9b9b; font-size:14px;")
        layout.addWidget(label)
        return page

    def beginDeferredLoad(self):
        """窗口完成 show/Slate 挂接后再启动当前页，保证菜单点击能先看到窗口。"""
        if self._startup_load_enabled:
            return
        self._startup_load_enabled = True
        QtCore.QTimer.singleShot(80, self.tabChange)

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
        settings.setValue('tab', self.tabWidget.currentIndex())

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
        for page in (self.asset_page, self.scene_page, self.blueprint_page,
                     self.vfx_page, self.component_page):
            layout = page.layout() if page is not None else None
            if layout is None:
                continue
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w is None:
                    continue
                shutdown = getattr(w, "shutdownThreads", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception:
                        pass
                for v in list(vars(w).values()):
                    if isinstance(v, QtCore.QThread):
                        try:
                            v.quit()
                            v.wait(500)
                        except Exception:
                            pass

    def tabChange(self):
        """
        切换 tab：先让占位页有机会绘制，再异步调度首次模块导入和界面构建。
        """
        if not self._startup_load_enabled:
            return
        idx = self.tabWidget.currentIndex()
        if idx in self._tab_initialized or idx in self._tab_build_pending:
            return
        self._tab_build_pending.add(idx)
        QtCore.QTimer.singleShot(20, lambda index=idx: self._buildLazyTab(index))

    def _buildLazyTab(self, idx):
        if idx in self._tab_initialized:
            self._tab_build_pending.discard(idx)
            return
        pages = (self.asset_page, self.scene_page, self.blueprint_page,
                 self.vfx_page, self.component_page)
        if idx not in range(len(pages)):
            self._tab_build_pending.discard(idx)
            return
        page = pages[idx]
        layout = page.layout()
        try:
            if idx == 0:
                from .sources import assetTools
                widget = assetTools.AssetToolsUI(
                    self.isSQL, user=self.user, password=self.password)
            elif idx == 1:
                from .sources import sceneTools
                widget = sceneTools.SceneToolsUI(
                    self.isSQL, user=self.user, password=self.password)
            elif idx == 2:
                from .sources import blueprintTools
                widget = blueprintTools.BlueprintToolsUI()
            elif idx == 3:
                from .sources import vfxTools
                widget = vfxTools.VfxToolsUI()
            else:
                from .sources import componentTools
                widget = componentTools.ComponentToolsUI()

            while layout.count():
                old = layout.takeAt(0).widget()
                if old is not None:
                    old.deleteLater()
            layout.addWidget(widget)
            self._tab_initialized.add(idx)
        except Exception as exc:
            label = layout.itemAt(0).widget() if layout.count() else None
            if isinstance(label, QtWidgets.QLabel):
                label.setText(u"工具加载失败：{0}".format(exc))
            raise
        finally:
            self._tab_build_pending.discard(idx)

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
        jsonPath = commonSettingPath()
        if password == "999999":
            if os.path.isfile(jsonPath):
                os.startfile(jsonPath)
            else:
                print(u"没有找到设置文件")
        else:
            QtWidgets.QMessageBox.warning(self, u'提示', u'密码错误')


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
    app = QtWidgets.QApplication.instance()
    if getattr(ue_qt_host, "_IN_UNREAL", False):
        # 先创建 HWND 并挂到 Slate，再在第一次 Qt processEvents 中启动延迟计时。
        # beginDeferredLoad 内还会等待 80ms，因此首轮事件只负责真正绘制窗口壳。
        ue_qt_host.host_window(win, app=app)
        QtCore.QTimer.singleShot(0, win.beginDeferredLoad)
    else:
        # 独立环境的 host_window 会进入阻塞式 Qt exec()，必须预先安排定时器。
        win.beginDeferredLoad()
        ue_qt_host.host_window(win, app=app)
