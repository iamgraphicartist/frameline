"""The image viewer: zoom/pan, A/B compare, onion skin, guides, annotation drawing."""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QSize
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QImage, QPolygonF,
                           QFontMetricsF, QCursor)
from PySide6.QtWidgets import QWidget, QInputDialog

from . import theme
from .theme import T, qc
from . import icons


def draw_strokes(p, strokes, opacity=1.0):
    """Paint annotation strokes. Painter must already be in image coordinates."""
    for st in strokes:
        col = QColor(st["c"])
        col.setAlphaF(col.alphaF() * opacity)
        w = st["w"]
        pen = QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pts = [QPointF(x, y) for x, y in st["p"]]
        t = st["t"]
        if not pts:
            continue
        if t == "pen":
            if len(pts) == 1:
                p.setBrush(col)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pts[0], w / 2, w / 2)
                continue
            path = QPainterPath(pts[0])
            for i in range(1, len(pts) - 1):
                mid = (pts[i] + pts[i + 1]) / 2
                path.quadTo(pts[i], mid)
            path.lineTo(pts[-1])
            p.drawPath(path)
        elif t in ("line", "arrow") and len(pts) >= 2:
            a, b = pts[0], pts[-1]
            p.drawLine(a, b)
            if t == "arrow":
                ang = math.atan2(b.y() - a.y(), b.x() - a.x())
                L = max(w * 4.0, 12)
                for da in (2.6, -2.6):
                    p.drawLine(b, QPointF(b.x() + L * math.cos(ang + da), b.y() + L * math.sin(ang + da)))
        elif t in ("rect", "ellipse") and len(pts) >= 2:
            r = QRectF(pts[0], pts[-1]).normalized()
            if t == "rect":
                p.drawRoundedRect(r, w, w)
            else:
                p.drawEllipse(r)
        elif t == "text":
            f = QFont(theme.ui_family())
            f.setPixelSize(max(8, int(w * 7)))
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            # soft shadow for legibility
            p.setPen(QColor(0, 0, 0, int(160 * opacity)))
            p.drawText(pts[0] + QPointF(w * 0.25, w * 0.25), st.get("s", ""))
            p.setPen(col)
            p.drawText(pts[0], st.get("s", ""))


class Viewer(QWidget):
    strokeFinished = Signal(dict)
    eraseAt = Signal(float, float, float)
    zoomChanged = Signal()
    pixelInfo = Signal(str)
    filesDropped = Signal(list)
    importRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(320, 200)
        self.img_a = None
        self.img_b = None
        self.size_a = QSize(0, 0)
        self.size_b = QSize(0, 0)
        self.label_a = ""
        self.label_b = ""
        self.ghosts = []           # [(QImage, opacity)]
        self.strokes = []
        self.ghost_strokes = []
        self.zoom = 1.0
        self.fit = True
        self.pan = QPointF(0, 0)
        self.compare = "off"
        self.wipe = 0.5
        self.wipe_vertical = True
        self.overlay_opacity = 0.5
        self.bg_mode = "dark"
        self.guides = set()
        self.mask_aspect = None
        self.hud = True
        self.hud_text = ""
        self.tool = None
        self.color = "#FF453A"
        self.brush = 4
        self.empty = True
        self._drag = None
        self._drawing = None
        self._drop_hover = False
        self._space = False
        self._checker = None

    # ------------------------------------------------------------------ geometry
    def scale(self, size=None, pane=None):
        size = size or self.size_a
        pane = pane or self._pane_rects()[0]
        if size.width() <= 0 or size.height() <= 0:
            return 1.0
        if self.fit:
            return min(pane.width() / size.width(), pane.height() / size.height())
        return self.zoom

    def _pane_rects(self):
        r = QRectF(self.rect())
        if self.compare == "side" and self.img_b is not None:
            h = r.width() / 2
            return [QRectF(r.x(), r.y(), h, r.height()), QRectF(r.x() + h, r.y(), h, r.height())]
        if self.compare == "stack" and self.img_b is not None:
            h = r.height() / 2
            return [QRectF(r.x(), r.y(), r.width(), h), QRectF(r.x(), r.y() + h, r.width(), h)]
        return [r, r]

    def image_rect(self, size=None, pane=None):
        size = size or self.size_a
        pane = pane or self._pane_rects()[0]
        s = self.scale(size, pane)
        w, h = size.width() * s, size.height() * s
        return QRectF(pane.center().x() - w / 2 + self.pan.x(), pane.center().y() - h / 2 + self.pan.y(), w, h)

    def to_image(self, pos):
        r = self.image_rect()
        s = self.scale()
        return QPointF((pos.x() - r.x()) / s, (pos.y() - r.y()) / s)

    def effective_zoom(self):
        return self.scale()

    def set_zoom(self, z, anchor=None):
        old = self.scale()
        z = max(0.02, min(64.0, z))
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        r = self.image_rect()
        ix = (anchor.x() - r.x()) / old
        iy = (anchor.y() - r.y()) / old
        self.fit = False
        self.zoom = z
        r2 = self.image_rect()
        self.pan += QPointF(anchor.x() - (r2.x() + ix * z), anchor.y() - (r2.y() + iy * z))
        self.zoomChanged.emit()
        self.update()

    def fit_view(self):
        self.fit = True
        self.pan = QPointF(0, 0)
        self.zoomChanged.emit()
        self.update()

    def actual_size(self):
        self.pan = QPointF(0, 0)
        self.fit = False
        self.zoom = 1.0 / max(1.0, self.devicePixelRatioF()) if False else 1.0
        self.zoomChanged.emit()
        self.update()

    # ------------------------------------------------------------------ painting
    def _checker_brush(self):
        if self._checker is None:
            img = QImage(16, 16, QImage.Format.Format_RGB32)
            img.fill(QColor(70, 70, 74))
            p = QPainter(img)
            p.fillRect(0, 0, 8, 8, QColor(98, 98, 102))
            p.fillRect(8, 8, 8, 8, QColor(98, 98, 102))
            p.end()
            self._checker = QBrush(img)
        return self._checker

    def _bg_color(self):
        return {"black": QColor(0, 0, 0), "grey": QColor(92, 92, 96), "white": QColor(235, 235, 238)}.get(
            self.bg_mode, qc("viewer"))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self._bg_color() if self.bg_mode != "checker" else qc("viewer"))
        if self.img_a is None and self.empty:
            self._paint_empty(p)
            p.end()
            return
        panes = self._pane_rects()
        ra = self.image_rect(self.size_a, panes[0])
        s = self.scale()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 2.0)

        def backdrop(r):
            if self.bg_mode == "checker":
                p.fillRect(r, self._checker_brush())

        mode = self.compare if self.img_b is not None else "off"
        if mode in ("side", "stack"):
            rb = self.image_rect(self.size_b, panes[1])
            p.save()
            p.setClipRect(panes[0])
            backdrop(ra)
            if self.img_a is not None:
                p.drawImage(ra, self.img_a)
            self._paint_ghosts(p, ra)
            p.restore()
            p.save()
            p.setClipRect(panes[1])
            backdrop(rb)
            p.drawImage(rb, self.img_b)
            p.restore()
            p.setPen(QPen(QColor(0, 0, 0, 200), 2))
            if mode == "side":
                p.drawLine(QPointF(panes[1].x(), 0), QPointF(panes[1].x(), self.height()))
            else:
                p.drawLine(QPointF(0, panes[1].y()), QPointF(self.width(), panes[1].y()))
            self._pill(p, QPointF(panes[0].x() + 12, panes[0].y() + 12), "A  " + self.label_a)
            self._pill(p, QPointF(panes[1].x() + 12, panes[1].y() + 12), "B  " + self.label_b)
        else:
            backdrop(ra)
            if self.img_a is not None:
                p.drawImage(ra, self.img_a)
            self._paint_ghosts(p, ra)
            if mode != "off":
                rb = self._fit_into(self.size_b, ra)
                if mode == "wipe":
                    p.save()
                    if self.wipe_vertical:
                        x = ra.x() + ra.width() * self.wipe
                        p.setClipRect(QRectF(x, ra.y() - 1, ra.right() - x + 1, ra.height() + 2))
                    else:
                        y = ra.y() + ra.height() * self.wipe
                        p.setClipRect(QRectF(ra.x() - 1, y, ra.width() + 2, ra.bottom() - y + 1))
                    if self.bg_mode == "checker":
                        p.fillRect(ra, self._checker_brush())
                    else:
                        p.fillRect(ra, self._bg_color())
                    p.drawImage(rb, self.img_b)
                    p.restore()
                    self._paint_wipe_handle(p, ra)
                elif mode == "overlay":
                    p.setOpacity(self.overlay_opacity)
                    p.drawImage(rb, self.img_b)
                    p.setOpacity(1.0)
                elif mode == "diff":
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
                    p.drawImage(rb, self.img_b)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                if mode == "wipe":
                    if self.wipe_vertical:
                        self._pill(p, QPointF(ra.x() + 12, ra.y() + 12), "A  " + self.label_a)
                        self._pill(p, QPointF(ra.right() - 12, ra.y() + 12), "B  " + self.label_b, right=True)
                    else:
                        self._pill(p, QPointF(ra.x() + 12, ra.y() + 12), "A  " + self.label_a)
                        self._pill(p, QPointF(ra.x() + 12, ra.bottom() - 36), "B  " + self.label_b)

        self._paint_guides(p, ra)

        # annotations
        p.save()
        p.setClipRect(QRectF(self.rect()))
        p.translate(ra.topLeft())
        p.scale(s, s)
        if self.ghost_strokes and not self.strokes:
            draw_strokes(p, self.ghost_strokes, 0.28)
        draw_strokes(p, self.strokes)
        if self._drawing:
            draw_strokes(p, [self._drawing])
        p.restore()

        if self.hud and self.hud_text:
            self._pill(p, QPointF(self.width() - 12, self.height() - 34), self.hud_text, right=True, mono=True)
        if not self.fit or self._drag == "zooming":
            self._pill(p, QPointF(12, self.height() - 34), f"{s * 100:.0f}%")
        if self._drop_hover:
            self._paint_drop(p)
        p.end()

    def _fit_into(self, size, r):
        if size.width() <= 0 or size.height() <= 0:
            return r
        s = min(r.width() / size.width(), r.height() / size.height())
        w, h = size.width() * s, size.height() * s
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def _paint_ghosts(self, p, r):
        for img, op in self.ghosts:
            p.setOpacity(op)
            p.drawImage(r, img)
        p.setOpacity(1.0)

    def _paint_wipe_handle(self, p, ra):
        col = QColor(255, 255, 255, 235)
        p.setPen(QPen(col, 1.5))
        if self.wipe_vertical:
            x = ra.x() + ra.width() * self.wipe
            p.drawLine(QPointF(x, ra.y()), QPointF(x, ra.bottom()))
            c = QPointF(x, ra.center().y())
        else:
            y = ra.y() + ra.height() * self.wipe
            p.drawLine(QPointF(ra.x(), y), QPointF(ra.right(), y))
            c = QPointF(ra.center().x(), y)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(col)
        p.drawEllipse(c, 13, 13)
        p.setBrush(QColor(40, 40, 44))
        p.setPen(Qt.PenStyle.NoPen)
        a = 4.5
        if self.wipe_vertical:
            p.drawPolygon(QPolygonF([c + QPointF(-8, 0), c + QPointF(-3, -a), c + QPointF(-3, a)]))
            p.drawPolygon(QPolygonF([c + QPointF(8, 0), c + QPointF(3, -a), c + QPointF(3, a)]))
        else:
            p.drawPolygon(QPolygonF([c + QPointF(0, -8), c + QPointF(-a, -3), c + QPointF(a, -3)]))
            p.drawPolygon(QPolygonF([c + QPointF(0, 8), c + QPointF(-a, 3), c + QPointF(a, 3)]))

    def _paint_guides(self, p, r):
        if self.mask_aspect:
            ar = r.width() / max(1, r.height())
            inner = QRectF(r)
            if self.mask_aspect > ar:
                h = r.width() / self.mask_aspect
                inner = QRectF(r.x(), r.center().y() - h / 2, r.width(), h)
            else:
                w = r.height() * self.mask_aspect
                inner = QRectF(r.center().x() - w / 2, r.y(), w, r.height())
            m = QColor(0, 0, 0, 215)
            p.fillRect(QRectF(r.x(), r.y(), r.width(), inner.y() - r.y()), m)
            p.fillRect(QRectF(r.x(), inner.bottom(), r.width(), r.bottom() - inner.bottom()), m)
            p.fillRect(QRectF(r.x(), inner.y(), inner.x() - r.x(), inner.height()), m)
            p.fillRect(QRectF(inner.right(), inner.y(), r.right() - inner.right(), inner.height()), m)
            r = inner
        pen = QPen(QColor(255, 255, 255, 120), 1, Qt.PenStyle.DashLine)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if "safe" in self.guides:
            p.setPen(pen)
            for f in (0.9, 0.8):
                w, h = r.width() * f, r.height() * f
                p.drawRect(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h))
        if "thirds" in self.guides:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for i in (1, 2):
                x = r.x() + r.width() * i / 3
                y = r.y() + r.height() * i / 3
                p.drawLine(QPointF(x, r.y()), QPointF(x, r.bottom()))
                p.drawLine(QPointF(r.x(), y), QPointF(r.right(), y))
        if "center" in self.guides:
            p.setPen(QPen(QColor(255, 255, 255, 170), 1))
            c = r.center()
            p.drawLine(c + QPointF(-12, 0), c + QPointF(12, 0))
            p.drawLine(c + QPointF(0, -12), c + QPointF(0, 12))

    def _pill(self, p, pos, text, right=False, mono=False):
        f = theme.font(11.5, QFont.Weight.Medium, mono=mono)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 20
        h = 24
        x = pos.x() - w if right else pos.x()
        rr = QRectF(x, pos.y(), w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 22, 170))
        p.drawRoundedRect(rr, h / 2, h / 2)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(rr, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_empty(self, p):
        c = QPointF(self.width() / 2, self.height() / 2)
        pm = icons.pixmap("drop", theme.qc("text3").name(), 54)
        p.drawPixmap(int(c.x() - 27), int(c.y() - 78), pm)
        p.setPen(qc("text"))
        p.setFont(theme.font(19, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, c.y() - 12, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "Drop media to start reviewing")
        p.setPen(qc("text2"))
        p.setFont(theme.font(13))
        p.drawText(QRectF(0, c.y() + 20, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   "Videos, image sequences and stills  ·  Ctrl+O to import")

    def _paint_drop(self, p):
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        p.setBrush(QColor(theme.qc("accent").red(), theme.qc("accent").green(), theme.qc("accent").blue(), 40))
        p.setPen(QPen(qc("accent"), 2, Qt.PenStyle.DashLine))
        p.drawRoundedRect(r, 14, 14)

    # ------------------------------------------------------------------ interaction
    def _near_wipe(self, pos):
        if self.compare != "wipe" or self.img_b is None:
            return False
        ra = self.image_rect()
        if self.wipe_vertical:
            return abs(pos.x() - (ra.x() + ra.width() * self.wipe)) < 10
        return abs(pos.y() - (ra.y() + ra.height() * self.wipe)) < 10

    def mousePressEvent(self, e):
        pos = e.position()
        self._last = pos
        if e.button() == Qt.MouseButton.MiddleButton or (
                e.button() == Qt.MouseButton.LeftButton and
                (e.modifiers() & Qt.KeyboardModifier.AltModifier or self._space)):
            self._drag = "pan"
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._near_wipe(pos):
            self._drag = "wipe"
            return
        if self.tool and self.img_a is not None:
            ip = self.to_image(pos)
            bw = self.brush * max(self.size_a.width(), self.size_a.height()) / 1920.0
            if self.tool == "eraser":
                self._drag = "erase"
                self.eraseAt.emit(ip.x(), ip.y(), bw * 4 + 6 / self.scale())
                return
            if self.tool == "text":
                txt, ok = QInputDialog.getText(self, "Add Text", "Text:")
                if ok and txt.strip():
                    self.strokeFinished.emit({"t": "text", "c": self.color, "w": bw, "p": [[ip.x(), ip.y()]],
                                              "s": txt.strip()})
                return
            self._drawing = {"t": self.tool, "c": self.color, "w": bw, "p": [[ip.x(), ip.y()]]}
            self._drag = "draw"
            self.update()
            return
        if self.compare == "wipe" and self.img_b is not None:
            self._drag = "wipe"
            self._move_wipe(pos)
            return
        self._drag = "pan"
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _move_wipe(self, pos):
        ra = self.image_rect()
        if self.wipe_vertical:
            self.wipe = min(1.0, max(0.0, (pos.x() - ra.x()) / max(1, ra.width())))
        else:
            self.wipe = min(1.0, max(0.0, (pos.y() - ra.y()) / max(1, ra.height())))
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag == "pan":
            d = pos - self._last
            if self.fit:
                self.zoom = self.scale()
                self.fit = False
            self.pan += d
            self._last = pos
            self.update()
        elif self._drag == "wipe":
            self._move_wipe(pos)
        elif self._drag == "draw" and self._drawing:
            ip = self.to_image(pos)
            if self._drawing["t"] == "pen":
                self._drawing["p"].append([ip.x(), ip.y()])
            else:
                self._drawing["p"] = [self._drawing["p"][0], [ip.x(), ip.y()]]
            self.update()
        elif self._drag == "erase":
            ip = self.to_image(pos)
            bw = self.brush * max(self.size_a.width(), self.size_a.height()) / 1920.0
            self.eraseAt.emit(ip.x(), ip.y(), bw * 4 + 6 / self.scale())
        else:
            if self._near_wipe(pos):
                self.setCursor(Qt.CursorShape.SplitHCursor if self.wipe_vertical else Qt.CursorShape.SplitVCursor)
            elif self.tool:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        self._emit_pixel(pos)

    def _emit_pixel(self, pos):
        if self.img_a is None or self.size_a.width() <= 0:
            return
        ip = self.to_image(pos)
        x, y = int(ip.x()), int(ip.y())
        if 0 <= x < self.size_a.width() and 0 <= y < self.size_a.height():
            sx = int(x * self.img_a.width() / self.size_a.width())
            sy = int(y * self.img_a.height() / self.size_a.height())
            c = self.img_a.pixelColor(min(sx, self.img_a.width() - 1), min(sy, self.img_a.height() - 1))
            self.pixelInfo.emit(f"X {x}  Y {y}   R {c.red()}  G {c.green()}  B {c.blue()}")
        else:
            self.pixelInfo.emit("")

    def mouseReleaseEvent(self, e):
        if self._drag == "draw" and self._drawing:
            st = self._drawing
            self._drawing = None
            if st["t"] != "pen" and len(st["p"]) < 2:
                st = None
            if st:
                self.strokeFinished.emit(st)
        self._drag = None
        self.setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if not self.tool:
            self.fit_view()

    def wheelEvent(self, e):
        if self.img_a is None:
            return
        d = e.angleDelta().y()
        if d == 0:
            return
        self.set_zoom(self.scale() * (1.0015 ** d), e.position())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            pass
        super().keyPressEvent(e)

    # ---- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragLeaveEvent(self, e):
        self._drop_hover = False
        self.update()

    def dropEvent(self, e):
        self._drop_hover = False
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        self.update()

    # ---- export helper
    def render_frame(self, with_annotations=True):
        """Return a full-resolution QImage of A with annotations burned in."""
        if self.img_a is None:
            return None
        w, h = self.size_a.width(), self.size_a.height()
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(0, 0, 0))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w, h), self.img_a)
        if with_annotations:
            draw_strokes(p, self.strokes)
        p.end()
        return out
