"""The action library reads the Animations tree after server folder migration."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6 import QtCore, QtWidgets
from AssetsManagerForUE.utils.fbxpreview.am_actionWidget import AssetActionWidget


class ActionLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="action_library_")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "GOF"
        self.asset = self.project / "Assets/Characters/BaSiTeV4"
        self.rig = self.asset / "FBX/BaSiTeV4.fbx"
        self.rig.parent.mkdir(parents=True)
        self.rig.write_bytes(b"rig")
        self.old_actions = self.asset / "Action"
        self.old_actions.mkdir()
        (self.old_actions / "OldOnly.fbx").write_bytes(b"old action")
        self.actions = self.project / "Animations/Characters/BaSiTeV4/Action"
        self.widget = AssetActionWidget()
        self.addCleanup(self.widget.close)

    def action_items(self):
        return [
            item for index in range(self.widget._list.topLevelItemCount())
            if (item := self.widget._list.topLevelItem(index)).data(0, QtCore.Qt.UserRole)
        ]

    def test_windows_unc_props_and_case_variations_use_animations(self):
        for source, expected in (
            (r"Y:\MCCProject\GOF\Assets\Characters\BaSiTeV4\FBX\BaSiTeV4.fbx",
             "Y:/MCCProject/GOF/Animations/Characters/BaSiTeV4/Action"),
            ("Y:/MCCProject/GOF/Assets/Props/Sword/FBX/Sword.fbx",
             "Y:/MCCProject/GOF/Animations/Props/Sword/Action"),
            (r"\\nas\MCCProject\GOF\assets\Characters\BaSiTeV4\fbx\rig.fbx",
             "//nas/MCCProject/GOF/Animations/Characters/BaSiTeV4/Action"),
            ("Y:/MCCProject/GOF/Assets/Characters/BaSiTeV4/rig.fbx",
             "Y:/MCCProject/GOF/Animations/Characters/BaSiTeV4/Action"),
        ):
            with self.subTest(source=source):
                self.assertEqual(self.widget._derive_action_dir(source), expected)

    def test_empty_binding_does_not_scan_any_folder(self):
        self.assertEqual(self.widget._derive_action_dir(""), "")
        self.widget.setAsset("")
        self.assertEqual(self.action_items(), [])

    def test_lists_new_actions_recursively_and_ignores_existing_old_library(self):
        nested = self.actions / "Combat"
        nested.mkdir(parents=True)
        (self.actions / "Walk.fbx").write_bytes(b"walk")
        (nested / "Attack.FBX").write_bytes(b"attack")
        (self.actions / "Walk.uasset").write_bytes(b"ue package")
        self.widget.setAsset(str(self.rig))
        self.assertEqual(self.widget._action_dir, self.actions.as_posix())
        self.assertEqual({item.text(0) for item in self.action_items()}, {"Walk.fbx", "Combat/Attack.FBX"})
        for item in self.action_items():
            self.assertTrue(Path(item.data(0, QtCore.Qt.UserRole)).is_relative_to(self.actions))

    def test_missing_new_library_does_not_fall_back_to_old_actions(self):
        self.widget.setAsset(str(self.rig))
        self.assertEqual(self.widget._action_dir, self.actions.as_posix())
        self.assertEqual(self.action_items(), [])
        self.assertEqual(self.widget._list.topLevelItem(1).text(0), "无 Action 目录")

    def test_preview_and_open_folder_use_the_new_file(self):
        self.actions.mkdir(parents=True)
        action_path = self.actions / "Walk.fbx"
        action_path.write_bytes(b"walk")
        self.widget.setAsset(str(self.rig))
        item = self.action_items()[0]
        activated = []
        self.widget.actionActivated.connect(activated.append)
        self.widget._on_item_clicked(item)
        self.assertEqual(activated, [action_path.as_posix()])
        with mock.patch.object(QtCore.QProcess, "startDetached", return_value=(True, 123)) as explorer:
            self.widget._open_action_folder(item.data(0, QtCore.Qt.UserRole))
        self.assertEqual(explorer.call_args.args, ("explorer.exe", ["/select,", os.path.normpath(action_path)]))

    def action_menu(self, select=None):
        self.widget.resize(620, 300)
        self.widget.show()
        self.app.processEvents()
        item = self.action_items()[0]
        point = self.widget._list.visualItemRect(item).center()
        captured = []
        def choose(menu, *args):
            captured.append(menu)
            return next((action for action in menu.actions() if action.text() == select), None)
        with mock.patch.object(QtWidgets.QMenu, "exec_", choose):
            self.widget._show_context_menu(point)
        return captured[0].actions()

    def test_load_menu_is_disabled_without_same_name_package(self):
        self.actions.mkdir(parents=True)
        (self.actions / "Walk.fbx").write_bytes(b"walk")
        (self.actions / "Other.uasset").write_bytes(b"unrelated package")
        self.widget.setAsset(str(self.rig))
        actions = self.action_menu()
        self.assertEqual([action.text() for action in actions], ["打开文件夹", "加载动作", "导入动作FBX"])
        self.assertFalse(actions[1].isEnabled())
        self.assertTrue(actions[2].isEnabled())

    def test_load_and_fbx_commands_emit_their_respective_source_files(self):
        self.actions.mkdir(parents=True)
        fbx = self.actions / "Walk.fbx"
        package = self.actions / "Walk.uasset"
        fbx.write_bytes(b"walk")
        package.write_bytes(b"package")
        self.widget.setAsset(str(self.rig))
        loaded, imported = [], []
        self.widget.loadActionRequested.connect(loaded.append)
        self.widget.importActionRequested.connect(imported.append)
        self.assertTrue(self.action_menu("加载动作")[1].isEnabled())
        self.action_menu("导入动作FBX")
        self.assertEqual(loaded, [package.as_posix()])
        self.assertEqual(imported, [fbx.as_posix()])
        self.widget.setLoadBusy(True)
        actions = self.action_menu("加载动作")
        self.assertFalse(actions[1].isEnabled())
        self.assertFalse(actions[2].isEnabled())
        self.assertEqual(loaded, [package.as_posix()])


if __name__ == "__main__":
    unittest.main()
