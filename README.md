# CGTools for Unreal Engine 5.7

Git 仓库根目录为 `UE574`，用于管理 UE Python 工具和原生插件。

- [Python](Python/README.md)：AssetsManager、ShotsManager 和配套 Python 工具。
- [CGToolsPublisher](Plugins/Marketplace/CGToolsPublisher/README.md)：UE 资产发布插件，当前版本 **1.8.0**，支持同类型资产在同一窗口批量发布。

2026-11-03 将原 `Python` 仓库扩大到本目录。保留原提交历史，通过一次普通提交将原路径归入 `Python/`，没有改写历史。查看旧 Python 文件历史时可使用 `git log --follow -- Python/文件路径`。

本次新纳入版本管理的是完整的 CGToolsPublisher 分发内容，包括源码、描述文件、运行资源、第三方运行库及与 UE 5.7.4 匹配的 DLL 和模块清单。其他插件按后续实际任务逐步纳入，避免把无关插件混入本次发布提交。

工作区上一级的 `Build` 保存本地构建、部署和服务器同步脚本，以及生成的编译包、隔离测试工程、测试结果、截图、同步收据和旧版备份。它位于 Git 仓库之外，生成物不随源码提交。插件的真正开发源码位于 `Plugins/Marketplace/CGToolsPublisher/Source`，不在测试工程或构建输出副本中。

共享分发路径为 `Y:\MCCTools\src\UE574`。同步服务器与 Git 提交是两项独立操作：前者更新同事安装器使用的完整已测试工具，后者记录开发版本。服务器同步后，同事仍需通过现有安装器更新并重启 UE。
