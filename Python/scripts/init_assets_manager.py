#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AssetsManagerForUE 初始化模块
在UE中导入此模块即可自动设置Python路径

使用方法:
    import sys
    sys.path.append(r"E:\CGTools_for_UE\UE574\Python\scripts")
    import init_assets_manager
    from AssetsManagerForUE.AssetsManagerForUE import showWindow
    showWindow()
"""

import sys
import os

# 本地venv路径
LOCAL_VENV = r"Y:\MCCTools\src\venv\Lib\site-packages"
LOCAL_SCRIPTS = r"E:\CGTools_for_UE\UE574\Python\scripts"

# 1. 先移除所有NAS/Y盘相关的路径（避免冲突）
sys.path[:] = [p for p in sys.path if not any(x in p for x in [
    r"Y:\ACTools\Python\UE5.03",
    r"fznas.diandian.info",
    r"\\fznas",
    r"\\AC\ACTools\Python",
    r"E:\CGTools_for_UE\UE574\Python\venv"
])]

# 2. 将本地venv插入到最前面（确保优先级最高）
if os.path.exists(LOCAL_VENV):
    if LOCAL_VENV in sys.path:
        sys.path.remove(LOCAL_VENV)
    sys.path.insert(0, LOCAL_VENV)
    print(f"[AssetsManager] 已设置本地venv: {LOCAL_VENV}")
else:
    print(f"[AssetsManager] 警告: 找不到本地venv: {LOCAL_VENV}")

# 3. 添加本地scripts目录
if os.path.exists(LOCAL_SCRIPTS):
    if LOCAL_SCRIPTS in sys.path:
        sys.path.remove(LOCAL_SCRIPTS)
    sys.path.insert(0, LOCAL_SCRIPTS)

# 4. 验证PySide6导入
try:
    from PySide6 import QtCore
    print(f"[AssetsManager] PySide6 版本: {QtCore.__version__}")
except ImportError as e:
    print(f"[AssetsManager] 错误: 无法导入PySide6: {e}")
    print(f"[AssetsManager] 当前sys.path前3项: {sys.path[:3]}")
