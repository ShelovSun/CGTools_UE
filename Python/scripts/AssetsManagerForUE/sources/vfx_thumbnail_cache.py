"""Visible-card thumbnail requests serviced by a separate, read-only UE process."""

import json
import os
import tempfile
import time
from pathlib import Path

from PySide6 import QtCore


def pending_assets(assets, attempted=()):
    return [asset for asset in assets if asset["thumbnail"] not in attempted
            and not os.path.isfile(asset["thumbnail"])
            and not os.path.isfile(asset["no_thumbnail"])]


class VfxThumbnailCache(QtCore.QObject):
    ready = QtCore.Signal(str, str)
    warning = QtCore.Signal(str)

    def __init__(self, engine_dir, parent=None):
        super(VfxThumbnailCache, self).__init__(parent)
        self.engine_dir = Path(engine_dir)
        self.process = None
        self.job = None
        self.assets = []
        self.content_root = ""
        self.attempted = set()
        self.disabled = False
        self.offset = 0
        self.started = 0
        self.last_progress = 0
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)

    def request(self, assets, content_root):
        if self.content_root and self.content_root != str(content_root):
            self.stop()
        self.assets = list(assets)
        self.content_root = str(content_root)
        if self.disabled:
            return
        try:
            if self.process is not None:
                self._writeRequests()
            elif pending_assets(self.assets, self.attempted):
                self._start()
        except OSError as exc:
            self.disabled = True
            self.stop()
            self.warning.emit("无法写入特效缩略图请求：{0}".format(exc))

    def reset_failures(self):
        self.attempted.clear()
        self.disabled = False

    def _writeRequests(self):
        if self.job is None:
            return
        data = {"content_root": self.content_root,
                "assets": [{key: asset.get(key) for key in (
                    "source_file", "thumbnail", "no_thumbnail", "source_signature")}
                    for asset in pending_assets(self.assets, self.attempted)]}
        temporary = self.job / "requests.writing.json"
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(temporary), str(self.job / "requests.json"))

    def _start(self):
        executable = self.engine_dir / "Binaries/Win64/UnrealEditor-Cmd.exe"
        if not executable.is_file():
            self.disabled = True
            self.warning.emit("找不到缩略图后台程序：{0}".format(executable))
            return
        try:
            root = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "AssetsManagerVfxThumbnails/Workers"
            root.mkdir(parents=True, exist_ok=True)
            # Windows TEMP may use ADMINI~1. UE mixes long and short paths when
            # mounting /Game, which can cause a fatal package-name conversion.
            root = root.resolve()
            self.job = Path(tempfile.mkdtemp(prefix="session_", dir=str(root)))
            (self.job / "Content").mkdir()
            project = self.job / "VfxThumbnailWorker.uproject"
            project.write_text(json.dumps({
                "FileVersion": 3, "EngineAssociation": "5.7",
                "DisableEnginePluginsByDefault": True,
                "Plugins": [{"Name": name, "Enabled": True} for name in (
                    "PythonScriptPlugin", "Niagara", "CGToolsAssetBridge")],
            }), encoding="utf-8")
            self._writeRequests()
            process = QtCore.QProcess(self)
            environment = QtCore.QProcessEnvironment.systemEnvironment()
            environment.insert("CGTOOLS_VFX_THUMBNAIL_JOB", str(self.job))
            process.setProcessEnvironment(environment)
            process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
            process.setStandardOutputFile(str(self.job / "worker.log"))
            process.finished.connect(self._finished)
            process.errorOccurred.connect(self._processError)
            process.started.connect(self._lowerPriority)
            self.process = process
            self.offset = 0
            self.started = self.last_progress = time.monotonic()
            script = Path(__file__).with_name("vfx_thumbnail_worker.py")
            process.start(str(executable), [str(project), "-run=pythonscript",
                "-script={0}".format(script.as_posix()), "-CGToolsThumbnailWorker",
                "-unattended", "-NullRHI", "-NoSound", "-NoSplash", "-NoCrashDialog",
                "-nosourcecontrol", "-stdout", "-FullStdOutLogOutput"])
            self.timer.start()
        except OSError as exc:
            self.disabled = True
            self.warning.emit("无法启动特效缩略图缓存：{0}".format(exc))

    def _lowerPriority(self):
        if os.name != "nt" or self.process is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x0200, False, int(self.process.processId()))
            if handle:
                try:
                    kernel.SetPriorityClass(handle, 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
                finally:
                    kernel.CloseHandle(handle)
        except (OSError, AttributeError):
            pass

    def _readResults(self):
        if self.job is None:
            return
        try:
            with (self.job / "results.jsonl").open("rb") as stream:
                stream.seek(self.offset)
                for line in stream:
                    # The worker may still be writing the last record.
                    if not line.endswith(b"\n"):
                        break
                    self.offset += len(line)
                    result = json.loads(line.decode("utf-8"))
                    self.last_progress = time.monotonic()
                    if result.get("fatal"):
                        self.disabled = True
                        self.warning.emit(result["fatal"])
                        continue
                    png = result["thumbnail"]
                    self.attempted.add(png)
                    if result.get("success") and os.path.isfile(png):
                        self.ready.emit(result["source_file"], png)
                    elif not result.get("error", "").startswith("NO_THUMBNAIL|"):
                        self.warning.emit("特效缩略图读取失败：{0}；{1}；日志：{2}".format(
                            result["source_file"], result.get("error"), self.job / "worker.log"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError) as exc:
            self.disabled = True
            self.warning.emit("读取缩略图缓存结果失败：{0}".format(exc))

    def _poll(self):
        self._readResults()
        if self.process is not None and time.monotonic() - self.last_progress > 240:
            self.disabled = True
            self.warning.emit("缩略图后台进程超时，已停止；日志：{0}".format(self.job / "worker.log"))
            self.stop()

    def _finished(self, exit_code, exit_status):
        self._readResults()
        process, self.process = self.process, None
        self.timer.stop()
        if process is not None:
            process.deleteLater()
        if exit_code != 0:
            self.disabled = True
            self.warning.emit("缩略图后台进程退出（{0}）；日志：{1}".format(exit_code, self.job / "worker.log"))
        if not self.disabled and pending_assets(self.assets, self.attempted):
            QtCore.QTimer.singleShot(0, self._restartPending)

    def _restartPending(self):
        if not self.disabled and self.process is None and pending_assets(self.assets, self.attempted):
            self._start()

    def _processError(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self.disabled = True
            self.warning.emit("特效缩略图后台进程启动失败；日志：{0}".format(self.job / "worker.log"))
            self.stop()

    def stop(self):
        self.timer.stop()
        self.assets = []
        process, self.process = self.process, None
        if process is not None:
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(500)
            process.deleteLater()
