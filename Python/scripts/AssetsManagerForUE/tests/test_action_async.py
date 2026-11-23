"""Large/slow action folders must never block asset selection or win stale races."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtWidgets
from AssetsManagerForUE.utils.fbxpreview import am_actionWidget as module
from test_action_library import wait_for_actions


class AsyncActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.widget = module.AssetActionWidget()
        self.addCleanup(self.widget.close)

    def wait(self,predicate):
        deadline = time.monotonic()+5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    @staticmethod
    def rig(name):
        return '/local/GOF/Assets/Characters/{0}/FBX/{0}.fbx'.format(name)

    @staticmethod
    def payload(directory,count=1):
        return dict(exists=True,error='',files=[('%04d.fbx'%i,directory+'/%04d.fbx'%i,1700000000+i,i+1)
                                               for i in range(count)])

    def test_slow_scan_allows_gui_heartbeat_and_later_selection_wins(self):
        started, release = threading.Event(), threading.Event()
        heartbeats, threads = [], []
        def scan(directory,cancelled):
            threads.append(threading.get_ident())
            if '/A/Action' in directory:
                started.set()
                release.wait(5)
            return self.payload(directory)
        watchdog = threading.Timer(5,release.set)
        watchdog.start()
        try:
            with mock.patch.object(module,'_scan_action_files',side_effect=scan):
                self.widget.setAsset(self.rig('A'))
                QtCore.QTimer.singleShot(10,lambda:heartbeats.append(True))
                self.wait(lambda:started.is_set() and bool(heartbeats))
                self.assertFalse(release.is_set())
                self.widget.setAsset(self.rig('B'))
                self.assertIn('正在读取动作',self.widget._list.topLevelItem(1).text(0))
                release.set()
                wait_for_actions(self.widget)
                path = self.widget._list.topLevelItem(1).data(0,QtCore.Qt.UserRole)
                self.assertIn('/B/Action/',path)
                self.assertTrue(all(ident != threading.get_ident() for ident in threads))
        finally:
            release.set()
            watchdog.cancel()
            module._ActionScanner.instance().pool.waitForDone(5000)
            self.app.processEvents()

    def test_rapid_switches_debounce_to_one_final_directory(self):
        with mock.patch.object(module,'_scan_action_files',side_effect=lambda path,cancelled:self.payload(path)) as scan:
            for name in ('A','B','C'):
                self.widget.setAsset(self.rig(name))
            scan.assert_not_called()
            wait_for_actions(self.widget)
            scan.assert_called_once()
            self.assertIn('/C/Action',scan.call_args.args[0])

    def test_scandir_metadata_keeps_nested_actions_without_per_file_os_stat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'Combat').mkdir()
            (root/'Walk.fbx').write_bytes(b'walk')
            (root/'Combat/Attack.FBX').write_bytes(b'attack')
            (root/'Walk.uasset').write_bytes(b'package')
            with mock.patch.object(module.os,'stat',side_effect=AssertionError('separate file stat')):
                result = module._scan_action_files(str(root),threading.Event())
            self.assertTrue(result['exists'])
            self.assertEqual(result['error'],'')
            self.assertEqual({(row[0],row[3]) for row in result['files']},
                             {('Walk.fbx',4),('Combat/Attack.FBX',6)})
            self.assertTrue(all(row[2] is not None for row in result['files']))

    def test_large_list_yields_to_other_gui_work_before_all_rows_exist(self):
        observations = []
        populate = self.widget._populate_rows
        def batch():
            populate()
            if not observations:
                QtCore.QTimer.singleShot(0,lambda:observations.append(
                    (self.widget._loading,self.widget._list.topLevelItemCount())))
        with mock.patch.object(module,'_scan_action_files',side_effect=lambda path,cancelled:self.payload(path,4096)), \
                mock.patch.object(self.widget,'_populate_rows',side_effect=batch):
            self.widget.setAsset(self.rig('Large'))
            wait_for_actions(self.widget)
        self.assertTrue(observations[0][0])
        self.assertLess(observations[0][1],4097)
        self.assertEqual(self.widget._list.topLevelItemCount(),4097)
        self.assertTrue(self.widget._list.isEnabled())

    def test_close_cancels_pending_timer_and_ignores_running_result(self):
        self.widget.setAsset(self.rig('NeverStarted'))
        cancelled = self.widget._cancelled
        generation = self.widget._generation
        directory = self.widget._action_dir
        self.widget.shutdown()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.widget._work_timer.isActive())
        self.widget._scan_finished(1,generation,directory,self.payload(directory))
        self.assertEqual(self.widget._list.topLevelItemCount(),2)
        self.assertFalse(self.widget._loading)


if __name__ == '__main__':
    unittest.main()
