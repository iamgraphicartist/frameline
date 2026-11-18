"""Render the app icon to build_assets/frameline.ico (multi-size) and frameline.png."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from frameline.appicon import save_ico, render
here = os.path.dirname(os.path.abspath(__file__))
save_ico(os.path.join(here, "frameline.ico"))
render(512).save(os.path.join(here, "frameline.png"))
print("icon saved")

# macOS iconset (turned into .icns by `iconutil` on the Mac build machine)
iconset = os.path.join(here, "frameline.iconset")
os.makedirs(iconset, exist_ok=True)
for s in (16, 32, 128, 256, 512):
    render(s).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
    render(s * 2).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
print("iconset saved")
