# Asset Registry Repair

`AssetRegistryRepair` 是一个 UE 编辑器专用的 Content Browser 文件夹右键菜单中的【资产注册表修复 → 修复资产显示】
用以资产注册表修复 
当前插件版本：`1.0.1`；当前工作区 DLL 针对 UE `5.7.4` 编译。

`1.0.1` 修复递归恢复子文件夹资产后，`SyncBrowserToAssets` 暂时把子文件夹资产平铺显示在父文件夹的问题。递归注册逻辑保持不变，但只有位于用户明确目标文件夹直属层级的资产会参与 Content Browser 定位；更深层资产继续被修复，不会再错误出现在父目录视图。

它用于处理下面这种情况：

```text
磁盘上的 <工程>/Content 已经存在 .uasset
                    ↓
UE Asset Registry 没有发现或登记它
                    ↓
Content Browser 中看不到该资产
```

这类情况常见于：UE 编辑器运行期间由外部工具直接复制包体、批量同步版本库、手动覆盖 `Content`、资产注册表缓存没有及时更新，或者普通目录扫描没有把包内对象重新登记出来。

## 是否可以删除

可以删除，但是否应该删除取决于是否还需要手动修复功能。

- Content Browser 文件夹右键菜单中的【资产注册表修复 → 修复资产显示】会消失；
- 蓝图、Python 或其他编辑器工具不能再调用本插件提供的修复函数。

如果团队经常把 `.uasset` 直接复制到正在运行的 UE 工程中，建议保留它作为独立的人工兜底工具。如果所有资产都只通过 UE 正常导入，并且从未遇到“文件在磁盘上但 Content Browser 看不见”，可以不部署。

### 源码目录与已安装插件

正式源码目录：

```text
E:\CGTools_for_UE\UE574\Plugins\Marketplace\AssetRegistryRepair
```

## 使用方法

1. 在 UE Content Browser 左侧文件夹树中选择 `/Game` 或它下面的一个或多个文件夹。
2. 右键所选文件夹。
3. 找到【资产注册表修复】分组。
4. 点击【修复资产显示】。
5. 等待扫描和缺失包加载完成；资产较多时会显示可取消的进度窗口。

右键菜单只接受 `/Game` 路径。Content Browser 的 `/All/Game/...` 会自动转换成 `/Game/...`。

## 右键菜单的实际默认行为

当前 C++ 菜单命令采用以下默认参数：

```text
修改时间限制：       0 分钟，即扫描全部时间
包含 .umap：         否
强制加载缺失包：     是
最多加载缺失包：     2000
最多定位到浏览器资产：5
```

注意：当前菜单 Tooltip 写了“资产和地图”，但实现中的 `bIncludeMaps` 默认值实际为 `false`，所以右键菜单默认只处理 `.uasset`，不处理 `.umap`。如需处理地图，应通过 C++、蓝图或 Python 调用公开函数并显式传入 `bIncludeMaps=true`。

## 修复流程

插件按以下顺序执行：

1. 将选中的虚拟 `/Game/...` 路径转换为工程 `Content` 下的磁盘目录；
2. 递归查找 `.uasset`，可选查找 `.umap`；
3. 跳过 World Partition 外部对象和集合目录；
4. 按修改时间过滤文件；
5. 调用 `ScanModifiedAssetFiles`；
6. 调用 `ScanFilesSynchronous` 并等待 Asset Registry 完成；
7. 检查哪些包仍未出现在 Asset Registry；
8. 在数量限制内加载缺失包；
9. 对包内有效资产调用 `FAssetRegistryModule::AssetCreated`；
10. 再扫描一次，并把恢复的资产或目标文件夹定位到 Content Browser。

默认跳过：

```text
__ExternalActors__
__ExternalObjects__
Collections
```

这样可以避免把 World Partition 的外部 Actor 包和集合文件当成普通内容资产逐个加载。

## 它不会做什么

本插件只修复当前编辑器进程中的资产发现和登记问题，不会：

- 从服务器复制资产；
- 导入 FBX、贴图或动画；
- 修复损坏或版本不兼容的 `.uasset`；
- 自动补齐缺少的依赖包；
- 修复材质、碰撞、骨架或蓝图逻辑；
- 修复重定向器；
- 修改包体内容；
- 保存、覆盖或删除服务器文件；
- 替代完整的资产迁移流程。

如果 `.uasset` 本身损坏、由不兼容的 UE 版本保存，或者依赖丢失，修复操作可能加载失败，结果中的 `FailedPackageCount` 会增加。

## 对外接口

插件通过 `UAssetRegistryRepairLibrary` 提供以下 Blueprint Callable 接口：

| C++ 接口 | 用途 |
|---|---|
| `GetContentBrowserRepairTargetFolders` | 获取 Content Browser 当前选中或正在浏览的有效 `/Game` 文件夹 |
| `RepairSelectedContentBrowserFolders` | 修复当前 Content Browser 文件夹 |
| `RepairAssetRegistryFromDiskInFolders` | 修复调用方明确传入的一个或多个虚拟文件夹 |

`RepairSelectedContentBrowserFolders` 的函数默认参数与右键菜单不同：

```text
ModifiedWithinMinutes = 30
bIncludeMaps = false
bForceLoadMissingPackages = true
MaxPackagesToLoad = 200
MaxAssetsToSync = 30
```

`RepairAssetRegistryFromDiskInFolders` 接受相同的控制参数，适合其他工具精确限定扫描范围。

## 返回结果

`FAssetRegistryRepairResult` 会返回：

- 是否成功；
- 是否被用户取消；
- 实际目标文件夹；
- 找到的磁盘文件数；
- 被时间条件跳过的文件数；
- 被目录规则跳过的文件数；
- 实际扫描文件数；
- 转换出的包数量；
- 原本已经可见的包数量；
- 仍然缺失的包数量；
- 成功加载的包数量；
- 加载失败的包数量；
- 因加载上限跳过的包数量；
- 手动登记的资产对象数量；
- 汇总消息。

详细结果同时写入 Output Log，日志类别为：

```text
LogAssetRegistryRepair
```

右键菜单的最终汇总还会通过 `LogTemp` 输出。

## 性能与安全提示

- 优先选择出现问题的最小文件夹，不要习惯性对整个 `/Game` 执行修复；
- 选择 `/Game` 时可能递归枚举全部 `.uasset`，并最多加载 2000 个缺失包；
- 强制加载包可能触发依赖加载、编译或错误日志，工程越大耗时越长；
- 进度窗口允许取消，取消后结果中的 `bCanceled` 为 `true`；
- 插件不写入或覆盖 `.uasset`，但会加载对象并更新当前 UE 进程中的 Asset Registry 状态；
- 修复完成后仍看不到资产时，应检查包版本、依赖和 Output Log，而不是反复对整个工程扫描。

## 部署要求

- 模块类型：`Editor`；
- 当前插件版本：`1.0.1`；
- 当前 DLL：UE `5.7.4` / Win64；
- `EnabledByDefault`：`true`；
- 可以安装到 Engine，也可以安装到单个 Project，但不要重复安装；
- 升级 UE 后需要针对新引擎重新编译。

给固定 UE 5.7 编辑器用户分发时，工具包应包含：

```text
AssetRegistryRepair.uplugin
Binaries\Win64\UnrealEditor-AssetRegistryRepair.dll
Resources\Icon128.png
Config
README.md
```

可选内容：

- `Source`：需要自行编译或升级引擎时保留；
- `.pdb`：只在需要调试符号时保留。

不应放入正式分发包：

```text
Intermediate
*.rsp
*.obj
*.exp
*.lib
```

## 是否进入安装包

需要区分安装包类型：

1. **CGTools/UE 编辑器工具安装包**  
   如果希望所有使用者都能通过 Content Browser 右键修复资产显示，应包含编译后的插件；如果不需要这项人工修复能力，可以不包含。

2. **最终游戏 Shipping 安装包**  
   不需要。它是 `Editor` 模块，只用于编辑器，不属于游戏运行时功能。

## 与 AssetsManagerForUE 的关系

`AssetsManagerForUE` 在复制包体后有自己的 Asset Registry 刷新流程；正常情况下不需要用户再运行本插件。

本插件适合作为异常情况下的独立兜底工具，例如：

```text
AssetsManager 已复制文件
        ↓
因为缓存、外部覆盖或异常状态，Content Browser 仍未显示
        ↓
在问题文件夹上执行“修复资产显示”
```

如果未来把 `AssetsManagerForUE` 完整迁移为 C++ 插件，可以选择复用 `UAssetRegistryRepairLibrary`，或者把其中的定向扫描和缺失包登记逻辑并入新的资产服务模块。
