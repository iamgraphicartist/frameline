"""Image loading for Stillframe: every common format, EXIF orientation, colour management, prefetch and thumbnails."""
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import QObject, Signal, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QColorSpace

QT_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".svgz", ".ico",
           ".tga", ".ppm", ".pgm", ".pbm"}
PIL_EXTS = {".heic", ".heif", ".avif", ".jxl", ".psd", ".jp2", ".dds"}
FFMPEG_EXTS = {".exr", ".dpx", ".hdr"}
IMAGE_EXTS = QT_EXTS | PIL_EXTS | FFMPEG_EXTS

_SRGB = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
_pil_ready = False


def _pil():
    global _pil_ready
    from PIL import Image
    if not _pil_ready:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        _pil_ready = True
    return Image


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(s))]


def list_folder(folder, sort="name"):
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names if is_image(n) and not n.startswith("._")]
    paths = [p for p in paths if os.path.isfile(p)]
    if sort == "date":
        paths.sort(key=lambda p: (os.path.getmtime(p), _natural_key(p)))
    elif sort == "size":
        paths.sort(key=lambda p: (os.path.getsize(p), _natural_key(p)))
    else:
        paths.sort(key=_natural_key)
    return paths


def _to_srgb(img):
    cs = img.colorSpace()
    if cs.isValid() and cs != _SRGB:
        try:
            img.convertToColorSpace(_SRGB)
        except Exception:
            pass
    return img


def _from_pil(im):
    Image = _pil()
    from PIL import ImageOps
    im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile")
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if ("A" in im.getbands() or im.mode == "P") else "RGB")
    if im.mode == "RGBA":
        data = im.tobytes("raw", "RGBA")
        img = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()
    else:
        data = im.tobytes("raw", "RGB")
        img = QImage(data, im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()
    if icc:
        cs = QColorSpace.fromIccProfile(icc)
        if cs.isValid():
            img.setColorSpace(cs)
    return img


def load_image(path, max_side=None):
    """Decode for display: oriented, sRGB. max_side gives a fast reduced decode (thumbnails)."""
    ext = os.path.splitext(path)[1].lower()
    img = QImage()
    if ext in QT_EXTS:
        r = QImageReader(path)
        r.setAutoTransform(True)
        r.setAllocationLimit(2048)  # MB; large panoramas are fine
        if max_side:
            sz = r.size()
            if sz.isValid() and max(sz.width(), sz.height()) > max_side:
                s = max_side / max(sz.width(), sz.height())
                r.setScaledSize(QSize(max(1, round(sz.width() * s)), max(1, round(sz.height() * s))))
        img = r.read()
    if img.isNull() and ext not in FFMPEG_EXTS:
        try:
            Image = _pil()
            with Image.open(path) as im:
                if max_side:
                    try:
                        im.draft("RGB", (max_side, max_side))
                    except Exception:
                        pass
                    im.thumbnail((max_side * 2, max_side * 2))
                img = _from_pil(im)
        except Exception:
            img = QImage()
    if img.isNull():
        from frameline.media import read_image
        img = read_image(path)
    img = _to_srgb(img)
    if max_side and max(img.width(), img.height()) > max_side:
        img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


def is_animated(path):
    if os.path.splitext(path)[1].lower() not in (".gif", ".webp", ".png"):
        return False
    r = QImageReader(path)
    return r.supportsAnimation() and r.imageCount() > 1


# ------------------------------------------------------------------------------------------- metadata
def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def _ratio(v):
    try:
        return float(v)
    except Exception:
        try:
            return v[0] / v[1]
        except Exception:
            return None


def read_info(path, img=None):
    """Basic file facts plus camera EXIF where available."""
    info = OrderedDict()
    st = os.stat(path)
    info["Name"] = os.path.basename(path)
    info["Folder"] = os.path.dirname(path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    info["Format"] = {"jpg": "JPEG", "jpeg": "JPEG", "tif": "TIFF", "heic": "HEIC", "heif": "HEIF"}.get(ext, ext.upper())
    if img is not None and not img.isNull():
        mp = img.width() * img.height() / 1e6
        info["Dimensions"] = f"{img.width()} × {img.height()}" + (f"  ({mp:.1f} MP)" if mp >= 1 else "")
    info["File Size"] = _fmt_size(st.st_size)
    info["Modified"] = datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y, %H:%M")
    exif = OrderedDict()
    try:
        Image = _pil()
        from PIL import ExifTags
        with Image.open(path) as im:
            ex = im.getexif()
            if ex:
                base = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
                try:
                    sub = {ExifTags.TAGS.get(k, k): v for k, v in ex.get_ifd(0x8769).items()}
                except Exception:
                    sub = {}
                allt = {**base, **sub}
                make = str(allt.get("Make", "")).strip().strip("\x00")
                model = str(allt.get("Model", "")).strip().strip("\x00")
                if model:
                    exif["Camera"] = model if (not make or model.lower().startswith(make.lower().split()[0])) else f"{make} {model}"
                lens = str(allt.get("LensModel", "")).strip().strip("\x00")
                if lens:
                    exif["Lens"] = lens
                parts = []
                f = _ratio(allt.get("FocalLength"))
                if f:
                    parts.append(f"{f:g} mm")
                a = _ratio(allt.get("FNumber"))
                if a:
                    parts.append(f"ƒ/{a:g}")
                t = _ratio(allt.get("ExposureTime"))
                if t:
                    parts.append(f"1/{round(1 / t)} s" if t < 0.5 else f"{t:g} s")
                iso = allt.get("ISOSpeedRatings") or allt.get("PhotographicSensitivity")
                if iso:
                    parts.append(f"ISO {iso[0] if isinstance(iso, tuple) else iso}")
                if parts:
                    exif["Exposure"] = "  ·  ".join(parts)
                dt = allt.get("DateTimeOriginal") or allt.get("DateTime")
                if dt:
                    try:
                        exif["Taken"] = datetime.strptime(str(dt).strip("\x00"), "%Y:%m:%d %H:%M:%S").strftime("%d %b %Y, %H:%M")
                    except Exception:
                        exif["Taken"] = str(dt)
                sw = str(allt.get("Software", "")).strip().strip("\x00")
                if sw:
                    exif["Software"] = sw
            if "icc_profile" in im.info:
                cs = QColorSpace.fromIccProfile(im.info["icc_profile"])
                if cs.isValid() and cs.description():
                    exif["Colour Profile"] = cs.description()
    except Exception:
        pass
    return info, exif


# ------------------------------------------------------------------------------------------- caches
class ImageCache(QObject):
    """Decodes full images on background threads; current image first, then neighbours."""
    loaded = Signal(str, object)     # path, QImage (null on failure)

    def __init__(self, budget_mb=1200, workers=2):
        super().__init__()
        self.budget = budget_mb * 1024 * 1024
        self.cache = OrderedDict()   # path -> QImage
        self.bytes = 0
        self.queue = []              # wanted paths, highest priority first
        self.busy = set()
        self.cv = threading.Condition()
        self.alive = True
        for _ in range(workers):
            threading.Thread(target=self._run, daemon=True).start()

    def get(self, path):
        with self.cv:
            img = self.cache.get(path)
            if img is not None:
                self.cache.move_to_end(path)
            return img

    def want(self, paths):
        with self.cv:
            self.queue = [p for p in paths if p not in self.cache]
            self.cv.notify_all()

    def drop(self, path):
        with self.cv:
            img = self.cache.pop(path, None)
            if img is not None:
                self.bytes -= img.sizeInBytes()

    def clear(self):
        with self.cv:
            self.cache.clear()
            self.bytes = 0
            self.queue = []

    def close(self):
        with self.cv:
            self.alive = False
            self.cv.notify_all()

    def _put(self, path, img):
        with self.cv:
            if path in self.cache:
                return
            self.cache[path] = img
            self.bytes += img.sizeInBytes()
            keep = set(self.queue[:5])
            while self.bytes > self.budget and len(self.cache) > 1:
                victim = next((k for k in self.cache if k not in keep and k != path), None)
                if victim is None:
                    break
                self.bytes -= self.cache.pop(victim).sizeInBytes()

    def _run(self):
        while True:
            with self.cv:
                while self.alive and not any(p not in self.busy for p in self.queue):
                    self.cv.wait()
                if not self.alive:
                    return
                path = next(p for p in self.queue if p not in self.busy)
                self.busy.add(path)
            try:
                img = load_image(path)
            except Exception:
                img = QImage()
            if not img.isNull():
                self._put(path, img)
            with self.cv:
                self.busy.discard(path)
                if path in self.queue:
                    self.queue.remove(path)
            if not self.alive:
                return
            try:
                self.loaded.emit(path, img)
            except RuntimeError:   # window already closed
                return


class ThumbLoader(QObject):
    """Small, fast thumbnails for the filmstrip (reduced-size decodes)."""
    ready = Signal(str, object)
    SIZE = 160

    def __init__(self):
        super().__init__()
        self.thumbs = {}
        self.pending = []
        self.cv = threading.Condition()
        self.alive = True
        self.gen = 0
        threading.Thread(target=self._run, daemon=True).start()

    def request(self, paths):
        """Replace the queue (ordered by priority)."""
        with self.cv:
            self.pending = [p for p in paths if p not in self.thumbs]
            self.cv.notify_all()

    def reset(self):
        with self.cv:
            self.gen += 1
            self.pending = []

    def close(self):
        with self.cv:
            self.alive = False
            self.cv.notify_all()

    def _run(self):
        while True:
            with self.cv:
                while self.alive and not self.pending:
                    self.cv.wait()
                if not self.alive:
                    return
                path = self.pending.pop(0)
                gen = self.gen
            try:
                img = load_image(path, max_side=self.SIZE)
            except Exception:
                img = QImage()
            with self.cv:
                if gen != self.gen:
                    continue
                self.thumbs[path] = img
            if not self.alive:
                return
            try:
                self.ready.emit(path, img)
            except RuntimeError:
                return
