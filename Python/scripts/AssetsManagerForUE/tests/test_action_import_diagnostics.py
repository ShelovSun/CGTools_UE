"""Nested UE ticks and preserving actionable native import failures."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from AssetsManagerForUE.sources import action_import_diagnostics
from AssetsManagerForUE.sources.action_batch import suspend_window_callbacks
from PySide6 import QtCore, QtWidgets
import ue_qt_host


class ActionImportDiagnosticTests(unittest.TestCase):
    def test_window_timers_pause_through_nested_import_and_resume_after_exception(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        timer = QtCore.QTimer(window)
        inactive = QtCore.QTimer(window)
        ticks = []
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(1)
        try:
            with self.assertRaisesRegex(RuntimeError, 'import interrupted'):
                with suspend_window_callbacks(window):
                    self.assertFalse(timer.isActive())
                    self.assertFalse(window.isEnabled())
                    self.assertFalse(window.updatesEnabled())
                    with suspend_window_callbacks(window):
                        time.sleep(0.015)
                        app.processEvents()
                    self.assertFalse(timer.isActive())
                    self.assertFalse(window.isEnabled())
                    self.assertEqual(ticks, [])
                    raise RuntimeError('import interrupted')
            self.assertTrue(timer.isActive())
            self.assertEqual(timer.interval(), 1)
            self.assertFalse(inactive.isActive())
            self.assertTrue(window.isEnabled())
            self.assertTrue(window.updatesEnabled())
            time.sleep(0.015)
            app.processEvents()
            self.assertTrue(ticks)
            window.setEnabled(False)
            window.setUpdatesEnabled(False)
            with suspend_window_callbacks(window):
                pass
            self.assertFalse(window.isEnabled())
            self.assertFalse(window.updatesEnabled())
        finally:
            timer.stop()
            window.close()

    def test_nested_suspend_defers_pump_and_restores_it_after_an_exception(self):
        callbacks = []
        engine = types.SimpleNamespace(register_slate_post_tick_callback=lambda cb: callbacks.append(cb) or 123)
        app = mock.Mock()
        with mock.patch.object(ue_qt_host, '_IN_UNREAL', True), \
             mock.patch.object(ue_qt_host, 'unreal', engine, create=True), \
             mock.patch.object(ue_qt_host._STATE, 'tick_handle', None), \
             mock.patch.object(ue_qt_host, '_find_app', return_value=app):
            ue_qt_host._ensure_event_pump()
            pump = callbacks[0]
            pump(0)
            with self.assertRaisesRegex(RuntimeError, 'native failure'):
                with ue_qt_host.suspend_event_pump():
                    pump(0)
                    with ue_qt_host.suspend_event_pump():
                        pump(0)
                    pump(0)
                    raise RuntimeError('native failure')
            self.assertEqual(app.processEvents.call_count, 1)
            pump(0)
            self.assertEqual(app.processEvents.call_count, 2)
        self.assertEqual(ue_qt_host._STATE.suspend_depth, 0)

    def test_native_bone_errors_are_reported_with_paths_and_full_local_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root/'Project.log'
            log.write_text('old error ignored\n', encoding='utf-8')
            engine = types.SimpleNamespace(Paths=types.SimpleNamespace(
                project_log_dir=lambda: str(root), convert_relative_path_to_full=lambda value: value))
            with mock.patch.dict(os.environ, LOCALAPPDATA=str(root)), self.assertRaises(RuntimeError) as error:
                with action_import_diagnostics.capture('Walk.fbx', '/Game/Hero_Skeleton', '/Game/Action', engine):
                    with log.open('a', encoding='utf-8') as stream:
                        stream.write('AssetTools: 无法检索轨道的骨骼索引：NoseCornerJoint_L\n')
                        stream.write('AssetTools: 无法检索轨道的骨骼索引：JawJoint_M\n')
                    raise SystemError('import_asset_tasks returned NULL without setting an exception')
            self.assertIn('部分动画轨道无法映射到目标骨架', str(error.exception))
            self.assertIn('NoseCornerJoint_L', str(error.exception))
            report = json.loads(next(root.rglob('action-import-*.json')).read_text(encoding='utf-8'))
            self.assertEqual(report['source'], 'Walk.fbx')
            self.assertEqual(report['skeleton'], '/Game/Hero_Skeleton')
            self.assertNotIn('old error ignored', report['log'])
            self.assertIn('returned NULL', report['traceback'])

    def test_original_python_cause_is_preserved_without_a_project_log(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, LOCALAPPDATA=temporary):
            with self.assertRaisesRegex(RuntimeError, '保存动作失败'):
                with action_import_diagnostics.capture('Walk.fbx', '/Game/Hero_Skeleton', '/Game/Action', object()):
                    raise ValueError('保存动作失败：/Game/Action/Walk')
            report = json.loads(next(Path(temporary).rglob('action-import-*.json')).read_text(encoding='utf-8'))
            self.assertIn('ValueError', report['traceback'])


if __name__ == '__main__':
    unittest.main()
