"""Shared asset/scene thumbnail capture; network writes never run on the GUI thread."""

import os
import tempfile
import weakref

from PySide6 import QtCore, QtGui, QtWidgets


_UPDATES = set()  # Retain jobs until their queued completion signal has been delivered.
_CAPTURING = None
_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
            ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP"}


def _path_key(path):
    return os.path.normcase(os.path.normpath(str(path or "")))


def icon_path(item):
    try:
        return str(item.itemData()[7] or "")
    except (IndexError, TypeError, RuntimeError):
        return ""


def _asset_root(path):
    normalized = path.replace("\\", "/")
    marker = normalized.lower().find("/icon/")
    if marker >= 0:
        return normalized[:marker]
    return os.path.dirname(os.path.dirname(path))


def save_thumbnail(captured_path, destination):
    """Decode/re-encode to the original format and atomically replace the icon.

    Called only by a worker. QSaveFile leaves the original intact on failure.
    """
    fmt = _FORMATS.get(os.path.splitext(destination)[1].lower())
    if not fmt or not os.path.isabs(destination):
        raise ValueError("资产 icon 路径无效或图片格式不支持：\n" + destination)
    root = _asset_root(destination)
    if not os.path.isdir(root):
        raise OSError("资产文件夹不存在或无法访问：\n" + root)
    image = QtGui.QImage(captured_path)
    if image.isNull():
        raise OSError("无法读取截图：\n" + captured_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    output = QtCore.QSaveFile(destination)
    output.setDirectWriteFallback(False)
    if not output.open(QtCore.QIODevice.WriteOnly):
        raise OSError("无法写入缩略图：\n{}\n{}".format(destination, output.errorString()))
    if not image.save(output, fmt, 95):
        error = output.errorString()
        output.cancelWriting()
        output.commit()  # Close/remove the temporary file before reporting the error.
        raise OSError("缩略图编码失败：\n{}\n{}".format(destination, error))
    if not output.commit():
        raise OSError("缩略图替换失败：\n{}\n{}".format(destination, output.errorString()))
    # Use the saved image so JPEG compression and immediate display agree.
    saved = QtGui.QImage(destination)
    return saved if not saved.isNull() else image


class _WriteSignals(QtCore.QObject):
    finished = QtCore.Signal(object, str)


class _WriteWorker(QtCore.QRunnable):
    def __init__(self, captured_path, destination):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _WriteSignals()
        self.captured_path = captured_path
        self.destination = destination

    def run(self):
        try:
            image = save_thumbnail(self.captured_path, self.destination)
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))
        else:
            self.signals.finished.emit(image, "")


def refresh_cards(owner, destination, image):
    """Refresh current cards by path, rather than retaining a possibly deleted Item."""
    key = _path_key(destination)
    widget = owner.main_listWgt
    for index in range(widget.count()):
        item = widget.item(index)
        if _path_key(icon_path(item)) == key:
            item.setThumbnailImage(image)
    preview = getattr(owner, "preview_wgt", None)
    if preview is not None and hasattr(preview, "refreshThumbnail"):
        preview.refreshThumbnail(destination, image)


class _Update(QtCore.QObject):
    def __init__(self, owner, destination):
        super().__init__()
        self.owner = weakref.ref(owner)
        self.destination = destination
        self.window = None
        self.restore_window = False
        self.temporary = None
        self.worker = None

    def notify(self, text, error=False):
        owner = self.owner()
        try:
            if owner is not None:
                owner.infoMsg("error" if error else "info", text)
                if error:
                    QtWidgets.QMessageBox.warning(owner, "更新缩略图", text)
        except RuntimeError:
            pass  # The tool was closed while the network write was in progress.

    def begin(self):
        owner = self.owner()
        try:
            self.window = weakref.ref(owner.window())
            window = self.window()
            self.restore_window = window.isVisible()
            if self.restore_window:
                window.hide()
            # Let the desktop repaint after closing the menu/hiding the manager.
            QtCore.QTimer.singleShot(150, self.capture)
        except (AttributeError, RuntimeError):
            self.finish()

    def restore(self):
        try:
            window = self.window() if self.window else None
            if window is not None and self.restore_window:
                window.show()
                window.raise_()
                window.activateWindow()
        except RuntimeError:
            pass
        self.restore_window = False

    def capture(self):
        global _CAPTURING
        error = ""
        accepted = False
        try:
            import unreal
            library = getattr(unreal, "CGToolsPublisherLibrary", None)
            if library is None or not hasattr(library, "capture_screenshot_to_file"):
                raise RuntimeError("截图接口不可用，请安装 CGToolsPublisher 1.7.1 或更新版本并重启 UE。")
            self.temporary = tempfile.TemporaryDirectory(prefix="CGToolsThumbnail_")
            captured = os.path.join(self.temporary.name, "capture.png")
            accepted, error = library.capture_screenshot_to_file(captured)
        except Exception as exc:
            error = str(exc)
        finally:
            _CAPTURING = None
            self.restore()
        if not accepted:
            if error:
                self.notify("截图失败：\n" + error, error=True)
            self.finish()
            return
        self.notify("正在保存缩略图…")
        self.worker = _WriteWorker(captured, self.destination)
        self.worker.signals.finished.connect(self.saved, QtCore.Qt.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(self.worker)

    @QtCore.Slot(object, str)
    def saved(self, image, error):
        try:
            if error:
                self.notify(error, error=True)
            else:
                owner = self.owner()
                if owner is not None:
                    try:
                        refresh_cards(owner, self.destination, image)
                    except RuntimeError:
                        pass
                self.notify("缩略图已更新：" + self.destination)
        finally:
            self.finish()

    def finish(self):
        global _CAPTURING
        if _CAPTURING is self:
            _CAPTURING = None
        self.restore()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        _UPDATES.discard(self)
        self.deleteLater()


def start_update(owner, destination):
    global _CAPTURING
    if _CAPTURING is not None or any(
            _path_key(job.destination) == _path_key(destination) for job in _UPDATES):
        owner.infoMsg("warning", "正在截图或保存该资产的缩略图，请稍候。")
        return
    job = _Update(owner, destination)
    _UPDATES.add(job)
    _CAPTURING = job
    job.begin()


def add_menu_action(menu, owner, item):
    destination = icon_path(item)
    action = menu.addAction("更新缩略图")
    action.setIcon(owner.style().standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView))
    action.setEnabled(bool(destination and os.path.isabs(destination)
                           and os.path.splitext(destination)[1].lower() in _FORMATS))
    action.setToolTip("框选截图，确定后替换该资产的缩略图" if action.isEnabled()
                      else "数据库中的 icon 路径为空、无效或图片格式不支持")
    # QAction fires inside menu.exec(); defer to avoid capturing the open menu.
    action.triggered.connect(lambda _checked=False: QtCore.QTimer.singleShot(
        0, lambda: start_update(owner, destination)))
    return action
