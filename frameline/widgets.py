"""Apple-style controls: segmented control, switch, icon buttons, colour swatches."""
from PySide6.QtCore import Qt, QRectF, Signal, QSize, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF
from PySide6.QtWidgets import QWidget, QToolButton, QLabel, QHBoxLayout, QSizePolicy

from . import theme, icons
from .theme import qc

_ICON_BUTTONS = []


def icon_button(name, tip="", checkable=False, size=18, accent_when_checked=False, box=30):
    b = QToolButton()
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setFixedSize(box, box)
    b.setIconSize(QSize(size, size))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b._icon_name = name
    b._icon_size = size
    b._accent = accent_when_checked
    if accent_when_checked:
        b.setObjectName("Accent")
    refresh_icon(b)
    _ICON_BUTTONS.append(b)
    return b


def refresh_icon(b, name=None):
    if name:
        b._icon_name = name
    on = "#FFFFFF" if b._accent else theme.qc("accent").name()
    b.setIcon(icons.icon(b._icon_name, theme.qc("text").name(), on, b._icon_size))


def refresh_all_icons():
    for b in list(_ICON_BUTTONS):
        try:
            refresh_icon(b)
        except RuntimeError:
            _ICON_BUTTONS.remove(b)


class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, items, parent=None, height=26, icon_items=False):
        super().__init__(parent)
        self.items = items
        self.icon_items = icon_items
        self.index = 0
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        f = theme.font(11.5, QFont.Weight.Medium)
        fm = QFontMetricsF(f)
        if icon_items:
            self.setMinimumWidth(len(items) * 36)
        else:
            self.setMinimumWidth(int(sum(min(fm.horizontalAdvance(t) + 10, 44) for t in items)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._x = 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._x = v
        self.update()

    def set_index(self, i, emit=False, animate=True):
        i = max(0, min(len(self.items) - 1, i))
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(float(self._x))
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._x = float(i)
        self.index = i
        self.update()
        if emit:
            self.changed.emit(i)

    def mousePressEvent(self, e):
        n = len(self.items)
        i = int(e.position().x() / (self.width() / n))
        if i != self.index:
            self.set_index(i, emit=True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        dark = theme.T["name"] == "dark"
        bg = QColor(255, 255, 255, 18) if dark else QColor(0, 0, 0, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 7, 7)
        n = len(self.items)
        sw = r.width() / n
        sel = QRectF(r.x() + 2 + self._x * sw, r.y() + 2, sw - 4, r.height() - 4)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRoundedRect(sel.translated(0, 0.8), 5.5, 5.5)
        p.setBrush(QColor(100, 100, 106) if dark else QColor(255, 255, 255))
        p.drawRoundedRect(sel, 5.5, 5.5)
        p.setPen(QPen(qc("separator"), 1))
        for k in range(1, n):
            if abs(k - self._x) > 0.6 and abs(k - 1 - self._x) > 0.6:
                x = r.x() + k * sw
                p.drawLine(QPointF(x, r.y() + 7), QPointF(x, r.bottom() - 7))
        for k, t in enumerate(self.items):
            p.setFont(theme.font(11.5, QFont.Weight.DemiBold if k == self.index else QFont.Weight.Normal))
            cell = QRectF(r.x() + k * sw, r.y(), sw, r.height())
            if self.icon_items:
                pm = icons.pixmap(t, qc("text").name(), 15)
                p.drawPixmap(int(cell.center().x() - 7.5), int(cell.center().y() - 7.5), pm)
            else:
                p.setPen(qc("text") if k == self.index else qc("text2"))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, t)
        p.end()


class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.checked = checked
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def set_checked(self, v, emit=False):
        self.checked = bool(v)
        self._anim.stop()
        self._anim.setStartValue(float(self._pos))
        self._anim.setEndValue(1.0 if self.checked else 0.0)
        self._anim.start()
        if emit:
            self.toggled.emit(self.checked)

    def mousePressEvent(self, _):
        self.set_checked(not self.checked, emit=True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        off = QColor(255, 255, 255, 40) if theme.T["name"] == "dark" else QColor(0, 0, 0, 30)
        on = qc("accent")
        t = self._pos
        col = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t), int(off.alpha() + (255 - off.alpha()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.x() + 2 + (r.width() - d - 4) * t
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QRectF(x, r.y() + 2.6, d, d))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, r.y() + 2, d, d))
        p.end()


class Swatch(QWidget):
    clicked = Signal(str)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = color
        self.selected = False
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color)

    def mousePressEvent(self, _):
        self.clicked.emit(self.color)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.selected:
            p.setPen(QPen(qc("text2"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(QColor(self.color))
        p.drawEllipse(r)
        p.end()


def row(label_text, widget, stretch=True):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(8)
    lab = QLabel(label_text)
    lay.addWidget(lab)
    if stretch:
        lay.addStretch(1)
    lay.addWidget(widget)
    return w


def section(text):
    l = QLabel(text.upper())
    l.setObjectName("Section")
    return l
