"""Stillframe icon: a pixel-mosaic landscape (sun over two peaks) on Frameline's dark tile."""
import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from frameline import appicon as base

# 13 x 9 cells: S = sun, M = mountains
ART = [
    ".........SS..",
    "........SSSS.",
    "...M....SSSS.",
    "..MMM....SS..",
    ".MMMMM..M....",
    "MMMMMMMMMM...",
    "MMMMMMMMMMMM.",
    "MMMMMMMMMMMMM",
    "MMMMMMMMMMMMM",
]
CELL = 54


def render_master():
    img, p = base.begin_tile()
    rows, cols = len(ART), len(ART[0])
    x0 = base.S / 2 - cols * CELL / 2
    y0 = base.S / 2 - rows * CELL / 2 + CELL * 0.2
    rng = random.Random(9)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(Qt.PenStyle.NoPen)
    for r, line in enumerate(ART):
        for c, ch in enumerate(line):
            if ch == ".":
                continue
            if ch == "S":
                t = 0.40 + rng.uniform(-0.04, 0.06)        # peach / pink sun
            else:
                # peaks: deep violet at the summits fading to pale greens at the foot
                t = 0.95 - (r / (rows - 1)) * 0.95 + (c / cols) * 0.08
                t += rng.uniform(-0.035, 0.035)
                if rng.random() < 0.08:
                    t += rng.choice((-0.12, 0.12))
            p.setBrush(base._spectrum(t))
            p.drawRect(QRectF(x0 + c * CELL, y0 + r * CELL, CELL, CELL))
    p.end()
    return img


def render(size):
    return base.render(size, render_master)


def qicon():
    return base.qicon(render_master)


def save_ico(path):
    base.save_ico(path, master_fn=render_master)
