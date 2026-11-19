"""Stillframe main window."""
import os
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, QSettings, QPoint, QFileSystemWatcher, QSize
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QGuiApplication, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMenu, QFileDialog,
                               QMessageBox, QApplication, QDialog, QPushButton, QCheckBox, QSlider,
                               QInputDialog)

from frameline import theme
from frameline.theme import T
from frameline.widgets import icon_button, refresh_all_icons, Swatch
from frameline.theme import SYSTEM_COLORS
from . import __version__
from .loader import ImageCache, ThumbLoader, list_folder, is_image, read_info, is_animated, IMAGE_EXTS
from .view import PhotoView
from .panels import Filmstrip, InfoPanel

APP = "Stillframe"
REPO_URL = "https://github.com/iamgraphicartist/frameline"


def app_icon():
    from .appicon import qicon
    return qicon()


class MainWindow(QMainWindow):
    def __init__(self, files=()):
        super().__init__()
        self.settings = QSettings(APP, APP)
        theme.set_theme(self.settings.value("appearance", "dark"))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.setWindowTitle(APP)
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self.setMinimumSize(720, 480)

        self.paths = []
        self.index = -1
        self.folder = None
        self.sort = self.settings.value("sort", "name")
        self.cache = ImageCache()
        self.cache.loaded.connect(self._on_loaded)
        self.thumbs = ThumbLoader()
        self.thumbs.ready.connect(self._on_thumb)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._rescan_soon.start())
        self._rescan_soon = QTimer(self, singleShot=True, interval=400, timeout=self._rescan)
        self.slideshow = QTimer(self, interval=int(float(self.settings.value("slide_secs", 4)) * 1000),
                                timeout=lambda: self.go(1, wrap=True))
        self._pre_fullscreen_info = True
        self.markup = {}          # path -> list of strokes (image pixel coordinates)
        self.markup_undo = {}     # path -> list of previous stroke lists
        self.markup_redo = {}
        self.markup_unsaved = set()

        self._build()
        self._actions()
        self.apply_theme()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.info.setVisible(self.settings.value("show_info", "true") == "true")
        self.btn_info.setChecked(self.info.isVisible())
        self.strip.setVisible(self.settings.value("show_strip", "true") == "true")
        self.btn_strip.setChecked(self.strip.isVisible())
        if files:
            QTimer.singleShot(0, lambda: self.open_paths(list(files)))
        else:
            self._update_chrome()

    # ================================================================== UI
    def _build(self):
        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        tb = QWidget(objectName="Toolbar")
        tb.setFixedHeight(50)
        self.toolbar = tb
        h = QHBoxLayout(tb)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(4)
        self.btn_open = icon_button("folder", "Open (Ctrl+O)")
        self.btn_open.clicked.connect(self.open_dialog)
        self.btn_prev = icon_button("chevron_left", "Previous (←)")
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_next = icon_button("chevron_right", "Next (→)")
        self.btn_next.clicked.connect(lambda: self.go(1))
        for b in (self.btn_open, self.btn_prev, self.btn_next):
            h.addWidget(b)
        h.addStretch(1)
        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        self.lbl_title = QLabel(APP, objectName="Title")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub = QLabel("", objectName="Subtitle")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tbox.addWidget(self.lbl_title)
        tbox.addWidget(self.lbl_sub)
        h.addLayout(tbox)
        h.addStretch(1)
        self.btn_zoom_out = icon_button("zoom_out", "Zoom Out (−)")
        self.btn_zoom_out.clicked.connect(lambda: self.view.zoom_step(-1))
        self.btn_zoom_in = icon_button("zoom_in", "Zoom In (+)")
        self.btn_zoom_in.clicked.connect(lambda: self.view.zoom_step(1))
        self.btn_fit = icon_button("fit", "Fit / Actual Size (Ctrl+0 / Ctrl+1)")
        self.btn_fit.clicked.connect(self.toggle_fit)
        self.btn_rot = icon_button("rotate_left", "Rotate Left (Ctrl+L)")
        self.btn_rot.clicked.connect(lambda: self.rotate(-90))
        self.btn_rot_r = icon_button("rotate_right", "Rotate Right (Ctrl+R)")
        self.btn_rot_r.clicked.connect(lambda: self.rotate(90))
        self.btn_show = icon_button("slideshow", "Slideshow (F5)")
        self.btn_show.clicked.connect(self.start_slideshow)
        self.btn_trash = icon_button("trash", "Move to Recycle Bin (Delete)")
        self.btn_trash.clicked.connect(self.delete_current)
        self.btn_strip = icon_button("filmstrip", "Show/Hide Filmstrip (F)", checkable=True)
        self.btn_strip.toggled.connect(self._toggle_strip)
        self.btn_info = icon_button("inspector", "Show/Hide Info (I)", checkable=True)
        self.btn_info.toggled.connect(self._toggle_info)
        self.btn_more = icon_button("more", "Menu")
        self.btn_markup = icon_button("pen", "Markup: draw and write on the photo (M)", checkable=True)
        self.btn_markup.toggled.connect(self._toggle_markup)
        for b in (self.btn_markup, self.btn_zoom_out, self.btn_zoom_in, self.btn_fit, self.btn_rot, self.btn_rot_r,
                  self.btn_show, self.btn_trash):
            h.addWidget(b)
        sep = QWidget()
        sep.setFixedSize(10, 1)
        h.addWidget(sep)
        h.addWidget(self.btn_strip)
        h.addWidget(self.btn_info)
        h.addWidget(self.btn_more)
        v.addWidget(tb)
        self.markup_bar = self._build_markup_bar()
        self.markup_bar.hide()
        v.addWidget(self.markup_bar)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.view = PhotoView()
        self.view.navigate.connect(self.go)
        self.view.filesDropped.connect(self.open_paths)
        self.view.zoomChanged.connect(lambda _: self._update_sub())
        self.view.strokeAdded.connect(self._on_stroke)
        self.view.eraseAt.connect(self._on_erase)
        self.view.textRequested.connect(self._on_text)
        body.addWidget(self.view, 1)
        self.info = InfoPanel()
        body.addWidget(self.info)
        v.addLayout(body, 1)
        self.strip = Filmstrip()
        self.strip.activated.connect(self.show_index)
        self.strip.visibleRange.connect(self._want_thumbs)
        v.addWidget(self.strip)
        self.size_slider.setValue(int(self.settings.value("pen_px", 4)))
        self.view.pen_px = float(self.size_slider.value())
        self.set_color(self.settings.value("pen_color", SYSTEM_COLORS["Red"]))

    # ================================================================== markup
    def _build_markup_bar(self):
        bar = QWidget(objectName="Toolbar")
        bar.setFixedHeight(44)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(3)
        self.tool_buttons = {}
        for tool, tip in (("pen", "Sketch (P)"), ("line", "Line (L)"), ("arrow", "Arrow (A)"), ("rect", "Rectangle (R)"),
                          ("ellipse", "Ellipse (O)"), ("text", "Text (T)"), ("eraser", "Eraser (E)")):
            b = icon_button(tool, tip, checkable=True, size=17, accent_when_checked=True)
            b.clicked.connect(lambda _=False, t=tool: self.set_tool(t))
            self.tool_buttons[tool] = b
            h.addWidget(b)
        sep = QWidget()
        sep.setFixedSize(14, 1)
        h.addWidget(sep)
        self.swatches = []
        for name in ("Red", "Orange", "Yellow", "Green", "Blue", "Purple", "White", "Black"):
            sw = Swatch(SYSTEM_COLORS[name])
            sw.setToolTip(name)
            sw.clicked.connect(self.set_color)
            self.swatches.append(sw)
            h.addWidget(sw)
        sep2 = QWidget()
        sep2.setFixedSize(10, 1)
        h.addWidget(sep2)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 24)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip("Line thickness")
        self.size_slider.valueChanged.connect(lambda v: setattr(self.view, "pen_px", float(v)))
        h.addWidget(self.size_slider)
        for name, tip, fn in (("undo", "Undo (Ctrl+Z)", self.markup_undo_step),
                              ("redo", "Redo (Ctrl+Y)", self.markup_redo_step),
                              ("trash", "Clear markup on this photo", self.markup_clear)):
            b = icon_button(name, tip, size=17)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch(1)
        self.btn_copy_markup = QPushButton("Copy")
        self.btn_copy_markup.setToolTip("Copy the photo with your markup to the clipboard (Ctrl+C)")
        self.btn_copy_markup.clicked.connect(self.copy_image)
        self.btn_save_markup = QPushButton("Save…")
        self.btn_save_markup.setObjectName("Primary")
        self.btn_save_markup.setToolTip("Save a copy of the photo with your markup (Ctrl+S)")
        self.btn_save_markup.clicked.connect(self.save_markup)
        h.addWidget(self.btn_copy_markup)
        h.addWidget(self.btn_save_markup)
        return bar

    def _toggle_markup(self, on):
        self.markup_bar.setVisible(on)
        self.set_tool(self.settings.value("pen_tool", "pen") if on else None)

    def set_tool(self, tool):
        if tool and self.slideshow.isActive():
            self.slideshow.stop()
        self.view.tool = tool
        for t, b in self.tool_buttons.items():
            b.setChecked(t == tool)
        if tool:
            self.settings.setValue("pen_tool", tool)
            if not self.btn_markup.isChecked():
                self.btn_markup.setChecked(True)
        self.view.setCursor(Qt.CursorShape.CrossCursor if tool else Qt.CursorShape.ArrowCursor)

    def set_color(self, c):
        self.view.color = c
        self.settings.setValue("pen_color", c)
        for sw in self.swatches:
            sw.selected = sw.color.lower() == c.lower()
            sw.update()

    def _markup_set(self, strokes, record=True):
        p = self._current()
        if not p:
            return
        if record:
            self.markup_undo.setdefault(p, []).append(list(self.markup.get(p, [])))
            self.markup_redo[p] = []
        self.markup[p] = strokes
        self.view.strokes = strokes
        if strokes:
            self.markup_unsaved.add(p)
        else:
            self.markup_unsaved.discard(p)
        self.view.update()

    def _on_stroke(self, st):
        p = self._current()
        if p:
            self.settings.setValue("pen_px", self.size_slider.value())
            self._markup_set(self.markup.get(p, []) + [st])

    def _on_text(self, x, y):
        text, ok = QInputDialog.getText(self, "Add Text", "Text:")
        if ok and text.strip():
            # text height on screen is about 7 x w: keep it readable relative to the thickness slider
            w = max(1.0, (2.0 + self.view.pen_px * 0.25) / max(self.view.scale, 1e-6))
            self._on_stroke({"t": "text", "c": self.view.color, "w": w, "s": text.strip(), "p": [[x, y]]})

    def _on_erase(self, x, y, r):
        p = self._current()
        strokes = self.markup.get(p, []) if p else []
        keep = [st for st in strokes
                if not any((px - x) ** 2 + (py - y) ** 2 <= (r + st["w"]) ** 2 for px, py in self._sample(st))]
        if len(keep) != len(strokes):
            self._markup_set(keep)

    @staticmethod
    def _sample(st):
        pts = st["p"]
        if st["t"] in ("rect", "ellipse") and len(pts) == 2:
            (x0, y0), (x1, y1) = pts
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (mx, y0), (mx, y1), (x0, my), (x1, my)]
        if st["t"] in ("line", "arrow") and len(pts) == 2:
            (x0, y0), (x1, y1) = pts
            return [(x0 + (x1 - x0) * k / 12, y0 + (y1 - y0) * k / 12) for k in range(13)]
        return [tuple(q) for q in pts]

    def markup_undo_step(self):
        p = self._current()
        stack = self.markup_undo.get(p) if p else None
        if stack:
            self.markup_redo.setdefault(p, []).append(list(self.markup.get(p, [])))
            self._markup_set(stack.pop(), record=False)

    def markup_redo_step(self):
        p = self._current()
        stack = self.markup_redo.get(p) if p else None
        if stack:
            self.markup_undo.setdefault(p, []).append(list(self.markup.get(p, [])))
            self._markup_set(stack.pop(), record=False)

    def markup_clear(self):
        p = self._current()
        if p and self.markup.get(p):
            self._markup_set([])

    def save_markup(self):
        p = self._current()
        img = self.view.rendered_image()
        if not p or img is None or self.view.placeholder:
            return
        base, ext = os.path.splitext(os.path.basename(p))
        jpg = ext.lower() in (".jpg", ".jpeg", ".heic", ".heif") and not img.hasAlphaChannel()
        out_ext = ".jpg" if jpg else ".png"
        default = os.path.join(self.settings.value("markup_dir", os.path.dirname(p)), f"{base} markup{out_ext}")
        filters = "JPEG (*.jpg);;PNG (*.png)" if jpg else "PNG (*.png);;JPEG (*.jpg)"
        path, _ = QFileDialog.getSaveFileName(self, "Save Photo with Markup", default, filters)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += out_ext
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(p)):
            r = QMessageBox.question(self, APP, "Replace the original photo with the marked-up version?\n\n"
                                     "The original can't be recovered afterwards.")
            if r != QMessageBox.StandardButton.Yes:
                return
        if not img.save(path, quality=95):
            QMessageBox.warning(self, APP, "Couldn't save the image.")
            return
        self.settings.setValue("markup_dir", os.path.dirname(path))
        self.markup_unsaved.discard(p)
        self._flash(f"Saved {os.path.basename(path)}", 1600)

    def _act(self, menu, text, shortcut, fn, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.setCheckable(checkable)
        a.triggered.connect(fn)
        self.addAction(a)
        if menu is not None:
            menu.addAction(a)
        return a

    def _actions(self):
        m = QMenu(self)
        fm = m.addMenu("File")
        self._act(fm, "Open…", "Ctrl+O", self.open_dialog)
        self._act(fm, "Open Folder…", "Ctrl+Shift+O", self.open_folder_dialog)
        fm.addSeparator()
        self._act(fm, "Copy Image", "Ctrl+C", self.copy_image)
        self._act(fm, "Copy File Path", "Ctrl+Shift+C", self.copy_path)
        self._act(fm, "Save", "Ctrl+S", self._save_shortcut)
        self._act(fm, "Save Photo with Markup…", None, self.save_markup)
        self._act(fm, "Save Rotation", None, self.save_rotation)
        self._act(fm, "Save a Copy As…", "Ctrl+Shift+S", self.save_copy)
        self._act(fm, "Show in Explorer" if sys.platform == "win32" else "Show in Finder", "Ctrl+E", self.reveal)
        self._act(fm, "Move to Recycle Bin" if sys.platform == "win32" else "Move to Trash", "Delete",
                  self.delete_current)
        vm = m.addMenu("View")
        self._act(vm, "Zoom In", "Ctrl+=", lambda: self.view.zoom_step(1))
        self._act(vm, "Zoom Out", "Ctrl+-", lambda: self.view.zoom_step(-1))
        self._act(vm, "Fit to Window", "Ctrl+0", self.view.set_fit)
        self._act(vm, "Actual Size", "Ctrl+1", lambda: self.view.actual_size())
        vm.addSeparator()
        self._act(vm, "Rotate Left", "Ctrl+L", lambda: self.rotate(-90))
        self._act(vm, "Rotate Right", "Ctrl+R", lambda: self.rotate(90))
        vm.addSeparator()
        self._act(vm, "Show/Hide Filmstrip", "F", lambda: self.btn_strip.toggle())
        self._act(vm, "Show/Hide Info", "I", lambda: self.btn_info.toggle())
        self._act(vm, "Full Screen", "F11", self.toggle_fullscreen)
        self._act(vm, "Slideshow", "F5", self.start_slideshow)
        sm = vm.addMenu("Sort By")
        self.sort_actions = {}
        for key, label in (("name", "Name"), ("date", "Date Modified"), ("size", "File Size")):
            a = self._act(sm, label, None, lambda _=False, k=key: self.set_sort(k), checkable=True)
            a.setChecked(key == self.sort)
            self.sort_actions[key] = a
        am = vm.addMenu("Appearance")
        self._act(am, "Dark", None, lambda: self.set_appearance("dark"))
        self._act(am, "Light", None, lambda: self.set_appearance("light"))
        m.addSeparator()
        self._act(m, "Set as Default Photo Viewer…", None, self.make_default)
        self._act(m, "Keyboard Shortcuts", "F1", self.show_shortcuts)
        self._act(m, f"About {APP}", None, self.show_about)
        self.menu = m
        self.btn_more.clicked.connect(lambda: m.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 4))))

        def key(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.WindowShortcut)
            s.activated.connect(fn)

        key("Right", lambda: self.go(1))
        key("Left", lambda: self.go(-1))
        key("Down", lambda: self.go(1))
        key("Up", lambda: self.go(-1))
        key("PgDown", lambda: self.go(1))
        key("PgUp", lambda: self.go(-1))
        key("Home", lambda: self.show_index(0))
        key("End", lambda: self.show_index(len(self.paths) - 1))
        key("Space", self._space)
        key("+", lambda: self.view.zoom_step(1))
        key("=", lambda: self.view.zoom_step(1))
        key("-", lambda: self.view.zoom_step(-1))
        key("Escape", self._escape)
        key("Return", self.toggle_fullscreen)
        key("M", lambda: self.btn_markup.toggle())
        key("Ctrl+Z", self.markup_undo_step)
        key("Ctrl+Y", self.markup_redo_step)
        key("Ctrl+Shift+Z", self.markup_redo_step)
        for k, t in (("P", "pen"), ("L", "line"), ("A", "arrow"), ("R", "rect"), ("O", "ellipse"), ("T", "text"),
                     ("E", "eraser")):
            key(k, lambda t=t: self.set_tool(t) if self.btn_markup.isChecked() else None)

    # ================================================================== theme
    def apply_theme(self):
        QApplication.instance().setStyleSheet(theme.stylesheet())
        refresh_all_icons()
        self._set_titlebar()
        for w in self.findChildren(QWidget):
            w.update()

    def set_appearance(self, name):
        theme.set_theme(name)
        self.settings.setValue("appearance", name)
        self.apply_theme()

    def _set_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            dark = ctypes.c_int(1 if T["name"] == "dark" else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
            r, g, b = T["toolbar"][:3]
            col = ctypes.c_int(r | (g << 8) | (b << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), 4)
            tr, tg, tb = T["text"][:3]
            tcol = ctypes.c_int(tr | (tg << 8) | (tb << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(tcol), 4)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._set_titlebar()

    # ================================================================== opening
    def open_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        start = self.folder or self.settings.value("last_dir", os.path.expanduser("~/Pictures"))
        files, _ = QFileDialog.getOpenFileNames(self, "Open", start, f"Images ({exts});;All files (*)")
        if files:
            self.open_paths(files)

    def open_folder_dialog(self):
        start = self.folder or self.settings.value("last_dir", os.path.expanduser("~/Pictures"))
        d = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if d:
            self.open_paths([d])

    def open_paths(self, paths):
        """One file → browse its whole folder; several files → just those; a folder → its photos."""
        paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
        if not paths:
            return
        start = None
        if len(paths) == 1 and os.path.isdir(paths[0]):
            folder, items = paths[0], list_folder(paths[0], self.sort)
        elif len(paths) == 1:
            folder, items, start = os.path.dirname(paths[0]), list_folder(os.path.dirname(paths[0]), self.sort), paths[0]
            if start not in items and is_image(start):
                items.append(start)
        else:
            items = [p for p in paths if os.path.isfile(p) and is_image(p)]
            for d in (p for p in paths if os.path.isdir(p)):
                items += list_folder(d, self.sort)
            folder = os.path.dirname(items[0]) if items else None
        if not items:
            QMessageBox.information(self, APP, "No photos found there.")
            return
        self._set_folder(folder, items)
        self.show_index(items.index(start) if start in items else 0, fade=False)

    def _set_folder(self, folder, items):
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.folder = folder
        if folder:
            self.watcher.addPath(folder)
            self.settings.setValue("last_dir", folder)
        self.paths = items
        self.index = -1
        self.cache.clear()
        self.thumbs.reset()
        self.strip.set_paths(items)

    def _rescan(self):
        if not self.folder:
            return
        cur = self.paths[self.index] if 0 <= self.index < len(self.paths) else None
        items = list_folder(self.folder, self.sort)
        if items == self.paths:
            return
        self.paths = items
        self.strip.set_paths(items)
        if not items:
            self.index = -1
            self.view.clear()
            self._update_chrome()
            return
        i = items.index(cur) if cur in items else min(max(0, self.index), len(items) - 1)
        self.index = -1
        self.show_index(i, fade=False)

    def set_sort(self, key):
        self.sort = key
        self.settings.setValue("sort", key)
        for k, a in self.sort_actions.items():
            a.setChecked(k == key)
        self._rescan()

    # ================================================================== navigation
    def go(self, step, wrap=False):
        if not self.paths:
            return
        i = self.index + step
        if wrap:
            i %= len(self.paths)
        self.show_index(max(0, min(len(self.paths) - 1, i)))

    def show_index(self, i, fade=True):
        if not self.paths or i == self.index or not (0 <= i < len(self.paths)):
            return
        self.index = i
        path = self.paths[i]
        img = self.cache.get(path)
        if img is not None:
            self.view.set_image(img, fade=fade)
        else:
            thumb = self.thumbs.thumbs.get(path)
            if thumb is not None and not thumb.isNull():
                self.view.set_image(thumb, placeholder=True, fade=fade)
            else:
                self.view.set_image(None, fade=fade)
                self.view.empty_hint = False
        if is_animated(path):
            self.view.play_movie(path)
        self.view.strokes = self.markup.get(path, [])
        self.strip.set_current(i)
        n = len(self.paths)
        self.cache.want([path] + [self.paths[(i + d) % n] for d in (1, -1, 2, 3, -2) if n > 1])
        self._update_chrome()
        self._update_info(img)

    def _on_loaded(self, path, img):
        if not (0 <= self.index < len(self.paths)) or self.paths[self.index] != path:
            return
        if img is None or img.isNull():
            self.view.set_image(None, fade=False)
            self.view.empty_hint = False
            self.view.message = "Can't open this file"
            self.view.update()
            QTimer.singleShot(2500, self._clear_message)
            return
        if self.view.placeholder:
            self.view.upgrade_image(img)
        elif self.view.img is None:
            self.view.set_image(img, fade=True)
        if is_animated(path):
            self.view.play_movie(path)
        self._update_chrome()
        self._update_info(img)

    def _clear_message(self):
        self.view.message = ""
        self.view.update()

    def _on_thumb(self, path, img):
        self.strip.set_thumb(path, img)
        if 0 <= self.index < len(self.paths) and self.paths[self.index] == path and self.view.img is None:
            self.view.set_image(img, placeholder=True, fade=False)

    def _want_thumbs(self, a, b):
        if not self.paths:
            return
        order = list(range(a, b))
        if 0 <= self.index < len(self.paths):
            order.sort(key=lambda k: abs(k - self.index))
        self.thumbs.request([self.paths[k] for k in order])

    # ================================================================== chrome
    def _update_chrome(self):
        has = 0 <= self.index < len(self.paths)
        if not has:
            self.lbl_title.setText(APP)
            self.lbl_sub.setText("")
            self.setWindowTitle(APP)
            self.view.empty_hint = True
            self.info.set_info(None, None)
            self.info.hist.set_image(None)
        else:
            name = os.path.basename(self.paths[self.index])
            self.lbl_title.setText(name)
            self.setWindowTitle(f"{name} — {APP}")
            self._update_sub()
        for b in (self.btn_prev, self.btn_next, self.btn_zoom_in, self.btn_zoom_out, self.btn_fit, self.btn_rot,
                  self.btn_rot_r, self.btn_show, self.btn_trash):
            b.setEnabled(has)
        if has:
            self.btn_prev.setEnabled(self.index > 0)
            self.btn_next.setEnabled(self.index < len(self.paths) - 1)

    def _update_sub(self):
        if not (0 <= self.index < len(self.paths)):
            return
        parts = [f"{self.index + 1} of {len(self.paths)}"]
        img = self.view.img
        if img is not None and not self.view.placeholder:
            w, h = (img.height(), img.width()) if self.view.rotation % 180 else (img.width(), img.height())
            parts.append(f"{w}×{h}")
            parts.append(f"{self.view.scale * 100:.0f}%")
        self.lbl_sub.setText("  ·  ".join(parts))

    def _update_info(self, img):
        if not self.info.isVisible() or not (0 <= self.index < len(self.paths)):
            return
        path = self.paths[self.index]
        try:
            info, exif = read_info(path, img)
        except OSError:
            info, exif = None, None
        self.info.set_info(info, exif)
        self.info.hist.set_image(img if img is not None else self.thumbs.thumbs.get(path))

    def _toggle_info(self, on):
        self.info.setVisible(on)
        self.settings.setValue("show_info", "true" if on else "false")
        if on:
            self._update_info(self.view.img if not self.view.placeholder else None)

    def _toggle_strip(self, on):
        self.strip.setVisible(on)
        self.settings.setValue("show_strip", "true" if on else "false")
        if on and self.index >= 0:
            QTimer.singleShot(0, lambda: self.strip.set_current(self.index, animate=False))

    def toggle_fit(self):
        if self.view.fit:
            self.view.actual_size()
        else:
            self.view.set_fit()

    def rotate(self, deg):
        if self.view.img is None:
            return
        self.view.rotate(deg)
        self._update_sub()
        if self.view.rotation and not self.view.strokes:
            self.view.message = "Rotated · Ctrl+S saves it to the file"
            self.view.update()
            QTimer.singleShot(1800, self._clear_message)

    # ================================================================== modes
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.toolbar.show()
            self.strip.setVisible(self.btn_strip.isChecked())
            self.info.setVisible(self.btn_info.isChecked())
            self.slideshow.stop()
        else:
            self.toolbar.hide()
            self.strip.hide()
            self.info.hide()
            self.showFullScreen()
        QTimer.singleShot(50, self.view.set_fit)

    def start_slideshow(self):
        if not self.paths:
            return
        if not self.isFullScreen():
            self.toggle_fullscreen()
        self.view.set_fit()
        self.slideshow.start()
        self.view.message = "Slideshow · Space pauses · Esc exits"
        self.view.update()
        QTimer.singleShot(2000, self._clear_message)

    def _space(self):
        if self.isFullScreen() and self.slideshow.isActive():
            self.slideshow.stop()
            self.view.message = "Paused"
            self.view.update()
            QTimer.singleShot(900, self._clear_message)
        elif self.isFullScreen() and self.paths:
            self.slideshow.start()
            self.go(1, wrap=True)
        else:
            self.go(1)

    def _escape(self):
        if self.btn_markup.isChecked():
            self.btn_markup.setChecked(False)
        elif self.isFullScreen():
            self.toggle_fullscreen()
        elif not self.view.fit:
            self.view.set_fit()

    # ================================================================== file actions
    def _current(self):
        return self.paths[self.index] if 0 <= self.index < len(self.paths) else None

    def copy_image(self):
        img = self.view.rendered_image()
        if img is not None:
            QGuiApplication.clipboard().setImage(img)
            if self.view.strokes:
                self.markup_unsaved.discard(self._current())
                self._flash("Copied with markup")
            else:
                self._flash("Copied")

    def copy_path(self):
        p = self._current()
        if p:
            QGuiApplication.clipboard().setText(p)
            self._flash("Path copied")

    def _flash(self, text, ms=1100):
        self.view.message = text
        self.view.update()
        QTimer.singleShot(ms, self._clear_message)

    def reveal(self):
        p = self._current()
        if not p:
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(p)])

    def delete_current(self):
        p = self._current()
        if not p:
            return
        bin_name = "Recycle Bin" if sys.platform == "win32" else "Trash"
        if self.settings.value("confirm_delete", "true") == "true":
            box = QMessageBox(self)
            box.setWindowTitle(APP)
            box.setText(f"Move “{os.path.basename(p)}” to the {bin_name}?")
            box.setInformativeText(f"You can restore it from the {bin_name}.")
            box.setStandardButtons(QMessageBox.StandardButton.Cancel)
            ok = box.addButton(f"Move to {bin_name}", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(ok)
            box.setCheckBox(QCheckBox("Don't ask again"))
            box.exec()
            if box.clickedButton() is not ok:
                return
            if box.checkBox().isChecked():
                self.settings.setValue("confirm_delete", "false")
        try:
            from send2trash import send2trash
            send2trash(os.path.normpath(p))
        except Exception as e:
            QMessageBox.warning(self, APP, f"Couldn't move the file to the {bin_name}:\n\n{e}")
            return
        self.cache.drop(p)
        i = self.index
        self.paths.pop(i)
        self.strip.set_paths(self.paths)
        self.index = -1
        if self.paths:
            self.show_index(min(i, len(self.paths) - 1), fade=True)
        else:
            self.view.clear()
            self._update_chrome()
        self._flash(f"Moved to {bin_name}")

    def _save_shortcut(self):
        if self.view.strokes:
            self.save_markup()
        else:
            self.save_rotation()

    def save_rotation(self):
        p = self._current()
        if not p or self.view.rotation == 0:
            self._flash("Nothing to save: rotate first (Ctrl+L / Ctrl+R)", 1600)
            return
        if self.markup.get(p):
            self._flash("Save or clear the markup first", 1600)
            return
        try:
            from .loader import _pil
            Image = _pil()
            from PIL import ImageOps
            with Image.open(p) as im:
                fmt = im.format
                exif = im.getexif()
                icc = im.info.get("icc_profile")
                im = ImageOps.exif_transpose(im)
                im = im.rotate(-self.view.rotation, expand=True)
                if exif:
                    exif[0x0112] = 1   # orientation is now baked into the pixels
                kw = {}
                if fmt == "JPEG":
                    kw = {"quality": 95, "subsampling": 0, "optimize": True}
                if icc:
                    kw["icc_profile"] = icc
                if exif and fmt in ("JPEG", "PNG", "WEBP", "TIFF", "HEIF"):
                    kw["exif"] = exif.tobytes()
                tmp = p + ".tmp-stillframe"
                im.save(tmp, format=fmt, **kw)
            os.replace(tmp, p)
        except Exception as e:
            try:
                os.remove(p + ".tmp-stillframe")
            except OSError:
                pass
            QMessageBox.warning(self, APP, f"Couldn't save the rotation:\n\n{e}")
            return
        self.cache.drop(p)
        self.thumbs.thumbs.pop(p, None)
        self.thumbs.request([p])
        i, self.index = self.index, -1
        self.show_index(i, fade=False)
        self._flash("Rotation saved")

    def save_copy(self):
        p = self._current()
        img = self.view.rendered_image()
        if not p or img is None:
            return
        base = os.path.splitext(os.path.basename(p))[0]
        path, _ = QFileDialog.getSaveFileName(self, "Save a Copy As", os.path.join(os.path.dirname(p), base + " copy.jpg"),
                                              "JPEG (*.jpg);;PNG (*.png);;WebP (*.webp);;TIFF (*.tif)")
        if path:
            ok = img.save(path, quality=95)
            self._flash("Saved" if ok else "Couldn't save")

    def make_default(self):
        msg = STILLFRAME_ASSOC.make_default()
        if msg:
            QMessageBox.information(self, APP, msg)

    # ================================================================== dialogs
    def show_shortcuts(self):
        rows = [("← → or ↑ ↓", "Previous / next photo"), ("Home / End", "First / last photo"),
                ("Scroll / + −", "Zoom at the cursor"), ("Double-click", "Toggle Fit and 100%"),
                ("Ctrl+0 / Ctrl+1", "Fit / Actual size"), ("Drag", "Pan when zoomed in"),
                ("Ctrl+L / Ctrl+R", "Rotate left / right"), ("Ctrl+S", "Save rotation to the file"),
                ("F5", "Slideshow (Space pauses)"), ("F11 or Enter", "Full screen"), ("Esc", "Exit full screen / fit"),
                ("I / F", "Show/hide info / filmstrip"), ("Ctrl+C", "Copy image"), ("Ctrl+E", "Show in folder"),
                ("Delete", "Move to Recycle Bin"), ("M", "Markup: draw and write on the photo"),
                ("P L A R O T E", "Sketch, line, arrow, rectangle, ellipse, text, eraser"),
                ("Ctrl+Z / Ctrl+Y", "Undo / redo markup"), ("Ctrl+C", "Copy (includes markup)"),
                ("Ctrl+S", "Save a copy with markup")]
        text = "<table cellspacing=6>" + "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def show_about(self):
        d = QDialog(self)
        d.setWindowTitle(f"About {APP}")
        d.setFixedWidth(340)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(28, 28, 28, 22)
        lay.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(96, 96))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        lay.addSpacing(8)
        for text, style in ((APP, f"font-size: {theme.pt(15)}; font-weight: 600;"),
                            (f"Version {__version__}", f"color: {theme.css('text2')};"),
                            ("", ""),
                            ("Designed and built by <span style=\"font-weight:600\">Miguel Rato</span>", ""),
                            ("A fast, simple photo viewer.", f"color: {theme.css('text2')};"),
                            (f'<a href="{REPO_URL}" style="color:{theme.css("accent")}; text-decoration:none">'
                             f'{REPO_URL.replace("https://", "")}</a>', ""),
                            ("A companion to Frameline · Interface by Qt", f"color: {theme.css('text3')}; font-size: {theme.pt(8)};")):
            l = QLabel(text)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setWordWrap(True)
            l.setOpenExternalLinks(True)
            if style:
                l.setStyleSheet(style)
            lay.addWidget(l)
        lay.addSpacing(10)
        ok = QPushButton("OK")
        ok.setObjectName("Primary")
        ok.clicked.connect(d.accept)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignCenter)
        d.exec()

    def closeEvent(self, e):
        pending = [q for q in self.markup_unsaved if self.markup.get(q)]
        if pending:
            n = len(pending)
            plural = "s" if n > 1 else ""
            r = QMessageBox.question(self, APP, f"You have markup on {n} photo{plural} that hasn't been saved or "
                                     "copied. Quit anyway?")
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        self.cache.close()
        self.thumbs.close()
        super().closeEvent(e)


from frameline.assoc import Association  # noqa: E402
from .loader import IMAGE_EXTS as _EXTS  # noqa: E402

STILLFRAME_ASSOC = Association(
    "Stillframe", "Stillframe.Image", "Stillframe.exe", exts=sorted(_EXTS - {".svgz", ".pbm", ".pgm", ".ppm"}),
    description="A fast, simple photo viewer", type_name="Stillframe image", run_script="run_stillframe.py",
    mac_hint="To open all photos with Stillframe: in Finder, select a photo, press ⌘I, choose Stillframe under "
             "“Open with”, then click “Change All…”. Repeat once per file type (.jpg, .heic, .png, …).",
    linux_mimes=("image/jpeg", "image/png", "image/webp", "image/gif", "image/heic"))
