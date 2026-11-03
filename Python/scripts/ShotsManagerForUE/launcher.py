#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Show native UE startup progress before importing ShotsManager or Qt."""

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
        self.connections = []
        self.started = time.perf_counter()
        self.finished = False

    def start(self):
        self.task = self.unreal.ScopedSlowTask(3.0, _MESSAGE)
        self.task.__enter__()
        self.task.make_dialog(False, True)
        self.task.enter_progress_frame(0.0, _MESSAGE)
        # Let Slate dismiss the menu and paint the native dialog before Qt's
        # first import or the synchronous project/shot initialization starts.
        self.tick_handle = self.unreal.register_slate_post_tick_callback(self._tick)

    def _remove_tick(self):
        handle, self.tick_handle = self.tick_handle, None
        if handle is not None:
            self.unreal.unregister_slate_post_tick_callback(handle)

    def _tick(self, _delta_seconds):
        self.frames += 1
        if self.frames < 2:
            return
        # Progress updates can pump Slate recursively. Stop the launch callback
        # before updating progress so a nested tick cannot open another window.
        self._remove_tick()
        try:
            self.task.enter_progress_frame(1.0, _MESSAGE)
            phase_start = time.perf_counter()
            module = importlib.import_module("ShotsManagerForUE.ShotsManager_UE")
            self.unreal.log(u"[ShotsManager] 主窗口模块导入耗时 {0:.2f} 秒".format(
                time.perf_counter() - phase_start))
            self.task.enter_progress_frame(1.0, _MESSAGE)
            phase_start = time.perf_counter()
            self.window = module.showWin() or getattr(module, "win", None)
            self.unreal.log(u"[ShotsManager] 主窗口创建耗时 {0:.2f} 秒".format(
                time.perf_counter() - phase_start))
            ready = getattr(self.window, "startupFinished", None)
            if ready is None or getattr(self.window, "_startup_finished", False):
                # Also support an older main module already cached by UE.
                self.complete()
            else:
                ready.connect(self.complete)
                self.connections.append((ready, self.complete))
                self.window.destroyed.connect(self.finish)
                self.connections.append((self.window.destroyed, self.finish))
        except Exception:
            self.finish()
            import traceback
            self.unreal.log_error(u"ShotsManager 启动失败：\n" + traceback.format_exc())

    def complete(self, *_unused):
        self.finish(completed=True)

    def finish(self, *_unused, completed=False):
        global _pending
        if self.finished:
            return
        self.finished = True
        self._remove_tick()
        task, self.task = self.task, None
        for signal, callback in self.connections:
            try:
                signal.disconnect(callback)
            except (AttributeError, RuntimeError, TypeError):
                pass
        self.connections.clear()
        self.window = None
        try:
            if task is not None:
                try:
                    if completed:
                        task.enter_progress_frame(1.0, _MESSAGE)
                finally:
                    task.__exit__(None, None, None)
        finally:
            if _pending is self:
                _pending = None
        self.unreal.log(u"[ShotsManager] 启动界面准备结束，耗时 {0:.2f} 秒".format(
            time.perf_counter() - self.started))


def showWin():
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
