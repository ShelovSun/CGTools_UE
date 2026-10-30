"""Native startup feedback must paint before importing Qt, then always close."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from AssetsManagerForUE import launcher


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


class NativeStartupTests(unittest.TestCase):
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
        # UE progress updates may pump a nested Slate tick.
        self.tick()

    def load_main(self, _name):
        self.events.append("import_qt_app")
        return types.SimpleNamespace(showWindow=lambda: self.window)

    def test_native_dialog_precedes_heavy_import_and_stays_until_initial_tab_ready(self):
        launcher.showWindow()
        self.unreal.ScopedSlowTask.assert_called_once_with(1.0, "正在启动...")
        self.task.make_dialog.assert_called_once_with(False, True)
        self.import_main.assert_not_called()
        self.tick()
        self.import_main.assert_not_called()
        self.tick()
        self.import_main.assert_called_once_with("AssetsManagerForUE.AssetsManagerForUE")
        self.assertLess(self.events.index("dialog"), self.events.index("import_qt_app"))
        self.assertEqual(self.callbacks, {})
        self.task.__exit__.assert_not_called()
        self.window.startupFinished.emit()
        self.task.__exit__.assert_called_once_with(None, None, None)
        self.assertIsNone(launcher._pending)
        self.assertEqual(self.window.startupFinished.callbacks, [])
        self.assertEqual(self.window.destroyed.callbacks, [])

    def test_repeated_clicks_and_nested_slate_ticks_only_launch_once(self):
        launcher.showWindow()
        launcher.showWindow()
        self.tick()
        self.tick()
        launcher.showWindow()
        self.unreal.ScopedSlowTask.assert_called_once()
        self.import_main.assert_called_once()
        self.window.startupFinished.emit()
        launcher.showWindow()
        self.assertEqual(self.unreal.ScopedSlowTask.call_count, 2)

    def test_import_failure_closes_native_dialog_and_allows_retry(self):
        self.import_main.side_effect = ImportError("cannot import PySide6")
        launcher.showWindow()
        self.tick()
        self.tick()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)
        self.assertEqual(self.callbacks, {})
        self.assertIn("cannot import PySide6", self.unreal.log_error.call_args.args[0])
        self.import_main.side_effect = self.load_main
        launcher.showWindow()
        self.assertEqual(self.unreal.ScopedSlowTask.call_count, 2)

    def test_destroyed_window_also_closes_dialog_once(self):
        launcher.showWindow()
        self.tick()
        self.tick()
        self.window.destroyed.emit(None)
        self.window.startupFinished.emit()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)

    def test_cached_older_application_module_can_still_open(self):
        old_window = object()
        self.import_main.side_effect = None
        self.import_main.return_value = types.SimpleNamespace(showWindow=lambda: None, win=old_window)
        launcher.showWindow()
        self.tick()
        self.tick()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)

    def test_registration_failure_releases_native_scope_and_pending_request(self):
        self.unreal.register_slate_post_tick_callback = mock.Mock(side_effect=RuntimeError("tick registration failed"))
        with self.assertRaisesRegex(RuntimeError, "tick registration failed"):
            launcher.showWindow()
        self.task.__exit__.assert_called_once()
        self.assertIsNone(launcher._pending)

    def test_importing_launcher_does_not_import_qt_or_main_application(self):
        spec = importlib.util.spec_from_file_location("isolated_startup_launcher", Path(launcher.__file__))
        fresh = importlib.util.module_from_spec(spec)
        real_import = __import__

        def checked_import(name, *args, **kwargs):
            if name.startswith(("PySide", "AssetsManagerForUE", "unreal")):
                self.fail("Heavy/UE import at module initialization: " + name)
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=checked_import):
            spec.loader.exec_module(fresh)
        self.assertIsNone(fresh._pending)
