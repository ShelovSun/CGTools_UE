"""Read and compose asset card images on a worker; never create QPixmap here."""

from PySide6 import QtCore, QtGui

from .fbxpreview.am_surface_variants import (
    discoverSurfaceVariants, isSceneIconPath, supportsSurfaceVariants)


def supports_surface_icons(icon_path, asset_name):
    """Use the same asset/scene rules as the right-hand preview."""
    return supportsSurfaceVariants(icon_path, asset_name)


def _read_image(path, edge):
    reader = QtGui.QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > edge:
        reader.setScaledSize(size.scaled(edge, edge, QtCore.Qt.KeepAspectRatio))
    image = reader.read()
    if not image.isNull() and max(image.width(), image.height()) > edge:
        image = image.scaled(edge, edge, QtCore.Qt.KeepAspectRatio,
                             QtCore.Qt.SmoothTransformation)
    return image


def surface_icon_rects(edge, count):
    """Maya layout: first skin on the left, remaining skins stacked on the right."""
    if count < 2:
        return [QtCore.QRect(0, 0, edge, edge)]
    gap = min(max(2, int(round(edge * 0.018))), edge // max(1, count - 1))
    right_width = max(24, int(round(edge * 0.31)))
    left_width = max(1, edge - right_width - gap)
    rects = [QtCore.QRect(0, 0, left_width, edge)]
    available = max(1, edge - gap * (count - 2))
    for index in range(count - 1):
        top = available * index // (count - 1) + gap * index
        bottom = available * (index + 1) // (count - 1) + gap * index
        rects.append(QtCore.QRect(left_width + gap, top, right_width, max(1, bottom - top)))
    return rects


def _draw_cover(painter, rect, image):
    """Crop at the center without stretching or retaining per-skin scaled copies."""
    scale = max(rect.width() / image.width(), rect.height() / image.height())
    width, height = rect.width() / scale, rect.height() / scale
    source = QtCore.QRectF((image.width() - width) / 2, (image.height() - height) / 2,
                          width, height)
    painter.drawImage(QtCore.QRectF(rect), image, source)


def load_card_image(icon_path, asset_name="", edge=512, should_load=None):
    """Return a bounded QImage, reading only this asset's Icon/FBX directories.

    Shared discovery pairs asset skins or scene model names with FBX files and
    sorts naturally. A scene with one pair uses that model's image; ordinary
    assets retain their database icon.
    No network IO or decoding is performed by the card's paint function.
    """
    edge = max(32, int(edge))
    wanted = should_load or (lambda: True)
    if not icon_path or not wanted():
        return None
    variants = []
    if supports_surface_icons(icon_path, asset_name):
        variants = discoverSurfaceVariants(icon_path, asset_name)
    if not wanted():
        return None
    if len(variants) < 2:
        if variants and isSceneIconPath(icon_path):
            return _read_image(variants[0][1], edge)
        return _read_image(icon_path, edge)

    result = QtGui.QImage(edge, edge, QtGui.QImage.Format_ARGB32_Premultiplied)
    result.fill(QtGui.QColor(31, 32, 35))
    painter = QtGui.QPainter(result)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    fallback = None
    loaded = 0
    try:
        for rect, (_skin, path, _fbx) in zip(surface_icon_rects(edge, len(variants)), variants):
            if not wanted():
                return None
            image = _read_image(path, edge)
            if image.isNull():
                if fallback is None:
                    fallback = _read_image(icon_path, edge)
                image = fallback
            else:
                loaded += 1
            if image is not None and not image.isNull():
                _draw_cover(painter, rect, image)
    finally:
        painter.end()
    return result if loaded else fallback
