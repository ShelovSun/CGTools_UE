"""Real Qt selection gestures and the file set delivered by action-library menus."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtTest, QtWidgets
from AssetsManagerForUE.utils.fbxpreview.am_actionWidget import AssetActionWidget
from test_action_library import wait_for_actions


class ActionMultiselectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='action_multiselect_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root/'GOF/Animations/Characters/Hero/Action'
        self.folder.mkdir(parents=True)
        for index in range(1, 6):
            path = self.folder/('Action_%d.fbx' % index)
            path.write_bytes(b'animation')
            path.with_suffix('.uasset').write_bytes(b'package')
            os.utime(path, (1700000000 + index, 1700000000 + index))
        self.widget = AssetActionWidget()
        self.widget.setAsset(str(self.root/'GOF/Assets/Characters/Hero/FBX/Hero.fbx'))
        wait_for_actions(self.widget)
        self.widget.resize(650, 320)
        self.widget.show()
        self.app.processEvents()
        self.addCleanup(self.widget.close)
        self.tree = self.widget._list

    def click(self, row, modifiers=QtCore.Qt.NoModifier):
        item = self.tree.topLevelItem(row)
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton, modifiers,
                               self.tree.visualItemRect(item).center())
        self.app.processEvents()

    def selected(self):
        return [Path(path).name for path in self.widget._selected_action_paths()]

    def menu(self, row, command=None):
        captured = []
        def choose(menu, *_args):
            captured.append(menu)
            return next((action for action in menu.actions() if action.text() == command), None)
        point = self.tree.visualItemRect(self.tree.topLevelItem(row)).center()
        with mock.patch.object(QtWidgets.QMenu, 'exec_', choose):
            self.widget._show_context_menu(point)
        return captured[0].actions()

    def test_shift_range_ctrl_toggle_and_normal_click(self):
        self.click(1)
        self.click(4, QtCore.Qt.ShiftModifier)
        self.assertEqual(self.selected(), ['Action_5.fbx', 'Action_4.fbx', 'Action_3.fbx', 'Action_2.fbx'])
        self.click(2, QtCore.Qt.ControlModifier)
        self.assertEqual(self.selected(), ['Action_5.fbx', 'Action_3.fbx', 'Action_2.fbx'])
        self.click(5, QtCore.Qt.ControlModifier)
        self.assertEqual(self.selected(), ['Action_5.fbx', 'Action_3.fbx', 'Action_2.fbx', 'Action_1.fbx'])
        self.click(3)
        self.assertEqual(self.selected(), ['Action_3.fbx'])

    def test_right_click_preserves_multiselection_and_dispatches_in_display_order(self):
        self.click(1)
        self.click(3, QtCore.Qt.ShiftModifier)
        loaded, imported, singles = [], [], []
        self.widget.loadActionsRequested.connect(loaded.append)
        self.widget.importActionsRequested.connect(imported.append)
        self.widget.loadActionRequested.connect(singles.append)
        point = self.tree.visualItemRect(self.tree.topLevelItem(2)).center()
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.RightButton, QtCore.Qt.NoModifier, point)
        self.assertEqual(len(self.selected()), 3, 'Native right-click must preserve the selected range')
        self.menu(2, '加载动作')
        self.menu(3, '导入动作FBX')
        self.assertEqual(self.selected(), ['Action_5.fbx', 'Action_4.fbx', 'Action_3.fbx'])
        self.assertEqual([[Path(path).name for path in paths] for paths in loaded],
                         [['Action_5.uasset', 'Action_4.uasset', 'Action_3.uasset']])
        self.assertEqual([[Path(path).name for path in paths] for paths in imported],
                         [['Action_5.fbx', 'Action_4.fbx', 'Action_3.fbx']])
        self.assertEqual(singles, [])

    def test_right_click_unselected_row_targets_only_that_file(self):
        self.click(1)
        self.click(2, QtCore.Qt.ShiftModifier)
        single = []
        self.widget.loadActionRequested.connect(single.append)
        self.menu(5, '加载动作')
        self.assertEqual(self.selected(), ['Action_1.fbx'])
        self.assertEqual([Path(path).name for path in single], ['Action_1.uasset'])

    def test_sort_preserves_all_selected_files_and_current_row(self):
        self.click(1)
        self.click(3, QtCore.Qt.ShiftModifier)
        current = self.tree.currentItem()
        self.widget._on_header_clicked(0)
        self.assertEqual(self.selected(), ['Action_3.fbx', 'Action_4.fbx', 'Action_5.fbx'])
        self.assertIs(self.tree.currentItem(), current)

    def test_search_deselects_hidden_files_and_preview_is_never_a_batch_file(self):
        self.tree.selectAll()
        self.assertEqual(len(self.selected()), 5)
        self.widget._search.setText('Action_2')
        self.assertEqual(self.selected(), ['Action_2.fbx'])
        self.widget._search.clear()
        self.assertEqual(self.selected(), ['Action_2.fbx'])
        self.tree.clearSelection()
        self.tree.topLevelItem(0).setSelected(True)
        self.assertEqual(self.selected(), [])

    def test_open_folder_deduplicates_directories_and_busy_blocks_file_operations(self):
        self.click(1)
        self.click(3, QtCore.Qt.ShiftModifier)
        with mock.patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=True) as opened:
            self.menu(2, '打开文件夹')
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.folder)
        self.widget.setLoadBusy(True)
        actions = self.menu(2)
        self.assertFalse(actions[1].isEnabled())
        self.assertFalse(actions[2].isEnabled())

    def test_missing_one_package_is_reported_to_the_batch_instead_of_silently_skipped(self):
        (self.folder/'Action_4.uasset').unlink()
        self.click(1)
        self.click(2, QtCore.Qt.ShiftModifier)
        loaded = []
        self.widget.loadActionsRequested.connect(loaded.append)
        self.assertTrue(self.menu(1, '加载动作')[1].isEnabled())
        self.assertEqual([Path(path).name for path in loaded[0]], ['Action_5.uasset', 'Action_4.uasset'])


if __name__ == '__main__':
    unittest.main()
