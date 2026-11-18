"""Custom-painted timeline: ruler, clips, play range, markers, annotation ticks, cache bar."""
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QFontMetricsF, QPolygonF
from PySide6.QtWidgets import QWidget, QToolTip

from . import theme
from .theme import qc, CLIP_COLORS

RULER = 34
TRACK = 50
BTRACK = 26
PAD = 14


def timecode(frame, fps):
    fps_i = max(1, int(round(fps)))
    f = int(frame)
    ff = f % fps_i
    s = f // fps_i
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}:{ff:02d}"


class Timeline(QWidget):
    scrubbed = Signal(int)
    scrubStarted = Signal()
    scrubEnded = Signal()
    rangeChanged = Signal(int, int)
    clipMoved = Signal(int, int)
    clipMenu = Signal(int, QPoint)
    markerActivated = Signal(int)
    emptyMenu = Signal(QPoint)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.frame = 0
        self.in_pt = 0
        self.out_pt = 0
        self.ppf = None
        self.scroll = 0.0
        self.cached = set()
        self.annotated = []
        self.b_track = None          # (label, offset, length)
        self.tc_mode = False
        self.base = 1
        self._drag = None
        self._drag_clip = None
        self._drop_index = None
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER + TRACK + 12)
        self._update_height()

    def _update_height(self):
        h = RULER + TRACK + 14 + (BTRACK + 4 if self.b_track else 0)
        self.setFixedHeight(h)

    def set_b_track(self, info):
        self.b_track = info
        self._update_height()
        self.update()

    # ---- mapping
    def total(self):
        return max(1, self.project.total())

    def _ppf(self):
        if self.ppf is None:
            return (self.width() - 2 * PAD) / self.total()
        return self.ppf

    def x_of(self, f):
        return PAD + (f - self.scroll) * self._ppf()

    def frame_at(self, x):
        f = int((x - PAD) / self._ppf() + self.scroll)
        return max(0, min(self.total() - 1, f))

    def label(self, f):
        return timecode(f, self.project.fps) if self.tc_mode else str(int(f) + self.base)

    def ensure_visible(self, f):
        if self.ppf is None:
            return
        x = self.x_of(f)
        if x < PAD or x > self.width() - PAD:
            vis = (self.width() - 2 * PAD) / self.ppf
            self.scroll = max(0.0, f - vis * 0.2)

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), qc("timeline"))
        p.fillRect(QRectF(0, 0, W, RULER), qc("ruler"))
        p.setPen(QPen(qc("separator"), 1))
        p.drawLine(QPointF(0, RULER - 0.5), QPointF(W, RULER - 0.5))
        total = self.project.total()
        if total <= 0:
            p.setPen(qc("text3"))
            p.setFont(theme.font(12))
            p.drawText(QRectF(0, RULER, W, H - RULER), Qt.AlignmentFlag.AlignCenter,
                       "Timeline is empty — import media or drag it here")
            p.end()
            return
        ppf = self._ppf()
        self._paint_ruler(p, W, ppf)

        # track area
        ty = RULER + 7
        starts = self.project.starts()
        current_idx = self.project.clip_index_at(self.frame)
        for i, (c, s) in enumerate(zip(self.project.clips, starts)):
            x0, x1 = self.x_of(s), self.x_of(s + c.length)
            if x1 < 0 or x0 > W:
                continue
            r = QRectF(x0 + 1, ty, max(2.0, x1 - x0 - 2), TRACK - 4)
            self._paint_clip(p, r, c, i == current_idx, self._drag_clip == i)
        if self._drop_index is not None:
            xs = self.x_of(starts[self._drop_index] if self._drop_index < len(starts) else total)
            p.setPen(QPen(qc("accent"), 3))
            p.drawLine(QPointF(xs, ty - 2), QPointF(xs, ty + TRACK))

        if self.b_track:
            label, off, length = self.b_track
            by = ty + TRACK + 2
            x0, x1 = self.x_of(off), self.x_of(off + length)
            r = QRectF(x0 + 1, by, max(2.0, x1 - x0 - 2), BTRACK - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(102, 212, 207, 150))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor(255, 255, 255))
            p.setFont(theme.font(11, QFont.Weight.DemiBold))
            p.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "B  " + label)

        # play range shading
        if self.in_pt > 0 or self.out_pt < total - 1:
            shade = QColor(0, 0, 0, 120)
            xi, xo = self.x_of(self.in_pt), self.x_of(self.out_pt + 1)
            p.fillRect(QRectF(0, RULER, max(0, xi), H - RULER), shade)
            p.fillRect(QRectF(xo, RULER, max(0, W - xo), H - RULER), shade)
            rc = qc("range")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rc)
            p.drawRoundedRect(QRectF(xi, RULER - 5, max(3, xo - xi), 4), 2, 2)
            for x, d in ((xi, 1), (xo, -1)):
                path = QPainterPath()
                path.moveTo(x, RULER - 10)
                path.lineTo(x, RULER + 3)
                path.lineTo(x + 6 * d, RULER - 1)
                path.lineTo(x + 6 * d, RULER - 10)
                path.closeSubpath()
                p.drawPath(path)

        self._paint_playhead(p, H)
        p.end()

    def _paint_ruler(self, p, W, ppf):
        steps = [1, 2, 5, 10, 12, 24, 25, 30, 48, 50, 60, 100, 120, 240, 250, 500, 1000, 2000, 5000, 10000, 20000]
        fm = QFontMetricsF(theme.font(10, mono=True))
        need = fm.horizontalAdvance(self.label(max(1, self.project.total()))) + 18
        step = next((s for s in steps if s * ppf >= need), steps[-1])
        minor = step / 5 if step >= 5 else (step if step * ppf > 10 else None)
        b = 0 if self.tc_mode else self.base
        f0 = int((max(0, self.scroll) + b) // step * step) - b
        f_end = self.frame_at(W) + step
        p.setFont(theme.font(10, mono=True))
        tick = qc("text3")
        f = f0
        while f <= f_end:
            if f < 0:
                f += step
                continue
            x = self.x_of(f)
            p.setPen(QPen(tick, 1))
            p.drawLine(QPointF(x, 4), QPointF(x, RULER - 1))
            p.setPen(qc("text2"))
            p.drawText(QPointF(x + 4, 13), self.label(f))
            if minor and minor != step:
                m = f + minor
                p.setPen(QPen(tick, 1))
                while m < f + step - 0.01:
                    xm = self.x_of(m)
                    p.drawLine(QPointF(xm, RULER - 5), QPointF(xm, RULER - 1))
                    m += minor
            f += step
        # cache bar
        if self.cached:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc("cache"))
            fr = sorted(self.cached)
            run_s = prev = fr[0]
            for v in fr[1:] + [None]:
                if v is not None and v == prev + 1:
                    prev = v
                    continue
                x0, x1 = self.x_of(run_s), self.x_of(prev + 1)
                p.drawRect(QRectF(x0, RULER - 2.5, max(1.0, x1 - x0), 2.5))
                if v is not None:
                    run_s = prev = v
        # annotation ticks
        p.setBrush(QColor("#FFD60A"))
        p.setPen(Qt.PenStyle.NoPen)
        for g in self.annotated:
            x = self.x_of(g + 0.5)
            p.drawEllipse(QPointF(x, RULER + 3.5), 2.6, 2.6)
        # markers
        for g, m in self.project.markers.items():
            x = self.x_of(g)
            col = QColor(m.get("color", "#FF9F0A"))
            p.setBrush(col)
            path = QPainterPath()
            path.moveTo(x, 17)
            path.lineTo(x + 9, 17)
            path.lineTo(x + 9, 24)
            path.lineTo(x + 4.5, 28)
            path.lineTo(x, 24)
            path.closeSubpath()
            p.drawPath(path)
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 150), 1))
            p.drawLine(QPointF(x + 0.5, 28), QPointF(x + 0.5, self.height()))
            p.setPen(Qt.PenStyle.NoPen)

    def _paint_clip(self, p, r, c, current, dragging):
        base = QColor(CLIP_COLORS.get(c.source.kind, "#3D6FE0"))
        if c.source.error:
            base = QColor("#8E3A3A")
        p.save()
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setClipPath(path)
        fill = QColor(base)
        fill.setAlpha(255 if current else 200)
        p.fillRect(r, fill)
        # thumbnail filmstrip
        th = c.source.thumb
        if th is not None and r.width() > 30:
            tw = th.width() * (r.height() / max(1, th.height()))
            x = r.x()
            n = 0
            while x < r.right() and n < 60:
                p.setOpacity(0.55)
                p.drawImage(QRectF(x, r.y(), tw, r.height()), th)
                x += tw + 1
                n += 1
                if r.width() < 260:
                    break
            p.setOpacity(1.0)
        # legibility gradient
        p.fillRect(QRectF(r.x(), r.y(), r.width(), 20), QColor(0, 0, 0, 90))
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 230) if current else QColor(0, 0, 0, 80), 1.6 if current else 1))
        if dragging:
            p.setPen(QPen(qc("accent"), 2))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        if r.width() > 40:
            p.setPen(QColor(255, 255, 255))
            p.setFont(theme.font(11, QFont.Weight.DemiBold))
            txt = QFontMetricsF(p.font()).elidedText(f"{c.source.name}   {c.length}f", Qt.TextElideMode.ElideRight,
                                                     r.width() - 14)
            p.drawText(QRectF(r.x() + 8, r.y() + 2, r.width() - 12, 17),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

    def _paint_playhead(self, p, H):
        x = self.x_of(self.frame + 0.5) if self._ppf() > 6 else self.x_of(self.frame)
        col = qc("playhead")
        p.setPen(QPen(col, 1.5))
        p.drawLine(QPointF(x, RULER - 2), QPointF(x, H))
        txt = self.label(self.frame)
        p.setFont(theme.font(10, QFont.Weight.DemiBold, mono=True))
        w = QFontMetricsF(p.font()).horizontalAdvance(txt) + 12
        r = QRectF(x - w / 2, 2, w, 16)
        if r.x() < 2:
            r.moveLeft(2)
        if r.right() > self.width() - 2:
            r.moveRight(self.width() - 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 5, 5)
        p.drawPolygon(QPolygonF([QPointF(x - 4, r.bottom() - 1), QPointF(x + 4, r.bottom() - 1),
                                 QPointF(x, r.bottom() + 4)]))
        p.setPen(QColor(255, 255, 255))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    # ---- interaction
    def _clip_at(self, x, y):
        if not (RULER + 4 <= y <= RULER + TRACK + 4):
            return None
        f = (x - PAD) / self._ppf() + self.scroll
        s = 0
        for i, c in enumerate(self.project.clips):
            if s <= f < s + c.length:
                return i
            s += c.length
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        x, y = pos.x(), pos.y()
        if self.project.total() <= 0:
            if e.button() == Qt.MouseButton.RightButton:
                self.emptyMenu.emit(e.globalPosition().toPoint())
            return
        if e.button() == Qt.MouseButton.RightButton:
            i = self._clip_at(x, y)
            if i is not None:
                self.clipMenu.emit(i, e.globalPosition().toPoint())
            else:
                self.emptyMenu.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        total = self.project.total()
        if y < RULER + 2 and (self.in_pt > 0 or self.out_pt < total - 1):
            if abs(x - self.x_of(self.in_pt)) < 7:
                self._drag = "in"
                return
            if abs(x - self.x_of(self.out_pt + 1)) < 7:
                self._drag = "out"
                return
        if e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            i = self._clip_at(x, y)
            if i is not None:
                self._drag = "clip"
                self._drag_clip = i
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        self._drag = "scrub"
        self.scrubStarted.emit()
        self.scrubbed.emit(self.frame_at(x))

    def mouseMoveEvent(self, e):
        x, y = e.position().x(), e.position().y()
        if self._drag == "scrub":
            self.scrubbed.emit(self.frame_at(x))
        elif self._drag == "in":
            self.in_pt = min(self.frame_at(x), self.out_pt)
            self.rangeChanged.emit(self.in_pt, self.out_pt)
            self.update()
        elif self._drag == "out":
            self.out_pt = max(self.frame_at(x) - 1, self.in_pt) if x < self.x_of(self.total()) else self.total() - 1
            self.rangeChanged.emit(self.in_pt, self.out_pt)
            self.update()
        elif self._drag == "clip":
            f = (x - PAD) / self._ppf() + self.scroll
            starts = self.project.starts() + [self.project.total()]
            best = min(range(len(starts)), key=lambda k: abs(starts[k] - f))
            self._drop_index = best
            self.update()
        else:
            if 14 < y < RULER:
                for g, m in self.project.markers.items():
                    if abs(x - self.x_of(g) - 4) < 7 and m.get("note"):
                        QToolTip.showText(e.globalPosition().toPoint(), m["note"], self)
                        break
            self.setCursor(Qt.CursorShape.SizeHorCursor if (
                y < RULER + 2 and (abs(x - self.x_of(self.in_pt)) < 7 or abs(x - self.x_of(self.out_pt + 1)) < 7)
                and (self.in_pt > 0 or self.out_pt < self.total() - 1)) else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._drag == "clip" and self._drop_index is not None and self._drag_clip is not None:
            src, dst = self._drag_clip, self._drop_index
            if dst > src:
                dst -= 1
            if dst != src:
                self.clipMoved.emit(src, dst)
        if self._drag == "scrub":
            self.scrubEnded.emit()
        self._drag = None
        self._drag_clip = None
        self._drop_index = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, e):
        x, y = e.position().x(), e.position().y()
        if y < RULER:
            for g in self.project.markers:
                if abs(x - self.x_of(g) - 4) < 8:
                    self.markerActivated.emit(g)
                    return

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.ppf is not None:
            self.scroll = max(0.0, self.scroll - d / 120 * 40 / self.ppf)
            self.update()
            return
        old = self._ppf()
        anchor = (e.position().x() - PAD) / old + self.scroll
        fit = (self.width() - 2 * PAD) / self.total()
        new = max(fit, min(40.0, old * (1.0015 ** d)))
        if new <= fit * 1.001:
            self.ppf = None
            self.scroll = 0.0
        else:
            self.ppf = new
            self.scroll = max(0.0, anchor - (e.position().x() - PAD) / new)
        self.update()
