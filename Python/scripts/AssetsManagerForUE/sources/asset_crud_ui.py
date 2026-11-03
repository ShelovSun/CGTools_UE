"""Nonmodal Add Asset dialog and Maya-style deletion for asset/scene cards."""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import asset_crud_service as service


class _Signals(QtCore.QObject):
    finished = QtCore.Signal(int, object, str)


class _Task(QtCore.QRunnable):
    def __init__(self, key, function, args):
        super().__init__()
        self.key, self.function, self.args = key, function, args
        self.signals = _Signals()

    def run(self):
        result, error = None, ""
        try:
            result = self.function(*self.args)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        finally:
            self.args = ()
        self.signals.finished.emit(self.key, result, error)


# No page-owned QThreadPool: closing a page must not wait for network I/O.
_POOL = QtCore.QThreadPool()
_POOL.setMaxThreadCount(2)


class AddAssetDialog(QtWidgets.QDialog):
    typesRequested = QtCore.Signal(str)
    submitted = QtCore.Signal(object)

    def __init__(self, page, table):
        super().__init__(page)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle("添加场景（Add Scene）" if table == "scene" else "添加资产（Add Asset）")
        self.setFont(QtGui.QFont("Microsoft YaHei UI", 10))
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setMinimumWidth(360)
        self.busy = False
        self.projects = QtWidgets.QComboBox()
        self.types = QtWidgets.QComboBox()
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("资产名 / name")
        self.zh_name = QtWidgets.QLineEdit()
        self.zh_name.setPlaceholderText("中文名（可留空）")
        self.message = QtWidgets.QLabel("正在读取项目和类型…")
        self.message.setWordWrap(True)
        self.message.setTextFormat(QtCore.Qt.PlainText)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("确定")
        self.buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("项目", self.projects)
        layout.addRow("类型", self.types)
        layout.addRow("资产名", self.name)
        layout.addRow("中文名", self.zh_name)
        layout.addRow(self.message)
        layout.addRow(self.buttons)
        self.projects.setEnabled(False)
        self.types.setEnabled(False)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.projects.currentTextChanged.connect(self._projectChanged)
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)
        self.name.setFocus()

    def _projectChanged(self, project):
        self.types.clear()
        self.types.setEnabled(False)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.message.setText("正在读取类型…")
        self.typesRequested.emit(project)

    def setOptions(self, options, preferred_type=""):
        self.projects.blockSignals(True)
        self.projects.clear()
        self.projects.addItems(options["projects"])
        self.projects.setCurrentText(options["project"])
        self.projects.blockSignals(False)
        self.projects.setEnabled(True)
        self.types.clear()
        self.types.addItems(options["types"])
        if preferred_type in options["types"]:
            self.types.setCurrentText(preferred_type)
        self.types.setEnabled(bool(options["types"]))
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(options["types"]))
        self.message.setText("" if options["types"] else "当前项目没有可添加的类型目录")

    def setBusy(self, busy):
        self.busy = busy
        for widget in (self.projects, self.types, self.name, self.zh_name, self.buttons):
            widget.setEnabled(not busy)
        if busy:
            self.message.setText("正在添加记录并创建目录…")

    def _submit(self):
        try:
            service._segment(self.name.text().strip(), "资产名")
        except ValueError as exc:
            self.message.setText(str(exc))
            self.name.setFocus()
            return
        self.submitted.emit({"project": self.projects.currentText(), "type": self.types.currentText(),
                             "name": self.name.text().strip(), "zh_name": self.zh_name.text().strip()})

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)


class RecordController(QtCore.QObject):
    changed = QtCore.Signal(object)

    def __init__(self, page, table, context_getter):
        super().__init__(page)
        self.page, self.table, self.context_getter = page, table, context_getter
        self.dialog = None
        self.busy = self.closed = False
        self._serial = 0
        self._options_key = 0
        self._jobs = {}
        page.add_bttn.setEnabled(page.isSQL)
        page.add_bttn.clicked.connect(self.openAdd)

    def _start(self, kind, function, args, extra=None):
        self._serial += 1
        task = _Task(self._serial, function, args)
        self._jobs[task.key] = (kind, task, extra)
        task.signals.finished.connect(self._completed)
        _POOL.start(task)
        return task.key

    def _setBusy(self, busy):
        self.busy = busy
        self.page.add_bttn.setEnabled(self.page.isSQL and not busy and not self.closed)

    def openAdd(self):
        if self.closed or self.busy or not self.page.isSQL:
            return
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        project, record_type = self.context_getter()
        dialog = AddAssetDialog(self.page, self.table)
        self.dialog = dialog
        dialog.typesRequested.connect(self._requestTypes)
        dialog.submitted.connect(self._submitAdd)
        dialog.finished.connect(self._dialogFinished)
        dialog.show()
        self._requestTypes(project, record_type)

    def _dialogFinished(self, _result):
        self.dialog = None
        self._options_key = 0

    def _requestTypes(self, project, preferred_type=""):
        self._options_key = self._start("options", service.read_add_options,
                                        (self.table, project), preferred_type)

    def _submitAdd(self, values):
        if self.closed or self.busy or self.dialog is None:
            return
        self._setBusy(True)
        self.dialog.setBusy(True)
        self._start("add", service.add_record,
                    (self.page.user, self.page.password, self.table, values["project"],
                     values["type"], values["name"], values["zh_name"]))

    def _canDelete(self):
        editor = self.page._status_editor
        return (self.page.isSQL and not self.closed and not self.busy and self.dialog is None
                and not editor.loading and editor.pending is None
                and editor.context == self.context_getter()
                and getattr(self.page, "_copy_thread", None) is None
                and not self.page._load_check.isRunning())

    def addDeleteAction(self, menu, item):
        action = menu.addAction(QtGui.QIcon(os.path.join(self.page.scriptsPath, "icon", "delete.png")),
                                "删除...")
        action.setEnabled(self._canDelete())
        # Snapshot data while the card is alive; async jobs never retain a Qt item.
        row = tuple(item.itemData())
        context = self.context_getter()
        action.triggered.connect(lambda _checked=False: self.delete(row, context))
        return action

    def delete(self, row, context):
        if not self._canDelete() or context != self.context_getter():
            return
        project, record_type = context
        answer = QtWidgets.QMessageBox.warning(
            self.page, "删除资产" if self.table == "asset" else "删除场景",
            "确定删除数据库记录吗？此操作不可撤销。\n\n项目：{0}\n类型：{1}\n资产：{2}".format(
                project, record_type, row[1]),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes or self.closed:
            return
        self._setBusy(True)
        self.page.infoMsg("info", "正在删除数据库记录…")
        self._start("delete", service.delete_record,
                    (self.page.user, self.page.password, self.table, project, record_type, row))

    @QtCore.Slot(int, object, str)
    def _completed(self, key, result, error):
        job = self._jobs.pop(key, None)
        if self.closed or job is None:
            return
        kind, _task, extra = job
        if kind == "options":
            if key != self._options_key or self.dialog is None:
                return
            if error:
                self.dialog.message.setText("读取项目/类型失败：" + error)
            else:
                self.dialog.setOptions(result, extra)
            return
        if error:
            self._setBusy(False)
            if kind == "add" and self.dialog is not None:
                self.dialog.setBusy(False)
                self.dialog.message.setText("添加失败：" + error)
            else:
                message = ("数据表已删除，但服务器资产文件夹删除失败：\n{0}\n\n{1}".format(
                    extra["folder"], error) if kind == "folder" else "删除数据库记录失败：\n" + error)
                QtWidgets.QMessageBox.warning(self.page, "操作失败", message)
                self.page.infoMsg("error", message)
            return
        if kind == "add":
            if self.dialog is not None:
                self.dialog.setBusy(False)
                self.dialog.accept()
            self.changed.emit(result)
            self._setBusy(False)
            self.page.infoMsg("info", "已添加：{0} / {1} / {2}".format(
                result["project"], result["type"], result["row"][1]))
        elif kind == "delete":
            self.changed.emit(result)
            if result["folder_error"]:
                self._setBusy(False)
                QtWidgets.QMessageBox.warning(self.page, "文件未删除",
                    "数据表已删除，但无法安全操作服务器资产文件夹，文件未删除。\n" + result["folder_error"])
            elif result["folder_exists"]:
                answer = QtWidgets.QMessageBox.warning(
                    self.page, "删除服务器资产文件夹",
                    "数据表已删除。是否同时永久删除服务器上的这个资产文件夹及全部内容？\n\n" + result["folder"],
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
                if answer == QtWidgets.QMessageBox.Yes and not self.closed:
                    self.page.infoMsg("info", "正在删除服务器资产文件夹…")
                    self._start("folder", service.delete_folder, (self.table, result), result)
                else:
                    self._setBusy(False)
                    self.page.infoMsg("info", "数据表已删除，服务器资产文件夹保留")
            else:
                self._setBusy(False)
                self.page.infoMsg("info", "数据表已删除，服务器上未找到这个资产文件夹")
        elif kind == "folder":
            self._setBusy(False)
            self.page.infoMsg("info", "数据表和服务器资产文件夹已删除：" + result["folder"])

    def shutdown(self):
        self.closed = True
        if self.dialog is not None:
            self.dialog.setBusy(False)
            self.dialog.reject()
        self._jobs.clear()


def apply_to_rows(rows, result):
    """Update the current type's in-memory rows, retaining search/sort settings."""
    updated = [row for row in (rows or []) if str(row[1]) != str(result["row"][1])]
    if result["operation"] == "add":
        updated.append(result["row"])
    return updated
