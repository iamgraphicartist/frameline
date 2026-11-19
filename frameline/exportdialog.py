"""Export Range dialog: H.264 (MP4) or GIF of the in/out section at the source resolution."""
import os
import threading
import time
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QFileDialog,
                               QProgressBar, QWidget, QMessageBox)

from . import exporter, theme
from .widgets import Segmented, Switch, row, section


def _fmt_dur(frames, fps):
    s = frames / fps
    return f"{s:.1f} s" if s < 60 else f"{int(s // 60)}:{s % 60:04.1f}"


class ExportDialog(QDialog):
    def __init__(self, win, lo, hi, has_range):
        super().__init__(win)
        self.win = win
        self.lo, self.hi = lo, hi
        self.project = win.project
        self.setWindowTitle("Export Range")
        self.setMinimumWidth(400)
        self._thread = None
        self._done = self._total = 0
        self._cancel = False
        self._error = None
        self._result = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        title = QLabel("Export Range")
        title.setStyleSheet(f"font-size: {theme.pt(13)}; font-weight: 600;")
        lay.addWidget(title)
        n = hi - lo + 1
        fps = self.project.fps
        b = win.base
        what = "In → Out" if has_range else "Whole timeline"
        sub = QLabel(f"{what}: frames {lo + b}–{hi + b} · {n} frames · {_fmt_dur(n, fps)} at {fps:g} fps")
        sub.setObjectName("Secondary")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        if not has_range:
            hint = QLabel("Tip: press I and O on the timeline to export just a section.")
            hint.setObjectName("Tertiary")
            lay.addWidget(hint)

        lay.addWidget(section("Format"))
        self.fmt = Segmented(["H.264 (MP4)", "GIF"])
        self.fmt.changed.connect(self._update)
        lay.addWidget(self.fmt)

        self.res = QComboBox()
        w, h = exporter.output_size(self.project, lo)
        for label, s in ((f"Full · {w}×{h}", 1.0), (f"Half · {w // 2}×{h // 2}", 0.5),
                         (f"Quarter · {w // 4}×{h // 4}", 0.25)):
            self.res.addItem(label, s)
        self.res.currentIndexChanged.connect(self._update)
        lay.addWidget(row("Resolution", self.res))

        self.quality = QComboBox()
        self.quality.addItems(list(exporter.QUALITY_CRF))
        self.quality_row = row("Quality", self.quality)
        lay.addWidget(self.quality_row)

        self.sw_audio = Switch(True)
        self.audio_row = row("Include audio", self.sw_audio)
        lay.addWidget(self.audio_row)

        has_notes = any(self._range_has_notes())
        self.sw_notes = Switch(has_notes)
        lay.addWidget(row("Burn in drawings", self.sw_notes))

        self.note = QLabel()
        self.note.setObjectName("Tertiary")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(f"QProgressBar {{ background: {theme.css('control')}; border: none; border-radius: 3px; }}"
                               f"QProgressBar::chunk {{ background: {theme.css('accent')}; border-radius: 3px; }}")
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel()
        self.status.setObjectName("Secondary")
        self.status.hide()
        lay.addWidget(self.status)

        lay.addSpacing(6)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_export = QPushButton("Export…")
        self.btn_export.setObjectName("Primary")
        self.btn_export.setDefault(True)
        self.btn_export.clicked.connect(self._start)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_export)
        lay.addLayout(btns)

        last = win.settings.value("export_format", 0)
        self.fmt.set_index(int(last), animate=False)
        self.quality.setCurrentText(win.settings.value("export_quality", "High"))
        self._timer = QTimer(self, interval=100, timeout=self._poll)
        self._update()

    def _range_has_notes(self):
        ann = self.project.annotations
        for g in range(self.lo, self.hi + 1):
            clip, off, _ = self.project.locate(g)
            yield bool(ann.get(self.project.akey(clip.source, clip.local(off))))

    def _update(self, *_):
        gif = self.fmt.index == 1
        self.quality_row.setVisible(not gif)
        self.audio_row.setVisible(not gif)
        n = self.hi - self.lo + 1
        scale = self.res.currentData()
        w, h = exporter.output_size(self.project, self.lo, scale, even=not gif)
        if gif:
            fps = self.project.fps
            msg = "GIFs are limited to 256 colours and have no sound."
            if fps > 50:
                msg += f" Frame rate will be reduced to {fps / max(1, -(-fps // 50)):g} fps (GIF maximum is 50)."
            if w * h * n > 1920 * 1080 * 240:
                msg += " At full resolution this GIF will be large; Half is much smaller."
        else:
            msg = f"H.264, {w}×{h}, {self.project.fps:g} fps. Plays everywhere: browsers, phones, Slack, QuickTime."
            src_w, src_h = exporter.output_size(self.project, self.lo, scale)
            if (src_w, src_h) != (w, h):
                msg += f" (Padded from {src_w}×{src_h}: H.264 needs even dimensions.)"
        self.note.setText(msg)

    def _start(self):
        gif = self.fmt.index == 1
        ext = "gif" if gif else "mp4"
        clip, _, _ = self.project.locate(self.lo)
        base = os.path.splitext(os.path.basename(clip.source.name.replace("#", "")))[0].rstrip("._ ") or "export"
        b = self.win.base
        name = f"{base}_{self.lo + b}-{self.hi + b}.{ext}"
        folder = self.win.settings.value("export_dir", os.path.expanduser("~/Videos"))
        path, _ = QFileDialog.getSaveFileName(self, "Export Range", os.path.join(folder, name),
                                              "GIF (*.gif)" if gif else "MP4 video (*.mp4)")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        s = self.win.settings
        s.setValue("export_dir", os.path.dirname(path))
        s.setValue("export_format", self.fmt.index)
        s.setValue("export_quality", self.quality.currentText())

        self.path = path
        for wdg in (self.fmt, self.res, self.quality, self.sw_audio, self.sw_notes, self.btn_export):
            wdg.setEnabled(False)
        self.bar.show()
        self.status.show()
        self.status.setText("Starting…")
        self._t0 = time.time()
        kw = dict(scale=self.res.currentData(), annotations=self.sw_notes.checked,
                  progress=self._progress, cancelled=lambda: self._cancel)
        if gif:
            fn = lambda: exporter.export_gif(self.project, self.lo, self.hi, path, **kw)
        else:
            fn = lambda: exporter.export_mp4(self.project, self.lo, self.hi, path, self.quality.currentText(),
                                             audio=self.sw_audio.checked, **kw)

        def run():
            try:
                self._result = fn()
            except exporter.Cancelled:
                self._error = "cancelled"
            except Exception as e:
                traceback.print_exc()
                self._error = str(e) or e.__class__.__name__

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        self._timer.start()

    def _progress(self, done, total):
        self._done, self._total = done, total

    def _poll(self):
        if self._total:
            self.bar.setMaximum(self._total)
            self.bar.setValue(self._done)
            el = time.time() - self._t0
            left = el / max(1, self._done) * (self._total - self._done)
            phase = ""
            if self.fmt.index == 1:
                phase = "Building palette · " if self._done <= self._total // 2 else "Encoding · "
            self.status.setText(f"{phase}{self._done} / {self._total} · about {left:.0f} s left")
        if self._thread and not self._thread.is_alive():
            self._timer.stop()
            self._finish()

    def _finish(self):
        if self._error == "cancelled":
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.reject()
            return
        if self._error:
            QMessageBox.warning(self, "Export Range", f"Export failed:\n\n{self._error}")
            self.reject()
            return
        size_mb = os.path.getsize(self.path) / 1048576
        self.win.toast(f"Exported {os.path.basename(self.path)}")
        box = QMessageBox(self)
        box.setWindowTitle("Export Range")
        box.setText(f"Exported {os.path.basename(self.path)}\n{size_mb:.1f} MB · {time.time() - self._t0:.0f} s")
        reveal = box.addButton("Show in Folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is reveal:
            self.win._reveal(self.path)
        self.accept()

    def _on_cancel(self):
        if self._thread and self._thread.is_alive():
            self._cancel = True
            self.status.setText("Cancelling…")
        else:
            self.reject()

    def closeEvent(self, e):
        if self._thread and self._thread.is_alive():
            self._cancel = True
            e.ignore()
            return
        super().closeEvent(e)
