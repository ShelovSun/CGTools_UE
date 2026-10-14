# AssetsManagerForUE：UE 资产发布与使用

## 服务器发布目录

旧版资产的数据库、Icon、FBX、Action 等路径规则全部保持不变。新增的 UE 最终资产放在每个资产根目录的 `UE/Content` 下，并完整保留它们在项目 `Content` 中的相对路径。

数据库地址统一取自设置窗口打开的 `Y:\MCCTools\config\ShotManager_config\commonSetting.json` 的 `host` 字段。当前应配置为 `"host": "smnas.diandian.info"`，PostgreSQL 端口仍为 `5432`。资产页、场景页、原生后端和发布插件不再使用写死的服务器地址。缺少有效 `host` 时会提示配置错误；下一次数据库连接会重读配置，因此修改 JSON 后刷新数据即可使用新地址。数据库地址修改不会改变 `rootPath`、MCCTools 或 Y: 文件路径。

以 `GuoWang` 为例：

```text
Y:\MCCProject\S01\Assets\Characters\GuoWang\
├─ Icon\                         # 旧版缩略图，继续使用
├─ FBX\                          # 旧版 FBX，继续使用
├─ Action\                       # 旧版动作，继续使用
└─ UE\
   ├─ asset_manifest.json        # 可选；指定卡片拖放时使用的主资产
   └─ Content\
      └─ Assets\Characters\GuoWang\
         ├─ BP_GuoWang.uasset
         ├─ SK_GuoWang.uasset
         ├─ SK_GuoWang.uexp      # 若存在，必须一并发布
         ├─ Materials\...
         ├─ Textures\...
         └─ Action\...
```

加载时会镜像复制为：

```text
<当前工程>\Content\Assets\Characters\GuoWang\...
```

不能在发布后移动或改名 `.uasset`，因为材质、骨架、蓝图等内部引用使用 `/Game/...` 包路径。源资产必须使用和目标工程兼容的 Unreal Engine 版本保存。

## 可选主资产清单

如果一个发布目录里有多个 Actor 蓝图或网格体，可在 `UE/asset_manifest.json` 明确指定拖放主资产：

```json
{
  "schema": 1,
  "mainObjectPath": "/Game/Assets/Characters/GuoWang/BP_GuoWang.BP_GuoWang"
}
```

不提供清单时会自动按以下优先级选择：

```text
Actor Blueprint > StaticMesh > SkeletalMesh
```

## 卡片状态

【资产】和【场景】页确认服务器上的资产有 `UE` 文件夹后，在缩略图右上角显示亮绿色“UE”文字。没有 UE 文件夹、正在检查或暂时无法确认时不显示标记。文字与深色底使用同一套绘制逻辑，直接复用各页已有的后台扫描结果。

“UE”表示发布目录存在。【资产】页的【加载资产】是否可用，还需要检查目录里是否有 `.uasset` 或 `.umap` 主包。空 UE 文件夹或只有 `.uexp`、`.ubulk`、`.uptnl` 等附属文件时，仍显示“UE”，但【加载资产】为灰色。正在检查或无法确认有主包时，该命令也为灰色。

悬停卡片可以查看具体原因。检查在后台进行；【资产】页排序、搜索和切换显示方式复用缓存，点击【刷新】重新检查，主动加载前还会再次核对源文件。

底部状态线表示当前工程的加载状态，与右上角“UE”标记独立：

- 红线：尚未加载、没有 UE 发布包，或者加载/注册失败。
- 橙线：部分文件、正在加载、路径冲突，或包内没有可直接放入关卡的资产。
- 绿线：包已在当前工程中，并已找到可拖放的主资产。
- 加载过程中缩略图上显示按字节计算的进度。

目标工程中出现同名但不同内容的文件时，工具会停止并显示冲突，不会静默覆盖。复制中途失败时，只回滚本次新建的文件。

## FBX 预览与动作库

多皮肤资产按以下配对规则显示：

```text
Icon\<资产名>_<皮肤名>.png
FBX\<资产名>_<皮肤名>.fbx
```

发现至少两套有效配对时，预览器不再显示可能包含全部皮肤的汇总 FBX，而是默认显示自然排序后的第一套皮肤。可用视口左右箭头或底部皮肤缩略图切换；切换后，动作库中选中的动作会重新套用到当前皮肤 FBX。三维预览显示有限地面网格，右下角按钮可在 FBX 三维预览与 Icon 图片预览之间切换。

动作库显示【名字】【修改日期】【大小】三列，点击表头可以排序。右侧底部不再放置【加载资产】与【Import FBX】按钮，这两项功能继续保留在资产卡片右键菜单中。

## 使用方式

1. 在【资产】页右键点击卡片，确认【加载资产】可用后选择该命令。
2. 底部状态线变绿后，按住卡片拖到 Level Viewport 内，在目标位置松开。
3. 原来的【Import FBX】、动作 FBX 导入、FBX 预览和场景页仍可照常使用。
4. 【蓝图】页按服务器文件夹显示分类；点击分类内任意卡片的【加载蓝图】，都会完整加载该分类，避免关联蓝图缺失。

## C++ 组件库

【组件】页读取：

```text
Y:\MCCTools\src\UE574\CppComponent\<分类>\<组件名>\
```

例如：

```text
Y:\MCCTools\src\UE574\CppComponent\排队小人\CrowdQueueRuntime\
├─ CrowdQueueRuntime.uplugin
├─ CrowdQueueRuntime.png          # 卡片图标；与组件文件夹同名
├─ Source\...
├─ Binaries\...
├─ Content\...
└─ Resources\...
```

左侧显示 `CppComponent` 下的一级分类，右侧每个直接子文件夹是一张组件卡片。点击【加载组件】后，整个组件目录会复制到：

```text
<当前工程>\Plugins\<组件名>
```

组件卡片右键菜单中的【使用说明】会查找组件根目录下的 `.md` 文件；如果有多个文档，按文件名排序并显示第一个。如果没有 Markdown 文档，工具会弹窗提示联系组件制作者。

使用说明会在组件卡片区右侧的可关闭面板中显示，支持 Markdown 文字格式、本地图片、GIF 动画和可点击链接。文档中的相对媒体路径以 `.md` 所在目录为基准；例如 `![操作演示](images/demo.gif)`。面板右上角的【外部打开】仍可调用系统默认 Markdown 程序。

复制成功后工具会询问是否立即重启 UE。选择【是】时会先显示 UE 的未保存内容对话框，然后退出并重新打开当前 `.uproject`。如果工程中已经存在不同版本，工具会先暂存服务器版本，等 UE 完全退出后再替换；原版本备份在：

```text
<当前工程>\Saved\AssetsManagerForUE\ComponentBackups
```

组件卡片只负责安装编辑器/运行时插件，不能拖入关卡。组件目录必须在根部包含唯一、有效的 `.uplugin` 描述文件。

## 原生拖放桥

精确落点由 `CGToolsAssetBridge` 编辑器插件负责。源码位于：

```text
UE574\Plugins\Marketplace\CGToolsAssetBridge
```

插件必须针对 UE 5.7 编译、部署并启用。若未启用，最终资产仍能加载进工程，但拖放会明确提示缺少插件，不会使用不准确的摄像机前方生成方式。
