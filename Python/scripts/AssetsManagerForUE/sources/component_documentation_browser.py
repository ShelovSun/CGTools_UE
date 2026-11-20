"""Display prepared resources without filesystem access or image decoding."""
import bisect
import os
import time

from PySide6 import QtCore, QtGui, QtWidgets


class _ResourceDocument(QtGui.QTextDocument):
    def __init__(self, resources, parent):
        super(_ResourceDocument, self).__init__(parent)
        self.resources = resources

    def loadResource(self, resource_type, name):
        if resource_type == QtGui.QTextDocument.ImageResource:
            return self.resources.get(name.toString(), QtGui.QImage())
        return QtCore.QByteArray()


class MarkdownBrowser(QtWidgets.QTextBrowser):
    def __init__(self, parent=None):
        super(MarkdownBrowser, self).__init__(parent)
        self._document_owner = QtCore.QObject(self)
        self._owned_document = None
        self._animations = []
        self._image_sizes = {}
        self._fragments = []
        self._message = None
        self._hidden_at = None
        self._fit_timer = QtCore.QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fitImages)
        self._animation_timer = QtCore.QTimer(self)
        self._animation_timer.setInterval(80)
        self._animation_timer.timeout.connect(self._advanceAnimations)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet(
            "QTextBrowser{background:#181818; color:#d7d7d7; padding:12px;}"
            "QScrollBar:vertical{background:#202020; width:12px;}"
            "QScrollBar::handle:vertical{background:#555; min-height:24px;}")
        self.anchorClicked.connect(self._openLink)

    def loadResource(self, resource_type, name):
        # Also protect the initial QTextBrowser document before the first result.
        return QtGui.QImage() if resource_type == QtGui.QTextDocument.ImageResource else QtCore.QByteArray()

    def _replaceDocument(self, resources, path="", html="", message=None):
        self._fit_timer.stop()
        self._animation_timer.stop()
        self._animations = []
        self._fragments = []
        self._image_sizes = {}
        document = _ResourceDocument(resources, self._document_owner)
        document.setUndoRedoEnabled(False)
        document.setLayoutEnabled(False)
        document.setDefaultStyleSheet(
            "body{color:#d7d7d7;}h1,h2,h3,h4{color:#f0f0f0;}"
            "a{color:#58a6ff;}blockquote{color:#b8b8b8;}"
            "pre{color:#ddd; background:#242424;}code{color:#efb366;}")
        if path:
            document.setBaseUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(path) + os.path.sep))
        # Populate off-view with layout suspended: avoid a relayout per table cell.
        if message is not None:
            document.setPlainText(message)
        else:
            document.setHtml(html)
        document.setLayoutEnabled(True)
        previous = self._owned_document
        self.setDocument(document)
        self._owned_document = document
        if previous is not None:
            previous.deleteLater()
            # UE pumps processEvents() without app.exec(); deliver this object's
            # deferred deletion explicitly so old image documents cannot pile up.
            QtCore.QCoreApplication.sendPostedEvents(previous, QtCore.QEvent.DeferredDelete)
        self._message = message
        self.moveCursor(QtGui.QTextCursor.Start)

    def showMessage(self, message):
        if self._message != message:
            self._replaceDocument({}, message=message)

    def clearMarkdown(self):
        self.showMessage("")

    def showPrepared(self, payload):
        base = QtCore.QUrl.fromLocalFile(os.path.dirname(payload['path']) + os.path.sep)
        resources = {}
        now = time.monotonic()
        animations = []
        sizes = {}
        for source, image in payload.get('images', {}).items():
            raw = QtCore.QUrl(source)
            urls = (raw.toString(), base.resolved(raw).toString())
            for url in urls:
                resources[url] = image['frames'][0]
            sizes[source] = image['frames'][0].size()
            if len(image['frames']) > 1:
                ends, duration = [], 0
                for delay in image['delays']:
                    duration += delay
                    ends.append(duration)
                animations.append(dict(image=image, urls=urls, source=source,
                                       start=now, ends=ends, duration=duration, index=0))
        self._replaceDocument(resources, payload['path'], payload['html'])
        self._image_sizes = sizes
        self._animations = animations
        self._fragments = self._imageFragments()
        self._fit_timer.start(0)
        if self.isVisible() and animations:
            self._animation_timer.start()

    def _imageFragments(self):
        result = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image_format = fragment.charFormat().toImageFormat()
                    result.append((fragment.position(), fragment.length(),
                                   str(image_format.name()), image_format))
                iterator += 1
            block = block.next()
        return result

    def _advanceAnimations(self):
        if not self.isVisible():
            self._animation_timer.stop()
            return
        now, updated, playing = time.monotonic(), False, False
        for animation in self._animations:
            image = animation['image']
            elapsed = max(0, (now - animation['start']) * 1000)
            loops = image['loop_count']
            complete = loops >= 0 and elapsed >= animation['duration'] * (loops + 1)
            if complete:
                index = len(image['frames']) - 1
            else:
                playing = True
                index = bisect.bisect_right(animation['ends'], elapsed % animation['duration'])
                index = min(index, len(image['frames']) - 1)
            if index == animation['index']:
                continue
            animation['index'] = index
            for url in animation['urls']:
                self.document().addResource(QtGui.QTextDocument.ImageResource,
                                            QtCore.QUrl(url), image['frames'][index])
            for position, length, source, _ in self._fragments:
                if source == animation['source']:
                    self.document().markContentsDirty(position, length)
            updated = True
        if updated:
            self.viewport().update()
        if not playing:
            self._animation_timer.stop()

    def _fitImages(self):
        maximum_width = max(160, self.viewport().width() - 36)
        for position, length, source, image_format in self._fragments:
            natural = self._image_sizes.get(source)
            if not natural or natural.width() <= 0:
                continue
            width = min(natural.width(), maximum_width)
            height = int(round(natural.height() * float(width) / natural.width()))
            if int(image_format.width()) == width and int(image_format.height()) == height:
                continue
            image_format.setWidth(width)
            image_format.setHeight(height)
            cursor = QtGui.QTextCursor(self.document())
            cursor.setPosition(position)
            cursor.setPosition(position + length, QtGui.QTextCursor.KeepAnchor)
            cursor.mergeCharFormat(image_format)

    def resizeEvent(self, event):
        super(MarkdownBrowser, self).resizeEvent(event)
        self._fit_timer.start(80)

    def hideEvent(self, event):
        self._hidden_at = time.monotonic()
        self._fit_timer.stop()
        self._animation_timer.stop()
        super(MarkdownBrowser, self).hideEvent(event)

    def showEvent(self, event):
        super(MarkdownBrowser, self).showEvent(event)
        if self._hidden_at is not None:
            elapsed = time.monotonic() - self._hidden_at
            for animation in self._animations:
                animation['start'] += elapsed
            self._hidden_at = None
        self._fit_timer.start(0)
        if self._animations:
            self._animation_timer.start()

    def _openLink(self, url):
        if not url.scheme() and not url.path() and url.fragment():
            self.scrollToAnchor(url.fragment())
        else:
            QtGui.QDesktopServices.openUrl(self.document().baseUrl().resolved(url))
