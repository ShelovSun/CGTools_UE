# CGTools Folder Organizer

`CGToolsFolderOrganizer` 是 UE 5.7 编辑器插件，用来在内容浏览器的文件夹右键菜单中提供可扩展的资产整理命令。

当前版本：`1.0.0`

## 使用方法

1. 在内容浏览器左侧文件夹大纲中选择一个 `/Game` 子文件夹。
2. 右键选择【整理文件夹】>【整理特效文件夹】。
3. 查看扫描统计和移动数量，确认后开始整理。

为防止误操作，插件只允许一次选择一个 `/Game` 子文件夹，也不允许直接整理整个 `/Game` 根目录。

## 特效文件夹整理规则

插件会递归扫描所选文件夹及其所有子文件夹，并按 UE 的真实资产类判断，而不是根据文件名前缀判断。

| 资产类型 | 目标目录 |
|---|---|
| `UMaterialFunctionInterface` 及派生类 | `<所选文件夹>/M_F` |
| `UMaterialInterface` 及派生类 | `<所选文件夹>/Mat` |
| `UStaticMesh`、`USkeletalMesh`、`USkeleton`、`UPhysicsAsset` | `<所选文件夹>/Mesh` |
| `UTexture` 及派生类 | `<所选文件夹>/Tex` |
| `UNiagaraSystem` | 所选文件夹根目录 |
| `UParticleSystem`（Cascade） | 所选文件夹根目录 |
| 其他类型 | 保持原位 |

`M_F`、`Mat`、`Mesh`、`Tex` 会在确认后建立，即使其中某一类暂时没有资产。

## 安全策略

- 执行前会显示递归扫描数量、各类型移动数量、已经正确分类数量及未识别数量。
- 所有目标路径会在移动前统一检查。
- 如果任何目标位置已经存在同名包，整个操作立即取消，不覆盖、不自动改名，也不会先移动一部分。
- 资产通过 UE `AssetTools` 移动，UE 会更新硬引用和软引用；插件不会直接移动磁盘上的 `.uasset`。
- 移动成功后只收集并修复本次移动源位置生成的 Redirector，不会顺便处理文件夹中早已存在的其他 Redirector。
- 如果 UE 报告批量移动失败，可能已经发生部分移动；插件会弹窗提示，并要求查看 Output Log 后重新检查文件夹。

建议在有版本控制或备份的工程中使用。整理前请确保相关资产没有被其他用户锁定。

## 扩展方式

后续文件夹整理类型继续添加在【整理文件夹】子菜单中，不需要再占用内容浏览器的一级右键菜单。

## 构建与部署

关闭 UE，以管理员身份打开 PowerShell，然后运行：

```powershell
& 'E:\CGTools_for_UE\Build\build_and_deploy_folder_organizer.ps1'
```

脚本会用 UE 5.7 AutomationTool 编译 Win64 编辑器插件，验证 DLL，将编译结果同步回工作区，并备份后部署到：

```text
C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Marketplace\CGToolsFolderOrganizer
```
