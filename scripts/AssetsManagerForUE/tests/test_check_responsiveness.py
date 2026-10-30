"""Thread affinity, UI backpressure and viewport work under large asset lists."""

import threading
import time
from unittest import mock

from test_state_scan_priority import ScanPriorityFixture
from AssetsManagerForUE.sources import ue_asset_service
from AssetsManagerForUE.utils import myWidget
from PySide6 import QtCore


class CheckResponsivenessTests(ScanPriorityFixture):
    def test_ready_scans_use_workers_and_never_resolve_or_load_ue_assets(self):
        main_thread = threading.get_ident()
        for scene in (False, True):
            with self.subTest(scene=scene):
                ui = self.make_ui(scene=scene)
                worker_threads, callback_threads, ticks = [], [], []

                def build(root, target, cancelled=None, **kwargs):
                    worker_threads.append(threading.get_ident())
                    return {"asset_root": root, "state": "ready", "source_available": True,
                            "package_object_paths": ["/Game/BP_Test.BP_Test"]}

                original = ui._setItemUEPlan

                def apply(item, plan):
                    callback_threads.append(threading.get_ident())
                    return original(item, plan)

                timer = QtCore.QTimer()
                timer.timeout.connect(lambda: ticks.append(time.monotonic()))
                timer.start(5)
                with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build), \
                        mock.patch.object(ue_asset_service, "resolve_placeable_object_path") as resolve, \
                        mock.patch.object(ui, "_setItemUEPlan", side_effect=apply), \
                        mock.patch.object(ui, "_findItemByKey", side_effect=AssertionError("linear result lookup")):
                    self.populate(ui, ["Card%03d" % i for i in range(120)])
                    self.wait_until(lambda: not ui._state_jobs and not ui._state_requests)
                timer.stop()
                self.assertEqual(len(worker_threads), 120)
                self.assertTrue(all(value != main_thread for value in worker_threads))
                self.assertEqual(set(callback_threads), {main_thread})
                resolve.assert_not_called()
                self.assertGreater(len(ticks), 15)
                self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), 0.2)
                self.assertEqual(ui.main_listWgt.item(119).ueState(), "ready")

    def test_result_backpressure_bounds_pending_callbacks_and_cancel_wakes_worker(self):
        worker = ue_asset_service.AssetStateWorker(
            5, [(str(i), str(i)) for i in range(100)], "offline", max_pending_results=3)
        calls = []
        full = threading.Event()

        def build(root, target, cancelled=None, **kwargs):
            calls.append(root)
            if len(calls) == 3:
                full.set()
            return {"asset_root": root}

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build):
            thread = threading.Thread(target=worker.run)
            thread.start()
            try:
                self.assertTrue(full.wait(1))
                # Deliberately do not process Qt events / acknowledge results.
                time.sleep(0.04)
                self.assertEqual(len(calls), 3)
                self.assertTrue(thread.is_alive())
                worker.acknowledge_result(4, "0")  # Stale acknowledgement.
                time.sleep(0.02)
                self.assertEqual(len(calls), 3)
                worker.acknowledge_result(5, "0")
                deadline = time.monotonic() + 1
                while len(calls) == 3 and time.monotonic() < deadline:
                    time.sleep(0.002)
                self.assertEqual(len(calls), 4)
            finally:
                worker.cancel()
                thread.join(1)
            self.assertFalse(thread.is_alive())

    def test_viewport_queries_match_rectangles_and_do_not_scale_with_list_size(self):
        ui = self.make_ui()
        widget = ui.main_listWgt
        with mock.patch.object(ui, "scanUEAssetStates"), \
                mock.patch.object(myWidget.Item, "requestThumbnailLoad"):
            self.populate(ui, ["Card%04d" % i for i in range(2000)])
            for list_mode in (False, True):
                widget.setIsList(list_mode)
                widget.setMode()
                widget.doItemsLayout()
                for ratio in (0, 0.31, 0.67, 1):
                    widget.verticalScrollBar().setValue(int(widget.verticalScrollBar().maximum() * ratio))
                    rect = widget.viewport().rect()
                    expected = [i for i in range(widget.count())
                                if rect.intersects(widget.visualItemRect(widget.item(i)))]
                    with mock.patch.object(widget, "item", wraps=widget.item) as item_access, \
                            mock.patch.object(widget, "visualItemRect", wraps=widget.visualItemRect) as geometry:
                        actual = widget.visibleItemRows()
                        widget.stateScanPriorityItems(include_remaining=False)
                        widget._updateVisibleItems()
                    self.assertEqual(actual, expected, (list_mode, ratio))
                    self.assertLess(item_access.call_count, 500)
                    self.assertLess(geometry.call_count, 150)

    def test_finished_queue_does_not_compute_viewport_priority_again(self):
        for scene in (False, True):
            ui = self.make_ui(scene=scene)
            with mock.patch.object(ui.main_listWgt, "stateScanPriorityItems") as priority:
                for _ in range(20):
                    ui._prioritizeStateScans()
            priority.assert_not_called()

    def test_cancelled_directory_scan_stops_before_reading_all_package_metadata(self):
        source = self.root / "Cancellable/UE/Content"
        source.mkdir(parents=True)
        for index in range(50):
            (source / ("Part%03d.uasset" % index)).write_bytes(b"package")
        calls = []
        original = ue_asset_service.os.path.getsize

        def metadata(path):
            calls.append(path)
            return original(path)

        with mock.patch.object(ue_asset_service.os.path, "getsize", side_effect=metadata):
            with self.assertRaises(ue_asset_service.ScanCancelled):
                ue_asset_service.build_import_plan(
                    str(source.parents[1]), str(self.root / "Content"),
                    cancelled=lambda: len(calls) >= 3)
        self.assertEqual(len(calls), 3)

    def test_scene_async_preflight_still_applies_selective_conflict_choices(self):
        ui = self.make_ui(scene=True)
        with mock.patch.object(ui, "scanUEAssetStates"):
            self.populate(ui, ["Scene"])
        source = self.root / "Scene/UE/Content"
        target = self.root / "Content"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "Mesh.uasset").write_bytes(b"server")
        (source / "New.uasset").write_bytes(b"new")
        (target / "Mesh.uasset").write_bytes(b"local_")
        main_thread = threading.get_ident()

        def choose(plan):
            self.assertEqual(threading.get_ident(), main_thread)
            self.assertEqual(plan["different_files"], ["Mesh.uasset"])
            plan["overwrite_files"] = []
            plan["keep_existing_files"] = ["Mesh.uasset"]
            return True

        with mock.patch.object(ui, "_chooseConflictFiles", side_effect=choose) as choices, \
                mock.patch.object(ue_asset_service, "prepare_plan_overwrites", return_value=[]), \
                mock.patch.object(ui, "_registerLoadedPlan") as register:
            ui.loadUEAsset(ui.main_listWgt.item(0))
            self.wait_until(lambda: not ui._load_check.isRunning() and ui._copy_thread is None)
        choices.assert_called_once()
        register.assert_called_once()
        self.assertEqual((target / "Mesh.uasset").read_bytes(), b"local_")
        self.assertEqual((target / "New.uasset").read_bytes(), b"new")

    def test_load_preflight_hashes_off_thread_while_ui_timer_keeps_running(self):
        main_thread = threading.get_ident()
        for scene in (False, True):
            with self.subTest(scene=scene):
                ui = self.make_ui(scene=scene)
                with mock.patch.object(ui, "scanUEAssetStates"):
                    self.populate(ui, ["Hero"])
                source = self.root / "Hero/UE/Content/Hero.uasset"
                target = self.root / "Content/Hero.uasset"
                for path in (source, target):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"same size package")
                item = ui.main_listWgt.item(0)
                item.setUESourceAvailability(True)
                ui.main_listWgt.setCurrentItem(item)
                entered, release = threading.Event(), threading.Event()
                hashing_threads, dialog_threads, ticks = [], [], []
                original_sha1 = ue_asset_service._sha1

                def slow_hash(path, cancelled=None):
                    hashing_threads.append(threading.get_ident())
                    entered.set()
                    release.wait(2)
                    return original_sha1(path, cancelled)

                def registered(*_args):
                    dialog_threads.append(threading.get_ident())

                timer = QtCore.QTimer()
                timer.timeout.connect(lambda: ticks.append(1))
                timer.start(5)
                with mock.patch.object(ue_asset_service, "_sha1", side_effect=slow_hash), \
                        mock.patch.object(ui, "_registerLoadedPlan", side_effect=registered) as register:
                    try:
                        start = time.monotonic()
                        ui.loadUEAsset(item)
                        self.assertLess(time.monotonic() - start, 0.15)
                        self.wait_until(entered.is_set)
                        self.assertFalse(ui.load_button.isEnabled())
                        with mock.patch.object(ui._load_check, "start") as duplicate:
                            ui.loadUEAsset(item)
                        duplicate.assert_not_called()
                        self.wait_until(lambda: len(ticks) >= 8)
                        register.assert_not_called()
                    finally:
                        release.set()
                    self.wait_until(lambda: not ui._load_check.isRunning())
                    register.assert_called_once()
                timer.stop()
                self.assertTrue(all(value != main_thread for value in hashing_threads))
                self.assertEqual(dialog_threads, [main_thread])

    def test_closing_during_preflight_drops_result_without_waiting_for_nas(self):
        ui = self.make_ui()
        with mock.patch.object(ui, "scanUEAssetStates"):
            self.populate(ui, ["Closing"])
        entered, release = threading.Event(), threading.Event()

        def build(*_args):
            entered.set()
            release.wait(2)
            return {"asset_root": str(self.root), "state": "ready"}

        with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build), \
                mock.patch.object(ui, "_registerLoadedPlan") as register, \
                mock.patch.object(ui, "_showMissingUEPackageDialog") as dialog:
            try:
                ui.loadUEAsset(ui.main_listWgt.item(0))
                self.wait_until(entered.is_set)
                started = time.monotonic()
                ui.shutdownThreads()
                self.assertLess(time.monotonic() - started, 0.15)
            finally:
                release.set()
            self.assertTrue(ue_asset_service._LOAD_CHECK_POOL.waitForDone(2000))
            self.app.processEvents()
        register.assert_not_called()
        dialog.assert_not_called()

    def test_closing_during_automatic_scan_does_not_wait_for_network_or_repaint(self):
        for scene in (False, True):
            with self.subTest(scene=scene):
                ui = self.make_ui(scene=scene)
                entered, release = threading.Event(), threading.Event()

                def build(*_args, **_kwargs):
                    entered.set()
                    release.wait(2)
                    return {"asset_root": "offline", "state": "ready"}

                with mock.patch.object(ue_asset_service, "build_import_plan", side_effect=build), \
                        mock.patch.object(ui, "_setItemUEPlan") as apply:
                    try:
                        self.populate(ui, ["SlowNAS"])
                        self.wait_until(entered.is_set)
                        started = time.monotonic()
                        ui.shutdownThreads()
                        self.assertLess(time.monotonic() - started, 0.15)
                    finally:
                        release.set()
                    self.wait_until(lambda: not ui._state_jobs)
                    apply.assert_not_called()
