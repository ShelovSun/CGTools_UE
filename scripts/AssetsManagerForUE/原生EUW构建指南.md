# AssetsManager 原生可停靠面板（UMG Editor Utility Widget）构建指南

目标：拿到 **UE 原装窗口样式 + 能停靠到主窗体（标签页）** 的 AssetsManager 面板。
做法：界面用 **UMG EUW** 在编辑器里搭（原生样式 + 真停靠），后端逻辑仍复用现有 Python。

> 为什么不能继续用 Qt：PySide/Qt 自绘控件，永远是 Qt 样式，也进不了 UE 的 Slate 停靠系统。
> 原生效果必须用 UE 原生 UI（UMG）。UE 插件用 **C++ 或 UMG**，**不用 C#**（那是 Unity）。

我已经替你接好的部分（代码）：
- 菜单项 **CGTools ▸ AssetsManager(原生可停靠)**：点了就会把 EUW 作为**原生可停靠标签**打开
  （走 [Common.py](../Common.py) 的 `run_utilityWidget` → `spawn_and_register_tab`，和你的灯光/动画样条线工具同一套）。
  它指向的资产路径是 `'/Engine/Python/scripts/AssetsManagerForUE/AssetsManager_WBG'`。
- 桥接模块 [euw_bridge.py](euw_bridge.py)：EUW 的按钮调用它就能跑你的 Python 后端。

你需要在**编辑器里**做的事（UMG 界面是二进制 .uasset，没法用脚本生成）：

---

## 步骤 1 · 创建 EUW 资产（并存到正确路径）

1. 内容浏览器里定位到 `/Engine/Python/scripts/AssetsManagerForUE/`
   （对应磁盘 `scripts/AssetsManagerForUE/`；若内容浏览器看不到 Engine/Python，先开
   「设置 Settings ▸ Show Engine Content / Show Plugin Content」）。
2. 右键 ▸ **Editor Utilities ▸ Editor Utility Widget**。
3. 命名为 **`AssetsManager_WBG`**（务必与菜单里的路径一致），保存。

> 命名/路径必须是 `/Engine/Python/scripts/AssetsManagerForUE/AssetsManager_WBG`，
> 否则菜单点击会提示资产不存在（这是 `run_utilityWidget` 的 `does_asset_exist` 检查）。

## 步骤 2 · 搭界面（原生 UMG 控件）

双击打开 `AssetsManager_WBG`，在 Designer 里拖控件。建议先做一个最小可用版：

- 顶部放一个 **Vertical Box / Tab 控件**（想要原 Qt 的多 tab，可用 `WidgetSwitcher` + 几个 `Button` 做标签）。
- 放 1~2 个 **Button**，命名清楚（如 `Btn_Ping`、`Btn_OpenQt`）。
- 文本/列表用原生控件：`TextBlock`、`EditableTextBox`、`ListView`、`TreeView`、`Image` 等。
  （这些都是 UE 原生样式，停靠后和编辑器完全一致。）

## 步骤 3 · 设为可停靠（默认就是）

通过菜单用 `spawn_and_register_tab` 打开的 EUW，本身就是一个**可拖动、可停靠的 Nomad Tab**——
拖到主窗口边缘/其他面板上即可吸附停靠，和内容浏览器一样。**这一步无需额外设置。**

## 步骤 4 · 按钮接 Python（二选一）

### 方式 A（推荐·最稳）：Execute Python Command

1. Designer 里选中按钮 → Details 面板 → 事件 **OnClicked** 右侧 **+**，进入 Graph。
2. 从 OnClicked 拉出，搜索并放置节点 **Execute Python Command (Advanced)**
   （即 `unreal.PythonScriptLibrary.execute_python_command`）。
3. 在 **Python Command** 字段填：
   - 连通性测试按钮：
     `import AssetsManagerForUE.euw_bridge as b; b.ping()`
   - 过渡按钮（先用旧 Qt 窗口）：
     `import AssetsManagerForUE.euw_bridge as b; b.open_qt_window()`
   - 业务按钮（分发动作）：
     `import AssetsManagerForUE.euw_bridge as b; b.run_action('refresh_assets')`
4. 编译保存。点按钮即可触发对应 Python。

> 要把 UMG 输入框的值传给 Python：先用 `Get Text` 取到字符串，用 **Format Text/Append**
> 拼进命令串，再喂给 Execute Python Command。（含引号/中文时注意转义；复杂参数建议用方式 B。）

### 方式 B（可选·更顺手的类型化节点）

[euw_bridge.py](euw_bridge.py) 里已用 `@unreal.uclass` 暴露了节点（分类 **AssetsManager**）：
`Bp Ping` / `Bp Open Qt Window` / `Bp Run Action`。在 Graph 里右键搜 “AssetsManager” 即可。

前提：**本模块需在编辑器启动时被 import 过一次**节点才会出现。最简单的办法——
在 [init_unreal.py](../../init_unreal.py) 末尾加一行（或在 `Common.py` 顶部 try 包裹导入）：
```python
import AssetsManagerForUE.euw_bridge  # 注册 EUW 蓝图节点
```
（我没自动加这行，是为了不影响你现在的启动流程；需要方式 B 时再加。改完重启编辑器。）

## 步骤 5 · 打开/停靠

重启编辑器（或重新 import Common 刷新菜单）后：
**菜单栏 ▸ Tools ▸ CGTools ▸ AssetsManager(原生可停靠)** → 面板以原生标签打开 → 拖到喜欢的位置停靠。

---

---

# 资产 tab · 原生竖切片（具体摆件 + 接线清单）

目标：在 EUW 里做出"项目下拉 + 类型下拉 + 查询 + 资产下拉 + 导入/打开目录 + 状态栏"，
全部走原生 UMG，数据/导入复用 Python（[sources/asset_backend.py](sources/asset_backend.py)）。

我已暴露好的蓝图节点（分类 **AssetsManager**，启动已自动注册，见 [init_unreal.py](../../init_unreal.py)）。
**填下拉框的循环放在 Python 里做了，所以蓝图不需要 ParseIntoArray / ForEach**——只要把下拉框控件“递”给节点：

| 节点 | 入参 | 返回 | 说明 |
|---|---|---|---|
| `Bp Fill Projects` | Combo（下拉框控件） | — | 把项目填进这个下拉框 |
| `Bp Fill Types` | Combo | — | 把类型填进这个下拉框 |
| `Bp Fill Asset Names` | Combo, project, asset_type | — | 把资产名填进这个下拉框 |
| `Bp Asset Import` | project, asset_type, name | str | 导入并返回状态串 |
| `Bp Asset Open Dir` | project, asset_type, name | str | 打开目录并返回路径/错误 |

## 摆件（Designer）

- `ComboBoxString` ×3：命名 **`Combo_Project`**、**`Combo_Type`**、**`Combo_Asset`**
- `Button` ×3：**`Btn_Query`**（查询）、**`Btn_Import`**（导入）、**`Btn_Open`**（打开目录）
- `TextBlock` ×1：**`Txt_Status`**（状态栏）
- 用 `Vertical Box`/`Horizontal Box` 排版即可（原生样式）。
- 每个控件选中后，Details 面板最上方勾选 **Is Variable**（这样 Graph 里才能引用它）。

## 接线（Graph）—— 详细见对话里的逐步说明

1. **Event Construct**（打开标签就把两个下拉填好）：
   `Bp Fill Projects`(Combo_Project) → `Bp Fill Types`(Combo_Type)
2. **Btn_Query ▸ OnClicked**：
   `Bp Fill Asset Names`(Combo_Asset, Combo_Project 的 Get Selected Option, Combo_Type 的 Get Selected Option)
3. **Btn_Import ▸ OnClicked**：
   `Bp Asset Import`(项目, 类型, Combo_Asset 的 Get Selected Option) → 返回串接到 `Txt_Status ▸ Set Text`
4. **Btn_Open ▸ OnClicked**：
   `Bp Asset Open Dir`(同上三个参数) → 返回串接到 `Txt_Status ▸ Set Text`

编译保存 → 走菜单打开 → 选项目/类型 → 查询 → 选资产 → 导入。**内容全在原生标签里**。

## 前置条件

- 登录信息：后端复用 `%APPDATA%/ShotManagerTemp/setting.json` 里的 user/password 连数据库
  （和 Qt 版同源）。没登录过就先用一次 Qt 版登录，或确认该文件存在。
- 数据库 `10.0.203.34:5432` 在 UE 机器上可达；查询失败时 `Bp Asset Names` 返回空串、状态栏可显示空。

## 下一步（确认这切片跑通后再做）

- 把"资产下拉"升级成**缩略图网格**（UMG `ListView` + Entry Widget + 一个 Python `unreal.Object`
  数据项 uclass 承载 name/zh_name/icon）。这步是纯编辑器 UMG 工作量，我可给你数据项 uclass + 接线清单。
- 右键菜单（Import Action / Show in Explorer）、缩略图预览、搜索框过滤。

---

## 注意事项 / 排错

- **改了 Python 后端**：UE 不会自动重载已 import 的模块。开发期可在按钮命令前加重载，
  或用 `importlib.reload`，例如：
  `import importlib, AssetsManagerForUE.euw_bridge as b; importlib.reload(b); b.run_action('x')`
- **点菜单提示资产不存在**：说明 EUW 没存在
  `/Engine/Python/scripts/AssetsManagerForUE/AssetsManager_WBG`，核对名字/路径。
- **方式 B 节点不出现**：没在启动时 import `euw_bridge`，按步骤 4-B 加导入并重启。
- **工作量预期**：AssetsManager 是多 tab 大工具，整套 UMG 重搭是逐步工程。建议先用方式 A 接
  `open_qt_window()` 让面板“能停靠且立刻可用”，再一个 tab、一个功能地把 UI 原生化，
  后端 Python 基本不用动。

## 涉及文件
- 已改：[scripts/Common.py](../Common.py)（新增“AssetsManager(原生可停靠)”菜单项）
- 新增：[scripts/AssetsManagerForUE/euw_bridge.py](euw_bridge.py)（EUW→Python 桥）
- 待你建：`scripts/AssetsManagerForUE/AssetsManager_WBG.uasset`（在编辑器里创建）
