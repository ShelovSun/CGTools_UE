#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AssetsManagerForUE 启动脚本
在启动工具前自动设置Python路径
"""

import sys
import os

# 获取当前脚本路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

# 添加项目路径到sys.path
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# 导入并启动
try:
    from AssetsManagerForUE.launcher import showWindow
    showWindow()
except Exception as e:
    print(f"启动失败: {e}")
    import traceback
    traceback.print_exc()
