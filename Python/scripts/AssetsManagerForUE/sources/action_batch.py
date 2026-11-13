"""Serial action-library operations, advanced only after the current item finishes."""

import os
from contextlib import ExitStack, contextmanager

from PySide6 import QtCore


class ActionBatch(QtCore.QObject):
    itemRequested = QtCore.Signal(str, str)
    finished = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super(ActionBatch, self).__init__(parent)
        self.active = False
        self.operation = ""
        self.current = ""
        self.results = []
        self.total = 0
        self._auto_advance = True
        self._paths = []
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)

    def start(self, operation, paths, auto_advance=True):
        if self.active:
            return False
        unique, seen = [], set()
        for path in paths:
            if not path:
                continue
            path = os.path.normpath(str(path)).replace("\\", "/")
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        if not unique:
            return False
        self.operation = operation
        self._paths = unique
        self.total = len(unique)
        self._auto_advance = auto_advance
        self.results = []
        self.current = ""
        self.active = True
        if self._auto_advance:
            self._timer.start(0)
        return True

    def nextItem(self):
        """Advance a synchronous import batch inside its single slow-task scope."""
        self._next()

    def nextPath(self):
        return self._paths[0] if self._paths else ""

    def _next(self):
        if not self.active or self.current:
            return
        if not self._paths:
            result = {"operation": self.operation, "items": list(self.results)}
            self.active = False
            self.finished.emit(result)
            return
        self.current = self._paths.pop(0)
        self.itemRequested.emit(self.operation, self.current)

    def finishItem(self, state, message=""):
        if not self.active or not self.current:
            return
        self.results.append({"path": self.current, "state": state, "message": str(message)})
        self.current = ""
        if self._auto_advance:
            self._timer.start(0)

    def skipPending(self, message, state="skipped"):
        """Cancel between files; keep completed results and report unstarted files."""
        if not self.active or self.current:
            return
        self._timer.stop()
        self.results.extend({"path": path, "state": state, "message": message}
                            for path in self._paths)
        self._paths = []
        self._next()

    def cancel(self):
        self._timer.stop()
        self.active = False
        self.current = ""
        self._paths = []


@contextmanager
def suspend_window_callbacks(owner):
    """Native Windows dispatch can run Qt timers even without processEvents()."""
    window = owner.window()
    enabled, updates = window.isEnabled(), window.updatesEnabled()
    timers = [(timer, timer.interval()) for timer in window.findChildren(QtCore.QTimer)
              if timer.thread() == window.thread() and timer.isActive()]
    try:
        for timer, _interval in timers:
            timer.stop()
        window.setUpdatesEnabled(False)
        window.setEnabled(False)
        yield
    finally:
        window.setEnabled(enabled)
        window.setUpdatesEnabled(updates)
        for timer, interval in timers:
            try:
                timer.start(interval)
            except RuntimeError:
                pass  # A closed/deleted child must not prevent other timers resuming.


class ActionImportProgress:
    """One native UE modal progress scope for the complete synchronous batch."""

    def __init__(self, owner, engine, total):
        self.window = owner.window()
        self.engine = engine
        self.total = total
        self.task = None
        self._stack = ExitStack()

    def __enter__(self):
        from ue_qt_host import suspend_event_pump
        try:
            self._stack.enter_context(suspend_event_pump())
            self._stack.enter_context(suspend_window_callbacks(self.window))
            factory = getattr(self.engine, "ScopedSlowTask", None)
            if factory is not None:
                self.task = self._stack.enter_context(factory(self.total, u"批量导入动作 FBX"))
                self.task.make_dialog(True)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def advance(self, index, path):
        if self.task is not None:
            self.task.enter_progress_frame(1, u"[{0}/{1}] {2}".format(index, self.total, os.path.basename(path)))

    def shouldCancel(self):
        return self.task is not None and self.task.should_cancel()

    def __exit__(self, exc_type, exc, tb):
        return self._stack.__exit__(exc_type, exc, tb)
