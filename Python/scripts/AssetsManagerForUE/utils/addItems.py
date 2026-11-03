#!/usr/bin/env python
# -*- coding: utf-8 -*-
# sceneTools_Maya Created: 9/5/2021 by Sunxh<175702994@qq.com>
# log: 第一次编写

from PySide6 import QtCore
from ..config import commonSetting


# reload(item)

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
    __path = '{0}/{1}/Assets/{2}'.format(commonSetting()['rootPath'], __project, __type)
    dir = QtCore.QDir(__path)
    for role_name in dir.entryList(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot):
        icon_path = '{0}/{1}/Icon/{1}.png'.format(__path, role_name)
        zn_name = ""
        bbb = {'role_name': role_name, 'project': __project, 'type': __type,
               'zh_name': zn_name, 'icon_path': icon_path}
        __items_dict.update({role_name: bbb})

    return __items_dict


