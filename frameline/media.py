"""Media sources: frame-accurate decoding (PyAV/FFmpeg), image sequences, RAM cache, audio."""
import os
import re
import threading
from collections import OrderedDict

import av
import numpy as np
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage, QImageReader

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mxf", ".wmv", ".mpg", ".mpeg", ".flv", ".ts",
             ".mts", ".m2ts", ".gif", ".3gp", ".ogv", ".dv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga", ".exr", ".dpx", ".webp", ".psd", ".hdr",
             ".jp2", ".ppm", ".sgi", ".rgb"}
AUDIO_RATE = 48000


# --------------------------------------------------------------------------------------- cache
class FrameCache:
    """Global LRU of decoded frames, bounded by a RAM budget."""

    def __init__(self, budget_mb=3072):
        self.budget = budget_mb * 1024 * 1024
        self.used = 0
        self.d = OrderedDict()
        self.by_src = {}
        self.lock = threading.Lock()

    def set_budget(self, mb):
        with self.lock:
            self.budget = int(mb) * 1024 * 1024
            self._evict()

    def get(self, key):
        with self.lock:
            img = self.d.get(key)
            if img is not None:
                self.d.move_to_end(key)
            return img

    def has(self, key):
        with self.lock:
            return key in self.d

    def put(self, key, img):
        with self.lock:
            if key in self.d:
                return
            self.d[key] = img
            self.used += img.sizeInBytes()
            self.by_src.setdefault(key[0], set()).add(key[1])
            self._evict()

    def _evict(self):
        while self.used > self.budget and len(self.d) > 2:
            k, v = self.d.popitem(last=False)
            self.used -= v.sizeInBytes()
            s = self.by_src.get(k[0])
            if s is not None:
                s.discard(k[1])

    def frames_for(self, sid):
        with self.lock:
            return set(self.by_src.get(sid, ()))

    def drop_source(self, sid):
        with self.lock:
            for f in list(self.by_src.get(sid, ())):
                v = self.d.pop((sid, f), None)
                if v is not None:
                    self.used -= v.sizeInBytes()
            self.by_src.pop(sid, None)

    def clear(self):
        with self.lock:
            self.d.clear()
            self.by_src.clear()
            self.used = 0


CACHE = FrameCache()


# --------------------------------------------------------------------------------------- helpers
def _to_qimage(arr, alpha):
    h, w = arr.shape[:2]
    fmt = QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32
    img = QImage(arr.data, w, h, arr.strides[0], fmt).copy()
    if alpha:
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return img


def _normalize(img):
    if img.hasAlphaChannel():
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return img.convertToFormat(QImage.Format.Format_RGB32)


def read_image(path):
    """Read a still with Qt; fall back to FFmpeg for EXR/DPX/etc."""
    img = QImage(path)
    if not img.isNull():
        return _normalize(img)
    with av.open(path) as c:
        for fr in c.decode(video=0):
            alpha = "a" in fr.format.name.replace("gray", "")
            try:
                arr = fr.to_ndarray(format="bgra")
            except Exception:
                arr = fr.reformat(format="bgra").to_ndarray()
            return _to_qimage(arr, alpha)
    raise IOError(f"Cannot read {path}")


SEQ_RE = re.compile(r"^(.*?)(\d+)(\.[A-Za-z0-9]+)$")


def detect_sequence(path):
    d, fn = os.path.split(path)
    m = SEQ_RE.match(fn)
    if not m:
        return None
    prefix, digits, ext = m.groups()
    rx = re.compile("^" + re.escape(prefix) + r"(\d+)" + re.escape(ext) + "$", re.I)
    nums = {}
    try:
        for f in os.listdir(d or "."):
            mm = rx.match(f)
            if mm:
                nums[int(mm.group(1))] = os.path.join(d, f)
    except OSError:
        return None
    if len(nums) < 2:
        return None
    lo, hi = min(nums), max(nums)
    if hi - lo > 200000:
        return None
    paths, last = [], None
    for n in range(lo, hi + 1):
        p = nums.get(n, last)
        if p is None:
            p = nums[min(k for k in nums if k > n)]
        paths.append(p)
        last = p
    return f"{prefix}{'#' * len(digits)}{ext}", paths, lo


def scan_folder(folder):
    """Return a list of (kind, path, extra) for all media inside a folder (non-recursive)."""
    out, seen = [], set()
    try:
        files = sorted(os.listdir(folder))
    except OSError:
        return out
    for f in files:
        p = os.path.join(folder, f)
        if not os.path.isfile(p) or p in seen:
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXT:
            out.append(("video", p, None))
        elif ext in IMAGE_EXT:
            seq = detect_sequence(p)
            if seq:
                seen.update(seq[1])
                out.append(("sequence", p, seq))
            else:
                out.append(("image", p, None))
    return out


def make_sources(paths):
    """Turn dropped/opened paths into MediaSource objects (sequences auto-detected)."""
    result, consumed = [], set()
    for p in paths:
        if p in consumed:
            continue
        if os.path.isdir(p):
            for kind, fp, extra in scan_folder(p):
                result.append(MediaSource(fp, kind, extra))
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in IMAGE_EXT:
            seq = detect_sequence(p)
            if seq:
                consumed.update(seq[1])
                result.append(MediaSource(p, "sequence", seq))
            else:
                result.append(MediaSource(p, "image"))
        else:
            result.append(MediaSource(p, "video"))
    return result


# --------------------------------------------------------------------------------------- decoders
class VideoDecoder:
    def __init__(self, src, proxy=None):
        self.src = src
        self.proxy = proxy
        self.c = av.open(src.path)
        self.vs = self.c.streams.video[0]
        self.vs.thread_type = "AUTO"
        self.tb = float(self.vs.time_base)
        self.start_pts = self.vs.start_time or 0
        self.fps = src.native_fps
        self.gen = None
        self.next_idx = None
        self.last_idx = None
        fmt = self.vs.codec_context.pix_fmt or ""
        self.alpha = fmt.startswith(("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya"))

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass

    def _idx(self, fr):
        if fr.pts is None:
            return (self.next_idx or 0)
        return int(round((fr.pts - self.start_pts) * self.tb * self.fps))

    def _seek(self, target, back_sec=0.0):
        t = max(0.0, target / self.fps - back_sec)
        ts = int(t / self.tb) + self.start_pts
        self.c.seek(ts, stream=self.vs, backward=True, any_frame=False)
        self.gen = self.c.decode(self.vs)
        self.next_idx = None

    def _convert(self, fr):
        p = self.proxy or self.src.proxy
        w = max(2, int(self.src.width * p)) & ~1
        h = max(2, int(self.src.height * p)) & ~1
        try:
            arr = fr.to_ndarray(format="bgra", width=w, height=h)
        except Exception:
            arr = fr.reformat(width=w, height=h, format="bgra").to_ndarray()
        return _to_qimage(arr, self.alpha)

    def decode(self, target, direction, store, has):
        keep_from = target - (90 if direction < 0 else 0)
        if self.next_idx is None or target < self.next_idx or target > self.next_idx + 40:
            self._seek(target)
            back = 0.0
            while True:
                try:
                    fr = next(self.gen)
                except StopIteration:
                    self._eof(target)
                    return
                idx = self._idx(fr)
                if idx > target and back < 16 and target > 0:
                    back = back * 2 + 1.0
                    self._seek(target, back)
                    continue
                break
        else:
            try:
                fr = next(self.gen)
            except StopIteration:
                self._eof(target)
                return
            idx = self._idx(fr)
        while True:
            self.next_idx = idx + 1
            self.last_idx = idx
            if idx >= keep_from and not has(idx):
                store(idx, self._convert(fr))
            if idx >= target:
                if idx > target and not has(target):
                    store(target, self._convert(fr))
                return
            try:
                fr = next(self.gen)
            except StopIteration:
                self._eof(target)
                return
            idx = self._idx(fr)

    def _eof(self, target):
        if self.last_idx is not None and target > self.last_idx:
            self.src._truncate(self.last_idx + 1)
        self.next_idx = None


class StillDecoder:
    def __init__(self, src, proxy=None):
        self.src = src
        self.proxy = proxy

    def close(self):
        pass

    def decode(self, target, direction, store, has):
        path = self.src.paths[target] if self.src.paths else self.src.path
        img = read_image(path)
        p = self.proxy or self.src.proxy
        if p < 1.0:
            img = img.scaled(max(1, int(img.width() * p)), max(1, int(img.height() * p)),
                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        store(target, img)


def decode_frame_sync(src, local):
    """Decode one full-resolution frame on the calling thread (used for exports)."""
    out = {}
    dec = VideoDecoder(src, 1.0) if src.kind == "video" else StillDecoder(src, 1.0)
    try:
        dec.decode(local, 1, lambda i, img: out.__setitem__(i, img), lambda i: i in out)
    finally:
        dec.close()
    return out.get(local)


# --------------------------------------------------------------------------------------- audio
def load_audio(path, video_start_sec=0.0):
    with av.open(path) as c:
        if not c.streams.audio:
            return None
        a = c.streams.audio[0]
        a.thread_type = "AUTO"
        res = av.AudioResampler(format="s16", layout="stereo", rate=AUDIO_RATE)
        chunks = []
        for fr in c.decode(a):
            for o in res.resample(fr):
                chunks.append(o.to_ndarray().reshape(-1))
        for o in res.resample(None):
            chunks.append(o.to_ndarray().reshape(-1))
        if not chunks:
            return None
        data = np.concatenate(chunks).reshape(-1, 2)
        a_start = float((a.start_time or 0) * a.time_base) if a.start_time is not None else 0.0
        off = int(round((a_start - video_start_sec) * AUDIO_RATE))
        if off > 0:
            data = np.concatenate([np.zeros((off, 2), np.int16), data])
        elif off < 0:
            data = data[-off:]
        return np.ascontiguousarray(data)


# --------------------------------------------------------------------------------------- source
class MediaSource(QObject):
    frameReady = Signal(object, int)
    infoChanged = Signal(object)
    _ids = 0

    def __init__(self, path, kind, seq=None):
        super().__init__()
        MediaSource._ids += 1
        self.id = MediaSource._ids
        self.path = os.path.abspath(path)
        self.kind = kind
        self.paths = None
        self.first_number = 0
        self.name = os.path.basename(path)
        if kind == "sequence" and seq:
            self.name, self.paths, self.first_number = seq
        self.width = self.height = 0
        self.native_fps = 24.0
        self.fps_override = None
        self.frames = 1
        self.codec = ""
        self.pix_fmt = ""
        self.bitrate = 0
        self.file_size = 0
        self.has_audio = False
        self.audio = None
        self.thumb = None
        self.error = None
        self.proxy = 1.0
        self._bad = set()
        self._cond = threading.Condition()
        self._target = 0
        self._dir = 1
        self._ahead = 24
        self._stop = False
        try:
            self._probe()
        except Exception as e:  # noqa
            self.error = str(e)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if self.has_audio:
            threading.Thread(target=self._load_audio, daemon=True).start()

    # ---- info
    @property
    def fps(self):
        return self.fps_override or self.native_fps

    @property
    def frame_bytes(self):
        return max(1, int(self.width * self.proxy) * int(self.height * self.proxy) * 4)

    def _probe(self):
        try:
            self.file_size = os.path.getsize(self.path)
        except OSError:
            pass
        if self.kind == "video":
            with av.open(self.path) as c:
                if not c.streams.video:
                    raise IOError("No video stream")
                vs = c.streams.video[0]
                cc = vs.codec_context
                self.width, self.height = cc.width, cc.height
                rate = vs.average_rate or vs.guessed_rate or vs.base_rate
                self.native_fps = float(rate) if rate else 24.0
                if not (1.0 <= self.native_fps <= 240.0):
                    self.native_fps = 24.0
                dur = None
                if vs.duration is not None:
                    dur = float(vs.duration * vs.time_base)
                elif c.duration:
                    dur = c.duration / 1_000_000
                n = vs.frames or (int(round(dur * self.native_fps)) if dur else 1)
                self.frames = max(1, int(n))
                self.codec = (cc.codec.long_name or cc.name or "").split(" / ")[0].split(" (")[0]
                self.pix_fmt = cc.pix_fmt or ""
                self.bitrate = c.bit_rate or 0
                self.has_audio = bool(c.streams.audio)
                self._video_start = float(vs.start_time * vs.time_base) if vs.start_time is not None else 0.0
        else:
            first = self.paths[0] if self.paths else self.path
            r = QImageReader(first)
            sz = r.size()
            if sz.isValid():
                self.width, self.height = sz.width(), sz.height()
                self.codec = bytes(r.format()).decode(errors="ignore").upper()
            else:
                img = read_image(first)
                self.width, self.height = img.width(), img.height()
                self.codec = os.path.splitext(first)[1][1:].upper()
            self.frames = len(self.paths) if self.paths else 1
            self.pix_fmt = "image"

    def _load_audio(self):
        try:
            self.audio = load_audio(self.path, getattr(self, "_video_start", 0.0))
        except Exception:
            self.audio = None
        self.infoChanged.emit(self)

    def _truncate(self, n):
        if 0 < n < self.frames:
            self.frames = n
            self.infoChanged.emit(self)

    def clamp(self, f):
        return 0 if f < 0 else (self.frames - 1 if f >= self.frames else int(f))

    # ---- frame access
    def get(self, f):
        return CACHE.get((self.id, self.clamp(f)))

    def cached_frames(self):
        return CACHE.frames_for(self.id)

    def request(self, f, direction=1, ahead=24):
        budget_frames = int(CACHE.budget * 0.45 / self.frame_bytes)
        with self._cond:
            self._target = self.clamp(f)
            self._dir = -1 if direction < 0 else 1
            self._ahead = max(1, min(ahead, budget_frames))
            self._cond.notify()

    def set_proxy(self, p):
        with self._cond:
            self.proxy = p
            CACHE.drop_source(self.id)
            self._bad.clear()
            self._cond.notify()

    def close(self):
        with self._cond:
            self._stop = True
            self._cond.notify()
        CACHE.drop_source(self.id)

    # ---- worker
    def _next_job(self):
        t, d = self._target, self._dir
        for i in range(self._ahead + 1):
            f = t + i * d
            if f < 0 or f >= self.frames:
                break
            if f not in self._bad and not CACHE.has((self.id, f)):
                return f, d
        return None

    def _store(self, idx, img):
        if 0 <= idx < self.frames:
            CACHE.put((self.id, idx), img)
            self.frameReady.emit(self, idx)

    def _has(self, idx):
        return CACHE.has((self.id, idx))

    def _run(self):
        if self.error:
            return
        try:
            dec = VideoDecoder(self) if self.kind == "video" else StillDecoder(self)
        except Exception as e:
            self.error = str(e)
            self.infoChanged.emit(self)
            return
        try:
            dec.decode(0, 1, self._store, self._has)
            img = CACHE.get((self.id, 0))
            if img is not None:
                self.thumb = img.scaled(192, 108, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
        except Exception as e:
            self.error = str(e)
        self.infoChanged.emit(self)
        while True:
            with self._cond:
                job = None
                while not self._stop:
                    job = self._next_job()
                    if job is not None:
                        break
                    self._cond.wait(0.25)
                if self._stop:
                    break
            f, d = job
            try:
                dec.decode(f, d, self._store, self._has)
            except Exception:
                try:
                    dec.close()
                    dec = VideoDecoder(self) if self.kind == "video" else StillDecoder(self)
                except Exception:
                    pass
            if not CACHE.has((self.id, f)):
                self._bad.add(f)
        dec.close()

    # ---- serialisation
    def to_dict(self):
        return {"path": self.path, "kind": self.kind, "fps_override": self.fps_override}
