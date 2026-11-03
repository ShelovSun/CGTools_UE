#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ue_qt_host —— 在 Unreal Editor 中正确承载 PySide/Qt 工具窗口的共享模块。

为什么需要它：
    UE 运行自己的 Slate 事件循环。Qt 工具窗口若只是 widget.show()：
      1) 它是与 UE 无关的独立顶层 OS 窗口 —— 不会置顶/“停靠”于 UE，
         也不会随 UE 一起最小化/还原；
      2) 在 UE 里调用 app.exec_() 会阻塞（卡死）整个编辑器主线程。

标准做法（本模块封装的 PySide-in-Unreal 模式）：
    1) unreal.parent_external_window_to_slate(hwnd, MAIN_WINDOW)
         把 Qt 原生窗口句柄挂到 UE 主窗口下 —— 始终浮于 UE 之上、跟随 UE 最小化/还原。
    2) 用 Slate 的每帧回调驱动 Qt 事件循环（app.processEvents），替代 app.exec_()。
       **整个进程只需要一个事件泵**：processEvents() 泵的是整个 QApplication（所有 Qt
       窗口），不是单个窗口。所以无论开多少个工具窗口，都只注册一次 tick；否则每开一次
       窗口就多一个 tick、每帧多跑一遍 processEvents，会越用越卡（这是之前卡顿的根因）。

非 UE（独立运行）环境下回退到标准 app.exec_() 以保持窗口存活。

绑定无关：本模块不强制 import 某个 PySide 版本，只调用 PySide2 / PySide6 / PyQt 共有的方法。
"""

import sys
import types

try:
    import unreal
    _IN_UNREAL = True
except Exception:
    _IN_UNREAL = False


# 事件泵句柄存到一个独立的 sys.modules 槽里：即使本模块被 importlib.reload，
# 句柄也不丢失、不会重复注册，从根上杜绝“进程里累积多个事件泵”。
_STATE_KEY = "__ue_qt_host_state__"
if _STATE_KEY not in sys.modules:
    _s = types.ModuleType(_STATE_KEY)
    _s.tick_handle = None
    sys.modules[_STATE_KEY] = _s
_STATE = sys.modules[_STATE_KEY]


def _find_app(explicit=None):
    """拿到当前 QApplication 实例（绑定无关）。调用方一般会直接把 app 传进来。"""
    if explicit is not None:
        return explicit
    for mod in ("PySide6", "PySide2", "PyQt5", "PyQt6"):
        try:
            qtw = __import__(mod + ".QtWidgets", fromlist=["QApplication"])
            inst = qtw.QApplication.instance()
            if inst is not None:
                return inst
        except Exception:
            continue
    return None


def _exec_app(app):
    """启动事件循环（PySide6 用 exec()，PySide2 用 exec_()，做兼容）。"""
    fn = getattr(app, "exec", None) or getattr(app, "exec_", None)
    if fn is not None:
        fn()


def _ensure_event_pump():
    """确保整个进程**只有一个** Slate tick 在驱动 Qt 事件循环。重复调用是幂等的。"""
    if not _IN_UNREAL or _STATE.tick_handle is not None:
        return

    def _pump(delta_seconds):
        app = _find_app()
        if app is not None:
            app.processEvents()

    try:
        _STATE.tick_handle = unreal.register_slate_post_tick_callback(_pump)
    except Exception as e:
        unreal.log_warning("[ue_qt_host] 注册 Slate tick 失败: %s" % e)


def stop_event_pump():
    """手动停止并注销事件泵（一般不需要；用于排查或彻底清理）。"""
    if _IN_UNREAL and _STATE.tick_handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(_STATE.tick_handle)
        except Exception:
            pass
    _STATE.tick_handle = None


def host_window(widget, app=None, on_top=True):
    """
    在 UE 中承载一个顶层 Qt 窗口（widget 已实例化、未必已 show）。

    :param widget: 需要显示的 QWidget（顶层窗口）
    :param app:    可选，QApplication 实例；不传则自动探测
    :param on_top: True=挂到 UE 主窗口下并随之置顶；False=保持独立窗口
    :return: widget（方便调用方保留引用）
    """
    app = _find_app(app)

    # 必须先 show，winId() 才会创建有效的原生句柄
    widget.show()
    try:
        widget.raise_()
        widget.activateWindow()
    except Exception:
        pass

    if not _IN_UNREAL:
        # 独立运行：用标准事件循环保持窗口存活（否则脚本结束窗口会一闪而过）
        if app is not None:
            _exec_app(app)
        return widget

    # ---- UE 内 ----
    if on_top:
        try:
            method = getattr(unreal.SlateParentWindowSearchMethod, "MAIN_WINDOW",
                             unreal.SlateParentWindowSearchMethod.ACTIVE_WINDOW)
            unreal.parent_external_window_to_slate(int(widget.winId()), method)
        except Exception as e:
            unreal.log_warning("[ue_qt_host] 挂接到 Slate 失败: %s" % e)

    # 进程级单例事件泵（幂等）：不再每开一个窗口就注册一个 tick。
    _ensure_event_pump()
    return widget
