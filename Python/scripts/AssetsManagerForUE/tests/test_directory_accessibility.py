"""Native Qt accessibility navigation after directory collapse, in our own UI."""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from AssetsManagerForUE.utils.folder_style import style_directory_view


class DirectoryAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.was_active = QtGui.QAccessible.isActive()
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        style_directory_view(self.tree)
        self.root = QtWidgets.QTreeWidgetItem(self.tree, ['Library'])
        self.team = QtWidgets.QTreeWidgetItem(self.root, ['Team1'])
        self.branch = QtWidgets.QTreeWidgetItem(self.team, ['aaa'])
        self.leaves = [QtWidgets.QTreeWidgetItem(self.branch, [name])
                       for name in ('explode_fx', 'NS_N_Upgrade', 'NS_Sparks')]
        for name in ('Bow', 'Water', 'Fire', 'Team3', 'Flower'):
            QtWidgets.QTreeWidgetItem(self.team, [name])
        for item in (self.root, self.team, self.branch):
            item.setExpanded(True)
        self.tree.setCurrentItem(self.leaves[0])
        self.tree.resize(240, 400)
        self.tree.show()
        self.app.processEvents()
        QtGui.QAccessible.setActive(True)
        self.iface = QtGui.QAccessible.queryAccessibleInterface(self.tree)
        self._read_cached_rows()

    def tearDown(self):
        self.tree.close()
        self.tree.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(self.tree, QtCore.QEvent.DeferredDelete)
        QtGui.QAccessible.setActive(self.was_active)

    def _read_cached_rows(self):
        return [(i, self.iface.child(i).text(QtGui.QAccessible.Name),
                 self.iface.indexOfChild(self.iface.child(i)))
                for i in range(self.iface.childCount())]

    def _assert_sibling_navigation(self, names):
        # QWindowsUiaMainProvider::Navigate(NextSibling) uses indexOfChild + 1,
        # then skips invisible children. Bound the walk instead of hanging.
        index, seen, actual = 0, set(), []
        while 0 <= index < self.iface.childCount():
            child = self.iface.child(index)
            if child.state().invisible:
                index += 1
                continue
            marker = (index, self.iface.indexOfChild(child))
            self.assertNotIn(marker, seen, 'Native UIA sibling navigation contains a cycle')
            seen.add(marker)
            actual.append(child.text(QtGui.QAccessible.Name))
            index = marker[1] + 1
        self.assertEqual(actual, names)

    def test_native_mouse_collapse_keeps_accessible_siblings_finite(self):
        rect = self.tree.visualItemRect(self.branch)
        point = QtCore.QPoint(rect.left() - self.tree.indentation() // 2, rect.center().y())
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                               QtCore.Qt.NoModifier, point)
        self.assertFalse(self.branch.isExpanded())
        self._assert_sibling_navigation(
            ['Library', 'Team1', 'aaa', 'Bow', 'Water', 'Fire', 'Team3', 'Flower'])

    def test_repeated_nested_collapse_updates_cache_before_event_loop(self):
        for _ in range(36):
            for branch in (self.branch, self.team):
                self._read_cached_rows()
                branch.setExpanded(False)
                # No processEvents() here: an immediately arriving UIA query
                # must see the new row ordering, even with a hidden selection.
                rows = self._read_cached_rows()
                self.assertEqual([row[0] for row in rows], [row[2] for row in rows])
                branch.setExpanded(True)
        self.assertIs(self.tree.currentItem(), self.leaves[0])

    def test_restyling_does_not_duplicate_accessibility_notifications(self):
        style_directory_view(self.tree)
        self.app.processEvents()
        self._read_cached_rows()
        original = QtGui.QAccessible.updateAccessibility
        with mock.patch.object(QtGui.QAccessible, 'updateAccessibility', wraps=original) as notify:
            self.branch.setExpanded(False)
        self.assertEqual(notify.call_count, 1)

    def test_inactive_accessibility_skips_extra_notifications(self):
        QtGui.QAccessible.setActive(False)
        with mock.patch.object(QtGui.QAccessible, 'updateAccessibility') as notify:
            self.branch.setExpanded(False)
        notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
