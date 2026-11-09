#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多皮肤资产和多模型场景的轻量发现器。

Assets 配对 <asset>_<surface>，Scenes 配对实际模型名的 Icon 和 FBX。

目录枚举全部在线程池执行；调用方只拿到已经同时存在 Icon 与 FBX 的配对结果，
不会读取或解析 FBX。结果自然排序，卡片和预览器使用同一个首项。
"""

import os
import re
from collections import OrderedDict

from PySide6 import QtCore


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")


def isSceneIconPath(icon_path):
    return "/scenes/" in str(icon_path or "").replace("\\", "/").lower()


def supportsSurfaceVariants(icon_path, asset_name):
    path = str(icon_path or "").replace("\\", "/").lower()
    return bool(asset_name and ("/assets/" in path or "/scenes/" in path))


def _identical_icons(first, second):
    """Recognize legacy folder aliases without reading any FBX content."""
    if os.path.getsize(first) != os.path.getsize(second):
        return False
    with open(first, "rb") as a, open(second, "rb") as b:
        while True:
            chunk = a.read(65536)
            if chunk != b.read(65536):
                return False
            if not chunk:
                return True


def _natural_key(value):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", value)]


def discoverSurfaceVariants(icon_path, asset_name):
    """返回 ``[(surface_name, icon_path, fbx_path), ...]``。

    Assets 使用 ``<asset>_<skin>``；Scenes 使用任意同名 Icon/FBX 配对。
    场景旧文件夹名图片若与某个模型图片完全相同则视为历史副本并忽略；
    实际同名模型有独立图片时保留。任何目录/权限错误均回退到普通图片。
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
    scene = isSceneIconPath(icon_path)
    def matches(stem):
        return scene or stem.lower().startswith(prefix)
    try:
        fbx_by_stem = {}
        with os.scandir(fbx_dir) as entries:
            for entry in entries:
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() == ".fbx" and matches(stem) and entry.is_file():
                    fbx_by_stem[stem.lower()] = entry.path.replace("\\", "/")

        variants = []
        with os.scandir(icon_dir) as entries:
            for entry in entries:
                stem, ext = os.path.splitext(entry.name)
                stem_lower = stem.lower()
                if ext.lower() not in _IMAGE_EXTENSIONS or not matches(stem) or not entry.is_file():
                    continue
                fbx_path = fbx_by_stem.get(stem_lower)
                if not fbx_path:
                    continue
                surface_name = stem if scene else stem[len(asset_name) + 1:]
                if surface_name:
                    variants.append((surface_name,
                                     entry.path.replace("\\", "/"),
                                     fbx_path))
        if scene and len(variants) > 1:
            canonical = [v for v in variants if v[0].lower() == asset_name.lower()]
            models = [v for v in variants if v[0].lower() != asset_name.lower()]
            variants = models + [v for v in canonical
                                 if not any(_identical_icons(v[1], m[1]) for m in models)]
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

    def invalidate(self, icon_path, asset_name):
        """Expire one completed listing without disturbing other assets."""
        self._cache.pop(self._key(icon_path, asset_name), None)


