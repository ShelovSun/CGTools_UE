# CGTools for Unreal Engine 5.7

Git 仓库根目录为 `UE574`，用于管理 UE Python 工具和原生插件。

- [Python](Python/README.md)：AssetsManager、ShotsManager 和配套 Python 工具。
- [CGToolsPublisher](Plugins/Marketplace/CGToolsPublisher/README.md)：UE 资产发布插件，当前版本 **1.8.0**，支持同类型资产在同一窗口批量发布。

2026-11-03 将原 `Python` 仓库扩大到本目录。保留原提交历史，通过一次普通提交将原路径归入 `Python/`，没有改写历史。查看旧 Python 文件历史时可使用 `git log --follow -- Python/文件路径`。

`Plugins/Marketplace` 下的以下 8 个配套插件纳入版本管理，包括源码、描述文件、配置、内容和运行资源，以及现有的 DLL 和模块清单：

- AssetRegistryRepair
- BlueprintComponentTools
- BlueprintScript
- CGToolsAssetBridge
- CGToolsFolderOrganizer
- CGToolsMayaBridge
- CGToolsPublisher
- SequencerEaseTools

其中 CGToolsPublisher 明确依赖 AssetRegistryRepair；其他插件提供资产管理、蓝图、Maya 通信、特效和 Sequencer 等配套功能。第三方插件保留各自的版权声明和许可证。

HoudiniNiagara 和 ExtContentBrowser 不纳入本仓库版本管理，其本地目录已加入 `.gitignore`，后续不随此仓库提交。需要使用时单独安装；Git 中排除它们不会删除本地安装文件。ExtContentBrowser 的本地安装暂时保留，后续另行清理。

仓库保留插件 `.uasset` 的 **Git LFS** 规则，供今后管理二进制内容使用。当前版本没有需要下载的 LFS 资产；查看早期提交、恢复其中的 LFS 内容时，需先安装 Git LFS，再在仓库根目录执行：

```shell
git lfs install --local
git lfs pull
```

DLL 和 `UnrealEditor.modules` 作为现有 UE 5.7.4 分发版本一同保存；修改 C++ 源码后，需要重新编译并同时更新它们。`Intermediate`、`Saved`、Python 缓存、PDB、临时日志等生成文件由 `.gitignore` 排除。

工作区上一级的 `Build` 保存本地构建、部署和服务器同步脚本，以及生成的编译包、隔离测试工程、测试结果、截图、同步收据和旧版备份。它位于 Git 仓库之外，生成物不随源码提交。插件的真正开发源码位于 `Plugins/Marketplace/<插件名>/Source`，不在测试工程或构建输出副本中。

共享分发路径为 `Y:\MCCTools\src\UE574`。同步服务器与 Git 提交是两项独立操作：前者更新同事安装器使用的完整已测试工具，后者记录开发版本。服务器同步后，同事仍需通过现有安装器更新并重启 UE。
