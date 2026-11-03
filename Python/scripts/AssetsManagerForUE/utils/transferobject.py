#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ActionTools Created: 9/5/2021 by Sunxh<175702994@qq.com>
# log: 第一次编写

import os
import abc
import json
import time
import locale
import getpass
import logging

from ..my_vendor import six

# from utils import namespace
import utils

try:
    import maya.cmds
except Exception:
    import traceback
    traceback.print_exc()


logger = logging.getLogger(__name__)


class TransferObject(object): # Pose的父类

    @classmethod
    def fromPath(cls, path):
        """
        Return a new transfer instance for the given path.

        :type path: str
        :rtype: TransferObject
        """
        t = cls()
        t.setPath(path)
        t.read()
        return t

    @classmethod
    def fromObjects(cls, objects, **kwargs):
        """
        Return a new transfer instance for the given objects.

        :type objects: list[str]
        :rtype: TransferObject
        """
        t = cls(**kwargs)
        for obj in objects:
            t.add(obj)
        return t

    @staticmethod
    def readJson(path):
        """
        Read the given json path
        新的动作应该都是以json形式存储，老的用.dict .list
        :type path: str
        :rtype: dict
        """
        with open(path, "r") as f:
            data = f.read() or "{}"

        data = json.loads(data)

        return data

    @staticmethod
    def readList(path):
        """
        Legacy method for reading older .list file type.
        遗留方法读取老的列表
        :rtype: dict
        """
        with open(path, "r") as f:
            data = f.read()

        data = eval(data, {}) # 返回传入字符串的表达式的结果。就是说：将字符串当成有效的表达式 来求值 并 返回计算结果
                              # eval函数就是实现list、dict、tuple与str之间的转化，同样str函数把list，dict，tuple转为为字符串
        result = {}
        for obj in data:
            result.setdefault(obj, {})

        return {"objects": result}

    @staticmethod
    def readDict(path):
        """
        Legacy method for reading older .dict file type.
        遗留方法读取老的字典
        :rtype: dict
        """
        with open(path, "r") as f:
            data = f.read()

        data = eval(data, {})
        result = {}
        for obj in data:
            result.setdefault(obj, {"attrs": {}})
            for attr in data[obj]:
                typ, val = data[obj][attr]
                result[obj]["attrs"][attr] = {"type": typ, "value": val}

        return {"objects": result}

    def __init__(self):
        self._path = None
        self._namespaces = None
        self._data = {"metadata": {}, "objects": {}}

    def path(self):
        """
        Return the disc location for the transfer object.

        :rtype: str
        """
        return self._path

    def setPath(self, path):
        """
        Set the disc location for loading and saving the transfer object.

        :type path: str
        """
        dictPath = path.replace(".json", ".dict")
        listPath = path.replace(".json", ".list")

        if not os.path.exists(path):

            if os.path.exists(dictPath):
                path = dictPath

            elif os.path.exists(listPath):
                path = listPath

        self._path = path

    def validate(self, **kwargs):
        """
        Validate the given kwargs for the current IO object.

        :type kwargs: dict
        """
        namespaces = kwargs.get("namespaces")
        if namespaces is not None:
            sceneNamespaces = utils.namespace.getAll() + [":"]
            for namespace in namespaces:
                if namespace and namespace not in sceneNamespaces:
                    msg = 'The namespace "{0}" does not exist in the scene! ' \
                          "Please choose a namespace which exists."
                    msg = msg.format(namespace)
                    maya.cmds.warning(msg)

    def mtime(self):
        """
        Return the modification datetime of self.path().

        :rtype: float
        """
        return os.path.getmtime(self.path())

    def ctime(self):
        """
        Return the creation datetime of self.path().

        :rtype: float
        """
        return os.path.getctime(self.path())

    def data(self):
        """
        Return all the data for the transfer object.

        :rtype: dict
        """
        return self._data

    def setData(self, data):
        """
        Set the data for the transfer object.

        :type data:
        """
        self._data = data

    def owner(self):
        """
        Return the user who created this item.

        :rtype: str
        """
        return self.metadata().get("user", "")

    def description(self):
        """
        Return the user description for this item.

        :rtype: str
        """
        return self.metadata().get("description", "")

    def objects(self):
        """
        Return all the object data.

        :rtype: dict
        """
        return self.data().get("objects", {})

    def object(self, name):
        """
        Return the data for the given object name.

        :type name: str
        :rtype: dict
        """
        return self.objects().get(name, {})

    def createObjectData(self, name):
        """
        Create the object data for the given object name.

        :type name: str
        :rtype: dict
        """
        return {}

    def namespaces(self):
        """
        Return the namespaces contained in the transfer object

        :rtype: list[str]
        """
        if self._namespaces is None:
            group = utils.groupObjects(self.objects())
            self._namespaces = group.keys()

        return self._namespaces

    def objectCount(self):
        """
        Return the number of objects in the transfer object.

        :rtype: int
        """
        return len(self.objects() or [])

    def add(self, objects):
        """
        Add the given objects to the transfer object.

        :type objects: str | list[str]
        """
        if isinstance(objects, six.string_types):
            objects = [objects]

        for name in objects:
            self.objects()[name] = self.createObjectData(name)

    def remove(self, objects):
        """
        Remove the given objects to the transfer object.

        :type objects: str | list[str]
        """
        if isinstance(objects, six.string_types):
            objects = [objects]

        for obj in objects:
            del self.objects()[obj]

    def setMetadata(self, key, value):
        """
        Set the given key and value in the metadata.

        :type key: str
        :type value: int | str | float | dict
        """
        self.data()["metadata"][key] = value

    def updateMetadata(self, metadata):
        """
        Update the given key and value in the metadata.

        :type metadata: dict
        """
        self.data()["metadata"].update(metadata)

    def metadata(self):
        """
        Return the current metadata for the transfer object.

        Example: print(self.metadata())
            Result # {
                "User": "",
                "Scene": "",
                "Reference": {"filename": "", "namespace": ""},
                "Description": "",
            }

        :rtype: dict
        """
        return self.data().get("metadata", {})

    def read(self, path=""):
        """
        Return the data from the path set on the Transfer object.
        读取动作的json
        :type path: str
        :rtype: dict
        """
        path = path or self.path()

        if path.endswith(".dict"):
            data = self.readDict(path)

        elif path.endswith(".list"):
            data = self.readList(path)

        else:
            data = self.readJson(path)

        self.setData(data)

    @abc.abstractmethod
    def load(self, *args, **kwargs):
        pass

 
    def dump(self, data=None):
        """
        :type data: str | dict
        :rtype: str
        """
        if data is None:
            data = self.data()

        return json.dumps(data, indent=2)
