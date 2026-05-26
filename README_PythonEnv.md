# AssetsManagerForUE Python 环境设置

## 环境要求

- Python 3.9+
- PySide6
- psycopg2 (用于数据库连接)

## 快速开始

### 1. 创建虚拟环境

```bash
# 在项目根目录下
python -m venv venv
```

### 2. 激活虚拟环境

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：
```bash
pip install PySide6 psycopg2-binary
```

## 依赖说明

| 包名 | 版本 | 用途 |
|------|------|------|
| PySide6 | >=6.0.0 | Qt GUI框架 |
| psycopg2-binary | >=2.9.0 | PostgreSQL数据库连接 |
| shiboken6 | 自动安装 | PySide6的C++绑定生成器 |

## 在Unreal Engine中使用

### 方法一：使用init_assets_manager（推荐）

在UE的Python脚本中，添加以下代码：

```python
import sys
# 添加项目scripts路径
sys.path.append(r"E:\CGTools_for_UE\UE574\Python\scripts")

# 导入初始化模块（自动设置venv路径）
import init_assets_manager

# 导入并启动工具
from AssetsManagerForUE.AssetsManagerForUE import showWindow
showWindow()
```

### 方法二：手动添加venv路径

如果方法一不工作，可以手动添加venv路径：

```python
import sys
import os

# 添加虚拟环境的site-packages（必须在导入PySide6之前）
venv_path = r"E:\CGTools_for_UE\UE574\Python\venv\Lib\site-packages"
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

# 添加scripts路径
scripts_path = r"E:\CGTools_for_UE\UE574\Python\scripts"
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

# 现在可以导入AssetsManagerForUE
from AssetsManagerForUE.AssetsManagerForUE import showWindow
showWindow()
```

### 方法三：直接运行启动脚本

```python
import sys
sys.path.append(r"E:\CGTools_for_UE\UE574\Python\scripts")
from AssetsManagerForUE.start_assets_manager import *
```

### 添加到UE工具栏

可以将以下代码保存为 `.py` 文件，放到UE的Python插件目录：

```python
# AssetsManagerToolbar.py
import sys
import unreal

# 配置路径（根据你的实际路径修改）
PROJECT_SCRIPTS = r"E:\CGTools_for_UE\UE574\Python\scripts"

if PROJECT_SCRIPTS not in sys.path:
    sys.path.append(PROJECT_SCRIPTS)

import init_assets_manager
from AssetsManagerForUE.AssetsManagerForUE import showWindow

# 创建菜单按钮
def create_menu():
    menus = unreal.ToolMenus.get()
    main_menu = menus.find_menu("LevelEditor.MainMenu")
    
    # 创建CGTools菜单
    cg_menu = main_menu.add_sub_menu(
        "CGTools",
        "AssetsManager",
        "AssetsManager",
        "Assets Manager"
    )
    
    # 添加启动按钮
    entry = unreal.ToolMenuEntry(
        name="LaunchAssetsManager",
        type=unreal.MultiBlockType.MENU_ENTRY,
        insert_position=unreal.ToolMenuInsert("", unreal.ToolMenuInsertType.DEFAULT)
    )
    entry.set_label("Launch Assets Manager")
    entry.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        "",
        "from AssetsManagerForUE.AssetsManagerForUE import showWindow; showWindow()"
    )
    cg_menu.add_menu_entry("Launch", entry)
    menus.refresh_all_widgets()

create_menu()
```

## 验证安装

```bash
# 激活虚拟环境后
python -c "from PySide6 import QtWidgets, QtCore, QtGui; print('PySide6 安装成功')"
python -c "import psycopg2; print('psycopg2 安装成功')"
```

## 常见问题

### 1. ImportError: No module named 'PySide6'
- 确保虚拟环境已激活
- 检查是否正确安装了PySide6: `pip list | findstr PySide6`

### 2. 在UE中找不到模块
- 确保将虚拟环境的site-packages路径添加到sys.path
- 检查路径是否正确（Windows使用\\或/）

### 3. psycopg2连接失败
- 检查PostgreSQL服务器是否运行
- 确认数据库连接参数正确

## 从PySide2迁移到PySide6的修改

已完成以下修改：

1. **导入语句**: `from PySide2 import ...` → `from PySide6 import ...`
2. **QtGui.QStringListModel**: 移动到 `QtCore.QStringListModel`
3. **exec_()方法**: 仍可用，但也可使用 `exec()` (Python 3)
4. **其他API变化**: 大多数代码兼容，无需修改

## 文件清单

已更新的文件（16个主要文件）：
- `scripts/AssetsManagerForUE/AssetsManagerForUE.py`
- `scripts/AssetsManagerForUE/config/__init__.py`
- `scripts/AssetsManagerForUE/sources/*.py` (5个文件)
- `scripts/AssetsManagerForUE/utils/*.py` (8个文件)
- `scripts/AssetsManagerForUE/my_vendor/Qt.py` (兼容性库)

## 技术支持

如有问题，请检查：
1. Python版本是否 >= 3.9
2. 虚拟环境是否正确激活
3. 所有依赖是否已安装
4. UE的Python插件是否已启用
