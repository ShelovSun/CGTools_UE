"""Native GL resources must be gone before a preview's context can die."""
import array
import gc
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
import weakref
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete as delete_qt, isValid
from AssetsManagerForUE.utils.fbxpreview import am_previewGLWidget as preview_module


class PreviewLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if cls.app.platformName() == 'offscreen':
            raise unittest.SkipTest('Native QOpenGLWidget requires a windowing platform')

    def wait(self, predicate):
        deadline = time.monotonic()+4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def build(self, register_cleanup=True):
        host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(host)
        preview = preview_module.PreviewGLWidget()
        layout.addWidget(preview)
        preview._stack.setCurrentWidget(preview._gl_view)
        host.resize(420, 340)
        host.show()
        self.wait(lambda: preview._gl_view._gl_inited)
        def cleanup():
            if isValid(preview):
                preview.shutdown()
            if isValid(host):
                delete_qt(host)
            self.app.processEvents()
        if register_cleanup:
            self.addCleanup(cleanup)
        return host, preview

    def mesh(self):
        values = array.array('f', [-1,-1,0, 0,0,1, 0,0,
                                   1,-1,0, 0,0,1, 1,0,
                                   0, 1,0, 0,0,1, .5,1])
        sm = types.SimpleNamespace(first=0, count=3, color=(1,1,1), texture='synthetic')
        md = types.SimpleNamespace(interleaved=values.tobytes(), submeshes=[sm],
                                   bbox_min=(-1,-1,0), bbox_max=(1,1,0))
        image = QtGui.QImage(8,8,QtGui.QImage.Format_RGBA8888)
        image.fill(QtGui.QColor('#c88435'))
        return md, {'synthetic': image}

    def upload(self, preview):
        md, images = self.mesh()
        preview._gl_view.showResult(md, None, images)
        self.wait(lambda: bool(preview._gl_view._textures))
        return md, images, list(preview._gl_view._textures.values())

    def test_shutdown_deletes_native_textures_and_buffers_before_context(self):
        host, preview = self.build()
        _md, _images, textures = self.upload(preview)
        view, context = preview._gl_view, preview._gl_view.context()
        resources = [view._vbo, view._program, view._grid_program, view._skin_program]
        preview.shutdown()
        preview.shutdown()
        self.assertTrue(isValid(context) and context.isValid())
        self.assertEqual(view._textures, {})
        self.assertTrue(all(not isValid(obj) for obj in textures+resources if obj is not None))
        self.assertFalse(view._anim_timer.isActive())
        self.assertFalse(preview._load_timer.isActive())
        self.assertFalse(view._gl_inited)
        delete_qt(host)
        self.assertFalse(isValid(context))
        gc.collect()

    def test_late_results_and_requests_cannot_restart_a_closed_deleted_preview(self):
        host, preview = self.build()
        md, images, _textures = self.upload(preview)
        view = preview._gl_view
        preview.shutdown()
        delete_qt(host)
        with mock.patch.object(preview_module, '_ParseTask') as parse, \
                mock.patch.object(preview_module, '_CombineTask') as combine:
            preview._onParsed(None, md, None, images)
            preview._onParseFailed(None)
            preview._onCombined(None, None, None, images)
            preview._onCombineFailed(None, None)
            preview._onSurfaceVariants(preview._surface_request_serial, [('x','icon','fbx')])
            preview._onSurfaceButtonThumbnail('icon', QtGui.QPixmap())
            preview._onGLFailed()
            preview._positionPreviewOverlays()
            preview.setTitle('late', 'late')
            preview.setPreviewPixmap('late')
            preview.loadFbx('late')
            preview.playAction('late')
            preview.clear()
            view.showResult(md, None, images)
            self.assertFalse(preview.recoverAfterWorkspaceRestore())
            parse.assert_not_called()
            combine.assert_not_called()
        self.assertIsNone(view._pending_result)
        self.assertEqual(preview._cache, {})
        self.assertEqual(preview._anim_cache, {})

    def test_view_replacement_cleans_old_context_and_restores_cached_mesh(self):
        _host, preview = self.build()
        md, images, textures = self.upload(preview)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'synthetic.fbx'
            path.write_bytes(b'local fixture, parsed mesh supplied directly')
            preview._current_fbx = str(path)
            preview._cachePut(str(path), md, None, images)
            old = preview._gl_view
            self.assertTrue(preview.recoverAfterWorkspaceRestore())
            self.assertTrue(old._disposed)
            self.assertEqual(old._textures, {})
            self.assertTrue(all(not isValid(texture) for texture in textures))
            self.wait(lambda: bool(preview._gl_view._textures))
            self.assertIsNot(preview._gl_view, old)
            self.assertEqual(preview._gl_view._count, 3)

    def test_cleanup_restores_another_previews_current_context(self):
        _host, preview = self.build()
        self.upload(preview)
        _other_host, other = self.build()
        other._gl_view.makeCurrent()
        context = other._gl_view.context()
        preview._gl_view._cleanupGL()
        self.assertEqual(QtGui.QOpenGLContext.currentContext(), context)
        other._gl_view.doneCurrent()

    def test_already_deleted_parent_fallback_does_not_compare_dead_contexts(self):
        host, preview = self.build()
        _md, _images, textures = self.upload(preview)
        view = preview._gl_view
        # Bypass normal owner shutdown to cover an already gone native parent.
        delete_qt(host)
        self.assertFalse(isValid(view))
        _other_host, other = self.build()
        other._gl_view.makeCurrent()
        context = other._gl_view.context()
        view.shutdown()
        self.assertTrue(all(not isValid(texture) for texture in textures))
        self.assertEqual(QtGui.QOpenGLContext.currentContext(), context)
        other._gl_view.doneCurrent()
        gc.collect()

    def test_gc_after_native_parent_deletion_releases_retained_textures(self):
        # This case owns native deletion itself; a cleanup closure retaining
        # preview would prevent the very GC transition under test.
        host, preview = self.build(register_cleanup=False)
        _md, _images, textures = self.upload(preview)
        view = preview._gl_view
        view._lifetime_probe_cycle = view
        reference = weakref.ref(view)
        delete_qt(host)
        _other_host, other = self.build()
        other._gl_view.makeCurrent()
        del preview, view
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(all(not isValid(texture) for texture in textures))
        other._gl_view.doneCurrent()

    def test_closing_does_not_wait_for_a_running_parse_or_deliver_its_result(self):
        host, preview = self.build()
        started, release = threading.Event(), threading.Event()
        md, _images = self.mesh()
        def read(*_args, **_kwargs):
            started.set()
            release.wait(3)
            return md, None
        pool = preview._pool
        self.assertIsNone(pool.parent())
        watchdog = threading.Timer(3, release.set)
        watchdog.start()
        try:
            with tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.object(preview_module.fbxMesh, 'read', side_effect=read):
                path = Path(temporary)/'waiting.fbx'
                path.write_bytes(b'local fixture')
                preview.loadFbx(str(path))
                self.assertTrue(started.wait(2))
                preview.shutdown()
                delete_qt(host)
                self.assertFalse(release.is_set(), 'Window deletion waited for a parse worker')
                release.set()
                self.assertTrue(pool.waitForDone(3000))
                self.app.processEvents()
                self.assertEqual(preview._cache, {})
        finally:
            release.set()
            watchdog.cancel()
            pool.waitForDone(4000)

    def test_cancelled_queued_work_skips_fbx_and_image_reads(self):
        cancelled = threading.Event()
        cancelled.set()
        signals = preview_module._ParseSignals()
        combine_signals = preview_module._CombineSignals()
        with mock.patch.object(preview_module.fbxMesh, 'read') as read, \
                mock.patch.object(preview_module.fbxMesh, 'read_skin') as skin:
            preview_module._ParseTask('unused', signals, cancelled).run()
            preview_module._CombineTask('rig', 'action', combine_signals, {}, threading.Lock(), cancelled).run()
            read.assert_not_called()
            skin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
