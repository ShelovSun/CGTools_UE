"""Local search phase timings and a native Python timeout dump for sporadic UI hangs."""

import faulthandler
import json
import os
from pathlib import Path
import tempfile
import time

from PySide6 import QtCore


_ACTIVE = None


def log_path():
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "CGTools/AssetsManagerForUE/diagnostics" / ("search-%s.log" % os.getpid())


class SearchTrace:
    """Keep the dump file open until the UI has processed events after rebuilding.

    The native faulthandler timer can dump Python stacks even when a C extension
    blocks while holding the GIL. It never exits/kills UE or invokes UE/Qt APIs.
    """

    def __init__(self, keyword, rows, cards, timeout=5.0, path=None):
        global _ACTIVE
        self._file = None
        self._armed = False
        self._closed = False
        self._destroy_connection = None
        self._start = time.perf_counter()
        self._phase_start = self._start
        self._phase = "begin"
        self.path = Path(path) if path is not None else log_path()
        if _ACTIVE is not None:
            _ACTIVE.finish()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 5 * 1024 * 1024:
                os.replace(self.path, self.path.with_suffix(".previous.log"))
            self._file = self.path.open("a", encoding="utf-8")
            self._write({"event": "begin", "keyword": keyword, "source_rows": rows,
                         "old_cards": cards, "timeout_seconds": timeout,
                         "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            _ACTIVE = self
            faulthandler.dump_traceback_later(timeout, repeat=False, file=self._file)
            self._armed = True
            print("[AssetsManager] 搜索开始 keyword={!r}, rows={}, cards={}, 诊断={}".format(
                keyword, rows, cards, self.path))
        except Exception:
            # Diagnostics must never prevent a search (e.g. local disk permissions).
            self.finish()

    def _write(self, data):
        if self._file is not None:
            try:
                self._file.write(json.dumps(data, ensure_ascii=False) + "\n")
                self._file.flush()
            except OSError:
                pass

    def mark(self, phase):
        if self._closed:
            return
        now = time.perf_counter()
        self._write({"event": "phase", "phase": phase,
                     "previous_phase": self._phase,
                     "previous_ms": round((now - self._phase_start) * 1000, 3),
                     "elapsed_ms": round((now - self._start) * 1000, 3)})
        self._phase, self._phase_start = phase, now

    def finish_after_events(self, owner):
        if self._closed:
            return
        self.mark("waiting_for_ui_events")
        self._destroy_connection = owner.destroyed.connect(self._owner_destroyed)
        # Keep the watchdog active for the immediate layout/paint callbacks too.
        QtCore.QTimer.singleShot(200, self.finish)

    def _owner_destroyed(self, *_args):
        self._destroy_connection = None
        self.finish()

    def finish(self, *_args):
        global _ACTIVE
        if self._closed:
            return
        if _ACTIVE is self:
            if self._armed:
                faulthandler.cancel_dump_traceback_later()
            _ACTIVE = None
        self.mark("complete")
        self._closed = True
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        try:
            if self._destroy_connection is not None:
                QtCore.QObject.disconnect(self._destroy_connection)
        except RuntimeError:
            pass
        self._destroy_connection = None
