"""SF-Symbols-style line icons rendered from inline SVG (some paths adapted from Feather, MIT)."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor
from PySide6.QtSvg import QSvgRenderer

S = 'stroke="{c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" fill="none"'
F = 'fill="{c}" stroke="none"'

_P = {
    "play": f'<path {F} d="M7 4.9v14.2a1.1 1.1 0 0 0 1.7.93l11.2-7.1a1.1 1.1 0 0 0 0-1.86L8.7 3.97A1.1 1.1 0 0 0 7 4.9z"/>',
    "pause": f'<rect {F} x="6" y="4.5" width="4.2" height="15" rx="1.3"/><rect {F} x="13.8" y="4.5" width="4.2" height="15" rx="1.3"/>',
    "reverse": f'<path {F} d="M17 4.9v14.2a1.1 1.1 0 0 1-1.7.93L4.1 12.93a1.1 1.1 0 0 1 0-1.86l11.2-7.1A1.1 1.1 0 0 1 17 4.9z"/>',
    "step_fwd": f'<path {F} d="M6 6.2v11.6a1 1 0 0 0 1.55.83l8.6-5.8a1 1 0 0 0 0-1.66l-8.6-5.8A1 1 0 0 0 6 6.2z"/><rect {F} x="17.2" y="5.5" width="2.4" height="13" rx="1"/>',
    "step_back": f'<path {F} d="M18 6.2v11.6a1 1 0 0 1-1.55.83l-8.6-5.8a1 1 0 0 1 0-1.66l8.6-5.8A1 1 0 0 1 18 6.2z"/><rect {F} x="4.4" y="5.5" width="2.4" height="13" rx="1"/>',
    "to_start": f'<rect {F} x="3" y="5.5" width="2.2" height="13" rx="1"/><path {F} d="M13.5 6.6v10.8a.9.9 0 0 1-1.4.74L5.9 12.74a.9.9 0 0 1 0-1.48l6.2-4.4a.9.9 0 0 1 1.4.74z"/><path {F} d="M21 6.6v10.8a.9.9 0 0 1-1.4.74l-6.2-4.4a.9.9 0 0 1 0-1.48l6.2-4.4A.9.9 0 0 1 21 6.6z"/>',
    "to_end": f'<rect {F} x="18.8" y="5.5" width="2.2" height="13" rx="1"/><path {F} d="M10.5 6.6v10.8a.9.9 0 0 0 1.4.74l6.2-4.4a.9.9 0 0 0 0-1.48l-6.2-4.4a.9.9 0 0 0-1.4.74z"/><path {F} d="M3 6.6v10.8a.9.9 0 0 0 1.4.74l6.2-4.4a.9.9 0 0 0 0-1.48L4.4 5.86A.9.9 0 0 0 3 6.6z"/>',
    "loop": f'<path {S} d="M17 2.5l3 3-3 3"/><path {S} d="M4 11.5v-1a5 5 0 0 1 5-5h11"/><path {S} d="M7 21.5l-3-3 3-3"/><path {S} d="M20 12.5v1a5 5 0 0 1-5 5H4"/>',
    "pingpong": f'<path {S} d="M16 3l4 4-4 4"/><path {S} d="M20 7H4"/><path {S} d="M8 21l-4-4 4-4"/><path {S} d="M4 17h16"/>',
    "once": f'<path {S} d="M3.5 12h13"/><path {S} d="M12 7l5 5-5 5"/><path {S} d="M20.5 5v14"/>',
    "volume": f'<path {S} d="M11 5L6 9H3v6h3l5 4V5z"/><path {S} d="M15.5 8.5a5 5 0 0 1 0 7"/><path {S} d="M18.5 5.5a9 9 0 0 1 0 13"/>',
    "mute": f'<path {S} d="M11 5L6 9H3v6h3l5 4V5z"/><path {S} d="M22 9l-6 6"/><path {S} d="M16 9l6 6"/>',
    "plus": f'<path {S} d="M12 5v14"/><path {S} d="M5 12h14"/>',
    "folder": f'<path {S} d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.6l2 2.2h7.4A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "sidebar": f'<rect {S} x="3" y="4.5" width="18" height="15" rx="3"/><path {S} d="M9.5 4.5v15"/><path {S} d="M5.5 8.5h1.5M5.5 11h1.5"/>',
    "inspector": f'<rect {S} x="3" y="4.5" width="18" height="15" rx="3"/><path {S} d="M14.5 4.5v15"/><path {S} d="M17 8.5h1.5M17 11h1.5"/>',
    "pen": f'<path {S} d="M16.2 3.8a2.2 2.2 0 0 1 3.1 3.1L8 18.2l-4.2 1 1-4.2z"/><path {S} d="M14.3 5.7l3 3"/>',
    "line": f'<path {S} d="M5 19L19 5"/>',
    "arrow": f'<path {S} d="M5 19L19 5"/><path {S} d="M10 5h9v9"/>',
    "rect": f'<rect {S} x="4" y="6" width="16" height="12" rx="2"/>',
    "ellipse": f'<ellipse {S} cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "text": f'<path {S} d="M5 7V5h14v2"/><path {S} d="M12 5v14"/><path {S} d="M9 19h6"/>',
    "eraser": f'<path {S} d="M20 20H8.5l-4.4-4.4a1.6 1.6 0 0 1 0-2.3l9.4-9.4a1.6 1.6 0 0 1 2.3 0l4.4 4.4a1.6 1.6 0 0 1 0 2.3L11.5 19.3"/><path {S} d="M8.6 9l6.4 6.4"/>',
    "pointer": f'<path {S} d="M6 3.5l12.5 6.8-5.6 1.6-2.7 5.6z"/>',
    "undo": f'<path {S} d="M9 14L4 9l5-5"/><path {S} d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": f'<path {S} d="M15 14l5-5-5-5"/><path {S} d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "trash": f'<path {S} d="M4 7h16"/><path {S} d="M10 11v6"/><path {S} d="M14 11v6"/><path {S} d="M5.5 7l1 12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2l1-12"/><path {S} d="M9 7V4.5h6V7"/>',
    "compare": f'<rect {S} x="3" y="5" width="18" height="14" rx="2.5"/><path {S} d="M12 3v18"/><path fill="{{c}}" fill-opacity=".4" d="M12 5h6.5A2.5 2.5 0 0 1 21 7.5v9a2.5 2.5 0 0 1-2.5 2.5H12z"/>',
    "fit": f'<path {S} d="M4 9V5h4"/><path {S} d="M20 9V5h-4"/><path {S} d="M4 15v4h4"/><path {S} d="M20 15v4h-4"/>',
    "fullscreen": f'<path {S} d="M14 4h6v6"/><path {S} d="M20 4l-6.5 6.5"/><path {S} d="M10 20H4v-6"/><path {S} d="M4 20l6.5-6.5"/>',
    "marker": f'<path {S} d="M6.5 3.5h11v17l-5.5-4.2-5.5 4.2z"/>',
    "camera": f'<path {S} d="M3.5 8.5a2 2 0 0 1 2-2h2.2L9.3 4.5h5.4l1.6 2h2.2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><circle {S} cx="12" cy="12.8" r="3.5"/>',
    "more": f'<circle {S} cx="12" cy="12" r="9.2"/><circle {F} cx="7.8" cy="12" r="1.3"/><circle {F} cx="12" cy="12" r="1.3"/><circle {F} cx="16.2" cy="12" r="1.3"/>',
    "in_point": f'<path {S} d="M13 4.5H8.5v15H13"/><path {S} d="M16 12h-3.5"/>',
    "out_point": f'<path {S} d="M11 4.5h4.5v15H11"/><path {S} d="M8 12h3.5"/>',
    "film": f'<rect {S} x="3" y="4" width="18" height="16" rx="2.5"/><path {S} d="M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/>',
    "sequence": f'<rect {S} x="7" y="7" width="13.5" height="11" rx="2"/><path {S} d="M4 15.5V6a2 2 0 0 1 2-2h10"/>',
    "photo": f'<rect {S} x="3" y="4.5" width="18" height="15" rx="2.5"/><circle {S} cx="9" cy="10" r="1.8"/><path {S} d="M21 15.5l-5-5L5.5 19.5"/>',
    "onion": f'<rect {S} x="9" y="9" width="11.5" height="11.5" rx="2"/><path {S} stroke-opacity=".55" d="M6 15H5.5A1.8 1.8 0 0 1 3.7 13.2V5.5A1.8 1.8 0 0 1 5.5 3.7h7.7A1.8 1.8 0 0 1 15 5.5V6"/>',
    "grid": f'<rect {S} x="3.5" y="4.5" width="17" height="15" rx="2"/><path {S} d="M9.2 4.5v15M14.8 4.5v15M3.5 9.5h17M3.5 14.5h17"/>',
    "search": f'<circle {S} cx="10.8" cy="10.8" r="6.3"/><path {S} d="M15.6 15.6l4.6 4.6"/>',
    "close": f'<path {S} d="M6 6l12 12M18 6L6 18"/>',
    "info": f'<circle {S} cx="12" cy="12" r="9.2"/><path {S} d="M12 11v5.5"/><circle {F} cx="12" cy="7.8" r="1.1"/>',
    "speed": f'<path {S} d="M3.8 16.5a8.5 8.5 0 1 1 16.4 0"/><path {S} d="M12 14l4.2-4.2"/><circle {F} cx="12" cy="14" r="1.5"/>',
    "swap": f'<path {S} d="M7 4L3 8l4 4"/><path {S} d="M3 8h14"/><path {S} d="M17 12l4 4-4 4"/><path {S} d="M21 16H7"/>',
    "eye": f'<path {S} d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle {S} cx="12" cy="12" r="3"/>',
    "save": f'<path {S} d="M5 3.5h11l3.5 3.5v11.5a2 2 0 0 1-2 2h-12.5a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/><path {S} d="M8 3.5v5h7v-5M7.5 20.5v-6h9v6"/>',
    "drop": f'<path {S} d="M12 3.5v11"/><path {S} d="M7.5 10l4.5 4.5 4.5-4.5"/><path {S} d="M4 15.5v2.5a2.5 2.5 0 0 0 2.5 2.5h11a2.5 2.5 0 0 0 2.5-2.5v-2.5"/>',
}


# Photo-viewer glyphs (Stillframe)
_P.update({
    "rotate_left": f'<path {S} d="M4.5 8.5V4"/><path {S} d="M4.5 8.5H9"/><path {S} d="M5.2 8.2A8 8 0 1 1 4 13.5"/>',
    "rotate_right": f'<path {S} d="M19.5 8.5V4"/><path {S} d="M19.5 8.5H15"/><path {S} d="M18.8 8.2A8 8 0 1 0 20 13.5"/>',
    "chevron_left": f'<path {S} d="M15 5l-7 7 7 7"/>',
    "chevron_right": f'<path {S} d="M9 5l7 7-7 7"/>',
    "zoom_in": f'<circle {S} cx="10.5" cy="10.5" r="6.5"/><path {S} d="M15.5 15.5L20.5 20.5"/><path {S} d="M10.5 7.8v5.4M7.8 10.5h5.4"/>',
    "zoom_out": f'<circle {S} cx="10.5" cy="10.5" r="6.5"/><path {S} d="M15.5 15.5L20.5 20.5"/><path {S} d="M7.8 10.5h5.4"/>',
    "slideshow": f'<rect {S} x="3" y="4.5" width="18" height="12.5" rx="2.5"/><path {F} d="M10.2 8.2v5.1a.6.6 0 0 0 .92.5l3.9-2.55a.6.6 0 0 0 0-1l-3.9-2.55a.6.6 0 0 0-.92.5z"/><path {S} d="M8.5 20h7"/>',
    "copy": f'<rect {S} x="8" y="8" width="12" height="12" rx="2.5"/><path {S} d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8"/>',
    "filmstrip": f'<rect {S} x="3" y="6" width="18" height="12" rx="2.5"/><path {S} d="M8 6v12M16 6v12"/>',
    "heart": f'<path {S} d="M12 20s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.2a4.4 4.4 0 0 1 7.5 2.7C19.5 15.4 12 20 12 20z"/>',
    "heart_fill": f'<path {F} d="M12 20s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.2a4.4 4.4 0 0 1 7.5 2.7C19.5 15.4 12 20 12 20z"/>',
})


def svg(name, color="#FFFFFF"):
    body = _P[name].replace("{c}", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


_cache = {}


def pixmap(name, color, size=18, dpr=2.0):
    key = (name, color, size, dpr)
    if key in _cache:
        return _cache[key]
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def icon(name, color, checked_color=None, size=18):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, checked_color or color, size), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, QColor(color).darker(170).name() if QColor(color).lightness() > 128 else "#B0B0B5", size),
                 QIcon.Mode.Disabled, QIcon.State.Off)
    return ic
