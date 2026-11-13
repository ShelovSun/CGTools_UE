"""Mixed source identity, SQL filtering, UI dispatch and late background results."""
import ast,os,sqlite3,sys,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest import mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try: import unreal
except ImportError:
    unreal=types.ModuleType('unreal')
    unreal.log_warning=lambda value:None
    sys.modules['unreal']=unreal
from PySide6 import QtCore,QtGui,QtWidgets
from AssetsManagerForUE.sources import libraryTools,library_service as data,status_edit_service
from AssetsManagerForUE.sources import assetTools,sceneTools
from test_status_editing import LocalConnection

class OfflineLibrary(libraryTools.LibraryToolsUI):
    def _startInitialLoad(self): pass
    def rememberSettings(self): pass
    def scanUEAssetStates(self): pass
    def _ensurePreviewWidgets(self): return False

class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='unified_library_')
        self.root=Path(self.temp.name)
        self.settings=dict(DataBase=['GOF','ALT'],rootPath=str(self.root),type=['Characters','Props'])
        self.types=dict(asset=['Characters','Props'],scene=['Map','Rock','StaticMesh'])
        self.preview=mock.patch.object(libraryTools._SceneDetails,'_ensureScenePreviewWidget',return_value=False)
        self.preview.start()
        self.ui=OfflineLibrary(isSQL=False)
        self.ui.resize(1200,700)
        self.ui.show()
        self.app.processEvents()
        self.rows=[self.row('asset','Characters',3),self.row('asset','Props',2),self.row('scene','Rock',1)]
        self.apply(self.rows)

    def tearDown(self):
        self.ui.shutdownThreads()
        self.ui.close()
        self.ui.deleteLater()
        assetTools._DATA_THREAD_POOL.waitForDone(4000)
        status_edit_service._WRITE_POOL.waitForDone(4000)
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.preview.stop()
        self.temp.cleanup()

    def row(self,table,typ,date=1,name='Shared',project='GOF',icon=True):
        path=str(self.root/project/data.TABLE_FOLDERS[table]/typ/name/'Icon'/(name+'.png')) if icon else ''
        raw=(date,name,'中文名','制作人','未开始','绑定人','未开始',path,'备注','未开始','UE人')
        return data.tag_row(raw,project,table,typ,self.root)

    def apply(self,rows,project='GOF',scope=('all',None)):
        self.ui._libraryLoaded(self.ui._query_generation,dict(settings=self.settings,project=project,
            types=self.types,scope=scope,rows=rows))
        self.app.processEvents()

    def wait(self,predicate):
        end=time.monotonic()+4
        while not predicate() and time.monotonic()<end:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def item(self,table,typ):
        return next(self.ui.main_listWgt.item(i) for i in range(self.ui.main_listWgt.count())
            if data.identity(self.ui.main_listWgt.item(i).itemData())[1:3]==(table,typ))

    def test_tree_contains_all_source_groups_types_and_scopes(self):
        root=self.ui.type_treeWidget.topLevelItem(0)
        self.assertEqual(root.text(0),'全部目录')
        self.assertEqual([root.child(i).text(0) for i in range(root.childCount())],['Assets','Scenes'])
        self.assertEqual([root.child(1).child(i).text(0) for i in range(3)],self.types['scene'])
        with mock.patch.object(self.ui,'_requestAssetData') as requested:
            self.ui.type_treeWidget.setCurrentItem(root.child(1).child(0))
        self.assertEqual(self.ui._scope,('scene','Map'))
        self.assertEqual(self.ui.main_listWgt.listHeaders()[1],'场景名')
        self.assertNotIn(6,self.ui.main_listWgt.listFieldIndices())
        requested.assert_called_once()

    def test_same_names_have_distinct_identity_even_without_icons(self):
        rows=[self.row('asset','Props',icon=False),self.row('scene','Rock',icon=False)]
        self.apply(rows)
        keys=[self.ui._itemKey(self.ui.main_listWgt.item(i)) for i in range(2)]
        self.assertNotEqual(*keys)
        for key in keys: self.assertIsNotNone(self.ui._findItemByKey(key))

    def test_selection_uses_separate_scene_details_and_asset_actions(self):
        asset=self.item('asset','Props')
        scene=self.item('scene','Rock')
        self.ui.main_listWgt.setCurrentItem(scene)
        self.assertEqual(self.ui._details_stack.currentIndex(),1)
        adapter=self.ui._scene_details
        self.assertEqual(adapter.getPanelsData()[:2],('GOF','Rock'))
        self.assertTrue(hasattr(adapter,'scene_int_listWgt'))
        self.assertTrue(hasattr(adapter,'exportScene_bttn'))
        self.ui.main_listWgt.setCurrentItem(asset)
        self.assertEqual(self.ui._details_stack.currentIndex(),0)
        self.assertEqual(self.ui._statusContext(),('GOF','Props'))
        self.assertEqual(adapter.scene_int_listWgt.count(),0)

    def test_scene_rig_cells_are_empty_and_cannot_be_edited(self):
        row=self.rows[2]
        self.assertEqual(row[5:7],('',''))
        self.assertFalse(self.ui.main_listWgt.rowFieldEditable(row,5))
        self.assertFalse(self.ui.main_listWgt.rowFieldEditable(row,6))
        self.assertTrue(self.ui.main_listWgt.rowFieldEditable(row,9))
        self.assertTrue(self.ui.main_listWgt.rowFieldEditable(self.rows[0],6))

    def test_mixed_and_scene_table_paint_checks_each_rows_editable_fields(self):
        widget=self.ui.main_listWgt
        for scope in (('all',None),('scene',None)):
            self.ui._scope=scope
            self.ui._configureColumns()
            widget.setIsList(True)
            widget.setMode()
            observed=[]
            def allowed(row,field):
                observed.append((data.identity(row),field))
                return self.ui._status_editor.field_allowed(row,field)
            with mock.patch.object(widget,'rowFieldEditable',side_effect=allowed):
                canvas=QtGui.QImage(1400,240,QtGui.QImage.Format_ARGB32)
                canvas.fill(QtCore.Qt.transparent)
                painter=QtGui.QPainter(canvas)
                try:
                    for i in range(widget.count()):
                        item=widget.item(i)
                        option=QtWidgets.QStyleOptionViewItem()
                        option.rect=QtCore.QRect(0,i*60,1400,60)
                        item.paintText(painter,option,widget.indexFromItem(item))
                finally:
                    painter.end()
            self.assertEqual({entry[0] for entry in observed},{data.identity(r) for r in self.rows})
            self.assertTrue(any(field==9 for _,field in observed))

    def test_map_fbx_import_is_blocked_for_both_server_spellings(self):
        for typ in ('Map','map'):
            row=self.row('scene',typ)
            self.apply([row])
            item=self.ui.main_listWgt.item(0)
            self.ui.main_listWgt.setCurrentItem(item)
            adapter=self.ui._scene(item)
            with mock.patch.object(sceneTools.os.path,'isdir',side_effect=AssertionError('Map FBX directory read')), \
                 mock.patch.object(adapter,'infoMsg') as message:
                adapter.importFBX(item)
            self.assertIn('Map 不能通过 FBX 导入',message.call_args.args[1])

    def test_menu_routes_import_and_delete_controller_by_card_not_tree(self):
        asset=self.item('asset','Props')
        scene=self.item('scene','Rock')
        menus=[]
        def capture(menu,*args): menus.append(menu); return None
        with mock.patch.object(QtWidgets.QMenu,'exec_',capture), \
             mock.patch.object(self.ui,'importFile') as asset_import:
            self.ui.main_listWgt.setCurrentItem(asset)
            self.ui.show_menu(self.ui.main_listWgt.visualItemRect(asset).center())
            next(a for a in menus[-1].actions() if a.text()=='导入 FBX').trigger()
            asset_import.assert_called_once()
            adapter=self.ui._scene(scene)
            with mock.patch.object(adapter,'importFBX') as scene_import:
                self.ui.show_menu(self.ui.main_listWgt.visualItemRect(scene).center())
                next(a for a in menus[-1].actions() if a.text()=='导入 FBX').trigger()
                scene_import.assert_called_once_with(scene)
                self.assertEqual(adapter._record_controller.table,'scene')
                self.assertEqual(adapter._record_controller.context_getter(),('GOF','Rock'))

    def test_load_dispatch_uses_correct_controller_and_prevents_cross_source_overlap(self):
        asset=self.item('asset','Props')
        scene=self.item('scene','Rock')
        with mock.patch.object(assetTools.AssetToolsUI,'loadUEAsset') as assets, \
             mock.patch.object(sceneTools.SceneToolsUI,'loadUEAsset') as scenes:
            self.ui.loadUEAsset(asset)
            self.ui.loadUEAsset(scene)
        assets.assert_called_once_with(asset)
        self.assertIs(scenes.call_args.args[0],self.ui._scene_details)
        self.assertIs(scenes.call_args.args[1],scene)
        with mock.patch.object(self.ui._scene_details._load_check,'isRunning',return_value=True), \
             mock.patch.object(assetTools.AssetToolsUI,'loadUEAsset') as assets:
            self.ui.loadUEAsset(asset)
        assets.assert_not_called()

    def test_crud_result_preserves_other_table_and_type_with_same_name(self):
        self.ui._recordChanged(dict(project='GOF',type='Rock',row=self.rows[2],operation='delete'),'scene')
        self.assertEqual(len(self.ui.main_listWgt.items()),2)
        self.assertEqual({data.identity(r)[1:3] for r in self.ui.main_listWgt.items()},
                         {('asset','Characters'),('asset','Props')})
        raw=self.row('scene','Rock')[:11]
        self.ui._recordChanged(dict(project='GOF',type='Rock',row=raw,operation='add'),'scene')
        self.assertEqual(len(self.ui.main_listWgt.items()),3)

    def test_edit_freezes_scene_sql_identity_and_changes_only_that_mixed_row(self):
        self.ui.isSQL=True
        self.ui._status_editor.setContext('GOF','')
        entered,release=threading.Event(),threading.Event()
        args=[]
        def write(*values): args.append(values); entered.set(); release.wait(3)
        with mock.patch.object(status_edit_service,'update_status',side_effect=write):
            self.ui._status_editor.request(self.rows[2],9,'已完成')
            self.wait(entered.is_set)
            self.ui.main_listWgt.setCurrentItem(self.item('asset','Characters'))
            release.set()
            self.wait(lambda:self.ui._status_editor.pending is None)
        self.assertEqual(args[0][2:6],('GOF','scene','Rock','Shared'))
        states={data.identity(r)[1:3]:r[9] for r in self.ui.main_listWgt.items()}
        self.assertEqual(states,{('asset','Characters'):'未开始',('asset','Props'):'未开始',('scene','Rock'):'已完成'})

    def test_late_write_does_not_update_same_name_in_another_project(self):
        self.ui.isSQL=True
        self.ui._status_editor.setContext('GOF','')
        release=threading.Event()
        with mock.patch.object(status_edit_service,'update_detail',side_effect=lambda *args:release.wait(3)):
            self.ui._status_editor.requestDetail(self.rows[2],2,'新中文名')
            other=self.row('scene','Rock',project='ALT')
            self.apply([other],project='ALT')
            release.set()
            self.wait(lambda:self.ui._status_editor.pending is None)
        self.assertEqual(self.ui.main_listWgt.items()[0][2],'中文名')

    def test_background_read_and_late_project_reply_do_not_block_or_replace_new_view(self):
        entered,release=threading.Event(),threading.Event()
        threads=[]
        def query(user,password,project,scope,settings):
            threads.append(threading.get_ident())
            if project=='GOF': entered.set(); release.wait(3)
            return [self.row('asset','Props',project=project)]
        self.ui.isSQL=True
        with mock.patch.object(data,'query_rows',side_effect=query):
            self.ui._requestLibrary('GOF',('asset','Props'))
            self.wait(entered.is_set)
            self.ui._requestLibrary('ALT',('asset','Props'))
            self.wait(lambda:self.ui.project_comb.currentText()=='ALT')
            release.set()
            self.wait(lambda:not self.ui._query_tasks)
        self.assertTrue(all(t!=threading.get_ident() for t in threads))
        self.assertEqual(data.metadata(self.ui.main_listWgt.items()[0])['project'],'ALT')

class LibrarySQLTests(unittest.TestCase):
    def test_main_tab_preferences_migrate_old_indices_once(self):
        path=Path(__file__).resolve().parents[1]/'AssetsManagerForUE.py'
        module=ast.parse(path.read_text(encoding='utf-8'))
        cls=next(node for node in module.body if isinstance(node,ast.ClassDef) and node.name=='AssetsManagerUI')
        method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='readSettings')
        method.decorator_list=[]
        preferences={}
        getter=types.SimpleNamespace(value=lambda key,default=None:preferences.get(key,default))
        namespace=dict(QtCore=types.SimpleNamespace(QSettings=lambda *args:getter))
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),namespace)
        for old,new in ((0,0),(1,0),(2,1),(3,2),(4,3)):
            preferences.update(tab=old,tabLayoutVersion=1)
            self.assertEqual(namespace['readSettings']()[2],new)
        for current in range(4):
            preferences.update(tab=current,tabLayoutVersion=2)
            self.assertEqual(namespace['readSettings']()[2],current)

    def test_all_source_groups_leaf_and_quoted_types_are_parameterized(self):
        with sqlite3.connect(':memory:') as db:
            for table in ('asset','scene'):
                fields=list(dict.fromkeys(data.FIELDS[table]+('type',)))
                db.execute('CREATE TABLE "{0}" ({1})'.format(table,','.join('"{0}.{1}" TEXT'.format(table,f) for f in fields)))
                for typ in ('Props',"Rock' OR 1=1--"):
                    values=[typ if f=='type' else ('Shared' if f=='name' else '未开始') for f in fields]
                    db.execute('INSERT INTO "{0}" VALUES ({1})'.format(table,','.join('?' for _ in fields)),values)
            with mock.patch('psycopg2.connect',side_effect=lambda **kwargs:LocalConnection(db)), \
                 mock.patch.object(data,'databaseHost',return_value='local.test'):
                all_rows=data.query_rows('u','p','GOF',('all',None),dict(rootPath='X:/Library'))
                assets=data.query_rows('u','p','GOF',('asset',None),dict(rootPath='X:/Library'))
                leaf=data.query_rows('u','p','GOF',('scene',"Rock' OR 1=1--"),dict(rootPath='X:/Library'))
        self.assertEqual(len(all_rows),4)
        self.assertEqual(len(assets),2)
        self.assertEqual(len(leaf),1)
        self.assertEqual(data.identity(leaf[0]),('GOF','scene',"Rock' OR 1=1--",'Shared'))

    def test_discovery_reads_both_directory_roots_and_falls_back_only_for_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('Building','Map','NewType'):
                (root/'GOF/Scenes'/name).mkdir(parents=True)
            (root/'GOF/Scenes/not_a_category.txt').write_text('file')
            result=data.discover_types(dict(rootPath=temporary,type=['Characters','Props']),'GOF')
        self.assertEqual(result,dict(asset=['Characters','Props'],scene=['Building','Map','NewType']))

if __name__=='__main__': unittest.main()
