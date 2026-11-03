"""Level dragging uses local packages independently of server sync state."""

import copy
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import unreal
except ImportError:
    unreal = types.ModuleType("unreal")
    unreal.log_warning = lambda text: None
    sys.modules["unreal"] = unreal

from PySide6 import QtCore, QtGui, QtWidgets
from AssetsManagerForUE.sources import ue_asset_service, sceneTools
from AssetsManagerForUE.utils import myWidget


class LocalAssetDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="local_asset_drag_")
        self.addCleanup(self.temporary.cleanup)
        self.content = Path(self.temporary.name) / "Project/Content"
        self.content.mkdir(parents=True)
        self.classes = {}
        self.library = mock.Mock()
        self.library.does_asset_exist.side_effect = lambda path: path in self.classes
        self.registry = mock.Mock()
        self.engine = types.SimpleNamespace(
            EditorAssetLibrary=self.library,
            AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda: self.registry))
        for patcher in (
                mock.patch.object(ue_asset_service, "unreal", self.engine),
                mock.patch.object(ue_asset_service, "_asset_class_name", side_effect=self.classes.get),
                mock.patch.object(ue_asset_service, "_is_actor_blueprint", return_value=True),
                mock.patch.object(ue_asset_service, "_project_content_dir", return_value=str(self.content))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.widget = myWidget.MainQListWiget()
        self.widget.resize(300, 250)
        self.widget.show()
        self.addCleanup(self.close_widget)

    def close_widget(self):
        self.widget._finishAssetDrag()
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def package(self, relative, class_name="StaticMesh"):
        file = self.content / (relative + ".uasset")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"old local version")
        path = "/Game/{0}.{1}".format(relative, relative.rsplit("/", 1)[-1])
        self.classes[path] = class_name
        return path, file

    def card(self, path, state="conflict", root="//offline/GOF/Assets/Characters/Hero"):
        item = myWidget.Item()
        item.setItemsWidget(self.widget)
        item.setItemData((0, "Hero", "", "", "", "", "", root + "/Icon/Hero.png", "", "category", path))
        item.setUEState(state, "server differs", {
            "state": state, "target_root": str(self.content),
            "main_object_path": path, "package_object_paths": [path],
            "files": [], "source_root": "//offline/server"})
        self.widget.addItem(item)
        self.widget.setCurrentItem(item)
        return item

    def test_old_local_asset_drags_in_all_sync_states_without_copy_or_server_scan(self):
        path, file = self.package("Assets/Characters/Hero/Hero", "SkeletalMesh")
        self.widget.setAssetDragResolver(ue_asset_service.resolve_local_card_drag)
        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=AssertionError("server read")), \
                mock.patch.object(ue_asset_service, "AssetCopyWorker", side_effect=AssertionError("copy")):
            for state in ("conflict", "partial", "ready", "missing", "error", "scanning"):
                with self.subTest(state=state):
                    item = self.card(path, state)
                    plan_before = copy.deepcopy(item.uePlan())
                    self.assertTrue(self.widget._beginAssetDrag(item, QtCore.QPoint(10, 10)))
                    self.assertEqual(item.ueMainObjectPath(), path)
                    self.assertEqual(item.ueState(), state)
                    self.assertEqual(item.uePlan(), plan_before)
                    self.widget._finishAssetDrag()
        self.assertEqual(file.read_bytes(), b"old local version")

    def test_deleted_local_uasset_blocks_drag_even_if_registry_and_state_say_ready(self):
        path, file = self.package("Assets/Characters/Hero/Hero")
        item = self.card(path, "ready")
        self.widget.setAssetDragResolver(ue_asset_service.resolve_local_card_drag)
        file.unlink()
        errors = []
        self.widget.assetDragRejected.connect(errors.append)
        for _ in range(3):
            self.assertFalse(self.widget._beginAssetDrag(item, QtCore.QPoint()))
        self.assertEqual(len(errors), 1)
        self.assertIn(".uasset", errors[0])
        self.assertFalse(self.widget._assetDragActive)

    def test_local_folder_fallback_works_when_server_plan_is_empty_or_has_renamed_main(self):
        for category, class_name in (("Assets/Characters", "SkeletalMesh"), ("Scenes/Props", "StaticMesh")):
            path, _ = self.package(category + "/Hero/Hero_Old", class_name)
            item = self.card("/Game/Missing_New.Missing_New", "error", "//offline/GOF/" + category + "/Hero")
            item._ue_plan = {}
            self.assertEqual(ue_asset_service.resolve_local_card_drag(item), (path, ""))

    def test_explicit_blueprint_and_effects_use_their_own_local_version(self):
        for name, class_name in (("BP_Hero", "Blueprint"), ("NS_Hit", "NiagaraSystem"), ("P_Hit", "ParticleSystem")):
            path, _ = self.package("Folder/" + name, class_name)
            item = self.card(path)
            self.widget.setAssetDragResolver(lambda card: ue_asset_service.resolve_local_drag_asset(
                card.uePlan(), object_path=card.itemData()[10]))
            self.assertTrue(self.widget._beginAssetDrag(item, QtCore.QPoint()))
            self.assertEqual(item.ueMainObjectPath(), path)
            self.widget._finishAssetDrag()

    def test_missing_explicit_effect_does_not_drag_a_local_dependency_instead(self):
        mesh, _ = self.package("VFX/Hit/Dependency")
        path, error = ue_asset_service.resolve_local_drag_asset(
            {"package_object_paths": [mesh]}, object_path="/Game/VFX/Hit/NS_Hit.NS_Hit")
        self.assertEqual(path, "")
        self.assertIn(".uasset", error)

    def test_non_actor_blueprints_and_non_placeable_assets_report_type_limit(self):
        for class_name in ("Blueprint", "AnimBlueprint", "Material", "Skeleton"):
            path, _ = self.package("Folder/" + class_name, class_name)
            with mock.patch.object(ue_asset_service, "_is_actor_blueprint", return_value=False):
                resolved, error = ue_asset_service.resolve_local_drag_asset({}, object_path=path)
            self.assertEqual(resolved, "")
            self.assertIn("无法直接拖入关卡", error)
            self.assertIn(path, error)

    def test_existing_file_is_registered_locally_when_registry_has_not_seen_it(self):
        path, file = self.package("Folder/SM_Hero")
        self.library.does_asset_exist.side_effect = [False, True]
        self.assertEqual(ue_asset_service.resolve_local_drag_asset({}, object_path=path), (path, ""))
        self.registry.scan_files_synchronous.assert_called_once_with([str(file).replace("\\", "/")], True)

    def test_release_keeps_screen_coordinates_and_routes_to_native_bridge(self):
        path, _ = self.package("Scenes/Props/Hero/Hero")
        item = self.card(path)
        self.widget.setAssetDragResolver(ue_asset_service.resolve_local_card_drag)
        self.widget.assetDropRequested.connect(
            lambda payload: sceneTools.SceneToolsUI.placeImportedAsset(mock.Mock(), payload))
        self.widget._assetDragItem = item
        self.assertTrue(self.widget._beginAssetDrag(item, QtCore.QPoint()))
        # Release outside the Qt list: actual placement is delegated to Slate.
        screen = self.widget.viewport().mapToGlobal(QtCore.QPoint(-100, -100))
        release = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(-100, -100), QtCore.QPointF(screen),
            QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        with mock.patch.object(ue_asset_service, "place_asset_at_cursor", return_value=(True, "")) as place:
            self.widget.mouseReleaseEvent(release)
        place.assert_called_once_with(path, screen_position=(screen.x(), screen.y()))

    def test_disabled_folder_or_component_cards_do_not_start_drag(self):
        item = self.card("", "folder")
        item.setDragEnabled(False)
        resolver = mock.Mock()
        self.widget.setAssetDragResolver(resolver)
        self.assertFalse(self.widget._beginAssetDrag(item, QtCore.QPoint()))
        resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
