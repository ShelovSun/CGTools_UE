#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/10/2020 by Sunxh<175702994@qq.com>

import os
import unreal
import socket


scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')


def projectSetting():
    data = {u'menu': {u'AssetsManager': {
                          # 最终版已接管唯一正式入口；旧代码仅保存在 Build 备份目录。
                          u'command': u"import AssetsManagerForUE.AssetsManagerForUE as AM;AM.showWindow()",
                          u'section': u'Pipeline', 
                          u'type': u'PYTHON', 
                          u'label': u'AssetsManager'},
                      # 原生可停靠(UMG)版暂时下线；文件保留，需要时取消注释即可恢复菜单项
                      # u'AssetsManagerNative': {
                      #     u'command': u"import Common as I;I.run_utilityWidget(content_widget_path='/Engine/Python/scripts/AssetsManagerForUE/AssetsManager_WBG')",
                      #     u'section': u'Assets', 
                      #     u'type': u'PYTHON', 
                      #     u'label': u'AssetsManager(原生可停靠)'},
                      u'ShotsManager': {
                          u'command': u"import ShotsManagerForUE.ShotsManager_UE as SM;SM.showWin()",
                          u'section': u'Pipeline', 
                          u'type': u'PYTHON', 
                          u'label': u'ShotsManager'},
                      u'ExtContentBrowser': {
                          u'command': u"import unreal;unreal.UAssetBrowserLibrary.open_browser()",
                          u'section': u'Pipeline', 
                          u'type': u'PYTHON', 
                          u'label': u'ExtContentBrowser'},
                      u'AnimSP': {
                          u'command': u"import Common as I;I.run_utilityWidget(content_widget_path='/Engine/Python/scripts/动画样条K帧/样条线交互工具_WBG')",
                          u'section': u'Anim', 
                          u'type': u'PYTHON', 
                          u'label': u'动画样条线工具'},
                      u'AnimLP': {
                          u'command': u"import Common as I;I.run_utilityWidget(content_widget_path='/Engine/Python/scripts/动画样条K帧/样条线锁帧工具_WBG')",
                          u'section': u'Anim', 
                          u'type': u'PYTHON', 
                          u'label': u'样条线锁帧工具'},
                      u'Blueprint': {
                          u'command': u"import Common as I;I.run_utilityWidget(content_widget_path='/Engine/Python/scripts/通用蓝图快速生成/通用蓝图快速生成')",
                          u'section': u'Bp', 
                          u'type': u'PYTHON', 
                          u'label': u'蓝图加载工具'},
                      u'BCache': {
                          u'command': u"",
                          u'section': u'Bp', 
                          u'type': u'PYTHON', 
                          u'label': u'蓝图缓存工具'},
                      u'LGT_Set 2.0.2': {
                          u'command': "import Common as I;I.run_utilityWidget()", 
                          u'section': u'Render',
                          u'type': u'PYTHON', 
                          u'label': u'灯光分层工具'},
                      u'UE_dir': {
                          u'command': "import Common as I;I.find_ue_dir()", 
                          u'section': u'Render',
                          u'type': u'PYTHON', 
                          u'label': u'渲染农场提交路径'},
                      u'UELoader': {
                          u'command': u"import UELoader.UELoader as LOAD;LOAD.showWin()",
                          u'section': u'Other', 
                          u'type': u'PYTHON', 
                          u'label': u'UELoader'},
                      u'Document': {
                          u'command': u"import webbrowser;webbrowser.open_new_tab('https://space.bilibili.com/475139733')",
                          u'section': u'Other', 
                          u'type': u'PYTHON', 
                          u'label': u'帮助'},},
            u'section': {u'Pipeline': u'流程:', 
                         u'Anim': u'动画：', 
                         u'Bp': u'蓝图：', 
                         u'Render': u'渲染:', 
                         u'Other': u'其他:',}}
    return data


type_map = {'COMMAND': unreal.ToolMenuStringCommandType.COMMAND, 'PYTHON': unreal.ToolMenuStringCommandType.PYTHON}


def run_utilityWidget(content_widget_path='/Engine/Python/scripts/LGTSet_v2'):
    """
    跑灯光设置插件
    """
    # if os.path.isfile(widget_file):
    if unreal.EditorAssetLibrary.does_asset_exist(content_widget_path):
        widget_asset = unreal.EditorAssetLibrary.load_asset(content_widget_path)
        editor_utility_subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        editor_utility_subsystem.spawn_and_register_tab(widget_asset)
    else:
        unreal.log_warning("%s is not exist！！！" % content_widget_path)


def find_ue_dir():
    """获取工程路径,DeadlineComment路径"""
    ip = get_local_ip()
    print(ip)
    project_dir = get_local_project()
    print(project_dir)
    path = r"\\" + os.path.normpath(os.path.join(ip, project_dir.split(":/")[-1]))
    print(path)
    unreal.EditorDialog.show_message("工程UNC路径：", f"{path}", unreal.AppMsgType.OK)


def get_local_project():
    """动态获取工程地址"""
    project_dir = unreal.Paths.project_dir()
    # project_dir = unreal.Paths.get_project_file_path()
    # 注意：返回的是相对路径（通常以 ../../../ 开头），建议转换为绝对路径
    absolute_project_dir = unreal.Paths.convert_relative_path_to_full(project_dir)
    return absolute_project_dir


def get_local_ip():
    """动态获取本机 IP 地址"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 这里不需要真实连接，只是为了获取本地出站 IP
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def create_menu():
    """
    V create MainMenu（下面可以有确定分组：File，Edit，Window，Help...），
    测试过用 “ MainFrame.MainMenu.File ”也是出现在菜单栏上
    :return:
    """
    menu_section_dict = projectSetting()['section']
    menu_entry_dict = projectSetting()['menu']
    menus = unreal.ToolMenus.get()
    main_menu = menus.find_menu('LevelEditor.MainMenu')
    if not main_menu:
        raise RuntimeError("Failed to find the 'Main' menu. Something is wrong in the force!")
    script_menu = main_menu.add_sub_menu(main_menu.get_name(), 'Tools', 'CG_Tools', ':: CGTools ::')
    for section, label in menu_section_dict.items():
        script_menu.add_section(section, label)

    for menu, data in menu_entry_dict.items():
        entry = unreal.ToolMenuEntry(name=menu, type=unreal.MultiBlockType.MENU_ENTRY,
                                     insert_position=unreal.ToolMenuInsert('', unreal.ToolMenuInsertType.FIRST))
        entry.set_label(data.get('label', 'untitle'))
        icon = data.get('icon')
        if icon:
            # icon 可以是字符串(图标名)或 (style_set, style_name) 元组
            if isinstance(icon, (list, tuple)):
                entry.set_icon(*icon)
            else:
                entry.set_icon('EditorStyle', icon)
        command = data.get('command', '')
        entry.set_string_command(type_map[data.get('type', 0)], '', string=command)
        script_menu.add_menu_entry(data.get('section', ''), entry)

    menus.refresh_all_widgets()


def create_toolBar():
    """
    X create LevelEditorToolBar  UE4可以，UE5工具栏不叫LevelEditorToolBar或者取消ToolBar了，未解决！
    :return:
    """
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu("LevelEditor.LevelEditorToolBar")

    entry = unreal.ToolMenuEntry(type=unreal.MultiBlockType.TOOL_BAR_BUTTON)
    entry.set_label("AM")

    typ = unreal.ToolMenuStringCommandType.PYTHON
    entry.set_string_command(typ, "", 'print "Hello World!"')

    section_name = 'Play'
    menu.add_menu_entry(section_name, entry)
    menus.refresh_all_widgets()  # 动态菜单不用刷新，静态菜单要刷新下


def create_folder_contextMenu():
    """
    V create FolderContextMenu
    :return:
    """
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu("ContentBrowser.FolderContextMenu")
    # Set the button type and label
    entry = unreal.ToolMenuEntry(type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label(u"文件夹右键测试")
    # Set button command, add button
    typ = unreal.ToolMenuStringCommandType.PYTHON
    entry.set_string_command(typ, "", 'print "这是文件夹的右键测试"')
    menu.add_menu_entry('CommonAssetActions', entry)


def create_asset_contextMenu():
    """
    V create AssetContextMenu（下面可以规定确定类型才有菜单：SoundWave，LevelSequence，CameraAnim...）测试通过可行
    :return:
    """
    # print("######### 加载内容库右键菜单 #########")
    # menus = unreal.ToolMenus.get()
    # menu_name = "ContentBrowser.AssetContextMenu"
    # menu = menus.find_menu(menu_name)
    # # Set the button type and label
    # entry = unreal.ToolMenuEntry(type=unreal.MultiBlockType.MENU_ENTRY)
    # entry.set_label(u"内容浏览器右键测试")
    # # Set button command, add button
    # entry.set_icon("EditorStyle", "ContentBrowser.AssetActions.Migrate")  # 未出现图标，没解决
    # entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "",
    #                          u"import UEPublisher.ue_publisher as Pub;Pub.showWin()")
    # menu.add_menu_entry('CommonAssetActions', entry)


def create_sequence_contextMenu():
    """
    X create SequenceContextMenu
    :return:
    """
    print("######### 加载定序器菜单 #########")
    menus = unreal.ToolMenus.get()
    menu_name = "MainFrame.MainMenu.File"
    menu = menus.find_menu(menu_name)
    entry = unreal.ToolMenuEntry(type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label(u"测试用菜单")
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "",
                             u"import UEPublisher.ue_sequence_export as Exp;Exp.do_it()")
    menu.add_menu_entry('BaseCommands', entry)
    menus.refresh_all_widgets()


def create_outliner_contextMenu():
    """
    V create AssetContextMenu
    :return:
    """
    print("######### 加载大纲菜单 #########")
    menus = unreal.ToolMenus.get()
    menu_name = "LevelEditor.LevelEditorSceneOutliner.ContextMenu"
    menu = menus.find_menu(menu_name)
    # Set the button type and label
    entry = unreal.ToolMenuEntry(type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label(u"测试用大纲菜单")
    # Set button command, add button
    # entry.set_icon("EditorStyle", "ContentBrowser.AssetActions.Migrate")  # 未出现图标，没解决
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "",
                             u"import UEPublisher.ue_publisher as Pub;Pub.showWin()")
    menu.add_menu_entry('CommonAssetActions', entry)


# def witch_project():
#     if unreal.EditorAssetLibrary.does_asset_exist("/Game/GOF_setup.GOF_setup"):
#         return "GOF"
#     elif unreal.EditorAssetLibrary.does_asset_exist("/Game/GOT_setup.GOT_setup"):
#         return "GOT"
#     else:
#         return None


# def migrate_asset():
#     selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
#     print(selected_assets)
#     if not selected_assets:
#         unreal.log_warning("没有选中的资产！请先选中需要迁移的资产")
#         return
#     selected_assets_paths = [i.get_path_name() for i in selected_assets]
#     # print(selected_assets_paths)
#     project = witch_project()
#     print(project)
#     export_path = selected_assets_paths[0].replace("/Game/", f"Y:/MCCProject/{project}/")
#     # if os.path.exists(export_path):
#
#     import tkinter as tk
#     from tkinter import filedialog
#     root = tk.Tk()
#     root.withdraw()
#     target_folder = filedialog.askdirectory(initialdir=export_path, title="选择迁移文件夹")
#     # target_folder = unreal.EditorDialogLibrary.open_directory_dialog(window_title="选择迁移文件夹")
#     # print(target_folder)
#     if target_folder and target_folder != "":
#         content_folder = os.path.join(target_folder, "Content")
#         if not os.path.exists(content_folder):
#             os.makedirs(content_folder)
#
#         # 获取 AssetTools
#         asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
#         asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
#
#         dependency_options = unreal.AssetRegistryDependencyOptions()
#         dependency_options.include_hard_management_references = True
#         dependency_options.include_hard_package_references = True
#         dependency_options.include_searchable_names = True
#         dependency_options.include_soft_management_references = True  # 可根据需要设 True
#         dependency_options.include_soft_package_references = True
#
#         all_package_names = set()
#         all_packages = set()
#
#         for asset_path in selected_assets_paths:
#             package_name = unreal.PackageTools.filename_to_package_name(asset_path)
#             all_package_names.add(package_name)
#
#             dependencies = asset_registry.get_dependencies(package_name, dependency_options)
#
#             for dep in dependencies:
#                 all_package_names.add(dep)
#
#         for pkg_name in all_package_names:
#             pkg_obj = unreal.find_package(pkg_name)
#             if not pkg_obj:
#                 # 如果未加载，尝试加载
#                 pkg_obj = unreal.load_package(None, pkg_name)
#             if pkg_obj:
#                 all_packages.add(pkg_obj)
#             else:
#                 unreal.log_warning(f"未找到 Package：{pkg_name}")
#
#         if not all_packages:
#             unreal.log_error("未收集到可迁移的 Package！")
#             return
#
#         # 执行迁移
#         try:
#             shutil.copy2('Y:/ACTools/CGTools/UnrealEngine/迁移Asset专用工程.uproject', target_folder)
#         except:
#             pass
#         unreal.log("正在迁移{}到: {}".format(list(all_package_names), content_folder))
#         success = asset_tools.migrate_packages(list(all_package_names), content_folder,
#                                                options=[unreal.AssetMigrationConflict.OVERWRITE, ''])
#
#         if success:
#             unreal.log("迁移完成！")
#         else:
#             unreal.log_warning("迁移失败或没有资产被迁移。")


create_menu()
create_asset_contextMenu()
create_sequence_contextMenu()
# create_outliner_contextMenu()


