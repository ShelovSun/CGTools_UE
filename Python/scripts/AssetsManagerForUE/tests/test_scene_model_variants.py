"""Scene model pairing, legacy alias compatibility, and real Qt switch controls."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.utils import asset_card_thumbnail as cards
from AssetsManagerForUE.utils.fbxpreview import am_surface_variants as variants
from AssetsManagerForUE.utils.fbxpreview.am_previewGLWidget import PreviewGLWidget


class SceneModelVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scene_models_')
        self.root = Path(self.temp.name) / 'Scenes/StaticMesh/TXingChuanSongDai'
        self.icon = self.root / 'Icon/TXingChuanSongDai.png'
        self.icon.parent.mkdir(parents=True)
        (self.root / 'FBX').mkdir()
        self.widgets = []
        variants.SurfaceVariantLoader.instance().clearCache()

    def tearDown(self):
        variants.SurfaceVariantLoader.instance()._pool.waitForDone(5000)
        self.app.processEvents()
        for widget in self.widgets:
            widget.clear()
            widget.close()
            widget._thumbnail_loader.getThreadPool().waitForDone(5000)
        self.app.processEvents()
        self.temp.cleanup()

    def pair(self, name, color, paired=True):
        path = self.icon.parent / (name + '.png')
        image = QtGui.QImage(150, 150, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor(color))
        self.assertTrue(image.save(str(path)))
        if paired:
            (self.root / 'FBX' / (name + '.FBX')).write_bytes(b'not parsed by these control tests')
        return path

    def discover(self):
        return variants.discoverSurfaceVariants(str(self.icon), 'TXingChuanSongDai')

    def wait(self, condition):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.002)
        self.fail('Asynchronous scene discovery did not finish')

    def preview(self):
        preview = PreviewGLWidget(isPlayer=False)
        self.widgets.append(preview)
        preview.resize(320, 340)
        preview.setTitle('TXingChuanSongDai', '传送带')
        return preview

    def test_arbitrary_names_pair_without_missing_folder_icon_and_compose(self):
        for name, color in (('zhi', 'blue'), ('TXing', 'green'), ('ShiZi', 'red')):
            self.pair(name, color)
        self.pair('orphan', 'yellow', paired=False)
        self.assertEqual([v[0] for v in self.discover()], ['ShiZi', 'TXing', 'zhi'])
        image = cards.load_card_image(str(self.icon), 'TXingChuanSongDai', edge=150)
        for rect, color in zip(cards.surface_icon_rects(150, 3), ('red', 'green', 'blue')):
            self.assertEqual(image.pixelColor(rect.center()), QtGui.QColor(color))

    def test_legacy_folder_alias_is_ignored_but_distinct_real_model_is_kept(self):
        first = self.pair('zhi', 'red')
        self.pair('TXing', 'green')
        self.pair('TXingChuanSongDai', 'blue')
        shutil.copy2(first, self.icon)
        self.assertEqual([v[0] for v in self.discover()], ['TXing', 'zhi'])
        self.pair('TXingChuanSongDai', 'blue')
        self.assertEqual([v[0] for v in self.discover()], ['TXing', 'TXingChuanSongDai', 'zhi'])

    def test_single_noncanonical_model_supplies_card_image(self):
        self.pair('zhi', 'red')
        image = cards.load_card_image(str(self.icon), 'TXingChuanSongDai', edge=150)
        self.assertEqual(image.pixelColor(20, 20), QtGui.QColor('red'))

    def test_single_canonical_and_no_pairs_keep_original_behavior(self):
        self.pair('TXingChuanSongDai', 'green')
        self.assertEqual(len(self.discover()), 1)
        self.assertEqual(cards.load_card_image(str(self.icon), 'TXingChuanSongDai').pixelColor(20, 20), QtGui.QColor('green'))
        (self.root / 'FBX/TXingChuanSongDai.FBX').unlink()
        self.assertEqual(self.discover(), [])

    def test_scene_arrows_and_bottom_buttons_select_real_fbx_and_title(self):
        for name, color in (('zhi', 'blue'), ('TXing', 'green'), ('ShiZi', 'red')):
            self.pair(name, color)
        preview = self.preview()
        loaded = []
        with mock.patch.object(preview, 'loadFbx', side_effect=lambda fbx, icon: loaded.append((fbx, icon))):
            preview.setPreviewPixmap(str(self.icon))
            self.wait(lambda: bool(loaded))
            self.assertFalse(preview._surface_bar.isHidden())
            self.assertFalse(preview._surface_prev_btn.isHidden())
            self.assertEqual(Path(loaded[-1][0]).stem, 'ShiZi')
            preview._surface_next_btn.click()
            self.assertEqual(Path(loaded[-1][0]).stem, 'TXing')
            preview._surface_prev_btn.click()
            self.assertEqual(Path(loaded[-1][0]).stem, 'ShiZi')
            preview._surface_prev_btn.click()
            self.assertEqual(Path(loaded[-1][0]).stem, 'zhi')
            buttons = preview._surface_buttons[preview._surface_variants[1][1]]
            buttons[0].click()
            self.assertEqual(Path(loaded[-1][0]).stem, 'TXing')
            self.assertEqual(buttons[0].toolTip(), 'TXing')
            self.assertIn('Name： TXing\n', preview.title_label.text())
            self.assertFalse(preview._load_timer.isActive())

    def test_single_scene_model_loads_real_file_without_switch_controls(self):
        self.pair('zhi', 'red')
        preview = self.preview()
        with mock.patch.object(preview, 'loadFbx') as load:
            preview.setPreviewPixmap(str(self.icon))
            self.wait(lambda: load.called)
            self.assertEqual(Path(load.call_args[0][0]).stem, 'zhi')
            self.assertTrue(preview._surface_bar.isHidden())
            self.assertTrue(preview._surface_next_btn.isHidden())

    def test_discovery_is_off_gui_thread_and_does_not_start_folder_fbx(self):
        self.pair('zhi', 'red')
        preview = self.preview()
        threads = []
        main = threading.get_ident()
        original = variants.discoverSurfaceVariants
        def discover(*args):
            threads.append(threading.get_ident())
            return original(*args)
        with mock.patch.object(variants, 'discoverSurfaceVariants', side_effect=discover), \
                mock.patch.object(preview, 'loadFbx') as load, \
                mock.patch.object(preview, '_scheduleLoad', side_effect=AssertionError('folder alias scheduled')):
            preview.setPreviewPixmap(str(self.icon))
            self.wait(lambda: load.called)
        self.assertTrue(threads and all(t != main for t in threads))

    def test_selecting_again_rediscovers_new_model_and_ignores_stale_callbacks(self):
        self.pair('zhi', 'red')
        preview = self.preview()
        with mock.patch.object(preview, 'loadFbx') as load:
            preview.setPreviewPixmap(str(self.icon))
            self.wait(lambda: load.called)
            old_serial = preview._surface_request_serial
            self.pair('TXing', 'green')
            load.reset_mock()
            preview.setPreviewPixmap(str(self.icon))
            self.wait(lambda: len(preview._surface_variants) == 2)
            count = load.call_count
            preview._onSurfaceVariants(old_serial, [])
            self.assertEqual(len(preview._surface_variants), 2)
            self.assertEqual(load.call_count, count)
            preview.clear()
            preview._onSurfaceVariants(preview._surface_request_serial - 1, self.discover())
            self.assertEqual(preview._surface_variants, [])

    def test_asset_prefix_rules_stay_unchanged(self):
        other = Path(self.temp.name) / 'Assets/Props/Hero/Icon/Hero.png'
        other.parent.mkdir(parents=True)
        (other.parent.parent / 'FBX').mkdir()
        for name in ('Hero', 'Hero_10', 'Hero_2', 'unrelated'):
            other.with_name(name + '.png').write_bytes(b'filename discovery only')
            (other.parent.parent / 'FBX' / (name + '.fbx')).write_bytes(b'not parsed')
        found = variants.discoverSurfaceVariants(str(other), 'Hero')
        self.assertEqual([v[0] for v in found], ['2', '10'])


if __name__ == '__main__':
    unittest.main()
