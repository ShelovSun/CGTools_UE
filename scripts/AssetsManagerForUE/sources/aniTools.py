#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/10/2020 by Sunxh<175702994@qq.com>

import os, sys, unreal, re

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from PySide6 import QtWidgets, QtUiTools, QtCore, QtGui
from functools import partial
from utils import jsonHelper, assetFunctions, sequenceFunctions
from imp import reload
reload(assetFunctions)
reload(sequenceFunctions)
WINDOW_NAME = 'Animation Tools'

class AniToolsUI(QtWidgets.QWidget):

    def __init__(self):
        super(AniToolsUI, self).__init__()
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)
        self.idea_item_userRole = QtCore.Qt.UserRole
        self.scene_item_userRole = QtCore.Qt.UserRole + 1
        self.fbx_item_userRole = QtCore.Qt.UserRole + 2
        self.init_ui()

    def init_ui(self):
        self.scriptsPath = os.path.split(os.path.realpath(__file__))[0]
        self.scriptsPath = self.scriptsPath.replace('\\', '/')
        self.scriptsPath = self.scriptsPath.replace('sources', 'ui')
        f = QtCore.QFile('%s/aniTools.ui' % self.scriptsPath)
        f.open(QtCore.QFile.ReadOnly)
        loader = QtUiTools.QUiLoader().load(f)
        self.ui = loader
        f.close()
        self.layout().addWidget(self.ui)
        self.setWindowTitle(WINDOW_NAME)
        self.regExp = QtCore.QRegExp('^\\w+$')
        self.validator = QtGui.QRegExpValidator(self.regExp, self)
        self.ui.ani_idea_line.setValidator(self.validator)
        self.getStyleSheet()
        self.update_project()
        self.update_idea()
        self.update_scene()
        self.get_ani_path()
        self.ui.aniPath_cBox.setVisible(False)
        self.ui.ani_project_listWgt.currentItemChanged.connect(self.update_idea)
        self.ui.ani_idea_listWgt.currentItemChanged.connect(self.update_scene)
        self.ui.ani_scene_listWgt.currentItemChanged.connect(self.update_FBX)
        self.ui.ani_idea_line.textChanged.connect(self.idea_search)
        self.ui.ani_scene_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.ani_scene_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.ui.fbxImport_bttn.clicked.connect(self.checkedFbx)

    def readSettings(self):
        settings = QtCore.QSettings('Ani_Tools', 'Ani_Tools_Settings')
        pos = settings.value('pos')
        size = settings.value('size')
        if pos is not None and size is not None:
            self.resize(size)
            self.move(pos)
        return

    def closeEvent(self, event):
        settings = QtCore.QSettings('Ani_Tools', 'Ani_Tools_Settings')
        settings.setValue('pos', self.pos())
        settings.setValue('size', self.size())

    def projectSetting(self):
        scriptsPath = self.scriptsPath.replace('ui', 'config')
        data = jsonHelper.readDictFromFile('%s/projectSetting.json' % scriptsPath)
        return data

    def getStyleSheet(self):
        scriptsPath = self.scriptsPath.replace('ui', 'qss')
        style_sheet_path = '%s/darkOrange.qss' % scriptsPath
        with open(style_sheet_path) as (file):
            str = file.read()
        self.setStyleSheet(str)

    def update_project(self):
        self.ui.ani_project_listWgt.addItems(self.projectSetting()['projects'])
        self.ui.ani_project_listWgt.setCurrentRow(0)

    def get_current_project(self):
        return self.ui.ani_project_listWgt.currentItem().text()

    def update_idea(self):
        self.ui.ani_idea_listWgt.clear()
        current_item = self.get_current_project()
        idea_path = ('{0}/{1}/{2}').format(self.projectSetting()['rootPath'], current_item, 'project')
        directory = QtCore.QDir(idea_path)
        directory.setNameFilters(['2019*', '2020*', '2021*', '2022*'])
        for dir in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
            if dir.find('_') != -1:
                dir_item = QtGui.QListWidgetItem()
                dir_item.setText(dir.split('_', 1)[1])
                dir_item.setData(self.idea_item_userRole, dir)
                self.ui.ani_idea_listWgt.addItem(dir_item)

        self.ui.ani_idea_listWgt.setCurrentRow(0)

    def get_current_idea_data(self):
        if self.ui.ani_idea_listWgt.currentItem():
            return self.ui.ani_idea_listWgt.currentItem().data(self.idea_item_userRole)

    def get_current_idea(self):
        if self.ui.ani_idea_listWgt.currentItem():
            return self.ui.ani_idea_listWgt.currentItem().text()

    def update_scene(self):
        self.ui.ani_scene_listWgt.clear()
        current_project = self.get_current_project()
        current_idea = self.get_current_idea()
        current_idea_data = self.get_current_idea_data()
        scene_path = ('{0}/{1}/{2}/{3}/Ani/AniFile').format(self.projectSetting()['rootPath'], current_project, 'project', current_idea_data)
        directory = QtCore.QDir(scene_path)
        prefix_scene = ('{0}_{1}_S').format(current_project, current_idea)
        for dir in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
            ani_file_path = ('{0}/{1}/{1}_ani.ma').format(scene_path, dir)
            if dir.find(prefix_scene) != -1 and os.path.exists(ani_file_path):
                dir_item = QtGui.QListWidgetItem()
                dir_item.setText(dir.split(prefix_scene)[(-1)])
                dir_item.setData(self.scene_item_userRole, ani_file_path)
                self.ui.ani_scene_listWgt.addItem(dir_item)

        self.ui.ani_scene_listWgt.setCurrentRow(0)

    def get_current_scene(self):
        if self.ui.ani_scene_listWgt.currentItem():
            if self.ui.ani_scene_listWgt.currentItem().text() == '-- Custom --':
                return 'Custom'
            else:
                return ('S{0}').format(self.ui.ani_scene_listWgt.currentItem().text())

    def get_current_scene_data(self):
        if self.ui.ani_scene_listWgt.currentItem():
            if self.ui.ani_scene_listWgt.currentItem().text() == '-- Custom --':
                return 'Custom'
            else:
                return self.ui.ani_scene_listWgt.currentItem().data(self.scene_item_userRole)

    def update_ani_name_example(self):
        current_project = self.get_current_project()
        current_idea = self.get_current_idea()
        current_scene = self.get_current_scene()
        ani_example_name = ('{0}_{1}_{2}_ani.ma').format(current_project, current_idea, current_scene)
        self.ui.ani_name_example_lable.setText(ani_example_name)

    def idea_search(self, text):
        if text:
            find_items = self.ui.ani_idea_listWgt.findItems(('*{0}*').format(text), QtCore.Qt.MatchWildcard)
            for i in range(self.ui.ani_idea_listWgt.count()):
                item = self.ui.ani_idea_listWgt.item(i)
                item.setHidden(True)

            for j in find_items:
                j.setHidden(False)

        else:
            for i in range(self.ui.ani_idea_listWgt.count()):
                item = self.ui.ani_idea_listWgt.item(i)
                item.setHidden(False)

    def get_ani_path(self):
        current_idea = self.get_current_idea()
        current_scene = self.get_current_scene()
        if current_idea is None or current_scene is None:
            animations_folder = '/Game/.../...'
        else:
            animations_folder = ('/Game/Project/{0}/Animations/{1}').format(current_idea, current_scene)
        self.ui.aniPath_label.setText(animations_folder)
        return

    def get_selected_path(self):
        pass

    def _get_curennt_data(self):
        current_project = self.get_current_project()
        current_idea = self.get_current_idea()
        current_idea_data = self.get_current_idea_data()
        current_scene = self.get_current_scene()
        current_scene_data = self.get_current_scene_data()
        return (current_project, current_idea, current_idea_data, current_scene, current_scene_data)

    def update_FBX(self, item):
        self.ui.aniAST_listWgt.clear()
        try:
            ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
            AniFBX_path = ani_folder_path.replace('/AniFile/', '/AniFBX/')
            AniCamera_path = ani_folder_path.replace('/AniFile/', '/AniCamera/')
            self.getFbx(AniFBX_path, item)
        except:
            pass

        self.get_ani_path()

    def getFbx(self, path, item):
        folder_info = QtCore.QFileInfo(path)
        if folder_info.exists():
            fbx_list = os.listdir(path)
            for i in fbx_list:
                if i.endswith('.fbx'):
                    item = QtGui.QListWidgetItem()
                    item.setCheckState(QtCore.Qt.Checked)
                    item.setText(i)
                    item.setData(self.fbx_item_userRole, ('{0}/{1}').format(path, i))
                    self.ui.aniAST_listWgt.addItem(item)

    def checkedFbx(self):
        m = self.ui.aniAST_listWgt.count()
        current_idea = self.get_current_idea()
        current_scene = self.get_current_scene()
        animations_folder = ('/Game/Project/{0}/Animations/{1}').format(current_idea, current_scene)
        reg = '([A-Za-z0-9]+_){3}_([A-Za-z0-9]+_){2}AST'
        assetName_list = self.get_asset_list(animations_folder)
        NotFindSkeleton = []
        NotFindFBX = []
        for i in range(m):
            if self.ui.aniAST_listWgt.item(i).checkState() == QtCore.Qt.Checked:
                fbx_path = self.ui.aniAST_listWgt.item(i).data(self.fbx_item_userRole)
                itemText = self.ui.aniAST_listWgt.item(i).text()
                assetNewName = ('{0}_{1}_{2}').format(current_idea, current_scene, itemText.split('__')[0])
                if assetNewName in assetName_list:
                    continue
                elif fbx_path.find('AniFBX') != -1 and re.match(reg, itemText):
                    character_name = itemText.split('__')[1].split('_')[0]
                    character_skeleton_path = ('/Game/Assets/Characters/{0}/Maya/{0}_Skeleton').format(character_name)
                    prop_skeleton_path = ('/Game/Assets/Props/{0}/Maya/{0}_Skeleton').format(character_name)
                    if unreal.EditorAssetLibrary.does_asset_exist(character_skeleton_path):
                        self.importAniFBX(fbx_path, character_skeleton_path, animations_folder)
                    elif unreal.EditorAssetLibrary.does_asset_exist(prop_skeleton_path):
                        self.importAniFBX(fbx_path, prop_skeleton_path, animations_folder)
                    else:
                        NotFindSkeleton.append(character_name)
                else:
                    NotFindFBX.append(itemText)
                    character_name = itemText

        self.renameAniFBX(animations_folder)
        if NotFindSkeleton:
            for name in NotFindSkeleton:
                unreal.log_warning(('Can not find {0} skeleton').format(name))

        if NotFindFBX:
            for name in NotFindFBX:
                unreal.log_warning(('Please check {0} ').format(name))

        if self.ui.fbxImport_cBox.isChecked():
            AF = assetFunctions.AssetFunctions()
            sequence_path = animations_folder
            if unreal.EditorAssetLibrary.does_asset_exist(asset_path=sequence_path):
                unreal.EditorAssetLibrary.delete_asset(sequence_path)
            AF.createGenericAsset(sequence_path, True, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
            asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
            asset_list_new = asset_reg.get_assets_by_path(sequence_path)
            for asset in asset_list_new:
                if asset.asset_class == 'AnimSequence':
                    sequenceFunctions.addSkeletalAnimationTrack(sequence_path, asset.object_path)

            self.add_to_folder(sequence_path)
            ani_camera_folder = fbx_path.rsplit('/', 1)[0].replace('AniFBX', 'AniCamera')
            if os.path.exists(ani_camera_folder):
                for i in os.listdir(ani_camera_folder):
                    if i.endswith('.fbx'):
                        cameraFBX_path = '%s/%s' % (ani_camera_folder, i)
                        sequenceFunctions.addCamera(sequence_path, cameraFBX_path)

    def get_asset_list(self, animations_folder):
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        assetName_list = []
        for asset in asset_list:
            assetName_list.append(str(asset.object_path).split('.')[1])

        return assetName_list

    def add_to_folder(self, sequence_path):
        sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
        animation_folder = sequence_asset.add_root_folder_to_sequence('Animations')
        animation_folder.set_folder_color(unreal.Color(255, 50, 0, 255))
        spawn_list = sequence_asset.get_spawnables()
        for i in spawn_list:
            animation_folder.add_child_object_binding(i)

    def importAniFBX(self, animation_mesh_fbx, skeleton_path, animations_folder):
        AF = assetFunctions.AssetFunctions()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list_before = asset_reg.get_assets_by_path(animations_folder)
        try:
            animation_mesh_task = AF.buildImportTask(animation_mesh_fbx, animations_folder, AF.buildAnimationImportOptions(skeleton_path))
            AF.executeImportTasks([animation_mesh_task])
        except:
            unreal.log_warning(('Can not import {0}').format(animation_mesh_fbx))

        asset_list_after = asset_reg.get_assets_by_path(animations_folder)
        new_assets = list(set(asset_list_after) - set(asset_list_before))
        for asset in new_assets:
            if asset.asset_class == 'SkeletalMesh':
                unreal.EditorAssetLibrary.delete_asset(asset.object_path)
            print ('Deleted asset: ' + str(asset.object_path))
            if asset.asset_class == 'AnimSequence':
                anim = unreal.load_asset(asset.object_path)
                unreal.AnimationLibrary.set_is_root_motion_lock_forced(anim, True)
                print ('"Force Root Lock" enabled for: ' + str(asset.object_path))
                unreal.EditorAssetLibrary.save_asset(asset.object_path, only_if_is_dirty=False)

    def renameAniFBX(self, animations_folder):
        current_idea = self.get_current_idea()
        current_scene = self.get_current_scene()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        editorAssetLib = unreal.EditorAssetLibrary()
        for asset in asset_list:
            if asset.asset_class == 'AnimSequence':
                assetPathName = str(asset.object_path)
                folderNameList = assetPathName.split('/')
                if assetPathName.split('.')[1].find(('{0}_{1}_').format(current_idea, current_scene)) != -1:
                    continue
                else:
                    assetNewName = ('{0}_{1}_{2}').format(folderNameList[3], folderNameList[5], folderNameList[6].split('.')[0].split('__')[0])
                    targetPathName = ('{0}/{1}.{1}').format(assetPathName.rsplit('/', 1)[0], assetNewName)
                    editorAssetLib.rename_asset(assetPathName, targetPathName)

    def deleteAniFBX(self, animations_folder):
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        editorAssetLib = unreal.EditorAssetLibrary()
        for asset in asset_list:
            editorAssetLib.delete_asset(asset.object_path)

    def createLevelSequence(self):
        pass

    def show_menu(self, point):
        self.currentItem = self.ui.ani_scene_listWgt.itemAt(point)
        if self.currentItem is not None and self.currentItem.text() != '-- Custom --':
            pop = QtGui.QMenu(self.ui.ani_scene_listWgt)
            alembic_action = QtGui.QAction('Alembic', self)
            ani_action = QtGui.QAction('Ani', self)
            camera_action = QtGui.QAction('Camera', self)
            fbx_action = QtGui.QAction('FBX', self)
            playblast_action = QtGui.QAction('Playblast', self)
            pop.addAction(alembic_action)
            pop.addAction(ani_action)
            pop.addAction(camera_action)
            pop.addAction(fbx_action)
            pop.addAction(playblast_action)
            self.checkDir('AniAlembic', self.currentItem, alembic_action)
            self.checkDir('AniFile', self.currentItem, ani_action)
            self.checkDir('AniCamera', self.currentItem, camera_action)
            self.checkDir('AniFBX', self.currentItem, fbx_action)
            self.checkDir('AniPlayblast', self.currentItem, playblast_action)
            alembic_action.triggered.connect(partial(self.openDir, 'AniAlembic', self.currentItem))
            ani_action.triggered.connect(partial(self.openDir, 'AniFile', self.currentItem))
            camera_action.triggered.connect(partial(self.openDir, 'AniCamera', self.currentItem))
            fbx_action.triggered.connect(partial(self.openDir, 'AniFBX', self.currentItem))
            playblast_action.triggered.connect(partial(self.openDir, 'AniPlayblast', self.currentItem))
            pop.exec_(QtGui.QCursor.pos())
        return

    def openDir(self, type, item):
        ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
        folder_path = ani_folder_path.replace('/AniFile/', ('/{0}/').format(type))
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists:
            QtGui.QDesktopServices.openUrl(folder_path)

    def checkDir(self, type, item, action):
        ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
        folder_path = ani_folder_path.replace('/AniFile/', ('/{0}/').format(type))
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists():
            action.setEnabled(True)
        else:
            action.setEnabled(False)


APP = None
if not QtWidgets.QApplication.instance():
    APP = QtWidgets.QApplication(sys.argv)

def showWindow():
    global win
    try:
        win.close()
    except:
        pass

    win = AniToolsUI()
    win.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    win.show()