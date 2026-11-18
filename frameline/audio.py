"""Low-latency audio output with scrubbing, varispeed and reverse playback."""
import threading

import numpy as np

from .media import AUDIO_RATE

try:
    import sounddevice as sd
except Exception:  # PortAudio missing
    sd = None


class AudioEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.track = None
        self.pos = 0.0
        self.rate = 1.0
        self.playing = False
        self.stop_at = None
        self.volume = 0.8
        self.muted = False
        self.stream = None
        self.available = sd is not None
        if self.available:
            try:
                self.stream = sd.OutputStream(samplerate=AUDIO_RATE, channels=2, dtype="int16",
                                              blocksize=512, latency="low", callback=self._cb)
                self.stream.start()
            except Exception:
                self.stream = None
                self.available = False

    def _cb(self, outdata, frames, _time, _status):
        with self.lock:
            tr = self.track
            if not self.playing or tr is None or self.muted:
                outdata.fill(0)
                if self.playing and tr is not None:
                    self.pos += frames * self.rate
                return
            idx = (self.pos + np.arange(frames) * self.rate).astype(np.int64)
            valid = (idx >= 0) & (idx < len(tr))
            out = np.zeros((frames, 2), np.int16)
            if valid.any():
                out[valid] = (tr[idx[valid]].astype(np.float32) * self.volume).astype(np.int16)
            self.pos += frames * self.rate
            if self.stop_at is not None and ((self.rate > 0 and self.pos >= self.stop_at) or
                                             (self.rate < 0 and self.pos <= self.stop_at)):
                self.playing = False
                self.stop_at = None
        outdata[:] = out

    def play(self, track, seconds, rate=1.0):
        with self.lock:
            self.track = track
            self.pos = seconds * AUDIO_RATE
            self.rate = rate
            self.stop_at = None
            self.playing = track is not None

    def scrub(self, track, seconds, duration, rate=1.0):
        """Play a short snippet (one frame) for audible scrubbing."""
        with self.lock:
            self.track = track
            self.pos = seconds * AUDIO_RATE
            self.rate = rate
            self.stop_at = self.pos + duration * AUDIO_RATE * (1 if rate > 0 else -1)
            self.playing = track is not None

    def position(self):
        with self.lock:
            return self.pos / AUDIO_RATE

    def stop(self):
        with self.lock:
            self.playing = False
            self.stop_at = None

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
