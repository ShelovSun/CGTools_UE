#!/usr/bin/env python
# -*- coding: utf-8 -*-
# sceneTools_Maya Created: 9/5/2021 by Sunxh<175702994@qq.com>
# log: 第一次编写

import os
from utils import jsonHelper
# import cgtw2

from PySide6 import QtCore


# reload(item)

scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/').replace('sources', '')


def projectSetting():
    jsonPath = 'Y:/ACTools/CGTools/scripts/AssetsManagerForMaya'
    data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % jsonPath)
    return data


def getItemsDictFromPath(__tab, __project, __type):
    """
    从路径获取字典
    :return:{role_name:{'role_name': xx,
                        'project': xx,
                        'type': xx,
                        'zh_name': xx,
                        'icon_path': xx}}
    """
    __items_dict = {}
    __path = '{0}/{1}/Assets/{2}'.format(projectSetting()['rootPath'], __project, __type)
    dir = QtCore.QDir(__path)
    for role_name in dir.entryList(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot):
        icon_path = '{0}/{1}/Icon/{1}.png'.format(__path, role_name)
        zn_name = ""
        bbb = {'role_name': role_name, 'project': __project, 'type': __type,
               'zh_name': zn_name, 'icon_path': icon_path}
        __items_dict.update({role_name: bbb})

    return __items_dict


def getItemsDictFromCGTW(__tab, __project, __type):
    """
    从CGTW获取字典
    :return:{role_name:{'role_name': xx,
                        'project': xx,
                        'type': xx,
                        'zh_name': xx,
                        'icon_path': xx}}
    """
    t_tw = cgtw2.tw()
    __items_dict = {}
    asset, assetmaya, assetstapy, entity, cn_name = get_CGTW_entity(__tab)
    print(__tab, __project, __type, projectSetting()['rootPath'])
    path = '{0}/{1}/{2}/{3}'.format(projectSetting()['rootPath'], __project, __tab, __type)

    TW_proj = str(projectSetting()['projectdiction'][__project])
    t_asset_ids = t_tw.info.get_id(TW_proj, asset, [[assetmaya, '=', u"完成"], 'and', [assetstapy, '=', __type]])
    TW_dictionInfo = t_tw.info.get(TW_proj, asset, t_asset_ids, [entity, cn_name])
    for info in TW_dictionInfo:
        icon_path = '{0}/{1}/Icon/{1}.png'.format(path, info[entity])
        bbb = {'role_name': info[entity], 'project': __project, 'type': __type,
               'zh_name': info[cn_name], 'icon_path': icon_path}
        __items_dict.update({info[entity]: bbb})

    return __items_dict


def get_CGTW_entity(_tab):
    if _tab == 'Assets':
        return 'asset', 'asset.maya', 'asset.assetstapy', 'asset.entity', 'asset.cn_name'
    else:
        if type != "Map":
            return 'scenes', 'scenes.maya', 'scenes.scenesassetstype', 'scenes.entity', 'scenes.assetsnamecn'
        else:
            return 'map', 'map.maya', 'map.type', 'map.entity', 'map.mapnamecn'


