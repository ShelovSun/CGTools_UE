"""One library tree/list, with separate asset and scene details and operations."""
import json,os
from PySide6 import QtCore,QtGui,QtWidgets
from ..config import commonSetting
from ..utils import myWidget
from . import assetTools,sceneTools,library_service as service,asset_fbx_service
from .library_editing import LibraryStatusEditor

class _LibraryTask(QtCore.QRunnable):
    def __init__(self,generation,user,password,is_sql,project,scope,settings=None,discover=False,project_index=0):
        super().__init__()
        self.signals=assetTools._QuerySignals()
        self.generation,self.user,self.password,self.is_sql=generation,user,password,is_sql
        self.project,self.scope,self.settings,self.discover,self.project_index=project,scope,settings,discover,project_index

    def run(self):
        try:
            settings=self.settings or commonSetting(force_reload=True)
            projects=list(settings.get('DataBase') or [])
            project=self.project if self.project in projects else (projects[min(max(self.project_index,0),len(projects)-1)] if projects else '')
            types=service.discover_types(settings,project) if self.discover and project else None
            scope=self.scope
            if scope is None:
                names=(types or {}).get('asset',[])
                scope=('asset','Characters' if 'Characters' in names else (names[0] if names else None))
            if types is not None and scope[1] is not None and scope[1] not in types.get(scope[0],[]):
                scope=(scope[0],None)
            rows=service.query_rows(self.user,self.password,project,scope,settings) if self.is_sql and project else []
            self.signals.loaded.emit(self.generation,dict(settings=settings,project=project,types=types,scope=scope,rows=rows))
        except Exception as exc:
            self.signals.failed.emit(self.generation,str(exc))

class _SceneDetails(sceneTools.SceneToolsUI):
    def __init__(self,owner):
        self.library=owner
        super().__init__(owner.isSQL,user=owner.user,password=owner.password,defer_initial_load=True)
        self.setParent(owner,QtCore.Qt.Widget)
        self.hide()
        self.main_listWgt=owner.main_listWgt

    def rememberSettings(self): pass
    def infoMsg(self,icon,text): self.library.infoMsg(icon,text)
    def _updateLoadButton(self): self.library._updateLoadButton()
    def _recordChanged(self,result): self.library._recordChanged(result,'scene')
    def scanUEAssetStates(self): self.library.scanUEAssetStates()
    def _canLoadUEAsset(self,item): return self.library._canLoadUEAsset(item)
    def loadUEAsset(self,item=None): return self.library.loadUEAsset(item)
    def _registerLoadedPlan(self,item,plan):
        self.library._state_cache.pop(self.library._sourceCacheKey(plan.get('asset_root')),None)
        super()._registerLoadedPlan(item,plan)

class LibraryToolsUI(assetTools.AssetToolsUI):
    def __init__(self,isSQL=True,user='',password='',initial_scope=None):
        self._library_settings={}
        self._library_types={}
        self._scene_details=None
        self._initial_scope=initial_scope
        self._scope=('asset',None)
        super().__init__(isSQL,user=user,password=password)
        old=self._status_editor
        self.main_listWgt.statusChangeRequested.disconnect(old.request)
        self.main_listWgt.detailEditRequested.disconnect(old.openDetail)
        self.main_listWgt.cellEditorsInvalidated.disconnect(old._closeDetail)
        old.shutdown()
        old.deleteLater()
        self._status_editor=LibraryStatusEditor(self)
        self._status_editor.saved.connect(self._statusSaved)
        self.add_bttn.clicked.disconnect(self._record_controller.openAdd)
        self.add_bttn.clicked.connect(self._openAdd)

    def build_ui(self):
        super().build_ui()
        self.type_listWgt.hide()  # Retained solely for old helper compatibility.
        self.type_treeWidget=QtWidgets.QTreeWidget()
        self.type_treeWidget.setObjectName('LibraryDirectoryTree')
        self.type_treeWidget.setHeaderHidden(True)
        self.type_treeWidget.setMinimumWidth(150)
        # Keep Qt's native branch arrows; avoid nested indentation wasting the sidebar.
        self.type_treeWidget.setIndentation(12)
        self.type_treeWidget.setIconSize(QtCore.QSize(12,12))
        self.type_treeWidget.setUniformRowHeights(True)
        self.type_treeWidget.setAnimated(False)
        self.type_treeWidget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.mainWindow_splitter.widget(0).layout().addWidget(self.type_treeWidget,1)
        self.type_treeWidget.itemSelectionChanged.connect(self._treeChanged)
        self._asset_details=self.mainWindow_splitter.widget(2)
        self._details_stack=QtWidgets.QStackedWidget()
        self.mainWindow_splitter.replaceWidget(2,self._details_stack)
        self._details_stack.addWidget(self._asset_details)
        self.mainWindow_splitter.setSizes([185,520,330])

    def _startInitialLoad(self):
        thumb,project_index,_typ=self.readSettings()
        if thumb is not None: self.itemSize_Slider.setValue(int(thumb))
        settings=QtCore.QSettings('AssetsUE','UnifiedAssetsSettings')
        project=str(settings.value('project',''))
        try: scope=tuple(json.loads(settings.value('scope','null'))) if settings.contains('scope') else None
        except (TypeError,ValueError): scope=None
        if not scope or len(scope)!=2 or scope[0] not in ('all','asset','scene'): scope=None
        scope=self._initial_scope or scope
        self._requestLibrary(project,scope,discover=True,project_index=int(project_index or 0))

    def rememberSettings(self):
        super().rememberSettings()
        settings=QtCore.QSettings('AssetsUE','UnifiedAssetsSettings')
        settings.setValue('project',self.project_comb.currentText())
        settings.setValue('scope',json.dumps(self._scope))

    def _requestLibrary(self,project,scope,discover=False,project_index=0):
        if self._state_closed: return
        self._query_generation+=1
        self.listWidgetAddItems([])
        self._status_editor.setLoading()
        self.infoMsg('info',u'正在后台读取目录和资产…' if discover else u'正在后台读取资产…')
        task=_LibraryTask(self._query_generation,self.user,self.password,self.isSQL,project,scope,
            None if discover else self._library_settings,discover,project_index)
        task.signals.loaded.connect(self._libraryLoaded)
        task.signals.failed.connect(self._assetDataFailed)
        self._query_tasks[self._query_generation]=task
        self._data_pool.start(task)

    def _libraryLoaded(self,generation,payload):
        self._query_tasks.pop(generation,None)
        if self._state_closed or generation!=self._query_generation: return
        self._library_settings=payload['settings']
        self.project_comb.blockSignals(True)
        self.project_comb.clear()
        self.project_comb.addItems(list(self._library_settings.get('DataBase') or []))
        self.project_comb.setCurrentText(payload['project'])
        self.project_comb.blockSignals(False)
        self._scope=tuple(payload['scope'])
        if payload['types'] is not None:
            self._library_types=payload['types']
            self._buildTree()
        self._configureColumns()
        self.listWidgetAddItems(payload['rows'])

    def _buildTree(self):
        tree=self.type_treeWidget
        tree.blockSignals(True)
        tree.clear()
        icon=QtGui.QIcon(os.path.join(self.scriptsPath,'icon','folder_white.png'))
        root=QtWidgets.QTreeWidgetItem(tree,[u'全部目录'])
        root.setData(0,QtCore.Qt.UserRole,('all',None))
        root.setIcon(0,icon)
        selected=root if self._scope==('all',None) else None
        for table,label in service.TABLE_FOLDERS.items():
            group=QtWidgets.QTreeWidgetItem(root,[label])
            group.setIcon(0,icon)
            group.setData(0,QtCore.Qt.UserRole,(table,None))
            if self._scope==(table,None): selected=group
            for name in self._library_types.get(table,[]):
                item=QtWidgets.QTreeWidgetItem(group,[name])
                item.setIcon(0,icon)
                item.setData(0,QtCore.Qt.UserRole,(table,name))
                if self._scope==(table,name): selected=item
            group.setExpanded(True)
        root.setExpanded(True)
        tree.setCurrentItem(selected or root)
        tree.blockSignals(False)

    def _treeChanged(self):
        item=self.type_treeWidget.currentItem()
        if item is None: return
        self._scope=tuple(item.data(0,QtCore.Qt.UserRole))
        self._current_sort=(0,True)
        self._configureColumns()
        self.rememberSettings()
        self._requestAssetData()

    def _configureColumns(self):
        if self._scope[0]=='scene':
            headers=(u'创建日期',u'场景名',u'中文名',u'制作人',u'状态',u'UE状态',u'UE制作',u'备注')
            indices=(0,1,2,3,4,9,10,8)
            widths=(86,180,110,95,85,85,95,180)
        else:
            headers=myWidget.MainQListWiget.LIST_HEADERS
            if self._scope[0]=='all':
                headers=(u'创建日期',u'资产名',u'中文名',u'制作人',u'状态',u'绑定制作',u'绑定状态',u'UE状态',u'UE制作',u'备注')
            indices=myWidget.MainQListWiget.LIST_FIELD_INDICES
            widths=myWidget.MainQListWiget.LIST_COLUMN_WIDTHS
        if tuple(self.main_listWgt.listHeaders())!=tuple(headers):
            self.main_listWgt.setListColumns(headers,indices,widths,
                tuple('note' if index==8 else None for index in indices),
                tuple('left' if index in (1,2,8) else 'center' for index in indices))
        self.asset_list_header.updateGeometry()
        self.asset_list_header.update()
        self.add_bttn.setToolTip(u'添加场景（Add Scene）' if self._scope[0]=='scene' else u'添加资产（Add Asset）')

    def _sort_data(self,data):
        column,reverse=self._current_sort
        indices=self.main_listWgt.listFieldIndices()
        index=indices[column] if column<len(indices) else 0
        def key(row):
            value=row[index]
            if index==0:
                try: return int(value)
                except (ValueError,TypeError): return 0
            return str(value or '').casefold()
        data.sort(key=key,reverse=reverse)
        return data

    def sort_asset_ui(self):
        menu=QtWidgets.QMenu(self)
        for column,name in enumerate(self.main_listWgt.listHeaders()):
            action=menu.addAction(u'按{0}排序'.format(name))
            action.triggered.connect(lambda _checked=False,col=column:self._do_sort(col))
        menu.exec_(self.sort_bttn.mapToGlobal(self.sort_bttn.rect().bottomLeft()))

    def projectChanged(self):
        self.rememberSettings()
        self._invalidateUEStateCache()
        self._requestLibrary(self.project_comb.currentText(),self._scope,discover=True)

    def _requestAssetData(self):
        self._requestLibrary(self.project_comb.currentText(),self._scope)

    def refresh_asset(self):
        self._invalidateUEStateCache()
        self._requestLibrary(self.project_comb.currentText(),self._scope,discover=True)

    def _currentCard(self):
        item=self.main_listWgt.currentItem()
        return item if item is not None and item.isSelected() else None

    def _statusContext(self):
        item=self._currentCard()
        meta=service.metadata(item.itemData()) if item is not None else {}
        return (str(self.project_comb.currentText()),meta.get('type') or self._scope[1] or '')

    def getTypeAndProject(self):
        project,typ=self._statusContext()
        item=self._currentCard()
        table=service.metadata(item.itemData()).get('table','asset') if item else 'asset'
        return typ,project,os.path.join(str(self._library_settings.get('rootPath','')),project,service.TABLE_FOLDERS[table],typ)

    def _itemKey(self,item):
        return ue_root(item).replace('\\','/').casefold()

    def _scene(self,item=None):
        if self._scene_details is None:
            scene=_SceneDetails(self)
            self._scene_details=scene
            right=scene.main_splitter.widget(2)
            self._details_stack.addWidget(right)
        scene=self._scene_details
        meta=service.metadata(item.itemData()) if item is not None else {}
        project=self.project_comb.currentText()
        typ=meta.get('type') or (self._scope[1] if self._scope[0]=='scene' else '') or ''
        scene.proj_comb.blockSignals(True)
        scene.type_listWgt.blockSignals(True)
        scene.proj_comb.clear()
        scene.proj_comb.addItem(project)
        scene.type_listWgt.clear()
        if typ:
            scene.type_listWgt.addItem(typ)
            scene.type_listWgt.setCurrentRow(0)
        scene.proj_comb.blockSignals(False)
        scene.type_listWgt.blockSignals(False)
        scene._status_editor.setContext(project,typ)
        return scene

    def listWidgetItemChanged(self):
        item=self._currentCard()
        if hasattr(self,'_status_editor'):
            self._status_editor._closeDetail()
            self._status_editor.setContext(*self._statusContext())
        if item is None:
            if self.preview_wgt is not None: self.preview_wgt.clear()
            if self.action_wgt is not None: self.action_wgt.clear()
            if self._scene_details is not None:
                if self._scene_details.preview_wgt is not None: self._scene_details.preview_wgt.clear()
                self._scene_details.scene_int_listWgt.clear()
            return
        row=item.itemData()
        if service.metadata(row).get('table')=='scene':
            if self.preview_wgt is not None: self.preview_wgt.clear()
            if self.action_wgt is not None: self.action_wgt.clear()
            scene=self._scene(item)
            self._details_stack.setCurrentIndex(1)
            if scene._ensureScenePreviewWidget():
                scene.preview_wgt.clear()
                scene.preview_wgt.setTitle(row[1],str(row[2] or ''))
                scene.preview_wgt.setPreviewPixmap(row[7])
            scene.update_asset_int(os.path.join(ue_root(item),'Mod'))
        else:
            self._details_stack.setCurrentIndex(0)
            if self._scene_details is not None and self._scene_details.preview_wgt is not None:
                self._scene_details.preview_wgt.clear()
            if self._ensurePreviewWidgets():
                self.preview_wgt.clear()
                self.preview_wgt.setTitle(row[1],row[2])
                self.preview_wgt.setPreviewPixmap(row[7])
                self.action_wgt.setAsset(self.preview_wgt.deriveFbxPath(row[7]))

    def show_menu(self,point):
        item=self.main_listWgt.itemAt(point)
        if item is None: return
        self.main_listWgt.setCurrentItem(item)
        if service.metadata(item.itemData()).get('table')=='scene':
            self._scene(item).show_item_menu(item)
        else: self.show_item_menu(item)

    def _libraryBusy(self):
        scene=self._scene_details
        return bool(scene is not None and (scene._copy_thread is not None or scene._load_check.isRunning()))

    def _canLoadUEAsset(self,item):
        return not self._libraryBusy() and super()._canLoadUEAsset(item)

    def loadUEAsset(self,item=None):
        item=item if item is not None and not isinstance(item,bool) else self._currentCard()
        if item is None: return
        if self._libraryBusy() or self._copy_thread is not None or self._load_check.isRunning() or self._action_batch.active:
            self.infoMsg('warning',u'已有资产正在处理，请等待完成')
            return
        if service.metadata(item.itemData()).get('table')=='scene':
            sceneTools.SceneToolsUI.loadUEAsset(self._scene(item),item)
            key=self._sourceCacheKey(ue_root(item))
            self._state_pending.discard(key)
            self._state_requests.pop(key,None)
            self._prioritizeStateScans()
        else: super().loadUEAsset(item)

    def _startActionBatch(self,operation,paths):
        if self._libraryBusy():
            self.infoMsg('warning',u'已有场景正在加载，请等待完成')
            return
        super()._startActionBatch(operation,paths)

    def importFile(self):
        for item in self.main_listWgt.selectedItems():
            meta=service.metadata(item.itemData())
            if meta.get('table')=='asset':
                asset_fbx_service.import_asset(ue_root(item),meta['type'],str(item.itemData()[1]))

    def _openAdd(self):
        controllers=[self._record_controller]
        if self._scene_details is not None: controllers.append(self._scene_details._record_controller)
        for controller in controllers:
            if controller.dialog is not None:
                controller.dialog.raise_()
                controller.dialog.activateWindow()
                return
            if controller.busy: return
        table=self._scope[0]
        if table=='all':
            choice,ok=QtWidgets.QInputDialog.getItem(self,u'添加资产',u'目录：',['Assets','Scenes'],0,False)
            if not ok: return
            table='scene' if choice=='Scenes' else 'asset'
        controller=self._scene()._record_controller if table=='scene' else self._record_controller
        controller.openAdd()

    def _recordChanged(self,result,table=None):
        table=table or getattr(self.sender(),'table','asset')
        self._query_generation+=1
        rows=[r for r in self.main_listWgt.items() if service.identity(r)!=(result['project'],table,result['type'],str(result['row'][1]))]
        if (result['operation']=='add' and result['project']==self.project_comb.currentText()
                and service.accepts(self._scope,table,result['type'])):
            rows.append(service.tag_row(result['row'],result['project'],table,result['type'],self._library_settings['rootPath']))
        self._invalidateUEStateCache()
        self.listWidgetAddItems(rows)

    def _statusSaved(self,request):
        if request['field']==9: self.scanUEAssetStates()
        if request['field']==2:
            item=self._currentCard()
            if item is not None and service.identity(item.itemData())==request['identity']:
                preview=self._scene_details.preview_wgt if request['table']=='scene' and self._scene_details else self.preview_wgt
                if preview is not None: preview.setTitle(request['name'],request['value'])
        if self._query_generation in self._query_tasks: self._requestAssetData()

    def shutdownThreads(self):
        super().shutdownThreads()
        if self._scene_details is not None: self._scene_details.shutdownThreads()

def ue_root(item):
    from .ue_asset_service import asset_root_from_item_data
    return asset_root_from_item_data(item.itemData())
