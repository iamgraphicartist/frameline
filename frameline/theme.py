"""Visual language: macOS-inspired palettes, typography and the global stylesheet."""
import re
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase

# Sizes are tuned on Windows (96 dpi). macOS renders 1pt = 1px, so scale up to match.
PT = 4 / 3 if sys.platform == "darwin" else 1.0


def pt(v):
    """A CSS point size, scaled for the platform."""
    return f"{v * PT:.2f}pt"


def _scale_pts(css_text):
    if PT == 1.0:
        return css_text
    return re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: pt(float(m.group(1))), css_text)

DARK = {
    "name": "dark",
    "window": (30, 30, 32),
    "toolbar": (40, 40, 43),
    "sidebar": (36, 36, 39),
    "panel": (44, 44, 47),
    "card": (52, 52, 56),
    "control": (64, 64, 68),
    "control_hover": (76, 76, 81),
    "control_pressed": (92, 92, 97),
    "field": (28, 28, 30),
    "separator": (255, 255, 255, 22),
    "hairline": (0, 0, 0, 120),
    "text": (245, 245, 247),
    "text2": (174, 174, 178),
    "text3": (110, 110, 115),
    "accent": (10, 132, 255),
    "accent_text": (255, 255, 255),
    "viewer": (18, 18, 20),
    "timeline": (26, 26, 28),
    "track": (34, 34, 37),
    "ruler": (32, 32, 35),
    "playhead": (255, 69, 58),
    "range": (255, 214, 10),
    "cache": (48, 209, 88),
    "selection": (10, 132, 255, 70),
    "shadow": (0, 0, 0, 140),
}

LIGHT = {
    "name": "light",
    "window": (246, 246, 248),
    "toolbar": (236, 236, 238),
    "sidebar": (232, 232, 236),
    "panel": (242, 242, 245),
    "card": (255, 255, 255),
    "control": (255, 255, 255),
    "control_hover": (244, 244, 246),
    "control_pressed": (226, 226, 230),
    "field": (255, 255, 255),
    "separator": (0, 0, 0, 26),
    "hairline": (0, 0, 0, 40),
    "text": (29, 29, 31),
    "text2": (99, 99, 102),
    "text3": (152, 152, 157),
    "accent": (0, 122, 255),
    "accent_text": (255, 255, 255),
    "viewer": (40, 40, 42),
    "timeline": (238, 238, 241),
    "track": (226, 226, 230),
    "ruler": (232, 232, 236),
    "playhead": (255, 59, 48),
    "range": (230, 170, 0),
    "cache": (40, 180, 75),
    "selection": (0, 122, 255, 60),
    "shadow": (0, 0, 0, 60),
}

# Apple system colours used for annotation swatches, clip tints and markers.
SYSTEM_COLORS = {
    "Red": "#FF453A", "Orange": "#FF9F0A", "Yellow": "#FFD60A", "Green": "#30D158",
    "Mint": "#66D4CF", "Blue": "#0A84FF", "Indigo": "#5E5CE6", "Purple": "#BF5AF2",
    "Pink": "#FF375F", "White": "#FFFFFF", "Black": "#000000",
}
CLIP_COLORS = {"video": "#3D6FE0", "sequence": "#8A5CF0", "image": "#E08A2E"}

T = dict(DARK)


def set_theme(name):
    T.clear()
    T.update(LIGHT if name == "light" else DARK)


def qc(key_or_tuple, alpha=None):
    v = T[key_or_tuple] if isinstance(key_or_tuple, str) else key_or_tuple
    c = QColor(*v)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def css(key):
    v = T[key]
    if len(v) == 4:
        return f"rgba({v[0]},{v[1]},{v[2]},{v[3]})"
    return f"rgb({v[0]},{v[1]},{v[2]})"


_UI_FAMILY = None
_MONO_FAMILY = None


def ui_family():
    global _UI_FAMILY
    if _UI_FAMILY is None:
        if sys.platform == "darwin":
            _UI_FAMILY = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
            return _UI_FAMILY
        fams = set(QFontDatabase.families())
        for f in ("SF Pro Text", "SF Pro Display", "Inter", "Segoe UI Variable Text", "Segoe UI"):
            if f in fams:
                _UI_FAMILY = f
                break
        else:
            _UI_FAMILY = QFont().defaultFamily()
    return _UI_FAMILY


def mono_family():
    global _MONO_FAMILY
    if _MONO_FAMILY is None:
        fams = set(QFontDatabase.families())
        for f in ("SF Mono", "Menlo", "JetBrains Mono", "Cascadia Mono", "Consolas"):
            if f in fams:
                _MONO_FAMILY = f
                break
        else:
            _MONO_FAMILY = "Courier New"
    return _MONO_FAMILY


def font(size=12.5, weight=QFont.Weight.Normal, mono=False):
    if weight == QFont.Weight.Medium:
        weight = QFont.Weight.Normal  # "Medium" resolves to an italic face on Segoe UI Variable
    f = QFont(mono_family() if mono else ui_family())
    f.setPointSizeF(size * 0.77 * PT)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def stylesheet():
    fam = ui_family()
    return _scale_pts(f"""
* {{ font-family: "{fam}"; font-size: 10pt; color: {css('text')}; outline: none; }}
QMainWindow, QWidget#Root {{ background: {css('window')}; }}
QWidget#Toolbar {{ background: {css('toolbar')}; border-bottom: 1px solid {css('hairline')}; }}
QWidget#Sidebar {{ background: {css('sidebar')}; border-right: 1px solid {css('hairline')}; }}
QWidget#Inspector {{ background: {css('sidebar')}; border-left: 1px solid {css('hairline')}; }}
QWidget#Transport {{ background: {css('toolbar')}; border-top: 1px solid {css('hairline')}; }}
QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 10pt; font-weight: 600; }}
QLabel#Subtitle {{ color: {css('text2')}; font-size: 8.5pt; }}
QLabel#Section {{ color: {css('text2')}; font-size: 8pt; font-weight: 600; letter-spacing: 0.4px; padding-top: 6px; }}
QLabel#Secondary {{ color: {css('text2')}; }}
QLabel#Tertiary {{ color: {css('text3')}; font-size: 8.5pt; }}
QLabel#Empty {{ color: {css('text3')}; }}

QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {css('control_hover') if T['name']=='light' else css('control')}; }}
QToolButton:pressed {{ background: {css('control_pressed')}; }}
QToolButton:checked {{ background: {css('control')}; }}
QToolButton#Accent:checked {{ background: {css('accent')}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton {{ background: {css('control')}; border: 1px solid {css('separator')}; border-radius: 6px;
    padding: 4px 12px; min-height: 18px; }}
QPushButton:hover {{ background: {css('control_hover')}; }}
QPushButton:pressed {{ background: {css('control_pressed')}; }}
QPushButton#Primary {{ background: {css('accent')}; color: {css('accent_text')}; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {css('accent')}; }}
QPushButton:disabled {{ color: {css('text3')}; }}

QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {css('field')}; border: 1px solid {css('separator')};
    border-radius: 6px; padding: 3px 7px; selection-background-color: {css('accent')}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {css('accent')}; padding: 2px 6px; }}
QLineEdit#Search {{ border-radius: 8px; padding-left: 8px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QComboBox {{ background: {css('control')}; border: 1px solid {css('separator')}; border-radius: 6px; padding: 3px 9px; min-height: 18px; }}
QComboBox:hover {{ background: {css('control_hover')}; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {css('card')}; border: 1px solid {css('separator')}; border-radius: 8px;
    padding: 4px; selection-background-color: {css('accent')}; selection-color: white; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {css('text3')}; background: {css('field')}; }}
QCheckBox::indicator:checked {{ background: {css('accent')}; border: 3px solid {css('field')};
    outline: 1px solid {css('accent')}; }}

QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {css('control')}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {css('accent')}; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: white;
    border: 1px solid rgba(0,0,0,40); }}

QListWidget {{ background: transparent; border: none; padding: 4px; }}
QListWidget::item {{ border-radius: 8px; padding: 0px; margin: 1px 0; }}
QListWidget::item:selected {{ background: {css('accent')}; }}
QListWidget::item:hover:!selected {{ background: {css('separator')}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {css('text3')}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

QMenu {{ background: {css('card')}; border: 1px solid {css('separator')}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 5px 26px 5px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {css('accent')}; color: white; }}
QMenu::item:disabled {{ color: {css('text3')}; }}
QMenu::separator {{ height: 1px; background: {css('separator')}; margin: 4px 8px; }}
QMenu::indicator {{ width: 12px; left: 6px; }}
QMenu::right-arrow {{ width: 0; }}

QToolTip {{ background: {css('card')}; color: {css('text')}; border: 1px solid {css('separator')}; border-radius: 6px; padding: 4px 8px; }}
QSplitter::handle {{ background: transparent; }}
QDialog {{ background: {css('panel')}; }}
QMessageBox {{ background: {css('panel')}; }}
""")
