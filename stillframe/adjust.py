"""Levels and Curves for Stillframe.

Fidelity rules (the same ones an editor like Photoshop follows):
- Adjustments run on the photo's own pixel values, in its own colour space (sRGB, Display P3, Adobe RGB…).
  The embedded colour profile is kept when saving, so the edit looks the same everywhere.
- Tone curves are evaluated as 65,536-step tables in floating point, so 16-bit PNG/TIFF photos stay 16-bit
  end to end, and 8-bit photos get exactly one rounding step (no banding from chained 8-bit maths).
- Saving never re-uses the on-screen image: it decodes the original again at full resolution.
  JPEG is written at quality 95 with 4:4:4 colour, and EXIF (camera, date, GPS…) is carried over.
"""
import math
import os
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal, Qt, QSize
from PySide6.QtGui import QImage, QImageReader, QImageWriter, QColorSpace, QPainter, QTransform

from .loader import QT_EXTS, PIL_EXTS, FFMPEG_EXTS, _pil, _from_pil

CHANNELS = ("rgb", "r", "g", "b")
N = 65536
_X = np.linspace(0.0, 1.0, N, dtype=np.float64)
_SRGB = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
DEEP = {QImage.Format.Format_RGBA64, QImage.Format.Format_RGBX64, QImage.Format.Format_RGBA64_Premultiplied,
        QImage.Format.Format_Grayscale16, QImage.Format.Format_RGBA16FPx4, QImage.Format.Format_RGBX16FPx4,
        QImage.Format.Format_RGBA16FPx4_Premultiplied, QImage.Format.Format_RGBA32FPx4,
        QImage.Format.Format_RGBX32FPx4, QImage.Format.Format_RGBA32FPx4_Premultiplied}


# ============================================================================================ settings
def default_levels():
    return [0.0, 1.0, 255.0, 0.0, 255.0]          # in black, gamma, in white, out black, out white


def default_curve():
    return [[0.0, 0.0], [255.0, 255.0]]


class Adjustments:
    """Levels then Curves, each with a composite RGB channel plus Red, Green and Blue."""

    def __init__(self, data=None):
        data = data or {}
        self.levels = {c: list(data.get("levels", {}).get(c, default_levels())) for c in CHANNELS}
        self.curves = {c: [list(p) for p in data.get("curves", {}).get(c, default_curve())] for c in CHANNELS}

    def to_dict(self):
        return {"levels": {c: list(v) for c, v in self.levels.items()},
                "curves": {c: [list(p) for p in v] for c, v in self.curves.items()}}

    def copy(self):
        return Adjustments(self.to_dict())

    def __eq__(self, other):
        return isinstance(other, Adjustments) and self.to_dict() == other.to_dict()

    def levels_identity(self, c=None):
        chans = [c] if c else CHANNELS
        return all(self.levels[k] == default_levels() for k in chans)

    def curve_identity(self, c=None):
        chans = [c] if c else CHANNELS
        return all(all(abs(x - y) < 1e-9 for x, y in self.curves[k]) and
                   any(x == 0 for x, _ in self.curves[k]) and any(x == 255 for x, _ in self.curves[k])
                   for k in chans)

    def is_identity(self):
        return self.levels_identity() and self.curve_identity()

    # ------------------------------------------------------------------ tables
    def luts(self):
        """float64 array (3, 65536): output 0..1 for every 16-bit input value, per R, G, B."""
        comp_l = levels_fn(self.levels["rgb"])
        comp_c = curve_fn(self.curves["rgb"])
        out = []
        for c in ("r", "g", "b"):
            v = levels_fn(self.levels[c])(_X)
            v = comp_l(v)
            v = curve_fn(self.curves[c])(v)
            v = comp_c(v)
            out.append(np.clip(v, 0.0, 1.0))
        return np.stack(out)


def levels_fn(lv):
    b, g, w, ob, ow = (float(x) for x in lv)
    b, w, ob, ow = b / 255.0, w / 255.0, ob / 255.0, ow / 255.0
    if (b, g, w, ob, ow) == (0.0, 1.0, 1.0, 0.0, 1.0):
        return lambda x: x
    span = max(w - b, 1e-6)
    inv_g = 1.0 / max(g, 1e-3)

    def f(x):
        t = np.clip((x - b) / span, 0.0, 1.0)
        return ob + (t ** inv_g) * (ow - ob)
    return f


def curve_fn(points):
    """Natural cubic spline through the points (0..255), flat beyond the end points, clamped to 0..1."""
    pts = sorted((float(x) / 255.0, float(y) / 255.0) for x, y in points)
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    if len(pts) == 2 and xs[0] == 0 and xs[1] == 1 and ys[0] == 0 and ys[1] == 1:
        return lambda x: x
    if len(pts) == 2:
        def lin(x):
            t = np.clip((x - xs[0]) / max(xs[1] - xs[0], 1e-9), 0.0, 1.0)
            return ys[0] + t * (ys[1] - ys[0])
        return lin
    m = _spline_second_derivs(xs, ys)

    def f(x):
        x = np.asarray(x, dtype=np.float64)
        xc = np.clip(x, xs[0], xs[-1])
        i = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, len(xs) - 2)
        h = xs[i + 1] - xs[i]
        a = (xs[i + 1] - xc) / h
        bb = (xc - xs[i]) / h
        y = a * ys[i] + bb * ys[i + 1] + ((a ** 3 - a) * m[i] + (bb ** 3 - bb) * m[i + 1]) * h * h / 6.0
        return np.clip(y, 0.0, 1.0)
    return f


def _spline_second_derivs(xs, ys):
    n = len(xs)
    m = np.zeros(n)
    if n < 3:
        return m
    a = np.zeros(n)
    b = np.ones(n)
    c = np.zeros(n)
    d = np.zeros(n)
    for i in range(1, n - 1):
        h0, h1 = xs[i] - xs[i - 1], xs[i + 1] - xs[i]
        a[i], b[i], c[i] = h0 / 6.0, (h0 + h1) / 3.0, h1 / 6.0
        d[i] = (ys[i + 1] - ys[i]) / h1 - (ys[i] - ys[i - 1]) / h0
    for i in range(1, n):          # Thomas algorithm
        w = a[i] / b[i - 1]
        b[i] -= w * c[i - 1]
        d[i] -= w * d[i - 1]
    m[n - 1] = d[n - 1] / b[n - 1]
    for i in range(n - 2, -1, -1):
        m[i] = (d[i] - c[i] * m[i + 1]) / b[i]
    m[0] = m[-1] = 0.0
    return m


def auto_levels(hists, clip=0.001):
    """Per-channel black/white points that clip 0.1 % at each end (like 'Enhance Per Channel Contrast')."""
    out = {}
    for c, h in zip(("r", "g", "b"), hists):
        total = float(h.sum())
        if total <= 0:
            continue
        cum = np.cumsum(h) / total
        lo = int(np.searchsorted(cum, clip))
        hi = int(np.searchsorted(cum, 1.0 - clip))
        lo, hi = max(0, min(lo, 253)), max(lo + 2, min(hi, 255))
        out[c] = [float(lo), 1.0, float(hi), 0.0, 255.0]
    return out


# ============================================================================================ pixels
def load_native(path):
    """Full-resolution decode in the photo's own colour space and bit depth, EXIF orientation applied.

    Returns a QImage in RGBA8888 / RGBX8888 (8-bit) or RGBA64 / RGBX64 (16-bit) with its colour space set."""
    ext = os.path.splitext(path)[1].lower()
    img = QImage()
    if ext in QT_EXTS:
        r = QImageReader(path)
        r.setAutoTransform(True)
        r.setAllocationLimit(4096)
        img = r.read()
    if img.isNull() and ext not in FFMPEG_EXTS:
        try:
            Image = _pil()
            with Image.open(path) as im:
                img = _from_pil(im)
        except Exception:
            img = QImage()
    if img.isNull():
        from frameline.media import read_image
        img = read_image(path)
    return normalise(img)


def normalise(img):
    if img is None or img.isNull():
        return QImage()
    cs = img.colorSpace()
    alpha = img.hasAlphaChannel()
    if img.format() in DEEP:
        out = img.convertToFormat(QImage.Format.Format_RGBA64 if alpha else QImage.Format.Format_RGBX64)
    else:
        out = img.convertToFormat(QImage.Format.Format_RGBA8888 if alpha else QImage.Format.Format_RGBX8888)
    if cs.isValid():
        out.setColorSpace(cs)
    return out


def is_deep(img):
    return img.format() in (QImage.Format.Format_RGBA64, QImage.Format.Format_RGBX64)


def as_array(img):
    """Writable numpy view (H, W, 4) of a normalised image (uint8 or uint16). Keep img alive while using it."""
    dt = np.uint16 if is_deep(img) else np.uint8
    bpp = 8 if dt is np.uint16 else 4
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = np.frombuffer(img.bits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * bpp]
    return buf.view(dt).reshape(h, w, 4)


def tables(adj, deep):
    """Integer lookup tables (3, 256) uint8 or (3, 65536) uint16 for the given bit depth."""
    lut = adj.luts()
    if deep:
        return np.rint(lut * 65535.0).astype(np.uint16)
    return np.rint(lut[:, np.arange(256) * 257] * 255.0).astype(np.uint8)


def apply(img, adj, tabs=None):
    """New QImage (same format and colour space) with the adjustment applied. Alpha is left alone."""
    out = img.copy()
    if adj is None or adj.is_identity():
        return out
    tabs = tables(adj, is_deep(img)) if tabs is None else tabs
    a = as_array(out)
    for c in range(3):
        a[..., c] = tabs[c][a[..., c]]
    return out


def histograms(img, max_side=640):
    """256-bin histograms (r, g, b) of a normalised image, from a reduced copy."""
    if img is None or img.isNull():
        return None
    small = img
    if max(img.width(), img.height()) > max_side:
        small = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        small = normalise(small) if small.format() != img.format() else small
    a = as_array(small)
    if a.dtype == np.uint16:
        a = (a >> 8).astype(np.uint8)
    return [np.bincount(a[..., c].ravel(), minlength=256).astype(np.float64) for c in range(3)]


def to_display(img):
    """sRGB, 8-bit, ready for the screen (the same conversion the viewer uses for unedited photos)."""
    out = img.copy()
    cs = out.colorSpace()
    if cs.isValid() and cs != _SRGB:
        try:
            out.convertToColorSpace(_SRGB)
        except Exception:
            pass
    fmt = QImage.Format.Format_ARGB32_Premultiplied if out.hasAlphaChannel() else QImage.Format.Format_RGB32
    return out.convertToFormat(fmt)


def proxy_of(img, max_side):
    if max(img.width(), img.height()) <= max_side:
        return img
    p = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    p = normalise(p) if p.format() != img.format() else p
    p.setColorSpace(img.colorSpace())
    return p


# ============================================================================================ export
def render_full(native, adj, strokes=(), rotation=0):
    """Full-resolution result in the native colour space and depth: adjustments, then markup, then rotation."""
    from frameline.viewer import draw_strokes
    out = apply(native, adj)
    if strokes:
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_strokes(p, strokes)
        p.end()
    if rotation % 360:
        cs = out.colorSpace()
        out = out.transformed(QTransform().rotate(rotation), Qt.TransformationMode.SmoothTransformation)
        out = normalise(out)
        out.setColorSpace(cs)
    return out


SAVE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP"}


def default_ext(src_path, img):
    ext = os.path.splitext(src_path)[1].lower()
    if ext in SAVE_FORMATS:
        if ext in (".jpg", ".jpeg") and img.hasAlphaChannel():
            return ".png"
        return ".jpg" if ext == ".jpeg" else ext
    if is_deep(img):
        return ".tif"
    return ".png" if img.hasAlphaChannel() else ".jpg"


def _source_exif(src_path):
    try:
        Image = _pil()
        with Image.open(src_path) as im:
            exif = im.getexif()
            if exif:
                exif[0x0112] = 1    # orientation is baked into the pixels
                return exif.tobytes()
    except Exception:
        pass
    return None


def write(img, out_path, src_path=None, quality=95):
    """Save with the colour profile and the original EXIF. 16-bit images stay 16-bit in PNG and TIFF."""
    ext = os.path.splitext(out_path)[1].lower()
    fmt = SAVE_FORMATS.get(ext)
    if fmt is None:
        raise ValueError(f"Can't save {ext} files")
    icc = img.colorSpace().iccProfile().data() if img.colorSpace().isValid() else None
    exif = _source_exif(src_path) if src_path and os.path.exists(src_path) else None
    tmp = out_path + ".tmp-stillframe"
    try:
        if is_deep(img) and fmt in ("PNG", "TIFF"):
            w = QImageWriter(tmp, fmt.lower().encode())
            if fmt == "TIFF":
                w.setCompression(1)          # LZW, lossless
            ok, err = w.write(img), w.errorString()
            w.device().close()               # release the file before it is renamed
            del w
            if not ok:
                raise OSError(err)
        else:
            Image = _pil()
            alpha = img.hasAlphaChannel() and fmt != "JPEG"
            q = img.convertToFormat(QImage.Format.Format_RGBA8888 if alpha else QImage.Format.Format_RGB888)
            h, wd, bpl = q.height(), q.width(), q.bytesPerLine()
            ch = 4 if alpha else 3
            arr = np.frombuffer(q.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :wd * ch].reshape(h, wd, ch)
            im = Image.fromarray(np.ascontiguousarray(arr), "RGBA" if alpha else "RGB")
            kw = {}
            if icc:
                kw["icc_profile"] = icc
            if exif and fmt in ("JPEG", "PNG", "WEBP", "TIFF"):
                kw["exif"] = exif
            if fmt == "JPEG":
                kw.update(quality=quality, subsampling=0, optimize=True)
            elif fmt == "WEBP":
                kw.update(quality=quality, method=6)
            elif fmt == "TIFF":
                kw.update(compression="tiff_lzw")
            im.save(tmp, format=fmt, **kw)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ============================================================================================ live engine
class AdjustEngine(QObject):
    """Holds the native decode of the current photo and produces previews off the UI thread.

    nativeReady(path)          – the full-resolution native image (and its proxy and histograms) is ready
    fullReady(path, gen, img)  – display-ready full-resolution adjusted image for generation gen
    """
    nativeReady = Signal(str)
    fullReady = Signal(str, int, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.native = None
        self.proxy = None
        self.hists = None
        self.gen = 0
        self.alive = True
        self._lock = threading.Lock()

    def load(self, path, proxy_side=2000):
        if path == self.path and self.native is not None:
            self.nativeReady.emit(path)
            return
        self.path = path
        self.native = self.proxy = self.hists = None

        def work():
            try:
                img = load_native(path)
            except Exception:
                img = QImage()
            if not self.alive or self.path != path or img.isNull():
                return
            prox = proxy_of(img, proxy_side)
            hists = histograms(prox)
            with self._lock:
                if self.path != path:
                    return
                self.native, self.proxy, self.hists = img, prox, hists
            try:
                self.nativeReady.emit(path)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def ready(self, path):
        return self.path == path and self.native is not None

    def preview(self, adj):
        """Fast, proxy-sized display image."""
        return to_display(apply(self.proxy, adj))

    def full_async(self, adj):
        self.gen += 1
        gen, path, native = self.gen, self.path, self.native
        adj = adj.copy()

        def work():
            out = to_display(apply(native, adj))
            if self.alive and self.gen == gen:
                try:
                    self.fullReady.emit(path, gen, out)
                except RuntimeError:
                    pass
        threading.Thread(target=work, daemon=True).start()
        return gen

    def full_now(self, adj):
        return to_display(apply(self.native, adj))

    def forget(self):
        self.path = None
        self.native = self.proxy = self.hists = None
        self.gen += 1
