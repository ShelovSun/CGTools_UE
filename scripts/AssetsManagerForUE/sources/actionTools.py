#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ActionTools Created: 9/5/2021 by Sunxh<175702994@qq.com>
# log: 第一次编写

import os
import sys
import time
import unreal
from imp import reload

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = os.path.join(os.path.dirname(scriptsPath), '..', '..', 'venv', 'Lib', 'site-packages').replace('\\', '/')
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtUiTools
from PySide6 import QtWidgets
from utils import jsonHelper, assetFunctions, messageBox, sequenceplayer, imagesequence, myWidget, style

reload(myWidget)


class ActionToolsUI(QtWidgets.QMainWindow):
    ThreadPool = QtCore.QThreadPool()
    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')
    MYPREFSDIR = os.environ.get('TEMP')  # cmds.internalVar(userPrefDir=True)

    def __init__(self):
        super(ActionToolsUI, self).__init__()

        f = QtCore.QFile('%s/ui/actionTools.ui' % self.scriptsPath)
        f.open(QtCore.QFile.ReadOnly)
        loader = QtUiTools.QUiLoader().load(f)
        self.ui = loader
        f.close()

        self.fbx_item_userRole = QtCore.Qt.UserRole + 1

        self.isList = False
        # self.__showedItemNum = 0
        # self.__updatedNum = 0
        self.DEF_SPACING = 8
        self.DEFAULT_FPS = 30
        self.LOG = ""

        self.ACTION_PATH = self.projectSetting()['rootPath'] + "/StudioLibrary_Ani"
        self._imageSequence = None
        self._current_fram = 0
        self.init_ui_thread = myWidget.MyThread()
        self.init_ui_thread.signal.connect(lambda: self.init_ui())
        self.init_ui_thread.start()
        self.init_ui_thread.finished.connect(lambda: self.listWidgetAddItems())

        self.updateScenethread = myWidget.MyThread()
        self.updateScenethread.signal.connect(lambda: self.listWidgetAddItems())
        # self._worker = myWidget.ImageWorker()
        # self._worker.setAutoDelete(False)
        # self._worker.signals.triggered.connect(self._thumbnailFromImage)
        # self._workerStarted = False

    def init_ui(self):
        self.setCentralWidget(self.ui)
        self.regExp = QtCore.QRegExp('^\\w+$')
        self.validator = QtGui.QRegExpValidator(self.regExp, self)

        self.get_project()

        thumbSize, project, typ = self.readSettings()
        # print(thumbSize, proj, typ)
        if project is not None:
            self.ui.proj_comb.setCurrentIndex(project)
        else:
            self.ui.proj_comb.setCurrentIndex(0)

        self.get_typ()
        if typ is not None:
            self.ui.type_listWgt.setCurrentRow(typ)
        else:
            self.ui.type_listWgt.setCurrentRow(0)

        if thumbSize is not None:
            self.ui.itemSize_Slider.setValue(thumbSize)
        '''左侧边栏'''
        self.ui.proj_comb.currentIndexChanged.connect(self.projectChanged)
        self.ui.type_listWgt.itemSelectionChanged.connect(self.typeChanged)

        '''上侧小按钮栏'''
        self.get_viewThumbnail_bttn()
        self.ui.displayThumb_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
        self.ui.displayThumb_bttn.clicked.connect(self.viewThumbnailChanged)
        self.ui.itemSize_Slider.valueChanged.connect(self.itemSizeSliderChanged)
        self.ui.itemSize_Slider.setToolTip(u"%s" % self.ui.itemSize_Slider.value())
        self.ui.itemSize_Slider.sliderReleased.connect(self.itemSizeSliderReleased)
        self.ui.download_Bttn.setIcon(QtGui.QPixmap('%s/icon/download.png' % self.scriptsPath))
        self.ui.download_Bttn.setStyleSheet("border-style: flat; background: transparent;")
        # self.ui.download_Bttn.clicked.connect(self.download_asset)
        self.ui.refresh_Bttn.setIcon(QtGui.QPixmap('%s/icon/refresh.png' % self.scriptsPath))
        self.ui.refresh_Bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.refresh_Bttn.clicked.connect(self.refresh_asset)
        self.ui.key_line.returnPressed.connect(self.search_asset)
        self.ui.key_line.addAction(QtGui.QIcon('%s/icon/search.png' % self.scriptsPath),
                                   QtWidgets.QLineEdit.LeadingPosition)

        '''主界面栏'''
        self.ui.main_listWgt = myWidget.MainQListWiget()
        self.ui.verticalLayout_main.addWidget(self.ui.main_listWgt)

        self.ui.main_listWgt.itemSelectionChanged.connect(self.mainWightItemChanged)
        self.ui.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.main_listWgt.customContextMenuRequested.connect(self.show_menu)

        self.ui.splitter_2.setSizes([120, 500, 300])
        self.ui.splitter_2.setStretchFactor(0, False)
        self.ui.splitter_2.setStretchFactor(1, True)
        self.ui.splitter_2.setStretchFactor(2, False)

        '''右侧属性栏'''
        self.ui.tag_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.favor_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.PreviewLabel = myWidget.PreviewLabel(self.ui.frams_lineEdit)
        self.ui.verticalLayout_Preview.addWidget(self.ui.PreviewLabel)
        self.ui.PreviewLabel.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.PreviewLabel.customContextMenuRequested.connect(self.show_menu_preview)
        self.playerSet()

        self.ui.actionPublish_bttn.clicked.connect(self.importAction)
        self.ui.actionPublish_bttn.setStyleSheet("QPushButton{background: #b0e600; color: #000000;}")

    def projectSetting(self):
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % self.scriptsPath)
        return data

    def infoMsg(self, icon, text):
        """
        消息栏
        :param icon:
        :param text:
        """
        messageBox.show_msg(self.ui.msg_icon_label, icon,
                            self.ui.msg_label, text)

    def rememberSettings(self):
        """ 记忆窗口设置 """
        settings = QtCore.QSettings('Action', 'ActionSettings')
        settings.setValue('isList', self.isList)
        settings.setValue('thumbSize', self.ui.itemSize_Slider.value())
        settings.setValue('project', self.ui.proj_comb.currentIndex())
        settings.setValue('typ', self.ui.type_listWgt.currentRow())

    def readSettings(self):
        """ 读取QSettings数据 """
        settings = QtCore.QSettings('Action', 'ActionSettings')
        isList = settings.value('isList')
        thumbSize = settings.value('thumbSize')
        project = settings.value('project')
        typ = settings.value('typ')
        isMini = settings.value('isMini')
        if isList is not None:
            if isList == 'true':
                self.isList = True
            else:
                self.isList = False

        return thumbSize, project, typ

    def get_project(self):
        # print("update_project")
        self.ui.proj_comb.addItems(self.projectSetting()['projects'])
        return

    def get_typ(self):
        """ 根据选择的project读取type文件夹 """
        # print("update_type")
        self.ui.type_listWgt.clear()
        project = self.ui.proj_comb.currentText()
        p_path = '{0}/{1}'.format(self.ACTION_PATH, project)
        # print(p_path)
        directory = QtCore.QDir(p_path)
        type_list = directory.entryList(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllEntries,
                                        QtCore.QDir.DirsFirst | QtCore.QDir.IgnoreCase)
        for i in type_list:
            item = QtWidgets.QListWidgetItem()
            item.setText(str(i))
            icon = QtGui.QIcon()
            pixmap = myWidget.Pixmap('%s/icon/folder.svg' % self.scriptsPath)
            pixmap.setColor(QtGui.QColor("#b3b3b3"))
            icon.addPixmap(pixmap, QtGui.QIcon.Normal, QtGui.QIcon.Off)
            item.setIcon(icon)
            # item.setData(self.type_item_userRole, ('{0}/{1}').format(projcet_path, i))  # 写入type items Data
            self.ui.type_listWgt.addItem(item)
        return type_list

    def projectChanged(self):
        self.rememberSettings()
        # self.__showedItemNum = 0
        self.get_typ()
        return str(self.ui.proj_comb.currentText())

    def typeChanged(self):
        self.rememberSettings()
        # self.__showedItemNum = 0
        self.update_asset()
        return str(self.ui.type_listWgt.selectedItems()[0].text())

    def _viewList(self):
        """
        列表显示
        """
        style._viewList(self.ui.main_listWgt)

    def _viewThumb(self):
        """
        缩略图显示
        """
        style._viewThumb(self.ui.main_listWgt, self.ui.itemSize_Slider)

    def get_viewThumbnail_bttn(self):
        """
        displayThumb_bttn  的初显示状态
        """
        style._get_viewThumbnail_bttn(self.ui.displayThumb_bttn, self.isList)

    def viewThumbnailChanged(self):
        """
        切换  缩略图/表单  显示
        """
        isAction = self.isAction
        isList = self.isList
        # self.__showedItemNum = 0
        if isList:
            '''如果list则切换icon显示'''
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("表单显示")
            self.isList = False
            self.ui.main_listWgt.setIsList(self.isList)
            self.ui.main_listWgt.setIconMode()
        else:
            '''否则切换list显示'''
            self.ui.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.ui.displayThumb_bttn.setToolTip("缩略图显示")
            self.isList = True
            self.ui.main_listWgt.setIsList(self.isList)
            self.ui.main_listWgt.setListMode()
        self.rememberSettings()

    def itemSizeSliderChanged(self):
        itemSize = self.ui.itemSize_Slider.value()
        if self.isList:
            pass
        else:
            self.ui.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.ui.main_listWgt.setGridSize(
                QtCore.QSize(itemSize + self.DEF_SPACING, itemSize + self.DEF_SPACING + 40))

    def itemSizeSliderReleased(self):
        self.rememberSettings()
        # if self.__showedItemNum < self.ui.main_listWgt.count():
        #     self.__update_visible_icon()

    def refresh_asset(self):
        self.listWidgetAddItems()

    def search_asset(self):
        """ """
        self.update_asset()

    def update_asset(self):
        """ 根据type，project，设置主面板item显示 """
        # print("update_scene_asset()")
        type, project, path = self.getTypeAndProject()
        # print(path)
        if os.path.exists(str(path)):
            self.infoMsg("info", "Loading...")
            self.updateScenethread.start()
        else:
            self.ui.main_listWgt.clear()

    def getItemsDict(self):
        """
        从CGTW获取字典
        :return:{role_name:{'role_name': xx,
                            'project': xx,
                            'type': xx,
                            'zh_name': xx,
                            'icon_path': xx}}
        """
        __items_dict = {}
        type, project, path = self.getTypeAndProject()
        dir = QtCore.QDir(path)
        for role_name in dir.entryList(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot):
            icon_path = "%s/%s/thumbnail.jpg" % (path, role_name)
            zh_name = self.get_CNname("%s/%s/pose.json" % (path, role_name))
            bbb = {'role_name': role_name, 'project': project, 'type': type,
                   'zh_name': zh_name, 'icon_path': icon_path}
            __items_dict.update({role_name: bbb})

        return __items_dict

    def listWidgetAddItems(self):
        self.ui.main_listWgt.clear()
        keyWords = self.ui.key_line.text()
        start_time = time.time()

        self.ui.main_listWgt.setItemsdict(self.getItemsDict())
        self.ui.main_listWgt.setIsList(self.isList)
        self.ui.main_listWgt.setItemSize(self.ui.itemSize_Slider.value())
        self.ui.main_listWgt.addItems(keyWords)
        self.ui.main_listWgt.setMode()

        end_time = time.time()
        self.infoMsg("info", "%s items" % (self.ui.main_listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')

    def mainWightItemChanged(self):
        """
        改变item触发：改变标题显示，改变预览显示，改变fbx显示
        :return:
        """
        # print("mainWightItemChanged")
        currentSelected = self.ui.main_listWgt.selectedItems()
        if currentSelected:
            self.ui.PreviewLabel.clear()
            self.ui.title_label.clear()
            item_data = currentSelected[0].itemData()
            # print(item_data)
            self.ui.title_label.setText(u"Name： " + item_data['role_name'] + u"\n中文名： " + item_data['zh_name'])
            if item_data['role_name'].endswith('.pose'):
                self.ui.PreviewLabel.setPreviewPixmap(item_data['icon_path'], "pose")
            elif item_data['role_name'].endswith('.anim'):
                self.ui.PreviewLabel.setAnim(item_data['icon_path'], "animation")
                self.get_fbx()

    def get_fbx(self):
        """
        获取路径内的FBX，设置 fbx_listWidget 显示
        :return:
        """
        self.ui.fbx_listWidget.clear()
        ani_dir = QtCore.QDir(self.get_item_path())
        for ani_fbx in ani_dir.entryList(['*.fbx'], QtCore.QDir.Files | QtCore.QDir.NoDotAndDotDot):
            item = QtWidgets.QListWidgetItem()
            item.setCheckState(QtCore.Qt.Checked)
            item.setText(ani_fbx)
            __ch = ani_fbx.split('__')[1].split('_')[0]
            __project = ani_fbx.split('__')[1].split('_')[1]
            namespace = ani_fbx.split('__')[0]
            json = "%s/pose.json" % self.get_item_path()
            __assetPath = self.get_asset_path(json, namespace)
            __type = __assetPath.split('/')[4]
            data = {'role_name': __ch, 'project': __project, 'type': __type,
                    'asset_path': __assetPath,
                    'fbx_path': '{0}/{1}'.format(self.get_item_path(), ani_fbx)}
            item.setData(self.fbx_item_userRole, data)
            self.ui.fbx_listWidget.addItem(item)

    def get_item_path(self):
        currentSelected = self.ui.main_listWgt.selectedItems()
        if currentSelected:
            item_data = currentSelected[0].itemData()
            return "{0}/{1}/{2}/{3}".format(self.ACTION_PATH, item_data['project'],
                                            item_data['type'], item_data['role_name'])

    def get_CNname(self, path):
        """
        从路径下的 pose.json 读取中文名
        :param path: /pose.json
        :return:
        """
        data = jsonHelper.readDictFromFile(path)
        try:
            return data['metadata']['description']
        except:
            return ""

    def get_asset_path(self, path, namespace):
        """
        从路径下的 pose.json 读取 asset 路径
        :param namespace: 资产空间名，例：Amanda_hi_rig1
        :param path: /pose.json
        :return:
        """
        data = jsonHelper.readDictFromFile(path)
        # print(data['metadata']['references'])
        try:
            for i in data['metadata']['references']:
                if i["namespace"] == ":%s" % namespace:
                    return i["filename"]
        except:
            return ""

    def _play(self, path):
        """ Start playing the image sequence movie."""
        movie = None
        if os.path.isfile(path) and path.lower().endswith(".gif"):
            pass
            # self.__playGif(path)
        elif os.path.isdir(path):
            movie = imagesequence.ImageSequence(path)
            movie.frameChanged.connect(self.__frameChanged)
            self._imageSequence = movie
        if movie:
            movie.start()

    def __frameChanged(self, frame=None):
        """ Triggered when the movie object updates to the given frame."""
        isAppRunning = bool(QtWidgets.QApplication.instance())
        if not isAppRunning:
            return
        if self._imageSequence is not None:
            _pixmap = self._imageSequence.currentPixmap()
            fn = self._imageSequence.currentFrameNumber()
            fc = self._imageSequence.frameCount()
            try:
                self.ui.PreviewLabel.setPixmap(_pixmap)
                self.ui.frams_lineEdit.setText(str(fn) + " / " + str(fc))
            except Exception as e:
                print(e)

    def getTypeAndProject(self):
        project = self.ui.proj_comb.currentText()
        try:
            type = self.ui.type_listWgt.selectedItems()[0].text()
        except:
            type = ""
        path = '%s/%s/%s' % (self.ACTION_PATH, project, type)
        return type, project, path

    def listWidgetAddMovItems(self, path):
        """
        将gif显示在Action预览面板
        """
        self.ui.Preview_label.clear()
        preview_dir = QtCore.QDir((path))
        for i in preview_dir.entryList(['ActionGif.gif'], QtCore.QDir.Files | QtCore.QDir.NoDotAndDotDot):
            # item = QtWidgets.QListWidgetItem()
            # item.setSizeHint(QtCore.QSize(150, 180))
            # text = i.split('/')[(-1)].split('.')[0].split('_')[(-1)]
            # item.setText(text)
            # item.setTextAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
            # widget2 = QtWidgets.QWidget()
            # lay = QtWidgets.QHBoxLayout()
            # lay.setContentsMargins(0, 0, 0, 0)
            # widget2.setLayout(lay)
            # label = QtWidgets.QLabel()
            self.player.movie.setFileName('%s/%s' % (path, i))
            self.player.total_frame = self.player.movie.frameCount()
            print("total_frame:", self.player.total_frame)
            # mov = QtGui.QMovie('%s/%s' % (path, i))
            # mov.start()

            # label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
            # label.setMovie(self.player.movie)
            # lay.addWidget(label)
            # self.ui.iconDisplay_listWgt.addItem(item)
            # self.ui.iconDisplay_listWgt.setItemWidget(item, widget2)
            # mov.stop()
            self.ui.Preview_label.setScaledContents(True)
            self.ui.Preview_label.setMovie(self.player.movie)
            self.player.play(100, self.ui.Play_toolBttn)

    def show_menu(self, point):
        """
        main_listWgt 右键菜单
        :param point:
        :return:
        """
        currentItem = self.ui.main_listWgt.itemAt(point)
        # currentItem = self.ui.main_listWgt.selectedItems()[0]
        menu = QtWidgets.QMenu(self.ui.main_listWgt)
        if currentItem is not None:
            show_action = QtWidgets.QAction('Show in Explorer', self)
            show_action.setIcon(QtGui.QIcon("{}/icon/folder_white.png".format(self.scriptsPath)))
            apply_action = QtWidgets.QAction('Import Action', self)

            menu.addAction(show_action)
            menu.addAction(apply_action)

            show_action.triggered.connect(self.openDir)
            menu.addSeparator()
            apply_action.triggered.connect(self.importAction)

            menu.exec_(QtGui.QCursor.pos())
        else:
            refresh_action = QtWidgets.QAction(u'刷新', self)
            refresh_action.setIcon(QtGui.QIcon("{}/icon/refresh.png".format(self.scriptsPath)))
            refresh_action.triggered.connect(self.refresh_asset)

            menu.addAction(refresh_action)

            menu.exec_(QtGui.QCursor.pos())
        return

    def openDir(self):
        """右键打开文件夹"""
        currentSelected = self.ui.main_listWgt.selectedItems()
        item_data = currentSelected[0].itemData()
        folder_path = os.path.dirname(item_data['icon_path'].replace('thumbnail.jpg', ''))
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists():
            QtGui.QDesktopServices.openUrl(folder_path)
        else:
            unreal.log_warning('Can not find {0}'.format(folder_path))

    def importAction(self):
        """
        导入动作
        :return:
        """
        m = self.ui.fbx_listWidget.count()
        for n in range(m):
            if self.ui.fbx_listWidget.item(n).checkState() == QtCore.Qt.Checked:
                data = self.ui.fbx_listWidget.item(n).data(self.fbx_item_userRole)

                fbx_path = data['fbx_path']
                # animation_mesh_fbx = item_data['icon_path'].replace('thumbnail.jpg', 'anim.fbx')

                skeleton_path = '/Game/Assets/{0}/{1}/{1}_Skeleton'.format(data['type'], data['role_name'])
                animations_folder = '/Game/Assets/{0}/{1}/Action'.format(data['type'], data['role_name'])
                self.importAniFBX(fbx_path, skeleton_path, animations_folder)

    @staticmethod
    def importAniFBX(fbx_path, skeleton_path, animations_folder):
        """
        导入动画到指定的骨架网格体
        """
        AF = assetFunctions.AssetFunctions()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list_before = asset_reg.get_assets_by_path(animations_folder)
        try:
            animation_mesh_task = AF.buildImportTask(fbx_path, animations_folder,
                                                     AF.buildAnimationImportOptions(skeleton_path))
            AF.executeImportTasks([animation_mesh_task])
        except:
            unreal.log_warning('Can not import {0}'.format(fbx_path))

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

    def clearWidgetItems(self):
        self.ui.PreviewLabel.clear()
        self.mov.stop()

    def playerSet(self):
        player = sequenceplayer.Player()
        player.setPlayButtonState(self.ui.Play_toolBttn)
        '''播放'''
        self.ui.Play_toolBttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        self.ui.Play_toolBttn.clicked.connect(lambda: player._play(self.ui.Play_toolBttn, self._imageSequence))
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
        '''显示帧数'''
        # self.setFrame()

    def show_menu_preview(self):
        actionPath = r'%s\ActionTools\ActionGif' % self.MYPREFSDIR
        pop = QtWidgets.QMenu(self.ui.PreviewLabel)
        shot = QtWidgets.QAction('Open Local SnapShot', self)
        pop.addAction(shot)
        shot.triggered.connect(lambda: os.startfile(actionPath))
        pop.exec_(QtGui.QCursor.pos())
