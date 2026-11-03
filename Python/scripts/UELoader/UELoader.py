#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/10/2020 by Sunxh<175702994@qq.com>


import os, sys, unreal, shutil
sys.path.append('Y:\\ACTools\\Python\\UE5.03\\venv\\Lib\\site-packages')
from PySide2.QtCore import *
from PySide2.QtWidgets import *
from . import assetFunctions

class UELoaderUI(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(300, 150)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(8)
        sizePolicy.setVerticalStretch(11)
        sizePolicy.setHeightForWidth(Dialog.sizePolicy().hasHeightForWidth())
        Dialog.setSizePolicy(sizePolicy)
        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setSpacing(6)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(-1, 0, -1, -1)
        self.pushButton = QPushButton(Dialog)
        self.pushButton.setObjectName(u"pushButton")
        sizePolicy1 = QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(12)
        sizePolicy1.setHeightForWidth(self.pushButton.sizePolicy().hasHeightForWidth())
        self.pushButton.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.pushButton)

        self.pushButton_2 = QPushButton(Dialog)
        self.pushButton_2.setObjectName(u"pushButton_2")
        sizePolicy1.setHeightForWidth(self.pushButton_2.sizePolicy().hasHeightForWidth())
        self.pushButton_2.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.pushButton_2)

        self.pushButton_4 = QPushButton(Dialog)
        self.pushButton_4.setObjectName(u"pushButton_4")
        sizePolicy1.setHeightForWidth(self.pushButton_4.sizePolicy().hasHeightForWidth())
        self.pushButton_4.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.pushButton_4)

        self.pushButton_3 = QPushButton(Dialog)
        self.pushButton_3.setObjectName(u"pushButton_3")
        sizePolicy1.setHeightForWidth(self.pushButton_3.sizePolicy().hasHeightForWidth())
        self.pushButton_3.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.pushButton_3)


        self.retranslateUi(Dialog)

        QMetaObject.connectSlotsByName(Dialog)

        Dialog.show()

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"UELoader v 1.0.1 ", None))
        Dialog.setStyleSheet("background-color: #1c1c1c;color: #b9b9b9;")
        self.pushButton.setText(QCoreApplication.translate("Dialog", u"加载灯光Script到工程（旧的灯光工具）", None))
        self.pushButton_2.setText(QCoreApplication.translate("Dialog", u"加载.abc到工程（屋顶雪）", None))
        self.pushButton_4.setText(QCoreApplication.translate("Dialog", u"导单帧ABC", None))
        self.pushButton_3.setText(QCoreApplication.translate("Dialog", u"None...", None))
        self.pushButton.clicked.connect(lambda:self.load_uasset(uassetpath=r"Y:/ACTools/LGTSet_UE/Content/Script"))
        self.pushButton_2.clicked.connect(lambda: self.load_abc(Dialog))
        self.pushButton_4.clicked.connect(lambda: self.load_abc(Dialog, static=True))

      
    def load_uasset(self, uassetpath):
        '''拷贝uassetpath的内容到Content目录下'''
        flodername=uassetpath.split('/')[-1]
        contentpath=unreal.Paths.project_content_dir()
        contentfile=os.listdir(contentpath)
        if os.path.isdir(uassetpath):
            if flodername not in contentfile:
                try:
                    copytree(uassetpath, contentpath + flodername)
                    print ("%s is loaded!!"%flodername)
                    msgBox = QMessageBox()
                    msgBox.setText(u"%s 成功加载！请保存重启UE！！"%flodername)
                    msgBox.exec_()
                except:
                    unreal.log_warning("%s load failed!!"%flodername)
            else :
                unreal.log_warning("%s is exist in content!!! load failed!!"%flodername)
                msgBox = QMessageBox()
                msgBox.setText(u"%s 已存在工程中，加载失败！！"%flodername)
                msgBox.exec_()
        else:
            unreal.log_warning("%s is not exist！！！"%uassetpath)
            msgBox = QMessageBox()
            msgBox.setText(u"%s不存在，加载失败！请联系管理员"%flodername)
            msgBox.exec_()

    def load_abc(self, Dialog, static=False):
        """ """
        # exportABC = QFileDialog.getExistingDirectory(options=QFileDialog.ShowDirsOnly)
        files, selectedFilter = QFileDialog.getOpenFileNames(Dialog, u"选择abc文件导入", "/home", "ABC(*.abc)")
        print(files)
        character_folder = '/Game/Scenes/FX/SnowMesh/Cache'
        for i in files:
            AF = assetFunctions.AssetFunctions()
            asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
            asset_list_before = asset_reg.get_assets_by_path(character_folder)
            if static:
                animation_mesh_task = AF.buildImportTask(i, character_folder, AF.buildABCImportOptions_static())
            else:
                animation_mesh_task = AF.buildImportTask(i, character_folder, AF.buildABCImportOptions())
            AF.executeImportTasks([animation_mesh_task])


win = None


def showWin():
    """浮于 UE 之上、随 UE 最小化/还原；挂接与事件驱动封装在共享模块 ue_qt_host。"""
    global win
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    try:
        win.close()
    except Exception:
        pass

    win = QWidget()
    win.setAttribute(Qt.WA_DeleteOnClose)
    ui = UELoaderUI()
    ui.setupUi(win)
    win._ui = ui  # 保活，避免 UI 对象被回收

    import ue_qt_host
    ue_qt_host.host_window(win, app=app)

def loadEnginePlugin(pluginpath):
    # pluginpath='Y:/Onemt/Marketing/Shared/Plug-in/LGTSet_UE/Plugins/GetRGB'
    flodername = pluginpath.split('/')[-1]
    enginePluginsPath=unreal.Paths.engine_plugins_dir()
    pluginfile = os.listdir(enginePluginsPath)
    if os.path.isdir(pluginpath):
        if flodername not in pluginfile:
            try:
                copytree(pluginpath, enginePluginsPath + flodername)
                print ("%s is loaded!!" % flodername)
            except:
                unreal.log_warning("%s load failed!!" % flodername)
        else:
            unreal.log_warning("%s is exist in project's plugin!!! load failed!!" % flodername)
    else:
        unreal.log_warning("%s is not exist！！！" % pluginpath)

def loadProjectPlugin():
    """ """
    
def copytree(src, dst, symlinks = False, ignore = None):
    '''拷贝'''
    if not os.path.exists(dst):
        os.makedirs(dst)
        shutil.copystat(src, dst)
    lst = os.listdir(src)
    if ignore:
        excl = ignore(src, lst)
        lst = [x for x in lst if x not in excl]
    for item in lst:
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if symlinks and os.path.islink(s):
            if os.path.lexists(d):
                os.remove(d)
            os.symlink(os.readlink(s), d)
            try:
                st = os.lstat(s)
                mode = stat.S_IMODE(st.st_mode)
                os.lchmod(d, mode)
            except:
                pass # lchmod not available
        elif os.path.isdir(s):
            copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)

def run_utilitywidget(widgetpath):
    '''跑widget'''
    #widgetpath='/Game/Script/ONEMTLGTSet_v2'
    contentpath=unreal.Paths.project_content_dir()
    widgetfile=contentpath+widgetpath.split('Game/')[1]+".uasset"
    if os.path.isfile(widgetfile):
        widget_asset  = unreal.EditorAssetLibrary.load_asset(widgetpath)
        editor_utility_subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        editor_utility_subsystem.spawn_and_register_tab(widget_asset)
    else:
        unreal.log_warning("%s is not exist！！！"%widgetfile)