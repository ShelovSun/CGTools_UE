#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import configparser

from PySide2 import QtCore

scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')


def am_Temp():
    path = os.getenv('APPDATA') or os.getenv('HOME')
    TempPath = os.path.join(path, "AssetsManagerTemp")
    if not os.path.exists(TempPath):
        os.mkdir(TempPath)
    return TempPath


def sm_Temp():
    path = os.getenv('APPDATA') or os.getenv('HOME')
    TempPath = os.path.join(path, "ShotManagerTemp")
    # TEMP = "{}/ShotManagerTemp".format(os.environ.get('APPDATA')) or os.getenv('HOME')
    if not os.path.exists(TempPath):
        os.mkdir(TempPath)
    return TempPath


def serverTempPath():
    return 'Y:/ACTools/tools/sm_config'


def projectSetting():
    Json = '%s/projectSetting.json' % scriptsPath
    if os.path.exists(Json):
        f = open(Json, 'rb')
        data = f.read()
        f.close()
        try:
            decode_json = json.loads(data)
            return decode_json
        except Exception as e:
            print('read %s data file error:%s!' % (Json, e))
            return None
    else:
        print("there is not %s" % Json)
        return None


class SMConfig(object):
    CONFIGS_STORAGE = {}

    def __init__(self, *args, **kwargs):
        self.registerConfigFile("PREFS", os.path.join(sm_Temp(), "Configs", "prefs.ini"))
        self.registerConfigFile("CONFIG", os.path.join(sm_Temp(), "Configs", "config.ini"))

    def registerConfigFile(self, alias, absPath):
        if alias not in self.CONFIGS_STORAGE:
            self.CONFIGS_STORAGE[alias] = absPath
            return True
        return False

    def configs_storage(self):
        return self.CONFIGS_STORAGE

    def getSettings(self, alias):
        if alias in self.CONFIGS_STORAGE:
            QtCore.QTextCodec.setCodecForLocale(QtCore.QTextCodec.codecForName("UTF-8"))
            settings = QtCore.QSettings(self.CONFIGS_STORAGE[alias], QtCore.QSettings.IniFormat)
            return settings

    def getPrefsValue(self, valueKey, default=None):
        return self.getValue("PREFS", valueKey, default)

    def setPrefsValue(self, valueKey, value):
        section, key = valueKey.split("/")
        # settings = self.getSettings("PREFS")
        # settings.beginGroup(section)
        # settings.setValue(key, value)
        # settings.endGroup()
        config = configparser.ConfigParser()
        config[section] = {key: value}

        with open(self.CONFIGS_STORAGE["PREFS"], "w", encoding="utf-8") as configfile:
            config.write(configfile)

    def getConfigValue(self, valueKey, default=None):
        return self.getValue("CONFIG", valueKey, default)

    def setConfigValue(self, valueKey, value):
        section, key = valueKey.split("/")
        # settings = self.getSettings("CONFIG")
        # settings.beginGroup(section)
        # settings.setValue(key, value)
        # settings.endGroup()
        config = configparser.ConfigParser()
        config[section] = {key: value}

        with open(self.CONFIGS_STORAGE["CONFIG"], "w", encoding="utf-8") as configfile:
            config.write(configfile)

    def getValue(self, set_name, valueKey, default):
        section, key = valueKey.split("/")
        if section:
            if key != "":  # 如果有参数名读取参数
                if os.path.isfile(self.CONFIGS_STORAGE[set_name]):
                    config = configparser.ConfigParser()
                    config.read(self.CONFIGS_STORAGE[set_name], encoding='utf-8')
                    try:
                        section_items = config.items(section)
                        return [v for k, v in section_items if k == key][0]
                    except:
                        return default
                else:
                    return default
            else:  # 如果没用参数名读取整个section
                return_dic = {}
                if os.path.isfile(self.CONFIGS_STORAGE[set_name]):
                    config = configparser.ConfigParser()
                    config.read(self.CONFIGS_STORAGE[set_name], encoding='utf-8')
                    try:
                        section_items = config.items(section)
                        for k, v in section_items:
                            return_dic[k] = v
                        return return_dic
                    except:
                        return default
                else:
                    return default
        else:
            return default
