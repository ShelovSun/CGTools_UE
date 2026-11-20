"""Bounded preparation of component Markdown, entirely off the GUI thread."""
from collections import OrderedDict
import math
import os
import time
from html import escape

from PySide6 import QtCore, QtGui

MAX_TEXT_BYTES = 128 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
MAX_IMAGE_SIDE = 1024
MAX_IMAGES = 24
MAX_HTML_BYTES = 192 * 1024
MAX_DOCUMENT_BLOCKS = 600
MAX_GIF_FRAMES = 120
DOCUMENT_IMAGE_BUDGET = 24 * 1024 * 1024


class Cancelled(Exception):
    pass


class _Document(QtGui.QTextDocument):
    def loadResource(self, resource_type, name):
        # Parsing must never trigger implicit file or network reads.
        return QtGui.QImage() if resource_type == QtGui.QTextDocument.ImageResource else QtCore.QByteArray()


def local_image_path(source, base_folder):
    url = QtCore.QUrl(source)
    if url.isLocalFile():
        return os.path.normpath(url.toLocalFile())
    normalized = str(source).replace('/', os.path.sep)
    if os.path.isabs(normalized):
        return os.path.normpath(normalized)
    if url.scheme():
        return ""
    decoded = QtCore.QUrl.fromPercentEncoding(str(source).encode("utf-8"))
    decoded = str(decoded).split("#", 1)[0].split("?", 1)[0]
    return os.path.normpath(os.path.join(base_folder, decoded.replace("/", os.path.sep)))


def image_sources(document):
    seen = set()
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                name = str(fragment.charFormat().toImageFormat().name())
                if name not in seen:
                    seen.add(name)
                    yield name
            iterator += 1
        block = block.next()


def decode_markdown(raw, truncated=False):
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            if truncated and exc.end == len(raw):
                try:
                    return raw[:exc.start].decode(encoding)
                except UnicodeDecodeError:
                    pass
    return raw.decode('utf-8', errors='replace')


def _code_font_fallback(document):
    """Avoid slow GUI font discovery for Chinese inside Western code fonts."""
    changes = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and any(ord(char) > 127 for char in fragment.text()):
                families = fragment.charFormat().font().families()
                if any(name in ('Courier New', 'Consolas', 'monospace') for name in families):
                    changes.append((fragment.position(), fragment.length()))
            iterator += 1
        block = block.next()
    cursor = QtGui.QTextCursor(document)
    for position, length in changes:
        cursor.setPosition(position)
        cursor.setPosition(position + length, QtGui.QTextCursor.KeepAnchor)
        fmt = QtGui.QTextCharFormat()
        fmt.setFontFamilies(['Microsoft YaHei UI'])
        cursor.mergeCharFormat(fmt)


def _image(path, budget, check):
    check()
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        return None
    buffer = QtCore.QBuffer()
    buffer.setData(raw)
    buffer.open(QtCore.QIODevice.ReadOnly)
    reader = QtGui.QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    width, height = size.width(), size.height()
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        return None
    count = reader.imageCount() if reader.supportsAnimation() else 1
    animated = 1 < count <= MAX_GIF_FRAMES
    frames_to_read = count if animated else 1
    ratio = min(1.0, MAX_IMAGE_SIDE / float(max(width, height)),
                math.sqrt(max(0, budget) / float(4 * width * height * frames_to_read)))
    # Prefer a readable still preview over a tiny, long animation.
    if animated and max(width, height) * ratio < min(160, max(width, height)):
        animated, frames_to_read = False, 1
        ratio = min(1.0, MAX_IMAGE_SIDE / float(max(width, height)),
                    math.sqrt(max(0, budget) / float(4 * width * height)))
    if ratio <= 0:
        return None
    scaled = QtCore.QSize(max(1, int(width * ratio)), max(1, int(height * ratio)))
    reader.setScaledSize(scaled)
    frames, delays, cost = [], [], 0
    for _ in range(frames_to_read):
        check()
        image = reader.read()
        if image.isNull():
            break
        if image.width() > scaled.width() or image.height() > scaled.height():
            image = image.scaled(scaled, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        frame_cost = image.sizeInBytes()
        if cost + frame_cost > budget:
            break
        frames.append(image)
        delays.append(max(20, reader.nextImageDelay()))
        cost += frame_cost
    if not frames:
        return None
    if len(frames) != frames_to_read:
        frames, delays = frames[:1], delays[:1]
        cost = frames[0].sizeInBytes()
    return dict(frames=frames, delays=delays, cost=cost,
                still_animation=reader.supportsAnimation() and len(frames) == 1,
                loop_count=reader.loopCount())


def prepare(folder, cancelled=lambda: False):
    """Only enumerate this component root; return strings and bounded QImages."""
    def check():
        if cancelled():
            raise Cancelled()
    check()
    documents = []
    with os.scandir(folder) as entries:
        for entry in entries:
            check()
            if entry.name.lower().endswith('.md') and entry.is_file():
                documents.append(entry.path)
    if not documents:
        return dict(status='missing', message='该组件暂无使用说明。', path='', cost=128)
    path = min(documents, key=lambda value: os.path.basename(value).lower())
    check()
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_TEXT_BYTES + 1)
    truncated = len(raw) > MAX_TEXT_BYTES
    text = decode_markdown(raw[:MAX_TEXT_BYTES], truncated)
    document = _Document()
    font = QtGui.QFont('Microsoft YaHei UI')
    font.setPixelSize(14)
    document.setDefaultFont(font)
    document.setMarkdown(text)
    _code_font_fallback(document)
    html = document.toHtml()
    # Large tables/code listings can otherwise make GUI HTML layout expensive.
    if document.blockCount() > MAX_DOCUMENT_BLOCKS or len(html.encode('utf-8')) > MAX_HTML_BYTES:
        preview = '\n'.join(document.toPlainText().splitlines()[:240])[:16000]
        html = ('<html><body style="font-size:14px"><p>'
                + escape(preview).replace('\n', '<br/>')
                + '</p><p>说明较长，外部打开可查看完整内容。</p></body></html>')
        check()
        return dict(status='ready', path=path, html=html, images={}, cost=len(html.encode('utf-8')))
    images, used, limited = {}, 0, False
    still_animation = False
    for index, name in enumerate(image_sources(document)):
        check()
        if index >= MAX_IMAGES:
            limited = True
            break
        image_path = local_image_path(name, os.path.dirname(path))
        if not image_path:
            continue
        try:
            image = _image(image_path, DOCUMENT_IMAGE_BUDGET - used, check)
        except (OSError, ValueError):
            image = None
        if image:
            images[name] = image
            used += image['cost']
            still_animation = still_animation or image['still_animation']
        else:
            limited = True
    check()
    notes = []
    if truncated:
        notes.append('说明较长，外部打开可查看完整内容。')
    if limited:
        notes.append('部分图片暂不显示，外部打开可查看完整内容。')
    if still_animation:
        notes.append('较长的动图显示静态预览，外部打开可查看完整动画。')
    if notes:
        html = html.replace('</body>', '<p>' + '<br/>'.join(notes) + '</p></body>')
    return dict(status='ready', path=path, html=html, images=images,
                cost=used + len(html.encode('utf-8')))


class DocumentCache:
    """GUI-owned LRU: bounded memory and no stat/read on cache hits."""
    def __init__(self, max_entries=8, max_bytes=48 * 1024 * 1024, ttl=60):
        self.max_entries, self.max_bytes, self.ttl = max_entries, max_bytes, ttl
        self._entries = OrderedDict()
        self.bytes = 0

    def clear(self):
        self._entries.clear()
        self.bytes = 0

    def get(self, key):
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        timestamp, payload = entry
        if time.monotonic() - timestamp >= self.ttl:
            self.bytes -= payload['cost']
            return None
        self._entries[key] = entry
        return payload

    def put(self, key, payload):
        previous = self._entries.pop(key, None)
        if previous:
            self.bytes -= previous[1]['cost']
        cost = payload['cost']
        if cost > self.max_bytes:
            return
        self._entries[key] = (time.monotonic(), payload)
        self.bytes += cost
        while len(self._entries) > self.max_entries or self.bytes > self.max_bytes:
            _, (_, removed) = self._entries.popitem(last=False)
            self.bytes -= removed['cost']
