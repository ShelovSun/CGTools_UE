# CGTools Maya Bridge 1.2.1（UE 5.7）

这个 Editor 插件接收 Maya `PublishTools` 发出的动作发布消息。在 UE 收到并验证消息后，它会立刻给 Maya 返回 ACK，然后在 UE 游戏线程弹出一次批量确认框；选择 Yes 后，检查 Skeleton 并导入动画 FBX。若工程中缺少 Skeleton，会先询问是否加载资产；加载未能提供 Skeleton 时，再询问是否执行【Import FBX】。

网络线程只负责收包和 ACK。收到的消息进入线程安全队列，并由普通 Editor Tick 在游戏线程消费；不要改回 `AsyncTask(GameThread)` 后直接同步调用 Interchange，否则 UE 5.7 会触发 TaskGraph 递归保护断言。

整批导入结束后，内容浏览器会主动定位并选中本次成功导入的动画序列。直接导入、先加载 UE 资产、先通过【Import FBX】补齐资产，均使用同一段定位逻辑；多选发布会选中本批成功导入的动作。

## 默认映射

插件默认采用当前工具已有的目录约定：

```text
Skeleton: /Game/Assets/{asset_type}/{asset_name}/{asset_name}_Skeleton
Animation: /Game/Assets/{asset_type}/{asset_name}/Action
```

例如 `Characters / Nujian / Run` 会查找：

```text
/Game/Assets/Characters/Nujian/Nujian_Skeleton
```

并把动画导入到：

```text
/Game/Assets/Characters/Nujian/Action/Run
```

## 配置

Bridge 的端口和 UE 路径映射配置位于 `Config/BridgeSettings.json`。

- `port`：默认 `19821`。环境变量 `CGTOOLS_UE_BRIDGE_PORT` 会覆盖这个值，Maya 与 UE 必须相同。
- `skeleton_template`、`animation_path_template`：全局路径模板。
- `replace_existing`：同名动作是否自动覆盖。
- `asset_overrides`：给特殊资产覆盖 Skeleton 或动画目录。

覆盖示例：

```json
{
  "port": 19821,
  "skeleton_template": "/Game/Assets/{asset_type}/{asset_name}/{asset_name}_Skeleton",
  "animation_path_template": "/Game/Assets/{asset_type}/{asset_name}/Action",
  "replace_existing": true,
  "asset_overrides": [
    {
      "project_name": "GOF",
      "asset_type": "Characters",
      "asset_name": "Nujian",
      "skeleton": "/Game/Characters/Nujian/Rig/Nujian_Skeleton",
      "animation_path": "/Game/Characters/Nujian/Animations"
    }
  ]
}
```

`asset_overrides[].project_name` 可留空，表示该覆盖适用于所有项目；`asset_type` 和 `asset_name` 必填。

服务器资产根目录读取资产管理器共用的 `Y:\MCCTools\config\ShotManager_config\commonSetting.json` 中的 `rootPath`。例如 `rootPath` 为 `Y:/MCCProject` 时，`GOF / Props / Yu015QiePian` 对应 `Y:/MCCProject/GOF/Assets/Props/Yu015QiePian`。不从动作库的 `Animations` 目录加载模型。

## 缺少 Skeleton 时的处理

1. 弹出【缺少骨架：是否加载资产？】，显示资产源目录和目标 Skeleton 路径。选择 Yes 后执行资产加载，注册拷贝的 UE 资源并重新查找 Skeleton；找到后继续原来的动画导入。
2. 若源资产没有可加载的 UE 文件，明确提示“该资产还没有可加载的 UE 文件”，询问是否执行【Import FBX】。其他加载失败会显示实际原因，例如目录无法访问或加载后仍没有指定 Skeleton。
3. 选择 Yes 后，与资产卡片的【Import FBX】共用同一套导入逻辑，读取 `<资产目录>/FBX/<资产名>.fbx`，导入到 `/Game/Assets/<类型>/<资产名>` 并保存。重新找到目标 Skeleton 后，继续导入本次动作。
4. 任一步选择 No，或 FBX 导入后仍没有指定 Skeleton，该资产的动作会跳过并在结果框中说明原因。同一批中相同资产、相同 Skeleton 的失败或取消只询问一次。

Bridge 加载 UE 资产时，所有已有同名文件均保留工程版本，只复制工程中缺少的文件。共享材质、贴图等即使内容不同，也不会阻止其他资源加载或触发 FBX 回退；加载完成后仍需找到指定 Skeleton 才能继续导入动作。使用自定义 `asset_overrides` 时，目标 Skeleton 路径仍须与资产实际提供的 Skeleton 一致；【Import FBX】采用上面的标准目录。

## 安装与更新

原生插件与资产管理器 Python 文件需要一起更新。插件包包含 `Content/Python/cgtools_maya_bridge_assets.py`；以下模块安装在 `Engine/Content/Python/scripts/AssetsManagerForUE/sources`：

- `assetTools.py`
- `asset_fbx_service.py`
- `maya_bridge_service.py`

插件启用 `PythonScriptPlugin` 和 `EditorScriptingUtilities`，恢复操作不需要打开资产管理器窗口或登录数据库。Python 依赖沿用现有工具环境。

关闭所有 UE 编辑器后，运行工作区中的 `Build/deploy_maya_bridge_asset_recovery.ps1` 安装已经编译好的 1.2.1 插件和配套 Python 文件。脚本会备份当前安装并保留现有 `BridgeSettings.json`。再次启动 UE 后生效。

## 运行与排查

插件不读取也不比较 `.uproject` 文件名，所有合法的 Maya 动作发布消息都由当前监听实例接收。它只监听 `127.0.0.1`，不会开放局域网端口。第一台成功占用 `19821` 端口的 UE Editor 是唯一接收实例；之后打开的 UE Editor 因端口已被占用，只会禁用自己的 Bridge，不会弹窗，也不会阻止 Editor 启动。UE Output Log 中用 `LogCGToolsMayaBridge` 搜索即可看到监听、拒绝、导入和错误信息。

如果加载资产或导入模型 FBX 后仍没有指定 Skeleton，结果框会显示实际原因以及本次查找的 `/Game/...` 路径。若 Maya 的 `Y:` 映射盘在 UE 工作站不可见，需要让两边使用相同映射，或在 Maya 发布端发送 UE 可访问的路径。
