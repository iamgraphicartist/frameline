"""The Adjust sidebar: Levels and Curves editors in the style of a photo editor."""
import math

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QLinearGradient, QPolygonF, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
                               QScrollArea, QSizePolicy, QFrame)

from frameline import theme
from frameline.theme import qc
from frameline.widgets import Segmented, section
from .adjust import Adjustments, CHANNELS, curve_fn, default_levels, default_curve, auto_levels, tables

CH_LABELS = ("RGB", "Red", "Green", "Blue")
CH_COLORS = {"rgb": None, "r": QColor(255, 82, 72), "g": QColor(52, 210, 96), "b": QColor(40, 140, 255)}


def _curve_color(ch):
    c = CH_COLORS[ch]
    return QColor(c) if c is not None else qc("text")


def _hist_for(hists, ch):
    if hists is None:
        return None
    if ch == "rgb":
        h = hists[0] * 0.30 + hists[1] * 0.59 + hists[2] * 0.11
    else:
        h = hists[("r", "g", "b").index(ch)]
    peak = max(float(np.percentile(h, 99.5)), 1.0)
    return np.minimum(h / peak, 1.0)


def _paint_hist(p, rect, h, color):
    if h is None:
        return
    path = QPainterPath(QPointF(rect.left(), rect.bottom()))
    for i in range(256):
        path.lineTo(rect.left() + rect.width() * i / 255.0, rect.bottom() - rect.height() * float(h[i]))
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _hist_color(ch, alpha):
    c = CH_COLORS[ch]
    if c is None:
        c = qc("text2")
    c = QColor(c)
    c.setAlpha(alpha)
    return c


# =============================================================================================== curves
class CurveEditor(QWidget):
    """Square curve graph. Click to add a point, drag to move, drag off the graph or double-click to remove."""
    changed = Signal()        # while dragging
    committed = Signal()      # interaction finished (for undo)
    selectionChanged = Signal()

    PAD = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.adj = Adjustments()
        self.ch = "rgb"
        self.hist = None
        self.sel = None
        self._drag = False
        self._removed = None      # point index hidden while dragged off the graph
        self._hover = None
        self.setMouseTracking(True)

    def heightForWidth(self, w):
        return w

    def hasHeightForWidth(self):
        return True

    def resizeEvent(self, e):
        if self.height() != self.width():
            self.setFixedHeight(self.width())
        super().resizeEvent(e)

    @property
    def pts(self):
        return self.adj.curves[self.ch]

    def set_channel(self, ch):
        self.ch = ch
        self.sel = None
        self.selectionChanged.emit()
        self.update()

    def _graph(self):
        s = min(self.width(), self.height()) - 2 * self.PAD
        return QRectF(self.PAD, self.PAD, s, s)

    def _to_w(self, x, y):
        g = self._graph()
        return QPointF(g.left() + g.width() * x / 255.0, g.bottom() - g.height() * y / 255.0)

    def _to_v(self, pos):
        g = self._graph()
        x = (pos.x() - g.left()) / g.width() * 255.0
        y = (g.bottom() - pos.y()) / g.height() * 255.0
        return x, y

    def _hit(self, pos):
        best, bd = None, 10.0
        for i, (x, y) in enumerate(self.pts):
            q = self._to_w(x, y)
            d = math.hypot(q.x() - pos.x(), q.y() - pos.y())
            if d < bd:
                best, bd = i, d
        return best

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        i = self._hit(pos)
        if i is None:
            x, y = self._to_v(pos)
            x = max(0.0, min(255.0, round(x)))
            y = max(0.0, min(255.0, round(y)))
            pts = self.pts
            if any(abs(px - x) < 2 for px, _ in pts):
                return
            pts.append([x, y])
            pts.sort(key=lambda p: p[0])
            i = next(k for k, p in enumerate(pts) if p[0] == x)
            self.changed.emit()
        self.sel = i
        self._drag = True
        self.selectionChanged.emit()
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag or self.sel is None:
            h = self._hit(pos)
            if h != self._hover:
                self._hover = h
                self.update()
            return
        pts = self.pts
        i = self.sel
        x, y = self._to_v(pos)
        g = self._graph()
        far = (pos.x() < g.left() - 24 or pos.x() > g.right() + 24 or pos.y() < g.top() - 24 or
               pos.y() > g.bottom() + 24)
        removable = len(pts) > 2
        self._removed = i if (far and removable) else None
        lo = pts[i - 1][0] + 1 if i > 0 else 0.0
        hi = pts[i + 1][0] - 1 if i < len(pts) - 1 else 255.0
        pts[i][0] = float(max(lo, min(hi, round(x))))
        pts[i][1] = float(max(0.0, min(255.0, round(y))))
        self.changed.emit()
        self.selectionChanged.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        self._drag = False
        if self._removed is not None:
            self.pts.pop(self._removed)
            self._removed = None
            self.sel = None
            self.selectionChanged.emit()
            self.changed.emit()
        self.committed.emit()
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._hit(e.position())
        if i is not None and len(self.pts) > 2:
            self.pts.pop(i)
            self.sel = None
            self.selectionChanged.emit()
            self.changed.emit()
            self.committed.emit()
            self.update()

    NUDGE_KEYS = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Delete,
                  Qt.Key.Key_Backspace)

    def event(self, e):
        # with a point selected, arrows and Delete edit the curve instead of browsing or deleting the photo
        if e.type() == e.Type.ShortcutOverride and self.sel is not None and e.key() in self.NUDGE_KEYS:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if self.sel is None:
            return super().keyPressEvent(e)
        step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(e.key(), 0)
        dy = {Qt.Key.Key_Up: step, Qt.Key.Key_Down: -step}.get(e.key(), 0)
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and len(self.pts) > 2:
            self.pts.pop(self.sel)
            self.sel = None
        elif dx or dy:
            self.set_selected(self.pts[self.sel][0] + dx, self.pts[self.sel][1] + dy, emit=False)
        else:
            return super().keyPressEvent(e)
        self.selectionChanged.emit()
        self.changed.emit()
        self.committed.emit()
        self.update()

    def set_selected(self, x=None, y=None, emit=True):
        if self.sel is None:
            return
        pts, i = self.pts, self.sel
        lo = pts[i - 1][0] + 1 if i > 0 else 0.0
        hi = pts[i + 1][0] - 1 if i < len(pts) - 1 else 255.0
        if x is not None:
            pts[i][0] = float(max(lo, min(hi, x)))
        if y is not None:
            pts[i][1] = float(max(0.0, min(255.0, y)))
        if emit:
            self.changed.emit()
            self.committed.emit()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self._graph()
        p.setPen(QPen(qc("separator"), 1))
        p.setBrush(qc("field"))
        p.drawRoundedRect(g.adjusted(-0.5, -0.5, 0.5, 0.5), 4, 4)
        _paint_hist(p, g.adjusted(1, 1, -1, -1), _hist_for(self.hist, self.ch), _hist_color(self.ch, 60))
        grid = QColor(qc("text3"))
        grid.setAlpha(55)
        p.setPen(QPen(grid, 1))
        for k in (1, 2, 3):
            x = g.left() + g.width() * k / 4
            y = g.top() + g.height() * k / 4
            p.drawLine(QPointF(x, g.top()), QPointF(x, g.bottom()))
            p.drawLine(QPointF(g.left(), y), QPointF(g.right(), y))
        base = QColor(qc("text3"))
        base.setAlpha(110)
        p.setPen(QPen(base, 1, Qt.PenStyle.DashLine))
        p.drawLine(g.bottomLeft(), g.topRight())
        xs = np.linspace(0, 1, 256)
        # other channels faintly, so you can see the whole correction
        for ch in CHANNELS:
            if ch == self.ch or self.adj.curve_identity(ch):
                continue
            c = _curve_color(ch)
            c.setAlpha(110)
            self._draw_curve(p, g, curve_fn(self.adj.curves[ch])(xs), c, 1.2)
        pts = [q for k, q in enumerate(self.pts) if k != self._removed]
        self._draw_curve(p, g, curve_fn(pts)(xs), _curve_color(self.ch), 2.0)
        for k, (x, y) in enumerate(self.pts):
            if k == self._removed:
                continue
            q = self._to_w(x, y)
            sel = k == self.sel
            p.setPen(QPen(_curve_color(self.ch), 1.6))
            p.setBrush(_curve_color(self.ch) if sel else qc("field"))
            r = 5.0 if sel or k == self._hover else 4.2
            p.drawEllipse(q, r, r)
        p.end()

    @staticmethod
    def _draw_curve(p, g, ys, color, width):
        path = QPainterPath()
        for i, y in enumerate(ys):
            q = QPointF(g.left() + g.width() * i / 255.0, g.bottom() - g.height() * float(y))
            if i == 0:
                path.moveTo(q)
            else:
                path.lineTo(q)
        p.setPen(QPen(color, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


# =============================================================================================== levels
class LevelsEditor(QWidget):
    """Histogram with input black / midtone / white handles, then an output range bar with two handles."""
    changed = Signal()
    committed = Signal()

    HIST_H = 76
    TRI = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HIST_H + 58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.adj = Adjustments()
        self.ch = "rgb"
        self.hist = None
        self._drag = None

    @property
    def lv(self):
        return self.adj.levels[self.ch]

    def set_channel(self, ch):
        self.ch = ch
        self.update()

    def _rects(self):
        m = self.TRI + 1
        hist = QRectF(m, 0, self.width() - 2 * m, self.HIST_H)
        in_y = self.HIST_H + 2
        out_bar = QRectF(m, self.HIST_H + 30, self.width() - 2 * m, 9)
        return hist, in_y, out_bar

    def _x(self, v):
        hist, _, _ = self._rects()
        return hist.left() + hist.width() * v / 255.0

    def _v(self, x):
        hist, _, _ = self._rects()
        return max(0.0, min(255.0, (x - hist.left()) / hist.width() * 255.0))

    def gamma_pos(self):
        b, g, w = self.lv[0], self.lv[1], self.lv[2]
        return b + (w - b) * (0.5 ** g)

    def _handles(self):
        _, in_y, out_bar = self._rects()
        b, g, w, ob, ow = self.lv
        return {"b": (self._x(b), in_y), "g": (self._x(self.gamma_pos()), in_y), "w": (self._x(w), in_y),
                "ob": (self._x(ob), out_bar.bottom() + 1), "ow": (self._x(ow), out_bar.bottom() + 1)}

    def mousePressEvent(self, e):
        pos = e.position()
        best, bd = None, 14.0
        for k, (x, y) in self._handles().items():
            d = math.hypot(x - pos.x(), (y + self.TRI) - pos.y())
            if d < bd:
                best, bd = k, d
        self._drag = best

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        v = round(self._v(e.position().x()))
        lv = self.lv
        k = self._drag
        if k == "b":
            lv[0] = float(max(0, min(v, lv[2] - 2)))
        elif k == "w":
            lv[2] = float(min(255, max(v, lv[0] + 2)))
        elif k == "g":
            b, w = lv[0], lv[2]
            t = max(0.0, min(1.0, (self._v(e.position().x()) - b) / max(w - b, 1e-6)))
            t = max(0.0010, min(0.9999, t))
            lv[1] = float(round(max(0.01, min(9.99, math.log(t) / math.log(0.5))), 2))
        elif k == "ob":
            lv[3] = float(v)
        elif k == "ow":
            lv[4] = float(v)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.committed.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hist, in_y, out_bar = self._rects()
        p.setPen(QPen(qc("separator"), 1))
        p.setBrush(qc("field"))
        p.drawRoundedRect(hist.adjusted(-0.5, -0.5, 0.5, 0.5), 4, 4)
        _paint_hist(p, hist.adjusted(1, 4, -1, -1), _hist_for(self.hist, self.ch), _hist_color(self.ch, 150))
        # clipped regions are shaded so you can see what's being crushed
        b, g, w, ob, ow = self.lv
        shade = QColor(0, 0, 0, 70) if theme.T["name"] == "dark" else QColor(0, 0, 0, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        if b > 0:
            p.drawRect(QRectF(hist.left(), hist.top(), self._x(b) - hist.left(), hist.height()))
        if w < 255:
            p.drawRect(QRectF(self._x(w), hist.top(), hist.right() - self._x(w), hist.height()))
        # input track
        track = QColor(qc("text3"))
        track.setAlpha(90)
        p.setPen(QPen(track, 1))
        p.drawLine(QPointF(hist.left(), in_y), QPointF(hist.right(), in_y))
        hs = self._handles()
        self._tri(p, hs["b"], QColor(10, 10, 12))
        self._tri(p, hs["g"], QColor(128, 128, 132))
        self._tri(p, hs["w"], QColor(250, 250, 252))
        # output bar
        tint = CH_COLORS[self.ch]
        grad = QLinearGradient(out_bar.topLeft(), out_bar.topRight())
        grad.setColorAt(0, QColor(0, 0, 0))
        grad.setColorAt(1, QColor(tint) if tint is not None else QColor(255, 255, 255))
        p.setPen(QPen(qc("separator"), 1))
        p.setBrush(grad)
        p.drawRoundedRect(out_bar, 3, 3)
        self._tri(p, hs["ob"], QColor(10, 10, 12))
        self._tri(p, hs["ow"], QColor(250, 250, 252))
        p.end()

    def _tri(self, p, at, fill):
        x, y = at
        t = self.TRI
        poly = QPolygonF([QPointF(x, y), QPointF(x - t, y + t * 1.55), QPointF(x + t, y + t * 1.55)])
        p.setPen(QPen(QColor(140, 140, 146), 1))
        p.setBrush(fill)
        p.drawPolygon(poly)


# =============================================================================================== panel
def _spin(lo, hi, decimals=0, width=54):
    s = QDoubleSpinBox() if decimals else QSpinBox()
    if decimals:
        s.setDecimals(decimals)
        s.setSingleStep(0.01)
    s.setRange(lo, hi)
    s.setFixedWidth(width)
    s.setAlignment(Qt.AlignmentFlag.AlignCenter)
    s.setKeyboardTracking(False)
    return s


class AdjustPanel(QWidget):
    """Emits changed (live, while dragging) and committed (finished edit, for undo)."""
    changed = Signal()
    committed = Signal()
    compareHeld = Signal(bool)
    copyRequested = Signal()
    saveRequested = Signal()
    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setFixedWidth(300)
        self.adj = Adjustments()
        self._sync = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 12, 16, 8)
        lay.setSpacing(5)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        head = QHBoxLayout()
        t = QLabel("Adjust", objectName="Title")
        head.addWidget(t)
        head.addStretch(1)
        self.btn_reset = QPushButton("Reset All")
        self.btn_reset.setToolTip("Remove all adjustments from this photo")
        self.btn_reset.clicked.connect(self.resetRequested)
        head.addWidget(self.btn_reset)
        lay.addLayout(head)

        # ---- levels
        lh = QHBoxLayout()
        lh.addWidget(section("Levels"))
        lh.addStretch(1)
        self.btn_auto = QPushButton("Auto")
        self.btn_auto.setToolTip("Set black and white points for each channel automatically (clips 0.1 %)")
        self.btn_auto.clicked.connect(self._auto)
        lh.addWidget(self.btn_auto)
        self.btn_lreset = QPushButton("Reset")
        self.btn_lreset.setToolTip("Reset Levels for this channel")
        self.btn_lreset.clicked.connect(self._reset_levels)
        lh.addWidget(self.btn_lreset)
        lay.addLayout(lh)
        self.lch = Segmented(list(CH_LABELS))
        self.lch.changed.connect(lambda i: self._set_lch(CHANNELS[i]))
        lay.addWidget(self.lch)
        self.levels = LevelsEditor()
        self.levels.changed.connect(self._levels_dragged)
        self.levels.committed.connect(self.committed)
        lay.addWidget(self.levels)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.s_b, self.s_g, self.s_w = _spin(0, 253), _spin(0.01, 9.99, 2), _spin(2, 255)
        for s, tip in ((self.s_b, "Input black point"), (self.s_g, "Midtones (gamma)"), (self.s_w, "Input white point")):
            s.setToolTip(tip)
            s.valueChanged.connect(self._levels_typed)
        row.addWidget(QLabel("Input", objectName="Secondary"))
        row.addStretch(1)
        row.addWidget(self.s_b)
        row.addWidget(self.s_g)
        row.addWidget(self.s_w)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.s_ob, self.s_ow = _spin(0, 255), _spin(0, 255)
        for s, tip in ((self.s_ob, "Output black"), (self.s_ow, "Output white")):
            s.setToolTip(tip)
            s.valueChanged.connect(self._levels_typed)
        row2.addWidget(QLabel("Output", objectName="Secondary"))
        row2.addStretch(1)
        row2.addWidget(self.s_ob)
        row2.addSpacing(60)
        row2.addWidget(self.s_ow)
        lay.addLayout(row2)
        lay.addSpacing(8)

        # ---- curves
        ch = QHBoxLayout()
        ch.addWidget(section("Curves"))
        ch.addStretch(1)
        self.btn_creset = QPushButton("Reset")
        self.btn_creset.setToolTip("Reset the curve for this channel")
        self.btn_creset.clicked.connect(self._reset_curve)
        ch.addWidget(self.btn_creset)
        lay.addLayout(ch)
        self.cch = Segmented(list(CH_LABELS))
        self.cch.changed.connect(lambda i: self._set_cch(CHANNELS[i]))
        lay.addWidget(self.cch)
        self.curve = CurveEditor()
        self.curve.changed.connect(self._curve_dragged)
        self.curve.committed.connect(self.committed)
        self.curve.selectionChanged.connect(self._sync_point)
        lay.addWidget(self.curve)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.s_in, self.s_out = _spin(0, 255), _spin(0, 255)
        self.s_in.setToolTip("Selected point: input")
        self.s_out.setToolTip("Selected point: output")
        self.s_in.valueChanged.connect(lambda v: self._point_typed(x=v))
        self.s_out.valueChanged.connect(lambda v: self._point_typed(y=v))
        prow.addWidget(QLabel("Input", objectName="Secondary"))
        prow.addWidget(self.s_in)
        prow.addStretch(1)
        prow.addWidget(QLabel("Output", objectName="Secondary"))
        prow.addWidget(self.s_out)
        lay.addLayout(prow)
        hint = QLabel("Click the graph to add a point. Drag a point off the graph, or double-click it, to remove it.",
                      objectName="Tertiary")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

        # ---- footer
        foot = QWidget()
        f = QHBoxLayout(foot)
        f.setContentsMargins(16, 10, 16, 14)
        f.setSpacing(6)
        self.btn_compare = QPushButton("Compare")
        self.btn_compare.setToolTip("Hold to see the original (or hold \\ )")
        self.btn_compare.pressed.connect(lambda: self.compareHeld.emit(True))
        self.btn_compare.released.connect(lambda: self.compareHeld.emit(False))
        f.addWidget(self.btn_compare)
        f.addStretch(1)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setToolTip("Copy the adjusted photo to the clipboard (Ctrl+C)")
        self.btn_copy.clicked.connect(self.copyRequested)
        f.addWidget(self.btn_copy)
        self.btn_save = QPushButton("Save…")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setToolTip("Save the adjusted photo at full quality (Ctrl+S)")
        self.btn_save.clicked.connect(self.saveRequested)
        f.addWidget(self.btn_save)
        outer.addWidget(foot)
        self.set_adjustments(self.adj)

    # ------------------------------------------------------------------ state
    def set_adjustments(self, adj, hists=None):
        self.adj = adj
        self.levels.adj = adj
        self.curve.adj = adj
        self.set_hists(hists)
        self.curve.sel = None
        self._sync_levels()
        self._sync_point()
        self.levels.update()
        self.curve.update()

    def set_hists(self, hists):
        self.levels.hist = hists
        self._update_curve_hist()
        self.levels.update()

    def _update_curve_hist(self):
        """Curves sits after Levels, so its histogram is the Levels result (remapped bins, no pixel work)."""
        h = self.levels.hist
        if h is None or self.adj.levels_identity():
            self.curve.hist = h
        else:
            only = Adjustments({"levels": self.adj.to_dict()["levels"]})
            t = tables(only, False)
            self.curve.hist = [np.bincount(t[c], weights=h[c], minlength=256) for c in range(3)]
        self.curve.update()

    def set_enabled(self, on):
        for w in (self.levels, self.curve, self.btn_auto, self.btn_save, self.btn_copy, self.btn_compare,
                  self.btn_reset, self.btn_lreset, self.btn_creset):
            w.setEnabled(on)

    def _set_lch(self, ch):
        self.levels.set_channel(ch)
        self._sync_levels()

    def _set_cch(self, ch):
        self.curve.set_channel(ch)

    def _sync_levels(self):
        self._sync = True
        b, g, w, ob, ow = self.levels.lv
        self.s_b.setMaximum(max(0, int(w) - 2))
        self.s_w.setMinimum(min(255, int(b) + 2))
        self.s_b.setValue(int(b))
        self.s_g.setValue(g)
        self.s_w.setValue(int(w))
        self.s_ob.setValue(int(ob))
        self.s_ow.setValue(int(ow))
        self._sync = False

    def _sync_point(self):
        self._sync = True
        sel = self.curve.sel
        on = sel is not None and sel < len(self.curve.pts)
        self.s_in.setEnabled(on)
        self.s_out.setEnabled(on)
        if on:
            x, y = self.curve.pts[sel]
            self.s_in.setValue(int(x))
            self.s_out.setValue(int(y))
        self._sync = False

    def _levels_dragged(self):
        self._sync_levels()
        self._update_curve_hist()
        self.changed.emit()

    def _levels_typed(self):
        if self._sync:
            return
        lv = self.levels.lv
        lv[0], lv[1], lv[2] = float(self.s_b.value()), float(self.s_g.value()), float(self.s_w.value())
        lv[3], lv[4] = float(self.s_ob.value()), float(self.s_ow.value())
        self._sync_levels()
        self._update_curve_hist()
        self.levels.update()
        self.changed.emit()
        self.committed.emit()

    def _curve_dragged(self):
        self.changed.emit()

    def _point_typed(self, x=None, y=None):
        if self._sync:
            return
        self.curve.set_selected(x, y)
        self._sync_point()

    def _reset_levels(self):
        self.adj.levels[self.levels.ch] = default_levels()
        self._sync_levels()
        self._update_curve_hist()
        self.levels.update()
        self.changed.emit()
        self.committed.emit()

    def _reset_curve(self):
        self.adj.curves[self.curve.ch] = default_curve()
        self.curve.sel = None
        self._sync_point()
        self.curve.update()
        self.changed.emit()
        self.committed.emit()

    def _auto(self):
        if self.levels.hist is None:
            return
        for c, lv in auto_levels(self.levels.hist).items():
            self.adj.levels[c] = lv
        self.adj.levels["rgb"] = default_levels()
        self._sync_levels()
        self._update_curve_hist()
        self.levels.update()
        self.changed.emit()
        self.committed.emit()
