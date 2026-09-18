# uncompyle6 version 3.7.4
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.8.6 (tags/v3.8.6:db45529, Sep 23 2020, 15:37:30) [MSC v.1927 32 bit (Intel)]
# Embedded file name: E:/PyCharm/AssetsManagerUE4/v2.1.0\tools\ue4SceneTools.py
# Compiled at: 2021-01-11 13:44:31


import os, sys, unreal, subprocess
from PySide6 import QtWidgets, QtUiTools, QtCore, QtGui
from functools import partial
from ..utils import exportFunctions
from imp import reload
# reload(exportFunctions)
WINDOW_NAME = 'UE4 Scene Tools'

class UE4SceneToolsUI(QtWidgets.QWidget):

    def __init__(self):
        super(UE4SceneToolsUI, self).__init__()
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)
        self.init_ui()

    def init_ui(self):
        self.scriptsPath = os.path.split(os.path.realpath(__file__))[0]
        self.scriptsPath = self.scriptsPath.replace('\\', '/')
        self.scriptsPath = self.scriptsPath.replace('tools', 'ui')
        f = QtCore.QFile('%s/ue4SceneTools.ui' % self.scriptsPath)
        f.open(QtCore.QFile.ReadOnly)
        loader = QtUiTools.QUiLoader().load(f)
        self.ui = loader
        f.close()
        self.layout().addWidget(self.ui)
        self.setWindowTitle(WINDOW_NAME)
        self.getStyleSheet()
        self.ui.exportScenePath_bttn.clicked.connect(self.getSceneExportPath)
        self.ui.exportScene_bttn.clicked.connect(self.exportScene)

    def readSettings(self):
        settings = QtCore.QSettings('ue4Scene_Tools', 'ue4Scene_Tools_Settings')
        pos = settings.value('pos')
        size = settings.value('size')
        if pos is not None and size is not None:
            self.resize(size)
            self.move(pos)
        return

    def closeEvent(self, event):
        settings = QtCore.QSettings('ue4Scene_Tools', 'ue4Scene_Tools_Settings')
        settings.setValue('pos', self.pos())
        settings.setValue('size', self.size())

    def getStyleSheet(self):
        scriptsPath = self.scriptsPath.replace('ui', 'qss')
        style_sheet_path = '%s/darkOrange.qss' % scriptsPath
        with open(style_sheet_path) as (file):
            str = file.read()
        self.setStyleSheet(str)

    def exportScene(self):
        tools_dir = os.path.split(os.path.realpath(__file__))[0]
        utils_dir = '%s/utils' % tools_dir.rsplit('\\', 1)[0]
        gpu_path = self.ui.exportScenePath_line.text()
        fbx_path = '%s.fbx' % gpu_path.split('.')[0]
        gpu_dir = gpu_path.rsplit('/', 1)
        gpu_name = '%s_GPU' % gpu_dir[1].split('.')[0]
        ef = exportFunctions.ExportFunctions()
        ef.exportSingleFbxFile(fbx_path)
        os.environ['PATH'] = 'C:/Program Files/Autodesk/Maya2019/bin;' + os.environ['PATH']
        subprocess.check_call('mayapy -c "import maya.standalone;maya.standalone.initialize();import sys;sys.path.append(r\'%s\');import standaloneMayapy;reload(standaloneMayapy); standaloneMayapy.importFBX(\'%s\'); standaloneMayapy.exportGPU(\'%s\', \'%s\')"' % (utils_dir, fbx_path, gpu_dir[0], gpu_name), shell=True)
        os.remove(fbx_path)
        print('Success')
        QtWidgets.QMessageBox.information(self, '提示', '导出成功')

    def getSceneExportPath(self):
        file_type = 'Alembic (*.abc);;All Files (*.*)'
        exportScenePath = QtWidgets.QFileDialog.getSaveFileName(filter=file_type)[0]
        self.ui.exportScenePath_line.setText(str(exportScenePath))


APP = None
if not QtWidgets.QApplication.instance():
    APP = QtWidgets.QApplication(sys.argv)

def showWindow():
    global win
    try:
        win.close()
    except:
        pass

    win = UE4SceneToolsUI()
    win.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    win.show()
