#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Show native UE startup feedback before importing any Qt application code."""

import importlib
import time


_pending = None
_MESSAGE = u"正在启动..."


class _StartupRequest:
    def __init__(self, unreal):
        self.unreal = unreal
        self.task = None
        self.tick_handle = None
        self.frames = 0
        self.window = None
        self.started = time.perf_counter()
        self.finished = False

    def start(self):
        self.task = self.unreal.ScopedSlowTask(1.0, _MESSAGE)
        self.task.__enter__()
        self.task.make_dialog(False, True)
        self.task.enter_progress_frame(0.0, _MESSAGE)
        # Return to Slate before importing PySide6 or creating OpenGL windows.
        # A second post-tick lets the menu dismiss and the native dialog paint.
        self.tick_handle = self.unreal.register_slate_post_tick_callback(self._tick)

    def _remove_tick(self):
        handle, self.tick_handle = self.tick_handle, None
        if handle is not None:
            self.unreal.unregister_slate_post_tick_callback(handle)

    def _tick(self, _delta_seconds):
        self.frames += 1
        if self.frames < 2:
            return
        # Progress updates may pump Slate again. Unregister before doing any
        # work, so nested ticks cannot launch a second window.
        self._remove_tick()
        try:
            self.task.enter_progress_frame(1.0, _MESSAGE)
            phase_start = time.perf_counter()
            module = importlib.import_module("AssetsManagerForUE.AssetsManagerForUE")
            self.unreal.log(u"[AssetsManager] 主窗口模块导入耗时 {0:.2f} 秒".format(
                time.perf_counter() - phase_start))
            phase_start = time.perf_counter()
            self.window = module.showWindow() or getattr(module, "win", None)
            self.unreal.log(u"[AssetsManager] 主窗口创建耗时 {0:.2f} 秒".format(
                time.perf_counter() - phase_start))
            ready = getattr(self.window, "startupFinished", None)
            if ready is None or getattr(self.window, "_startup_finished", False):
                # Support an already-imported older application module too.
                self.finish()
            else:
                ready.connect(self.finish)
                self.window.destroyed.connect(self.finish)
        except Exception:
            self.finish()
            import traceback
            self.unreal.log_error(u"AssetsManager 启动失败：\n" + traceback.format_exc())

    def finish(self, *_unused):
        global _pending
        if self.finished:
            return
        self.finished = True
        self._remove_tick()
        task, self.task = self.task, None
        if self.window is not None:
            for signal_name in ("startupFinished", "destroyed"):
                try:
                    getattr(self.window, signal_name).disconnect(self.finish)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self.window = None
        try:
            if task is not None:
                task.__exit__(None, None, None)
        finally:
            if _pending is self:
                _pending = None
        self.unreal.log(u"[AssetsManager] 启动界面准备结束，耗时 {0:.2f} 秒".format(
            time.perf_counter() - self.started))


def showWindow():
    """Menu/script entry: native progress first, then the Qt window on Slate."""
    global _pending
    if _pending is not None:
        return
    import unreal

    request = _StartupRequest(unreal)
    _pending = request
    try:
        request.start()
    except Exception:
        request.finish()
        raise
