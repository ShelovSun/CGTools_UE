#!/usr/bin/env python
# -*- coding: utf-8 -*-
# sceneTools_UE Created: 9/5/2021 by Sunxh<175702994@qq.com>
# log: 第一次编写


import getpass
import os
import subprocess
import sys
import time
import unreal
import psycopg2

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

sys.path.append(scriptsPath.replace('sources', ''))
from utils import jsonHelper, exportFunctions, assetFunctions, messageBox, myWidget, addItems
from PySide6 import QtWidgets, QtCore, QtGui


class SceneToolsUI(QtWidgets.QMainWindow):

    def __init__(self, isSQL=True,
                 user="",
                 password=""):
        super(SceneToolsUI, self).__init__()

        self.scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')
        self.tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))

        self.asset_item_userRole = QtCore.Qt.UserRole
        self.type_item_userRole = QtCore.Qt.UserRole + 1
        self.isSQL = isSQL
        self.host = "10.0.203.34"
        self.user = user
        self.password = password
        self.scene_isList = False

        # 同步搭建界面（纯代码，无 I/O）→ 窗口一显示即最终布局，不闪。
        self.build_ui()
        self.firstView()
        # 数据加载(DB 查询)延迟到窗口显示后
        self.init_ui_thread = myWidget.MyThread()
        self.init_ui_thread.signal.connect(lambda: self.listWidgetAddItems(self.getItemsFromSQL()))
        self.init_ui_thread.start()

    def _toolBtn(self, icon_name, tip):
        b = QtWidgets.QPushButton()
        b.setFixedSize(25, 25)
        b.setIconSize(QtCore.QSize(22, 22))
        b.setIcon(QtGui.QIcon('%s/icon/%s' % (self.scriptsPath, icon_name)))
        b.setToolTip(tip)
        b.setStyleSheet("border-style: flat; background: transparent;")
        return b

    def build_ui(self):
        """纯代码搭建界面：左(项目+类型) | 中(工具栏+列表) | 右(静态预览+.ma列表+导出面板) + 底部状态栏。"""
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setSpacing(0)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.main_splitter.setHandleWidth(3)
        grid.addWidget(self.main_splitter, 0, 0)

        # ---- 左栏 ----
        left = QtWidgets.QWidget()
        leftV = QtWidgets.QVBoxLayout(left)
        leftV.setContentsMargins(0, 0, 0, 0)
        leftV.setSpacing(2)
        projRow = QtWidgets.QHBoxLayout()
        projRow.addWidget(QtWidgets.QLabel(u"项目："))
        self.proj_comb = QtWidgets.QComboBox()
        self.proj_comb.setMinimumWidth(50)
        projRow.addWidget(self.proj_comb, 1)
        leftV.addLayout(projRow)
        self.type_listWgt = QtWidgets.QListWidget()
        self.type_listWgt.setSortingEnabled(False)
        self.type_listWgt.setSpacing(3)
        leftV.addWidget(self.type_listWgt, 1)
        self.main_splitter.addWidget(left)

        # ---- 中栏 ----
        center = QtWidgets.QWidget()
        centerV = QtWidgets.QVBoxLayout(center)
        centerV.setContentsMargins(0, 0, 0, 0)
        centerV.setSpacing(8)
        tool = QtWidgets.QHBoxLayout()
        tool.setSpacing(3)
        self.scene_displayThumb_bttn = self._toolBtn('display_list.png', u"表单显示")
        tool.addWidget(self.scene_displayThumb_bttn)
        self.scene_itemSize_Slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.scene_itemSize_Slider.setMinimum(10)
        self.scene_itemSize_Slider.setMaximum(200)
        self.scene_itemSize_Slider.setValue(120)
        self.scene_itemSize_Slider.setMaximumWidth(250)
        tool.addWidget(self.scene_itemSize_Slider)
        self.scene_download_Bttn = self._toolBtn('download.png', u"下载资产到本地")
        tool.addWidget(self.scene_download_Bttn)
        self.scene_refresh_Bttn = self._toolBtn('refresh.png', u"刷新")
        tool.addWidget(self.scene_refresh_Bttn)
        tool.addStretch(1)
        self.scene_key_line = QtWidgets.QLineEdit()
        self.scene_key_line.setClearButtonEnabled(True)
        self.scene_key_line.setMaximumWidth(250)
        self.scene_key_line.setPlaceholderText(u"Search...")
        self.scene_key_line.addAction(QtGui.QIcon('%s/icon/search.png' % self.scriptsPath),
                                      QtWidgets.QLineEdit.LeadingPosition)
        tool.addWidget(self.scene_key_line)
        centerV.addLayout(tool)
        self.main_listWgt = myWidget.MainQListWiget()
        centerV.addWidget(self.main_listWgt, 1)
        self.main_splitter.addWidget(center)

        # ---- 右栏：静态预览 + .ma 列表 + 导出面板 ----
        right = QtWidgets.QWidget()
        rightV = QtWidgets.QVBoxLayout(right)
        rightV.setContentsMargins(0, 0, 0, 0)
        rightV.setSpacing(4)
        self.Preview_frame = QtWidgets.QFrame()
        self.Preview_frame.setFrameShape(QtWidgets.QFrame.Box)
        self.Preview_frame.setMinimumHeight(200)
        pv = QtWidgets.QVBoxLayout(self.Preview_frame)
        pv.setContentsMargins(0, 0, 0, 0)
        self.Preview_label = myWidget.PreviewLabel()
        pv.addWidget(self.Preview_label, 1)
        self.scene_title_label = QtWidgets.QLabel()
        self.scene_title_label.setWordWrap(True)
        self.scene_title_label.setMaximumHeight(45)
        pv.addWidget(self.scene_title_label)
        rightV.addWidget(self.Preview_frame)

        self.scene_int_listWgt = QtWidgets.QListWidget()
        self.scene_int_listWgt.setMaximumWidth(300)
        rightV.addWidget(self.scene_int_listWgt, 1)

        exportFrame = QtWidgets.QFrame()
        exportFrame.setFrameShape(QtWidgets.QFrame.Box)
        exportFrame.setMaximumWidth(300)
        ex = QtWidgets.QVBoxLayout(exportFrame)
        pathRow = QtWidgets.QHBoxLayout()
        pathRow.addWidget(QtWidgets.QLabel("Path:"))
        self.exportScenePath_line = QtWidgets.QLineEdit()
        pathRow.addWidget(self.exportScenePath_line, 1)
        self.exportScenePath_bttn = QtWidgets.QPushButton("...")
        self.exportScenePath_bttn.setFixedSize(25, 20)
        pathRow.addWidget(self.exportScenePath_bttn)
        ex.addLayout(pathRow)
        foliageRow = QtWidgets.QHBoxLayout()
        self.foliage_cBox = QtWidgets.QCheckBox("Foliage")
        foliageRow.addWidget(self.foliage_cBox)
        foliageRow.addStretch(1)
        ex.addLayout(foliageRow)
        self.exportScene_bttn = QtWidgets.QPushButton(u"导出场景ABC")
        ex.addWidget(self.exportScene_bttn)
        rightV.addWidget(exportFrame)
        rightV.addStretch(1)
        self.main_splitter.addWidget(right)

        self.main_splitter.setSizes([120, 500, 300])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)

        # ---- 底部状态栏 ----
        msgRow = QtWidgets.QHBoxLayout()
        msgRow.setSpacing(10)
        self.msg_icon_label = QtWidgets.QLabel()
        self.msg_icon_label.setFixedSize(15, 15)
        self.msg_icon_label.setScaledContents(True)
        msgRow.addWidget(self.msg_icon_label)
        self.msg_label = QtWidgets.QLabel()
        self.msg_label.setMaximumHeight(15)
        msgRow.addWidget(self.msg_label, 1)
        msgRow.addStretch(0)
        grid.addLayout(msgRow, 1, 0)

        # ---- 信号连接 ----
        self.proj_comb.currentIndexChanged.connect(self.projectChanged)
        self.type_listWgt.itemSelectionChanged.connect(self.typeChanged)
        self.scene_displayThumb_bttn.clicked.connect(self.viewThumbnailChange)
        self.scene_itemSize_Slider.valueChanged.connect(self.setItemSize)
        self.scene_itemSize_Slider.sliderReleased.connect(self.rememberSettings)
        self.scene_download_Bttn.clicked.connect(self.download_CGTicon_to_localTemp)
        self.scene_refresh_Bttn.clicked.connect(self.update_asset)
        self.scene_key_line.returnPressed.connect(self.sc_search)
        self.main_listWgt.itemSelectionChanged.connect(self.mainWightItemChanged)
        self.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.main_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.exportScenePath_bttn.clicked.connect(self.getSceneExportPath)
        self.exportScene_bttn.clicked.connect(self.exportScene)

    def projectSetting(self):
        jsonPath = 'Y:/ACTools/CGTools/scripts/AssetsManagerForMaya'
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % jsonPath)
        return data

    def rememberSettings(self):
        """ 记忆窗口设置 """
        settings = QtCore.QSettings('SceneUE', 'SceneUESettings')
        settings.setValue('isList', self.scene_isList)
        settings.setValue('thumbSize', self.scene_itemSize_Slider.value())
        settings.setValue('project', self.proj_comb.currentIndex())
        settings.setValue('typ', self.type_listWgt.currentRow())

    def readSettings(self):
        """ 读取QSettings数据 """
        settings = QtCore.QSettings('SceneUE', 'SceneUESettings')
        isList = settings.value('isList')
        thumbSize = settings.value('thumbSize')
        project = settings.value('project')
        typ = settings.value('typ')
        if isList is not None:
            if isList == 'true':
                self.scene_isList = True
            else:
                self.scene_isList = False

        return thumbSize, project, typ

    def firstView(self):
        """ 风格外观初设置。屏蔽选择信号，避免启动时同步触发 DB 查询。"""
        self.proj_comb.blockSignals(True)
        self.type_listWgt.blockSignals(True)
        try:
            self.get_proj()
            thumbSize, project, typ = self.readSettings()
            if thumbSize is not None:
                self.scene_itemSize_Slider.setValue(int(thumbSize))
            if project is not None:
                self.proj_comb.setCurrentIndex(int(project))
            else:
                self.proj_comb.setCurrentIndex(0)
            self.get_typ()
            if typ is not None and int(typ) != -1:
                self.type_listWgt.setCurrentRow(int(typ))
            else:
                self.type_listWgt.setCurrentRow(0)
        finally:
            self.proj_comb.blockSignals(False)
            self.type_listWgt.blockSignals(False)

    def get_proj(self):
        # print("update_project")
        self.proj_comb.clear()
        self.proj_comb.addItems(self.projectSetting()['projects'])

    def get_typ(self):
        # print("update_type")
        self.type_listWgt.clear()
        project = self.proj_comb.currentText()
        pj_path = '{0}/{1}/{2}'.format(self.projectSetting()['rootPath'], project, 'Scenes')
        directory = QtCore.QDir(pj_path)
        type_list = directory.entryList(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                        QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
        # print("update_type:",projcet_path,type_list)
        for i in type_list:
            item = QtWidgets.QListWidgetItem()
            item.setText(str(i))
            icon = QtGui.QIcon()
            pix = myWidget.Pixmap('%s/icon/folder.svg' % self.scriptsPath)
            if i == 'Map':
                pix.setColor(QtGui.QColor("#beff69"))
            else:
                pix.setColor(QtGui.QColor("#b3b3b3"))
            icon.addPixmap(pix, QtGui.QIcon.Normal, QtGui.QIcon.Off)
            item.setIcon(icon)
            item.setData(self.type_item_userRole, '{0}/{1}'.format(pj_path, i))
            self.type_listWgt.addItem(item)
        return type_list

    def projectChanged(self):
        self.rememberSettings()
        self.get_typ()

    def typeChanged(self):
        if self.type_listWgt.currentRow != -1:
            self.rememberSettings()
            self.update_asset()

    # def _rememberSetting(self):
    #     WinSetting = {'proj': self.proj_comb.currentIndex(),
    #                   'type': self.type_listWgt.currentRow(),
    #                   'isList': bool(self.scene_isList),
    #                   'thumbSize': self.scene_itemSize_Slider.value()}
    #     return WinSetting
    # 
    # def rememberSettings(self):
    #     """ 记忆窗口设置 """
    #     settingPath = "{}/AssetsManangerSetting.json".format(self.tempPath)
    #     WinSetting = self._rememberSetting()
    #     jsonHelper.writeDictToFile(settingPath, WinSetting)
    # 
    # def _readSetting(self):
    #     settingJson = "{}/AssetsManangerSetting.json".format(self.tempPath)
    #     if os.path.isfile(settingJson):
    #         settingdata = jsonHelper.readDictFromFile(settingJson)
    #         if settingdata is not None:
    #             return settingdata
    #         else:
    #             return {"thumbSize": 120, "type": 0, "proj": 0, "isList": False}
    #     else:
    #         return {"thumbSize": 120, "type": 0, "proj": 0, "isList": False}
    # 
    # def readSetting(self):
    #     isList = self._readSetting()['isList']
    #     thumbSize = self._readSetting()['thumbSize']
    #     typ = self._readSetting()['type']
    #     # print(isList,thumbSize,typ)
    #     if isList is not None:
    #         self.scene_isList = isList
    #     if thumbSize is not None:
    #         self.scene_itemSize_Slider.setValue(thumbSize)
    #     if typ is not None:
    #         self.type_listWgt.setCurrentRow(typ)
    #     else:
    #         self.type_listWgt.setCurrentRow(0)
    #     return
    # 
    # def showEvent(self, event):
    #     super(SceneToolsUI, self).showEvent(event)
    #     print("hjhjhhhhhh")
    #     # self.update_project()
    #     # self.update_type()
    #     # self.readSetting()
    #     # self.update_asset()
    # 
    # def closeEvent(self, event):
    #     super(SceneToolsUI, self).closeEvent(event)

    def getPanelsData(self):
        __project = str(self.proj_comb.currentText())
        # print(self.type_listWgt.selectedItems())
        __type = str(self.type_listWgt.selectedItems()[0].text())
        __path = '%s/%s/%s/%s' % (self.projectSetting()['rootPath'],
                                  __project,
                                  self.projectSetting()['scenesFolder'],
                                  __type)
        return __project, __type, __path

    def update_asset_int(self, modPath):
        self.scene_int_listWgt.clear()
        directory = QtCore.QDir(modPath)
        int_list = directory.entryList(['*.ma'], QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                       QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
        for i in int_list:
            item = QtWidgets.QListWidgetItem()
            item.setText(i.split("_mod")[0])
            self.scene_int_listWgt.addItem(item)

    def viewThumbnail(self):
        """缩略图/表单  初显示大小"""
        itemSize = self.scene_itemSize_Slider.value()
        if self.scene_isList:
            self.scene_displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.scene_displayThumb_bttn.setToolTip("缩略图显示")
            self.main_listWgt.setIconSize(QtCore.QSize(20, 20))
            self.main_listWgt.setViewMode(QtWidgets.QListView.ListMode)
            self.main_listWgt.setGridSize(QtCore.QSize(2000, 25))
            self.main_listWgt.setSpacing(1)
        else:
            self.scene_displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.scene_displayThumb_bttn.setToolTip("表单显示")
            self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.main_listWgt.setViewMode(QtWidgets.QListView.IconMode)
            self.main_listWgt.setGridSize(QtCore.QSize(itemSize + 2, itemSize + 40))
            self.main_listWgt.setSpacing(1)

    def viewThumbnailChange(self):
        """切换  缩略图/表单  显示"""
        itemSize = self.scene_itemSize_Slider.value()
        if self.scene_isList:
            self.scene_displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.scene_displayThumb_bttn.setToolTip("表单显示")
            self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.main_listWgt.setViewMode(QtWidgets.QListView.IconMode)
            self.main_listWgt.setGridSize(QtCore.QSize(itemSize + 2, itemSize + 40))
            self.main_listWgt.setSpacing(1)
            self.update_asset()
            self.scene_isList = False
        else:
            self.scene_displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.scene_displayThumb_bttn.setToolTip("缩略图显示")
            self.main_listWgt.setIconSize(QtCore.QSize(20, 20))
            self.main_listWgt.setViewMode(QtWidgets.QListView.ListMode)
            self.main_listWgt.setGridSize(QtCore.QSize(2000, 25))
            # self.main_listWgt.setStyleSheet("QListWidget:item{border: 1px solid #ffaa00};")
            self.main_listWgt.setSpacing(1)
            self.update_asset()
            self.scene_isList = True
        self.rememberSettings()

    def setItemSize(self):
        itemSize = self.scene_itemSize_Slider.value()
        if self.scene_isList:
            pass
        else:
            # self.projectChange()
            self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.main_listWgt.setGridSize(QtCore.QSize(itemSize + 2, itemSize + 40))

    def download_CGTicon_to_localTemp(self):
        """
        下载CGT的icon到本地
        """
        import cgtw2
        t_tw = cgtw2.tw()
        project, type, path = self.getPanelsData()
        TW_proj = self.projectSetting()['projectdiction'][project]
        t_asset_ids = t_tw.info.get_id(TW_proj, 'asset',
                                       [['asset.maya', '=', u"完成"], 'and', ['asset.assetstapy', '=', type]])
        TW_dictionInfo = t_tw.info.get(TW_proj, 'asset', t_asset_ids, ['asset.entity', 'asset.image', 'asset.cn_name'])
        for id in TW_dictionInfo:
            ids = [id['id']]
            localPath = "{0}/{1}/Assets/{2}".format(self.tempPath, project, type)
            if not os.path.exists(localPath):
                os.makedirs(localPath)
            try:
                downloadInfo = t_tw.info.download_image(TW_proj, 'asset', ids, 'asset.image', is_small=False,
                                                        local_dir=localPath)
                rename = downloadInfo[0]['asset.image'][0].rsplit("/", 1)[0] + "/" + id['asset.entity'] + ".png"
                if os.path.exists(rename):
                    print(u"%s已经存在！" % rename)
                else:
                    os.rename(downloadInfo[0]['asset.image'][0], rename)
            except:
                print(u"下载%s失败！" % id['asset.entity'])
        self.listWidgetAddItems_CGT(self.main_listWgt, project, type, keyWords="")

    def update_asset(self):
        """
        根据type，project，设置主面板item显示
        """
        project, _type, path = self.getPanelsData()
        if os.path.exists(str(path)):
            self.update_scene_thread = myWidget.MyThread()
            self.update_scene_thread.signal.connect(lambda: self.listWidgetAddItems(self.getItemsFromSQL()))
            self.infoMsg("info", "Loading...")
            self.update_scene_thread.start()
        else:
            self.main_listWgt.clear()

    def getItemsDict(self):
        """
        从CGTW获取字典
        :return:{role_name:{'role_name': xx,
                        'project': xx,
                        'type': xx,
                        'zh_name': xx,
                        'icon_path': xx}}
        """
        # __items_dict = {}
        # __tab = "Scenes"
        # __project, __type, __path = self.getPanelsData()
        # print(__project, __type, __path)
        # _projects = self.projectSetting()['projects']
        # _types = self.get_typ()

        if self.isSQL:
            __items_dict = self.getItemsFromSQL()
            # if not self.searchAll_cBox.isChecked():
            #     __items_dict = addItems.getItemsDictFromCGTW(__tab, __project, __type)
            # else:
            #     for pj in _projects:
            #         for ty in _types:
            #             __items_dict.update(addItems.getItemsDictFromCGTW(__tab, pj, ty))
        # else:
        #     __items_dict = addItems.getItemsDictFromPath(__tab, __project, __type)
        return __items_dict

    def getItemsFromSQL(self):
        _project, _type, path = self.getPanelsData()
        print(_project, _type, path)
        if self.isSQL:
            return self.get_database(_project, _type)

    def get_database(self, _project, _type):
        """ 得到asset数据 """
        conn = None
        cur = None
        get_script = ''' 
                 SELECT "scene.date", "scene.name", "scene.zh_name", "scene.artist", "scene.status", 
                 "scene.artist", "scene.status", "scene.icon" 
                 FROM public."scene"
                 WHERE
                 "scene.type" = '%s';
                 ''' % _type
        try:
            conn = psycopg2.connect(database=_project, user=self.user, password=self.password, host=self.host,
                                    port="5432")
            cur = conn.cursor()
            cur.execute(get_script)
            data = cur.fetchall()
            # print(data)
            return data
        except Exception as e:
            print(e)
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    def listWidgetAddItems(self, new_dict=None):
        """
        根据type，project，读取CGT资产数据库，设置主面板item显示
        """
        # print("listWidgetAddItems Scene", dict)
        listWgt = self.main_listWgt
        listWgt.clear()
        self.Preview_label.clear()
        keyWords = self.scene_key_line.text()
        is_list = self.scene_isList

        start_time = time.time()
        if new_dict:
            listWgt.setItems(new_dict)
        # listWgt.setItems(dict)
        listWgt.setIsList(is_list)
        listWgt.setItemSize(self.scene_itemSize_Slider.value())
        listWgt.addItems(keyWords)
        listWgt.setMode()
        end_time = time.time()

        self.infoMsg("info", 'Load Completed !  ' +
                     "   %s items" % (listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')

    def mainWightItemChanged(self):
        """
        改变item触发：改变rBttn显示,改变预览显示,改变scene_int_listWgt显示
        """
        currentSelected = self.main_listWgt.selectedItems()
        if currentSelected:
            item_data = currentSelected[0].itemData()
            modPath = '{0}/{1}/Scenes/{2}/{3}/Mod'.format(self.projectSetting()['rootPath'], item_data['project'],
                                                          item_data['type'], item_data['role_name'])
            '''根据item_data设置预览窗口显示'''
            self.Preview_label.clear()
            self.Preview_label.setPreviewPixmap(item_data['icon_path'])

            self.scene_title_label.clear()
            self.scene_title_label.setText(u"Name：  " + item_data["role_name"] + u"\n中文名： " + item_data["zh_name"])

            self.update_asset_int(modPath)

    def show_menu(self, point):
        """
        右键菜单
        """
        currentItem = self.main_listWgt.itemAt(point)
        if currentItem is not None:
            menu = QtWidgets.QMenu(self.main_listWgt)
            show_action = QtGui.QAction('Show in Explorer', self)
            show_action.setIcon(QtGui.QIcon("{}/icon/folder_white.png".format(self.scriptsPath)))
            imp_action = QtGui.QAction('Import', self)

            menu.addAction(show_action)
            menu.addSeparator()
            menu.addAction(imp_action)

            show_action.triggered.connect(self.openDir)
            imp_action.triggered.connect(self.importFile)

            menu.exec_(QtGui.QCursor.pos())
        return

    def openDir(self):
        try:
            currentSelected, currentProject, currentType = self.getCurrentData()
        except:
            self.infoMsg('warning', 'Please select Character!!!')
            return
        mod_file_path = '%s/%s/Scenes/%s' % (self.projectSetting()['rootPath'], currentProject, currentType)
        folder_path = os.path.dirname(mod_file_path)
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists():
            QtGui.QDesktopServices.openUrl(folder_path)
        else:
            pass

    def loadingText(self):
        # print("loadingGif()")
        text = "Loading ... "
        self.main_listWgt.clear()
        item = QtWidgets.QListWidgetItem()
        item.setText(text)
        self.main_listWgt.addItem(item)

    def export_data(self, asset_name, type, bool):
        asset_list, type_path = self.get_asset_list()
        current_type = self.type_listWgt.currentItem().text()
        if current_type == 'Scene':
            data_path = '{0}/{1}/{2}/{3}'.format(type_path, asset_name, 'Terrain', type)
        else:
            data_path = '{0}/{1}/{2}'.format(type_path, asset_name, type)
        self.make_path(data_path)
        if bool:
            self.scenePub.createHistory(data_path)
        return data_path

    def override_check(self, asset_name):
        asset_list, type_path = self.get_asset_list()
        if asset_name in asset_list:
            reply = QtWidgets.QMessageBox.question(self, '提示', '有重名资产，确定要覆盖吗？',
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                return True
            return False
        else:
            return True

    def get_asset_list(self):
        if self.type_listWgt.currentItem() is None:
            return
        else:
            type_path = self.type_listWgt.currentItem().data(self.type_item_userRole)
            directory = QtCore.QDir(type_path)
            asset_list = directory.entryList(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                             QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
            return asset_list, type_path

    def make_path(self, path):
        fileinfo = QtCore.QFileInfo(path)
        if fileinfo.exists() is False:
            mkpath = QtCore.QDir()
            mkpath.mkpath(path)

    def sc_search(self):
        """
        搜索
        """
        self.listWidgetAddItems()
        # project, type, path = self.getPanelsData()
        # self.main_listWgt.clear()
        # keyWords = self.scene_key_line.text().lower()
        # if not self.scene_searchAll_cBox.isChecked():
        #     self.listWidgetAddItems_CGT(project, type)
        # else:
        #     for i in self.projectSetting()['projects']:
        #         self.listWidgetAddItems_CGT(i, type)

    def listWidgetAddItems_CGT(self, project, type):
        """
        根据type，project，读取CGT资产数据库，icon优先读取本地数据（快速），设置主面板item显示
        """
        import cgtw2
        t_tw = cgtw2.tw()
        keyWords = self.scene_key_line.text()
        self.main_listWgt.clear()
        self.Preview_label.clear()
        path = '{0}/{1}/{2}/{3}'.format(self.projectSetting()['rootPath'], project,
                                        self.projectSetting()['scenesFolder'], type)
        TW_proj = self.projectSetting()['projectdiction'][project]
        t_asset_ids = t_tw.info.get_id(TW_proj, 'scenes',
                                       [['scenes.maya', '=', u"完成"], 'and', ['scenes.scenesassetstype', '=', type]])
        TW_dictionInfo = t_tw.info.get(TW_proj, 'scenes', t_asset_ids, ['scenes.entity', 'scenes.assetsnamecn'])
        currentTypeItem = self.type_listWgt.currentItem()
        if currentTypeItem:
            for info in TW_dictionInfo:
                item = QtWidgets.QListWidgetItem()
                type_path = currentTypeItem.data(self.type_item_userRole)
                icon_path = '{0}/{1}/Icon/{1}.png'.format(type_path, info['scenes.entity'])
                asset_info = {'role_name': info['scenes.entity'], 'project': project, 'type': type}
                starttime = time.time()
                if info['scenes.entity'].lower().find(keyWords.lower()) != -1 or info['scenes.assetsnamecn'].find(
                        keyWords) != -1:
                    item.setData(self.asset_item_userRole, asset_info)
                    if self.scene_isList:
                        item.setText(info['scenes.entity'] + '   /   ' + info['scenes.assetsnamecn'])
                    else:
                        itemSize = self.scene_itemSize_Slider.value()
                        if not QtCore.QFileInfo(icon_path).exists():
                            icon_path = self.projectSetting()['defaultIcon']
                        item.setText(info['scenes.entity'] + '\n' + info['scenes.assetsnamecn'])
                        item.setIcon(QtGui.QIcon(QtGui.QPixmap(icon_path)))
                        self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
                        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
                    self.main_listWgt.addItem(item)
            endtime = time.time()
            self.msg_icon_label.setPixmap(QtGui.QPixmap("%s/icon/info.png" % self.scriptsPath))
            self.msg_label.setText('Completed !  ' + '   Path :  ' + path + '        Total :  ' + str(
                self.main_listWgt.count()) + '        Cost :  ' + str(endtime - starttime) + ' sec')
            self.viewThumbnail()

    def addItems_CGT(self, role_name, icon_path, ch_name):
        # item_data = self.itemDetail(role_name)
        itemSize = self.scene_itemSize_Slider.value()
        item = QtWidgets.QListWidgetItem()
        item.setText(role_name + '   /   ' + ch_name)  # 设置文字

        type_path = self.type_listWgt.currentItem().data(self.type_item_userRole)
        assembly_file_path = '{0}/{1}/{2}/{1}_AD.ma'.format(type_path, role_name, 'Assembly')
        icon_file_path = '{0}/{1}/{2}/{1}.png'.format(type_path, role_name, 'Icon')
        mod_file_path = '{0}/{1}/{2}/{1}_mod.ma'.format(type_path, role_name, 'Mod')
        asset_info = {'role_name': role_name, 'Assembly': assembly_file_path, 'Icon': icon_file_path,
                      'Mod': mod_file_path}
        item.setData(self.asset_item_userRole, asset_info)  # 记录信息

        icon = QtGui.QIcon()
        pixmap = QtGui.QPixmap(icon_path)  # 设置icon
        icon.addPixmap(pixmap, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item.setIcon(icon)
        self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
        item.setTextAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        self.main_listWgt.addItem(item)

    def importFile(self):
        """
        导入Asset文件到UE
        """
        try:
            currentSelected, currentProject, currentType = self.getCurrentData()
        except:
            print('Please select Character!!!')
            return
        if currentType != "Map":
            for item in currentSelected:
                item_data = item.data(QtCore.Qt.UserRole)
                role_name = item_data['role_name']
                path = '{0}/{1}/Scenes/{2}/{3}/FBX'.format(self.projectSetting()['rootPath'],
                                                           currentProject,
                                                           currentType,
                                                           role_name)
                directory = QtCore.QDir(path)
                type_list = directory.entryList(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                                QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
                for i in type_list:
                    if i.endswith('.fbx'):
                        fbx_path = '%s/%s' % (path, i)
                        # skeleton_path = ('/Game/Assets/{1}/{0}/Maya/{0}_Skeleton').format(role_name, currentType)
                        skeleton_path = '/Game/Scenes/{0}/{1}/{1}_Skeleton'.format(currentType, role_name)
                        # character_folder = ('/Game/Assets/{1}/{0}/Maya/').format(role_name, currentType)  # 带maya
                        scenes_folder = '/Game/Scenes/{0}/{1}/'.format(currentType, role_name)
                        material_folder = '/Game/Scenes/{0}/{1}/Material/'.format(currentType, role_name)
                        texture_folder = '/Game/Scenes/{0}/{1}/Texture/'.format(currentType, role_name)
                        max_folder = '/Game/Scenes/{0}/{1}/Max/'.format(currentType, role_name)
                        AF = assetFunctions.AssetFunctions()
                        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
                        asset_list_before = asset_reg.get_assets_by_path(scenes_folder)
                        animation_mesh_task = AF.buildImportTask(fbx_path, scenes_folder,
                                                                 AF.buildStaticMeshImportOptions())
                        AF.executeImportTasks([animation_mesh_task])
                        if not unreal.EditorAssetLibrary.does_directory_exist(material_folder):
                            unreal.EditorAssetLibrary.make_directory(material_folder)
                        if not unreal.EditorAssetLibrary.does_directory_exist(texture_folder):
                            unreal.EditorAssetLibrary.make_directory(texture_folder)
                        if not unreal.EditorAssetLibrary.does_directory_exist(max_folder):
                            unreal.EditorAssetLibrary.make_directory(max_folder)
                        self.repathAssets(scenes_folder)
        else:
            self.infoMsg("warning", u"UE里Map不能导入 ！")

    def repathAssets(self, character_folder):
        """
        移动Material和Texture
        """
        editorAssetLib = unreal.EditorAssetLibrary()
        assets_list = editorAssetLib.list_assets(character_folder)
        for asset in assets_list:
            assetData = editorAssetLib.find_asset_data(asset)
            assetName = assetData.get_asset().get_name()
            assetPathName = assetData.get_asset().get_path_name()
            assetClassName = assetData.get_asset().get_class().get_name()
            # print ('hahaha'+assetClassName)
            if assetClassName == 'Material':
                targetPathName = '{0}/{1}/{2}.{2}'.format(character_folder.rsplit('/', 1)[0], assetClassName,
                                                          assetName)
                editorAssetLib.rename_asset(assetPathName, targetPathName)
            elif assetClassName == 'Texture2D':
                targetPathName = '{0}/Texture/{1}.{1}'.format(character_folder.rsplit('/', 1)[0], assetName)
                editorAssetLib.rename_asset(assetPathName, targetPathName)

    def detailPath(self):
        item_data = self.main_listWgt.currentItem().data(self.asset_item_userRole)
        detailPaths = {'Assembly': '{0}/{1}/{2}/{3}/{4}/Assembly/{4}_AD.ma'.format(self.projectSetting()['rootPath'],
                                                                                   item_data['project'],
                                                                                   self.projectSetting()[
                                                                                       'scenesFolder'],
                                                                                   item_data['type'],
                                                                                   item_data['role_name']),
                       'Icon': '{0}/{1}/{2}/{3}/{4}/Icon/{4}.png'.format(self.projectSetting()['rootPath'],
                                                                         item_data['project'],
                                                                         self.projectSetting()['scenesFolder'],
                                                                         item_data['type'], item_data['role_name']),
                       'GPU': '{0}/{1}/{2}/{3}/{4}/GPU/{4}_GPU.abc'.format(self.projectSetting()['rootPath'],
                                                                           item_data['project'],
                                                                           self.projectSetting()['scenesFolder'],
                                                                           item_data['type'], item_data['role_name']),
                       'Mod': '{0}/{1}/{2}/{3}/{4}/Mod/{4}_mod.ma'.format(self.projectSetting()['rootPath'],
                                                                          item_data['project'],
                                                                          self.projectSetting()['scenesFolder'],
                                                                          item_data['type'], item_data['role_name'])}
        return detailPaths

    def getCurrentData(self):
        currentSelected = self.main_listWgt.selectedItems()
        currentProject = str(self.proj_comb.currentText())
        currentType = self.type_listWgt.selectedItems()[0].text()
        return currentSelected, currentProject, currentType

    def exportScene(self):
        # utils_dir = '%s/utils' % self.scriptsPath
        # print(utils_dir)
        # gpu_path = self.exportScenePath_line.text()
        # fbx_path = '%s.fbx' % gpu_path.split('.')[0]
        # gpu_dir = gpu_path.rsplit('/', 1)
        # gpu_name = '%s_GPU' % gpu_dir[1].split('.')[0]
        # print(gpu_name)
        # ef = exportFunctions.ExportFunctions()
        # ef.exportSingleFbxFile(fbx_path)
        # print("ddddd")
        # os.environ['PATH'] = 'C:/Program Files/Autodesk/Maya2019/bin;' + os.environ['PATH']
        # subprocess.check_call('mayapy -c "import maya.standalone;maya.standalone.initialize();import sys;sys.path.append(r\'%s\');import standaloneMayapy;standaloneMayapy.importFBX(\'%s\'); standaloneMayapy.exportGPU(\'%s\', \'%s\')"' % (utils_dir, fbx_path, gpu_dir[0], gpu_name), shell=True)
        # os.remove(fbx_path)
        # print ('Success !! ')
        # QtGui.QMessageBox.information(self, '提示', '导出成功')
        task = 100
        with unreal.ScopedSlowTask(task, '正在导出，请等待......') as (slow_task):
            slow_task.make_dialog(True)
            slow_task.enter_progress_frame(10, '正在导出，请等待......')
            utils_dir = '%s/utils' % self.scriptsPath
            gpu_path = self.exportScenePath_line.text()
            fbx_path = '%s.fbx' % gpu_path.split('.')[0]
            gpu_dir = gpu_path.rsplit('/', 1)
            gpu_name = '%s_GPU' % gpu_dir[1].split('.')[0]
            is_foliage_export = self.foliage_cBox.isChecked()
            allExport = self.all_cBox.isChecked()
            if is_foliage_export:
                slow_task.enter_progress_frame(20, '正在导出植被，请等待......')
            ef = exportFunctions.ExportFunctions()
            ef.exportSingleFbxFile(fbx_path, is_foliage_export, allExport)
            slow_task.enter_progress_frame(50, 'fbx导出成功，正在转换GPU，请等待......')
            os.environ['PATH'] = 'C:/Program Files/Autodesk/Maya2019/bin;' + os.environ['PATH']
            subprocess.check_call(
                'mayapy -c "import maya.standalone;maya.standalone.initialize();import sys;sys.path.append('
                'r\'%s\');import standaloneMayapy;reload(standaloneMayapy); standaloneMayapy.importFBX(\'%s\'); '
                'standaloneMayapy.exportGPU(\'%s\', \'%s\')"' % (utils_dir, fbx_path, gpu_dir[0], gpu_name),
                shell=True)
            # os.remove(fbx_path)
            slow_task.enter_progress_frame(90, '正在转换GPU，请等待......')
            print('Success !!')
            slow_task.make_dialog(False)
            msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：", u"<h3>场景GPU导出成功  ! !</h3>       ")
            msg.setStyleSheet("background-color: #1c1c1c;color: #b9b9b9;")
            msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
            msg.setDefaultButton(QtWidgets.QMessageBox.Cancel)
            msg.exec_()

    def getSceneExportPath(self):
        file_type = 'Alembic (*.abc);;All Files (*.*)'
        exportScenePath = QtWidgets.QFileDialog.getSaveFileName(filter=file_type)[0]
        self.exportScenePath_line.setText(str(exportScenePath))

    def fbxDefaultExportPath(self):
        gpu_path = self.exportScenePath_line.text()
        fbx_name = os.path.basename(gpu_path).split('.')[0]
        user_name = getpass.getuser()
        temp_path = 'C:/Users/%s/AppData/Local/Temp' % user_name
        if not os.path.exists(temp_path):
            os.makedirs(temp_path)
        fbx_path = 'C:/Users/%s/AppData/Local/Temp/%s.fbx' % (user_name, fbx_name)
        if os.path.exists(fbx_path):
            os.remove(fbx_path)
        return fbx_path

    def infoMsg(self, icon, text):
        messageBox.show_msg(self.msg_icon_label, icon,
                            self.msg_label, text)


def showWindow():
    global win
    try:
        win.close()
    except:
        pass

    win = SceneToolsUI()
    win.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    win.show()
