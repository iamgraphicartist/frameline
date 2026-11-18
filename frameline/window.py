"""Main window: layout, playback engine, library, inspector, menus, sessions."""
import json
import math
import os
import subprocess
import sys
import time

from PySide6.QtCore import Qt, QTimer, QSize, QSettings, QRectF, QPoint, QElapsedTimer
from PySide6.QtGui import (QAction, QKeySequence, QShortcut, QPainter, QColor, QFont, QFontMetricsF, QImage,
                           QGuiApplication, QPen, QPainterPath, QIcon, QPixmap, QLinearGradient)
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QListWidget,
                               QListWidgetItem, QStyledItemDelegate, QStyle, QLineEdit, QStackedWidget,
                               QScrollArea, QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QPushButton, QMenu,
                               QFileDialog, QMessageBox, QInputDialog, QGridLayout, QProgressDialog, QApplication,
                               QButtonGroup, QSizePolicy)

from . import theme, icons
from .theme import qc, T, SYSTEM_COLORS
from .media import make_sources, CACHE, VIDEO_EXT, IMAGE_EXT, decode_frame_sync, MediaSource
from .model import Project, Clip
from .viewer import Viewer, draw_strokes
from .timeline import Timeline, timecode
from .audio import AudioEngine
from .widgets import icon_button, refresh_all_icons, refresh_icon, Segmented, Switch, Swatch, row, section
from .remote import RemoteServer, PORT

APP = "Frameline"
REPO_URL = "https://github.com/iamgraphicartist/frameline"
SESSION_EXT = ".flsession"
ZWSP = "​"  # zero-width space: lets long paths wrap
SPEEDS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0, 8.0]
MASKS = [("None", None), ("1.85 : 1", 1.85), ("2.00 : 1", 2.0), ("2.35 : 1", 2.35), ("2.39 : 1", 2.39),
         ("16 : 9", 16 / 9), ("4 : 3", 4 / 3), ("1 : 1", 1.0), ("4 : 5", 0.8), ("9 : 16", 9 / 16)]


def human_size(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def app_icon():
    from .appicon import qicon
    return qicon()


class LibraryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 54)

    def paint(self, p, option, index):
        src = index.data(Qt.ItemDataRole.UserRole)
        if src is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc("accent"))
            p.drawRoundedRect(r, 8, 8)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc("separator"))
            p.drawRoundedRect(r, 8, 8)
        tr = QRectF(r.x() + 7, r.y() + 7, 64, r.height() - 14)
        path = QPainterPath()
        path.addRoundedRect(tr, 5, 5)
        p.setClipPath(path)
        p.fillRect(tr, QColor(0, 0, 0, 90))
        if src.thumb is not None:
            th = src.thumb
            s = max(tr.width() / th.width(), tr.height() / th.height())
            w, h = th.width() * s, th.height() * s
            p.drawImage(QRectF(tr.center().x() - w / 2, tr.center().y() - h / 2, w, h), th)
        else:
            name = {"video": "film", "sequence": "sequence", "image": "photo"}.get(src.kind, "film")
            p.drawPixmap(int(tr.center().x() - 9), int(tr.center().y() - 9), icons.pixmap(name, "#9A9AA0", 18))
        p.setClipping(False)
        tx = tr.right() + 10
        p.setPen(QColor(255, 255, 255) if selected else qc("text"))
        f = theme.font(12.5, QFont.Weight.DemiBold)
        p.setFont(f)
        fm = QFontMetricsF(f)
        p.drawText(QRectF(tx, r.y() + 8, r.right() - tx - 8, 18), Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(src.name, Qt.TextElideMode.ElideMiddle, r.right() - tx - 8))
        if src.error:
            meta = "Unsupported file"
        elif src.kind == "image":
            meta = f"{src.width}×{src.height} · Still"
        else:
            meta = f"{src.width}×{src.height} · {src.fps:g} fps · {src.frames}f"
        p.setPen(QColor(255, 255, 255, 200) if selected else (QColor("#FF6961") if src.error else qc("text2")))
        f2 = theme.font(11)
        p.setFont(f2)
        p.drawText(QRectF(tx, r.y() + 27, r.right() - tx - 8, 16), Qt.AlignmentFlag.AlignLeft,
                   QFontMetricsF(f2).elidedText(meta, Qt.TextElideMode.ElideRight, r.right() - tx - 8))
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self, files=None):
        super().__init__()
        self.settings = QSettings(APP, APP)
        theme.set_theme(self.settings.value("appearance", "dark"))
        CACHE.set_budget(int(self.settings.value("cache_mb", 3072)))
        self.project = Project()
        self.audio = AudioEngine()
        self.audio.volume = float(self.settings.value("volume", 0.8))
        self.frame = 0
        self.playing = False
        self.direction = 1
        self.speed = 1.0
        self.loop_mode = self.settings.value("loop_mode", "loop")
        self.in_pt = 0
        self.out_pt = -1
        self.every_frame = False
        self.audio_scrub = self.settings.value("audio_scrub", "true") == "true"
        self.base = int(self.settings.value("frame_base", 1))
        self.tc_mode = False
        self.compare_source = None
        self.compare_offset = 0
        self.onion_on = False
        self.onion_before = 2
        self.onion_after = 0
        self.onion_opacity = 0.3
        self.ghost_annotations = True
        self.proxy = 1.0
        self._audio_key = None
        self._fps_frames = []
        self._last_drawn = None
        self._cache_dirty = True
        self._presentation = False
        self.remote = RemoteServer(self)
        self.remote.command.connect(self._on_remote)

        self.setWindowTitle(APP)
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(900, 560)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self.apply_theme()

        self.clock = QElapsedTimer()
        self.clock.start()
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.setInterval(2)
        self.play_timer.timeout.connect(self._tick)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(200)
        self.ui_timer.timeout.connect(self._ui_refresh)
        self.ui_timer.start()

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        if self.settings.value("remote", "false") == "true":
            self.remote.start()
        if self.settings.value("on_top", "false") == "true":
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if files:
            QTimer.singleShot(50, lambda: self.open_paths(files))
        self.refresh_all()

    # ================================================================== UI construction
    def _build_ui(self):
        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- toolbar
        tb = QWidget(objectName="Toolbar")
        tb.setFixedHeight(50)
        self.toolbar = tb
        h = QHBoxLayout(tb)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(4)
        self.btn_sidebar = icon_button("sidebar", "Show/Hide Library (Ctrl+1)", checkable=True)
        self.btn_sidebar.setChecked(True)
        self.btn_sidebar.toggled.connect(lambda on: self.sidebar.setVisible(on))
        self.btn_import = icon_button("plus", "Import Media (Ctrl+O)")
        self.btn_import.clicked.connect(self.import_dialog)
        h.addWidget(self.btn_sidebar)
        h.addWidget(self.btn_import)
        h.addStretch(1)
        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        self.lbl_title = QLabel(APP, objectName="Title")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub = QLabel("No media", objectName="Subtitle")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tbox.addWidget(self.lbl_title)
        tbox.addWidget(self.lbl_sub)
        h.addLayout(tbox)
        h.addStretch(1)
        self.btn_compare = icon_button("compare", "Compare A/B (C)", checkable=True)
        self.btn_compare.clicked.connect(self._toggle_compare)
        self.btn_draw = icon_button("pen", "Annotate (D)", checkable=True)
        self.btn_draw.clicked.connect(self._toggle_draw)
        self.btn_onion = icon_button("onion", "Onion Skin (Alt+O)", checkable=True)
        self.btn_onion.toggled.connect(self._set_onion)
        self.btn_guides = icon_button("grid", "Guides & Masks")
        self.btn_guides.clicked.connect(self._guides_menu)
        self.btn_snap = icon_button("camera", "Save Snapshot (Ctrl+E)")
        self.btn_snap.clicked.connect(self.save_snapshot)
        self.btn_full = icon_button("fullscreen", "Presentation Mode (F11)")
        self.btn_full.clicked.connect(self.toggle_presentation)
        self.btn_inspector = icon_button("inspector", "Show/Hide Inspector (Ctrl+2)", checkable=True)
        self.btn_inspector.setChecked(True)
        self.btn_inspector.toggled.connect(lambda on: self.inspector.setVisible(on))
        self.btn_more = icon_button("more", "Menu")
        for b in (self.btn_compare, self.btn_draw, self.btn_onion, self.btn_guides, self.btn_snap, self.btn_full):
            h.addWidget(b)
        sep = QWidget()
        sep.setFixedSize(10, 1)
        h.addWidget(sep)
        h.addWidget(self.btn_inspector)
        h.addWidget(self.btn_more)
        v.addWidget(tb)

        # ---- body
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(1)
        self.split.setChildrenCollapsible(False)
        self.sidebar = self._build_sidebar()
        self.viewer = Viewer()
        self.viewer.strokeFinished.connect(self._on_stroke)
        self.viewer.eraseAt.connect(self._on_erase)
        self.viewer.filesDropped.connect(self.open_paths)
        self.viewer.pixelInfo.connect(lambda s: self.lbl_pixel.setText(s))
        self.viewer.zoomChanged.connect(self._update_status)
        self.inspector = self._build_inspector()
        self.split.addWidget(self.sidebar)
        self.split.addWidget(self.viewer)
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([250, 900, 290])
        v.addWidget(self.split, 1)

        # ---- transport
        v.addWidget(self._build_transport())
        self.timeline = Timeline(self.project)
        self.timeline.base = self.base
        self.timeline.scrubbed.connect(self._on_scrub)
        self.timeline.scrubStarted.connect(self._scrub_start)
        self.timeline.rangeChanged.connect(self._on_range)
        self.timeline.clipMoved.connect(self._on_clip_moved)
        self.timeline.clipMenu.connect(self._clip_menu)
        self.timeline.emptyMenu.connect(self._timeline_menu)
        self.timeline.markerActivated.connect(self.edit_marker)
        v.addWidget(self.timeline)

    def _build_sidebar(self):
        w = QWidget(objectName="Sidebar")
        w.setMinimumWidth(200)
        w.setMaximumWidth(420)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(8)
        hdr = QHBoxLayout()
        t = QLabel("Library", objectName="Title")
        hdr.addWidget(t)
        hdr.addStretch(1)
        b = icon_button("folder", "Import Folder…", size=16, box=26)
        b.clicked.connect(self.import_folder_dialog)
        hdr.addWidget(b)
        lay.addLayout(hdr)
        self.search = QLineEdit(objectName="Search")
        self.search.setPlaceholderText("Search")
        self.search.addAction(icons.icon("search", "#8E8E93", size=14), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter_library)
        lay.addWidget(self.search)
        self.library = QListWidget()
        self.library.setItemDelegate(LibraryDelegate())
        self.library.setMouseTracking(True)
        self.library.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.library.itemDoubleClicked.connect(self._library_activate)
        self.library.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library.customContextMenuRequested.connect(self._library_menu)
        lay.addWidget(self.library, 1)
        self.lib_empty = QLabel("Imported media appears here.\nDouble-click to add to the timeline.",
                                objectName="Empty")
        self.lib_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lib_empty.setWordWrap(True)
        lay.addWidget(self.lib_empty)
        self.lbl_cache = QLabel("", objectName="Tertiary")
        lay.addWidget(self.lbl_cache)
        return w

    def _page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 6, 14, 14)
        lay.setSpacing(6)
        return page, lay

    def _build_inspector(self):
        w = QWidget(objectName="Inspector")
        w.setMinimumWidth(280)
        w.setMaximumWidth(400)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(6)
        segw = QWidget()
        sl = QHBoxLayout(segw)
        sl.setContentsMargins(12, 0, 12, 0)
        self.insp_seg = Segmented(["Info", "Compare", "Draw", "View"])
        sl.addWidget(self.insp_seg)
        lay.addWidget(segw)
        self.insp_stack = QStackedWidget()
        self.insp_seg.changed.connect(self.insp_stack.setCurrentIndex)
        for builder in (self._page_info, self._page_compare, self._page_draw, self._page_view):
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sa.setWidget(builder())
            self.insp_stack.addWidget(sa)
        lay.addWidget(self.insp_stack, 1)
        return w

    def _page_info(self):
        page, lay = self._page()
        self.info_name = QLabel("No clip", objectName="Title")
        self.info_name.setWordWrap(True)
        self.info_path = QLabel("", objectName="Tertiary")
        self.info_path.setWordWrap(True)
        self.info_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.info_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.info_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info_name)
        lay.addWidget(self.info_path)
        lay.addWidget(section("Media"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        self.info_fields = {}
        for i, k in enumerate(["Resolution", "Frame Rate", "Duration", "Codec", "Pixel Format", "File Size",
                               "Audio", "Source Frame"]):
            a = QLabel(k, objectName="Secondary")
            b = QLabel("—")
            b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(a, i, 0)
            grid.addWidget(b, i, 1)
            self.info_fields[k] = b
        lay.addLayout(grid)

        lay.addWidget(section("Playback"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0, 240)
        self.fps_spin.setDecimals(3)
        self.fps_spin.setSpecialValueText("Native")
        self.fps_spin.setFixedWidth(90)
        self.fps_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.fps_spin.valueChanged.connect(self._on_fps_override)
        lay.addWidget(row("Timeline FPS", self.fps_spin))
        self.sw_every = Switch(False)
        self.sw_every.toggled.connect(lambda v: setattr(self, "every_frame", v))
        lay.addWidget(row("Play every frame", self.sw_every))
        self.proxy_seg = Segmented(["Full", "½", "¼"], height=24)
        self.proxy_seg.setFixedWidth(120)
        self.proxy_seg.changed.connect(self._on_proxy)
        lay.addWidget(row("Resolution", self.proxy_seg))

        mh = QHBoxLayout()
        mh.addWidget(section("Markers"))
        mh.addStretch(1)
        b = icon_button("marker", "Add Marker (M)", size=15, box=24)
        b.clicked.connect(self.toggle_marker)
        mh.addWidget(b)
        lay.addLayout(mh)
        self.marker_list = QListWidget()
        self.marker_list.setFixedHeight(150)
        self.marker_list.setStyleSheet("QListWidget::item { padding: 4px 6px; }")
        self.marker_list.itemClicked.connect(lambda it: self.set_frame(it.data(Qt.ItemDataRole.UserRole)))
        self.marker_list.itemDoubleClicked.connect(lambda it: self.edit_marker(it.data(Qt.ItemDataRole.UserRole)))
        self.marker_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.marker_list.customContextMenuRequested.connect(self._marker_menu)
        lay.addWidget(self.marker_list)
        hint = QLabel("M adds a marker · Shift+←/→ jumps between them", objectName="Tertiary")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    def _page_compare(self):
        page, lay = self._page()
        lay.addWidget(section("Mode"))
        self.cmp_seg = Segmented(["Off", "Wipe", "Side", "Stack", "Blend", "Diff"], height=26)
        self.cmp_seg.changed.connect(self._on_compare_mode)
        lay.addWidget(self.cmp_seg)
        lay.addWidget(section("Source B"))
        self.cmp_combo = QComboBox()
        self.cmp_combo.currentIndexChanged.connect(self._on_compare_source)
        lay.addWidget(self.cmp_combo)
        self.cmp_offset = QSpinBox()
        self.cmp_offset.setRange(-100000, 100000)
        self.cmp_offset.setFixedWidth(90)
        self.cmp_offset.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmp_offset.valueChanged.connect(self._on_compare_offset)
        lay.addWidget(row("Start offset (frames)", self.cmp_offset))
        b = QPushButton("Use Current Clip as B")
        b.clicked.connect(self._compare_current)
        lay.addWidget(b)
        lay.addWidget(section("Wipe"))
        self.wipe_seg = Segmented(["Vertical", "Horizontal"], height=24)
        self.wipe_seg.changed.connect(self._on_wipe_dir)
        lay.addWidget(self.wipe_seg)
        lay.addWidget(section("Blend Opacity"))
        self.blend_slider = QSlider(Qt.Orientation.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(50)
        self.blend_slider.valueChanged.connect(self._on_blend)
        lay.addWidget(self.blend_slider)
        tip = QLabel("Drag the divider in the viewer to wipe between A and B. Difference mode highlights every "
                     "pixel that changed between versions.", objectName="Tertiary")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return page

    def _page_draw(self):
        page, lay = self._page()
        lay.addWidget(section("Tools"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons = {}
        tools = [("pointer", None, "Navigate (V)"), ("pen", "pen", "Pen (P)"), ("line", "line", "Line"),
                 ("arrow", "arrow", "Arrow (A)"), ("rect", "rect", "Rectangle (R)"),
                 ("ellipse", "ellipse", "Ellipse (E)"), ("text", "text", "Text (T)"),
                 ("eraser", "eraser", "Eraser (X)")]
        for i, (ic, tool, tip) in enumerate(tools):
            b = icon_button(ic, tip, checkable=True, accent_when_checked=True, box=34)
            b.clicked.connect(lambda _=False, t=tool: self.set_tool(t))
            self.tool_group.addButton(b)
            self.tool_buttons[tool] = b
            grid.addWidget(b, i // 4, i % 4)
        self.tool_buttons[None].setChecked(True)
        lay.addLayout(grid)
        lay.addWidget(section("Colour"))
        sw = QGridLayout()
        sw.setSpacing(2)
        self.swatches = []
        for i, (name, col) in enumerate(SYSTEM_COLORS.items()):
            s = Swatch(col)
            s.setToolTip(name)
            s.clicked.connect(self.set_color)
            self.swatches.append(s)
            sw.addWidget(s, i // 6, i % 6)
        lay.addLayout(sw)
        self.swatches[0].selected = True
        lay.addWidget(section("Size"))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 40)
        self.size_slider.setValue(4)
        self.size_slider.valueChanged.connect(lambda v: setattr(self.viewer, "brush", v))
        lay.addWidget(self.size_slider)
        self.sw_ghost = Switch(True)
        self.sw_ghost.toggled.connect(self._set_ghost_annotations)
        lay.addWidget(row("Ghost previous drawing", self.sw_ghost))
        hb = QHBoxLayout()
        for ic, tip, fn in (("undo", "Undo (Ctrl+Z)", self.undo), ("redo", "Redo (Ctrl+Y)", self.redo),
                            ("trash", "Clear Frame (Del)", self.clear_frame_annotations)):
            b = icon_button(ic, tip, box=32)
            b.clicked.connect(fn)
            hb.addWidget(b)
        hb.addStretch(1)
        lay.addLayout(hb)
        lay.addWidget(section("Export"))
        for text, fn in (("Save Snapshot…", self.save_snapshot), ("Copy Frame", self.copy_frame),
                         ("Export Annotated Frames…", self.export_annotations),
                         ("Clear All Annotations", self.clear_all_annotations)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lay.addWidget(b)
        tip = QLabel("Drawings are stored per source frame, so they stay with the shot even if you re-order "
                     "the timeline. Ctrl+←/→ jumps between annotated frames.", objectName="Tertiary")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return page

    def _page_view(self):
        page, lay = self._page()
        lay.addWidget(section("Background"))
        self.bg_seg = Segmented(["Dark", "Black", "Grey", "Checker"], height=24)
        self.bg_seg.changed.connect(lambda i: self._set_bg(["dark", "black", "grey", "checker"][i]))
        lay.addWidget(self.bg_seg)
        lay.addWidget(section("Guides"))
        self.guide_switches = {}
        for key, label in (("safe", "Safe areas"), ("thirds", "Rule of thirds"), ("center", "Centre cross")):
            s = Switch(False)
            s.toggled.connect(lambda v, k=key: self.set_guide(k, v))
            self.guide_switches[key] = s
            lay.addWidget(row(label, s))
        self.mask_combo = QComboBox()
        for name, _ in MASKS:
            self.mask_combo.addItem(name)
        self.mask_combo.currentIndexChanged.connect(self._on_mask)
        lay.addWidget(row("Aspect mask", self.mask_combo))
        lay.addWidget(section("Onion Skin"))
        self.sw_onion = Switch(False)
        self.sw_onion.toggled.connect(lambda v: self.btn_onion.setChecked(v))
        lay.addWidget(row("Enabled", self.sw_onion))
        self.onion_b = QSpinBox()
        self.onion_b.setRange(0, 5)
        self.onion_b.setValue(2)
        self.onion_b.setFixedWidth(60)
        self.onion_b.valueChanged.connect(lambda v: (setattr(self, "onion_before", v), self.render_frame()))
        lay.addWidget(row("Frames before", self.onion_b))
        self.onion_a = QSpinBox()
        self.onion_a.setRange(0, 5)
        self.onion_a.setFixedWidth(60)
        self.onion_a.valueChanged.connect(lambda v: (setattr(self, "onion_after", v), self.render_frame()))
        lay.addWidget(row("Frames after", self.onion_a))
        self.onion_op = QSlider(Qt.Orientation.Horizontal)
        self.onion_op.setRange(5, 80)
        self.onion_op.setValue(30)
        self.onion_op.valueChanged.connect(lambda v: (setattr(self, "onion_opacity", v / 100), self.render_frame()))
        lay.addWidget(self.onion_op)
        lay.addWidget(section("Display"))
        self.sw_hud = Switch(True)
        self.sw_hud.toggled.connect(lambda v: (setattr(self.viewer, "hud", v), self.viewer.update()))
        lay.addWidget(row("Frame overlay", self.sw_hud))
        self.sw_tc = Switch(False)
        self.sw_tc.toggled.connect(self._set_tc_mode)
        lay.addWidget(row("Show timecode", self.sw_tc))
        self.base_seg = Segmented(["0", "1"], height=24)
        self.base_seg.setFixedWidth(80)
        self.base_seg.set_index(self.base, animate=False)
        self.base_seg.changed.connect(self._set_base)
        lay.addWidget(row("First frame", self.base_seg))
        self.sw_ascrub = Switch(self.audio_scrub)
        self.sw_ascrub.toggled.connect(self._set_audio_scrub)
        lay.addWidget(row("Audio scrubbing", self.sw_ascrub))
        lay.addWidget(section("App"))
        self.appear_seg = Segmented(["Dark", "Light"], height=24)
        self.appear_seg.setFixedWidth(130)
        self.appear_seg.set_index(1 if T["name"] == "light" else 0, animate=False)
        self.appear_seg.changed.connect(lambda i: self.set_appearance("light" if i else "dark"))
        lay.addWidget(row("Appearance", self.appear_seg))
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(256, 65536)
        self.cache_spin.setSingleStep(512)
        self.cache_spin.setSuffix(" MB")
        self.cache_spin.setFixedWidth(100)
        self.cache_spin.setValue(int(self.settings.value("cache_mb", 3072)))
        self.cache_spin.valueChanged.connect(self._set_cache)
        lay.addWidget(row("RAM cache", self.cache_spin))
        self.sw_top = Switch(self.settings.value("on_top", "false") == "true")
        self.sw_top.toggled.connect(self._set_on_top)
        lay.addWidget(row("Always on top", self.sw_top))
        self.sw_remote = Switch(self.settings.value("remote", "false") == "true")
        self.sw_remote.toggled.connect(self._set_remote)
        lay.addWidget(row(f"Remote API (port {PORT})", self.sw_remote))
        lay.addStretch(1)
        return page

    def _build_transport(self):
        w = QWidget(objectName="Transport")
        w.setFixedHeight(58)
        h = QHBoxLayout(w)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(2)
        cnt = QVBoxLayout()
        cnt.setSpacing(0)
        self.counter = QLineEdit("0")
        self.counter.setFont(theme.font(20, QFont.Weight.DemiBold, mono=True))
        self.counter.setFixedWidth(150)
        self.counter.setToolTip("Type a frame number or timecode and press Enter")
        self.counter.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; padding: 0; font-family: '{theme.mono_family()}';"
            f" font-size: {theme.pt(17)}; font-weight: 600; }} QLineEdit:focus {{ border: none; padding: 0; }}")
        self.counter.returnPressed.connect(self._goto_typed)
        self.counter_sub = QLabel("", objectName="Tertiary")
        self.counter_sub.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {theme.pt(8)};")
        cnt.addWidget(self.counter)
        cnt.addWidget(self.counter_sub)
        h.addLayout(cnt)
        h.addStretch(1)
        self.btn_start = icon_button("to_start", "Go to Start (Home)", size=17, box=34)
        self.btn_back = icon_button("step_back", "Previous Frame (←)", size=17, box=34)
        self.btn_rev = icon_button("reverse", "Play Backwards (J)", size=17, box=34)
        self.btn_play = icon_button("play", "Play / Pause (Space)", size=22, box=44)
        self.btn_fwd = icon_button("step_fwd", "Next Frame (→)", size=17, box=34)
        self.btn_end = icon_button("to_end", "Go to End (End)", size=17, box=34)
        self.btn_start.clicked.connect(self.go_start)
        self.btn_back.clicked.connect(lambda: self.step(-1))
        self.btn_rev.clicked.connect(lambda: self.toggle_play(-1))
        self.btn_play.clicked.connect(lambda: self.toggle_play(1))
        self.btn_fwd.clicked.connect(lambda: self.step(1))
        self.btn_end.clicked.connect(self.go_end)
        for b in (self.btn_start, self.btn_back, self.btn_rev, self.btn_play, self.btn_fwd, self.btn_end):
            h.addWidget(b)
        h.addStretch(1)
        self.lbl_pixel = QLabel("", objectName="Tertiary")
        self.lbl_pixel.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {theme.pt(8)};")
        h.addWidget(self.lbl_pixel)
        h.addSpacing(10)
        self.lbl_fps = QLabel("", objectName="Tertiary")
        self.lbl_fps.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {theme.pt(8)};")
        self.lbl_fps.setFixedWidth(80)
        h.addWidget(self.lbl_fps)
        self.btn_in = icon_button("in_point", "Set In Point (I)", size=17)
        self.btn_out = icon_button("out_point", "Set Out Point (O)", size=17)
        self.btn_in.clicked.connect(self.set_in)
        self.btn_out.clicked.connect(self.set_out)
        h.addWidget(self.btn_in)
        h.addWidget(self.btn_out)
        self.btn_loop = icon_button(self.loop_mode if self.loop_mode != "loop" else "loop", "Loop Mode", size=17)
        self.btn_loop.clicked.connect(self.cycle_loop)
        h.addWidget(self.btn_loop)
        self.speed_combo = QComboBox()
        for s in SPEEDS:
            self.speed_combo.addItem(f"{s:g}×")
        self.speed_combo.setCurrentIndex(SPEEDS.index(1.0))
        self.speed_combo.setFixedWidth(68)
        self.speed_combo.setToolTip("Playback speed")
        self.speed_combo.currentIndexChanged.connect(lambda i: self.set_speed(SPEEDS[i]))
        h.addWidget(self.speed_combo)
        h.addSpacing(6)
        self.btn_vol = icon_button("volume", "Mute", size=17, checkable=False)
        self.btn_vol.clicked.connect(self.toggle_mute)
        h.addWidget(self.btn_vol)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(self.audio.volume * 100))
        self.vol.setFixedWidth(90)
        self.vol.valueChanged.connect(self._on_volume)
        h.addWidget(self.vol)
        return w

    def _build_menu(self):
        m = QMenu(self)
        self.more_menu = m
        fm = m.addMenu("File")
        self._act(fm, "Import Media…", "Ctrl+O", self.import_dialog)
        self._act(fm, "Import Folder…", "Ctrl+Shift+I", self.import_folder_dialog)
        self.recent_menu = fm.addMenu("Open Recent")
        fm.addSeparator()
        self._act(fm, "New Session", "Ctrl+N", self.new_session)
        self._act(fm, "Open Session…", "Ctrl+Shift+O", self.open_session_dialog)
        self._act(fm, "Save Session", "Ctrl+S", self.save_session)
        self._act(fm, "Save Session As…", "Ctrl+Shift+S", lambda: self.save_session(as_new=True))
        fm.addSeparator()
        self._act(fm, "Save Snapshot…", "Ctrl+E", self.save_snapshot)
        self._act(fm, "Copy Frame", "Ctrl+Shift+C", self.copy_frame)
        self._act(fm, "Export Annotated Frames…", None, self.export_annotations)
        em = m.addMenu("Edit")
        self._act(em, "Undo", "Ctrl+Z", self.undo)
        self._act(em, "Redo", "Ctrl+Y", self.redo)
        em.addSeparator()
        self._act(em, "Clear Frame Annotations", "Delete", self.clear_frame_annotations)
        self._act(em, "Clear All Annotations", None, self.clear_all_annotations)
        self._act(em, "Remove Current Clip", "Ctrl+Backspace", lambda: self.remove_clip(
            self.project.clip_index_at(self.frame)))
        pm = m.addMenu("Playback")
        self._act(pm, "Play / Pause", "Space", lambda: self.toggle_play(1))
        self._act(pm, "Play Backwards", "J", self.key_j)
        self._act(pm, "Stop", "K", self.pause)
        self._act(pm, "Play Forwards / Faster", "L", self.key_l)
        pm.addSeparator()
        self._act(pm, "Next Frame", "Right", lambda: self.step(1))
        self._act(pm, "Previous Frame", "Left", lambda: self.step(-1))
        self._act(pm, "Next Clip", "Down", lambda: self.jump_clip(1))
        self._act(pm, "Previous Clip", "Up", lambda: self.jump_clip(-1))
        self._act(pm, "Next Marker", "Shift+Right", lambda: self.jump_marker(1))
        self._act(pm, "Previous Marker", "Shift+Left", lambda: self.jump_marker(-1))
        self._act(pm, "Next Annotated Frame", "Ctrl+Right", lambda: self.jump_annotation(1))
        self._act(pm, "Previous Annotated Frame", "Ctrl+Left", lambda: self.jump_annotation(-1))
        self._act(pm, "Go to Start", "Home", self.go_start)
        self._act(pm, "Go to End", "End", self.go_end)
        pm.addSeparator()
        self._act(pm, "Set In Point", "I", self.set_in)
        self._act(pm, "Set Out Point", "O", self.set_out)
        self._act(pm, "Clear In/Out", "Alt+X", self.clear_range)
        self._act(pm, "Cycle Loop Mode", "Ctrl+L", self.cycle_loop)
        self._act(pm, "Toggle Marker", "M", self.toggle_marker)
        self._act(pm, "Edit Marker Note", "Shift+M", lambda: self.edit_marker(self.frame))
        vm = m.addMenu("View")
        self._act(vm, "Fit to Window", "F", self.viewer.fit_view)
        self._act(vm, "Actual Size (100%)", "1", self.viewer.actual_size)
        self._act(vm, "Zoom In", "=", lambda: self.viewer.set_zoom(self.viewer.scale() * 1.25))
        self._act(vm, "Zoom Out", "-", lambda: self.viewer.set_zoom(self.viewer.scale() / 1.25))
        vm.addSeparator()
        self._act(vm, "Toggle Compare", "C", self._toggle_compare_key)
        self._act(vm, "Toggle Annotate", "D", self._toggle_draw_key)
        self._act(vm, "Toggle Onion Skin", "Alt+O", lambda: self.btn_onion.toggle())
        self._act(vm, "Show/Hide Library", "Ctrl+1", lambda: self.btn_sidebar.toggle())
        self._act(vm, "Show/Hide Inspector", "Ctrl+2", lambda: self.btn_inspector.toggle())
        self._act(vm, "Hide Panels", "Tab", self.toggle_panels)
        self._act(vm, "Presentation Mode", "F11", self.toggle_presentation)
        m.addSeparator()
        self._act(m, "Set as Default Video Player…", None, self.make_default_player)
        self._act(m, "Keyboard Shortcuts", "F1", self.show_shortcuts)
        self._act(m, f"About {APP}", None, self.show_about)
        self.btn_more.clicked.connect(lambda: m.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 4))))
        self._refresh_recent()

        # tool shortcuts (only active in draw mode)
        for key, tool in (("V", None), ("P", "pen"), ("A", "arrow"), ("R", "rect"), ("E", "ellipse"),
                          ("T", "text"), ("X", "eraser")):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda t=tool: self.set_tool(t) if self.btn_draw.isChecked() else None)

    def _act(self, menu, text, shortcut, fn):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(lambda _=False: fn())
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_shortcuts(self):
        sc = QShortcut(QKeySequence("Escape"), self)
        sc.activated.connect(self._escape)
        sc = QShortcut(QKeySequence("Ctrl+F"), self)
        sc.activated.connect(self.toggle_presentation)

    # ================================================================== theme
    def apply_theme(self):
        QApplication.instance().setStyleSheet(theme.stylesheet())
        refresh_all_icons()
        self._set_dark_titlebar()
        for w in self.findChildren(QWidget):
            w.update()

    def set_appearance(self, name):
        theme.set_theme(name)
        self.settings.setValue("appearance", name)
        self.apply_theme()

    def _set_dark_titlebar(self):
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
        self._set_dark_titlebar()

    # ================================================================== media
    def import_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT | IMAGE_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "Import Media", self.settings.value("last_dir", ""),
                                                f"Media ({exts});;Sessions (*{SESSION_EXT});;All files (*)")
        if files:
            self.settings.setValue("last_dir", os.path.dirname(files[0]))
            self.open_paths(files)

    def import_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Import Folder", self.settings.value("last_dir", ""))
        if d:
            self.settings.setValue("last_dir", d)
            self.open_paths([d])

    def open_paths(self, paths, add_to_timeline=True, replace=False):
        sessions = [p for p in paths if p.lower().endswith(SESSION_EXT)]
        if sessions:
            self.load_session(sessions[0])
            return
        if replace:
            self.project.clips.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            new = make_sources(paths)
        finally:
            QApplication.restoreOverrideCursor()
        first_global = self.project.total()
        for s in new:
            self._add_source(s)
            if add_to_timeline:
                self.project.clips.append(Clip(s))
        for p in paths:
            self._add_recent(p)
        if new and add_to_timeline:
            self.in_pt, self.out_pt = 0, -1
            self.set_frame(first_global if not replace else 0)
        bad = [s.name for s in new if s.error]
        if bad:
            QMessageBox.warning(self, APP, "Some files could not be opened:\n\n" + "\n".join(bad[:10]))
        self.refresh_all()
        return new

    def _add_source(self, s):
        self.project.sources.append(s)
        s.frameReady.connect(self._on_frame_ready)
        s.infoChanged.connect(self._on_source_info)
        if self.proxy != 1.0:
            s.set_proxy(self.proxy)
        it = QListWidgetItem()
        it.setData(Qt.ItemDataRole.UserRole, s)
        it.setToolTip(s.path)
        self.library.addItem(it)

    def _find_source(self, path):
        path = os.path.abspath(path)
        for s in self.project.sources:
            if s.path == path:
                return s
        return None

    def _on_source_info(self, src):
        self.library.viewport().update()
        self.timeline.update()
        self.refresh_info()
        self.render_frame()

    def _filter_library(self, text):
        t = text.lower().strip()
        for i in range(self.library.count()):
            it = self.library.item(i)
            s = it.data(Qt.ItemDataRole.UserRole)
            it.setHidden(bool(t) and t not in s.name.lower())

    def _library_activate(self, it):
        s = it.data(Qt.ItemDataRole.UserRole)
        start = self.project.total()
        self.project.clips.append(Clip(s))
        self.refresh_all()
        self.set_frame(start)

    def _library_menu(self, pos):
        it = self.library.itemAt(pos)
        if not it:
            return
        s = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Add to Timeline", lambda: self._library_activate(it))
        m.addAction("Insert at Playhead", lambda: self._insert_clip(s))
        m.addAction("Compare Against Current (B)", lambda: self.set_compare_source(s, mode="wipe"))
        m.addSeparator()
        m.addAction("Show in Explorer", lambda: self._reveal(s.path))
        m.addAction("Remove from Library", lambda: self.remove_source(s))
        m.exec(self.library.mapToGlobal(pos))

    def _insert_clip(self, s):
        if not self.project.clips:
            self.project.clips.append(Clip(s))
            self.refresh_all()
            self.set_frame(0)
            return
        i = self.project.clip_index_at(self.frame)
        self.project.clips.insert(i + 1, Clip(s))
        self.refresh_all()
        self.set_frame(self.project.starts()[i + 1])

    def _reveal(self, path):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def remove_source(self, s):
        self.project.clips = [c for c in self.project.clips if c.source is not s]
        self.project.sources.remove(s)
        if self.compare_source is s:
            self.compare_source = None
        for i in range(self.library.count()):
            if self.library.item(i).data(Qt.ItemDataRole.UserRole) is s:
                self.library.takeItem(i)
                break
        s.close()
        self.refresh_all()
        self.set_frame(min(self.frame, max(0, self.project.total() - 1)))

    def remove_clip(self, i):
        if 0 <= i < len(self.project.clips):
            self.project.clips.pop(i)
            self.refresh_all()
            self.set_frame(min(self.frame, max(0, self.project.total() - 1)))

    def _clip_menu(self, i, gpos):
        c = self.project.clips[i]
        m = QMenu(self)
        m.addAction("Set Play Range to Clip", lambda: self._range_to_clip(i))
        m.addAction("Move Left", lambda: self._on_clip_moved(i, i - 1)).setEnabled(i > 0)
        m.addAction("Move Right", lambda: self._on_clip_moved(i, i + 1)).setEnabled(i < len(self.project.clips) - 1)
        m.addAction("Compare Against This Clip (B)", lambda: self.set_compare_source(c.source, mode="wipe"))
        if c.source.kind == "image":
            m.addAction("Set Hold Duration…", lambda: self._set_hold(c))
        m.addSeparator()
        m.addAction("Show in Explorer", lambda: self._reveal(c.source.path))
        m.addAction("Remove from Timeline", lambda: self.remove_clip(i))
        m.exec(gpos)

    def _set_hold(self, c):
        n, ok = QInputDialog.getInt(self, "Hold Duration", "Frames:", c.length, 1, 100000)
        if ok:
            c.length = n
            self.refresh_all()

    def _timeline_menu(self, gpos):
        m = QMenu(self)
        m.addAction("Import Media…", self.import_dialog)
        m.addAction("Clear In/Out", self.clear_range)
        m.exec(gpos)

    def _range_to_clip(self, i):
        s = self.project.starts()[i]
        self.in_pt, self.out_pt = s, s + self.project.clips[i].length - 1
        self._sync_range()

    def _on_clip_moved(self, src, dst):
        clips = self.project.clips
        if not (0 <= src < len(clips)) or not (0 <= dst < len(clips)):
            return
        current = self.project.locate(self.frame)
        c = clips.pop(src)
        clips.insert(dst, c)
        self.refresh_all()
        if current[0] is not None:
            idx = clips.index(current[0])
            self.set_frame(self.project.starts()[idx] + current[1])

    # ================================================================== frame display
    def _range(self):
        total = self.project.total()
        lo = max(0, min(self.in_pt, total - 1))
        hi = total - 1 if self.out_pt < 0 else max(lo, min(self.out_pt, total - 1))
        return lo, hi

    def set_frame(self, g, scrub=False):
        total = self.project.total()
        if total <= 0:
            self.frame = 0
            self.render_frame()
            return
        g = max(0, min(total - 1, int(g)))
        changed = g != self.frame
        self.frame = g
        self.render_frame()
        if scrub and changed and not self.playing and self.audio_scrub:
            self._scrub_audio()

    def render_frame(self):
        v = self.viewer
        clip, off, cs = self.project.locate(self.frame)
        if clip is None:
            v.img_a = None
            v.img_b = None
            v.empty = True
            v.strokes = []
            v.ghost_strokes = []
            v.ghosts = []
            v.update()
            self._update_transport()
            return
        v.empty = False
        src = clip.source
        lf = clip.local(off)
        ahead = 72 if self.playing else 16
        d = self.direction if self.playing else 1
        src.request(lf, d, ahead)
        img = src.get(lf)
        if img is not None:
            v.img_a = img
            self._last_drawn = (src.id, lf)
        elif self._last_drawn is None or self._last_drawn[0] != src.id:
            # keep previous picture until the new one decodes (avoids flashing)
            pass
        v.size_a = QSize(src.width or 1920, src.height or 1080)
        v.label_a = src.name
        # prefetch next clip when nearing the cut
        if self.playing:
            i = self.project.clips.index(clip)
            if d > 0 and clip.length - off < 30 and i + 1 < len(self.project.clips):
                nc = self.project.clips[i + 1]
                if nc.source is not src:
                    nc.source.request(nc.start, 1, 24)
            elif d > 0 and clip.length - off < 30 and self.loop_mode == "loop":
                lo, _ = self._range()
                c0, o0, _ = self.project.locate(lo)
                if c0 is not None and c0.source is not src:
                    c0.source.request(c0.local(o0), 1, 24)
        # B
        if self.compare_source is not None and self.cmp_seg.index > 0:
            b = self.compare_source
            bf = b.clamp(self.frame - self.compare_offset) if b.kind != "image" else 0
            b.request(bf, d, ahead)
            bi = b.get(bf)
            if bi is not None:
                v.img_b = bi
            v.size_b = QSize(b.width or 1920, b.height or 1080)
            v.label_b = b.name
        else:
            v.img_b = None
        # onion skin
        ghosts = []
        if self.onion_on and src.kind != "image":
            for k in list(range(1, self.onion_before + 1)) + [-k for k in range(1, self.onion_after + 1)]:
                f = lf - k
                if 0 <= f < src.frames:
                    gi = src.get(f)
                    if gi is not None:
                        ghosts.append((gi, self.onion_opacity / abs(k)))
            if not self.playing and self.onion_before:
                # one window covering the ghosts before, the current frame and the ones after
                src.request(max(0, lf - self.onion_before), 1, self.onion_before + self.onion_after + 16)
        v.ghosts = ghosts
        # annotations
        v.strokes = self.project.strokes(src, lf)
        v.ghost_strokes = []
        if self.ghost_annotations and not v.strokes:
            prefix = src.path + "|"
            best = None
            for k in self.project.annotations:
                if k.startswith(prefix):
                    f = int(k[len(prefix):])
                    if f < lf and (best is None or f > best) and lf - f <= 48:
                        best = f
            if best is not None:
                v.ghost_strokes = self.project.strokes(src, best)
        src_no = (src.first_number + lf) if src.kind == "sequence" else lf + self.base
        v.hud_text = f"{self.frame + self.base}   ·   {timecode(self.frame, self.project.fps)}"
        v.update()
        self._src_frame_text = f"{src_no}"
        self._update_transport()

    def _on_frame_ready(self, src, idx):
        self._cache_dirty = True
        clip, off, _ = self.project.locate(self.frame)
        if clip is None:
            return
        need = clip.source is src and clip.local(off) == idx
        if self.compare_source is src:
            need = True
        if self.onion_on and clip.source is src:
            need = True
        if need and not self.playing:
            self.render_frame()
        elif need and self.playing:
            # playback tick will pick it up; but repaint if we were showing a stale frame
            img = src.get(idx)
            if img is not None and clip.source is src and clip.local(off) == idx:
                self.viewer.img_a = img
                self.viewer.update()

    def _update_transport(self):
        total = self.project.total()
        if not self.counter.hasFocus():
            if self.tc_mode:
                self.counter.setText(timecode(self.frame, self.project.fps))
            else:
                self.counter.setText(str(self.frame + self.base) if total else "—")
        clip, off, cs = self.project.locate(self.frame)
        if clip:
            idx = self.project.clips.index(clip) + 1
            other = str(self.frame + self.base) if self.tc_mode else timecode(self.frame, self.project.fps)
            self.counter_sub.setText(f"{other}  ·  {total}f  ·  clip {idx}/{len(self.project.clips)}")
            self.lbl_title.setText(clip.source.name)
            s = clip.source
            self.lbl_sub.setText(f"{s.width}×{s.height}  ·  {self.project.fps:g} fps  ·  {s.codec}"
                                 if not s.error else "Unsupported file")
            self.info_fields["Source Frame"].setText(getattr(self, "_src_frame_text", ""))
            if getattr(self, "_info_src", None) is not s:
                self.refresh_info()
        else:
            self.counter_sub.setText("")
            self.lbl_title.setText(APP)
            self.lbl_sub.setText("No media")
        self.timeline.frame = self.frame
        if self.playing:
            self.timeline.ensure_visible(self.frame)
        self.timeline.update()
        self.setWindowTitle(f"{clip.source.name} — {APP}" if clip else APP)

    def _ui_refresh(self):
        if self._cache_dirty:
            self._cache_dirty = False
            cached = set()
            s = 0
            for c in self.project.clips:
                fr = c.source.cached_frames()
                if c.source.kind == "image":
                    if 0 in fr:
                        cached.update(range(s, s + c.length))
                else:
                    lo, hi = c.start, c.start + c.length
                    cached.update(s + f - c.start for f in fr if lo <= f < hi)
                s += c.length
            self.timeline.cached = cached
            self.timeline.update()
            self.lbl_cache.setText(f"RAM cache  {human_size(CACHE.used)} / {human_size(CACHE.budget)}")
        if self.playing and len(self._fps_frames) > 2:
            span = self._fps_frames[-1] - self._fps_frames[0]
            if span > 0:
                self.lbl_fps.setText(f"{(len(self._fps_frames) - 1) / span:5.1f} fps")
        elif not self.playing:
            self.lbl_fps.setText("")

    def refresh_all(self):
        self.timeline.annotated = self.project.annotated_globals()
        self.timeline.in_pt, self.timeline.out_pt = self._range() if self.project.total() else (0, 0)
        self.lib_empty.setVisible(self.library.count() == 0)
        self._refresh_compare_combo()
        self._refresh_markers()
        self._update_b_track()
        self._cache_dirty = True
        self.refresh_info()
        self.render_frame()
        self.timeline.update()

    def refresh_info(self):
        clip, off, _ = self.project.locate(self.frame)
        f = self.info_fields
        if clip is None:
            self.info_name.setText("No clip")
            self.info_path.setText("")
            for k in f:
                f[k].setText("—")
            self._info_src = None
            return
        s = clip.source
        self._info_src = s
        self.info_name.setText(s.name)
        self.info_path.setText(os.path.dirname(s.path).replace(os.sep, os.sep + ZWSP).replace("/", "/" + ZWSP))
        f["Resolution"].setText(f"{s.width} × {s.height}")
        f["Frame Rate"].setText(f"{s.native_fps:.3f}".rstrip("0").rstrip(".") + " fps")
        f["Duration"].setText(f"{s.frames}f  ·  {timecode(s.frames, s.fps)}" if s.kind != "image" else "Still")
        f["Codec"].setText(s.codec or "—")
        f["Pixel Format"].setText(s.pix_fmt or "—")
        f["File Size"].setText(human_size(s.file_size) if s.file_size else "—")
        f["Audio"].setText("Stereo 48 kHz" if s.audio is not None else ("Loading…" if s.has_audio else "None"))

    # ================================================================== playback
    def toggle_play(self, direction=1):
        if self.playing and self.direction == direction:
            self.pause()
        else:
            self.play(direction)

    def play(self, direction=1):
        if self.project.total() <= 0:
            return
        lo, hi = self._range()
        if self.loop_mode == "once":
            if direction > 0 and self.frame >= hi:
                self.frame = lo
            elif direction < 0 and self.frame <= lo:
                self.frame = hi
        if not (lo <= self.frame <= hi):
            self.frame = lo if direction > 0 else hi
        self.playing = True
        self.direction = direction
        self._anchor(self.frame)
        self._fps_frames = []
        self._audio_key = None
        self.play_timer.start()
        refresh_icon(self.btn_play, "pause" if direction > 0 else "play")
        refresh_icon(self.btn_rev, "pause" if direction < 0 else "reverse")
        self.render_frame()
        self._sync_audio(force=True)

    def pause(self):
        if not self.playing:
            return
        self.playing = False
        self.play_timer.stop()
        self.audio.stop()
        self.speed_combo.blockSignals(True)
        refresh_icon(self.btn_play, "play")
        refresh_icon(self.btn_rev, "reverse")
        self.speed_combo.blockSignals(False)
        self.render_frame()

    def _anchor(self, f):
        self.anchor_frame = f
        self.anchor_t = self.clock.nsecsElapsed() / 1e9

    def _tick(self):
        now = self.clock.nsecsElapsed() / 1e9
        fps = self.project.fps * self.speed
        lo, hi = self._range()
        if self.every_frame:
            due = self.anchor_frame + self.direction * (now - self.anchor_t) * fps
            if (self.direction > 0 and due < self.frame + 1) or (self.direction < 0 and due > self.frame - 1):
                return
            nxt = self.frame + self.direction
            clip, off, _ = self.project.locate(max(lo, min(hi, nxt)))
            if clip is not None and clip.source.get(clip.local(off)) is None:
                self._anchor(self.frame)  # wait for decoder
                return
            tf = nxt
            self._anchor(nxt)
        else:
            t = self.anchor_frame + self.direction * (now - self.anchor_t) * fps
            tf = int(math.floor(t + 1e-6)) if self.direction > 0 else int(math.ceil(t - 1e-6))
        span = hi - lo + 1
        if tf > hi:
            if self.loop_mode == "loop":
                tf = lo + (tf - hi - 1) % span
                self._anchor(tf)
                self._audio_key = None
            elif self.loop_mode == "pingpong":
                self.direction = -1
                tf = max(lo, hi - (tf - hi))
                self._anchor(tf)
                self._audio_key = None
                refresh_icon(self.btn_play, "play")
                refresh_icon(self.btn_rev, "pause")
            else:
                self.frame = hi
                self.pause()
                return
        elif tf < lo:
            if self.loop_mode == "loop":
                tf = hi - (lo - tf - 1) % span
                self._anchor(tf)
                self._audio_key = None
            elif self.loop_mode == "pingpong":
                self.direction = 1
                tf = min(hi, lo + (lo - tf))
                self._anchor(tf)
                self._audio_key = None
                refresh_icon(self.btn_play, "pause")
                refresh_icon(self.btn_rev, "reverse")
            else:
                self.frame = lo
                self.pause()
                return
        if tf != self.frame:
            self.frame = tf
            self._fps_frames.append(now)
            if len(self._fps_frames) > 30:
                self._fps_frames.pop(0)
            self.render_frame()
            self._sync_audio()

    def _audio_pos(self, g):
        clip, off, _ = self.project.locate(g)
        if clip is None or clip.source.audio is None:
            return None, None, 1.0
        src = clip.source
        lf = clip.local(off)
        return src, lf / src.native_fps, self.project.fps * self.speed / src.native_fps

    def _sync_audio(self, force=False):
        if self.audio.muted or not self.audio.available:
            return
        src, secs, rate = self._audio_pos(self.frame)
        if src is None:
            if self._audio_key is not None:
                self.audio.stop()
                self._audio_key = None
            return
        rate *= self.direction
        key = (src.id, round(rate, 4))
        if force or key != self._audio_key or abs(self.audio.position() - secs) > 0.12:
            self.audio.play(src.audio, secs, rate)
            self._audio_key = key

    def _scrub_audio(self):
        if self.audio.muted:
            return
        src, secs, rate = self._audio_pos(self.frame)
        if src is not None:
            self.audio.scrub(src.audio, secs, 1.0 / max(1.0, self.project.fps) * 1.5, 1.0)

    def step(self, n):
        if self.playing:
            self.pause()
        total = self.project.total()
        if total <= 0:
            return
        lo, hi = self._range()
        f = self.frame + n
        if f > hi:
            f = lo if self.loop_mode != "once" else hi
        elif f < lo:
            f = hi if self.loop_mode != "once" else lo
        self.direction = 1 if n > 0 else -1
        self.set_frame(f, scrub=True)

    def go_start(self):
        self.pause()
        self.set_frame(self._range()[0])

    def go_end(self):
        self.pause()
        self.set_frame(self._range()[1])

    def key_j(self):
        if self.playing and self.direction < 0:
            self.set_speed(min(8.0, self.speed * 2))
        else:
            self.set_speed(1.0)
            self.play(-1)

    def key_l(self):
        if self.playing and self.direction > 0:
            self.set_speed(min(8.0, self.speed * 2))
        else:
            self.set_speed(1.0)
            self.play(1)

    def set_speed(self, s):
        if self.playing:
            self._anchor(self.frame)
        self.speed = s
        self.speed_combo.blockSignals(True)
        best = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - s))
        self.speed_combo.setCurrentIndex(best)
        self.speed_combo.blockSignals(False)
        self._audio_key = None
        if self.playing:
            self._sync_audio(force=True)

    def cycle_loop(self):
        order = ["loop", "pingpong", "once"]
        self.loop_mode = order[(order.index(self.loop_mode) + 1) % 3]
        refresh_icon(self.btn_loop, self.loop_mode)
        self.btn_loop.setToolTip({"loop": "Loop", "pingpong": "Ping-Pong", "once": "Play Once"}[self.loop_mode])
        self.settings.setValue("loop_mode", self.loop_mode)
        self.toast({"loop": "Loop", "pingpong": "Ping-Pong", "once": "Play Once"}[self.loop_mode])

    def toast(self, text):
        self.lbl_fps.setText(text)
        QTimer.singleShot(1200, lambda: self.lbl_fps.setText("") if not self.playing else None)

    def _on_scrub(self, f):
        self.set_frame(f, scrub=True)

    def _scrub_start(self):
        if self.playing:
            self.pause()

    def _goto_typed(self):
        txt = self.counter.text().strip()
        self.counter.clearFocus()
        try:
            if ":" in txt:
                parts = [int(x) for x in txt.split(":")]
                while len(parts) < 4:
                    parts.insert(0, 0)
                h, m, s, f = parts[-4:]
                fps = max(1, round(self.project.fps))
                g = ((h * 60 + m) * 60 + s) * fps + f
            else:
                g = int(txt) - self.base
            self.set_frame(g)
        except ValueError:
            self._update_transport()

    def jump_clip(self, d):
        starts = self.project.starts()
        if not starts:
            return
        i = self.project.clip_index_at(self.frame)
        if d < 0 and self.frame > starts[i]:
            self.set_frame(starts[i])
        else:
            self.set_frame(starts[max(0, min(len(starts) - 1, i + d))])

    def jump_marker(self, d):
        ms = sorted(self.project.markers)
        cand = [m for m in ms if (m > self.frame if d > 0 else m < self.frame)]
        if cand:
            self.set_frame(cand[0] if d > 0 else cand[-1])

    def jump_annotation(self, d):
        a = self.project.annotated_globals()
        cand = [m for m in a if (m > self.frame if d > 0 else m < self.frame)]
        if cand:
            self.set_frame(cand[0] if d > 0 else cand[-1])

    def toggle_mute(self):
        self.audio.muted = not self.audio.muted
        refresh_icon(self.btn_vol, "mute" if self.audio.muted else "volume")
        if not self.audio.muted and self.playing:
            self._sync_audio(force=True)

    def _on_volume(self, v):
        self.audio.volume = v / 100
        self.settings.setValue("volume", v / 100)

    # ---- range
    def set_in(self):
        if not self.project.total():
            return
        lo, hi = self._range()
        self.in_pt = self.frame
        if self.frame > hi:
            self.out_pt = -1
        self._sync_range()

    def set_out(self):
        if not self.project.total():
            return
        lo, hi = self._range()
        self.out_pt = self.frame
        if self.frame < lo:
            self.in_pt = 0
        self._sync_range()

    def clear_range(self):
        self.in_pt, self.out_pt = 0, -1
        self._sync_range()

    def _on_range(self, i, o):
        self.in_pt = i
        self.out_pt = o
        self._sync_range(update_timeline=False)

    def _sync_range(self, update_timeline=True):
        lo, hi = self._range()
        if update_timeline:
            self.timeline.in_pt, self.timeline.out_pt = lo, hi
        self.timeline.update()

    # ================================================================== compare
    def _refresh_compare_combo(self):
        self.cmp_combo.blockSignals(True)
        self.cmp_combo.clear()
        self.cmp_combo.addItem("— Choose a source —", None)
        sel = 0
        for i, s in enumerate(self.project.sources):
            self.cmp_combo.addItem(s.name, s)
            if s is self.compare_source:
                sel = i + 1
        self.cmp_combo.setCurrentIndex(sel)
        self.cmp_combo.blockSignals(False)

    def _on_compare_source(self, i):
        self.compare_source = self.cmp_combo.itemData(i)
        if self.compare_source and self.cmp_seg.index == 0:
            self.cmp_seg.set_index(1, emit=True)
        self._update_b_track()
        self.render_frame()

    def set_compare_source(self, s, mode=None):
        self.compare_source = s
        self._refresh_compare_combo()
        if mode:
            self.cmp_seg.set_index(["off", "wipe", "side", "stack", "overlay", "diff"].index(mode), emit=True)
        self.insp_seg.set_index(1, emit=True)
        self._update_b_track()
        self.render_frame()

    def _compare_current(self):
        clip, _, cs = self.project.locate(self.frame)
        if clip:
            self.compare_offset = cs
            self.cmp_offset.setValue(cs)
            self.set_compare_source(clip.source, mode="wipe" if self.cmp_seg.index == 0 else None)

    def _on_compare_mode(self, i):
        mode = ["off", "wipe", "side", "stack", "overlay", "diff"][i]
        self.viewer.compare = mode
        self.btn_compare.setChecked(i > 0)
        if i > 0 and self.compare_source is None:
            # pick a sensible default B: next source in the library
            clip, _, _ = self.project.locate(self.frame)
            others = [s for s in self.project.sources if clip is None or s is not clip.source]
            if others:
                self.compare_source = others[0]
                self._refresh_compare_combo()
        self._update_b_track()
        self.render_frame()

    def _update_b_track(self):
        if self.compare_source is not None and self.cmp_seg.index > 0:
            s = self.compare_source
            self.timeline.set_b_track((s.name, self.compare_offset, s.frames if s.kind != "image" else 24))
        else:
            self.timeline.set_b_track(None)

    def _on_compare_offset(self, v):
        self.compare_offset = v
        self._update_b_track()
        self.render_frame()

    def _on_wipe_dir(self, i):
        self.viewer.wipe_vertical = i == 0
        self.viewer.update()

    def _on_blend(self, v):
        self.viewer.overlay_opacity = v / 100
        self.viewer.update()

    def _toggle_compare(self):
        on = self.btn_compare.isChecked()
        self.cmp_seg.set_index(1 if on else 0, emit=True)
        if on:
            self.btn_inspector.setChecked(True)
            self.insp_seg.set_index(1, emit=True)

    def _toggle_compare_key(self):
        self.btn_compare.toggle()
        self._toggle_compare()

    # ================================================================== annotations
    def _toggle_draw(self):
        on = self.btn_draw.isChecked()
        if on:
            self.btn_inspector.setChecked(True)
            self.insp_seg.set_index(2, emit=True)
            if self.viewer.tool is None:
                self.set_tool("pen")
        else:
            self.set_tool(None)

    def _toggle_draw_key(self):
        self.btn_draw.toggle()
        self._toggle_draw()

    def set_tool(self, tool):
        if tool and self.playing:
            self.pause()
        self.viewer.tool = tool
        self.tool_buttons[tool].setChecked(True)
        self.btn_draw.setChecked(tool is not None)
        self.viewer.setCursor(Qt.CursorShape.CrossCursor if tool else Qt.CursorShape.ArrowCursor)

    def set_color(self, c):
        self.viewer.color = c
        for s in self.swatches:
            s.selected = s.color == c
            s.update()

    def _current_src_frame(self):
        clip, off, _ = self.project.locate(self.frame)
        if clip is None:
            return None, None
        return clip.source, clip.local(off)

    def _on_stroke(self, st):
        src, lf = self._current_src_frame()
        if src is None:
            return
        self.project.add_stroke(src, lf, st)
        self._annotations_changed()

    def _on_erase(self, x, y, r):
        src, lf = self._current_src_frame()
        if src is None:
            return
        strokes = self.project.strokes(src, lf)
        keep = []
        for st in strokes:
            pts = st["p"]
            hit = False
            if st["t"] in ("rect", "ellipse", "line", "arrow") and len(pts) >= 2:
                (x0, y0), (x1, y1) = pts[0], pts[-1]
                n = 24
                pts = [[x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n] for k in range(n + 1)]
                if st["t"] in ("rect", "ellipse"):
                    pts += [[x0, y0 + (y1 - y0) * k / n] for k in range(n + 1)]
                    pts += [[x1, y0 + (y1 - y0) * k / n] for k in range(n + 1)]
                    pts += [[x0 + (x1 - x0) * k / n, y0] for k in range(n + 1)]
                    pts += [[x0 + (x1 - x0) * k / n, y1] for k in range(n + 1)]
            elif st["t"] == "text":
                hit = abs(pts[0][0] - x) < st["w"] * 20 and -st["w"] * 7 < (pts[0][1] - y) < st["w"] * 2
            for px, py in pts:
                if (px - x) ** 2 + (py - y) ** 2 <= (r + st["w"] / 2) ** 2:
                    hit = True
                    break
            if not hit:
                keep.append(st)
        if len(keep) != len(strokes):
            self.project.set_strokes(src, lf, keep)
            self._annotations_changed()

    def _annotations_changed(self):
        self.timeline.annotated = self.project.annotated_globals()
        self.render_frame()

    def _set_ghost_annotations(self, v):
        self.ghost_annotations = v
        self.render_frame()

    def undo(self):
        if self.project.undo() is not None:
            self._annotations_changed()

    def redo(self):
        if self.project.redo() is not None:
            self._annotations_changed()

    def clear_frame_annotations(self):
        src, lf = self._current_src_frame()
        if src is not None and self.project.strokes(src, lf):
            self.project.set_strokes(src, lf, [])
            self._annotations_changed()

    def clear_all_annotations(self):
        if not self.project.annotations:
            return
        if QMessageBox.question(self, APP, "Remove every annotation in this session?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.project.annotations.clear()
        self.project.undo_stack.clear()
        self.project.redo_stack.clear()
        self._annotations_changed()

    # ================================================================== markers
    def toggle_marker(self):
        if not self.project.total():
            return
        if self.frame in self.project.markers:
            del self.project.markers[self.frame]
        else:
            self.project.markers[self.frame] = {"color": "#FF9F0A", "note": ""}
        self.project.dirty = True
        self._refresh_markers()
        self.timeline.update()

    def edit_marker(self, g):
        m = self.project.markers.get(g)
        if m is None:
            m = {"color": "#FF9F0A", "note": ""}
        txt, ok = QInputDialog.getText(self, "Marker", f"Note for frame {g + self.base}:", text=m.get("note", ""))
        if ok:
            m["note"] = txt
            self.project.markers[g] = m
            self.project.dirty = True
            self._refresh_markers()
            self.timeline.update()

    def _marker_menu(self, pos):
        it = self.marker_list.itemAt(pos)
        if not it:
            return
        g = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Edit Note…", lambda: self.edit_marker(g))
        cm = m.addMenu("Colour")
        for name in ("Red", "Orange", "Yellow", "Green", "Blue", "Purple"):
            cm.addAction(name, lambda c=SYSTEM_COLORS[name]: self._marker_color(g, c))
        m.addAction("Delete", lambda: (self.project.markers.pop(g, None), self._refresh_markers(),
                                       self.timeline.update()))
        m.exec(self.marker_list.mapToGlobal(pos))

    def _marker_color(self, g, c):
        if g in self.project.markers:
            self.project.markers[g]["color"] = c
            self._refresh_markers()
            self.timeline.update()

    def _refresh_markers(self):
        self.marker_list.clear()
        for g in sorted(self.project.markers):
            m = self.project.markers[g]
            it = QListWidgetItem(f"{g + self.base:>6}   {m.get('note') or 'Marker'}")
            pm = QPixmap(20, 20)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(m.get("color", "#FF9F0A")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(5, 5, 10, 10)
            p.end()
            it.setIcon(QIcon(pm))
            it.setData(Qt.ItemDataRole.UserRole, g)
            self.marker_list.addItem(it)

    # ================================================================== view settings
    def _set_onion(self, on):
        self.onion_on = on
        self.sw_onion.set_checked(on)
        self.render_frame()

    def _set_bg(self, mode):
        self.viewer.bg_mode = mode
        self.viewer.update()

    def set_guide(self, key, on):
        if on:
            self.viewer.guides.add(key)
        else:
            self.viewer.guides.discard(key)
        if self.guide_switches[key].checked != on:
            self.guide_switches[key].set_checked(on)
        self.viewer.update()

    def _on_mask(self, i):
        self.viewer.mask_aspect = MASKS[i][1]
        self.viewer.update()

    def _guides_menu(self):
        m = QMenu(self)
        for key, label in (("safe", "Safe Areas"), ("thirds", "Rule of Thirds"), ("center", "Centre Cross")):
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(key in self.viewer.guides)
            a.toggled.connect(lambda v, k=key: self.set_guide(k, v))
        m.addSeparator()
        mm = m.addMenu("Aspect Mask")
        for i, (name, _) in enumerate(MASKS):
            a = mm.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.mask_combo.currentIndex() == i)
            a.triggered.connect(lambda _=False, k=i: self.mask_combo.setCurrentIndex(k))
        bm = m.addMenu("Background")
        for i, name in enumerate(["Dark", "Black", "Grey", "Checker"]):
            a = bm.addAction(name)
            a.triggered.connect(lambda _=False, k=i: self.bg_seg.set_index(k, emit=True))
        m.exec(self.btn_guides.mapToGlobal(QPoint(0, self.btn_guides.height() + 4)))

    def _set_tc_mode(self, v):
        self.tc_mode = v
        self.timeline.tc_mode = v
        self._update_transport()

    def _set_base(self, i):
        self.base = i
        self.timeline_base_changed()
        self.settings.setValue("frame_base", i)

    def timeline_base_changed(self):
        self.timeline.base = self.base
        self._refresh_markers()
        self.render_frame()

    def _set_audio_scrub(self, v):
        self.audio_scrub = v
        self.settings.setValue("audio_scrub", "true" if v else "false")

    def _set_cache(self, v):
        CACHE.set_budget(v)
        self.settings.setValue("cache_mb", v)
        self._cache_dirty = True

    def _set_on_top(self, v):
        self.settings.setValue("on_top", "true" if v else "false")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, v)
        self.show()
        self._set_dark_titlebar()

    def _set_remote(self, v):
        self.settings.setValue("remote", "true" if v else "false")
        if v:
            if not self.remote.start():
                QMessageBox.warning(self, APP, f"Port {PORT} is already in use.")
                self.sw_remote.set_checked(False)
        else:
            self.remote.stop()

    def _on_fps_override(self, v):
        self.project.fps_override = v if v > 0 else None
        if self.playing:
            self._anchor(self.frame)
            self._audio_key = None
        self._update_transport()
        self.timeline.update()

    def _on_proxy(self, i):
        self.proxy = [1.0, 0.5, 0.25][i]
        for s in self.project.sources:
            s.set_proxy(self.proxy)
        self._cache_dirty = True
        self.render_frame()

    def _update_status(self):
        self.viewer.update()

    def toggle_panels(self):
        vis = self.sidebar.isVisible() or self.inspector.isVisible()
        self.btn_sidebar.setChecked(not vis)
        self.btn_inspector.setChecked(not vis)

    def toggle_presentation(self):
        self._presentation = not self._presentation
        p = self._presentation
        if p:
            self._pre_state = (self.sidebar.isVisible(), self.inspector.isVisible(), self.isMaximized())
            self.sidebar.hide()
            self.inspector.hide()
            self.toolbar.hide()
            self.showFullScreen()
        else:
            sb, ins, maxed = getattr(self, "_pre_state", (True, True, False))
            self.toolbar.show()
            self.sidebar.setVisible(sb)
            self.inspector.setVisible(ins)
            self.showMaximized() if maxed else self.showNormal()
        self.viewer.fit_view()

    def _escape(self):
        if self._presentation:
            self.toggle_presentation()
        elif self.viewer.tool:
            self.set_tool(None)

    # ================================================================== export
    def _composited_frame(self):
        img = self.viewer.render_frame(True)
        if img is None:
            return None
        src, lf = self._current_src_frame()
        if src is not None and (self.viewer.img_a is None or self.viewer.img_a.width() != src.width):
            full = decode_frame_sync(src, lf)
            if full is not None:
                out = QImage(full.size(), QImage.Format.Format_ARGB32_Premultiplied)
                p = QPainter(out)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.drawImage(0, 0, full)
                draw_strokes(p, self.project.strokes(src, lf))
                p.end()
                return out
        return img

    def save_snapshot(self):
        img = self._composited_frame()
        if img is None:
            return
        src, lf = self._current_src_frame()
        base = os.path.splitext(src.name.replace("#", ""))[0].rstrip("._")
        default = os.path.join(self.settings.value("snap_dir", os.path.expanduser("~/Pictures")),
                               f"{base}_f{lf + self.base:05d}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save Snapshot", default, "PNG (*.png);;JPEG (*.jpg)")
        if path:
            self.settings.setValue("snap_dir", os.path.dirname(path))
            img.save(path)
            self.toast("Saved")

    def copy_frame(self):
        img = self._composited_frame()
        if img is not None:
            QGuiApplication.clipboard().setImage(img)
            self.toast("Copied")

    def export_annotations(self):
        if not self.project.annotations:
            QMessageBox.information(self, APP, "There are no annotated frames to export.")
            return
        d = QFileDialog.getExistingDirectory(self, "Export Annotated Frames To",
                                             self.settings.value("snap_dir", os.path.expanduser("~/Pictures")))
        if not d:
            return
        keys = list(self.project.annotations.keys())
        dlg = QProgressDialog("Exporting annotated frames…", "Cancel", 0, len(keys), self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        n = 0
        for i, k in enumerate(keys):
            if dlg.wasCanceled():
                break
            dlg.setValue(i)
            QApplication.processEvents()
            path, lf = k.rsplit("|", 1)
            src = self._find_source(path)
            if src is None:
                continue
            lf = int(lf)
            img = decode_frame_sync(src, lf)
            if img is None:
                continue
            out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
            p = QPainter(out)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawImage(0, 0, img)
            draw_strokes(p, self.project.annotations[k])
            p.end()
            base = os.path.splitext(src.name.replace("#", ""))[0].rstrip("._")
            out.save(os.path.join(d, f"{base}_f{lf + self.base:05d}.png"))
            n += 1
        dlg.setValue(len(keys))
        self.toast(f"Exported {n}")
        QMessageBox.information(self, APP, f"Exported {n} annotated frame(s) to:\n{d}")

    # ================================================================== sessions
    def new_session(self):
        if not self._confirm_discard():
            return
        self.pause()
        for s in list(self.project.sources):
            s.close()
        self.library.clear()
        self.project = Project()
        self.timeline.project = self.project
        self.compare_source = None
        self.in_pt, self.out_pt, self.frame = 0, -1, 0
        self.fps_spin.setValue(0)
        self.refresh_all()

    def _confirm_discard(self):
        if not self.project.dirty or not (self.project.annotations or self.project.markers):
            return True
        r = QMessageBox.question(self, APP, "Save changes to annotations and markers in this session?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_session()
        return r == QMessageBox.StandardButton.Discard

    def session_dict(self):
        pr = self.project
        return {
            "app": APP, "version": 1,
            "sources": [s.to_dict() for s in pr.sources],
            "clips": [c.to_dict() for c in pr.clips],
            "markers": {str(k): v for k, v in pr.markers.items()},
            "annotations": pr.annotations,
            "fps_override": pr.fps_override,
            "in": self.in_pt, "out": self.out_pt, "frame": self.frame,
            "compare": {"path": self.compare_source.path if self.compare_source else None,
                        "mode": self.cmp_seg.index, "offset": self.compare_offset,
                        "wipe_vertical": self.viewer.wipe_vertical},
            "loop": self.loop_mode,
        }

    def save_session(self, as_new=False):
        path = self.project.path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save Session",
                                                  os.path.join(self.settings.value("last_dir", ""),
                                                               "Review" + SESSION_EXT),
                                                  f"{APP} Session (*{SESSION_EXT})")
            if not path:
                return False
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.session_dict(), f, indent=1)
        self.project.path = path
        self.project.dirty = False
        self._add_recent(path)
        self.toast("Session saved")
        return True

    def open_session_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Session", self.settings.value("last_dir", ""),
                                              f"{APP} Session (*{SESSION_EXT})")
        if path:
            self.load_session(path)

    def load_session(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, APP, f"Could not open session:\n{e}")
            return
        if not self._confirm_discard():
            return
        self.new_session_silent()
        missing = []
        for sd in d.get("sources", []):
            p = sd["path"]
            if not os.path.exists(p):
                missing.append(p)
                continue
            kind = sd.get("kind", "video")
            srcs = make_sources([p]) if kind != "sequence" else make_sources([p])
            for s in srcs:
                s.fps_override = sd.get("fps_override")
                self._add_source(s)
        for cd in d.get("clips", []):
            s = self._find_source(cd["path"])
            if s:
                self.project.clips.append(Clip(s, cd.get("start", 0), cd.get("length")))
        self.project.markers = {int(k): v for k, v in d.get("markers", {}).items()}
        self.project.annotations = d.get("annotations", {})
        self.project.fps_override = d.get("fps_override")
        self.fps_spin.setValue(self.project.fps_override or 0)
        self.in_pt, self.out_pt = d.get("in", 0), d.get("out", -1)
        cmp = d.get("compare") or {}
        if cmp.get("path"):
            self.compare_source = self._find_source(cmp["path"])
            self.compare_offset = cmp.get("offset", 0)
            self.cmp_offset.setValue(self.compare_offset)
            self.viewer.wipe_vertical = cmp.get("wipe_vertical", True)
            self.wipe_seg.set_index(0 if self.viewer.wipe_vertical else 1, animate=False)
        self.loop_mode = d.get("loop", "loop")
        refresh_icon(self.btn_loop, self.loop_mode)
        self.project.path = path
        self.project.dirty = False
        self._add_recent(path)
        self.refresh_all()
        if cmp.get("mode"):
            self.cmp_seg.set_index(cmp["mode"], emit=True)
        self.set_frame(d.get("frame", 0))
        if missing:
            QMessageBox.warning(self, APP, "These files could not be found:\n\n" + "\n".join(missing[:12]))

    def new_session_silent(self):
        self.pause()
        for s in list(self.project.sources):
            s.close()
        self.library.clear()
        self.project = Project()
        self.timeline.project = self.project
        self.compare_source = None
        self.in_pt, self.out_pt, self.frame = 0, -1, 0

    def _add_recent(self, path):
        rec = self.settings.value("recent", []) or []
        if isinstance(rec, str):
            rec = [rec]
        path = os.path.abspath(path)
        rec = [path] + [r for r in rec if r != path]
        self.settings.setValue("recent", rec[:12])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        rec = self.settings.value("recent", []) or []
        if isinstance(rec, str):
            rec = [rec]
        for r in rec:
            self.recent_menu.addAction(os.path.basename(r) or r, lambda p=r: self.open_paths([p]))
        if not rec:
            self.recent_menu.addAction("No recent items").setEnabled(False)

    # ================================================================== remote API
    def _on_remote(self, msg, sock):
        cmd = msg.get("cmd")
        ok = True
        res = {}
        try:
            if cmd == "open":
                self.open_paths(msg.get("paths", []), replace=msg.get("replace", False))
            elif cmd == "goto":
                self.set_frame(int(msg["frame"]) - self.base)
            elif cmd == "play":
                self.play(-1 if msg.get("reverse") else 1)
            elif cmd == "pause":
                self.pause()
            elif cmd == "range":
                self.in_pt = int(msg.get("in", self.base)) - self.base
                self.out_pt = int(msg.get("out", 0)) - self.base if "out" in msg else -1
                self._sync_range()
            elif cmd == "marker":
                g = int(msg.get("frame", self.frame + self.base)) - self.base
                self.project.markers[g] = {"color": msg.get("color", "#FF9F0A"), "note": msg.get("note", "")}
                self._refresh_markers()
                self.timeline.update()
            elif cmd == "compare":
                s = self._find_source(msg["path"]) or (self.open_paths([msg["path"]], add_to_timeline=False) or
                                                       [None])[0]
                if s:
                    self.set_compare_source(s, mode=msg.get("mode", "wipe"))
            elif cmd == "status":
                pass
            else:
                ok = False
                res["error"] = f"unknown command {cmd!r}"
            res.update({"frame": self.frame + self.base, "playing": self.playing,
                        "total": self.project.total(), "fps": self.project.fps})
        except Exception as e:
            ok = False
            res["error"] = str(e)
        res["ok"] = ok
        RemoteServer.reply(sock, res)

    # ================================================================== misc
    def show_shortcuts(self):
        text = """<style>td{padding:2px 14px 2px 0}</style><table>
<tr><td><b>Space</b></td><td>Play / pause</td></tr>
<tr><td><b>J / K / L</b></td><td>Reverse · stop · forward (press again for 2×, 4×…)</td></tr>
<tr><td><b>← / →</b></td><td>Previous / next frame</td></tr>
<tr><td><b>↑ / ↓</b></td><td>Previous / next clip</td></tr>
<tr><td><b>Home / End</b></td><td>Start / end of play range</td></tr>
<tr><td><b>I / O / Alt+X</b></td><td>Set in · set out · clear range</td></tr>
<tr><td><b>Ctrl+L</b></td><td>Loop · ping-pong · play once</td></tr>
<tr><td><b>M / Shift+M</b></td><td>Toggle marker · edit marker note</td></tr>
<tr><td><b>Shift+← / →</b></td><td>Previous / next marker</td></tr>
<tr><td><b>Ctrl+← / →</b></td><td>Previous / next annotated frame</td></tr>
<tr><td><b>D</b></td><td>Annotate (then P pen, L… A arrow, R rect, E ellipse, T text, X eraser, V navigate)</td></tr>
<tr><td><b>Ctrl+Z / Ctrl+Y</b></td><td>Undo / redo drawing</td></tr>
<tr><td><b>C</b></td><td>Toggle A/B compare</td></tr>
<tr><td><b>Alt+O</b></td><td>Onion skin</td></tr>
<tr><td><b>F / 1 / = / −</b></td><td>Fit · 100% · zoom in · zoom out</td></tr>
<tr><td><b>Wheel · Alt/Middle-drag</b></td><td>Zoom · pan</td></tr>
<tr><td><b>Tab · F11</b></td><td>Hide panels · presentation mode</td></tr>
<tr><td><b>Ctrl+E · Ctrl+Shift+C</b></td><td>Save snapshot · copy frame</td></tr>
<tr><td><b>Ctrl+O · Ctrl+S</b></td><td>Import media · save session</td></tr>
<tr><td><b>Ctrl+drag clip</b></td><td>Re-order clips on the timeline</td></tr>
</table>"""
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def make_default_player(self):
        from .assoc import make_default
        try:
            msg = make_default()
        except Exception as e:
            msg = f"Could not register file types: {e}"
        if msg:
            QMessageBox.information(self, APP, msg)

    def show_about(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout as VB, QPushButton
        from . import __version__
        d = QDialog(self)
        d.setWindowTitle(f"About {APP}")
        d.setFixedWidth(340)
        lay = VB(d)
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
                            ("A frame-accurate media player and review tool for animation and VFX.",
                             f"color: {theme.css('text2')};"),
                            (f'<a href="{REPO_URL}" style="color:{theme.css("accent")}; text-decoration:none">'
                             f'{REPO_URL.replace("https://", "")}</a>', ""),
                            ("Decoding by FFmpeg (PyAV) · Interface by Qt",
                             f"color: {theme.css('text3')}; font-size: {theme.pt(8)};")):
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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def closeEvent(self, e):
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.play_timer.stop()
        self.audio.close()
        for s in self.project.sources:
            s.close()
        super().closeEvent(e)
