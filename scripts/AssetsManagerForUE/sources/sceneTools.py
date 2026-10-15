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
from functools import partial

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

sys.path.append(scriptsPath.replace('sources', ''))
from ..utils import exportFunctions, assetFunctions, messageBox, myWidget
from ..utils.ue_window_style import (
    UEWindowFrameOverlay,
    UEWindowTitleBar,
    apply_ue_stylesheet,
    unreal_window_icon,
)
from ..config import commonSetting, databaseHost
from . import ue_asset_service, status_edit_service
from PySide6 import QtWidgets, QtCore, QtGui


_DRAINING_THREAD_JOBS = []


_ASSET_CLASS_LABELS = {
    "StaticMesh": u"静态网格体",
    "SkeletalMesh": u"骨架网格体",
    "Blueprint": u"蓝图",
    "WidgetBlueprint": u"控件蓝图",
    "AnimBlueprint": u"动画蓝图",
    "ControlRigBlueprint": u"控制绑定蓝图",
    "AnimSequence": u"动画序列",
    "AnimMontage": u"动画蒙太奇",
    "BlendSpace": u"混合空间",
    "Skeleton": u"骨骼",
    "PhysicsAsset": u"物理资产",
    "Material": u"材质",
    "MaterialInstanceConstant": u"材质实例",
    "MaterialFunction": u"材质函数",
    "MaterialFunctionInstance": u"材质函数实例",
    "Texture2D": u"贴图",
    "TextureCube": u"立方体贴图",
    "TextureRenderTarget2D": u"渲染目标贴图",
    "NiagaraSystem": u"Niagara 系统",
    "NiagaraEmitter": u"Niagara 发射器",
    "ParticleSystem": u"Cascade 粒子系统",
    "LevelSequence": u"关卡序列",
    "SoundWave": u"声音",
    "SoundCue": u"声音提示",
    "DataTable": u"数据表",
    "CurveTable": u"曲线表",
    "World": u"关卡",
}


def _asset_type_label(class_name, extension):
    """Return a readable conflict-list label for a UE package class."""
    class_name = str(class_name or "").strip()
    if class_name:
        short_name = class_name.rsplit(".", 1)[-1]
        return _ASSET_CLASS_LABELS.get(short_name, short_name)
    extension = str(extension or "").lower()
    if extension == ".umap":
        return u"关卡"
    if extension in (".uexp", ".ubulk", ".uptnl"):
        return u"包附属文件"
    if extension == ".uasset":
        return u"UE 资产"
    return extension or u"文件"


def _releaseDrainingJob(job):
    try:
        _DRAINING_THREAD_JOBS.remove(job)
    except ValueError:
        pass


class _UEHeaderCheckBox(QtWidgets.QCheckBox):
    """Three-state display whose user click always toggles all on/off."""

    def __init__(self, parent=None):
        super(_UEHeaderCheckBox, self).__init__(parent)
        self.setTristate(True)

    def nextCheckState(self):
        # Qt's default tri-state sequence is Unchecked -> PartiallyChecked ->
        # Checked. A select-all header skips the intermediate user state, while
        # code can still display it when only some rows are selected.
        target = (QtCore.Qt.Unchecked
                  if self.checkState() == QtCore.Qt.Checked
                  else QtCore.Qt.Checked)
        self.setCheckState(target)


class _UEConflictDialog(QtWidgets.QDialog):
    """接近 Unreal Editor 原生弹窗观感的无边框 Qt 对话框。"""

    def __init__(self, title, parent=None):
        super(_UEConflictDialog, self).__init__(parent)
        self._initial_position_applied = False
        self.setObjectName("UEConflictDialog")
        self.setWindowFlags(
            QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        self.setWindowIcon(unreal_window_icon())
        self.setModal(True)
        self.setMinimumSize(760, 500)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.title_bar = UEWindowTitleBar(
            self,
            title,
            close_callback=self.reject,
            allow_maximize=False,
        )
        root.addWidget(self.title_bar)

        self.content = QtWidgets.QWidget()
        self.content.setObjectName("UEConflictContent")
        self._content_layout = QtWidgets.QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(16, 14, 16, 14)
        self._content_layout.setSpacing(10)
        root.addWidget(self.content, 1)

        apply_ue_stylesheet(self, """
            QDialog#UEConflictDialog {
                background: #202020;
                border: none;
                color: #c9c9c9;
            }
            QWidget#UEConflictContent {
                background: #202020;
            }
            QLabel#UEConflictSectionTitle {
                color: #d8d8d8;
                font-size: 13px;
                font-weight: normal;
            }
            QLabel#UEConflictHint {
                color: #929292;
                font-size: 11px;
            }
            QLabel#UEConflictSelectionSummary {
                color: #a9a9a9;
                padding-left: 2px;
            }
            QTreeWidget#UEConflictTree {
                background: #171717;
                alternate-background-color: #1c1c1c;
                color: #c8c8c8;
                border: 1px solid #303030;
                outline: none;
                font-size: 12px;
            }
            QTreeWidget#UEConflictTree::item {
                height: 25px;
                border: none;
            }
            QTreeWidget#UEConflictTree::item:hover {
                background: #252f37;
            }
            QTreeWidget#UEConflictTree::item:selected {
                background: #274d68;
                color: white;
            }
            QHeaderView::section {
                background: #292929;
                color: #bdbdbd;
                border: none;
                border-right: 1px solid #3b3b3b;
                border-bottom: 1px solid #111111;
                padding: 4px 7px;
                height: 23px;
            }
            QScrollBar:vertical {
                background: #171717;
                width: 13px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #565656;
                min-height: 30px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6a6a6a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
            }
            QPushButton {
                background: #303030;
                color: #d0d0d0;
                border: 1px solid #4a4a4a;
                border-radius: 2px;
                min-height: 24px;
                padding: 1px 14px;
            }
            QPushButton:hover {
                background: #3a3a3a;
                border-color: #686868;
            }
            QPushButton:pressed {
                background: #252525;
            }
            QPushButton#UEConflictPrimaryButton {
                background: #0875c1;
                border-color: #1a8cda;
                color: white;
            }
            QPushButton#UEConflictPrimaryButton:hover {
                background: #128bdc;
            }
            QPushButton#UEConflictTextButton {
                background: transparent;
                border-color: transparent;
                color: #aeb8bf;
                padding: 1px 8px;
            }
            QPushButton#UEConflictTextButton:hover {
                background: #30363a;
                border-color: #46515a;
            }
            QToolTip {
                background: #111111;
                color: #d6d6d6;
                border: 1px solid #505050;
            }
        """)
        self._frame_overlay = UEWindowFrameOverlay(self)

    def contentLayout(self):
        return self._content_layout

    def showEvent(self, event):
        super(_UEConflictDialog, self).showEvent(event)
        if self._initial_position_applied:
            return
        self._initial_position_applied = True
        parent = self.parentWidget()
        if parent is not None:
            target_geometry = parent.window().frameGeometry()
        else:
            screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
            if screen is None:
                screen = QtGui.QGuiApplication.primaryScreen()
            target_geometry = screen.availableGeometry() if screen else QtCore.QRect()
        if target_geometry.isValid():
            self.move(target_geometry.center() - self.rect().center())

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
        self.user = user
        self.password = password
        self.scene_isList = False
        self._current_sort = (0, True)  # Default: newest scene first.
        self._state_generation = 0
        self._state_jobs = []
        self._copy_thread = None
        self._copy_worker = None
        self._copy_item_key = ""

        # 同步搭建界面（纯代码，无 I/O）→ 窗口一显示即最终布局，不闪。
        self.build_ui()
        self._status_editor = status_edit_service.StatusEditor(
            self, "scene", self._statusContext)
        self._status_editor.saved.connect(self._detailSaved)
        self.firstView()
        self.viewThumbnail()
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

    def _ensureScenePreviewWidget(self):
        """Create the shared FBX/OpenGL preview only after a scene is selected."""
        if self.preview_wgt is not None:
            return True
        try:
            from ..utils.fbxpreview.am_previewGLWidget import PreviewGLWidget

            preview = PreviewGLWidget(isPlayer=False)
            preview.setMinimumHeight(160)
            preview.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Expanding)
            if self._preview_placeholder is not None:
                self._preview_host_layout.removeWidget(self._preview_placeholder)
                self._preview_placeholder.deleteLater()
                self._preview_placeholder = None
            self._preview_host_layout.addWidget(preview, 1)
            self.preview_wgt = preview
            return True
        except Exception as exc:
            if self._preview_placeholder is not None:
                self._preview_placeholder.setText(
                    u"FBX 预览器加载失败：{0}".format(exc))
            self.infoMsg("error", u"FBX 预览器加载失败：{0}".format(exc))
            return False

    def build_ui(self):
        """纯代码搭建界面：左(项目+类型) | 中(工具栏+列表) | 右(静态预览+.ma列表+导出面板) + 底部状态栏。"""
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setSpacing(0)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.main_splitter.setObjectName("SceneMainSplitter")
        self.main_splitter.setHandleWidth(5)
        self.main_splitter.setChildrenCollapsible(False)
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
        self.scene_refresh_Bttn = self._toolBtn('refresh.png', u"刷新")
        tool.addWidget(self.scene_refresh_Bttn)

        self.scene_sort_bttn = QtWidgets.QToolButton()
        self.scene_sort_bttn.setIcon(
            QtGui.QIcon('%s/icon/sort.png' % self.scriptsPath))
        self.scene_sort_bttn.setToolTip(u"排序")
        self.scene_sort_bttn.setStyleSheet(
            "border-style: flat; background: transparent;")
        tool.addWidget(self.scene_sort_bttn)

        self.scene_key_line = QtWidgets.QLineEdit()
        self.scene_key_line.setClearButtonEnabled(True)
        self.scene_key_line.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed)
        self.scene_key_line.setPlaceholderText(u"Search...")
        self.scene_key_line.addAction(QtGui.QIcon('%s/icon/search.png' % self.scriptsPath),
                                      QtWidgets.QLineEdit.LeadingPosition)
        tool.addWidget(self.scene_key_line, 1)
        centerV.addLayout(tool)
        self.main_listWgt = myWidget.MainQListWiget()
        self.main_listWgt.setUEPublishedStatusField(4)  # scene.status
        self.main_listWgt.setSortingEnabled(False)
        self.main_listWgt.setListColumns(
            (u"创建日期", u"场景名", u"中文名", u"制作人", u"状态", u"备注"),
            (0, 1, 2, 3, 4, 8),
            (90, 190, 120, 100, 90, 260),
            (None, None, None, None, None, "note"),
            ("center", "left", "left", "center", "center", "left"),
        )
        self.scene_list_header = myWidget.AssetListHeader(self.main_listWgt)
        self.scene_list_header.setSortIndicator(*self._current_sort)
        self.scene_list_header.sectionClicked.connect(self._do_scene_sort)
        self.scene_list_header.hide()
        self.main_listWgt.setListHeader(self.scene_list_header)
        centerV.addWidget(self.scene_list_header)
        centerV.addWidget(self.main_listWgt, 1)
        self.main_splitter.addWidget(center)

        # ---- 右栏：可调高度的 FBX 预览 + .ma 列表/导出面板 ----
        right = QtWidgets.QWidget()
        rightV = QtWidgets.QVBoxLayout(right)
        rightV.setContentsMargins(0, 0, 0, 0)
        rightV.setSpacing(0)
        self.detail_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.detail_splitter.setObjectName("SceneDetailsSplitter")
        self.detail_splitter.setHandleWidth(5)
        self.detail_splitter.setChildrenCollapsible(False)

        self._preview_host = QtWidgets.QWidget()
        self._preview_host_layout = QtWidgets.QVBoxLayout(self._preview_host)
        self._preview_host_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_host_layout.setSpacing(0)
        self.preview_wgt = None
        self._preview_placeholder = QtWidgets.QLabel(u"选择场景后加载 FBX 预览")
        self._preview_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._preview_placeholder.setMinimumHeight(160)
        self._preview_placeholder.setStyleSheet(
            "background:#242528; color:#858585; border:1px solid #151515;")
        self._preview_host_layout.addWidget(self._preview_placeholder, 1)
        self.detail_splitter.addWidget(self._preview_host)

        lower = QtWidgets.QWidget()
        lowerV = QtWidgets.QVBoxLayout(lower)
        lowerV.setContentsMargins(0, 0, 0, 0)
        lowerV.setSpacing(4)

        self.scene_int_listWgt = QtWidgets.QListWidget()
        lowerV.addWidget(self.scene_int_listWgt, 1)

        exportFrame = QtWidgets.QFrame()
        exportFrame.setFrameShape(QtWidgets.QFrame.Box)
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
        lowerV.addWidget(exportFrame)
        self.detail_splitter.addWidget(lower)
        self.detail_splitter.setStretchFactor(0, 3)
        self.detail_splitter.setStretchFactor(1, 2)
        self.detail_splitter.setSizes([340, 220])
        rightV.addWidget(self.detail_splitter, 1)
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
        self.scene_refresh_Bttn.clicked.connect(self.update_asset)
        self.scene_sort_bttn.clicked.connect(self.sort_scene_ui)
        self.scene_key_line.returnPressed.connect(self.sc_search)
        self.main_listWgt.itemSelectionChanged.connect(self.mainWightItemChanged)
        self.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.main_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.main_listWgt.assetDropRequested.connect(self.placeImportedAsset)
        self.main_listWgt.assetDragRejected.connect(
            lambda text: self.infoMsg("warning", text))
        self.exportScenePath_bttn.clicked.connect(self.getSceneExportPath)
        self.exportScene_bttn.clicked.connect(self.exportScene)
        self.detail_splitter.splitterMoved.connect(
            lambda _position, _index: self.rememberSettings())
        self.main_splitter.splitterMoved.connect(
            lambda _position, _index: self.rememberSettings())

    def rememberSettings(self):
        """ 记忆窗口设置 """
        settings = QtCore.QSettings('SceneUE', 'SceneUESettings')
        settings.setValue('isList', self.scene_isList)
        settings.setValue('thumbSize', self.scene_itemSize_Slider.value())
        settings.setValue('project', self.proj_comb.currentIndex())
        settings.setValue('typ', self.type_listWgt.currentRow())
        settings.setValue('detailSplitterSizes', self.detail_splitter.sizes())
        settings.setValue('mainSplitterSizes', self.main_splitter.sizes())

    def readSettings(self):
        """ 读取QSettings数据 """
        settings = QtCore.QSettings('SceneUE', 'SceneUESettings')
        isList = settings.value('isList')
        thumbSize = settings.value('thumbSize')
        project = settings.value('project')
        typ = settings.value('typ')
        splitter_sizes = settings.value('detailSplitterSizes')
        main_splitter_sizes = settings.value('mainSplitterSizes')
        if isList is not None:
            if isList == 'true':
                self.scene_isList = True
            else:
                self.scene_isList = False

        if isinstance(splitter_sizes, (list, tuple)) and len(splitter_sizes) == 2:
            try:
                sizes = [max(1, int(value)) for value in splitter_sizes]
                self.detail_splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass
        if isinstance(main_splitter_sizes, (list, tuple)) and len(main_splitter_sizes) == 3:
            try:
                sizes = [max(1, int(value)) for value in main_splitter_sizes]
                self.main_splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass

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
        self.proj_comb.addItems(commonSetting()['DataBase'])

    def get_typ(self):
        # print("update_type")
        self.type_listWgt.clear()
        project = self.proj_comb.currentText()
        pj_path = '{0}/{1}/{2}'.format(commonSetting()['rootPath'], project, 'Scenes')
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
        __path = '%s/%s/Scenes/%s' % (commonSetting()['rootPath'], __project, __type)
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
        else:
            self.scene_displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_list.png' % self.scriptsPath))
            self.scene_displayThumb_bttn.setToolTip("表单显示")
        self.main_listWgt.setIsList(self.scene_isList)
        self.main_listWgt.setItemSize(itemSize)
        self.main_listWgt.setMode()
        self.scene_list_header.setVisible(self.scene_isList)

    def viewThumbnailChange(self):
        """切换  缩略图/表单  显示"""
        self.scene_isList = not self.scene_isList
        self.viewThumbnail()
        self.update_asset()
        self.rememberSettings()

    def setItemSize(self):
        itemSize = self.scene_itemSize_Slider.value()
        if self.scene_isList:
            pass
        else:
            # The delegate paints from MainQListWiget.itemSize(). Updating only
            # iconSize/gridSize enlarges the cell gap while leaving the card at
            # its old size, so all three values must move together.
            self.main_listWgt.setItemSize(itemSize)
            self.main_listWgt.setIconSize(QtCore.QSize(itemSize, itemSize))
            self.main_listWgt.setGridSize(QtCore.QSize(
                itemSize + self.main_listWgt.DEF_SPACING,
                itemSize + self.main_listWgt.DEF_SPACING
                + self.main_listWgt.textAreaHeight()))
            self.main_listWgt.viewport().update()

    def sort_scene_ui(self):
        """Scene sorting menu; selecting the active field reverses it."""
        menu = QtWidgets.QMenu(self)
        current_column, reverse = self._current_sort
        sort_icon = QtGui.QIcon('%s/icon/%s' % (
            self.scriptsPath, 'sort_down.png' if reverse else 'sort_up.png'))
        sort_columns = [
            (u'按日期排序', 0),
            (u'按场景名排序', 1),
            (u'按中文名排序', 2),
            (u'按制作人排序', 3),
            (u'按状态排序', 4),
            (u'按备注排序', 5),
        ]
        for name, column in sort_columns:
            action = QtGui.QAction(name, self)
            if column == current_column:
                action.setIcon(sort_icon)
                action.setIconVisibleInMenu(True)
            action.triggered.connect(
                lambda checked=False, col=column: self._do_scene_sort(col))
            menu.addAction(action)
        menu.exec_(self.scene_sort_bttn.mapToGlobal(
            self.scene_sort_bttn.rect().bottomLeft()))

    def _do_scene_sort(self, column):
        cur_column, cur_reverse = self._current_sort
        reverse = (not cur_reverse) if column == cur_column else False
        self._current_sort = (int(column), reverse)
        self.scene_list_header.setSortIndicator(column, reverse)
        self.listWidgetAddItems()

    def _sort_scene_data(self, data):
        """Sort scene rows using the same field mapping as the list header."""
        column, reverse = self._current_sort
        field_indices = self.main_listWgt.listFieldIndices()
        data_index = field_indices[column] if 0 <= column < len(field_indices) else 0

        def sort_key(item_data):
            try:
                value = item_data[data_index] if len(item_data) > data_index else None
            except (IndexError, TypeError):
                value = None
            if data_index == 0:
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return 0
            return "" if value is None else str(value).lower()

        data.sort(key=sort_key, reverse=reverse)
        return data

    def update_asset(self):
        """
        根据type，project，设置主面板item显示
        """
        self._status_editor.setLoading()
        project, _type, path = self.getPanelsData()
        if os.path.exists(str(path)):
            self.update_scene_thread = myWidget.MyThread()
            self.update_scene_thread.signal.connect(lambda: self.listWidgetAddItems(self.getItemsFromSQL()))
            self.infoMsg("info", "Loading...")
            self.update_scene_thread.start()
        else:
            self.listWidgetAddItems([])

    def _statusContext(self):
        current_type = self.type_listWgt.currentItem()
        return (str(self.proj_comb.currentText()),
                str(current_type.text()) if current_type is not None else "")

    def _detailSaved(self, request):
        if (request[3] == 2 and request[:2] == self._statusContext()
                and request[:2] == self._status_editor.context
                and self.preview_wgt is not None):
            selected = self.main_listWgt.currentItem()
            if selected is not None and str(selected.itemData()[1]) == request[2]:
                self.preview_wgt.setTitle(request[2], request[4])

    def getItemsDict(self):
        """
        从 PostgreSQL 获取场景数据。
        :return:{role_name:{'role_name': xx,
                        'project': xx,
                        'type': xx,
                        'zh_name': xx,
                        'icon_path': xx}}
        """
        if self.isSQL:
            __items_dict = self.getItemsFromSQL()
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
                 "scene.artist", "scene.status", "scene.icon", "scene.note"
                 FROM public."scene"
                 WHERE
                 "scene.type" = '%s';
                 ''' % _type
        try:
            conn = psycopg2.connect(database=_project, user=self.user, password=self.password, host=databaseHost(),
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
        根据 type、project 显示 PostgreSQL 场景数据。
        """
        # print("listWidgetAddItems Scene", dict)
        listWgt = self.main_listWgt
        listWgt.clear()
        if self.preview_wgt is not None:
            self.preview_wgt.clear()
        keyWords = self.scene_key_line.text()
        is_list = self.scene_isList

        start_time = time.time()
        if new_dict is not None:
            listWgt.setItems(new_dict or [])
            self._status_editor.setContext(*self._statusContext())
        data = list(listWgt.items() or [])
        if data:
            self._sort_scene_data(data)
            listWgt.setItems(data)
        listWgt.setIsList(is_list)
        listWgt.setItemSize(self.scene_itemSize_Slider.value())
        listWgt.addItems(keyWords)
        listWgt.setMode()
        self.scene_list_header.setVisible(is_list)
        self.scene_list_header.setSortIndicator(*self._current_sort)
        end_time = time.time()

        self.infoMsg("info", 'Load Completed !  ' +
                     "   %s items" % (listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')
        self.scanUEAssetStates()

    def mainWightItemChanged(self):
        """
        改变item触发：改变rBttn显示,改变预览显示,改变scene_int_listWgt显示
        """
        currentSelected = self.main_listWgt.selectedItems()
        if currentSelected:
            item_data = currentSelected[0].itemData()
            project, scene_type, unused_path = self.getPanelsData()
            del unused_path
            scene_name = str(item_data[1])
            zh_name = "" if item_data[2] is None else str(item_data[2])
            modPath = '{0}/{1}/Scenes/{2}/{3}/Mod'.format(
                commonSetting()['rootPath'], project, scene_type, scene_name)
            if not self._ensureScenePreviewWidget():
                return
            self.preview_wgt.clear()
            self.preview_wgt.setTitle(scene_name, zh_name)
            self.preview_wgt.setPreviewPixmap(item_data[7])

            self.update_asset_int(modPath)
        else:
            if self.preview_wgt is not None:
                self.preview_wgt.clear()
            self.scene_int_listWgt.clear()

    def show_menu(self, point):
        """
        场景卡片右键菜单：旧 FBX 导入和 UE 最终资产迁移各走各的入口。
        """
        currentItem = self.main_listWgt.itemAt(point)
        if currentItem is None:
            return
        self.main_listWgt.setCurrentItem(currentItem)
        asset_root = self._assetRootForItem(currentItem)

        menu = QtWidgets.QMenu(self.main_listWgt)
        show_action = QtGui.QAction(u'打开资产文件夹', self)
        show_action.setIcon(QtGui.QIcon(
            "{}/icon/folder_white.png".format(self.scriptsPath)))
        show_ue_action = QtGui.QAction(u'打开 UE 发布目录', self)
        load_action = QtGui.QAction(u'加载资产', self)
        import_fbx_action = QtGui.QAction(u'导入 FBX', self)
        locate_action = QtGui.QAction(u'在内容浏览器中定位', self)
        locate_action.setEnabled(bool(currentItem.ueMainObjectPath()))

        menu.addAction(show_action)
        menu.addAction(show_ue_action)
        menu.addSeparator()
        menu.addAction(load_action)
        menu.addAction(locate_action)
        menu.addSeparator()
        menu.addAction(import_fbx_action)

        show_action.triggered.connect(
            lambda _checked=False, path=asset_root: self.openDir(path))
        show_ue_action.triggered.connect(
            lambda _checked=False, path=os.path.join(asset_root, "UE"):
            self.openDir(path))
        load_action.triggered.connect(
            lambda _checked=False, item=currentItem: self.loadUEAsset(item))
        locate_action.triggered.connect(
            lambda _checked=False, item=currentItem: self.locateUEAsset(item))
        import_fbx_action.triggered.connect(
            lambda _checked=False, item=currentItem: self.importFBX(item))
        menu.exec_(QtGui.QCursor.pos())

    def openDir(self, folder_path=None):
        folder_path = os.path.normpath(str(folder_path or ""))
        if not folder_path or not os.path.isdir(folder_path):
            self.infoMsg('warning', u'文件夹不存在：{0}'.format(folder_path))
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder_path))

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

    # ---------------------------------------------------------- UE 最终资产包
    def _assetRootForItem(self, item):
        if item is None:
            return ""
        item_data = item.itemData()
        asset_root = ue_asset_service.asset_root_from_item_data(item_data)
        if asset_root:
            return os.path.normpath(asset_root)
        try:
            scene_name = str(item_data[1])
            project, scene_type, _unused = self.getPanelsData()
        except (IndexError, TypeError, AttributeError):
            return ""
        return os.path.normpath(os.path.join(
            str(commonSetting()['rootPath']), project, "Scenes",
            scene_type, scene_name))

    def _itemKey(self, item):
        return self._assetRootForItem(item).replace("\\", "/").lower()

    def _findItemByKey(self, key):
        key = str(key or "")
        for index in range(self.main_listWgt.count()):
            item = self.main_listWgt.item(index)
            try:
                if self._itemKey(item) == key:
                    return item
            except (IndexError, TypeError, RuntimeError):
                pass
        return None

    def scanUEAssetStates(self):
        """后台检查场景卡片对应的 UE 发布包和当前工程状态。"""
        self._state_generation += 1
        generation = self._state_generation
        for _thread, worker in list(self._state_jobs):
            worker.cancel()

        requests = []
        for index in range(self.main_listWgt.count()):
            item = self.main_listWgt.item(index)
            key = self._itemKey(item)
            asset_root = self._assetRootForItem(item)
            item.setUESourceAvailability(None, u"正在检查服务器 UE 发布文件…")
            item.setUEState("scanning", u"正在检查 UE 发布资产…")
            requests.append((key, asset_root))
        if not requests:
            return

        try:
            target_content = ue_asset_service.project_content_dir()
        except Exception as exc:
            self.infoMsg("error", str(exc))
            return

        thread = QtCore.QThread()
        worker = ue_asset_service.AssetStateWorker(
            generation, requests, target_content)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.itemScanned.connect(self._applyUEState)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._releaseStateJob)
        self._state_jobs.append((thread, worker))
        thread.start()

    def _releaseStateJob(self):
        finished_thread = self.sender()
        self._state_jobs = [
            job for job in self._state_jobs if job[0] is not finished_thread]

    @staticmethod
    def _setItemUEPlan(item, plan):
        item.setUESourceAvailability(
            plan.get("source_available"), plan.get("source_message"),
            ue_directory_exists=plan.get("ue_directory_exists"))
        item.setUEState(plan.get("state"), plan.get("message"), plan)

    def _applyUEState(self, generation, key, plan):
        if generation != self._state_generation:
            return
        item = self._findItemByKey(key)
        if item is None:
            return
        if plan.get("state") == "ready":
            try:
                plan["main_object_path"] = (
                    ue_asset_service.resolve_placeable_object_path(plan))
                if not plan["main_object_path"]:
                    plan["state"] = "partial"
                    plan["message"] = (
                        u"UE 包已在工程中；未找到可直接拖放的 Actor 蓝图或网格体")
            except Exception:
                pass
        self._setItemUEPlan(item, plan)

    def _chooseConflictFiles(self, plan):
        """让用户逐项决定冲突文件是覆盖服务器版本还是保留工程版本。"""
        conflicts = list(plan.get("different_files") or [])
        if not conflicts:
            return False

        entries = {
            str(entry.get("relative") or "").replace("\\", "/").lower(): entry
            for entry in (plan.get("files") or [])
        }
        dialog = _UEConflictDialog(u"加载资产冲突", self)
        dialog.resize(980, 610)
        layout = dialog.contentLayout()

        title = QtWidgets.QLabel(u"选择要覆盖加载的内容")
        title.setObjectName("UEConflictSectionTitle")
        layout.addWidget(title)
        description = QtWidgets.QLabel(
            u"检测到 {0} 个同名但内容不同的文件。勾选项将使用服务器版本覆盖；"
            u"未勾选项保留工程版本。缺失文件仍会正常加载。".format(len(conflicts)))
        description.setObjectName("UEConflictHint")
        description.setWordWrap(True)
        layout.addWidget(description)

        tree = QtWidgets.QTreeWidget()
        tree.setObjectName("UEConflictTree")
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setIndentation(0)
        tree.setIconSize(QtCore.QSize(16, 16))
        tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        tree.setHeaderLabels(
            ("", u"资产", u"文件", u"类型", u"服务器大小", u"工程大小"))
        tree.setColumnWidth(0, 42)
        tree.setColumnWidth(1, 175)
        tree.setColumnWidth(3, 135)
        tree.setColumnWidth(4, 95)
        tree.setColumnWidth(5, 95)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        layout.addWidget(tree, 1)

        def size_text(value):
            value = max(0, int(value or 0))
            if value >= 1024 * 1024:
                return u"{0:.1f} MB".format(value / (1024.0 * 1024.0))
            if value >= 1024:
                return u"{0:.1f} KB".format(value / 1024.0)
            return u"{0} B".format(value)

        icon_cache = {}

        def package_icon(extension):
            extension = str(extension or "").lower()
            if extension in icon_cache:
                return icon_cache[extension]
            color = {
                ".umap": QtGui.QColor(92, 160, 83),
                ".uasset": QtGui.QColor(35, 132, 187),
                ".uexp": QtGui.QColor(116, 97, 155),
                ".ubulk": QtGui.QColor(125, 102, 72),
                ".uptnl": QtGui.QColor(125, 102, 72),
            }.get(extension, QtGui.QColor(100, 110, 118))
            pixmap = QtGui.QPixmap(16, 16)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
            painter.setPen(QtGui.QPen(color.lighter(145), 1))
            painter.setBrush(color)
            painter.drawRect(2, 2, 11, 11)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 85), 1))
            painter.drawLine(4, 5, 11, 5)
            painter.drawLine(4, 8, 10, 8)
            painter.end()
            icon = QtGui.QIcon(pixmap)
            icon_cache[extension] = icon
            return icon

        # Resolve package types in one batch. Sidecar files inherit the class
        # of the .uasset/.umap with the same stem. When an older bridge cannot
        # inspect the server package, the existing project asset is a reliable
        # fallback for this conflict-only list.
        conflict_stems = {
            os.path.splitext(str(relative).replace("\\", "/"))[0].lower()
            for relative in conflicts
        }
        primary_entries = {}
        for source_entry in (plan.get("files") or []):
            relative_path = str(
                source_entry.get("relative") or "").replace("\\", "/")
            package_stem, package_extension = os.path.splitext(relative_path)
            if (package_stem.lower() in conflict_stems
                    and package_extension.lower() in (".uasset", ".umap")):
                primary_entries[package_stem.lower()] = (
                    relative_path, source_entry)

        class_names_by_stem = {}
        external_paths = []
        external_stems = []
        for package_stem, (relative_path, source_entry) in primary_entries.items():
            extension = os.path.splitext(relative_path)[1].lower()
            if extension == ".umap":
                class_names_by_stem[package_stem] = "World"
                continue
            source_path = str(source_entry.get("source") or "")
            if source_path and os.path.isfile(source_path):
                external_paths.append(source_path)
                external_stems.append(package_stem)

        source_content_root = (
            plan.get("source_content_root") or plan.get("source_root") or "")
        if external_paths and source_content_root:
            external_classes, _type_error = (
                ue_asset_service.get_external_asset_class_names(
                    external_paths, source_content_root))
            for package_stem, class_name in zip(
                    external_stems, external_classes):
                if class_name:
                    class_names_by_stem[package_stem] = class_name

        for package_stem, (relative_path, _source_entry) in primary_entries.items():
            if class_names_by_stem.get(package_stem):
                continue
            class_name = ue_asset_service.project_asset_class_name(
                relative_path)
            if class_name:
                class_names_by_stem[package_stem] = class_name

        for relative in sorted(conflicts, key=str.lower):
            normalized = str(relative).replace("\\", "/")
            entry = entries.get(normalized.lower(), {})
            target = str(entry.get("target") or "")
            package_relative, extension = os.path.splitext(normalized)
            extension = extension.lower()
            asset_name = os.path.basename(package_relative)
            package_path = "/Game/{0}".format(package_relative.strip("/"))
            class_name = class_names_by_stem.get(package_relative.lower(), "")
            try:
                target_size = os.path.getsize(target) if os.path.isfile(target) else 0
            except OSError:
                target_size = 0
            row = QtWidgets.QTreeWidgetItem((
                "", asset_name, package_path,
                _asset_type_label(class_name, extension),
                size_text(entry.get("size", 0)), size_text(target_size)))
            row.setFlags(row.flags() | QtCore.Qt.ItemIsUserCheckable)
            row.setCheckState(0, QtCore.Qt.Unchecked)
            row.setData(0, QtCore.Qt.UserRole, normalized)
            row.setIcon(1, package_icon(extension))
            row.setForeground(
                3, QtGui.QBrush(
                    QtGui.QColor(75, 205, 113)
                    if extension == ".umap"
                    else QtGui.QColor(46, 178, 221)))
            row.setToolTip(2, u"服务器：{0}\n工程：{1}".format(
                entry.get("source") or "", target))
            tree.addTopLevelItem(row)

        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(8)
        selection_label = QtWidgets.QLabel()
        selection_label.setObjectName("UEConflictSelectionSummary")
        footer.addWidget(selection_label)

        select_all = QtWidgets.QPushButton(u"全选")
        select_all.setObjectName("UEConflictTextButton")
        invert = QtWidgets.QPushButton(u"反选")
        invert.setObjectName("UEConflictTextButton")
        footer.addWidget(select_all)
        footer.addWidget(invert)
        footer.addStretch(1)

        continue_button = QtWidgets.QPushButton(u"加载选中项")
        continue_button.setObjectName("UEConflictPrimaryButton")
        keep_button = QtWidgets.QPushButton(u"全部保留并加载")
        cancel_button = QtWidgets.QPushButton(u"取消")
        continue_button.setDefault(True)
        continue_button.setAutoDefault(True)
        footer.addWidget(continue_button)
        footer.addWidget(keep_button)
        footer.addWidget(cancel_button)
        layout.addLayout(footer)

        header_check = _UEHeaderCheckBox(header)
        header_check.setToolTip(u"全选或全部取消")
        header_check.resize(18, 18)
        header_updating = [False]

        def position_header_check():
            header_check.move(
                max(4, int((tree.columnWidth(0) - header_check.width()) / 2)),
                max(2, int((header.height() - header_check.height()) / 2)))

        header.geometriesChanged.connect(position_header_check)
        position_header_check()

        def update_selection_label(*_unused):
            selected = sum(
                1 for index in range(tree.topLevelItemCount())
                if tree.topLevelItem(index).checkState(0) == QtCore.Qt.Checked)
            selection_label.setText(
                u"已选择 {0} / {1}（覆盖 {0}，保留 {2}）".format(
                    selected, tree.topLevelItemCount(),
                    tree.topLevelItemCount() - selected))
            header_updating[0] = True
            header_check.blockSignals(True)
            if selected == 0:
                header_check.setCheckState(QtCore.Qt.Unchecked)
            elif selected == tree.topLevelItemCount():
                header_check.setCheckState(QtCore.Qt.Checked)
            else:
                header_check.setCheckState(QtCore.Qt.PartiallyChecked)
            header_check.blockSignals(False)
            header_updating[0] = False

        def set_all(state):
            tree.blockSignals(True)
            for index in range(tree.topLevelItemCount()):
                tree.topLevelItem(index).setCheckState(0, state)
            tree.blockSignals(False)
            update_selection_label()

        def header_state_changed(state):
            if header_updating[0]:
                return
            target_state = (QtCore.Qt.Checked
                            if header_check.checkState() == QtCore.Qt.Checked
                            else QtCore.Qt.Unchecked)
            set_all(target_state)

        def invert_all(*_unused):
            tree.blockSignals(True)
            for index in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(index)
                state = (QtCore.Qt.Unchecked
                         if row.checkState(0) == QtCore.Qt.Checked
                         else QtCore.Qt.Checked)
                row.setCheckState(0, state)
            tree.blockSignals(False)
            update_selection_label()

        def keep_all_and_accept(*_unused):
            set_all(QtCore.Qt.Unchecked)
            dialog.accept()

        select_all.clicked.connect(
            lambda _checked=False: set_all(QtCore.Qt.Checked))
        invert.clicked.connect(invert_all)
        header_check.stateChanged.connect(header_state_changed)
        tree.itemChanged.connect(update_selection_label)
        continue_button.clicked.connect(dialog.accept)
        keep_button.clicked.connect(keep_all_and_accept)
        cancel_button.clicked.connect(dialog.reject)
        update_selection_label()

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return False

        overwrite_files = []
        keep_existing_files = []
        for index in range(tree.topLevelItemCount()):
            row = tree.topLevelItem(index)
            relative = str(row.data(0, QtCore.Qt.UserRole) or "")
            if row.checkState(0) == QtCore.Qt.Checked:
                overwrite_files.append(relative)
            else:
                keep_existing_files.append(relative)
        plan["overwrite_files"] = overwrite_files
        plan["keep_existing_files"] = keep_existing_files
        return True

    def loadUEAsset(self, item=None):
        """迁移 ``<场景资产>/UE`` 中的 UE 包，不经过 FBX 再导入。"""
        if isinstance(item, bool):
            item = None
        item = item or self.main_listWgt.currentItem()
        if item is None:
            self.infoMsg("warning", u"请先选择一张场景资产卡片")
            return
        if self._copy_thread is not None and self._copy_thread.isRunning():
            self.infoMsg("warning", u"已有资产正在加载，请等待当前任务完成")
            return

        plan = item.uePlan()
        if not plan or plan.get("state") == "scanning":
            try:
                plan = ue_asset_service.build_import_plan(
                    self._assetRootForItem(item))
            except Exception as exc:
                item.setUESourceAvailability(
                    None, u"无法确认服务器 UE 发布文件：{0}".format(exc))
                item.setUEState("error", str(exc))
                self.infoMsg("error", str(exc))
                return

        # The background card state may be older than the user's click.  Use
        # the same size + SHA-1 rule as the copy worker before showing conflict
        # choices, so every differing file receives an overwrite/keep policy.
        plan = ue_asset_service.query_filesystem_state(
            plan, verify_content=True)
        self._setItemUEPlan(item, plan)

        if not plan.get("files") or not plan.get("package_object_paths"):
            message = plan.get("message") or u"没有找到该资产的 UE 发布文件"
            item.setUEState("missing", message, plan)
            self.infoMsg("warning", message)
            self._showMissingUEPackageDialog(plan, message)
            return
        if plan.get("state") == "conflict":
            item.setUEState("conflict", plan.get("message"), plan)
            self.infoMsg("warning", plan.get("message"))
            if not self._chooseConflictFiles(plan):
                return
        if plan.get("state") == "ready":
            self._registerLoadedPlan(item, plan)
            return

        self._copy_item_key = self._itemKey(item)
        item.setUEProgress(0, u"准备迁移 UE 最终资产…")
        for warning in ue_asset_service.prepare_plan_overwrites(plan):
            self.infoMsg("warning", warning)
        thread = QtCore.QThread()
        worker = ue_asset_service.AssetCopyWorker(plan)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._onCopyProgress)
        worker.finished.connect(self._onCopyFinished)
        worker.failed.connect(self._onCopyFailed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._onCopyThreadFinished)
        self._copy_thread = thread
        self._copy_worker = worker
        thread.start()

    def _showMissingUEPackageDialog(self, plan, message):
        asset_root = os.path.normpath(
            str((plan or {}).get("asset_root") or ""))
        release_root = os.path.join(asset_root, "UE") if asset_root else ""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(u"加载资产失败")
        box.setText(str(message or u"没有找到可加载的 UE 发布资产"))
        detail = (
            u"请确认该场景资产的 UE 发布目录中至少包含一个完整的 "
            u".uasset 或 .umap 主包。\n"
            u"只有 .uexp、.ubulk 或 .uptnl 等附属文件不能单独加载。")
        if release_root:
            detail += u"\n\n检查路径：{0}".format(release_root)
        box.setInformativeText(detail)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        box.setEscapeButton(QtWidgets.QMessageBox.Ok)
        box.exec()

    def _onCopyProgress(self, percent, name):
        item = self._findItemByKey(self._copy_item_key)
        if item is not None:
            item.setUEProgress(percent, u"正在加载：{0}".format(name))
        self.infoMsg("info", u"加载资产 {0}%：{1}".format(percent, name))

    def _onCopyFinished(self, plan):
        item = self._findItemByKey(self._copy_item_key)
        if item is not None:
            self._registerLoadedPlan(item, plan)

    def _registerLoadedPlan(self, item, plan):
        try:
            item.setUEProgress(100, u"正在刷新 UE Asset Registry…")
            plan = ue_asset_service.refresh_asset_registry(plan)
            self._setItemUEPlan(item, plan)
            if plan.get("state") == "ready":
                self.infoMsg("info", plan.get("message"))
            elif plan.get("state") == "partial":
                self.infoMsg("warning", plan.get("message"))
            else:
                self.infoMsg("error", plan.get("message"))
            if plan.get("state") in ("ready", "partial"):
                located, object_path = (
                    ue_asset_service.sync_plan_to_content_browser(plan))
                if located:
                    self.infoMsg(
                        "info", u"加载完成，已在内容浏览器中定位：{0}".format(
                            object_path))
                else:
                    self.infoMsg(
                        "warning", u"加载完成，但没有找到可在内容浏览器中定位的资产")
        except Exception as exc:
            item.setUEState("error", str(exc), plan)
            self.infoMsg("error", u"UE 注册资产失败：{0}".format(exc))

    def _onCopyFailed(self, message):
        item = self._findItemByKey(self._copy_item_key)
        state = "conflict" if (
            u"同名不同" in message or u"目标文件" in message) else "error"
        if item is not None:
            item.setUEState(state, message)
        self.infoMsg("error", message)
        QtWidgets.QMessageBox.warning(self, u"加载资产失败", str(message))

    def _onCopyThreadFinished(self):
        self._copy_thread = None
        self._copy_worker = None
        self._copy_item_key = ""

    def locateUEAsset(self, item=None):
        item = item or self.main_listWgt.currentItem()
        if item is None or not item.ueMainObjectPath():
            self.infoMsg("warning", u"该资产尚未加载，或没有可定位的主资产")
            return
        if not ue_asset_service.sync_to_content_browser(
                item.ueMainObjectPath()):
            self.infoMsg("warning", u"内容浏览器无法定位该资产")

    def placeImportedAsset(self, payload):
        object_path = (payload or {}).get("object_path", "")
        screen_position = None
        if "screen_x" in (payload or {}) and "screen_y" in (payload or {}):
            screen_position = (payload["screen_x"], payload["screen_y"])
        success, error = ue_asset_service.place_asset_at_cursor(
            object_path, screen_position=screen_position)
        if success:
            self.infoMsg("info", u"已放入关卡：{0}".format(object_path))
        else:
            self.infoMsg("warning", error or u"资产未能放入当前关卡")

    # --------------------------------------------------------------- FBX 导入
    def importFile(self):
        """兼容旧调用名称；实际执行明确命名的【导入 FBX】流程。"""
        self.importFBX()

    def importFBX(self, item=None):
        """
        从 ``<场景资产>/FBX`` 导入静态网格体；不读取 UE 发布包。
        """
        if isinstance(item, bool):
            item = None
        item = item or self.main_listWgt.currentItem()
        selected_types = self.type_listWgt.selectedItems()
        if item is None or not selected_types:
            self.infoMsg("warning", u"请先选择一张场景资产卡片")
            return
        currentProject = str(self.proj_comb.currentText())
        currentType = str(selected_types[0].text())
        if currentType != "Map":
            item_data = item.itemData()
            try:
                role_name = str(item_data[1])
            except (IndexError, TypeError):
                self.infoMsg("error", u"场景卡片数据无效，无法取得资产名")
                return
            path = os.path.join(
                str(commonSetting()['rootPath']), currentProject, "Scenes",
                currentType, role_name, "FBX")
            if not os.path.isdir(path):
                message = u"没有找到 FBX 发布目录：{0}".format(path)
                self.infoMsg("warning", message)
                QtWidgets.QMessageBox.warning(self, u"导入 FBX 失败", message)
                return
            fbx_files = sorted(
                (name for name in os.listdir(path)
                 if name.lower().endswith(".fbx")
                 and os.path.isfile(os.path.join(path, name))),
                key=str.lower)
            if not fbx_files:
                message = u"FBX 发布目录中没有 .fbx 文件：{0}".format(path)
                self.infoMsg("warning", message)
                QtWidgets.QMessageBox.warning(self, u"导入 FBX 失败", message)
                return

            scenes_folder = '/Game/Scenes/{0}/{1}/'.format(
                currentType, role_name)
            material_folder = scenes_folder + 'Material/'
            texture_folder = scenes_folder + 'Texture/'
            max_folder = scenes_folder + 'Max/'
            AF = assetFunctions.AssetFunctions()
            for name in fbx_files:
                fbx_path = os.path.join(path, name).replace('\\', '/')
                animation_mesh_task = AF.buildImportTask(
                    fbx_path, scenes_folder, AF.buildStaticMeshImportOptions())
                AF.executeImportTasks([animation_mesh_task])
            for folder in (material_folder, texture_folder, max_folder):
                if not unreal.EditorAssetLibrary.does_directory_exist(folder):
                    unreal.EditorAssetLibrary.make_directory(folder)
            self.repathAssets(scenes_folder)
            self.infoMsg(
                "info", u"FBX 导入完成：{0}（{1} 个文件）".format(
                    role_name, len(fbx_files)))
        else:
            self.infoMsg("warning", u"Map 不能通过 FBX 导入；请使用【加载资产】迁移 .umap")

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
        """返回当前场景卡片的旧版发布路径。"""
        item = self.main_listWgt.currentItem()
        if item is None:
            return {}
        item_data = item.itemData()
        try:
            role_name = str(item_data[1])
            project, scene_type, _unused = self.getPanelsData()
        except (IndexError, TypeError, AttributeError):
            return {}
        asset_root = os.path.join(
            str(commonSetting()['rootPath']), project, "Scenes",
            scene_type, role_name)
        return {
            'Assembly': os.path.join(
                asset_root, 'Assembly', role_name + '_AD.ma'),
            'Icon': os.path.join(asset_root, 'Icon', role_name + '.png'),
            'GPU': os.path.join(asset_root, 'GPU', role_name + '_GPU.abc'),
            'Mod': os.path.join(asset_root, 'Mod', role_name + '_mod.ma'),
        }

    def shutdownThreads(self):
        """停止场景页的 UE 包扫描/迁移任务，防止关闭窗口时销毁运行中线程。"""
        self._status_editor.shutdown()
        self._state_generation += 1
        jobs = list(self._state_jobs)
        for thread, worker in jobs:
            worker.cancel()
            thread.requestInterruption()
            thread.quit()
        if self._copy_worker is not None:
            self._copy_worker.cancel()
        if self._copy_thread is not None:
            self._copy_thread.requestInterruption()
            self._copy_thread.quit()

        for thread, _worker in jobs:
            try:
                thread.wait(1500)
            except RuntimeError:
                pass
        if self._copy_thread is not None:
            try:
                self._copy_thread.wait(3000)
            except RuntimeError:
                pass

        remaining = list(jobs)
        if self._copy_thread is not None and self._copy_worker is not None:
            remaining.append((self._copy_thread, self._copy_worker))
        for job in remaining:
            thread, _worker = job
            try:
                running = thread.isRunning()
            except RuntimeError:
                running = False
            if running and job not in _DRAINING_THREAD_JOBS:
                _DRAINING_THREAD_JOBS.append(job)
                thread.finished.connect(partial(_releaseDrainingJob, job))

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
