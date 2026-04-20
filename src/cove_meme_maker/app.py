from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QPoint,
    QRect,
    QSettings,
    QStandardPaths,
    QThread,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import ffmpeg_utils as ff
from . import fonts
from .export_worker import AnimatedJob, start_animated_export, start_export
from .timeline import TrimBar
from .image_renderer import (
    MemeSpec,
    classic_block_rect,
    is_animated,
    load_animation,
    render,
    render_to_file,
)
from .video_renderer import VideoJob

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# .gif and animated .webp are probed as potentially-animated and routed to the
# pure-Pillow multi-frame path; if they're single-frame they fall back to the
# still-image path.
ANIMATED_EXTS = {".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
OPEN_FILTERS = (
    "Media (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mkv *.webm *.mov *.avi *.m4v *.gif);;"
    "Images (*.png *.jpg *.jpeg *.webp *.bmp);;"
    "Videos (*.mp4 *.mkv *.webm *.mov *.avi *.m4v);;"
    "All files (*)"
)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_DIR / "cove_icon.png"

DROP_STYLE_IDLE = "QFrame#drop { border: 2px dashed #4a5160; border-radius: 8px; background:#14181f; }"
DROP_STYLE_HOVER = "QFrame#drop { border: 2px dashed #5fb4ff; border-radius: 8px; background:#1b2330; }"
DROP_STYLE_LOADED = "QFrame#drop { border: 1px solid #2a2f3a; border-radius: 8px; background:#0e1116; }"


class DropFrame(QFrame):
    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(DROP_STYLE_IDLE)

    def set_loaded_style(self, loaded: bool) -> None:
        self.setStyleSheet(DROP_STYLE_LOADED if loaded else DROP_STYLE_IDLE)
        self.setCursor(Qt.ArrowCursor if loaded else Qt.PointingHandCursor)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(DROP_STYLE_HOVER)

    def dragLeaveEvent(self, _event) -> None:
        self.setStyleSheet(DROP_STYLE_IDLE)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(DROP_STYLE_IDLE)
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path:
            self.fileDropped.emit(path)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PreviewLabel(QLabel):
    """QLabel that emits rich mouse signals. Used so the MainWindow can
    hit-test against the rendered meme and handle drag-to-reposition."""

    pressed = Signal(object)    # QPoint
    moved = Signal(object)      # QPoint
    released = Signal(object)   # QPoint

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.pressed.emit(event.position().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.moved.emit(event.position().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.released.emit(event.position().toPoint())


class ColorSwatch(QPushButton):
    """Small square button that opens a colour dialog and paints its own colour."""

    colorChanged = Signal(tuple)  # (r, g, b)

    def __init__(self, color: tuple[int, int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._color = color
        self._apply_style()
        self.clicked.connect(self._pick)

    def color(self) -> tuple[int, int, int]:
        return self._color

    def set_color(self, color: tuple[int, int, int]) -> None:
        self._color = color
        self._apply_style()

    def _apply_style(self) -> None:
        r, g, b = self._color
        self.setStyleSheet(
            f"QPushButton {{ background:#{r:02x}{g:02x}{b:02x}; "
            f"border:1px solid #2a2f3a; border-radius:4px; }}"
        )

    def _pick(self) -> None:
        initial = QColor(*self._color)
        c = QColorDialog.getColor(initial, self, "Pick text colour")
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue())
            self._apply_style()
            self.colorChanged.emit(self._color)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cove Meme Maker")
        self.resize(1080, 720)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._source_path: Path | None = None
        self._source_kind: str | None = None  # "image" | "video" | "animated"
        # Pillow image used for preview. For videos this is an extracted frame;
        # for animated GIFs it's the first frame of the sequence.
        self._preview_base: Image.Image | None = None
        self._animated_frames: list[Image.Image] | None = None
        self._animated_durations: list[int] | None = None  # ms per frame
        self._video_info: ff.VideoInfo | None = None
        self._trim_start: float | None = None
        self._trim_end: float | None = None
        self._top_pos: tuple[float, float] | None = None
        self._bottom_pos: tuple[float, float] | None = None
        # Drag state for repositioning classic text on the preview.
        self._drag_target: str | None = None  # "top" | "bottom" | None
        self._drag_grab: tuple[float, float] = (0.0, 0.0)  # normalised offset from block centre
        # Set on each preview refresh so mouse events can map label->image.
        self._pixmap_rect: QRect = QRect()
        self._pixmap_src_size: tuple[int, int] = (0, 0)
        self._tempdir = tempfile.TemporaryDirectory(prefix="cove-meme-")

        self._font_choices = fonts.list_choices()
        self._export_thread: QThread | None = None
        self._export_worker = None
        self._settings = QSettings("Cove", "cove-meme-maker")

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._build_ui()
        self._load_settings()
        self._update_controls_enabled()
        self._on_style_toggled()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # --- Left: preview --------------------------------------------
        self.drop_frame = DropFrame()
        self.drop_frame.setMinimumSize(520, 520)
        self.drop_frame.fileDropped.connect(self._on_file_dropped)
        self.drop_frame.clicked.connect(self._on_drop_clicked)
        drop_layout = QVBoxLayout(self.drop_frame)
        drop_layout.setContentsMargins(12, 12, 12, 12)
        drop_layout.setSpacing(8)

        self.loaded_bar = QWidget()
        loaded_layout = QHBoxLayout(self.loaded_bar)
        loaded_layout.setContentsMargins(0, 0, 0, 0)
        loaded_layout.setSpacing(8)
        self.loaded_name = QLabel("")
        self.loaded_name.setStyleSheet(
            "color:#cfd0d4; font-size:12px; border:none; background:transparent;"
        )
        self.loaded_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Remove the loaded file and drop in a new one")
        self.clear_btn.clicked.connect(self._clear_source)
        loaded_layout.addWidget(self.loaded_name, stretch=1)
        loaded_layout.addWidget(self.clear_btn)
        self.loaded_bar.setVisible(False)
        drop_layout.addWidget(self.loaded_bar)

        self.preview_label = PreviewLabel("Click or drop an image or video here")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "color:#7a8294; font-size:14px; border:none; background:transparent;"
        )
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setMinimumSize(400, 400)
        self.preview_label.pressed.connect(self._on_preview_pressed)
        self.preview_label.moved.connect(self._on_preview_moved)
        self.preview_label.released.connect(self._on_preview_released)
        drop_layout.addWidget(self.preview_label, stretch=1)

        self.trim_bar = TrimBar()
        self.trim_bar.rangeChanged.connect(self._on_trim_changed)
        self.trim_bar.rangePreviewing.connect(self._on_trim_changed)
        self.trim_bar.setVisible(False)
        drop_layout.addWidget(self.trim_bar)

        root.addWidget(self.drop_frame, stretch=3)

        # --- Right: controls ------------------------------------------
        panel = QVBoxLayout()
        panel.setSpacing(10)

        style_box = QFrame()
        style_box.setObjectName("styleBox")
        style_box.setStyleSheet(
            "QFrame#styleBox { border:1px solid #2a2f3a; border-radius:6px; }"
        )
        style_layout = QHBoxLayout(style_box)
        style_layout.setContentsMargins(10, 8, 10, 8)
        self.style_classic = QRadioButton("Classic")
        self.style_classic.setToolTip("White text with black outline, inside the image")
        self.style_classic.setChecked(True)
        self.style_modern = QRadioButton("Modern")
        self.style_modern.setToolTip("Black caption on a white band above the image")
        self._style_group = QButtonGroup(self)
        self._style_group.addButton(self.style_classic)
        self._style_group.addButton(self.style_modern)
        self.style_classic.toggled.connect(self._on_style_toggled)
        self.style_modern.toggled.connect(self._on_style_toggled)
        style_layout.addWidget(QLabel("Style:"))
        style_layout.addWidget(self.style_classic)
        style_layout.addWidget(self.style_modern)
        style_layout.addStretch(1)
        panel.addWidget(style_box)

        # Classic text inputs — each has a colour swatch beside its label.
        self.top_swatch = ColorSwatch((255, 255, 255))
        self.top_swatch.colorChanged.connect(self._schedule_preview)
        self.top_label_row, self.top_label = _labeled_row("Top text", self.top_swatch)
        self.top_edit = QTextEdit()
        self.top_edit.setPlaceholderText("TOP TEXT")
        self.top_edit.setFixedHeight(60)
        self.top_edit.textChanged.connect(self._schedule_preview)

        self.bottom_swatch = ColorSwatch((255, 255, 255))
        self.bottom_swatch.colorChanged.connect(self._schedule_preview)
        self.bottom_label_row, self.bottom_label = _labeled_row(
            "Bottom text", self.bottom_swatch,
        )
        self.bottom_edit = QTextEdit()
        self.bottom_edit.setPlaceholderText("BOTTOM TEXT")
        self.bottom_edit.setFixedHeight(60)
        self.bottom_edit.textChanged.connect(self._schedule_preview)

        # Modern text input
        self.caption_swatch = ColorSwatch((0, 0, 0))
        self.caption_swatch.colorChanged.connect(self._schedule_preview)
        self.caption_label_row, self.caption_label = _labeled_row(
            "Caption", self.caption_swatch,
        )
        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Write your caption here…")
        self.caption_edit.setFixedHeight(100)
        self.caption_edit.textChanged.connect(self._schedule_preview)

        self.uppercase_check = QCheckBox("ALL CAPS")
        self.uppercase_check.setChecked(True)
        self.uppercase_check.setToolTip("Classic style: force uppercase. Off respects the case you typed.")
        self.uppercase_check.toggled.connect(self._schedule_preview)

        panel.addWidget(self.top_label_row)
        panel.addWidget(self.top_edit)
        panel.addWidget(self.bottom_label_row)
        panel.addWidget(self.bottom_edit)
        panel.addWidget(self.caption_label_row)
        panel.addWidget(self.caption_edit)
        panel.addWidget(self.uppercase_check)

        # Typography controls
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.font_combo = QComboBox()
        if self._font_choices:
            for label, path in self._font_choices:
                self.font_combo.addItem(label, str(path))
        else:
            self.font_combo.addItem("Default", "")
        self.font_combo.currentIndexChanged.connect(self._schedule_preview)

        self.add_font_btn = QPushButton("Load .ttf…")
        self.add_font_btn.clicked.connect(self._on_load_font)

        font_row = QHBoxLayout()
        font_row.addWidget(self.font_combo, stretch=1)
        font_row.addWidget(self.add_font_btn)
        font_row_w = QWidget()
        font_row_w.setLayout(font_row)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(3, 30)
        self.size_spin.setValue(9)
        self.size_spin.setSuffix(" %")
        self.size_spin.setToolTip("Font size as a percentage of image height")
        self.size_spin.valueChanged.connect(self._schedule_preview)

        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 20)
        self.stroke_spin.setValue(8)
        self.stroke_spin.setSuffix(" %")
        self.stroke_spin.setToolTip("Classic stroke width, percent of font size")
        self.stroke_spin.valueChanged.connect(self._schedule_preview)

        self.pad_spin = QSpinBox()
        self.pad_spin.setRange(5, 60)
        self.pad_spin.setValue(22)
        self.pad_spin.setSuffix(" %")
        self.pad_spin.setToolTip("Modern band height, percent of image height")
        self.pad_spin.valueChanged.connect(self._schedule_preview)

        form.addRow("Font", font_row_w)
        form.addRow("Size", self.size_spin)
        form.addRow("Stroke", self.stroke_spin)
        form.addRow("Padding", self.pad_spin)

        form_w = QWidget()
        form_w.setLayout(form)
        panel.addWidget(form_w)

        # Video-only output controls
        self.video_form = QFormLayout()
        self.video_form.setLabelAlignment(Qt.AlignRight)

        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["WebP", "GIF", "MP4"])
        self.fmt_combo.currentTextChanged.connect(self._on_format_changed)

        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["8", "12", "15", "24", "30"])
        self.fps_combo.setCurrentText("15")

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["25", "50", "75", "100"])
        self.scale_combo.setCurrentText("100")

        self.webp_quality = QSpinBox()
        self.webp_quality.setRange(1, 100)
        self.webp_quality.setValue(80)

        self.keep_audio_check = QCheckBox("Keep audio")
        self.keep_audio_check.setChecked(True)
        self.keep_audio_check.setToolTip("MP4 only. Off strips the audio track.")

        self.video_form.addRow("Format", self.fmt_combo)
        self.video_form.addRow("FPS", self.fps_combo)
        self.video_form.addRow("Scale %", self.scale_combo)
        self.video_form.addRow("Quality", self.webp_quality)
        self.video_form.addRow("Audio", self.keep_audio_check)

        self.video_form_w = QWidget()
        self.video_form_w.setLayout(self.video_form)
        self.video_form_w.setVisible(False)
        panel.addWidget(self.video_form_w)

        panel.addStretch(1)

        # Export buttons
        self.export_btn = QPushButton("Export")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.setStyleSheet(
            "QPushButton { background:#2563eb; color:white; font-weight:600; "
            "border:none; border-radius:6px; padding:8px 16px; }"
            "QPushButton:hover { background:#1d4ed8; }"
            "QPushButton:disabled { background:#3a4150; color:#9aa0ad; }"
        )
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.copy_btn = QPushButton("Copy image")
        self.copy_btn.setToolTip(
            "Copy the rendered preview to the clipboard — paste directly into a chat app."
        )
        self.copy_btn.clicked.connect(self._on_copy_clicked)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")

        action_row = QHBoxLayout()
        action_row.addWidget(self.copy_btn)
        action_row.addWidget(self.cancel_btn)
        action_row_w = QWidget()
        action_row_w.setLayout(action_row)

        panel.addWidget(self.export_btn)
        panel.addWidget(action_row_w)
        panel.addWidget(self.progress)

        panel_w = QWidget()
        panel_w.setLayout(panel)
        panel_w.setMinimumWidth(360)
        panel_w.setMaximumWidth(440)
        root.addWidget(panel_w, stretch=2)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._on_format_changed(self.fmt_combo.currentText())

        self.setAcceptDrops(True)

    # ----------------------------------------------------- file handling

    def _on_drop_clicked(self) -> None:
        if self._source_path is None:
            self._open_dialog()

    def _open_dialog(self) -> None:
        start_dir = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image or video", start_dir, OPEN_FILTERS,
        )
        if path:
            self._load(Path(path))

    def _on_file_dropped(self, path: str) -> None:
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix in ANIMATED_EXTS:
            self._load_maybe_animated(path)
        elif suffix in IMAGE_EXTS:
            self._load_image(path)
        elif suffix in VIDEO_EXTS:
            self._load_video(path)
        else:
            QMessageBox.warning(
                self, "Unsupported file",
                f"Don't know how to handle {suffix}. Drop an image or a video.",
            )

    def _load_maybe_animated(self, path: Path) -> None:
        """For .gif / .webp: treat as animated if it has >1 frame; else fall
        back to the still-image path so the user still sees a preview.
        """
        try:
            with Image.open(path) as probe_img:
                animated = is_animated(probe_img)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open file", str(exc))
            return
        if not animated:
            self._load_image(path)
            return
        try:
            frames, durations = load_animation(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open animation", str(exc))
            return
        self._source_path = path
        self._source_kind = "animated"
        self._preview_base = frames[0]
        self._animated_frames = frames
        self._animated_durations = durations
        self._video_info = None
        self._trim_start = None
        self._trim_end = None
        self.trim_bar.setVisible(False)
        self.trim_bar.clear()
        self.video_form_w.setVisible(True)
        # MP4/trim/audio/fps/scale don't apply to animated images; narrow the
        # format picker to the two things we can actually produce.
        self._set_format_options(["WebP", "GIF"])
        self.keep_audio_check.setEnabled(False)
        self.fps_combo.setEnabled(False)
        self.scale_combo.setEnabled(False)
        self.drop_frame.set_loaded_style(True)
        total_ms = sum(durations) if durations else 0
        self._show_loaded(
            path,
            f"{frames[0].width}×{frames[0].height} · {len(frames)} frames · {total_ms/1000:.1f}s",
        )
        self.status.showMessage(
            f"{path.name} • animated {len(frames)} frames"
        )
        self._refresh_preview()
        self._update_controls_enabled()

    def _set_format_options(self, options: list[str]) -> None:
        """Replace the fmt_combo contents, preserving the current selection
        if it still exists in the new list."""
        current = self.fmt_combo.currentText()
        self.fmt_combo.blockSignals(True)
        self.fmt_combo.clear()
        self.fmt_combo.addItems(options)
        idx = self.fmt_combo.findText(current)
        if idx >= 0:
            self.fmt_combo.setCurrentIndex(idx)
        self.fmt_combo.blockSignals(False)
        self._on_format_changed(self.fmt_combo.currentText())

    def _load_image(self, path: Path) -> None:
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        self._source_path = path
        self._source_kind = "image"
        self._preview_base = img
        self._animated_frames = None
        self._animated_durations = None
        self._video_info = None
        self._trim_start = None
        self._trim_end = None
        self.trim_bar.setVisible(False)
        self.trim_bar.clear()
        self.video_form_w.setVisible(False)
        self.drop_frame.set_loaded_style(True)
        self._show_loaded(path, f"{img.width}×{img.height}")
        self.status.showMessage(f"{path.name} • {img.width}×{img.height}")
        self._refresh_preview()
        self._update_controls_enabled()

    def _load_video(self, path: Path) -> None:
        try:
            info = ff.probe(path)
        except ff.FFmpegMissingError as exc:
            QMessageBox.critical(self, "Missing dependency", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open video", str(exc))
            return
        frame_path = Path(self._tempdir.name) / "frame.jpg"
        try:
            ff.extract_frame(path, info.duration / 2, frame_path)
            frame = Image.open(frame_path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not preview video", str(exc))
            return
        self._source_path = path
        self._source_kind = "video"
        self._preview_base = frame
        self._animated_frames = None
        self._animated_durations = None
        self._video_info = info
        self._trim_start = None
        self._trim_end = None
        self.trim_bar.set_duration(info.duration)
        self.trim_bar.setVisible(True)
        self.video_form_w.setVisible(True)
        self._set_format_options(["WebP", "GIF", "MP4"])
        self.fps_combo.setEnabled(True)
        self.scale_combo.setEnabled(True)
        self.drop_frame.set_loaded_style(True)
        self._show_loaded(
            path,
            f"{info.width}×{info.height} · {info.duration:.1f}s",
        )
        self.status.showMessage(
            f"{path.name} • {info.width}×{info.height} @ {info.fps:.2f}fps • {info.duration:.2f}s"
        )
        self._refresh_preview()
        self._update_controls_enabled()

    def _show_loaded(self, path: Path, meta: str) -> None:
        self.loaded_name.setText(f"<b>{path.name}</b>  <span style='color:#7a8294'>· {meta}</span>")
        self.loaded_name.setToolTip(str(path))
        self.loaded_bar.setVisible(True)

    def _clear_source(self) -> None:
        if self._export_worker is not None:
            try:
                self._export_worker.cancel()
            except Exception:
                pass
        self._source_path = None
        self._source_kind = None
        self._preview_base = None
        self._animated_frames = None
        self._animated_durations = None
        self._video_info = None
        self._trim_start = None
        self._trim_end = None
        self._top_pos = None
        self._bottom_pos = None
        self.loaded_bar.setVisible(False)
        self.video_form_w.setVisible(False)
        self.trim_bar.setVisible(False)
        self.trim_bar.clear()
        self.drop_frame.set_loaded_style(False)
        self.preview_label.clear()
        self.preview_label.setText("Click or drop an image or video here")
        self.top_edit.clear()
        self.bottom_edit.clear()
        self.caption_edit.clear()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self._set_format_options(["WebP", "GIF", "MP4"])
        self.status.showMessage("Cleared", 3000)
        self._update_controls_enabled()

    def _on_load_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load font", "", "Fonts (*.ttf *.otf);;All files (*)",
        )
        if not path:
            return
        p = Path(path)
        label = p.stem
        self.font_combo.addItem(label, str(p))
        self.font_combo.setCurrentIndex(self.font_combo.count() - 1)

    # ----------------------------------------------------------- styling

    def _on_style_toggled(self) -> None:
        classic = self.style_classic.isChecked()
        self.top_label_row.setVisible(classic)
        self.top_edit.setVisible(classic)
        self.bottom_label_row.setVisible(classic)
        self.bottom_edit.setVisible(classic)
        self.caption_label_row.setVisible(not classic)
        self.caption_edit.setVisible(not classic)
        self.uppercase_check.setVisible(classic)
        self.stroke_spin.setEnabled(classic)
        self.pad_spin.setEnabled(not classic)
        self._schedule_preview()

    def _on_format_changed(self, fmt: str) -> None:
        f = fmt.lower()
        self.webp_quality.setEnabled(f == "webp")
        self.fps_combo.setEnabled(f in ("gif", "webp"))
        self.keep_audio_check.setEnabled(f == "mp4")

    # ------------------------------------------------------------ preview

    def _current_spec(self) -> MemeSpec:
        font_data = self.font_combo.currentData()
        font_path = Path(font_data) if font_data else None
        return MemeSpec(
            style="classic" if self.style_classic.isChecked() else "modern",
            top=self.top_edit.toPlainText(),
            bottom=self.bottom_edit.toPlainText(),
            caption=self.caption_edit.toPlainText(),
            font_path=font_path,
            font_scale=self.size_spin.value() / 100.0,
            stroke_ratio=self.stroke_spin.value() / 100.0,
            padding_scale=self.pad_spin.value() / 100.0,
            top_color=self.top_swatch.color(),
            bottom_color=self.bottom_swatch.color(),
            caption_color=self.caption_swatch.color(),
            uppercase=self.uppercase_check.isChecked(),
            top_pos=self._top_pos,
            bottom_pos=self._bottom_pos,
        )

    def _schedule_preview(self) -> None:
        if self._preview_base is None:
            return
        self._preview_timer.start()

    def _refresh_preview(self) -> None:
        if self._preview_base is None:
            return
        try:
            rendered = render(self._preview_base, self._current_spec())
        except Exception as exc:  # noqa: BLE001
            self.status.showMessage(f"Preview error: {exc}", 4000)
            return
        self.preview_label.setText("")
        buf = io.BytesIO()
        rendered.save(buf, format="PNG")
        image = QImage.fromData(buf.getvalue(), "PNG")
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        # Cache the pixmap's on-label geometry so mouse coords can be mapped
        # back to source-image pixels. The label centres the pixmap, which is
        # how Qt draws it when the widget is larger than the pixmap.
        lw, lh = self.preview_label.width(), self.preview_label.height()
        pw, ph = scaled.width(), scaled.height()
        self._pixmap_rect = QRect((lw - pw) // 2, (lh - ph) // 2, pw, ph)
        # For classic style the rendered size matches the source; for modern
        # the band shifts the image down by the band height. Hit-testing only
        # runs in classic mode so source size is enough.
        self._pixmap_src_size = (rendered.width, rendered.height)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if self._preview_base is not None:
            self._refresh_preview()

    # -------------------------------------------------------------- export

    def _on_export_clicked(self) -> None:
        if self._source_path is None or self._preview_base is None:
            return
        if self._source_kind == "image":
            self._export_image()
        elif self._source_kind == "animated":
            self._export_animated()
        else:
            self._export_video()

    def _export_image(self) -> None:
        assert self._source_path is not None
        suggested = str(self._source_path.with_name(self._source_path.stem + "-meme.png"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save meme", suggested,
            "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;All files (*)",
        )
        if not path:
            return
        out = Path(path)
        try:
            render_to_file(self._preview_base, self._current_spec(), out)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.status.showMessage(f"Saved {out.name}", 6000)
        self.progress.setValue(100)

    def _export_animated(self) -> None:
        assert self._source_path is not None
        assert self._animated_frames is not None and self._animated_durations is not None
        fmt = self.fmt_combo.currentText().lower()
        if fmt not in ("gif", "webp"):
            QMessageBox.warning(self, "Unsupported", "Animated export supports GIF or WebP")
            return
        suggested = str(self._source_path.with_name(self._source_path.stem + f"-meme.{fmt}"))
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {fmt.upper()}", suggested, f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        job = AnimatedJob(
            frames=self._animated_frames,
            durations=self._animated_durations,
            spec=self._current_spec(),
            output=Path(path),
            fmt=fmt,
        )
        self.progress.setValue(0)
        self.progress.setFormat("rendering frames…")
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.showMessage("Exporting…")

        thread, worker = start_animated_export(job)
        worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        worker.log.connect(self._on_log, Qt.QueuedConnection)
        worker.finished.connect(self._on_export_done, Qt.QueuedConnection)
        worker.failed.connect(self._on_export_failed, Qt.QueuedConnection)
        thread.finished.connect(self._reset_export)
        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _export_video(self) -> None:
        assert self._source_path is not None and self._video_info is not None
        fmt = self.fmt_combo.currentText().lower()
        ext = {"gif": "gif", "webp": "webp", "mp4": "mp4"}[fmt]
        suggested = str(self._source_path.with_suffix(f".{ext}"))
        suggested = str(Path(suggested).with_stem(Path(suggested).stem + "-meme"))
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {ext.upper()}", suggested, f"{ext.upper()} (*.{ext})",
        )
        if not path:
            return
        job = VideoJob(
            source=self._source_path,
            output=Path(path),
            width=self._video_info.width,
            height=self._video_info.height,
            spec=self._current_spec(),
            fmt=fmt,  # type: ignore[arg-type]
            fps=int(self.fps_combo.currentText()),
            scale_pct=int(self.scale_combo.currentText()),
            webp_quality=self.webp_quality.value(),
            start=self._trim_start,
            end=self._trim_end,
            keep_audio=self.keep_audio_check.isChecked(),
        )

        self.progress.setValue(0)
        self.progress.setFormat("starting…")
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.showMessage("Exporting…")

        thread, worker = start_export(job)
        worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        worker.log.connect(self._on_log, Qt.QueuedConnection)
        worker.finished.connect(self._on_export_done, Qt.QueuedConnection)
        worker.failed.connect(self._on_export_failed, Qt.QueuedConnection)
        thread.finished.connect(self._reset_export)
        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _on_cancel_clicked(self) -> None:
        if self._export_worker is not None:
            self._export_worker.cancel()
            self.status.showMessage("Cancelling…")

    def _on_progress(self, pct: int) -> None:
        self.progress.setValue(pct)
        self.progress.setFormat("%p%")

    def _on_log(self, msg: str) -> None:
        self.status.showMessage(msg, 4000)

    def _on_export_done(self, out: Path) -> None:
        size_kb = out.stat().st_size / 1024
        if size_kb < 1024:
            size = f"{size_kb:.1f} KB"
        else:
            size = f"{size_kb/1024:.1f} MB"
        self.status.showMessage(f"Saved {out.name} ({size})", 8000)
        self.progress.setValue(100)
        self.progress.setFormat("%p%")

    def _on_export_failed(self, msg: str) -> None:
        self.status.showMessage(f"Failed: {msg}", 8000)
        QMessageBox.warning(self, "Export failed", msg)

    def _reset_export(self) -> None:
        self._export_thread = None
        self._export_worker = None
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    # -------------------------------------------------------------- misc

    def _update_controls_enabled(self) -> None:
        loaded = self._preview_base is not None
        for w in (
            self.style_classic, self.style_modern,
            self.top_edit, self.bottom_edit, self.caption_edit,
            self.top_swatch, self.bottom_swatch, self.caption_swatch,
            self.uppercase_check,
            self.font_combo, self.add_font_btn,
            self.size_spin, self.stroke_spin, self.pad_spin,
            self.export_btn, self.copy_btn,
        ):
            w.setEnabled(loaded)
        self._on_style_toggled()

    # --- preview drag -----------------------------------------------

    def _label_to_norm(self, p: QPoint) -> tuple[float, float] | None:
        """Convert a label-local QPoint into normalised (nx, ny) coordinates
        within the source image. Returns None if the point is outside the
        rendered pixmap.
        """
        if self._pixmap_rect.isEmpty() or not self._pixmap_src_size[0]:
            return None
        rx = p.x() - self._pixmap_rect.x()
        ry = p.y() - self._pixmap_rect.y()
        if not (0 <= rx <= self._pixmap_rect.width() and 0 <= ry <= self._pixmap_rect.height()):
            return None
        nx = rx / self._pixmap_rect.width()
        ny = ry / self._pixmap_rect.height()
        return nx, ny

    def _hit_test_text(self, nx: float, ny: float) -> str | None:
        """Return 'top', 'bottom', or None based on normalised coords."""
        if self._preview_base is None or not self.style_classic.isChecked():
            return None
        spec = self._current_spec()
        w, h = self._preview_base.size
        for which in ("top", "bottom"):
            rect = classic_block_rect((w, h), spec, which)  # type: ignore[arg-type]
            if rect is None:
                continue
            rx, ry, rw, rh = rect
            px = nx * w
            py = ny * h
            if rx <= px <= rx + rw and ry <= py <= ry + rh:
                return which
        return None

    def _on_preview_pressed(self, p: QPoint) -> None:
        # Click on the empty-state preview opens the file picker — restores
        # the behaviour the DropFrame's own click would have done before the
        # label started accepting mouse events.
        if self._source_path is None:
            self._open_dialog()
            return
        norm = self._label_to_norm(p)
        if norm is None:
            return
        which = self._hit_test_text(*norm)
        if which is None:
            return
        # grab offset (in normalised space) so the drag doesn't snap the
        # block's centre to the cursor — it follows the grab point instead.
        spec = self._current_spec()
        current = spec.top_pos if which == "top" else spec.bottom_pos
        if current is None:
            # use the default anchor as a starting centre
            current = (0.5, 0.08) if which == "top" else (0.5, 0.92)
        self._drag_target = which
        self._drag_grab = (current[0] - norm[0], current[1] - norm[1])
        self.preview_label.setCursor(Qt.ClosedHandCursor)
        self.status.showMessage(f"Dragging {which} text…", 2000)

    def _on_preview_moved(self, p: QPoint) -> None:
        norm = self._label_to_norm(p)
        if self._drag_target is None:
            if norm is None:
                self.preview_label.unsetCursor()
                return
            hit = self._hit_test_text(*norm)
            if hit:
                self.preview_label.setCursor(Qt.OpenHandCursor)
            else:
                self.preview_label.unsetCursor()
            return
        if norm is None:
            return
        cx = max(0.0, min(1.0, norm[0] + self._drag_grab[0]))
        cy = max(0.0, min(1.0, norm[1] + self._drag_grab[1]))
        if self._drag_target == "top":
            self._top_pos = (cx, cy)
        else:
            self._bottom_pos = (cx, cy)
        self._refresh_preview()

    def _on_preview_released(self, _p: QPoint) -> None:
        if self._drag_target is not None:
            self._drag_target = None
            self.preview_label.unsetCursor()

    def _on_trim_changed(self, start: float, end: float) -> None:
        """Persist trim range; update status. The preview frame is fixed at
        the middle of the full clip, so we don't re-render on trim changes."""
        self._trim_start = start if start > 0 else None
        self._trim_end = end if self._video_info and end < self._video_info.duration else None
        self.status.showMessage(
            f"Trim: {start:.2f}s – {end:.2f}s  ({end - start:.2f}s)", 4000,
        )

    def _on_copy_clicked(self) -> None:
        if self._preview_base is None:
            return
        try:
            rendered = render(self._preview_base, self._current_spec())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Copy failed", str(exc))
            return
        buf = io.BytesIO()
        rendered.save(buf, format="PNG")
        image = QImage.fromData(buf.getvalue(), "PNG")
        QApplication.clipboard().setImage(image)
        self.status.showMessage("Copied to clipboard", 4000)

    # --- QSettings --------------------------------------------------

    def _load_settings(self) -> None:
        s = self._settings
        style = s.value("style", "classic")
        if style == "modern":
            self.style_modern.setChecked(True)
        font_label = s.value("font_label", "")
        if font_label:
            idx = self.font_combo.findText(font_label)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
        self.size_spin.setValue(int(s.value("size", self.size_spin.value())))
        self.stroke_spin.setValue(int(s.value("stroke", self.stroke_spin.value())))
        self.pad_spin.setValue(int(s.value("padding", self.pad_spin.value())))
        self.uppercase_check.setChecked(_as_bool(s.value("uppercase", True)))
        top = _parse_color(s.value("top_color", ""), (255, 255, 255))
        bottom = _parse_color(s.value("bottom_color", ""), (255, 255, 255))
        caption = _parse_color(s.value("caption_color", ""), (0, 0, 0))
        self.top_swatch.set_color(top)
        self.bottom_swatch.set_color(bottom)
        self.caption_swatch.set_color(caption)
        fmt = s.value("video_format", "WebP")
        idx = self.fmt_combo.findText(fmt)
        if idx >= 0:
            self.fmt_combo.setCurrentIndex(idx)
        self.keep_audio_check.setChecked(_as_bool(s.value("keep_audio", True)))
        self._on_format_changed(self.fmt_combo.currentText())

    def _save_settings(self) -> None:
        s = self._settings
        s.setValue("style", "classic" if self.style_classic.isChecked() else "modern")
        s.setValue("font_label", self.font_combo.currentText())
        s.setValue("size", self.size_spin.value())
        s.setValue("stroke", self.stroke_spin.value())
        s.setValue("padding", self.pad_spin.value())
        s.setValue("uppercase", self.uppercase_check.isChecked())
        s.setValue("top_color", _format_color(self.top_swatch.color()))
        s.setValue("bottom_color", _format_color(self.bottom_swatch.color()))
        s.setValue("caption_color", _format_color(self.caption_swatch.color()))
        s.setValue("video_format", self.fmt_combo.currentText())
        s.setValue("keep_audio", self.keep_audio_check.isChecked())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self._load(Path(path))
                event.acceptProposedAction()
                return

    def closeEvent(self, event) -> None:  # noqa: ANN001
        if self._export_worker is not None:
            try:
                self._export_worker.cancel()
            except Exception:
                pass
        if self._export_thread is not None and self._export_thread.isRunning():
            self._export_thread.quit()
            self._export_thread.wait(2000)
        self._save_settings()
        self._tempdir.cleanup()
        super().closeEvent(event)


def _as_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


def _parse_color(s: object, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(s, str) or not s.startswith("#") or len(s) != 7:
        return default
    try:
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    except ValueError:
        return default


def _format_color(c: tuple[int, int, int]) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def _labeled_row(text: str, extra: QWidget) -> tuple[QWidget, QLabel]:
    """Horizontal row with a label on the left and an auxiliary widget on
    the right. Returns (row_widget, label) so the label can be shown/hidden
    together with its companion input below.
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(text)
    layout.addWidget(label)
    layout.addStretch(1)
    layout.addWidget(extra)
    return row, label
