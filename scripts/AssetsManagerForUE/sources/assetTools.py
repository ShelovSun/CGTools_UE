#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <AssetsManager_UE>Created: 19/10/2020 by Sunxh<175702994@qq.com>

import os
import sys
import threading
import time
import unreal
import psycopg2

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = os.path.join(os.path.dirname(scriptsPath), '..', '..', 'venv', 'Lib', 'site-packages').replace('\\', '/')
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from PySide6 import QtWidgets, QtUiTools, QtCore, QtGui

from functools import partial
from utils import jsonHelper, assetFunctions, messageBox, myWidget


# from imp import reload
# reload(myWidget)


class AssetToolsUI(QtWidgets.QWidget):
    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')

    jsonPath = 'Y:/ACTools/CGTools/scripts/AssetsManagerForMaya'

    def __init__(self, isSQL=True,
                 user="",
                 password=""):
        super(AssetToolsUI, self).__init__()

        self.isSQL = isSQL
        self.host = "10.0.203.34"
        self.user = user
        self.password = password

        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)
        self.tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))
        f = QtCore.QFile('%s/ui/assetTools.ui' % self.scriptsPath)
        f.open(QtCore.QFile.ReadOnly)
        loader = QtUiTools.QUiLoader().load(f)
        self.ui = loader
        f.close()

        self.isList = False
        self.isAction = False

        self.__fileTypeFolderDict = {'mod': 'Mod',
                                     'render': 'Render',
                                     'all_rig': 'Rig',
                                     'hi_rig': 'Rig',
                                     'low_rig': 'Rig',
                                     'xgen': 'xgenFile',
                                     'AD': 'Assembly',
                                     'OAT': 'Rig'}
        self.currentAssetData = {}
        self.update_asset_thread = myWidget.MyThread()
        self.update_asset_thread.signal.connect(lambda: self.listWidgetAddItems())
        self.update_action_thread = myWidget.MyThread()
        self.update_action_thread.signal.connect(lambda: self.listWidgetAddActionItems())

        self.firstView()
        self.init_ui_thread = myWidget.MyThread()
        self.init_ui_thread.signal.connect(self.init_ui)
        self.init_ui_thread.start()
        self.init_ui_thread.finished.connect(lambda: self.listWidgetAddItems(self.getItemsFromSQL()))

    def init_ui(self):
        self.layout().addWidget(self.ui)
        # self.getStyleSheet()

        '''左侧边栏'''
        self.ui.project_comb.currentIndexChanged.connect(self.projectChanged)
        self.ui.type_listWgt.itemSelectionChanged.connect(self.typeChanged)

        '''上侧小按钮栏'''
        self.ui.back_bttn.setIcon(QtGui.QIcon('%s/icon/back.png' % self.scriptsPath))
        self.ui.back_bttn.clicked.connect(self.backToMainWgt)
        self.ui.back_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
        self.ui.displayThumb_bttn.clicked.connect(self.viewThumbnailChange)
        self.ui.displayThumb_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.itemSize_Slider.valueChanged.connect(self.itemSizeSliderChanged)
        self.ui.itemSize_Slider.sliderReleased.connect(self.itemSizeSliderReleased)
        self.ui.download_Bttn.setIcon(QtGui.QPixmap('%s/icon/download.png' % self.scriptsPath))
        self.ui.download_Bttn.clicked.connect(self.download_CGTicon_to_localTemp)
        self.ui.download_Bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.refresh_Bttn.setIcon(QtGui.QPixmap('%s/icon/refresh.png' % self.scriptsPath))
        self.ui.refresh_Bttn.clicked.connect(self.refresh_asset)
        self.ui.refresh_Bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.key_line.returnPressed.connect(self.search_asset)
        self.ui.key_line.addAction(QtGui.QIcon('%s/icon/search.png' % self.scriptsPath),
                                   QtWidgets.QLineEdit.LeadingPosition)

        '''主界面栏'''
        self.ui.main_listWgt = myWidget.MainQListWiget()

        self.ui.main_listWgt.itemSelectionChanged.connect(self.listWidgetItemChanged)
        self.ui.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.main_listWgt.customContextMenuRequested.connect(self.show_menu)

        self.ui.verticalLayout_3.addWidget(self.ui.main_listWgt)
        self.ui.mainWindow_splitter.setSizes([120, 500, 300])
        self.ui.mainWindow_splitter.setStretchFactor(0, False)
        self.ui.mainWindow_splitter.setStretchFactor(1, True)
        self.ui.mainWindow_splitter.setStretchFactor(2, False)

        '''右侧属性栏'''
        self.ui.arrow_Bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.tag_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.favor_bttn.setStyleSheet("border-style: flat; background: transparent;")

        self.ui.Preview_label = myWidget.PreviewLabel(self.ui.frams_lineEdit)
        self.ui.verticalLayout_Preview.addWidget(self.ui.Preview_label)
        self.playerSet()
        self.ui.import_bttn.clicked.connect(self.importFile)

    def getStyleSheet(self):
        style_sheet_path = '%s/qss/UE5.qss' % self.scriptsPath
        with open(style_sheet_path) as (file):
            str = file.read()
        self.setStyleSheet(str)

    def projectSetting(self):
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % self.jsonPath)
        return data

    def rememberSettings(self):
        settings = QtCore.QSettings('AssetsUE', 'AssetsUESettings')
        settings.setValue('isList', self.isList)
        settings.setValue('thumbSize', self.ui.itemSize_Slider.value())
        settings.setValue('project', self.ui.project_comb.currentIndex())
        settings.setValue('typ', self.ui.type_listWgt.currentRow())

    def readSettings(self):
        settings = QtCore.QSettings('AssetsUE', 'AssetsUESettings')
        isList = settings.value('isList')
        thumbSize = settings.value('thumbSize')
        project = settings.value('project')
        typ = settings.value('typ')

        if isList is not None:
            if isList == 'true':
                self.isList = True
            else:
                self.isList = False

        return thumbSize, project, typ

    def firstView(self):
        """ 初显示 """
        self.update_project()
        self.update_type()

        thumbSize, project, typ = self.readSettings()
        if thumbSize is not None:
            self.ui.itemSize_Slider.setValue(thumbSize)
        if project is not None:
            self.ui.project_comb.setCurrentIndex(project)
        if typ is not None:
            self.ui.type_listWgt.setCurrentRow(typ)
        else:
            self.ui.type_listWgt.setCurrentRow(0)

    def update_project(self):
        self.ui.project_comb.addItems(self.projectSetting()['projects'])

    def update_type(self):
        """
        设置type显示
        """
        for i in self.projectSetting()['type']:
            item = QtWidgets.QListWidgetItem()
            item.setText(str(i))
            icon = QtGui.QIcon()
            pixmap = myWidget.Pixmap('%s/icon/folder.svg' % self.scriptsPath)
            pixmap.setColor(QtGui.QColor("#b3b3b3"))
            icon.addPixmap(pixmap, QtGui.QIcon.Normal, QtGui.QIcon.Off)
            item.setIcon(icon)
            self.ui.type_listWgt.addItem(item)

    def projectChanged(self):
        self.rememberSettings()
        self.listWidgetAddItems(self.getItemsFromSQL())

    def typeChanged(self):
        self.rememberSettings()
        self.listWidgetAddItems(self.getItemsFromSQL())

    def getCurrentItemsData(self):
        """
        获取当前图标信息
        :return:__item, __fileType, __folder
        """
        __item = self.ui.main_listWgt.selectedItems()
        __fileType = self.ui.fileType_bttnGroup.checkedButton().text()
        __folder = self.__fileTypeFolderDict[__fileType]
        if not __item:
            return
        return __item, __fileType, __folder

    def openDir(self, dir_path):
        """
        'Show in Explorer'打开文件夹
        """
        folder_info = QtCore.QFileInfo(dir_path)
        if folder_info.exists():
            QtGui.QDesktopServices.openUrl(dir_path)
        else:
            self.infoMsg('warning', 'Can not find {0}'.format(dir_path))

    def get_viewThumbnail_bttn(self):
        """
        displayThumb_bttn  的初显示状态
        """
        if self.isList:
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("缩略图显示")
        else:
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("表单显示")

    def backToMainWgt(self):
        """返回主面板"""
        self.ui.Preview_label.clear()
        self.ui.Play_toolBttn.setEnabled(False)
        self.ui.firstFrame_toolBttn.setEnabled(False)
        self.ui.prevFrame_toolBttn.setEnabled(False)
        self.ui.nextFrame_toolBttn.setEnabled(False)
        self.ui.lastFrame_toolBttn.setEnabled(False)
        self.update_asset()

    def viewThumbnailChange(self):
        """ 切换  缩略图/表单  显示 """
        isAction = self.isAction
        if self.isList:
            '''如果list则切换icon显示'''
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("表单显示")
            self.isList = False
            self.ui.main_listWgt.setIsList(self.isList)
            self.ui.main_listWgt.setIconMode()
            if not isAction:
                self.update_asset()
            else:
                self.update_action()
        else:
            '''否则切换list显示'''
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("缩略图显示")
            self.isList = True
            self.ui.main_listWgt.setIsList(self.isList)
            self.ui.main_listWgt.setListMode()
            if not isAction:
                self.update_asset()
            else:
                self.update_action()

        self.rememberSettings()

    def itemSizeSliderChanged(self):
        """ 设置item尺寸 """
        itemSize = self.ui.itemSize_Slider.value()
        if self.isList:
            pass
        else:
            self.ui.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.ui.main_listWgt.setGridSize(QtCore.QSize(itemSize + 10, itemSize + 50))

    def itemSizeSliderReleased(self):
        self.rememberSettings()

    def download_CGTicon_to_localTemp(self):
        """
        下载CGT的icon到本地
        """
        import cgtw2
        t_tw = cgtw2.tw()
        type, project, path = self.getTypeAndProject()
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
        self.listWidgetAddItems_CGT_Fast(self.ui.main_listWgt, project, type, keyWords="")

    def loadingText(self):
        # print("loadingGif()")
        text = "Loading ... "
        self.ui.main_listWgt.clear()
        item = QtWidgets.QListWidgetItem()
        item.setText(text)
        self.ui.main_listWgt.addItem(item)

    def update_asset(self):
        """
        更新资产的多线程
        """
        print("update_asset")
        type, project, path = self.getTypeAndProject()
        if os.path.exists(path):
            self.infoMsg("info", "Loading...")
            self.update_asset_thread.start()
        else:
            self.ui.main_listWgt.clear()

    def refresh_asset(self):
        if not self.isAction:
            self.listWidgetAddItems(self.getItemsFromSQL())
        else:
            self.update_action()

    def search_asset(self):
        """ 搜索 """
        self.listWidgetAddItems()
        # keyWords = self.ui.key_line.text()
        # type, project, path = self.getTypeAndProject()
        # if not self.ui.searchAll_cBox.isChecked():
        #     self.update_asset_thread = myWidget.MyThread()
        #     self.update_asset_thread.signal.connect(
        #         lambda: self.listWidgetAddItems_CGT_Search(project, type, keyWords))
        #     self.loadingText()
        #     self.update_asset_thread.start()
        # else:
        #     for i in self.projectSetting()['projects']:
        #         self.update_action_thread = myWidget.MyThread()
        #         self.update_action_thread.signal.connect(lambda: self.listWidgetAddItems_CGT(i, type, keyWords))
        #         self.loadingText()
        #         self.update_action_thread.start()

    def update_action(self):
        """ 更新动作库的多线程 """
        currentSelected = self.ui.main_listWgt.selectedItems()
        if currentSelected:
            self.currentAssetData = currentSelected[0].data(QtCore.Qt.UserRole)
        item_data = self.currentAssetData
        type, project, path = self.getTypeAndProject()
        if os.path.exists(path):
            self.loadingText()
            self.update_action_thread.start()
        else:
            self.ui.main_listWgt.clear()

    def getItemsFromSQL(self):
        _type, _project, path = self.getTypeAndProject()
        if self.isSQL:
            return self.get_database(_project, _type)

    def get_database(self, _project, _type):
        """ 得到asset数据 """
        conn = None
        cur = None
        get_script = ''' 
             SELECT "asset.date", "asset.name", "asset.zh_name", "asset.mod_artist", "asset.mod_status", 
             "asset.rig_artist", "asset.rig_status", "asset.icon" 
             FROM public."asset"
             WHERE
             "asset.type" = '%s';
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
    #
    # def getItemsDictFromCGTW(self, keyWords=u""):
    #     """
    #     从CGTeamWork获取字典
    #     :param keyWords:
    #     :return:{text:icon}
    #     """
    #     import cgtw2
    #     t_tw = cgtw2.tw()
    #     type, project, path = self.getTypeAndProject()
    #     TW_proj = str(self.projectSetting()['projectdiction'][project])
    #     t_asset_ids = t_tw.info.get_id(TW_proj, 'asset', [['asset.maya', '=', u"完成"],
    #                                                       'and', ['asset.assetstapy', '=', type]])
    #     TW_dictionInfo = t_tw.info.get(TW_proj, 'asset', t_asset_ids, ['asset.entity', 'asset.cn_name'])
    #     itemsListDict = {}
    #     for info in TW_dictionInfo:
    #         if info['asset.entity'].lower().find(keyWords.lower()) != -1 or info['asset.cn_name'].find(keyWords) != -1:
    #             icon_path = '{0}/{1}/Icon/{1}.png'.format(path, info['asset.entity'])
    #             bbb = {'role_name': info['asset.entity'], 'project': project, 'type': type,
    #                    'zh_name': info['asset.cn_name'], 'icon_path': icon_path}
    #             itemsListDict.update({info['asset.entity']: bbb})
    #     return itemsListDict

    def listWidgetAddItems(self, new_dict=None):
        """
        设置主面板FBX显示
        """
        self.ui.main_listWgt.clear()
        self.ui.Preview_label.clear()
        self.isAction = False
        keyWords = self.ui.key_line.text()

        start_time = time.time()
        if new_dict:
            self.ui.main_listWgt.setItems(new_dict)
        self.ui.main_listWgt.setIsList(self.isList)
        self.ui.main_listWgt.setItemSize(self.ui.itemSize_Slider.value())
        self.ui.main_listWgt.addItems(keyWords)
        self.ui.main_listWgt.setMode()
        end_time = time.time()
        self.infoMsg("info", "%s items" % (self.ui.main_listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')

    def listWidgetAddActionItems(self, item_data):
        """
        根据选择item，添加主面板Action显示(非多线程)
        """
        selectedPath = item_data['hi_rig'].split('Rig/')[0]
        preview_dir = QtCore.QDir('{0}/Action/ActionFBX'.format(selectedPath))
        self.ui.back_bttn.setEnabled(True)
        self.ui.itemSize_Slider.setEnabled(False)
        self.ui.main_listWgt.clear()
        self.isAction = True
        for i in preview_dir.entryList(['*.fbx'], QtCore.QDir.Files | QtCore.QDir.NoDotAndDotDot):
            item = QtWidgets.QListWidgetItem()
            text = i.split('/')[(-1)].split('.')[0].split('_')[(-1)]
            item.setText(text)
            if self.isList:
                self.ui.main_listWgt.setViewMode(QtWidgets.QListView.ListMode)
                item.setSizeHint(QtCore.QSize(200, 22))
                self.ui.main_listWgt.setGridSize(QtCore.QSize(2000, 25))
                self.ui.main_listWgt.setSpacing(1)
                item.setData(QtCore.Qt.UserRole, item_data)  # 设置信息
                self.ui.main_listWgt.addItem(item)
            else:
                item.setSizeHint(QtCore.QSize(160, 180))
                self.ui.main_listWgt.setGridSize(QtCore.QSize(162, 190))
                item.setTextAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
                widget2 = QtWidgets.QWidget()  # 增加自定义Widget
                widget2.setMaximumSize(QtCore.QSize(160, 160))
                lay = QtWidgets.QVBoxLayout()
                lay.setContentsMargins(0, 0, 0, 0)
                widget2.setLayout(lay)
                label = QtWidgets.QLabel()
                label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
                movPath = '%s/Action/Preview/%s' % (selectedPath, i.replace('.fbx', '.gif'))
                if os.path.isfile(movPath):
                    mov = QtGui.QMovie(movPath)
                    mov.start()
                    label.setMovie(mov)
                    lay.addWidget(label)
                else:
                    icon_path = "%s/icon/Default_action.png" % self.scriptsPath
                    pixmap = QtGui.QPixmap(icon_path)
                    label.setPixmap(pixmap)
                    lay.addWidget(label)
                item.setData(QtCore.Qt.UserRole, item_data)  # 设置信息
                self.ui.main_listWgt.addItem(item)
                self.ui.main_listWgt.setItemWidget(item, widget2)

    def listWidgetItemChanged(self):
        """ 改变item触发：改变预览显示 """
        currentSelected = self.ui.main_listWgt.selectedItems()
        if currentSelected:
            item_data = currentSelected[0].itemData()
            # iconpath = '{0}/{1}/Assets/{2}/{3}/Icon/{3}.png'.format(self.projectSetting()['rootPath'],
            #                                                         item_data['project'], item_data['type'],
            #                                                         item_data['role_name'])
            # localpath = '{0}/{1}/Assets/{2}/{3}.png'.format(self.tempPath, item_data['project'], item_data['type'],
            #                                                 item_data['role_name'])
            # actionpath = '{0}/{1}/Assets/{2}/{3}/Action/Preview/{3}'.format(self.projectSetting()['rootPath'],
            #                                                                 item_data['project'], item_data['type'],
            #                                                                 item_data['role_name']) + "_" + \
            #              currentSelected[0].text() + ".gif"
            '''根据item_data设置预览窗口显示'''
            self.ui.Preview_label.clear()
            self.ui.title_label.clear()
            self.ui.title_label.setText(u"Name： " + item_data[1] + u"\n中文名： " + item_data[2])

            if not self.isAction:
                self.ui.Preview_label.setPreviewPixmap(item_data[7], "pose")
            else:
                self.__playerEnabled(True)
                self.ui.PreviewLabel.setAnim(item_data[7], "animation")

    def show_menu(self, point):
        """
        设置主面板右键菜单
        """
        currentItem = self.ui.main_listWgt.itemAt(point)
        if currentItem is not None:
            menu = QtWidgets.QMenu(self.ui.main_listWgt)
            action_action = QtWidgets.QAction('Action', self)
            show_action = QtWidgets.QAction('Show in Explorer', self)
            show_action.setIcon(QtGui.QIcon("{}/icon/folder_white.png".format(self.scriptsPath)))
            imp_action = QtWidgets.QAction('Import', self)
            impAction_action = QtWidgets.QAction('Import Action', self)

            if self.isAction:
                menu.addAction(impAction_action)
            else:
                menu.addAction(action_action)
                menu.addSeparator()
                menu.addAction(show_action)
                menu.addSeparator()
                menu.addAction(imp_action)

            self.checkDir('Action', currentItem, action_action)  # 检查Action是否为空，决定action_action是否可用

            action_action.triggered.connect(self.update_action)
            show_action.triggered.connect(partial(self.openDir,
                                                  currentItem.itemData()[7].split("/Icon/")[0]))
            imp_action.triggered.connect(self.importFile)
            impAction_action.triggered.connect(self.importActionFile)

            menu.exec_(QtGui.QCursor.pos())
        return

    def checkDir(self, type, item, action):
        """
        检查选择item的路径下是否为空，决定右键菜单显示是否可用
        """
        item_data = item.itemData()
        folder_path = item_data[7].split('/Icon/')[0]
        folder_path = '{0}/{1}'.format(folder_path, type)
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists():
            action.setEnabled(True)
        else:
            action.setEnabled(False)

    # def mainListWgtAddItem(self, project_name, keyWords, type, search):
    #     """
    #     根据搜索词KeyWords设置主面板显示
    #     """
    #     path = '{0}/{1}/{2}/{3}'.format(self.ps_rootPath, project_name, self.ps_assetFolder, type)
    #     dir = QtCore.QDir(path)
    #     for role_name in dir.entryList(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot):
    #         role_rig_dir = QtCore.QDir('{0}/{1}/{2}'.format(path, role_name, 'FBX'))
    #         if role_rig_dir.entryList(['*.fbx'],
    #                                   QtCore.QDir.Files | QtCore.QDir.NoDotAndDotDot) and role_name.lower().find(
    #             keyWords) != -1:
    #             icon_path = '{0}/{1}/{2}/{1}.png'.format(path, role_name, self.ps_iconFolder)
    #             if icon_path.find('/Miarmy/') != -1:
    #                 icon_path = icon_path.replace('/Miarmy', '/Characters/')
    #             if QtCore.QFileInfo(icon_path).exists() is False:
    #                 icon_path = self.ps_defaultIcon
    #             self.itemDetail(icon_path, role_name, project_name, search)

    # def listWidgetAddItems_XXX(self):
    #     """
    #     根据type，project，读取CGT资产数据库，icon优先读取本地数据（快速），设置主面板item显示
    #     """
    #     type, project, path = self.getTypeAndProject()
    #     isCGTW = self.isCGTW()
    #     self.ui.main_listWgt.clear()
    #     self.ui.Preview_label.clear()
    #     self.isAction = False
    #     keyWords = self.ui.key_line.text()
    #     itemsList = self.getItemsListDict(keyWords).keys()
    #     starttime = time.time()
    #     if isCGTW:
    #         for list in itemsList:
    #             role_name = list.split('   /   ')[0]
    #             item = QtWidgets.QListWidgetItem()
    #             item_data = {'role_name': role_name, 'project': project, 'type': type}
    #             item.setData(QtCore.Qt.UserRole, item_data)
    #             item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    #             if self.isList:
    #                 item.setText(list)
    #             else:
    #                 item.setText(list.replace('   /   ', '\n'))
    #                 item.setToolTip(list.replace('   /   ', '\n'))
    #                 icon = QtGui.QIcon()
    #                 icon.addPixmap(QtGui.QPixmap("%s/icon/blank_ch.png" % self.scriptsPath), QtGui.QIcon.Normal,
    #                                QtGui.QIcon.Off)
    #                 item.setIcon(icon)
    #             self.ui.main_listWgt.addItem(item)
    #         self.viewThumbnail()
    #         self.__update_visible_icon()
    #     # self.ui.main_listWgt._sizeSignal.connect(self.mainWightSizeChanged)
    #     endtime = time.time()
    #     self.infoMsg("info", 'Load Completed !  ' +
    #                  "   %s/%s items" % (self.__updatedNum, self.ui.main_listWgt.count()) +
    #                  '   Cost :  %.2f' % (endtime - starttime) + ' sec')

    def listWidgetAddItems_CGT_Search(self, project, type, keyWords):
        """
        根据type，project，读取CGT资产数据库，icon优先读取本地数据（快速），设置主面板item显示
        """
        self.ui.main_listWgt.clear()
        self.ui.Preview_label.clear()
        self.isAction = False
        path = '{0}/{1}/{2}/{3}'.format(self.projectSetting()['rootPath'], project,
                                        self.projectSetting()['assetFolder'], type)
        TW_proj = self.projectSetting()['projectdiction'][project]
        t_asset_ids = t_tw.info.get_id(TW_proj, 'asset',
                                       [['asset.maya', '=', u"完成"], 'and', ['asset.assetstapy', '=', type]])
        TW_dictionInfo = t_tw.info.get(TW_proj, 'asset', t_asset_ids, ['asset.entity', 'asset.cn_name'])
        if self.isList:
            for info in TW_dictionInfo:
                if info['asset.entity'].lower().find(keyWords.lower()) != -1 or info['asset.cn_name'].find(
                        keyWords) != -1:
                    icon_path = 'None'
                    sub_thread = threading.Thread(target=self.addItems_CGT,
                                                  args=(info['asset.entity'], icon_path, info['asset.cn_name']))
                    sub_thread.setDaemon(True)
                    sub_thread.start()
                    sub_thread.join()
        else:
            for info in TW_dictionInfo:
                if info['asset.entity'].lower().find(keyWords.lower()) != -1 or info['asset.cn_name'].find(
                        keyWords) != -1:
                    icon_path = '{0}/{1}/Assets/{2}/{3}.png'.format(self.tempPath, project, type,
                                                                    info['asset.entity'])
                    if QtCore.QFileInfo(icon_path).exists() is False:
                        icon_path = '{0}/{1}/Icon/{1}.png'.format(path, info['asset.entity'])
                        if QtCore.QFileInfo(icon_path).exists() is False:
                            icon_path = self.projectSetting()['defaultIcon']
                    sub_thread = threading.Thread(target=self.addItems_CGT,
                                                  args=(info['asset.entity'], icon_path, info['asset.cn_name']))
                    sub_thread.setDaemon(True)
                    sub_thread.start()
                    sub_thread.join()
        self.viewThumbnail()

    def mainListItemChange(self):
        """
        主面板item改变触发：改变文件类型显示
        """
        currentSelected = self.ui.main_listWgt.selectedItems()
        currentProject = self.ui.project_listWgt.selectedItems()
        rBttn_dict = {'mod': 'self.ui.mod_rBttn', 'hi_rig': 'self.ui.hiRig_rBttn',
                      'low_rig': 'self.ui.lowRig_rBttn',
                      'all_rig': 'self.ui.allRig_rBttn',
                      'render': 'self.ui.render_rBttn',
                      'xgen': 'self.ui.xgen_rBttn',
                      'AD': 'self.ui.ad_rBttn',
                      'OAT': 'self.ui.oat_rBttn'}
        eval(rBttn_dict['mod']).setEnabled(True)
        eval(rBttn_dict['hi_rig']).setEnabled(True)
        eval(rBttn_dict['low_rig']).setEnabled(True)
        eval(rBttn_dict['all_rig']).setEnabled(True)
        eval(rBttn_dict['render']).setEnabled(True)
        eval(rBttn_dict['xgen']).setEnabled(True)
        eval(rBttn_dict['AD']).setEnabled(True)
        eval(rBttn_dict['OAT']).setEnabled(True)
        if len(currentSelected) != 1:
            return
        item_data = currentSelected[0].data(QtCore.Qt.UserRole)
        item_data.pop('icon')
        item_data.pop('role_name')
        item_data.pop('project')
        for type in item_data.keys():
            file_info = QtCore.QFileInfo(item_data[type])
            if file_info.exists() is False:
                eval(rBttn_dict[type]).setEnabled(False)

    def getTypeAndProject(self):
        project = self.ui.project_comb.currentText()
        currentType = self.ui.type_listWgt.selectedItems()
        if not currentType:
            type = 'Default'
            path = None
        else:
            type = str(currentType[0].text())
            path = '%s/%s/%s/%s' % (self.projectSetting()['rootPath'], project,
                                    self.projectSetting()['assetFolder'], type)
        return type, project, path

    def getCurrentData(self):
        currentSelected = self.ui.main_listWgt.selectedItems()
        currentProject = str(self.ui.project_comb.currentText())
        currentType = self.ui.type_listWgt.selectedItems()[0].text()

        return currentSelected, currentProject, currentType

    def playerSet(self):
        sys.path.append('{}/utils'.format(self.scriptsPath))
        import gifplayer
        # reload(gifplayer)
        player = gifplayer.Player()
        player.setPlayButtonState(self.ui.Play_toolBttn)
        '''播放'''
        self.ui.Play_toolBttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
        self.ui.Play_toolBttn.clicked.connect(lambda: player.play(100, self.ui.Play_toolBttn))
        '''起始帧'''
        self.ui.firstFrame_toolBttn.setIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaSkipBackward))
        self.ui.firstFrame_toolBttn.clicked.connect(player.firstFrame)
        '''上一帧'''
        self.ui.prevFrame_toolBttn.setIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaSeekBackward))
        self.ui.prevFrame_toolBttn.clicked.connect(player.prevFrame)
        '''下一帧'''
        self.ui.nextFrame_toolBttn.setIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaSeekForward))
        self.ui.nextFrame_toolBttn.clicked.connect(player.nextFrame)
        '''结束帧'''
        self.ui.lastFrame_toolBttn.setIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaSkipForward))
        self.ui.lastFrame_toolBttn.clicked.connect(player.lastFrame)

    def __playerEnabled(self, value):
        self.ui.Play_toolBttn.setEnabled(value)
        self.ui.firstFrame_toolBttn.setEnabled(value)
        self.ui.prevFrame_toolBttn.setEnabled(value)
        self.ui.nextFrame_toolBttn.setEnabled(value)
        self.ui.lastFrame_toolBttn.setEnabled(value)

    def createRef(self):
        print('TODO: CreateRef')

    def switchRef(self):
        print('TODO: SwitchRef')

    def importAniFBX(self, animation_mesh_fbx, skeleton_path, animations_folder):
        """
        导入动画到指定的骨架网格体
        """
        AF = assetFunctions.AssetFunctions()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list_before = asset_reg.get_assets_by_path(animations_folder)
        try:
            animation_mesh_task = AF.buildImportTask(animation_mesh_fbx, animations_folder,
                                                     AF.buildAnimationImportOptions(skeleton_path))
            AF.executeImportTasks([animation_mesh_task])
        except:
            unreal.log_warning('Can not import {0}'.format(animation_mesh_fbx))

        asset_list_after = asset_reg.get_assets_by_path(animations_folder)
        new_assets = list(set(asset_list_after) - set(asset_list_before))
        for asset in new_assets:
            if asset.asset_class == 'SkeletalMesh':
                unreal.EditorAssetLibrary.delete_asset(asset.object_path)
            print('Deleted asset: ' + str(asset.object_path))
            if asset.asset_class == 'AnimSequence':
                anim = unreal.load_asset(asset.object_path)
                unreal.AnimationLibrary.set_is_root_motion_lock_forced(anim, True)
                print('"Force Root Lock" enabled for: ' + str(asset.object_path))
                unreal.EditorAssetLibrary.save_asset(asset.object_path, only_if_is_dirty=False)

    def importFile(self):
        """
        导入Asset文件到UE
        """
        try:
            currentSelected, currentProject, currentType = self.getCurrentData()
        except:
            self.infoMsg("warning", 'Please select Character!!!')
            return

        for item in currentSelected:
            item_data = item.itemData()
            # print(item_data)
            path = item_data[7].split('/Icon/')[0]
            role_name = item_data[1]
            fbx_path = '%s/FBX/%s.fbx' % (path, role_name)
            # skeleton_path = ('/Game/Assets/{1}/{0}/Maya/{0}_Skeleton').format(role_name, currentType)
            skeleton_path = '/Game/Assets/{1}/{0}/{0}_Skeleton'.format(role_name, currentType)
            # character_folder = ('/Game/Assets/{1}/{0}/Maya/').format(role_name, currentType)
            character_folder = '/Game/Assets/{1}/{0}/'.format(role_name, currentType)
            material_folder = '/Game/Assets/{1}/{0}/Material/'.format(role_name, currentType)
            texture_folder = '/Game/Assets/{1}/{0}/Texture/'.format(role_name, currentType)
            max_folder = '/Game/Assets/{1}/{0}/Max/'.format(role_name, currentType)
            AF = assetFunctions.AssetFunctions()
            asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
            asset_list_before = asset_reg.get_assets_by_path(character_folder)
            animation_mesh_task = AF.buildImportTask(fbx_path, character_folder, AF.buildSkeletalMeshImportOptions())
            AF.executeImportTasks([animation_mesh_task])
            if not unreal.EditorAssetLibrary.does_directory_exist(material_folder):
                unreal.EditorAssetLibrary.make_directory(material_folder)
            if not unreal.EditorAssetLibrary.does_directory_exist(texture_folder):
                unreal.EditorAssetLibrary.make_directory(texture_folder)
            # if not unreal.EditorAssetLibrary.does_directory_exist(max_folder):
            #     unreal.EditorAssetLibrary.make_directory(max_folder)
            self.repathAssets(character_folder)

    def importActionFile(self):
        """
        导入动作库文件到UE
        """
        AF = assetFunctions.AssetFunctions()
        currentSelected = self.ui.main_listWgt.selectedItems()
        # asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        # asset_list_before = asset_reg.get_assets_by_path(animations_folder)
        # print (asset_list_before)
        for item in currentSelected:
            item_data = item.data(QtCore.Qt.UserRole)
            itemText = item.text()
            animation_mesh_ma = item_data['action']  #
            character_name = item_data['action'].split('/Action/')[0].split('/')[-1]
            animation_mesh_fbx = "{0}ActionFBX/{1}_{2}.fbx".format(animation_mesh_ma.split("ActionFile")[0],
                                                                   character_name, itemText)
            print(animation_mesh_fbx)
            type_name = item_data['action'].split('/Action/')[0].split('/')[-2]
            # skeleton_path = ('/Game/Assets/{0}/{1}/Maya/{1}_Skeleton').format(type_name,character_name)
            # animations_folder = ('/Game/Assets/{0}/{1}/Maya/Action').format(type_name,character_name)
            skeleton_path = '/Game/Assets/{0}/{1}/{1}_Skeleton'.format(type_name, character_name)
            print(skeleton_path)
            animations_folder = '/Game/Assets/{0}/{1}/Action'.format(type_name, character_name)
            print(animations_folder)
            self.importAniFBX(animation_mesh_fbx, skeleton_path, animations_folder)
            # animation_mesh_task = AF.buildImportTask(animation_mesh_fbx, animations_folder, AF.buildAnimationImportOptions(skeleton_path))
            # AF.executeImportTasks([animation_mesh_task])

    @staticmethod
    def repathAssets(character_folder):
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
            # print('============================='+assetClassName)
            if assetClassName == 'Material' or assetClassName == 'MaterialInstanceConstant':
                targetPathName = '{0}/Material/{1}.{1}'.format(character_folder.rsplit('/', 1)[0], assetName)
                editorAssetLib.rename_asset(assetPathName, targetPathName)
            elif assetClassName == 'Texture2D':
                targetPathName = '{0}/Texture/{1}.{1}'.format(character_folder.rsplit('/', 1)[0], assetName)
                editorAssetLib.rename_asset(assetPathName, targetPathName)

    def infoMsg(self, icon, text):
        """
        消息栏
        :param icon: "warning", "info", "error"
        :param text: str
        """
        messageBox.show_msg(self.ui.msg_icon_label, icon,
                            self.ui.msg_label, text)

