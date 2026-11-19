"""Filmstrip, histogram and info panel."""
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPainterPath, QImage, QFont, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout, QSizePolicy

from frameline import theme
from frameline.theme import qc
from frameline.widgets import section

ZWSP = "​"


class Filmstrip(QWidget):
    """Horizontal strip of square thumbnails; the current photo is kept centred."""
    activated = Signal(int)
    visibleRange = Signal(int, int)
    CELL = 58
    GAP = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.CELL + 22)
        self.paths = []
        self.thumbs = {}
        self.current = -1
        self.offset = 0.0
        self._anim = QVariantAnimation(self, duration=220, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_offset)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = -1
        self.setMouseTracking(True)

    def set_paths(self, paths):
        self.paths = paths
        self.current = -1
        self.offset = 0.0
        self.update()

    def set_thumb(self, path, img):
        self.thumbs[path] = img
        self.update()

    def _pitch(self):
        return self.CELL + self.GAP

    def _target_offset(self, i):
        return i * self._pitch() + self.CELL / 2 - self.width() / 2

    def _clamp(self, off):
        total = len(self.paths) * self._pitch() - self.GAP
        if total <= self.width() - 24:
            return -(self.width() - total) / 2
        return max(-12, min(off, total - self.width() + 12))

    def set_current(self, i, animate=True):
        self.current = i
        target = self._clamp(self._target_offset(i))
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(float(self.offset))
            self._anim.setEndValue(float(target))
            self._anim.start()
        else:
            self._set_offset(target)
        self.update()

    def _set_offset(self, v):
        self.offset = v
        self.update()
        self.visibleRange.emit(*self.visible_indices())

    def visible_indices(self):
        p = self._pitch()
        a = max(0, int(self.offset // p) - 2)
        b = min(len(self.paths), int((self.offset + self.width()) // p) + 3)
        return a, b

    def resizeEvent(self, e):
        if self.current >= 0:
            self._set_offset(self._clamp(self._target_offset(self.current)))
        super().resizeEvent(e)

    def _index_at(self, x):
        i = int((x + self.offset) // self._pitch())
        if 0 <= i < len(self.paths) and (x + self.offset) - i * self._pitch() <= self.CELL:
            return i
        return -1

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x())
        if i >= 0:
            self.activated.emit(i)

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.setToolTip(self.paths[i].replace("\\", "/").split("/")[-1] if i >= 0 else "")
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        self._anim.stop()
        self._set_offset(self._clamp(self.offset - d * 0.8))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), qc("toolbar"))
        a, b = self.visible_indices()
        y = (self.height() - self.CELL) / 2
        for i in range(a, b):
            x = i * self._pitch() - self.offset
            r = QRectF(x, y, self.CELL, self.CELL)
            cur = i == self.current
            rr = r.adjusted(-6, -6, 6, 6) if cur else r
            if cur:
                rr = QRectF(r.center().x() - (self.CELL + 8) / 2, y - 4, self.CELL + 8, self.CELL + 8)
            path = QPainterPath()
            path.addRoundedRect(rr, 7, 7)
            p.save()
            p.setClipPath(path)
            img = self.thumbs.get(self.paths[i])
            if img is not None and not img.isNull():
                # centre-crop to a square
                s = min(img.width(), img.height())
                src = QRectF((img.width() - s) / 2, (img.height() - s) / 2, s, s)
                p.drawImage(rr, img, src)
            else:
                p.fillRect(rr, qc("card"))
            if not cur:
                p.fillRect(rr, QColor(0, 0, 0, 70 if self._hover != i else 20))
            p.restore()
            if cur:
                p.setPen(QPen(QColor(255, 255, 255) if theme.T["name"] == "dark" else qc("accent"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rr.adjusted(1, 1, -1, -1), 7, 7)
        p.setPen(qc("hairline"))
        p.drawLine(0, 0, self.width(), 0)
        p.end()


class Histogram(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(92)
        self.h = None

    def set_image(self, img):
        if img is None or img.isNull():
            self.h = None
            self.update()
            return
        small = img.scaled(320, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        small = small.convertToFormat(QImage.Format.Format_RGB888)
        w, h, bpl = small.width(), small.height(), small.bytesPerLine()
        arr = np.frombuffer(small.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 3].reshape(-1, 3)
        hist = [np.bincount(arr[:, c], minlength=256).astype(np.float32) for c in range(3)]
        peak = max(float(np.percentile(np.concatenate(hist), 99.5)), 1.0)
        self.h = [np.minimum(x / peak, 1.0) for x in hist]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc("field"))
        p.drawRoundedRect(r, 8, 8)
        if self.h is None:
            p.end()
            return
        inner = r.adjusted(6, 8, -6, -6)
        dark = theme.T["name"] == "dark"
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus if dark
                             else QPainter.CompositionMode.CompositionMode_Multiply)
        cols = ([QColor(255, 69, 58, 150), QColor(48, 209, 88, 150), QColor(10, 132, 255, 170)] if dark else
                [QColor(255, 140, 130), QColor(140, 230, 160), QColor(130, 180, 255)])
        for c, hh in zip(cols, self.h):
            path = QPainterPath(QPointF(inner.left(), inner.bottom()))
            for i in range(256):
                path.lineTo(inner.left() + inner.width() * i / 255, inner.bottom() - inner.height() * float(hh[i]))
            path.lineTo(inner.right(), inner.bottom())
            path.closeSubpath()
            p.setBrush(c)
            p.drawPath(path)
        p.end()


class InfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setMinimumWidth(270)
        self.setMaximumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        self.title = QLabel(objectName="Title")
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.title)
        self.folder = QLabel(objectName="Tertiary")
        self.folder.setWordWrap(True)
        self.folder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.folder)
        lay.addSpacing(6)
        self.hist = Histogram()
        lay.addWidget(self.hist)
        self.file_sec = section("File")
        lay.addWidget(self.file_sec)
        self.file_grid = QGridLayout()
        self.file_grid.setHorizontalSpacing(10)
        self.file_grid.setVerticalSpacing(5)
        lay.addLayout(self.file_grid)
        self.cam_sec = section("Camera")
        lay.addWidget(self.cam_sec)
        self.cam_grid = QGridLayout()
        self.cam_grid.setHorizontalSpacing(10)
        self.cam_grid.setVerticalSpacing(5)
        lay.addLayout(self.cam_grid)
        lay.addStretch(1)
        self.hint = QLabel("← → browse  ·  double-click for 100%  ·  F5 slideshow", objectName="Tertiary")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

    @staticmethod
    def _fill(grid, items):
        while grid.count():
            w = grid.takeAt(0).widget()
            if w:
                w.hide()          # deleteLater alone leaves it painted until the next event-loop pass
                w.setParent(None)
                w.deleteLater()
        for r, (k, v) in enumerate(items):
            a = QLabel(k, objectName="Secondary")
            a.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            b = QLabel(str(v))
            b.setWordWrap(True)
            b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(a, r, 0)
            grid.addWidget(b, r, 1)
        grid.setColumnStretch(1, 1)

    def set_info(self, info, exif):
        if not info:
            self.title.setText("No photo")
            self.folder.setText("")
            self._fill(self.file_grid, [])
            self._fill(self.cam_grid, [])
            self.cam_sec.hide()
            return
        self.title.setText(ZWSP.join(info.get("Name", "")))
        self.folder.setText(info.get("Folder", "").replace("\\", "\\" + ZWSP).replace("/", "/" + ZWSP))
        rows = [(k, v) for k, v in info.items() if k not in ("Name", "Folder")]
        self._fill(self.file_grid, rows)
        self._fill(self.cam_grid, list(exif.items()))
        self.cam_sec.setVisible(bool(exif))
