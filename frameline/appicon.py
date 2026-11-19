"""App icon: a pixel-mosaic play button in a pastel-to-violet spectrum on a dark tile, drawn in code."""
import random
import struct

from PySide6.QtCore import Qt, QRectF, QPointF, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap, QIcon

S = 1024                      # master canvas
BX, BY, BW, BH = 92, 84, 840, 840
RAD = 190

# spectrum from the triangle's lower-left to its tip
STOPS = ["#FFF3B8", "#DDFBC9", "#8EEB8A", "#3FC9A6", "#2AA7DE", "#FFD3C2",
         "#F9B7C8", "#FF8C9C", "#F567B4", "#E04CD6", "#B54EE2", "#7C5BDF", "#4D3CC9", "#2F2097"]

CELL = 52
HEIGHTS = [11, 11, 9, 9, 7, 7, 5, 3, 1]   # cells per column: a stepped, symmetric play triangle
COLS, ROWS = len(HEIGHTS), HEIGHTS[0]


def _lerp(c1, c2, t):
    return QColor(int(c1.red() + (c2.red() - c1.red()) * t),
                  int(c1.green() + (c2.green() - c1.green()) * t),
                  int(c1.blue() + (c2.blue() - c1.blue()) * t))


def _spectrum(t):
    t = max(0.0, min(1.0, t)) * (len(STOPS) - 1)
    i = min(int(t), len(STOPS) - 2)
    return _lerp(QColor(STOPS[i]), QColor(STOPS[i + 1]), t - i)


def _cells():
    out = []
    for c, h in enumerate(HEIGHTS):
        top = (ROWS - h) // 2
        out += [(c, r) for r in range(top, top + h)]
    return out


def begin_tile():
    """Transparent master canvas with the dark rounded tile and its shadow; returns (image, painter)."""
    img = QImage(S, S, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # soft drop shadow, offset down-left like a lit object
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(26, 0, -1):
        p.setBrush(QColor(0, 0, 0, 6))
        p.drawRoundedRect(QRectF(BX - 10 - i * 0.7, BY + 22 + i * 0.5, BW + i * 0.8, BH + i * 0.6), RAD + i, RAD + i)

    # tile
    p.setBrush(QColor(36, 36, 37))
    p.drawRoundedRect(QRectF(BX, BY, BW, BH), RAD, RAD)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QColor(255, 255, 255, 14))
    p.drawRoundedRect(QRectF(BX + 2, BY + 2, BW - 4, BH - 4), RAD - 2, RAD - 2)
    return img, p


def render_master():
    img, p = begin_tile()

    # mosaic play triangle (optically centred: nudged right of the tile centre)
    cells = _cells()
    x0 = S / 2 - COLS * CELL / 2 + CELL * 0.6
    y0 = S / 2 - ROWS * CELL / 2
    rng = random.Random(5)
    raw = {cr: cr[0] + (ROWS - 1 - cr[1]) * 0.75 for cr in cells}
    lo, hi = min(raw.values()), max(raw.values())
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(Qt.PenStyle.NoPen)
    for c, r in cells:
        t = (raw[(c, r)] - lo) / (hi - lo)          # lower-left pale -> tip deep indigo
        t += rng.uniform(-0.035, 0.035)
        col = _spectrum(t)
        if rng.random() < 0.08:                     # occasional off-hue tile for the mosaic feel
            col = _spectrum(t + rng.choice((-0.12, 0.12)))
        p.setBrush(col)
        p.drawRect(QRectF(x0 + c * CELL, y0 + r * CELL, CELL, CELL))
    p.end()
    return img


_MASTERS = {}


def render(size, master_fn=None):
    master_fn = master_fn or render_master
    if master_fn not in _MASTERS:
        _MASTERS[master_fn] = master_fn()
    img = _MASTERS[master_fn]
    while img.width() // 2 >= size * 1.5:
        img = img.scaled(img.width() // 2, img.height() // 2, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def qicon(master_fn=None):
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(render(s, master_fn)))
    return ic


def save_ico(path, sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256), master_fn=None):
    """Write a multi-resolution .ico with PNG-compressed entries."""
    blobs = []
    for s in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render(s, master_fn).save(buf, "PNG")
        buf.close()
        blobs.append((s, bytes(ba.data())))
    out = struct.pack("<HHH", 0, 1, len(blobs))
    off = 6 + 16 * len(blobs)
    for s, b in blobs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    with open(path, "wb") as f:
        f.write(out + b"".join(b for _, b in blobs))
