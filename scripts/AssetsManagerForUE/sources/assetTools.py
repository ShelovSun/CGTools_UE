#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <AssetsManager_UE>Created: 19/10/2020 by Sunxh<175702994@qq.com>
# UI 已由 .ui + QUiLoader 改为纯 Python 代码搭建（build_ui），彻底绕开 QtUiTools 冷启动。

import os
import sys
import time
import unreal
import psycopg2

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from PySide6 import QtWidgets, QtCore, QtGui

from functools import partial
from utils import jsonHelper, assetFunctions, messageBox, myWidget
from utils.fbxpreview.am_previewGLWidget import PreviewGLWidget
from utils.fbxpreview.am_actionWidget import AssetActionWidget

_FLAT = "border-style: flat; background: transparent;"


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
        self.tempPath = "{}/AssetsManagerIconTemp".format(os.environ.get('TEMP'))

        self.isList = False
        self._current_sort = (0, True)  # 默认排序：按日期(列0)降序(reverse=True)，最新在前

        self.update_asset_thread = myWidget.MyThread()
        self.update_asset_thread.signal.connect(lambda: self.listWidgetAddItems())

        # 同步搭建界面（纯控件、无 I/O，秒级）→ 窗口一显示即最终布局，不闪。
        self.build_ui()
        # 填充项目/类型并恢复上次选择（build_ui 已连信号，这里在 firstView 内屏蔽选择信号，避免触发 DB 查询）。
        self.firstView()
        # 数据加载(含 DB 查询，可能较慢)延迟到窗口显示后执行，避免卡住启动。
        self.init_ui_thread = myWidget.MyThread()
        self.init_ui_thread.signal.connect(lambda: self.listWidgetAddItems(self.getItemsFromSQL()))
        self.init_ui_thread.start()

    # ------------------------------------------------------------------ UI 搭建
    def build_ui(self):
        """纯代码搭建界面：左(项目下拉+类型列表) | 中(工具栏+缩略图列表) | 右(FBX预览+动作库+Import) + 底部状态栏。"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        self.mainWindow_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.mainWindow_splitter.setHandleWidth(3)
        self.mainWindow_splitter.setChildrenCollapsible(False)
        root.addWidget(self.mainWindow_splitter, 1)

        # ---- 左栏 ----
        left = QtWidgets.QWidget()
        leftV = QtWidgets.QVBoxLayout(left)
        leftV.setContentsMargins(0, 0, 0, 0)
        leftV.setSpacing(2)
        projRow = QtWidgets.QHBoxLayout()
        projRow.addWidget(QtWidgets.QLabel(u"项目:"))
        self.project_comb = QtWidgets.QComboBox()
        self.project_comb.setMinimumWidth(50)
        projRow.addWidget(self.project_comb, 1)
        leftV.addLayout(projRow)
        self.type_listWgt = QtWidgets.QListWidget()
        self.type_listWgt.setSortingEnabled(False)
        self.type_listWgt.setSpacing(3)
        leftV.addWidget(self.type_listWgt, 1)
        self.mainWindow_splitter.addWidget(left)

        # ---- 中栏 ----
        mid = QtWidgets.QWidget()
        midV = QtWidgets.QVBoxLayout(mid)
        midV.setContentsMargins(0, 0, 0, 0)
        midV.setSpacing(3)
        tool = QtWidgets.QHBoxLayout()
        tool.setSpacing(2)

        self.back_bttn = self._toolBtn('back.png', u"后退")
        self.back_bttn.setEnabled(False)
        tool.addWidget(self.back_bttn)
        self.displayThumb_bttn = self._toolBtn('display_list.png', u"表单显示")
        tool.addWidget(self.displayThumb_bttn)

        self.itemSize_Slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.itemSize_Slider.setMinimum(10)
        self.itemSize_Slider.setMaximum(200)
        self.itemSize_Slider.setValue(120)
        self.itemSize_Slider.setMaximumWidth(250)
        self.itemSize_Slider.setToolTip(u"缩放图标")
        tool.addWidget(self.itemSize_Slider)

        self.download_Bttn = self._toolBtn('download.png', u"下载资产到本地")
        tool.addWidget(self.download_Bttn)
        self.refresh_Bttn = self._toolBtn('refresh.png', u"刷新")
        tool.addWidget(self.refresh_Bttn)

        self.sort_bttn = QtWidgets.QToolButton()
        self.sort_bttn.setIcon(QtGui.QIcon('%s/icon/sort.png' % self.scriptsPath))
        self.sort_bttn.setToolTip(u"排序")
        self.sort_bttn.setStyleSheet(_FLAT)
        tool.addWidget(self.sort_bttn)

        self.key_line = QtWidgets.QLineEdit()
        self.key_line.setClearButtonEnabled(True)
        self.key_line.setPlaceholderText(u"Search...")
        self.key_line.addAction(QtGui.QIcon('%s/icon/search.png' % self.scriptsPath),
                                QtWidgets.QLineEdit.LeadingPosition)
        tool.addWidget(self.key_line, 1)

        midV.addLayout(tool)
        self.main_listWgt = myWidget.MainQListWiget()
        # 关掉 Qt 按 item 文字(资产名)的自动排序，否则会覆盖排序菜单选择的自定义顺序(日期/状态等)
        self.main_listWgt.setSortingEnabled(False)
        midV.addWidget(self.main_listWgt, 1)
        self.mainWindow_splitter.addWidget(mid)

        # ---- 右栏：FBX 三维预览 + 动作库 + 底部 Import ----
        right = QtWidgets.QWidget()
        rightV = QtWidgets.QVBoxLayout(right)
        rightV.setContentsMargins(0, 0, 0, 0)
        rightV.setSpacing(2)
        self.preview_wgt = PreviewGLWidget(isPlayer=False)
        self.preview_wgt.setMinimumHeight(350)
        rightV.addWidget(self.preview_wgt)
        self.action_wgt = AssetActionWidget()
        self.action_wgt.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        rightV.addWidget(self.action_wgt, 1)
        self.import_bttn = QtWidgets.QPushButton("Import")
        self.import_bttn.setMinimumHeight(30)
        rightV.addWidget(self.import_bttn)
        self.mainWindow_splitter.addWidget(right)

        self.mainWindow_splitter.setSizes([120, 500, 350])
        self.mainWindow_splitter.setStretchFactor(0, 0)
        self.mainWindow_splitter.setStretchFactor(1, 1)
        self.mainWindow_splitter.setStretchFactor(2, 0)

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
        root.addLayout(msgRow)

        # ---- 信号连接 ----
        self.project_comb.currentIndexChanged.connect(self.projectChanged)
        self.type_listWgt.itemSelectionChanged.connect(self.typeChanged)
        self.back_bttn.clicked.connect(self.backToMainWgt)
        self.displayThumb_bttn.clicked.connect(self.viewThumbnailChange)
        self.itemSize_Slider.valueChanged.connect(self.itemSizeSliderChanged)
        self.itemSize_Slider.sliderReleased.connect(self.itemSizeSliderReleased)
        self.download_Bttn.clicked.connect(self.download_CGTicon_to_localTemp)
        self.refresh_Bttn.clicked.connect(self.refresh_asset)
        self.sort_bttn.clicked.connect(self.sort_asset_ui)
        self.key_line.returnPressed.connect(self.search_asset)
        self.main_listWgt.itemSelectionChanged.connect(self.listWidgetItemChanged)
        self.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.main_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.action_wgt.actionActivated.connect(self.on_action_selected)
        self.action_wgt.importActionRequested.connect(self.importActionFile)  # 右键"导入动作"
        self.import_bttn.clicked.connect(self.importFile)

    def _toolBtn(self, icon_name, tip):
        """工具栏小按钮：25x25、扁平透明、22 图标。"""
        b = QtWidgets.QPushButton()
        b.setFixedSize(25, 25)
        b.setIconSize(QtCore.QSize(22, 22))
        b.setIcon(QtGui.QIcon('%s/icon/%s' % (self.scriptsPath, icon_name)))
        b.setToolTip(tip)
        b.setStyleSheet(_FLAT)
        return b

    # ------------------------------------------------------------------ 数据/逻辑
    def projectSetting(self):
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % self.jsonPath)
        return data

    def rememberSettings(self):
        settings = QtCore.QSettings('AssetsUE', 'AssetsUESettings')
        settings.setValue('isList', self.isList)
        settings.setValue('thumbSize', self.itemSize_Slider.value())
        settings.setValue('project', self.project_comb.currentIndex())
        settings.setValue('typ', self.type_listWgt.currentRow())

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
        """ 初显示：填充项目/类型并恢复上次选择。屏蔽选择信号，避免启动时同步触发 DB 查询。"""
        self.project_comb.blockSignals(True)
        self.type_listWgt.blockSignals(True)
        try:
            self.update_project()
            self.update_type()
            thumbSize, project, typ = self.readSettings()
            if thumbSize is not None:
                self.itemSize_Slider.setValue(int(thumbSize))
            if project is not None:
                self.project_comb.setCurrentIndex(int(project))
            self.type_listWgt.setCurrentRow(int(typ) if typ is not None else 0)
        finally:
            self.project_comb.blockSignals(False)
            self.type_listWgt.blockSignals(False)

    def update_project(self):
        self.project_comb.addItems(self.projectSetting()['projects'])

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
            self.type_listWgt.addItem(item)

    def projectChanged(self):
        self.rememberSettings()
        self.listWidgetAddItems(self.getItemsFromSQL())

    def typeChanged(self):
        self.rememberSettings()
        self.listWidgetAddItems(self.getItemsFromSQL())

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
            self.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.displayThumb_bttn.setToolTip("缩略图显示")
        else:
            self.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.displayThumb_bttn.setToolTip("表单显示")

    def backToMainWgt(self):
        """返回主面板"""
        self.preview_wgt.clear()
        self.update_asset()

    def viewThumbnailChange(self):
        """ 切换  缩略图/表单  显示 """
        if self.isList:
            self.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.displayThumb_bttn.setToolTip("表单显示")
            self.isList = False
            self.main_listWgt.setIsList(self.isList)
            self.main_listWgt.setIconMode()
        else:
            self.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.displayThumb_bttn.setToolTip("缩略图显示")
            self.isList = True
            self.main_listWgt.setIsList(self.isList)
            self.main_listWgt.setListMode()
        self.update_asset()
        self.rememberSettings()

    def itemSizeSliderChanged(self):
        """ 设置item尺寸 """
        itemSize = self.itemSize_Slider.value()
        if self.isList:
            pass
        else:
            # 关键：主列表是自绘 delegate，图标区尺寸取自 itemSize()(_itemSize)；只改 iconSize/gridSize
            # 只会让网格单元(间隙)变大而图标不变，必须同步更新 _itemSize，delegate 的 iconRect 高度才随之变大。
            self.main_listWgt.setItemSize(itemSize)
            self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.main_listWgt.setGridSize(QtCore.QSize(itemSize + 10, itemSize + 50))

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
        self.listWidgetAddItems(self.getItemsFromSQL())

    def update_asset(self):
        """
        更新资产的多线程
        """
        type, project, path = self.getTypeAndProject()
        if path and os.path.exists(path):
            self.infoMsg("info", "Loading...")
            self.update_asset_thread.start()
        else:
            self.main_listWgt.clear()

    def refresh_asset(self):
        self.listWidgetAddItems(self.getItemsFromSQL())

    def sort_asset_ui(self):
        """ 资产排序菜单：按列排序，同一项再次点击切换升/降序 """
        menu = QtWidgets.QMenu(self)
        sort_columns = [
            (u'按日期排序', 0),
            (u'按资产名排序', 1),
            (u'按中文名排序', 2),
            (u'按模型制作排序', 3),
            (u'按模型状态排序', 4),
            (u'按绑定制作排序', 5),
            (u'按绑定状态排序', 6),
        ]
        for name, column in sort_columns:
            act = QtGui.QAction(name, self)
            act.triggered.connect(lambda checked=False, col=column: self._do_sort(col))
            menu.addAction(act)
        menu.exec_(self.sort_bttn.mapToGlobal(self.sort_bttn.rect().bottomLeft()))

    def _do_sort(self, column):
        """
        更新当前排序状态并重排列表：同一列再次点击 -> 反向；换列 -> 默认升序。
        column: 0=日期 1=资产名 2=中文名 3=模型制作 4=模型状态 5=绑定制作 6=绑定状态
        """
        cur_col, cur_reverse = self._current_sort
        reverse = (not cur_reverse) if column == cur_col else False
        self._current_sort = (column, reverse)
        self.listWidgetAddItems()  # 用现有数据按新排序状态重排重填(保留当前搜索过滤)

    def _sort_data(self, data):
        """ 按当前排序状态 self._current_sort 对数据列表就地排序。 """
        column, reverse = self._current_sort

        def sort_key(item_data):
            try:
                value = item_data[column] if len(item_data) > column else None
            except (IndexError, TypeError):
                value = None
            if column == 0:  # 日期列统一按整数比较（空值当 0），避免 int/str 混排报错
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return 0
            return "" if value is None else str(value).lower()

        data.sort(key=sort_key, reverse=reverse)
        return data

    def search_asset(self):
        """ 搜索：按关键字过滤当前数据重填 """
        self.listWidgetAddItems()

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
        设置主面板FBX显示
        """
        self.main_listWgt.clear()
        self.preview_wgt.clear()
        keyWords = self.key_line.text()

        start_time = time.time()
        if new_dict:
            self.main_listWgt.setItems(new_dict)
        # 按当前排序状态排序数据（默认日期降序，最新在前），每次加载都生效
        _data = list(self.main_listWgt.items() or [])
        if _data:
            self._sort_data(_data)
            self.main_listWgt.setItems(_data)
        self.main_listWgt.setIsList(self.isList)
        self.main_listWgt.setItemSize(self.itemSize_Slider.value())
        self.main_listWgt.addItems(keyWords)
        self.main_listWgt.setMode()
        end_time = time.time()
        self.infoMsg("info", "%s items" % (self.main_listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')

    def listWidgetItemChanged(self):
        """ 改变item触发：把选中资产喂给 FBX 三维预览 + 动作库 """
        currentSelected = self.main_listWgt.selectedItems()
        if currentSelected:
            item_data = currentSelected[0].itemData()
            icon = item_data[7]
            '''喂给 FBX 预览：必须先 setTitle（GL 据 name 由 /Icon/→/FBX/ 推绑定文件），再 setPreviewPixmap'''
            self.preview_wgt.clear()
            self.preview_wgt.setTitle(item_data[1], item_data[2])
            self.preview_wgt.setPreviewPixmap(icon)
            '''列出该资产 Action 目录下的动作（递归），点击后 on_action_selected 套播'''
            self.action_wgt.setAsset(self.preview_wgt.deriveFbxPath(icon))
        else:
            self.preview_wgt.clear()
            self.action_wgt.clear()

    def on_action_selected(self, action_path):
        """动作库选中：把该动作套到当前预览的绑定文件上循环播放；空路径回静态预览。"""
        self.preview_wgt.playAction(action_path)

    def show_menu(self, point):
        """
        设置主面板右键菜单：Show in Explorer / Import
        """
        currentItem = self.main_listWgt.itemAt(point)
        if currentItem is None:
            return
        menu = QtWidgets.QMenu(self.main_listWgt)
        show_action = QtGui.QAction('Show in Explorer', self)
        show_action.setIcon(QtGui.QIcon("{}/icon/folder_white.png".format(self.scriptsPath)))
        imp_action = QtGui.QAction('Import', self)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(imp_action)
        show_action.triggered.connect(partial(self.openDir,
                                              currentItem.itemData()[7].split("/Icon/")[0]))
        imp_action.triggered.connect(self.importFile)
        menu.exec_(QtGui.QCursor.pos())

    def getTypeAndProject(self):
        project = self.project_comb.currentText()
        currentType = self.type_listWgt.selectedItems()
        if not currentType:
            type = 'Default'
            path = None
        else:
            type = str(currentType[0].text())
            path = '%s/%s/%s/%s' % (self.projectSetting()['rootPath'], project,
                                    self.projectSetting()['assetFolder'], type)
        return type, project, path

    def getCurrentData(self):
        currentSelected = self.main_listWgt.selectedItems()
        currentProject = str(self.project_comb.currentText())
        currentType = self.type_listWgt.selectedItems()[0].text()

        return currentSelected, currentProject, currentType

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
        if not new_assets:
            unreal.log_warning(u'导入动作未生成任何资产: {0} (检查: 该fbx是否含动画 / 骨架 {1} 的骨骼是否与动作匹配)'.format(
                animation_mesh_fbx, skeleton_path))
        for asset in new_assets:
            asset_path = '%s.%s' % (asset.package_name, asset.asset_name)  # UE5.7: AssetData 无 object_path
            if asset.asset_class == 'SkeletalMesh':
                unreal.EditorAssetLibrary.delete_asset(asset_path)
                print('Deleted asset: ' + asset_path)
            elif asset.asset_class == 'AnimSequence':
                anim = unreal.load_asset(asset_path)
                unreal.AnimationLibrary.set_is_root_motion_lock_forced(anim, True)
                print('"Force Root Lock" enabled for: ' + asset_path)
                unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)

    def importFile(self):
        """
        导入Asset文件到UE（SkeletalMesh）
        """
        try:
            currentSelected, currentProject, currentType = self.getCurrentData()
        except:
            self.infoMsg("warning", 'Please select Character!!!')
            return

        for item in currentSelected:
            item_data = item.itemData()
            path = item_data[7].split('/Icon/')[0]
            role_name = item_data[1]
            fbx_path = '%s/FBX/%s.fbx' % (path, role_name)
            character_folder = '/Game/Assets/{1}/{0}/'.format(role_name, currentType)
            material_folder = '/Game/Assets/{1}/{0}/Material/'.format(role_name, currentType)
            texture_folder = '/Game/Assets/{1}/{0}/Texture/'.format(role_name, currentType)
            AF = assetFunctions.AssetFunctions()
            animation_mesh_task = AF.buildImportTask(fbx_path, character_folder, AF.buildSkeletalMeshImportOptions())
            AF.executeImportTasks([animation_mesh_task])
            if not unreal.EditorAssetLibrary.does_directory_exist(material_folder):
                unreal.EditorAssetLibrary.make_directory(material_folder)
            if not unreal.EditorAssetLibrary.does_directory_exist(texture_folder):
                unreal.EditorAssetLibrary.make_directory(texture_folder)
            self.repathAssets(character_folder)

    def importActionFile(self, action_fbx=None):
        """
        导入动作到 UE 该资产的 Action 文件夹下（作 AnimSequence）。由右侧动作库右键"导入动作"触发，传动作 .fbx 全路径。
        """
        if not action_fbx:
            return
        p = str(action_fbx).replace("\\", "/")
        character_name = p.split('/Action/')[0].split('/')[-1]
        type_name = p.split('/Action/')[0].split('/')[-2]
        character_folder = '/Game/Assets/{0}/{1}'.format(type_name, character_name)
        skeleton_path = '{0}/{1}_Skeleton'.format(character_folder, character_name)
        animations_folder = '{0}/Action'.format(character_folder)
        # 动画导入必须绑定已存在的骨架；骨架缺失时 Interchange 只会报含糊的"没有要导入的数据"。
        # 这里先明确检查：找不到就列出该目录下实际存在的骨架名，直接暴露"没 Import 资产"或"骨架命名/路径不符"。
        if unreal.load_asset(skeleton_path) is None:
            existing = []
            if unreal.EditorAssetLibrary.does_directory_exist(character_folder):
                for a in unreal.EditorAssetLibrary.list_assets(character_folder, recursive=True):
                    if 'Skeleton' in str(a):
                        existing.append(str(a))
            unreal.log_warning(u'导入动作失败：找不到骨架 {0}。该目录下现有骨架: {1}'.format(
                skeleton_path, existing or u'无（请先 Import 该资产以生成骨架）'))
            self.infoMsg("warning", u"找不到骨架 %s_Skeleton，请先 Import 该资产" % character_name)
            return
        self.importAniFBX(p, skeleton_path, animations_folder)

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
        messageBox.show_msg(self.msg_icon_label, icon,
                            self.msg_label, text)
