#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多皮肤资产的轻量发现器。

发布约定：
    Icon/<asset>_<surface>.png
    FBX/<asset>_<surface>.fbx

目录枚举全部在线程池执行；调用方只拿到已经同时存在 Icon 与 FBX 的配对结果，
不会读取或解析 FBX。结果按皮肤名自然排序，作为卡片和预览器一致的“首个皮肤”。
"""

import os
import re
from collections import OrderedDict

from PySide6 import QtCore


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")


def _natural_key(value):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", value)]


def discoverSurfaceVariants(icon_path, asset_name):
    """返回 ``[(surface_name, icon_path, fbx_path), ...]``。

    只认 ``<asset>_`` 前缀，并要求同名 FBX 存在；主 ``<asset>.png/.fbx``
    不属于皮肤清单。任何网络目录/权限错误都按无皮肤处理，不影响普通资产显示。
    """
    if not icon_path or not asset_name:
        return []

    icon_path = os.path.normpath(str(icon_path))
    asset_name = str(asset_name)
    icon_dir = os.path.dirname(icon_path)
    asset_root = os.path.dirname(icon_dir)
    fbx_dir = os.path.join(asset_root, "FBX")
    if not icon_dir or not os.path.isdir(icon_dir) or not os.path.isdir(fbx_dir):
        return []

    prefix = (asset_name + "_").lower()
    try:
        fbx_by_stem = {}
        with os.scandir(fbx_dir) as entries:
            for entry in entries:
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() == ".fbx" and stem.lower().startswith(prefix):
                    fbx_by_stem[stem.lower()] = entry.path.replace("\\", "/")

        variants = []
        with os.scandir(icon_dir) as entries:
            for entry in entries:
                stem, ext = os.path.splitext(entry.name)
                stem_lower = stem.lower()
                if ext.lower() not in _IMAGE_EXTENSIONS or not stem_lower.startswith(prefix):
                    continue
                fbx_path = fbx_by_stem.get(stem_lower)
                if not fbx_path:
                    continue
                surface_name = stem[len(asset_name) + 1:]
                if surface_name:
                    variants.append((surface_name,
                                     entry.path.replace("\\", "/"),
                                     fbx_path))
    except (OSError, IOError):
        return []

    variants.sort(key=lambda item: _natural_key(item[0]))
    return variants


class _DiscoverSignals(QtCore.QObject):
    finished = QtCore.Signal(str, object)


class _DiscoverWorker(QtCore.QRunnable):

    def __init__(self, key, icon_path, asset_name):
        super(_DiscoverWorker, self).__init__()
        self.key = key
        self.icon_path = icon_path
        self.asset_name = asset_name
        self.signals = _DiscoverSignals()

    def run(self):
        variants = discoverSurfaceVariants(self.icon_path, self.asset_name)
        self.signals.finished.emit(self.key, variants)


class SurfaceVariantLoader(QtCore.QObject):
    """合并重复请求的异步目录发现器，带小型内存 LRU。"""

    _instance = None
    _CACHE_CAP = 256

    def __init__(self, parent=None):
        super(SurfaceVariantLoader, self).__init__(parent)
        self._pool = QtCore.QThreadPool()
        # 网络目录枚举不是 CPU 密集任务，但也不应与缩略图的 8 线程一起扩大请求风暴。
        self._pool.setMaxThreadCount(2)
        self._cache = OrderedDict()
        self._pending = {}       # key -> [callback]
        self._workers = {}       # 保持 worker/signal 生命周期直到完成

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _key(icon_path, asset_name):
        path = os.path.normcase(os.path.normpath(str(icon_path or "")))
        # 普通可见分隔符比 NUL 更适合经 Qt 的 Signal(str) 往返。
        return path + "|asset=" + str(asset_name or "").lower()

    def request(self, icon_path, asset_name, callback):
        """异步请求；callback 在 GUI 线程收到一个 variant tuple 列表。"""
        key = self._key(icon_path, asset_name)
        if not icon_path or not asset_name:
            callback([])
            return

        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            callback(list(cached))
            return

        callbacks = self._pending.get(key)
        if callbacks is not None:
            if callback not in callbacks:
                callbacks.append(callback)
            return

        self._pending[key] = [callback]
        worker = _DiscoverWorker(key, icon_path, asset_name)
        worker.signals.finished.connect(self._onFinished)
        self._workers[key] = worker
        self._pool.start(worker)

    def _onFinished(self, key, variants):
        callbacks = self._pending.pop(key, [])
        self._workers.pop(key, None)
        self._cache[key] = list(variants)
        self._cache.move_to_end(key)
        while len(self._cache) > self._CACHE_CAP:
            self._cache.popitem(last=False)
        for callback in callbacks:
            try:
                callback(list(variants))
            except RuntimeError:
                # 对应卡片/预览控件可能已在网络请求完成前销毁。
                pass

    def clearCache(self):
        """发布后点击刷新时失效目录结果；运行中的请求仍允许安全结束。"""
        self._cache.clear()


