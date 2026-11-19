"""The photo canvas: fit/zoom/pan, rotation, cross-fades, transparency checkerboard, animated GIFs."""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, QVariantAnimation, QEasingCurve, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap, QTransform, QBrush, QMovie, QFont, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from frameline import theme, icons
from frameline.viewer import draw_strokes
from frameline.theme import qc

ZOOM_STEPS = [0.05, 0.0833, 0.125, 0.1667, 0.25, 0.333, 0.5, 0.667, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0]


def _checker(dark):
    pm = QPixmap(16, 16)
    a, b = (QColor(58, 58, 62), QColor(44, 44, 48)) if dark else (QColor(255, 255, 255), QColor(226, 226, 230))
    pm.fill(a)
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, b)
    p.fillRect(8, 8, 8, 8, b)
    p.end()
    return pm


class PhotoView(QWidget):
    zoomChanged = Signal(float)
    navigate = Signal(int)          # -1 / +1 from edge clicks
    strokeAdded = Signal(dict)      # markup stroke in image pixel coordinates
    eraseAt = Signal(float, float, float)
    textRequested = Signal(float, float)
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.img = None              # QImage being shown
        self.pix = None              # QPixmap of img
        self.rotation = 0
        self.fit = True
        self.scale = 1.0
        self.center = QPointF(0, 0)  # image-space point shown at the widget centre
        self.placeholder = False     # showing a low-res stand-in while the full image decodes
        self.message = ""
        self.empty_hint = True
        self.bg = "auto"
        self._old = None             # previous frame for cross-fade
        self._fade = 1.0
        self._fade_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=170,
                                            easingCurve=QEasingCurve.Type.OutCubic)
        self._fade_anim.valueChanged.connect(self._on_fade)
        self._scaled = None          # (key, QPixmap) smooth-scaled cache for zoomed-out views
        self._refine = QTimer(self, singleShot=True, interval=90, timeout=self._make_scaled)
        self._drag = None
        self._hud_until = 0
        self._hud_timer = QTimer(self, singleShot=True, timeout=self.update)
        self._clock = QElapsedTimer()
        self._clock.start()
        self.movie = None
        self.drop_active = False
        self._edge_hover = 0
        # markup
        self.tool = None             # pen / line / arrow / rect / ellipse / text / eraser
        self.color = "#FF453A"
        self.pen_px = 4.0            # stroke width in screen pixels at the time of drawing
        self.strokes = []
        self._live = None
        # adjustments (levels / curves)
        self.adj_pix = None          # adjusted preview (any resolution; drawn into the image rect)
        self.adjusted_img = None     # full-resolution adjusted image, sRGB (for copy)
        self.show_original = False   # "Compare" held

    # ------------------------------------------------------------------ content
    def set_image(self, img, placeholder=False, fade=True, keep_view=False):
        if fade and self.pix is not None and self.isVisible():
            self._old = self.grab()
            self._fade_anim.stop()
            self._fade_anim.start()
        self.stop_movie()
        self.img = img
        self.pix = QPixmap.fromImage(img) if img is not None and not img.isNull() else None
        self.placeholder = placeholder
        self._scaled = None
        self.adj_pix = None
        self.adjusted_img = None
        if not keep_view:
            self.rotation = 0
            self.fit = True
        self._apply_fit()
        self.update()

    def upgrade_image(self, img):
        """Swap the placeholder for the full-resolution decode without resetting the view."""
        if self.img is None or img is None or img.isNull():
            return self.set_image(img, fade=False)
        if not self.fit:
            # keep the same visible region: rescale the centre and zoom to the new pixel grid
            k = img.width() / max(1, self.img.width())
            self.center = QPointF(self.center.x() * k, self.center.y() * k)
            self.scale /= k
        self.img = img
        self.pix = QPixmap.fromImage(img)
        self.placeholder = False
        self._scaled = None
        self.adj_pix = None
        self.adjusted_img = None
        self._apply_fit()
        self.update()

    def play_movie(self, path):
        self.stop_movie()
        m = QMovie(path)
        if not m.isValid():
            return
        self.movie = m
        m.frameChanged.connect(self._on_movie_frame)
        m.start()

    def stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    def _on_movie_frame(self, _):
        if self.movie is None:
            return
        img = self.movie.currentImage()
        if not img.isNull():
            self.img = img
            self.pix = QPixmap.fromImage(img)
            self._scaled = None
            self.update()

    def clear(self):
        self.stop_movie()
        self.img = self.pix = None
        self._old = None
        self.update()

    def _on_fade(self, v):
        self._fade = v
        if v >= 1.0:
            self._old = None
        self.update()

    # ------------------------------------------------------------------ geometry
    def _img_size(self):
        if self.img is None:
            return 1, 1
        w, h = self.img.width(), self.img.height()
        return (h, w) if self.rotation % 180 else (w, h)

    def fit_scale(self):
        w, h = self._img_size()
        avail_w, avail_h = max(1, self.width() - 32), max(1, self.height() - 32)
        return min(avail_w / w, avail_h / h, 1.0 if not self._upscale_small() else 1e9)

    def _upscale_small(self):
        return False   # never blow small images up past 100% when fitting

    def _apply_fit(self):
        if self.img is None:
            return
        if self.fit:
            self.scale = self.fit_scale()
            w, h = self._img_size()
            self.center = QPointF(w / 2, h / 2)
        self._clamp()
        self.zoomChanged.emit(self.scale)

    def resizeEvent(self, e):
        self._scaled = None
        self._apply_fit()
        super().resizeEvent(e)

    def _clamp(self):
        w, h = self._img_size()
        vw, vh = self.width() / self.scale / 2, self.height() / self.scale / 2
        cx = w / 2 if w <= vw * 2 else min(max(self.center.x(), vw), w - vw)
        cy = h / 2 if h <= vh * 2 else min(max(self.center.y(), vh), h - vh)
        self.center = QPointF(cx, cy)

    def to_widget(self, pt):
        return QPointF((pt.x() - self.center.x()) * self.scale + self.width() / 2,
                       (pt.y() - self.center.y()) * self.scale + self.height() / 2)

    def to_image(self, pos):
        return QPointF((pos.x() - self.width() / 2) / self.scale + self.center.x(),
                       (pos.y() - self.height() / 2) / self.scale + self.center.y())

    def image_transform(self):
        """Unrotated image pixels -> widget coordinates."""
        r = self.image_rect()
        t = QTransform()
        t.translate(r.center().x(), r.center().y())
        t.rotate(self.rotation)
        t.translate(-self.img.width() * self.scale / 2, -self.img.height() * self.scale / 2)
        t.scale(self.scale, self.scale)
        return t

    def widget_to_pixels(self, pos):
        inv, ok = self.image_transform().inverted()
        q = inv.map(QPointF(pos))
        return q.x(), q.y()

    def image_rect(self):
        w, h = self._img_size()
        tl = self.to_widget(QPointF(0, 0))
        return QRectF(tl.x(), tl.y(), w * self.scale, h * self.scale)

    # ------------------------------------------------------------------ zoom API
    def zoom_to(self, s, anchor=None):
        if self.img is None:
            return
        s = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], s))
        anchor = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        before = self.to_image(anchor)
        self.fit = False
        self.scale = s
        after = self.to_image(anchor)
        self.center += before - after
        self._clamp()
        if abs(self.scale - self.fit_scale()) < 1e-6:
            self.fit = True
        self._hud()
        self._refine.start()
        self.zoomChanged.emit(self.scale)
        self.update()

    def zoom_step(self, direction, anchor=None):
        cur = self.scale
        if direction > 0:
            nxt = next((z for z in ZOOM_STEPS if z > cur * 1.01), ZOOM_STEPS[-1])
        else:
            nxt = next((z for z in reversed(ZOOM_STEPS) if z < cur * 0.99), ZOOM_STEPS[0])
        fs = self.fit_scale()
        if (cur < fs < nxt) or (nxt < fs < cur):
            nxt = fs    # stop at "fit" on the way through
        self.zoom_to(nxt, anchor)

    def set_fit(self):
        self.fit = True
        self._apply_fit()
        self._hud()
        self.update()

    def actual_size(self, anchor=None):
        self.zoom_to(1.0, anchor)

    def rotate(self, deg):
        self.rotation = (self.rotation + deg) % 360
        self._scaled = None
        self.fit = True
        self._apply_fit()
        self.update()

    def _hud(self):
        self._hud_until = self._clock.elapsed() + 900
        self._hud_timer.start(950)

    def set_adjusted(self, img, full=False):
        """Show an adjusted version (None restores the original). full=True marks a full-resolution result."""
        if img is None or img.isNull():
            self.adj_pix = None
            self.adjusted_img = None
        else:
            self.adj_pix = QPixmap.fromImage(img)
            self.adjusted_img = img if full else None
        self._scaled = None
        self.update()

    def _shown(self):
        if self.adj_pix is not None and not self.show_original:
            return self.adj_pix
        return self.pix

    # ------------------------------------------------------------------ painting
    def _bg_color(self):
        return qc("viewer")

    def _make_scaled(self):
        """Smooth pre-scaled pixmap for zoomed-out display (Qt's on-the-fly scaling is coarse)."""
        if self.pix is None or self.scale >= 1.0:
            self._scaled = None
            return
        w = max(1, round(self.img.width() * self.scale))
        h = max(1, round(self.img.height() * self.scale))
        src = self._shown()
        key = (w, h, src.cacheKey())
        if self._scaled and self._scaled[0] == key:
            return
        self._scaled = (key, src.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg_color())
        if self.pix is not None:
            self._paint_image(p)
        elif self.empty_hint:
            self._paint_empty(p)
        if self._old is not None and self._fade < 1.0:
            p.setOpacity(1.0 - self._fade)
            p.drawPixmap(0, 0, self._old)
            p.setOpacity(1.0)
        if self.pix is not None and self._clock.elapsed() < self._hud_until:
            self._paint_hud(p, f"{self.scale * 100:.0f}%")
        if self.message:
            self._paint_hud(p, self.message, top=True)
        if self.drop_active:
            self._paint_drop(p)
        p.end()

    def _paint_image(self, p):
        r = self.image_rect()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.img.hasAlphaChannel():
            p.save()
            p.setBrushOrigin(r.topLeft())
            p.fillRect(r, QBrush(_checker(theme.T["name"] == "dark")))
            p.restore()
        p.save()
        p.translate(r.center())
        p.rotate(self.rotation)
        iw, ih = self.img.width() * self.scale, self.img.height() * self.scale
        target = QRectF(-iw / 2, -ih / 2, iw, ih)
        src = self._shown()
        if self.scale >= 1.0:
            # pixel-peeping: crisp nearest-neighbour above 200 %, smooth below
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale < 2.0 or src.width() != self.pix.width())
            p.drawPixmap(target, src, QRectF(src.rect()))
        else:
            if self._scaled is None or self._scaled[0] != (max(1, round(self.img.width() * self.scale)),
                                                           max(1, round(self.img.height() * self.scale)),
                                                           src.cacheKey()):
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawPixmap(target, src, QRectF(src.rect()))
                if not self._refine.isActive():
                    self._refine.start()
            else:
                p.drawPixmap(target.topLeft(), self._scaled[1])
        p.restore()
        if (self.strokes or self._live) and not self.placeholder:
            p.save()
            p.setTransform(self.image_transform(), True)
            draw_strokes(p, self.strokes + ([self._live] if self._live else []))
            p.restore()
        if self.placeholder:
            self._paint_spinner(p)

    def _paint_spinner(self, p):
        t = self._clock.elapsed() / 1000.0
        c = QPointF(self.width() - 34, self.height() - 34)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            a = i / 8 * 2 * math.pi
            alpha = int(60 + 195 * (((i / 8) - t * 1.2) % 1.0))
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawEllipse(c + QPointF(math.cos(a) * 9, math.sin(a) * 9), 2.2, 2.2)
        QTimer.singleShot(60, self.update)

    def _pill(self, p, text, center, font_px=12.5):
        f = theme.font(font_px, QFont.Weight.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 26
        h = fm.height() + 12
        r = QRectF(center.x() - w / 2, center.y() - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(58, 58, 62, 225) if theme.T["name"] == "dark" else QColor(30, 30, 32, 200))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(QColor(255, 255, 255))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_hud(self, p, text, top=False):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = 36 if top else self.height() - 40
        self._pill(p, text, QPointF(self.width() / 2, y))

    def _paint_empty(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2 - 30)
        pm = icons.pixmap("photo", qc("text3").name(), 44)
        p.drawPixmap(int(c.x() - 22), int(c.y() - 44), pm)
        p.setPen(qc("text"))
        p.setFont(theme.font(17, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, c.y() + 10, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "Open a photo or a folder")
        p.setPen(qc("text2"))
        p.setFont(theme.font(12.5))
        p.drawText(QRectF(0, c.y() + 40, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   "Drop files here  ·  Ctrl+O to open  ·  every photo in the folder is ready to browse")

    def _paint_drop(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        p.setBrush(QColor(qc("accent").red(), qc("accent").green(), qc("accent").blue(), 30))
        pen = QPen(qc("accent"), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r, 14, 14)

    # ------------------------------------------------------------------ input
    def wheelEvent(self, e):
        if self.img is None:
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier or True:
            # smooth multiplicative zoom for trackpads, step zoom for mouse wheels
            if abs(d) < 120 and e.pixelDelta().y():
                self.zoom_to(self.scale * (1.0015 ** e.pixelDelta().y()), e.position())
            else:
                self.zoom_to(self.scale * (1.2 if d > 0 else 1 / 1.2), e.position())

    def _stroke_w(self):
        return max(0.5, self.pen_px / max(self.scale, 1e-6))

    def mousePressEvent(self, e):
        if self.tool and e.button() == Qt.MouseButton.LeftButton and self.img is not None and not self.placeholder:
            x, y = self.widget_to_pixels(e.position())
            if self.tool == "text":
                if 0 <= x < self.img.width() and 0 <= y < self.img.height():
                    self.textRequested.emit(x, y)
                return
            if self.tool == "eraser":
                self._erasing = True
                self.eraseAt.emit(x, y, 14 / self.scale)
                return
            self._live = {"t": self.tool, "c": self.color, "w": self._stroke_w(), "p": [[x, y]]}
            self.update()
            return
        if e.button() == Qt.MouseButton.LeftButton and self.img is not None:
            edge = self._edge(e.position())
            if edge and self.fit:
                self.navigate.emit(edge)
                return
            self._drag = (e.position(), QPointF(self.center))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.tool and self.img is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
            if self._live is not None:
                x, y = self.widget_to_pixels(e.position())
                if self._live["t"] == "pen":
                    self._live["p"].append([x, y])
                else:
                    self._live["p"] = [self._live["p"][0], [x, y]]
                self.update()
            elif getattr(self, "_erasing", False):
                x, y = self.widget_to_pixels(e.position())
                self.eraseAt.emit(x, y, 14 / self.scale)
            return
        if self._drag is not None:
            start, c0 = self._drag
            d = e.position() - start
            self.center = c0 - QPointF(d.x() / self.scale, d.y() / self.scale)
            self._clamp()
            self.update()
            return
        edge = self._edge(e.position()) if (self.img is not None and self.fit) else 0
        if edge != self._edge_hover:
            self._edge_hover = edge
        self.setCursor(Qt.CursorShape.PointingHandCursor if edge else
                       (Qt.CursorShape.OpenHandCursor if (self.img is not None and not self.fit) else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, e):
        self._erasing = False
        if self._live is not None:
            st, self._live = self._live, None
            pts = st["p"]
            if st["t"] == "pen" or (len(pts) == 2 and (abs(pts[0][0] - pts[1][0]) + abs(pts[0][1] - pts[1][1])) * self.scale > 3):
                self.strokeAdded.emit(st)
            self.update()
            return
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if (self.img is not None and not self.fit) else Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, e):
        if self.img is None or self.tool:
            return
        if self.fit:
            self.actual_size(e.position())
        else:
            self.set_fit()

    def _edge(self, pos):
        """Click zones at the far left/right of a fitted photo flip to the previous/next one."""
        if pos.x() < min(90, self.width() * 0.12):
            return -1
        if pos.x() > self.width() - min(90, self.width() * 0.12):
            return 1
        return 0

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop_active = True
            self.update()

    def dragLeaveEvent(self, e):
        self.drop_active = False
        self.update()

    def dropEvent(self, e):
        self.drop_active = False
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        self.update()

    # ------------------------------------------------------------------ helpers
    def rendered_image(self):
        """The image with its current rotation applied (for copy / save)."""
        if self.img is None:
            return None
        img = self.adjusted_img if self.adjusted_img is not None else self.img
        if self.strokes:
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied if img.hasAlphaChannel()
                                      else QImage.Format.Format_RGB32)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_strokes(p, self.strokes)
            p.end()
        if self.rotation == 0:
            return img
        return img.transformed(QTransform().rotate(self.rotation), Qt.TransformationMode.SmoothTransformation)
