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

# 获取当前文件路径
current_file = os.path.abspath(__file__)
scripts_dir = os.path.dirname(current_file)
project_root = os.path.dirname(scripts_dir)

# 添加venv的site-packages到sys.path（最前面）
venv_site_packages = os.path.join(project_root, 'venv', 'Lib', 'site-packages')
if os.path.exists(venv_site_packages):
    if venv_site_packages not in sys.path:
        sys.path.insert(0, venv_site_packages)
        # print(f"[AssetsManager] 已添加venv路径: {venv_site_packages}")
else:
    print(f"[AssetsManager] 警告: 找不到venv路径: {venv_site_packages}")

# 添加scripts目录到sys.path
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# 尝试导入并打印版本信息
try:
    from PySide6 import QtCore
    # print(f"[AssetsManager] PySide6 版本: {QtCore.__version__}")
except ImportError as e:
    print(f"[AssetsManager] 错误: 无法导入PySide6: {e}")
