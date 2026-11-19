"""Export a timeline range to H.264 (MP4) or animated GIF at the source resolution."""
from fractions import Fraction

import av
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor

from .media import VideoDecoder, StillDecoder, AUDIO_RATE, load_audio
from .model import Project
from .viewer import draw_strokes

QUALITY_CRF = {"High": 16, "Medium": 20, "Small file": 26}


class Cancelled(Exception):
    pass


def output_size(project, lo, scale=1.0, even=False):
    """Native size of the first frame in the range (optionally scaled; even for H.264)."""
    clip, off, _ = project.locate(lo)
    w, h = clip.source.width, clip.source.height
    w, h = max(2, round(w * scale)), max(2, round(h * scale))
    if even:
        w, h = w + (w % 2), h + (h % 2)
    return w, h


class FrameSource:
    """Yields full-resolution, annotated RGB frames for global frames lo..hi in order."""

    def __init__(self, project: Project, size, annotations=True):
        self.project = project
        self.size = size
        self.annotations = annotations
        self.decoders = {}

    def close(self):
        for d in self.decoders.values():
            d.close()
        self.decoders.clear()

    def _decoder(self, src):
        d = self.decoders.get(src.id)
        if d is None:
            d = VideoDecoder(src, 1.0) if src.kind == "video" else StillDecoder(src, 1.0)
            self.decoders[src.id] = d
        return d

    def frame(self, g):
        clip, off, _ = self.project.locate(g)
        src = clip.source
        lf = clip.local(off)
        out = {}
        self._decoder(src).decode(lf, 1, lambda i, img: out.__setitem__(i, img), lambda i: i in out)
        img = out.get(lf)
        w, h = self.size
        canvas = QImage(w, h, QImage.Format.Format_RGB888)
        canvas.fill(QColor(0, 0, 0))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if img is not None:
            iw, ih = img.width(), img.height()
            s = min(w / iw, h / ih)          # fit (letterbox) if a later clip has another size
            dw, dh = iw * s, ih * s
            x, y = (w - dw) / 2, (h - dh) / 2
            p.translate(x, y)
            p.scale(s, s)
            p.drawImage(0, 0, img)
            if self.annotations:
                strokes = self.project.annotations.get(Project.akey(src, lf))
                if strokes:
                    draw_strokes(p, strokes)
        p.end()
        return canvas

    @staticmethod
    def to_array(img):
        img = img.convertToFormat(QImage.Format.Format_RGB888)
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        arr = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
        return arr[:, :w * 3].reshape(h, w, 3).copy()  # copy: the QImage buffer dies with img


def _range_audio(project, lo, hi, fps):
    """Stereo int16 audio for the range, following clips; stretched if the timeline fps differs."""
    pieces = []
    g = lo
    while g <= hi:
        clip, off, start = project.locate(g)
        seg_end = min(hi, start + clip.length - 1)
        n_frames = seg_end - g + 1
        n_out = int(round(n_frames / fps * AUDIO_RATE))
        src = clip.source
        data = None
        if src.kind == "video" and src.has_audio:
            if src.audio is None:
                try:
                    src.audio = load_audio(src.path, getattr(src, "_video_start", 0.0))
                except Exception:
                    src.audio = None
            data = src.audio
        if data is None or n_out <= 0:
            pieces.append(np.zeros((max(0, n_out), 2), np.int16))
        else:
            lf0 = clip.local(off)
            s0 = int(round(lf0 / src.native_fps * AUDIO_RATE))
            n_src = int(round(n_frames / src.native_fps * AUDIO_RATE))
            seg = data[s0:s0 + n_src]
            if len(seg) < n_src:
                seg = np.concatenate([seg, np.zeros((n_src - len(seg), 2), np.int16)])
            if n_src != n_out and n_src > 1:
                idx = np.linspace(0, n_src - 1, n_out)
                seg = np.stack([np.interp(idx, np.arange(n_src), seg[:, c]) for c in (0, 1)], 1).astype(np.int16)
            pieces.append(seg[:n_out])
        g = seg_end + 1
    if not pieces:
        return None
    audio = np.concatenate(pieces)
    return audio if np.any(audio) else None


def export_mp4(project, lo, hi, path, quality="High", scale=1.0, annotations=True, audio=True,
               progress=lambda done, total: None, cancelled=lambda: False):
    fps = Fraction(project.fps).limit_denominator(1001)
    size = output_size(project, lo, scale, even=True)
    total = hi - lo + 1
    fs = FrameSource(project, size, annotations)
    container = av.open(path, "w", options={"movflags": "+faststart"})
    try:
        vs = container.add_stream("libx264", rate=fps)
        vs.width, vs.height = size
        vs.pix_fmt = "yuv420p"
        vs.options = {"crf": str(QUALITY_CRF.get(quality, 18)), "preset": "medium", "tune": "film"}
        vs.codec_context.color_range = 1  # tv / limited, what players expect
        pcm = _range_audio(project, lo, hi, float(fps)) if audio else None
        aus = None
        if pcm is not None:
            aus = container.add_stream("aac", rate=AUDIO_RATE)
            aus.layout = "stereo"
            aus.bit_rate = 256000
        for i, g in enumerate(range(lo, hi + 1)):
            if cancelled():
                raise Cancelled()
            vf = av.VideoFrame.from_ndarray(FrameSource.to_array(fs.frame(g)), format="rgb24")
            vf.pts = i
            vf.time_base = 1 / fps
            for pkt in vs.encode(vf.reformat(format="yuv420p", dst_colorspace="ITU709", dst_color_range="MPEG")):
                container.mux(pkt)
            progress(i + 1, total)
        for pkt in vs.encode():
            container.mux(pkt)
        if aus is not None:
            res = av.AudioResampler(format="fltp", layout="stereo", rate=AUDIO_RATE)
            step = 1024
            pts = 0
            for s in range(0, len(pcm), step):
                chunk = np.ascontiguousarray(pcm[s:s + step]).reshape(1, -1)
                af = av.AudioFrame.from_ndarray(chunk, format="s16", layout="stereo")
                af.sample_rate = AUDIO_RATE
                af.pts = pts
                pts += chunk.shape[1] // 2
                for rf in res.resample(af):
                    for pkt in aus.encode(rf):
                        container.mux(pkt)
            for rf in res.resample(None):
                for pkt in aus.encode(rf):
                    container.mux(pkt)
            for pkt in aus.encode():
                container.mux(pkt)
    finally:
        container.close()
        fs.close()
    return size


def export_gif(project, lo, hi, path, scale=1.0, annotations=True, fps_cap=50,
               progress=lambda done, total: None, cancelled=lambda: False):
    """Two passes: build one palette from every frame, then dither all frames with it."""
    src_fps = float(project.fps)
    # GIF delays are in 1/100 s; drop frames evenly if the timeline is faster than the cap
    stride = max(1, int(np.ceil(src_fps / fps_cap)))
    frames = list(range(lo, hi + 1, stride))
    out_fps = Fraction(src_fps / stride).limit_denominator(1001)
    size = output_size(project, lo, scale)
    w, h = size
    total = len(frames) * 2
    tb = Fraction(1, 1000)

    def feed(fs, push, offset):
        for i, g in enumerate(frames):
            if cancelled():
                raise Cancelled()
            vf = av.VideoFrame.from_ndarray(FrameSource.to_array(fs.frame(g)), format="rgb24")
            vf.pts = int(i / out_fps / tb)
            vf.time_base = tb
            push(vf)
            progress(offset + i + 1, total)

    # pass 1: palette
    g1 = av.filter.Graph()
    b1 = g1.add_buffer(width=w, height=h, format="rgb24", time_base=tb)
    pg = g1.add("palettegen", "max_colors=256:stats_mode=full:reserve_transparent=0")
    s1 = g1.add("buffersink")
    b1.link_to(pg)
    pg.link_to(s1)
    g1.configure()
    fs = FrameSource(project, size, annotations)
    try:
        feed(fs, b1.push, 0)
    finally:
        fs.close()
    b1.push(None)
    palette = s1.pull()

    # pass 2: dither with the palette and encode
    g2 = av.filter.Graph()
    b2 = g2.add_buffer(width=w, height=h, format="rgb24", time_base=tb)
    bp = g2.add_buffer(width=palette.width, height=palette.height, format=palette.format.name, time_base=tb)
    pu = g2.add("paletteuse", "dither=sierra2_4a:diff_mode=rectangle")
    s2 = g2.add("buffersink")
    b2.link_to(pu, 0, 0)
    bp.link_to(pu, 0, 1)
    pu.link_to(s2)
    g2.configure()
    palette.pts = 0
    palette.time_base = tb
    bp.push(palette)
    bp.push(None)

    container = av.open(path, "w", format="gif", options={"loop": "0"})
    try:
        st = container.add_stream("gif", rate=out_fps)
        st.width, st.height = size
        st.pix_fmt = "pal8"
        st.time_base = tb

        def drain():
            while True:
                try:
                    f = s2.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return
                f.time_base = tb
                for pkt in st.encode(f):
                    container.mux(pkt)

        def push(vf):
            b2.push(vf)
            drain()

        fs = FrameSource(project, size, annotations)
        try:
            feed(fs, push, len(frames))
        finally:
            fs.close()
        b2.push(None)
        drain()
        for pkt in st.encode():
            container.mux(pkt)
    finally:
        container.close()
    return size, float(out_fps)
