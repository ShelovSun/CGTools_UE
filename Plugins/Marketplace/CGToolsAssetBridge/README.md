# CGTools Asset Bridge

`CGToolsAssetBridge` 是 `AssetsManagerForUE` 使用的 UE 5.7 原生编辑器桥接插件。  
当前版本：`1.3.3`。

`1.3.3` 新增 `export_external_vfx_thumbnail(资产文件, Content目录, 输出PNG)`，返回空字符串表示成功、`NO_THUMBNAIL|原因` 表示确实缺图、`ERROR|原因` 表示读取失败。该接口只允许独立、无人值守且带 `-CGToolsThumbnailWorker` 参数的进程调用，避免当前编辑器线程加载外部特效。优先读取标准缩略图，其次读取 Niagara/Cascade 内部预览纹理；只读挂载外部 Content，不保存或迁移源资产。原有标准缩略图 API 保留兼容。

它不提供独立窗口，也不负责从服务器复制资产。它只把 Python/PySide 不适合或无法可靠完成的 UE 编辑器底层操作放到 C++ 中执行。

## 是否可以删除

当前不建议删除。

正式版 `AssetsManagerForUE` 会通过 UE Python 暴露的 `unreal.CGToolsAssetBridgeLibrary` 调用这个插件。删除或停用后：

- 资产和蓝图的已知整包仍然可以复制进当前工程，但特效 Tab 无法从单个
  `.uasset` 递归解析材质、贴图、Niagara 等包依赖；
- 已加载的绿色资产卡片不能再精确拖放到鼠标松手所在的关卡视口位置；
- 蓝图和特效 Tab 无法读取工程外 `.uasset` 内嵌的原生缩略图，只能回退到通用图标；
- Python 会提示“未启用 CGToolsAssetBridge 插件”。

只有在 `AssetsManagerForUE` 已经完整迁移成包含这些能力的 C++ 插件，或者明确放弃卡片拖入关卡与外部 `.uasset` 缩略图后，才可以删除本插件。

### 源码目录与部署目录的区别

本目录：

```text
E:\CGTools_for_UE\UE574\Plugins\Marketplace\CGToolsAssetBridge
```

是插件的正式源码目录。删除它不会立刻删除已经编译并安装到某个 UE 工程里的 DLL，但会导致后续无法重新编译、升级和部署插件，同时现有构建脚本也会失败。

真正被 UE 加载的是工程或引擎插件目录中的编译版本，例如：

```text
<工程>\Plugins\CGToolsAssetBridge
```

当前测试工程历史上使用过目录名：

```text
E:\Project\UE57测试工程\Plugins\CGToolsAssetBridge_NEW
```

`_NEW` 只是测试阶段遗留的文件夹名；其中 `.uplugin`、模块名和 Python API 仍然都是正式名称 `CGToolsAssetBridge`。不要在同一个 UE 环境中同时部署两个包含同名模块的副本。

## 主要功能

### 1. 把已加载资产精确放入关卡

插件将 Qt/PySide 提供的鼠标松手屏幕坐标转换成 UE Slate 关卡视口的本地坐标，然后调用 UE 编辑器原生接口：

```text
FEditorViewportClient::CanDropObjectsAtCoordinates
FEditorViewportClient::DropObjectsAtCoordinates
```

这样静态网格体、骨架网格体和 Actor 蓝图会按照 UE 原生规则放置，并得到正确的碰撞表面落点、选中状态和撤销记录，而不是简单生成在摄像机前方。

### 2. 判断资产能否放入当前关卡

放置前会先让当前 `Level Viewport` 判断资产类型是否允许拖入。如果不能放置，会把 UE 返回的原因传回 Python 界面。

### 3. 读取工程外 `.uasset` 的内嵌缩略图

蓝图尚未加载进当前工程时，UE 的普通 `AssetRegistry` 和 `FAssetThumbnail` 不能直接处理服务器上的外部包。插件会只读解析外部 `.uasset` 的包头和缩略图表，把内嵌图片导出成 PNG 缓存，供资产卡片显示。

读取过程中会校验：

- Unreal 包标识；
- UE 文件版本；
- Licensee 版本；
- Custom Version；
- 缩略图表偏移和图像数据。

它不会修改服务器 `.uasset`。

### 4. 解析工程外特效的递归依赖闭包

特效 Tab 只需要选择一个 Niagara、粒子或其他特效 `.uasset`。插件会把服务器
`Content` 临时注册到一个只在当前编辑器会话中存在的唯一挂载点，使用
`AssetRegistry` 从选中的包开始递归查询依赖，并把闭包转换回服务器上的实际
`.uasset` / `.umap` 文件列表。

处理规则：

- `/Game/...` 依赖映射回同一个服务器 `Content` 树；
- `/Engine/...` 和 `/Script/...` 属于引擎，不复制；
- `/Niagara/...` 等插件依赖不复制，但会检查当前 UE 是否已经提供；
- 服务器和当前工程/插件都找不到的依赖会作为缺失项返回，Python 端拒绝执行
  不完整迁移；
- 插件只负责解析，不修改服务器文件，也不直接覆盖当前工程。

Python 端随后按解析结果复制主包、`.uexp`、`.ubulk`、`.uptnl` 等 sidecar，
并保持相对于 `Content` 的原路径，因此材质、贴图和 Niagara 模块引用不会因为
改名或换目录而断开。

### 5. 批量读取工程外资产类型

特效 Tab 枚举服务器 `.uasset` 后，会一次性调用原生桥读取对应包的
`AssetClassPath`。界面只保留 `NiagaraSystem` 和 `ParticleSystem` 卡片；材质、
贴图、NiagaraEmitter 和模块脚本不会显示为独立特效，但仍会在加载系统时作为
依赖迁移。

## 对外接口

插件通过 `UCGToolsAssetBridgeLibrary` 暴露以下接口：

| C++ 接口 | Python 名称 | 用途 |
|---|---|---|
| `GetBridgeVersion` | `get_bridge_version` | 返回当前桥版本 |
| `CanPlaceAssetAtCursor` | `can_place_asset_at_cursor` | 判断光标下的关卡视口能否接受资产 |
| `PlaceAssetAtCursor` | `place_asset_at_cursor` | 在当前平台光标位置放置资产 |
| `PlaceAssetAtScreenPosition` | `place_asset_at_screen_position` | 使用 Qt 传入的精确屏幕坐标放置资产 |
| `ExportExternalAssetThumbnail` | `export_external_asset_thumbnail` | 从工程外 `.uasset` 导出内嵌缩略图 |
| `GetExternalAssetClassNames` | `get_external_asset_class_names` | 批量读取工程外包的真实 UE 资产类型 |
| `ResolveExternalAssetDependencies` | `resolve_external_asset_dependencies` | 从一个工程外包递归解析可迁移依赖闭包 |

Python 调用位置：

```text
UE574\Python\scripts\AssetsManagerForUE\sources\ue_asset_service.py
```

## 它不负责什么

以下功能仍由 `AssetsManagerForUE` 的 Python 服务负责，不属于本插件：

- 读取 `commonSetting.json`；
- 查询 PostgreSQL 资产数据；
- 扫描服务器资产/蓝图/特效分类目录；
- 复制 `.uasset`、`.uexp`、`.ubulk` 等包体文件；
- 根据 C++ 返回的依赖闭包复制文件并判断服务器包和工程包是否冲突；
- 资产卡片 UI、进度条和红/橙/绿状态；
- 蓝图整文件夹加载；
- 特效依赖迁移进度、确认框和 Asset Registry 刷新；
- 组件插件复制和重启 UE；
- FBX 多皮肤和动作预览。

## 部署要求

- 目标引擎：UE `5.7`；
- 插件类型：`Editor`；
- `EnabledByDefault`：`true`，安装后对未显式禁用它的工程默认开启；
- 不包含游戏运行时内容；
- 必须针对目标 UE 版本编译；
- 项目插件和引擎插件二选一，不要重复部署；
- Python 调用缩略图功能时要求插件版本不低于 `1.2.0`；
- 特效递归依赖迁移要求插件版本不低于 `1.3.0`；
- `1.3.1` 兼容 UE 5.7 的三输出 Python 返回格式，并避免等待当前工程全部
  Asset Registry 后台扫描完成；
- `1.3.2` 增加外部资产类型批量查询，供特效 Tab 只显示 Niagara System 和
  Cascade Particle System。

工作区已有 `1.3.2` 构建和正式部署脚本：

```text
E:\CGTools_for_UE\Build\build_and_deploy_assets_manager_vfx.ps1
```

它会编译桥接插件、验证版本和 DLL、部署正式引擎插件，然后部署正式
`AssetsManagerForUE` Python 包；不会创建 `_NEW` 目录。执行前必须完全关闭 UE，
并从“以管理员身份运行”的 PowerShell 启动。

正式部署到 UE 5.7 引擎插件目录时，使用：

```powershell
& "E:\CGTools_for_UE\Build\deploy_cgtools_asset_bridge.ps1"
```

该脚本只使用正式目录名 `CGToolsAssetBridge`，不会创建已经废弃的
`CGToolsAssetBridge_NEW`；执行前要求关闭 UE，并会备份当前引擎插件。

脚本的正式源码入口就是本目录下的：

```text
CGToolsAssetBridge.uplugin
```

## 是否需要进入安装包

需要区分两类安装包：

1. **给美术或开发人员安装的 UE 编辑器工具包**  
   如果要使用 `AssetsManagerForUE` 的完整拖放和外部缩略图功能，应当包含编译后的 `CGToolsAssetBridge` 插件。

2. **最终游戏 Shipping 安装包**  
   不需要。本插件的模块类型是 `Editor`，只服务于 Unreal Editor，不应作为游戏运行时插件发布。

建议编辑器工具部署包包含：

```text
CGToolsAssetBridge.uplugin
Binaries\Win64\UnrealEditor-CGToolsAssetBridge.dll
Content（当前没有）
Config
Resources（如果以后增加插件图标）
```

是否携带 `Source` 取决于使用方式：

- 只给固定 UE 5.7 二进制用户使用：可以只发布预编译插件；
- 需要换引擎版本或自行编译：必须保留 `Source`。

## 常见问题

### Python 提示“未启用 CGToolsAssetBridge 插件”

检查：

1. 工程或引擎 `Plugins` 中是否存在编译后的插件；
2. 插件管理器中 `CGTools Asset Bridge` 是否启用；
3. `Binaries\Win64` 中是否存在对应 UE 5.7 的 DLL；
4. 修改插件状态后是否已经重启 UE；
5. Output Log 中是否有模块版本不兼容或加载失败信息。

如果某个工程的 `.uproject` 已经显式写入：

```json
{
  "Name": "CGToolsAssetBridge",
  "Enabled": false
}
```

工程级禁用会覆盖插件的 `EnabledByDefault=true`，需要删除该禁用项或改成 `true`。

### 资产能加载但不能拖进关卡

这通常说明 Python 资产包服务正常，但原生桥没有加载、版本过旧，或者鼠标松手位置不在当前 `Level Viewport` 内。

### 蓝图卡片只有通用方格图标

如果服务器 `.uasset` 本身没有保存嵌入缩略图，回退到通用图标是正常行为。如果所有蓝图或特效都同时回退，应检查插件是否启用以及版本是否至少为 `1.2.0`。

### 特效只能复制主包，或提示桥版本过低

特效的材质、贴图等递归依赖解析是 `1.3.0` 新增接口。确认实际加载的插件不是
历史 `_NEW` 副本，插件管理器中启用的是正式 `CGToolsAssetBridge`，并在关闭 UE
后重新编译、部署和启动编辑器。

## 后续迁移

如果未来把整个 `AssetsManagerForUE` 改造成原生 Slate C++ 插件，本插件现有的视口放置和外部缩略图实现可以直接并入新的正式插件模块。完成合并并修改所有 Python/C++ 调用后，才应停止单独部署 `CGToolsAssetBridge`。
