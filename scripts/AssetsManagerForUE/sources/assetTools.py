#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <AssetsManager_UE>Created: 19/10/2020 by Sunxh<175702994@qq.com>
# UI 已由 .ui + QUiLoader 改为纯 Python 代码搭建（build_ui），彻底绕开 QtUiTools 冷启动。

import os
import sys
import time
import unreal

# 添加venv路径，确保UE能找到PySide6
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
venv_path = r"Y:/MCCTools/src/venv/Lib/site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from PySide6 import QtWidgets, QtCore, QtGui

from functools import partial
from ..utils import assetFunctions, messageBox, myWidget
from ..config import commonSetting
from . import ue_asset_service

_FLAT = "border-style: flat; background: transparent;"
_DRAINING_THREAD_JOBS = []


def _releaseDrainingJob(job):
    try:
        _DRAINING_THREAD_JOBS.remove(job)
    except ValueError:
        pass


def _fetch_database(host, user, password, project, asset_type):
    """后台线程可调用的纯数据库查询；不接触任何 Qt 控件。"""
    import psycopg2

    conn = None
    cur = None
    query = '''
         SELECT "asset.date", "asset.name", "asset.zh_name", "asset.mod_artist", "asset.mod_status",
         "asset.rig_artist", "asset.rig_status", "asset.icon", "asset.note"
         FROM public."asset"
         WHERE "asset.type" = %s;
         '''
    try:
        conn = psycopg2.connect(
            database=project,
            user=user,
            password=password,
            host=host,
            port="5432",
            connect_timeout=4,
        )
        cur = conn.cursor()
        cur.execute(query, (asset_type,))
        return cur.fetchall()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


class _StartupSignals(QtCore.QObject):
    loaded = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class _StartupTask(QtCore.QRunnable):
    """首次网络配置 + PostgreSQL 查询，完整运行在后台线程。"""

    def __init__(self, host, user, password, is_sql, project_index, type_index):
        super(_StartupTask, self).__init__()
        self.signals = _StartupSignals()
        self.host = host
        self.user = user
        self.password = password
        self.is_sql = is_sql
        self.project_index = project_index
        self.type_index = type_index

    @staticmethod
    def _index(value, count):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return max(0, min(value, count - 1)) if count else -1

    def run(self):
        try:
            settings = commonSetting()
            projects = list(settings.get("DataBase") or [])
            asset_types = list(settings.get("type") or [])
            project_index = self._index(self.project_index, len(projects))
            type_index = self._index(self.type_index, len(asset_types))
            rows = []
            if self.is_sql and project_index >= 0 and type_index >= 0:
                rows = _fetch_database(
                    self.host,
                    self.user,
                    self.password,
                    projects[project_index],
                    asset_types[type_index],
                )
            self.signals.loaded.emit({
                "settings": settings,
                "project_index": project_index,
                "type_index": type_index,
                "rows": rows,
            })
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class _QuerySignals(QtCore.QObject):
    loaded = QtCore.Signal(int, object)
    failed = QtCore.Signal(int, str)


class _QueryTask(QtCore.QRunnable):
    """项目/类型切换和刷新使用的后台数据库查询。"""

    def __init__(self, generation, host, user, password, project, asset_type):
        super(_QueryTask, self).__init__()
        self.signals = _QuerySignals()
        self.generation = generation
        self.host = host
        self.user = user
        self.password = password
        self.project = project
        self.asset_type = asset_type

    def run(self):
        try:
            rows = _fetch_database(
                self.host, self.user, self.password, self.project, self.asset_type)
            self.signals.loaded.emit(self.generation, rows)
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))


# 进程级数据线程池不隶属于窗口；关闭窗口时不会等待仍在网络超时中的查询。
_DATA_THREAD_POOL = QtCore.QThreadPool()
_DATA_THREAD_POOL.setMaxThreadCount(2)


class AssetToolsUI(QtWidgets.QWidget):
    scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')

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
        self._state_generation = 0
        self._state_jobs = []
        self._copy_thread = None
        self._copy_worker = None
        self._copy_item_key = ""

        self._query_generation = 0
        self._query_tasks = {}
        self._startup_task = None
        self._data_pool = _DATA_THREAD_POOL

        # 同步搭建界面（纯控件、无 I/O，秒级）→ 窗口一显示即最终布局，不闪。
        self.build_ui()
        # 网络配置、psycopg2 冷导入和第一次查询都交给真正的后台任务。
        # 0ms 定时器让本控件先返回给主窗口，窗口可先完成一次绘制。
        QtCore.QTimer.singleShot(0, self._startInitialLoad)

    # ------------------------------------------------------------------ UI 搭建
    def build_ui(self):
        """纯代码搭建界面：左侧筛选、中间资产卡片、右侧 FBX/皮肤预览与动作库。"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        self.mainWindow_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.mainWindow_splitter.setObjectName("AssetMainSplitter")
        self.mainWindow_splitter.setHandleWidth(5)
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
        self.asset_list_header = myWidget.AssetListHeader(self.main_listWgt)
        self.asset_list_header.setSortIndicator(*self._current_sort)
        self.asset_list_header.sectionClicked.connect(self._do_sort)
        self.asset_list_header.setVisible(self.isList)
        self.main_listWgt.setListHeader(self.asset_list_header)
        midV.addWidget(self.asset_list_header)
        midV.addWidget(self.main_listWgt, 1)
        self.mainWindow_splitter.addWidget(mid)

        # ---- 右栏：FBX/OpenGL 预览在第一次选中资产时才创建 ----
        right = QtWidgets.QWidget()
        rightV = QtWidgets.QVBoxLayout(right)
        rightV.setContentsMargins(0, 0, 0, 0)
        rightV.setSpacing(0)
        self.detail_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.detail_splitter.setObjectName("AssetDetailsSplitter")
        self.detail_splitter.setHandleWidth(5)
        self.detail_splitter.setChildrenCollapsible(False)

        self._preview_host = QtWidgets.QWidget()
        self._preview_host_layout = QtWidgets.QVBoxLayout(self._preview_host)
        self._preview_host_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_host_layout.setSpacing(0)
        self.preview_wgt = None
        self.action_wgt = None
        self._preview_placeholder = QtWidgets.QLabel(u"选择资产后加载 FBX 预览")
        self._preview_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._preview_placeholder.setMinimumHeight(160)
        self._preview_placeholder.setStyleSheet(
            "background:#242528; color:#858585; border:1px solid #151515;")
        self._preview_host_layout.addWidget(self._preview_placeholder, 1)

        self._action_host = QtWidgets.QWidget()
        self._action_host_layout = QtWidgets.QVBoxLayout(self._action_host)
        self._action_host_layout.setContentsMargins(0, 0, 0, 0)
        self._action_host_layout.setSpacing(0)
        self._action_placeholder = QtWidgets.QLabel(u"选择资产后显示动作库")
        self._action_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._action_placeholder.setStyleSheet(
            "background:#232427; color:#707070; border:1px solid #151515;")
        self._action_host_layout.addWidget(self._action_placeholder, 1)

        self.detail_splitter.addWidget(self._preview_host)
        self.detail_splitter.addWidget(self._action_host)
        self.detail_splitter.setStretchFactor(0, 3)
        self.detail_splitter.setStretchFactor(1, 2)
        self.detail_splitter.setSizes([340, 220])
        rightV.addWidget(self.detail_splitter, 1)
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
        self.refresh_Bttn.clicked.connect(self.refresh_asset)
        self.sort_bttn.clicked.connect(self.sort_asset_ui)
        self.key_line.returnPressed.connect(self.search_asset)
        self.main_listWgt.itemSelectionChanged.connect(self.listWidgetItemChanged)
        self.main_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.main_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.main_listWgt.assetDropRequested.connect(self.placeImportedAsset)
        self.main_listWgt.assetDragRejected.connect(
            lambda text: self.infoMsg("warning", text))
        self.detail_splitter.splitterMoved.connect(
            lambda _position, _index: self.rememberSettings())
        self.mainWindow_splitter.splitterMoved.connect(
            lambda _position, _index: self.rememberSettings())

    def _toolBtn(self, icon_name, tip):
        """工具栏小按钮：25x25、扁平透明、22 图标。"""
        b = QtWidgets.QPushButton()
        b.setFixedSize(25, 25)
        b.setIconSize(QtCore.QSize(22, 22))
        b.setIcon(QtGui.QIcon('%s/icon/%s' % (self.scriptsPath, icon_name)))
        b.setToolTip(tip)
        b.setStyleSheet(_FLAT)
        return b

    def _ensurePreviewWidgets(self):
        """首次选中资产时才导入并创建 FBX/OpenGL 预览，避免阻塞首开窗口。"""
        if self.preview_wgt is not None and self.action_wgt is not None:
            return True
        try:
            from ..utils.fbxpreview.am_previewGLWidget import PreviewGLWidget
            from ..utils.fbxpreview.am_actionWidget import AssetActionWidget

            preview = PreviewGLWidget(isPlayer=False)
            preview.setMinimumHeight(160)
            preview.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            action = AssetActionWidget()
            action.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            action.actionActivated.connect(self.on_action_selected)
            action.importActionRequested.connect(self.importActionFile)

            if self._preview_placeholder is not None:
                self._preview_host_layout.removeWidget(self._preview_placeholder)
                self._preview_placeholder.deleteLater()
                self._preview_placeholder = None
            if self._action_placeholder is not None:
                self._action_host_layout.removeWidget(self._action_placeholder)
                self._action_placeholder.deleteLater()
                self._action_placeholder = None
            self._preview_host_layout.addWidget(preview, 1)
            self._action_host_layout.addWidget(action, 1)
            self.preview_wgt = preview
            self.action_wgt = action
            return True
        except Exception as exc:
            self.infoMsg("error", u"FBX 预览器加载失败：{0}".format(exc))
            return False

    # ------------------------------------------------------------------ 数据/逻辑
    def rememberSettings(self):
        settings = QtCore.QSettings('AssetsUE', 'AssetsUESettings')
        settings.setValue('isList', self.isList)
        settings.setValue('thumbSize', self.itemSize_Slider.value())
        settings.setValue('project', self.project_comb.currentIndex())
        settings.setValue('typ', self.type_listWgt.currentRow())
        settings.setValue('detailSplitterSizes', self.detail_splitter.sizes())
        settings.setValue('mainSplitterSizes', self.mainWindow_splitter.sizes())

    def readSettings(self):
        settings = QtCore.QSettings('AssetsUE', 'AssetsUESettings')
        isList = settings.value('isList')
        thumbSize = settings.value('thumbSize')
        project = settings.value('project')
        typ = settings.value('typ')
        splitter_sizes = settings.value('detailSplitterSizes')
        main_splitter_sizes = settings.value('mainSplitterSizes')

        if isList is not None:
            if isList == 'true':
                self.isList = True
            else:
                self.isList = False

        if isinstance(splitter_sizes, (list, tuple)) and len(splitter_sizes) == 2:
            try:
                sizes = [max(1, int(value)) for value in splitter_sizes]
                self.detail_splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass
        if isinstance(main_splitter_sizes, (list, tuple)) and len(main_splitter_sizes) == 3:
            try:
                sizes = [max(1, int(value)) for value in main_splitter_sizes]
                self.mainWindow_splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass

        return thumbSize, project, typ

    def _startInitialLoad(self):
        """读取本机 UI 偏好后，把网络配置和首次数据库查询交给后台线程。"""
        thumbSize, project, typ = self.readSettings()
        if thumbSize is not None:
            try:
                self.itemSize_Slider.setValue(int(thumbSize))
            except (TypeError, ValueError):
                pass
        self.infoMsg("info", u"正在后台读取项目配置和资产数据…")
        task = _StartupTask(
            self.host, self.user, self.password, self.isSQL, project, typ)
        task.signals.loaded.connect(self._applyInitialLoad)
        task.signals.failed.connect(self._initialLoadFailed)
        self._startup_task = task
        self._data_pool.start(task)

    def _populateFilters(self, settings, project_index=0, type_index=0):
        """只在 UI 主线程中更新项目和类型控件。"""
        self.project_comb.blockSignals(True)
        self.type_listWgt.blockSignals(True)
        try:
            self.project_comb.clear()
            self.type_listWgt.clear()
            self.project_comb.addItems([str(value) for value in settings.get('DataBase', [])])
            for value in settings.get('type', []):
                item = QtWidgets.QListWidgetItem(str(value))
                icon = QtGui.QIcon()
                pixmap = myWidget.Pixmap('%s/icon/folder.svg' % self.scriptsPath)
                pixmap.setColor(QtGui.QColor("#b3b3b3"))
                icon.addPixmap(pixmap, QtGui.QIcon.Normal, QtGui.QIcon.Off)
                item.setIcon(icon)
                self.type_listWgt.addItem(item)
            if self.project_comb.count():
                self.project_comb.setCurrentIndex(max(0, int(project_index)))
            if self.type_listWgt.count():
                self.type_listWgt.setCurrentRow(max(0, int(type_index)))
        finally:
            self.project_comb.blockSignals(False)
            self.type_listWgt.blockSignals(False)

    def _applyInitialLoad(self, payload):
        self._startup_task = None
        self._populateFilters(
            payload.get("settings") or {},
            payload.get("project_index", 0),
            payload.get("type_index", 0),
        )
        self.listWidgetAddItems(payload.get("rows") or [])

    def _initialLoadFailed(self, error):
        self._startup_task = None
        self.infoMsg("error", u"资产数据加载失败：{0}".format(error))
        try:
            unreal.log_warning(u"AssetsManager 首次数据加载失败：{0}".format(error))
        except Exception:
            pass

    def firstView(self):
        """兼容旧调用；新版启动流程使用 _startInitialLoad 后台加载。"""
        thumbSize, project, typ = self.readSettings()
        if thumbSize is not None:
            self.itemSize_Slider.setValue(int(thumbSize))
        self._populateFilters(commonSetting(), project or 0, typ or 0)

    def update_project(self):
        self.project_comb.addItems(commonSetting()['DataBase'])

    def update_type(self):
        """
        设置type显示
        """
        for i in commonSetting()['type']:
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
        self._requestAssetData()

    def typeChanged(self):
        self.rememberSettings()
        self._requestAssetData()

    def openDir(self, dir_path):
        """
        'Show in Explorer'打开文件夹
        """
        folder_info = QtCore.QFileInfo(dir_path)
        if folder_info.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder_info.absoluteFilePath()))
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
        if self.preview_wgt is not None:
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
            self.asset_list_header.hide()
        else:
            self.displayThumb_bttn.setIcon(QtGui.QIcon('%s/icon/display_icon.png' % self.scriptsPath))
            self.displayThumb_bttn.setToolTip("缩略图显示")
            self.isList = True
            self.main_listWgt.setIsList(self.isList)
            self.main_listWgt.setListMode()
            self.asset_list_header.show()
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
            self.main_listWgt.setGridSize(QtCore.QSize(
                itemSize + self.main_listWgt.DEF_SPACING,
                itemSize + self.main_listWgt.DEF_SPACING + self.main_listWgt.textAreaHeight()))

    def itemSizeSliderReleased(self):
        self.rememberSettings()

    def update_asset(self):
        """用内存中的查询结果重建列表；该调用来自 UI 线程，无需伪 QThread。"""
        self.listWidgetAddItems()

    def refresh_asset(self):
        self._requestAssetData()

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
            (u'按备注排序', 7),
        ]
        for name, column in sort_columns:
            act = QtGui.QAction(name, self)
            act.triggered.connect(lambda checked=False, col=column: self._do_sort(col))
            menu.addAction(act)
        menu.exec_(self.sort_bttn.mapToGlobal(self.sort_bttn.rect().bottomLeft()))

    def _do_sort(self, column):
        """
        更新当前排序状态并重排列表：同一列再次点击 -> 反向；换列 -> 默认升序。
        column: 0=日期 1=资产名 2=中文名 3=模型制作 4=模型状态
                5=绑定制作 6=绑定状态 7=备注（数据中下标 8）
        """
        cur_col, cur_reverse = self._current_sort
        reverse = (not cur_reverse) if column == cur_col else False
        self._current_sort = (column, reverse)
        self.asset_list_header.setSortIndicator(column, reverse)
        self.listWidgetAddItems()  # 用现有数据按新排序状态重排重填(保留当前搜索过滤)

    def _sort_data(self, data):
        """ 按当前排序状态 self._current_sort 对数据列表就地排序。 """
        column, reverse = self._current_sort

        def sort_key(item_data):
            data_index = 8 if column == 7 else column
            try:
                value = item_data[data_index] if len(item_data) > data_index else None
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
        """兼容旧调用的同步查询；交互界面统一走 _requestAssetData 后台查询。"""
        try:
            return _fetch_database(
                self.host, self.user, self.password, _project, _type)
        except Exception as e:
            print(e)
            return []

    def _requestAssetData(self):
        """后台刷新当前项目/类型；generation 防止慢查询覆盖较新的选择。"""
        asset_type, project, _path = self.getTypeAndProject()
        if not self.isSQL or not project or not asset_type:
            self.listWidgetAddItems([])
            return
        self._query_generation += 1
        generation = self._query_generation
        self.infoMsg("info", u"正在后台读取 {0} / {1}…".format(project, asset_type))
        task = _QueryTask(
            generation, self.host, self.user, self.password, project, asset_type)
        task.signals.loaded.connect(self._assetDataLoaded)
        task.signals.failed.connect(self._assetDataFailed)
        self._query_tasks[generation] = task
        self._data_pool.start(task)

    def _assetDataLoaded(self, generation, rows):
        self._query_tasks.pop(generation, None)
        if generation != self._query_generation:
            return
        self.listWidgetAddItems(rows or [])

    def _assetDataFailed(self, generation, error):
        self._query_tasks.pop(generation, None)
        if generation != self._query_generation:
            return
        self.infoMsg("error", u"资产数据读取失败：{0}".format(error))
        try:
            unreal.log_warning(u"AssetsManager 数据读取失败：{0}".format(error))
        except Exception:
            pass

    def listWidgetAddItems(self, new_dict=None):
        """
        设置主面板FBX显示
        """
        self.main_listWgt.clear()
        if self.preview_wgt is not None:
            self.preview_wgt.clear()
        keyWords = self.key_line.text()

        start_time = time.time()
        if new_dict is not None:
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
        self.asset_list_header.setVisible(self.isList)
        self.asset_list_header.setSortIndicator(*self._current_sort)
        end_time = time.time()
        self.infoMsg("info", "%s items" % (self.main_listWgt.count()) +
                     '   Cost :  %.2f' % (end_time - start_time) + ' sec')
        self.scanUEAssetStates()

    def listWidgetItemChanged(self):
        """ 改变item触发：把选中资产喂给 FBX 三维预览 + 动作库 """
        currentSelected = self.main_listWgt.selectedItems()
        if currentSelected:
            if not self._ensurePreviewWidgets():
                return
            item_data = currentSelected[0].itemData()
            icon = item_data[7]
            '''喂给 FBX 预览：必须先 setTitle（GL 据 name 由 /Icon/→/FBX/ 推绑定文件），再 setPreviewPixmap'''
            self.preview_wgt.clear()
            self.preview_wgt.setTitle(item_data[1], item_data[2])
            self.preview_wgt.setPreviewPixmap(icon)
            '''列出该资产 Action 目录下的动作（递归），点击后 on_action_selected 套播'''
            self.action_wgt.setAsset(self.preview_wgt.deriveFbxPath(icon))
        else:
            if self.preview_wgt is not None:
                self.preview_wgt.clear()
            if self.action_wgt is not None:
                self.action_wgt.clear()

    def on_action_selected(self, action_path):
        """动作库选中：把该动作套到当前预览的绑定文件上循环播放；空路径回静态预览。"""
        if self.preview_wgt is not None:
            self.preview_wgt.playAction(action_path)

    def show_menu(self, point):
        """
        设置主面板右键菜单：旧 FBX Import 与新 UE 包加载并存。
        """
        currentItem = self.main_listWgt.itemAt(point)
        if currentItem is None:
            return
        self.main_listWgt.setCurrentItem(currentItem)
        menu = QtWidgets.QMenu(self.main_listWgt)
        show_action = QtGui.QAction('Show in Explorer', self)
        show_action.setIcon(QtGui.QIcon("{}/icon/folder_white.png".format(self.scriptsPath)))
        show_ue_action = QtGui.QAction(u'打开 UE 发布目录', self)
        load_action = QtGui.QAction(u'加载资产', self)
        imp_action = QtGui.QAction('Import FBX', self)
        locate_action = QtGui.QAction(u'在内容浏览器中定位', self)
        locate_action.setEnabled(bool(currentItem.ueMainObjectPath()))
        menu.addAction(show_action)
        menu.addAction(show_ue_action)
        menu.addSeparator()
        menu.addAction(load_action)
        menu.addAction(locate_action)
        menu.addSeparator()
        menu.addAction(imp_action)
        asset_root = ue_asset_service.asset_root_from_item_data(currentItem.itemData())
        show_action.triggered.connect(partial(self.openDir, asset_root))
        show_ue_action.triggered.connect(partial(self.openDir, os.path.join(asset_root, "UE")))
        load_action.triggered.connect(partial(self.loadUEAsset, currentItem))
        locate_action.triggered.connect(partial(self.locateUEAsset, currentItem))
        imp_action.triggered.connect(self.importFile)
        menu.exec_(QtGui.QCursor.pos())

    # ---------------------------------------------------------- UE 最终资产包
    def _findItemByKey(self, key):
        for index in range(self.main_listWgt.count()):
            item = self.main_listWgt.item(index)
            try:
                if str(item.itemData()[7]) == str(key):
                    return item
            except (IndexError, TypeError, RuntimeError):
                pass
        return None

    def scanUEAssetStates(self):
        """后台扫描每张卡片的 UE 发布/工程文件状态，避免网络盘阻塞 UI。"""
        self._state_generation += 1
        generation = self._state_generation
        for _thread, worker in list(self._state_jobs):
            worker.cancel()

        requests = []
        for index in range(self.main_listWgt.count()):
            item = self.main_listWgt.item(index)
            key = str(item.itemData()[7])
            root = ue_asset_service.asset_root_from_item_data(item.itemData())
            item.setUEState("scanning", u"正在检查 UE 发布资产…")
            requests.append((key, root))
        if not requests:
            return
        try:
            target_content = ue_asset_service.project_content_dir()
        except Exception as exc:
            self.infoMsg("error", str(exc))
            return

        thread = QtCore.QThread()
        worker = ue_asset_service.AssetStateWorker(generation, requests, target_content)
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
        self._state_jobs = [job for job in self._state_jobs if job[0] is not finished_thread]

    def _applyUEState(self, generation, key, plan):
        if generation != self._state_generation:
            return
        item = self._findItemByKey(key)
        if item is None:
            return
        if plan.get("state") == "ready":
            try:
                plan["main_object_path"] = ue_asset_service.resolve_placeable_object_path(plan)
                if not plan["main_object_path"]:
                    plan["state"] = "partial"
                    plan["message"] = u"UE 包已在工程中；未找到可直接拖放的 Actor 蓝图或网格体"
            except Exception:
                pass
        item.setUEState(plan.get("state"), plan.get("message"), plan)

    def loadUEAsset(self, item=None):
        """复制选中资产 UE 发布包；现有同名不同内容文件绝不自动覆盖。"""
        if isinstance(item, bool):  # QPushButton.clicked(bool)
            item = None
        item = item or self.main_listWgt.currentItem()
        if item is None:
            self.infoMsg("warning", u"请先选择一张资产卡片")
            return
        if self._copy_thread is not None and self._copy_thread.isRunning():
            self.infoMsg("warning", u"已有资产正在加载，请等待当前任务完成")
            return

        plan = item.uePlan()
        if not plan or plan.get("state") == "scanning":
            try:
                asset_root = ue_asset_service.asset_root_from_item_data(item.itemData())
                plan = ue_asset_service.build_import_plan(asset_root)
            except Exception as exc:
                item.setUEState("error", str(exc))
                self.infoMsg("error", str(exc))
                return
        # Revalidate on the explicit load click with SHA-1.  The lightweight
        # background card scan intentionally compares sizes only.
        plan = ue_asset_service.query_filesystem_state(
            plan, verify_content=True)
        # ``files`` 可能只有 .uexp/.ubulk 等 sidecar；没有 .uasset/.umap
        # 仍然不是一个可加载的 UE 包，不能把孤立 sidecar 复制进工程。
        if not plan.get("files") or not plan.get("package_object_paths"):
            message = plan.get("message") or u"没有找到该资产的 UE 发布文件"
            item.setUEState("missing", message, plan)
            self.infoMsg("warning", message)
            self._showMissingUEPackageDialog(plan, message)
            return
        if plan.get("state") == "conflict":
            item.setUEState("conflict", plan.get("message"), plan)
            self.infoMsg("warning", plan.get("message"))
            return
        if plan.get("state") == "ready":
            self._registerLoadedPlan(item, plan)
            return

        key = str(item.itemData()[7])
        self._copy_item_key = key
        item.setUEProgress(0, u"准备加载 UE 最终资产…")
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
        """用户主动点击【加载资产】但发布包不可用时给出模态提醒。"""
        asset_root = os.path.normpath(str((plan or {}).get("asset_root") or ""))
        release_root = os.path.join(asset_root, "UE") if asset_root else ""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(u"加载资产失败")
        box.setText(str(message or u"没有找到可加载的 UE 发布资产"))
        detail = (
            u"请确认资产的 UE 发布目录中至少包含一个完整的 .uasset 或 .umap 主包。\n"
            u"只有 .uexp、.ubulk 或 .uptnl 等附属文件不能单独加载。"
        )
        if release_root:
            detail += u"\n\n检查路径：{0}".format(release_root)
        box.setInformativeText(detail)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        box.setEscapeButton(QtWidgets.QMessageBox.Ok)
        box.exec()

    def _onCopyProgress(self, percent, name):
        key = self._copy_item_key
        item = self._findItemByKey(key)
        if item is not None:
            item.setUEProgress(percent, u"正在加载：{0}".format(name))
        self.infoMsg("info", u"加载资产 {0}%：{1}".format(percent, name))

    def _onCopyFinished(self, plan):
        key = self._copy_item_key
        item = self._findItemByKey(key)
        if item is None:
            return
        self._registerLoadedPlan(item, plan)

    def _registerLoadedPlan(self, item, plan):
        try:
            item.setUEProgress(100, u"正在刷新 UE Asset Registry…")
            plan = ue_asset_service.refresh_asset_registry(plan)
            item.setUEState(plan.get("state"), plan.get("message"), plan)
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
        key = self._copy_item_key
        item = self._findItemByKey(key)
        state = "conflict" if (u"同名不同" in message or u"目标文件" in message) else "error"
        if item is not None:
            item.setUEState(state, message)
        self.infoMsg("error", message)

    def _onCopyThreadFinished(self):
        self._copy_thread = None
        self._copy_worker = None
        self._copy_item_key = ""

    def locateUEAsset(self, item=None):
        item = item or self.main_listWgt.currentItem()
        if item is None or not item.ueMainObjectPath():
            self.infoMsg("warning", u"该资产尚未加载，或没有可定位的主资产")
            return
        if not ue_asset_service.sync_to_content_browser(item.ueMainObjectPath()):
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

    def shutdownThreads(self):
        """主窗口关闭前取消本页 I/O 任务，避免销毁仍在运行的 QThread。"""
        self._query_generation += 1
        self._query_tasks.clear()
        self._startup_task = None
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

        # 极慢 NAS 调用可能在等待窗口后仍未返回。把线程/worker 提升到模块级持有，
        # 直到 finished 再释放，避免关闭窗口时出现 QThread destroyed while running。
        remaining = list(jobs)
        if self._copy_thread is not None and self._copy_worker is not None:
            remaining.append((self._copy_thread, self._copy_worker))
        for job in remaining:
            thread, worker = job
            try:
                running = thread.isRunning()
            except RuntimeError:
                running = False
            if running and job not in _DRAINING_THREAD_JOBS:
                _DRAINING_THREAD_JOBS.append(job)
                thread.finished.connect(partial(_releaseDrainingJob, job))

    def getTypeAndProject(self):
        project = self.project_comb.currentText()
        currentType = self.type_listWgt.selectedItems()
        if not currentType:
            type = 'Default'
            path = None
        else:
            type = str(currentType[0].text())
            path = '%s/%s/Assets/%s' % (commonSetting()['rootPath'], project, type)
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
