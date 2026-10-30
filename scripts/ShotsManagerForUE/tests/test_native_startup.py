"""Native startup order, scope cleanup, and real Qt readiness without network IO."""

import ast
import importlib
import importlib.util
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from ShotsManagerForUE import launcher


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class ShotsNativeStartupTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.callbacks = {}
        self.window = types.SimpleNamespace(
            startupFinished=Signal(), destroyed=Signal(), _startup_finished=False)
        self.task = mock.Mock()
        self.task.__enter__ = mock.Mock(side_effect=lambda: self.events.append("enter"))
        self.task.__exit__ = mock.Mock(side_effect=lambda *_: self.events.append("close"))
        self.task.make_dialog.side_effect = lambda *_: self.events.append("dialog")
        self.task.enter_progress_frame.side_effect = self.progress
        self.unreal = types.ModuleType("unreal")
        self.unreal.ScopedSlowTask = mock.Mock(return_value=self.task)
        self.unreal.register_slate_post_tick_callback = self.register
        self.unreal.unregister_slate_post_tick_callback = self.unregister
        self.unreal.log = mock.Mock()
        self.unreal.log_error = mock.Mock()
        self.enterContext(mock.patch.dict(sys.modules, {"unreal": self.unreal}))
        self.import_main = mock.Mock(side_effect=self.load_main)
        self.enterContext(mock.patch.object(
            launcher, "importlib", types.SimpleNamespace(import_module=self.import_main)))
        self.assertIsNone(launcher._pending)
        self.addCleanup(self.close_pending)

    def close_pending(self):
        if launcher._pending is not None:
            launcher._pending.finish()

    def register(self, callback):
        self.callbacks[1] = callback
        return 1

    def unregister(self, handle):
        self.callbacks.pop(handle)

    def tick(self):
        for callback in list(self.callbacks.values()):
            callback(1 / 60)

    def progress(self, *_args):
        self.events.append("progress")
        # ScopedSlowTask may cause reentrant Slate processing.
        self.tick()

    def load_main(self, _name):
        self.events.append("import_qt_app")
        return types.SimpleNamespace(showWin=lambda: self.window)

    def test_native_progress_precedes_import_and_waits_for_ready_signal(self):
        launcher.showWin()
        self.unreal.ScopedSlowTask.assert_called_once_with(3.0, "正在启动...")
        self.task.make_dialog.assert_called_once_with(False, True)
        self.import_main.assert_not_called()
        self.tick()
        self.import_main.assert_not_called()
        self.tick()
        self.import_main.assert_called_once_with("ShotsManagerForUE.ShotsManager_UE")
        self.assertLess(self.events.index("dialog"), self.events.index("import_qt_app"))
        self.assertEqual(self.callbacks, {})
        self.task.__exit__.assert_not_called()
        self.window.startupFinished.emit()
        self.task.__exit__.assert_called_once_with(None, None, None)
        self.assertEqual([call.args[0] for call in self.task.enter_progress_frame.call_args_list], [0, 1, 1, 1])
        self.assertIsNone(launcher._pending)
        self.assertEqual(self.window.startupFinished.callbacks, [])
        self.assertEqual(self.window.destroyed.callbacks, [])

    def test_repeated_clicks_and_nested_ticks_launch_only_once(self):
        launcher.showWin()
        launcher.showWin()
        self.tick()
        self.tick()
        launcher.showWin()
        self.unreal.ScopedSlowTask.assert_called_once()
        self.import_main.assert_called_once()
        self.window.startupFinished.emit()
        launcher.showWin()
        self.assertEqual(self.unreal.ScopedSlowTask.call_count, 2)

    def test_import_failure_closes_progress_and_allows_retry(self):
        self.import_main.side_effect = ImportError("cannot import PySide6")
        launcher.showWin()
        self.tick()
        self.tick()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)
        self.assertEqual(self.callbacks, {})
        self.assertIn("cannot import PySide6", self.unreal.log_error.call_args.args[0])
        self.import_main.side_effect = self.load_main
        launcher.showWin()
        self.assertEqual(self.unreal.ScopedSlowTask.call_count, 2)

    def test_initialization_failure_closes_progress_and_reports_reason(self):
        self.import_main.side_effect = None
        self.import_main.return_value = types.SimpleNamespace(
            showWin=mock.Mock(side_effect=OSError("project settings unavailable")))
        launcher.showWin()
        self.tick()
        self.tick()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)
        self.assertIn("project settings unavailable", self.unreal.log_error.call_args.args[0])

    def test_destroyed_window_closes_progress_once(self):
        launcher.showWin()
        self.tick()
        self.tick()
        self.window.destroyed.emit(None)
        self.window.startupFinished.emit()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)

    def test_cached_older_main_module_and_already_ready_window_are_supported(self):
        for window in (object(), types.SimpleNamespace(_startup_finished=True, startupFinished=Signal())):
            with self.subTest(window=window):
                self.import_main.side_effect = None
                self.import_main.return_value = types.SimpleNamespace(showWin=lambda: None, win=window)
                launcher.showWin()
                self.tick()
                self.tick()
                self.assertIsNone(launcher._pending)
        self.assertEqual(self.task.__exit__.call_count, 2)

    def test_tick_registration_failure_releases_scope(self):
        self.unreal.register_slate_post_tick_callback = mock.Mock(side_effect=RuntimeError("tick registration failed"))
        with self.assertRaisesRegex(RuntimeError, "tick registration failed"):
            launcher.showWin()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)

    def test_importing_launcher_does_not_import_unreal_qt_or_main_module(self):
        spec = importlib.util.spec_from_file_location("isolated_shots_launcher", Path(launcher.__file__))
        fresh = importlib.util.module_from_spec(spec)
        real_import = __import__
        def checked_import(name, *args, **kwargs):
            if name.startswith(("PySide", "ShotsManagerForUE", "unreal")):
                self.fail("Heavy import at launcher module initialization: " + name)
            return real_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=checked_import):
            spec.loader.exec_module(fresh)
        self.assertIsNone(fresh._pending)

    def test_menu_and_start_script_route_through_lightweight_launcher(self):
        # Read the actual menu command without running Common's menu creation.
        tree = ast.parse((SCRIPTS / "Common.py").read_text(encoding="utf-8-sig"))
        setting = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "projectSetting")
        namespace = {}
        exec(compile(ast.Module(body=[setting], type_ignores=[]), "Common.py", "exec"), namespace)
        command = namespace["projectSetting"]()["menu"]["ShotsManager"]["command"]
        with mock.patch.object(launcher, "showWin") as show:
            exec(command, {})
            runpy.run_path(str(SCRIPTS / "ShotsManagerForUE/start_shots_manager.py"))
        self.assertEqual(show.call_count, 2)


class ShotsQtStartupTests(unittest.TestCase):
    def test_real_window_reports_ready_after_show_and_only_once(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtWidgets
        unreal = types.ModuleType("unreal")
        fake_host = types.SimpleNamespace(host_window=lambda widget, app: widget.show())
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            sys.modules, {"unreal": unreal, "ue_qt_host": fake_host}
        ):
            module = importlib.import_module("ShotsManagerForUE.ShotsManager_UE")
            settings = {"rootPath": temp, "projects": ["Test"], "stages": ["Layout"]}
            with mock.patch.object(module.CGPipelineToolUEUI, "projectSetting", return_value=settings), \
                 mock.patch.object(module.CGPipelineToolUEUI, "readSettings", return_value=(None,) * 5), \
                 mock.patch.object(module.CGPipelineToolUEUI, "rememberSettings"):
                window = module.showWin()
                try:
                    self.assertIs(window, module.win)
                    self.assertIn("2.0.4", window.windowTitle())
                    self.assertTrue(window.isVisible())
                    self.assertFalse(window._startup_finished)
                    ready = mock.Mock()
                    window.startupFinished.connect(ready)
                    QtWidgets.QApplication.instance().processEvents()
                    self.assertTrue(window._startup_finished)
                    ready.assert_called_once_with()
                    window.finishStartup()
                    ready.assert_called_once_with()
                finally:
                    window.close()
                    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
                    module.win = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
