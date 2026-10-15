"""Database-cell editing shared by the asset and scene pages."""

from PySide6 import QtCore, QtWidgets

from ..config import commonSetting, databaseHost
from ..utils.cell_editors import ArtistPicker, NameEditor


BASE_STATUSES = (u"未开始", u"制作中", u"已完成")
MODEL_STATUSES = BASE_STATUSES + ("UE",)
STATUS_FIELDS = {
    "asset": {
        4: ("asset.mod_status", MODEL_STATUSES, (4,)),
        6: ("asset.rig_status", BASE_STATUSES, (6,)),
    },
    "scene": {4: ("scene.status", MODEL_STATUSES, (4, 6))},
}
DETAIL_FIELDS = {
    "asset": {
        2: ("asset.zh_name", u"中文名", (2,), "text"),
        3: ("asset.mod_artist", u"模型制作", (3,), "artist"),
        5: ("asset.rig_artist", u"绑定制作", (5,), "artist"),
    },
    "scene": {
        2: ("scene.zh_name", u"中文名", (2,), "text"),
        3: ("scene.artist", u"制作人", (3, 5), "artist"),
    },
}


def update_status(user, password, project, table, record_type, name,
                  field_index, old_status, new_status):
    """Commit one whitelisted field; roll back missing/changed/ambiguous rows."""
    field = STATUS_FIELDS.get(table, {}).get(field_index)
    if field is None or new_status not in field[1]:
        raise ValueError(u"不支持的状态字段或状态值")
    _update_record(user, password, project, table, record_type, name,
                   field[0], old_status, new_status)


def update_detail(user, password, project, table, record_type, name,
                  field_index, old_value, new_value):
    field = DETAIL_FIELDS.get(table, {}).get(field_index)
    if field is None or not isinstance(new_value, str) or "\x00" in new_value:
        raise ValueError(u"不支持的字段或文本内容")
    _update_record(user, password, project, table, record_type, name,
                   field[0], old_value, new_value)


def _update_record(user, password, project, table, record_type, name,
                   column, old_value, new_value):
    import psycopg2

    if not project or not record_type or not name:
        raise ValueError(u"项目、类型或资产名为空，请刷新后重试")
    # Identifiers come exclusively from field whitelists; values are parameters.
    query = '''UPDATE public."{table}" SET "{column}" = %s
               WHERE "{table}.name" = %s AND "{table}.type" = %s
               AND "{column}" IS NOT DISTINCT FROM %s'''.format(
                   table=table, column=column)
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(
            database=project, user=user, password=password, host=databaseHost(),
            port="5432", connect_timeout=4,
            options="-c statement_timeout=8000 -c lock_timeout=4000")
        cur = conn.cursor()
        cur.execute(query, (new_value, name, record_type, old_value))
        if cur.rowcount != 1:
            raise RuntimeError(
                u"记录不存在、内容已被其他人修改或存在重名记录，请刷新后重试")
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


class _WriteSignals(QtCore.QObject):
    finished = QtCore.Signal(str)


class _WriteTask(QtCore.QRunnable):
    def __init__(self, args, detail=False):
        super().__init__()
        self.signals = _WriteSignals()
        self.args = args
        self.detail = detail

    def run(self):
        error = ""
        try:
            writer = update_detail if self.detail else update_status
            writer(*self.args)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        finally:
            self.args = ()
        self.signals.finished.emit(error)


# Survives page closure; network timeouts do not block the editor window.
_WRITE_POOL = QtCore.QThreadPool()
_WRITE_POOL.setMaxThreadCount(2)


def read_artist_groups():
    """Use the same shared, departmental user list as the Maya AssetManager."""
    groups = commonSetting(force_reload=True).get("user_list")
    if not isinstance(groups, dict) or not groups:
        raise ValueError(u"commonSetting.json 中的 user_list 为空或格式错误")
    result = {}
    for group, names in groups.items():
        if (not isinstance(group, str) or not isinstance(names, list)
                or any(not isinstance(name, str) for name in names)):
            raise ValueError(u"user_list 必须按部门列出人员姓名列表")
        clean = list(dict.fromkeys(name.strip() for name in names if name.strip()))
        if clean:
            result[group] = clean
    if not result:
        raise ValueError(u"user_list 中没有可选择的人员")
    return result


class _ArtistSignals(QtCore.QObject):
    finished = QtCore.Signal(int, object, str)


class _ArtistTask(QtCore.QRunnable):
    def __init__(self, generation):
        super().__init__()
        self.generation = generation
        self.signals = _ArtistSignals()

    def run(self):
        try:
            groups = read_artist_groups()
        except Exception as exc:
            self.signals.finished.emit(self.generation, {}, str(exc))
        else:
            self.signals.finished.emit(self.generation, groups, "")


class StatusEditor(QtCore.QObject):
    saved = QtCore.Signal(object)

    def __init__(self, page, table, context_getter):
        super().__init__(page)
        self.page = page
        self.widget = page.main_listWgt
        self.table = table
        self.context_getter = context_getter
        self.context = None
        self.loading = True
        self.pending = None
        self.closed = False
        self.detail_popup = None
        self._artist_generation = 0
        self._artist_tasks = {}
        self.widget.setStatusColumns({
            index: field[1] for index, field in STATUS_FIELDS[table].items()})
        self.widget.statusChangeRequested.connect(self.request)
        self.widget.setDetailColumns({
            index: field[3] for index, field in DETAIL_FIELDS[table].items()})
        self.widget.detailEditRequested.connect(self.openDetail)
        self.widget.cellEditorsInvalidated.connect(self._closeDetail)
        self._updateEnabled()

    def setLoading(self):
        self.loading = True
        self._updateEnabled()

    def setContext(self, project, record_type):
        self.context = (str(project), str(record_type))
        self.loading = False
        self._updateEnabled()

    def _updateEnabled(self):
        self.widget.setStatusEditingEnabled(
            self.page.isSQL and not self.closed and not self.loading
            and self.pending is None and self.context is not None)

    def _canEdit(self):
        return (not self.closed and not self.loading and self.pending is None
                and self.page.isSQL and self.context == self.context_getter())

    def _closeDetail(self):
        popup = self.detail_popup
        self.detail_popup = None
        self._artist_generation += 1
        if popup is not None:
            popup.cancel()

    def _detailDismissed(self, popup):
        if self.detail_popup is popup:
            self.detail_popup = None

    @QtCore.Slot(object, int, object)
    def openDetail(self, row, field_index, cell):
        field = DETAIL_FIELDS[self.table].get(field_index)
        if not self._canEdit() or field is None or len(row) <= field_index:
            return
        self._closeDetail()
        context = self.context
        popup = (NameEditor(self.widget, row[field_index], cell.width())
                 if field[3] == "text" else ArtistPicker(self.widget, row[field_index]))
        self.detail_popup = popup
        popup.submitted.connect(lambda value: self._submitDetail(
            popup, context, row, field_index, value))
        popup.dismissed.connect(lambda: self._detailDismissed(popup))
        popup.showAt(cell, below=field[3] != "text")
        if field[3] == "artist":
            self._artist_generation += 1
            task = _ArtistTask(self._artist_generation)
            self._artist_tasks[task.generation] = task
            task.signals.finished.connect(self._artistsLoaded)
            _WRITE_POOL.start(task)

    @QtCore.Slot(int, object, str)
    def _artistsLoaded(self, generation, groups, error):
        self._artist_tasks.pop(generation, None)
        if (not self.closed and generation == self._artist_generation
                and isinstance(self.detail_popup, ArtistPicker)):
            self.detail_popup.setGroups(groups, error)

    def _submitDetail(self, popup, context, row, field_index, value):
        if (popup is self.detail_popup and context == self.context
                and self._canEdit()):
            self.requestDetail(row, field_index, value)

    def requestDetail(self, row, field_index, value):
        field = DETAIL_FIELDS[self.table].get(field_index)
        if not self._canEdit() or field is None or len(row) <= field_index:
            return
        if not isinstance(value, str) or "\x00" in value:
            return
        if row[field_index] == value or (row[field_index] is None and value == ""):
            return
        self._startWrite(row, field_index, value, detail=True)

    @QtCore.Slot(object, int, str)
    def request(self, row, field_index, new_status):
        if not self._canEdit():
            return
        field = STATUS_FIELDS[self.table].get(field_index)
        if field is None or new_status not in field[1] or len(row) <= field_index:
            return
        if row[field_index] == new_status:
            return
        self._startWrite(row, field_index, new_status)

    def _startWrite(self, row, field_index, new_value, detail=False):
        project, record_type = self.context
        name = str(row[1])
        task = _WriteTask((
            self.page.user, self.page.password, project, self.table,
            record_type, name, field_index, row[field_index], new_value), detail=detail)
        request = (project, record_type, name, field_index, new_value)
        self.pending = (task, request)
        task.signals.finished.connect(self._finished)
        self._updateEnabled()
        label = DETAIL_FIELDS[self.table][field_index][1] if detail else u"状态"
        self.page.infoMsg("info", u"正在保存 {0} 的{1}…".format(name, label))
        _WRITE_POOL.start(task)

    @QtCore.Slot(str)
    def _finished(self, error):
        if self.closed or self.pending is None:
            return
        _task, request = self.pending
        self.pending = None
        self._updateEnabled()
        project, record_type, name, field_index, new_value = request
        detail = DETAIL_FIELDS[self.table].get(field_index)
        label = detail[1] if detail else u"状态"
        if error:
            text = u"{0} 的{1}保存失败，原值已保留。\n{2}".format(name, label, error)
            self.page.infoMsg("error", text)
            QtWidgets.QMessageBox.warning(self.page, label + u"保存失败", text)
            return
        if self.context == (project, record_type):
            indices = detail[2] if detail else STATUS_FIELDS[self.table][field_index][2]
            self.widget.updateStatusData(name, indices, new_value)
        self.page.infoMsg("info", u"{0} 的{1}已保存为 {2}".format(name, label, new_value))
        self.saved.emit(request)

    def shutdown(self):
        self.closed = True
        self._updateEnabled()
