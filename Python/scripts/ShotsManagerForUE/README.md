# ShotsManagerForUE

当前版本：**2.0.4**。

## 启动进度

通过 `CGTools > ShotsManager` 启动时，先显示与 AssetsManager 相同的 UE 原生“正在启动...”进度窗口；等待两次 Slate post-tick 让窗口绘制后，再导入 PySide6 和 ShotsManager 主模块、初始化界面及项目/镜头列表。进度在模块加载、界面创建、初始化完成三个阶段推进，界面准备好后关闭。

启动期间重复点击会合并为同一次启动。导入或初始化失败会关闭进度窗口并在 UE 输出日志中报告原因；启动窗口被销毁时也会清理。输出日志记录模块导入、窗口创建及总准备耗时，便于观察首次启动的等待位置。进度提示本身不消除同步导入和网络读取耗时。

UE Python 控制台启动入口：

```python
from ShotsManagerForUE import launcher as SM
SM.showWin()
```

也可以执行 `start_shots_manager.py`。直接导入 `ShotsManagerForUE.ShotsManager_UE` 会先导入 Qt，不能在首次导入前显示启动提示，因此菜单及脚本统一使用轻量 launcher。

启动回归检查：

```powershell
python -B -m unittest discover -s UE574/Python/scripts/ShotsManagerForUE/tests -v
```
