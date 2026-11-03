#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/10/2020 by Sunxh<175702994@qq.com>


import unreal, json, os
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('/for_Maya','')

def Load_uasset(uassetpath):
    #uassetpath='Y:/Onemt/Marketing/Shared/Plug-in/LGTSet_UE/Content/Script'
    flodername=uassetpath.split('/')[-1]
    contentpath=unreal.Paths.project_content_dir()
    contentfile=os.listdir(contentpath)
    if os.path.isdir(uassetpath):
        if flodername not in contentfile:
            try:
                copytree(uassetpath, contentpath + flodername)
                print "%s is loaded!!"%flodername
                msgBox = QtGui.QMessageBox()
                msgBox.setText(u"%s 成功加载！请保存重启UE！！"%flodername)
                msgBox.exec_()
            except:
                unreal.log_warning("%s load failed!!"%flodername)
        else :
            unreal.log_warning("%s is exist in content!!! load failed!!"%flodername)
            msgBox = QtGui.QMessageBox()
            msgBox.setText(u"%s 已存在工程中，加载失败！！"%flodername)
            msgBox.exec_()
    else:
        unreal.log_warning("%s is not exist！！！"%uassetpath)
        msgBox = QtGui.QMessageBox()
        msgBox.setText(u"%s不存在，加载失败！请联系管理员"%flodername)
        msgBox.exec_()
        
def loadEnginePlugin(pluginpath):
    # pluginpath='Y:/Onemt/Marketing/Shared/Plug-in/LGTSet_UE/Plugins/GetRGB'
    flodername = pluginpath.split('/')[-1]
    enginePluginsPath=unreal.Paths.engine_plugins_dir()
    pluginfile = os.listdir(enginePluginsPath)
    if os.path.isdir(pluginpath):
        if flodername not in pluginfile:
            try:
                copytree(pluginpath, enginePluginsPath + flodername)
                print "%s is loaded!!" % flodername
            except:
                unreal.log_warning("%s load failed!!" % flodername)
        else:
            unreal.log_warning("%s is exist in project's plugin!!! load failed!!" % flodername)
    else:
        unreal.log_warning("%s is not exist！！！" % pluginpath)
        
def copytree(src, dst, symlinks = False, ignore = None):
    if not os.path.exists(dst):
        os.makedirs(dst)
        shutil.copystat(src, dst)
    lst = os.listdir(src)
    if ignore:
        excl = ignore(src, lst)
        lst = [x for x in lst if x not in excl]
    for item in lst:
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if symlinks and os.path.islink(s):
            if os.path.lexists(d):
                os.remove(d)
            os.symlink(os.readlink(s), d)
            try:
                st = os.lstat(s)
                mode = stat.S_IMODE(st.st_mode)
                os.lchmod(d, mode)
            except:
                pass # lchmod not available
        elif os.path.isdir(s):
            copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)
            
def run_utilitywidget(widgetpath):
    #widgetpath='/Game/Script/ONEMTLGTSet_v2'
    contentpath=unreal.Paths.project_content_dir()
    widgetfile=contentpath+widgetpath.split('Game/')[1]+".uasset"
    if os.path.isfile(widgetfile):
        widget_asset  = unreal.EditorAssetLibrary.load_asset(widgetpath)
        editor_utility_subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        editor_utility_subsystem.spawn_and_register_tab(widget_asset)
    else:
        unreal.log_warning("%s is not exist！！！"%widgetfile)