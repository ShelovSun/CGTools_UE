"""Prepared images/GIFs, bounded previews, and a GUI with no resource I/O."""
import base64
import builtins
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from AssetsManagerForUE.sources import component_documentation as service
from AssetsManagerForUE.sources.component_documentation_browser import MarkdownBrowser

GIF = ('R0lGODlhCAAIAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwA'
       'AAAACAAIAAAIDwABCBxIsKDBgwgTKkwYEAAh+QQBCgABACwAAAAACAAIAIEAAP8AAAAAAAAA'
       'AAAIDwABCBxIsKDBgwgTKkwYEAA7')


class DocumentationResourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='component_docs_')
        self.root = Path(self.temp.name)
        self.browser = MarkdownBrowser()
        self.browser.resize(540, 600)
        self.browser.show()
        self.app.processEvents()

    def tearDown(self):
        self.browser.clearMarkdown()
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.temp.cleanup()

    def png(self, folder, color, filename='preview.png', size=QtCore.QSize(320, 180)):
        folder.mkdir(parents=True, exist_ok=True)
        image = QtGui.QImage(size, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor(color))
        self.assertTrue(image.save(str(folder / filename)))
        (folder / 'README.md').write_text('# Example\n![preview](' + filename + ')', encoding='utf-8')

    def test_prepare_reads_and_decodes_in_worker_gui_never_reads_source(self):
        self.png(self.root, 'red')
        opened, decoded, result, errors = [], [], [], []
        original_open, original_reader = builtins.open, QtGui.QImageReader
        def record_open(*args, **kwargs):
            opened.append(threading.get_ident())
            return original_open(*args, **kwargs)
        def record_reader(*args, **kwargs):
            decoded.append(threading.get_ident())
            return original_reader(*args, **kwargs)
        def prepare():
            try:
                result.append(service.prepare(str(self.root)))
            except Exception as exc:
                errors.append(exc)
        with mock.patch('builtins.open', side_effect=record_open), \
             mock.patch.object(service.QtGui, 'QImageReader', side_effect=record_reader):
            thread = threading.Thread(target=prepare)
            thread.start()
            thread.join(4)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(opened and decoded)
            main = threading.get_ident()
            self.assertTrue(all(ident != main for ident in opened + decoded))
            before = len(opened), len(decoded)
            self.browser.showPrepared(result[0])
            self.app.processEvents()
            self.browser.resize(450, 580)
            QtTest.QTest.qWait(100)
            self.assertEqual((len(opened), len(decoded)), before)
            resource = self.browser.document().resource(
                QtGui.QTextDocument.ImageResource, QtCore.QUrl('preview.png'))
            self.assertEqual(resource.pixelColor(0, 0), QtGui.QColor('red'))
            blocked = self.browser.document().resource(
                QtGui.QTextDocument.ImageResource, QtCore.QUrl.fromLocalFile(str(self.root / 'unprepared.png')))
            self.assertTrue(blocked.isNull())

    def test_gif_predecoded_and_animation_pauses_when_hidden(self):
        (self.root / 'preview.gif').write_bytes(base64.b64decode(GIF))
        (self.root / 'README.md').write_text('# Animation\n![demo](preview.gif)', encoding='utf-8')
        payload = service.prepare(str(self.root))
        image = payload['images']['preview.gif']
        self.assertEqual(len(image['frames']), 2)
        self.assertNotEqual(image['frames'][0].pixelColor(0, 0), image['frames'][1].pixelColor(0, 0))
        self.browser.showPrepared(payload)
        self.app.processEvents()
        self.assertTrue(self.browser._animation_timer.isActive())
        deadline = time.monotonic() + 1
        while self.browser._animations[0]['index'] != 1 and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertEqual(self.browser._animations[0]['index'], 1)
        self.browser.hide()
        self.assertFalse(self.browser._animation_timer.isActive())
        self.browser.show()
        self.assertTrue(self.browser._animation_timer.isActive())
        self.browser.clearMarkdown()
        self.assertFalse(self.browser._animation_timer.isActive())
        self.assertEqual(self.browser._animations, [])

    def test_switch_same_resource_name_does_not_keep_old_image_or_mutate_cache(self):
        first, second = self.root / 'A', self.root / 'B'
        self.png(first, 'red')
        self.png(second, 'blue')
        red, blue = service.prepare(str(first)), service.prepare(str(second))
        self.browser.showPrepared(red)
        self.browser.showPrepared(blue)
        self.app.processEvents()
        resource = self.browser.document().resource(QtGui.QTextDocument.ImageResource, QtCore.QUrl('preview.png'))
        self.assertEqual(resource.pixelColor(0, 0), QtGui.QColor('blue'))
        self.assertEqual(red['images']['preview.png']['frames'][0].pixelColor(0, 0), QtGui.QColor('red'))

    def test_cache_evicts_image_payload_and_expired_content(self):
        self.png(self.root / 'A', 'red')
        self.png(self.root / 'B', 'blue')
        a, b = service.prepare(str(self.root / 'A')), service.prepare(str(self.root / 'B'))
        cache = service.DocumentCache(max_bytes=max(a['cost'], b['cost']) + 64)
        cache.put('A', a)
        cache.put('B', b)
        self.assertIsNone(cache.get('A'))
        self.assertIs(cache.get('B'), b)
        self.assertLessEqual(cache.bytes, cache.max_bytes)
        cache.ttl = 0
        self.assertIsNone(cache.get('B'))
        self.assertEqual(cache.bytes, 0)

    def test_large_assets_have_bounded_previews_with_external_open_note(self):
        (self.root / 'preview.gif').write_bytes(base64.b64decode(GIF))
        (self.root / 'README.md').write_text('# Preview\n![demo](preview.gif)\n' + 'text\n' * 100, encoding='utf-8')
        with mock.patch.object(service, 'MAX_GIF_FRAMES', 1), \
             mock.patch.object(service, 'MAX_TEXT_BYTES', 100):
            payload = service.prepare(str(self.root))
        self.assertEqual(len(payload['images']['preview.gif']['frames']), 1)
        self.assertIn('静态预览', payload['html'])
        self.assertIn('说明较长', payload['html'])
        self.assertLessEqual(payload['images']['preview.gif']['cost'], service.DOCUMENT_IMAGE_BUDGET)
        self.browser.showPrepared(payload)
        self.assertFalse(self.browser._animation_timer.isActive())

    def test_legacy_encoding_root_only_and_cancelled_prepare(self):
        child = self.root / 'nested'
        child.mkdir()
        (child / 'README.md').write_text('# Nested', encoding='utf-8')
        self.assertEqual(service.prepare(str(self.root))['status'], 'missing')
        (self.root / 'README.md').write_bytes('# 中文说明'.encode('gb18030'))
        payload = service.prepare(str(self.root))
        self.browser.showPrepared(payload)
        self.assertIn('中文说明', self.browser.toPlainText())
        with self.assertRaises(service.Cancelled):
            service.prepare(str(self.root), lambda: True)

    def test_large_tables_use_bounded_plain_preview_instead_of_heavy_gui_layout(self):
        text = '| A | B | C | D |\n|---|---|---|---|\n' + '| x | y | z | t |\n' * 1000
        (self.root / 'README.md').write_text(text, encoding='utf-8')
        payload = service.prepare(str(self.root))
        self.assertIn('外部打开', payload['html'])
        self.assertNotIn('<table', payload['html'])
        self.assertLess(len(payload['html']), 20000)
        self.browser.showPrepared(payload)
        self.assertLess(self.browser.document().blockCount(), 300)

    def test_chinese_code_has_explicit_supported_font_and_english_keeps_monospace(self):
        (self.root / 'README.md').write_text('`EnglishCode` 和 `中文接口`', encoding='utf-8')
        self.browser.showPrepared(service.prepare(str(self.root)))
        fonts = {}
        block = self.browser.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fonts[fragment.text()] = fragment.charFormat().font().families()
                iterator += 1
            block = block.next()
        self.assertIn('Courier New', fonts['EnglishCode'])
        chinese_fonts = next(families for text, families in fonts.items() if '中文接口' in text)
        self.assertIn('Microsoft YaHei UI', chinese_fonts)

    def test_repeated_switches_release_old_documents_with_only_process_events(self):
        self.png(self.root, 'red')
        payload = service.prepare(str(self.root))
        for _ in range(16):
            self.browser.showPrepared(payload)
            self.app.processEvents()
        documents = self.browser._document_owner.findChildren(QtGui.QTextDocument)
        self.assertEqual(len(documents), 1)
        self.browser.clearMarkdown()
        self.assertEqual(len(self.browser._document_owner.findChildren(QtGui.QTextDocument)), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
