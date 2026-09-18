#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
异步缩略图加载器
参考 StudioLibrary 的 ImageWorker 实现
使用 QThreadPool + QRunnable 实现异步图片加载
"""

import os
from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets


class ThumbnailLoaderSignals(QtCore.QObject):
    """缩略图加载信号"""
    # Worker 线程只传递 QImage。QPixmap 是 GUI 资源，必须在主线程创建。
    loaded = QtCore.Signal(str, object)  # path, image
    error = QtCore.Signal(str, str)  # path, error message


class ThumbnailWorker(QtCore.QRunnable):
    """
    缩略图加载工作线程
    在后台线程中加载图片，避免阻塞 UI
    """

    _cache = {}  # 类级别的 QImage 缓存
    _cache_lock = QtCore.QMutex()
    _max_cache_size = 500  # 最大缓存数量

    def __init__(self, path, size=120):
        super(ThumbnailWorker, self).__init__()
        self._path = path
        self._size = size
        self.signals = ThumbnailLoaderSignals()
        self._cancelled = False

    def setCancelled(self, value):
        self._cancelled = value

    @classmethod
    def getCachedImage(cls, path):
        """从缓存获取线程安全的 QImage。"""
        with QtCore.QMutexLocker(cls._cache_lock):
            return cls._cache.get(path)

    @classmethod
    def setCachedImage(cls, path, image):
        """缓存 QImage；不要从 Worker 线程缓存 QPixmap。"""
        with QtCore.QMutexLocker(cls._cache_lock):
            if len(cls._cache) >= cls._max_cache_size:
                # 清理最早的 20% 缓存
                keys_to_remove = list(cls._cache.keys())[:int(cls._max_cache_size * 0.2)]
                for key in keys_to_remove:
                    del cls._cache[key]
            cls._cache[path] = image

    @classmethod
    def clearCache(cls):
        """清空缓存"""
        with QtCore.QMutexLocker(cls._cache_lock):
            cls._cache.clear()

    @classmethod
    def removeCachedImage(cls, path):
        """移除指定路径的缓存——icon 文件被覆盖(路径不变内容变)后需失效旧图，否则一直读旧缩略图。"""
        with QtCore.QMutexLocker(cls._cache_lock):
            cls._cache.pop(path, None)

    def run(self):
        """在线程池中执行"""
        if self._cancelled:
            return

        # 首先检查缓存
        cached = self.getCachedImage(self._path)
        if cached is not None:
            self.signals.loaded.emit(self._path, cached)
            return

        try:
            if not os.path.exists(self._path):
                # 如果路径不存在，使用默认图片
                self._loadDefaultIcon()
                return

            # 使用 QImageReader 读取图片，更高效
            reader = QtGui.QImageReader(self._path)
            reader.setAutoTransform(True)

            # 设置缩放大小以提高性能
            if self._size > 0:
                reader.setScaledSize(QtCore.QSize(self._size, self._size))

            image = reader.read()

            if self._cancelled:
                return

            if image.isNull():
                # 如果图片读取失败，使用默认图片
                self._loadDefaultIcon()
                return

            # 存入缓存
            self.setCachedImage(self._path, image)

            if not self._cancelled:
                self.signals.loaded.emit(self._path, image)

        except Exception as e:
            if not self._cancelled:
                self.signals.error.emit(self._path, str(e))

    def _loadDefaultIcon(self):
        """加载默认图标"""
        default_path = self._getDefaultIconPath()
        if default_path and os.path.exists(default_path):
            image = QtGui.QImage(default_path)
            if not image.isNull():
                self.setCachedImage(self._path, image)
                if not self._cancelled:
                    self.signals.loaded.emit(self._path, image)

    def _getDefaultIconPath(self):
        """获取默认图标路径"""
        package_path = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(package_path, "icon", "blank_ch.png").replace("\\", "/")


class ThumbnailLoader(QtCore.QObject):
    """
    缩略图加载管理器
    管理线程池和加载队列
    """

    # 全局线程池
    _thread_pool = None
    _instance = None
    # 仅由 GUI 线程访问。QPixmap 不可在 ThumbnailWorker 中创建。
    _pixmap_cache = {}

    # 信号
    thumbnailLoaded = QtCore.Signal(str, QtGui.QPixmap)
    thumbnailError = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super(ThumbnailLoader, self).__init__(parent)
        self._workers = {}
        self._pending_paths = set()
        self._callbacks = {}  # path -> [callback]，按路径回调，避免全局信号风暴
        self._protected_paths = {}  # owner_key -> set(paths)，如右侧预览按钮不可被滚动取消
        self._mutex = QtCore.QMutex()

        # 初始化线程池
        if ThumbnailLoader._thread_pool is None:
            ThumbnailLoader._thread_pool = QtCore.QThreadPool()
            ThumbnailLoader._thread_pool.setMaxThreadCount(8)  # 缩略图解码较轻，放宽到 8 线程

    @classmethod
    def instance(cls):
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = ThumbnailLoader()
        return cls._instance

    @classmethod
    def getThreadPool(cls):
        """获取线程池"""
        if cls._thread_pool is None:
            cls._thread_pool = QtCore.QThreadPool()
            cls._thread_pool.setMaxThreadCount(8)
        return cls._thread_pool

    def loadThumbnail(self, path, size=120, callback=None):
        """
        异步加载缩略图。
        :param path: 图片路径
        :param size: 目标尺寸，默认 120
        :param callback: 可选，加载完成回调 callback(path, pixmap)，仅针对该 path 触发
        """
        if not path:
            return

        # 登记按路径回调（即使该 path 已在加载中也要登记，完成后统一通知）
        if callback is not None:
            with QtCore.QMutexLocker(self._mutex):
                self._callbacks.setdefault(path, [])
                if callback not in self._callbacks[path]:
                    self._callbacks[path].append(callback)

        # 检查缓存（命中则立即分发）
        cached = self.getCachedPixmap(path)
        if cached is not None:
            self._dispatch(path, cached)
            return

        # QImage 可由 Worker 缓存；此处在 GUI 线程完成 QPixmap 转换。
        cached_image = ThumbnailWorker.getCachedImage(path)
        if cached_image is not None:
            pixmap = self._pixmapFromImage(path, cached_image)
            if pixmap is not None:
                self._dispatch(path, pixmap)
                return

        with QtCore.QMutexLocker(self._mutex):
            if path in self._pending_paths:
                return  # 已在加载中，回调已登记，完成后统一通知
            self._pending_paths.add(path)

        # 创建工作线程
        worker = ThumbnailWorker(path, size)
        worker.signals.loaded.connect(self._onThumbnailLoaded)
        worker.signals.error.connect(self._onThumbnailError)

        with QtCore.QMutexLocker(self._mutex):
            self._workers[path] = worker

        # 提交到线程池
        self.getThreadPool().start(worker)

    def _dispatch(self, path, pixmap):
        """把加载结果分发给该 path 登记的回调，并发出全局信号（向后兼容）。"""
        with QtCore.QMutexLocker(self._mutex):
            callbacks = self._callbacks.pop(path, [])
        for cb in callbacks:
            try:
                cb(path, pixmap)
            except RuntimeError:
                # 回调宿主（item/视图）可能已销毁，忽略
                pass
        self.thumbnailLoaded.emit(path, pixmap)

    def _onThumbnailLoaded(self, path, image):
        """缩略图加载完成（worker 线程信号，主线程槽）"""
        with QtCore.QMutexLocker(self._mutex):
            self._pending_paths.discard(path)
            self._workers.pop(path, None)

        pixmap = self._pixmapFromImage(path, image)
        if pixmap is None:
            self.thumbnailError.emit(path, u"缩略图转换失败")
            return
        self._dispatch(path, pixmap)

    def _onThumbnailError(self, path, error):
        """缩略图加载错误"""
        with QtCore.QMutexLocker(self._mutex):
            self._pending_paths.discard(path)
            self._workers.pop(path, None)

        self.thumbnailError.emit(path, error)

    def isPending(self, path):
        """该路径是否仍在加载队列中（尚未完成/未被取消）。"""
        with QtCore.QMutexLocker(self._mutex):
            return path in self._pending_paths

    def cancelPathsExcept(self, keep_paths):
        """取消所有不在 keep_paths 中、尚未完成的加载请求。

        用于滚动停下后让线程池立即聚焦当前可见区：被取消的 worker 即使仍排在
        QThreadPool 队列里，run() 开头会因 _cancelled 立即返回，从而几微秒内腾出
        线程去处理可见区的 worker——这是避免“图标从上到下慢慢刷、滚到新区域迟迟
        不更新”的关键。返回被取消的路径列表，便于上层把对应条目复位以便回滚时重载。
        """
        keep = set(keep_paths or [])
        with QtCore.QMutexLocker(self._mutex):
            for paths in self._protected_paths.values():
                keep.update(paths)
            stale = [p for p in self._pending_paths if p not in keep]
            for p in stale:
                worker = self._workers.pop(p, None)
                if worker:
                    worker.setCancelled(True)
                self._pending_paths.discard(p)
                self._callbacks.pop(p, None)
        return stale

    def setProtectedPaths(self, owner_key, paths):
        """登记不应被列表滚动取消的少量路径；同 owner 的旧集合会被替换。"""
        with QtCore.QMutexLocker(self._mutex):
            clean = set(path for path in (paths or []) if path)
            if clean:
                self._protected_paths[owner_key] = clean
            else:
                self._protected_paths.pop(owner_key, None)

    def clearProtectedPaths(self, owner_key):
        with QtCore.QMutexLocker(self._mutex):
            self._protected_paths.pop(owner_key, None)

    def cancelLoad(self, path):
        """取消加载指定路径的缩略图"""
        with QtCore.QMutexLocker(self._mutex):
            worker = self._workers.get(path)
            if worker:
                worker.setCancelled(True)
            self._pending_paths.discard(path)
            self._workers.pop(path, None)
            self._callbacks.pop(path, None)

    def clearPendingLoads(self):
        """清除列表待加载缩略图；右侧预览登记的保护路径继续完成。"""
        with QtCore.QMutexLocker(self._mutex):
            protected = set()
            for paths in self._protected_paths.values():
                protected.update(paths)
            stale = [path for path in self._pending_paths if path not in protected]
            for path in stale:
                worker = self._workers.pop(path, None)
                if worker:
                    worker.setCancelled(True)
                self._pending_paths.discard(path)
                self._callbacks.pop(path, None)

    @classmethod
    def clearCache(cls):
        """清空缩略图缓存"""
        ThumbnailWorker.clearCache()
        cls._pixmap_cache.clear()

    @classmethod
    def getCachedPixmap(cls, path):
        """获取只能在 GUI 线程创建和使用的 QPixmap 缓存。"""
        return cls._pixmap_cache.get(path)

    @classmethod
    def _pixmapFromImage(cls, path, image):
        if image is None or image.isNull():
            return None
        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.isNull():
            return None
        if len(cls._pixmap_cache) >= ThumbnailWorker._max_cache_size:
            remove_count = max(1, int(ThumbnailWorker._max_cache_size * 0.2))
            for old_path in list(cls._pixmap_cache.keys())[:remove_count]:
                cls._pixmap_cache.pop(old_path, None)
        cls._pixmap_cache[path] = pixmap
        return pixmap
