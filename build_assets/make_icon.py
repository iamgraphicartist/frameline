"""Render both app icons: <app>.ico (multi-size), <app>.png and a macOS <app>.iconset (iconutil makes the .icns)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from frameline import appicon as fl
from stillframe import appicon as sf
here = os.path.dirname(os.path.abspath(__file__))

for name, render, save_ico in (("frameline", fl.render, fl.save_ico), ("stillframe", sf.render, sf.save_ico)):
    save_ico(os.path.join(here, f"{name}.ico"))
    render(512).save(os.path.join(here, f"{name}.png"))
    iconset = os.path.join(here, f"{name}.iconset")
    os.makedirs(iconset, exist_ok=True)
    for s in (16, 32, 128, 256, 512):
        render(s).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
        render(s * 2).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
    print(f"{name} icons saved")
