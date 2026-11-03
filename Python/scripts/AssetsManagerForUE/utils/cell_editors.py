"""Small text and grouped-artist popups for the painted asset list."""

from PySide6 import QtCore, QtGui, QtWidgets


class _CellPopup(QtWidgets.QFrame):
    submitted = QtCore.Signal(str)
    dismissed = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Popup)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

    def showAt(self, cell, below=True):
        screen = QtGui.QGuiApplication.screenAt(cell.topLeft())
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        x = cell.left()
        y = cell.bottom() + 1 if below else cell.top()
        if screen is not None:
            available = screen.availableGeometry()
            if y + self.height() > available.bottom() + 1:
                y = cell.top() - self.height() if below else available.bottom() - self.height() + 1
            x = max(available.left(), min(x, available.right() - self.width() + 1))
            y = max(available.top(), y)
        self.move(x, y)
        self.show()
        self.line.setFocus(QtCore.Qt.OtherFocusReason)

    def cancel(self):
        self.close()

    def hideEvent(self, event):
        self.dismissed.emit()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)


class NameEditor(_CellPopup):
    def __init__(self, parent, text, width):
        super().__init__(parent)
        self._editing = True
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        self.line = QtWidgets.QLineEdit("" if text is None else str(text), self)
        self.line.setAccessibleName(u"中文名")
        self.line.installEventFilter(self)
        self.line.editingFinished.connect(self._commit)
        layout.addWidget(self.line)
        self.resize(max(80, width), 28)
        self.line.selectAll()

    def _commit(self):
        if self._editing:
            self._editing = False
            self.submitted.emit(self.line.text())
            self.close()

    def cancel(self):
        self._editing = False
        super().cancel()

    def eventFilter(self, obj, event):
        if (obj is self.line and event.type() == QtCore.QEvent.KeyPress
                and event.key() == QtCore.Qt.Key_Escape):
            self.cancel()
            return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        self._commit()
        super().hideEvent(event)


class ArtistPicker(_CellPopup):
    def __init__(self, parent, current):
        super().__init__(parent)
        self.current = current
        self.groups = {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.line = QtWidgets.QLineEdit(self)
        self.line.setPlaceholderText(u"搜索制作人…")
        self.line.setClearButtonEnabled(True)
        self.line.textChanged.connect(self._filter)
        layout.addWidget(self.line)
        self.message = QtWidgets.QLabel(u"正在读取人员列表…", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemClicked.connect(self._choose)
        self.tree.itemActivated.connect(self._choose)
        layout.addWidget(self.tree, 1)
        self.resize(230, 320)

    def setGroups(self, groups, error=""):
        self.groups = groups
        self.message.setText(error)
        self.message.setVisible(bool(error))
        self._filter()

    def _filter(self):
        self.tree.clear()
        needle = self.line.text().casefold().strip()
        count = 0
        for group, names in self.groups.items():
            matching = [name for name in names
                        if needle in name.casefold() or needle in group.casefold()]
            if not matching:
                continue
            heading = QtWidgets.QTreeWidgetItem(self.tree, [group])
            heading.setFlags(QtCore.Qt.ItemIsEnabled)
            for name in matching:
                child = QtWidgets.QTreeWidgetItem(heading, [name])
                child.setData(0, QtCore.Qt.UserRole, name)
                if name == self.current:
                    self.tree.setCurrentItem(child)
                count += 1
            heading.setExpanded(True)
        if self.groups:
            self.message.setText(u"没有匹配的人员" if not count else "")
            self.message.setVisible(not count)

    def _choose(self, item, column):
        name = item.data(0, QtCore.Qt.UserRole)
        if name is not None:
            self.submitted.emit(name)
            self.close()
