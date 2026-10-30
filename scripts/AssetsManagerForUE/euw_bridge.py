#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
euw_bridge —— AssetsManager 的「原生 UMG Editor Utility Widget」与 Python 后端之间的桥。

思路：
    原生窗口样式 + 真正停靠 只能用 UE 原生 UI（UMG EUW）。界面在编辑器里用 UMG 搭，
    但后端逻辑（数据库、资产导入等）仍然用你现有的 Python 代码。EUW 里每个按钮的
    OnClick 调用本文件暴露的节点即可，从而“UI 原生、逻辑复用”。

为降低蓝图连线难度：填下拉框的活儿（清空 + 逐项添加）放在 Python 里做，蓝图只需把
ComboBoxString 控件作为参数“递进来”，因此**蓝图里不需要 ForEach / ParseIntoArray**。

注册：本模块在编辑器启动时被 import 一次（见 init_unreal.py），蓝图里才会出现这些节点。
后端数据/导入逻辑在 sources/asset_backend.py（无 Qt）。
"""

try:
    import unreal
except Exception:
    unreal = None


# =============================================================================
# 通用 / 自检（可被 "Execute Python Command" 直接调用）
# =============================================================================
def open_qt_window():
    """过渡用：用原来的 Qt 窗口打开 AssetsManager。"""
    from AssetsManagerForUE import launcher as AM
    AM.showWindow()


def ping(message=u"AssetsManager EUW 已连通 Python 后端"):
    """连通性自检：弹一个 UE 原生对话框。"""
    if unreal is not None:
        unreal.EditorDialog.show_message(u"AssetsManager", message, unreal.AppMsgType.OK)
    else:
        print(message)


# =============================================================================
# 资产 tab 后端封装
# =============================================================================
def _backend():
    import AssetsManagerForUE.sources.asset_backend as b
    return b


def _fill_combo(combo, items):
    """清空并填充一个 ComboBoxString（在 Python 里完成，蓝图不用循环）。"""
    if combo is None:
        return
    combo.clear_options()
    for it in items:
        combo.add_option(it)


def fill_projects(combo):
    _fill_combo(combo, _backend().get_projects())


def fill_types(combo):
    _fill_combo(combo, _backend().get_types())


def fill_asset_names(combo, project, asset_type):
    try:
        _fill_combo(combo, _backend().asset_names(project, asset_type))
    except Exception as e:
        if unreal is not None:
            unreal.log_warning(u"[euw_bridge] 查询资产失败: %s" % e)
        _fill_combo(combo, [])


def asset_import(project, asset_type, name):
    try:
        return _backend().import_asset(project, asset_type, name)
    except Exception as e:
        return "Import failed: %s" % e


def asset_open_dir(project, asset_type, name):
    try:
        p = _backend().open_asset_dir(project, asset_type, name)
        return p if p else "Directory not found"
    except Exception as e:
        return "Open failed: %s" % e


# =============================================================================
# 暴露成 EUW 蓝图节点（分类 "AssetsManager"）。用 try/except 包裹防止某版本签名差异。
# =============================================================================
if unreal is not None:
    try:
        @unreal.uclass()
        class AssetsManagerBridge(unreal.BlueprintFunctionLibrary):
            """EUW 蓝图中可见的节点集合（Category: AssetsManager）。"""

            # ---- 自检 ----
            @unreal.ufunction(static=True, meta=dict(Category="AssetsManager"))
            def bp_ping():
                ping()

            @unreal.ufunction(static=True, meta=dict(Category="AssetsManager"))
            def bp_open_qt_window():
                open_qt_window()

            # ---- 填下拉框：把 ComboBoxString 递进来，Python 负责清空+填充 ----
            @unreal.ufunction(static=True, params=[unreal.ComboBoxString],
                              meta=dict(Category="AssetsManager"))
            def bp_fill_projects(combo):
                fill_projects(combo)

            @unreal.ufunction(static=True, params=[unreal.ComboBoxString],
                              meta=dict(Category="AssetsManager"))
            def bp_fill_types(combo):
                fill_types(combo)

            @unreal.ufunction(static=True, params=[unreal.ComboBoxString, str, str],
                              meta=dict(Category="AssetsManager"))
            def bp_fill_asset_names(combo, project, asset_type):
                fill_asset_names(combo, project, asset_type)

            # ---- 动作：返回状态串，直接显示到界面 ----
            @unreal.ufunction(static=True, ret=str, params=[str, str, str],
                              meta=dict(Category="AssetsManager"))
            def bp_asset_import(project, asset_type, name):
                return asset_import(project, asset_type, name)

            @unreal.ufunction(static=True, ret=str, params=[str, str, str],
                              meta=dict(Category="AssetsManager"))
            def bp_asset_open_dir(project, asset_type, name):
                return asset_open_dir(project, asset_type, name)

    except Exception as e:
        unreal.log_warning(u"[euw_bridge] 蓝图节点注册失败（不影响 ExecutePythonCommand 方式）: %s" % e)
