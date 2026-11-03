#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/10/2020 by Sunxh<175702994@qq.com>

import os
import shutil
import sys
import unreal

sys.path.append('Y:\\ACTools\\Python\\UE5.03\\venv\\Lib\\site-packages')
from PySide2.QtCore import *
from PySide2.QtWidgets import *


class UEPublisherUI(object):
    def setupUi(self, Dialog):
        # super(UEPublisherUI, self).__init__(parent)
        self.dialog = Dialog
        self.dialog.resize(500, 150)
        self.dialog.setWindowTitle(u"发布UE资产")
        self.dialog.setStyleSheet("background-color: #1c1c1c;color: #b9b9b9;")
        # sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        # sizePolicy.setHorizontalStretch(8)
        # sizePolicy.setVerticalStretch(11)
        # sizePolicy.setHeightForWidth(Dialog.sizePolicy().hasHeightForWidth())
        # Dialog.setSizePolicy(sizePolicy)

        self.title = QLabel("将发布资产到下面路径，确定吗？")

        self.lineEdit = QLineEdit(self.dialog)
        self.lineEdit.setFixedHeight(30)

        self.folder_btn = QPushButton("...", self.dialog)
        self.folder_btn.setObjectName(u"pushButton")
        self.folder_btn.setFixedSize(QSize(25, 30))
        self.folder_btn.clicked.connect(self.search_folder)

        self.yes_btn = QPushButton("确定", self.dialog)
        self.yes_btn.clicked.connect(self.migrate_asset)
        self.cancel_btn = QPushButton("取消", self.dialog)
        self.cancel_btn.clicked.connect(self.dialog.close)

        mainLayout = QVBoxLayout(self.dialog)
        mainLayout.setSpacing(6)
        mainLayout.setObjectName(u"verticalLayout")
        mainLayout.setContentsMargins(-1, 0, -1, -1)
        mainLayout.addWidget(self.title)
        hLayout = QHBoxLayout(self.dialog)
        hLayout.addWidget(self.lineEdit)
        hLayout.addWidget(self.folder_btn)
        mainLayout.addLayout(hLayout)
        hLayout2 = QHBoxLayout(self.dialog)
        hLayout2.addWidget(self.yes_btn)
        hLayout2.addWidget(self.cancel_btn)
        mainLayout.addLayout(hLayout2)
        # self.setLayout(mainLayout)
        self.dialog.show()
        self.witch_folder()

    def witch_project(self):
        if unreal.EditorAssetLibrary.does_asset_exist("/Game/GOF_setup.GOF_setup"):
            return "GOF"
        elif unreal.EditorAssetLibrary.does_asset_exist("/Game/GOT_setup.GOT_setup"):
            return "GOT"
        else:
            return None

    def witch_folder(self):
        project = self.witch_project()
        # print(project)
        selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
        # print(selected_assets)
        if not selected_assets:
            unreal.log_warning("没有选中的资产！请先选中需要迁移的资产")
            return
        selected_assets_paths = [i.get_path_name() for i in selected_assets]
        # print(selected_assets_paths)
        export_path = os.path.dirname(selected_assets_paths[0]).replace("/Game/", f"Y:/MCCProject/{project}/")
        if os.path.exists(export_path):
            content_folder = os.path.join(export_path, "Content")
            if not os.path.exists(content_folder):
                os.makedirs(content_folder)
            self.lineEdit.setText(content_folder)
            return content_folder
        else:
            self.lineEdit.setText("找不到资产路径！")
            return None

    def search_folder(self):
        export_folder = QFileDialog.getExistingDirectory(options=QFileDialog.ShowDirsOnly)
        self.lineEdit.setText(export_folder)

    def migrate_asset(self):
        target_folder = self.lineEdit.text()
        if os.path.exists(target_folder):
            # 获取 AssetTools
            asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

            dependency_options = unreal.AssetRegistryDependencyOptions()
            dependency_options.include_hard_management_references = True
            dependency_options.include_hard_package_references = True
            dependency_options.include_searchable_names = True
            dependency_options.include_soft_management_references = True  # 可根据需要设 True
            dependency_options.include_soft_package_references = True

            # 收集所有关联package
            all_package_names = set()
            all_packages = set()

            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            selected_assets_paths = [i.get_path_name() for i in selected_assets]
            for asset_path in selected_assets_paths:
                package_name = unreal.PackageTools.filename_to_package_name(asset_path)
                all_package_names.add(package_name)

                dependencies = asset_registry.get_dependencies(package_name, dependency_options)

                for dep in dependencies:
                    all_package_names.add(dep)

            for pkg_name in all_package_names:
                pkg_obj = unreal.find_package(pkg_name)
                if not pkg_obj:
                    # 如果未加载，尝试加载
                    pkg_obj = unreal.load_package(None, pkg_name)
                if pkg_obj:
                    all_packages.add(pkg_obj)
                else:
                    unreal.log_warning(f"未找到 Package：{pkg_name}")

            if not all_packages:
                unreal.log_error("未收集到可迁移的 Package！")
                return

            # 执行迁移
            try:
                shutil.copy2('Y:/ACTools/CGTools/UnrealEngine/迁移Asset专用工程.uproject',
                             target_folder.replace("Content", ""))
            except:
                pass
            unreal.log("正在迁移{}到: {}".format(list(all_package_names), target_folder))
            self.dialog.close()
            success = asset_tools.migrate_packages(list(all_package_names), target_folder,
                                                   options=[unreal.AssetMigrationConflict.OVERWRITE, ''])

            # if success:
            unreal.EditorDialog.show_message(title="提示", message="迁移完成！", message_type=unreal.AppMsgType.OK,
                                             message_category=unreal.AppMsgCategory.SUCCESS)
            # else:
            #     unreal.log_warning("迁移失败或没有资产被迁移。")
        else:
            unreal.EditorDialog.show_message(title="提示", message="请选择一个可用文件夹", message_type=unreal.AppMsgType.OK)

    # def load_uasset(self, uassetpath):
    #     '''拷贝uassetpath的内容到Content目录下'''
        # flodername = uassetpath.split('/')[-1]
        # contentpath = unreal.Paths.project_content_dir()
        # contentfile = os.listdir(contentpath)
        # if os.path.isdir(uassetpath):
        #     if flodername not in contentfile:
        #         try:
        #             copytree(uassetpath, contentpath + flodername)
        #             print("%s is loaded!!" % flodername)
        #             msgBox = QMessageBox()
        #             msgBox.setText(u"%s 成功加载！请保存重启UE！！" % flodername)
        #             msgBox.exec_()
        #         except:
        #             unreal.log_warning("%s load failed!!" % flodername)
        #     else:
        #         unreal.log_warning("%s is exist in content!!! load failed!!" % flodername)
        #         msgBox = QMessageBox()
        #         msgBox.setText(u"%s 已存在工程中，加载失败！！" % flodername)
        #         msgBox.exec_()
        # else:
        #     unreal.log_warning("%s is not exist！！！" % uassetpath)
        #     msgBox = QMessageBox()
        #     msgBox.setText(u"%s不存在，加载失败！请联系管理员" % flodername)
        #     msgBox.exec_()

    # def load_abc(self, Dialog, static=False):
    #     """ """
        # exportABC = QFileDialog.getExistingDirectory(options=QFileDialog.ShowDirsOnly)
        # files, selectedFilter = QFileDialog.getOpenFileNames(Dialog, u"选择abc文件导入", "/home", "ABC(*.abc)")
        # print(files)
        # character_folder = '/Game/Scenes/FX/SnowMesh/Cache'
        # for i in files:
        #     AF = assetFunctions.AssetFunctions()
        #     asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        #     asset_list_before = asset_reg.get_assets_by_path(character_folder)
        #     if static:
        #         animation_mesh_task = AF.buildImportTask(i, character_folder, AF.buildABCImportOptions_static())
        #     else:
        #         animation_mesh_task = AF.buildImportTask(i, character_folder, AF.buildABCImportOptions())
        #     AF.executeImportTasks([animation_mesh_task])


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
    ui = UEPublisherUI()
    ui.setupUi(win)
    win._ui = ui  # 保活，避免 UI 对象被回收

    import ue_qt_host
    ue_qt_host.host_window(win, app=app)

# def showWin():
#     app = QApplication.instance()
#     if app is None:
#         app = QApplication(sys.argv)
#
#     w = UEPublisherUI()
#     # w.setWindowFlags(Qt.WindowStaysOnTopHint)
#     w.show()
#     sys.exit(app.exec_())


# def loadEnginePlugin(pluginpath):
#     # pluginpath='Y:/Onemt/Marketing/Shared/Plug-in/LGTSet_UE/Plugins/GetRGB'
#     flodername = pluginpath.split('/')[-1]
#     enginePluginsPath = unreal.Paths.engine_plugins_dir()
#     pluginfile = os.listdir(enginePluginsPath)
#     if os.path.isdir(pluginpath):
#         if flodername not in pluginfile:
#             try:
#                 copytree(pluginpath, enginePluginsPath + flodername)
#                 print("%s is loaded!!" % flodername)
#             except:
#                 unreal.log_warning("%s load failed!!" % flodername)
#         else:
#             unreal.log_warning("%s is exist in project's plugin!!! load failed!!" % flodername)
#     else:
#         unreal.log_warning("%s is not exist！！！" % pluginpath)
#
#
# def loadProjectPlugin():
#     """ """
#
#
# def copytree(src, dst, symlinks=False, ignore=None):
#     '''拷贝'''
#     if not os.path.exists(dst):
#         os.makedirs(dst)
#         shutil.copystat(src, dst)
#     lst = os.listdir(src)
#     if ignore:
#         excl = ignore(src, lst)
#         lst = [x for x in lst if x not in excl]
#     for item in lst:
#         s = os.path.join(src, item)
#         d = os.path.join(dst, item)
#         if symlinks and os.path.islink(s):
#             if os.path.lexists(d):
#                 os.remove(d)
#             os.symlink(os.readlink(s), d)
#             try:
#                 st = os.lstat(s)
#                 mode = stat.S_IMODE(st.st_mode)
#                 os.lchmod(d, mode)
#             except:
#                 pass  # lchmod not available
#         elif os.path.isdir(s):
#             copytree(s, d, symlinks, ignore)
#         else:
#             shutil.copy2(s, d)
#
#
# def run_utilitywidget(widgetpath):
#     '''跑widget'''
#     # widgetpath='/Game/Script/ONEMTLGTSet_v2'
#     contentpath = unreal.Paths.project_content_dir()
#     widgetfile = contentpath + widgetpath.split('Game/')[1] + ".uasset"
#     if os.path.isfile(widgetfile):
#         widget_asset = unreal.EditorAssetLibrary.load_asset(widgetpath)
#         editor_utility_subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
#         editor_utility_subsystem.spawn_and_register_tab(widget_asset)
#     else:
#         unreal.log_warning("%s is not exist！！！" % widgetfile)
