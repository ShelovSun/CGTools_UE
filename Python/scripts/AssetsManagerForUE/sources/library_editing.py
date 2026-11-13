"""Freeze each mixed row's table/type identity before any asynchronous write."""
from PySide6 import QtCore,QtWidgets
from . import status_edit_service as service
from .library_service import metadata,identity

class LibraryStatusEditor(service.StatusEditor):
    def __init__(self,page):
        super().__init__(page,'asset',page._statusContext)
        self.widget.rowFieldEditable=self.field_allowed

    @staticmethod
    def field_allowed(row,field):
        table=metadata(row).get('table')
        return field in service.STATUS_FIELDS.get(table,{}) or field in service.DETAIL_FIELDS.get(table,{})

    def _canEdit(self):
        return not self.closed and not self.loading and self.pending is None and self.page.isSQL

    def _select(self,row):
        meta=metadata(row)
        if (not self._canEdit() or meta.get('project')!=self.page.project_comb.currentText()
                or not any(identity(r)==identity(row) for r in self.widget.items())):
            return False
        self.table=meta['table']
        self.context=(meta['project'],meta['type'])
        return True

    def openDetail(self,row,field,cell):
        if self._select(row): super().openDetail(row,field,cell)

    def requestDetail(self,row,field,value):
        if self._select(row): super().requestDetail(row,field,value)

    def request(self,row,field,value):
        if self._select(row): super().request(row,field,value)

    def _startWrite(self,row,field,new_value,detail=False):
        meta=metadata(row)
        task=service._WriteTask((self.page.user,self.page.password,meta['project'],meta['table'],
            meta['type'],str(row[1]),field,row[field],new_value),detail=detail)
        request=dict(meta,name=str(row[1]),field=field,value=new_value,detail=detail,identity=identity(row))
        self.pending=(task,request)
        task.signals.finished.connect(self._finished)
        self._updateEnabled()
        self.page.infoMsg('info',u'正在保存 {0}…'.format(row[1]))
        service._WRITE_POOL.start(task)

    @QtCore.Slot(str)
    def _finished(self,error):
        if self.closed or self.pending is None: return
        _task,request=self.pending
        self.pending=None
        self._updateEnabled()
        table,field=request['table'],request['field']
        if error:
            QtWidgets.QMessageBox.warning(self.page,u'保存失败',u'{0}\n{1}'.format(request['name'],error))
            return
        fields=service.DETAIL_FIELDS if request['detail'] else service.STATUS_FIELDS
        indices=fields[table][field][2]
        if table=='scene': indices=(field,)
        self.widget.updateStatusData(request['name'],indices,request['value'],
            predicate=lambda row: identity(row)==request['identity'])
        self.page.infoMsg('info',u'{0} 已保存'.format(request['name']))
        self.saved.emit(request)
