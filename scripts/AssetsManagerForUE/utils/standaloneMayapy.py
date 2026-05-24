# uncompyle6 version 3.7.4
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.8.6 (tags/v3.8.6:db45529, Sep 23 2020, 15:37:30) [MSC v.1927 32 bit (Intel)]
# Embedded file name: E:/PyCharm/AssetsManagerUE4/v2.1.0/utils\standaloneMayapy.py
# Compiled at: 2020-12-04 14:43:54
import maya.cmds as cmds, maya.mel as mm

def importFBX(fbxFile):
    cmds.loadPlugin('fbxmaya.mll')
    cmds.file(force=True, new=True)
    cmds.file(fbxFile, i=True, type='FBX', ignoreVersion=True, mergeNamespacesOnClash=False, rpr='aa', options='v=0;', importFrameRate=True, importTimeRange='override')


def exportAlembic(abcFile):
    cmds.loadPlugin('AbcExport.mll')
    assemblies = cmds.ls(assemblies=1)
    assemblies.remove('persp')
    assemblies.remove('top')
    assemblies.remove('front')
    assemblies.remove('side')
    cmds.group(assemblies, name='Scene_GRP')
    mm.eval('AbcExport -j "-frameRange 1 1 -uvWrite -worldSpace -writeVisibility -dataFormat ogawa -root |Scene_GRP -file %s";' % abcFile)


def exportGPU(gpuPath, gpuFileName):
    cmds.loadPlugin('gpuCache.mll')
    assemblies = cmds.ls(assemblies=1)
    assemblies.remove('persp')
    assemblies.remove('top')
    assemblies.remove('front')
    assemblies.remove('side')
    scene_grp = cmds.group(assemblies, name='Scene_GRP')
    mm.eval('gpuCache -startTime 1 -endTime 1 -optimize -optimizationThreshold 40000 -writeMaterials -dataFormat ogawa -directory "%s" -fileName "%s" -saveMultipleFiles false %s;' % (gpuPath, gpuFileName, scene_grp))