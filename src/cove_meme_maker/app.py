from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QRectF,
    QSettings,
    QStandardPaths,
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
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__, theme, updater
from . import fonts
from .chrome import CoveTitleBar, FramelessResizer
from .crop_dialog import CropDialog
from .image_renderer import (
    MemeSpec,
    classic_block_geometry,
    render,
    render_to_file,
)
from .text_overlay import BlockGeom, TextOverlay

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
OPEN_FILTERS = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_DIR / "cove_icon.png"


# ── Helper widgets ─────────────────────────────────────────────────────────

class CoveRoot(QWidget):
    """Painted background with subtle radial glows, matching cove-nexus."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cove-root")

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        p = QPainter(self)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(theme.BG_GRAD_TOP))
        bg.setColorAt(1.0, QColor(theme.BG_GRAD_BOT))
        p.fillRect(self.rect(), bg)
        glow1 = QRadialGradient(w * 0.85, h * -0.1, max(w, h) * 0.7)
        glow1.setColorAt(0.0, QColor(80, 230, 207, 16))
        glow1.setColorAt(1.0, QColor(80, 230, 207, 0))
        p.fillRect(self.rect(), glow1)
        glow2 = QRadialGradient(w * -0.1, h * 1.0, max(w, h) * 0.55)
        glow2.setColorAt(0.0, QColor(80, 230, 207, 10))
        glow2.setColorAt(1.0, QColor(80, 230, 207, 0))
        p.fillRect(self.rect(), glow2)


class ColorButton(QPushButton):
    colorChanged = Signal(tuple)

    def __init__(self, color: tuple[int, int, int], label: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        r, g, b = color
        self._hex = f"#{r:02x}{g:02x}{b:02x}"
        self._label = label
        self.setMinimumHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 10, 6)
        layout.setSpacing(8)
        self._swatch = QLabel()
        self._swatch.setFixedSize(22, 22)
        self._swatch.setStyleSheet(self._swatch_qss())
        layout.addWidget(self._swatch)
        text_block = QVBoxLayout()
        text_block.setSpacing(1)
        self._label_lbl = QLabel(label)
        self._label_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        self._hex_lbl = QLabel(self._hex.upper())
        self._hex_lbl.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10.5px;"
            f" font-family: '{theme.FONT_MONO}', monospace;"
            f" background: transparent; border: none;"
        )
        text_block.addWidget(self._label_lbl)
        text_block.addWidget(self._hex_lbl)
        layout.addLayout(text_block, stretch=1)
        self._refresh_btn_style()
        self.clicked.connect(self._open_dialog)

    def color(self) -> tuple[int, int, int]:
        c = QColor(self._hex)
        return (c.red(), c.green(), c.blue())

    def set_color(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        self._hex = f"#{r:02x}{g:02x}{b:02x}"
        self._swatch.setStyleSheet(self._swatch_qss())
        self._hex_lbl.setText(self._hex.upper())

    def _swatch_qss(self) -> str:
        return (
            f"background: {self._hex}; border: 1px solid {theme.BORDER_STRONG};"
            f" border-radius: 5px;"
        )

    def _refresh_btn_style(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{ background: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_SM}px;"
            f" padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ background: {theme.SURFACE_2};"
            f" border-color: {theme.BORDER_HARD}; }}"
        )

    def _open_dialog(self) -> None:
        col = QColorDialog.getColor(
            QColor(self._hex), self,
            f"Pick {self._label.lower() or 'color'}",
            QColorDialog.ShowAlphaChannel,
        )
        if col.isValid():
            self._hex = col.name()
            self._swatch.setStyleSheet(self._swatch_qss())
            self._hex_lbl.setText(self._hex.upper())
            self.colorChanged.emit(self.color())


class SliderRow(QWidget):
    """label | slider | spin — linked."""

    valueChanged = Signal(int)

    def __init__(self, label: str, lo: int, hi: int, value: int,
                 suffix: str = "%", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        lbl = QLabel(label)
        lbl.setProperty("role", "field-label")
        lbl.setFixedWidth(56)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(64)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        layout.addWidget(lbl)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.spin)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(v)
        self.spin.setValue(v)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)

    def _from_slider(self, v: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _from_spin(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)


class DropZone(QFrame):
    """Empty-state drop area shown when no image is loaded."""

    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drop-zone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        title = QLabel("Drop an image to begin")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 500; color: {theme.TEXT};"
            " background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("PNG  ·  JPG  ·  WebP  ·  BMP")
        sub.setStyleSheet(
            f"font-size: 12.5px; color: {theme.TEXT_DIM};"
            " background: transparent;"
        )
        sub.setAlignment(Qt.AlignCenter)
        btn = QPushButton("Choose file")
        btn.setProperty("class", "tb-btn")
        btn.clicked.connect(self.clicked.emit)
        btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addWidget(btn, alignment=Qt.AlignCenter)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.fileDropped.emit(path)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PreviewLabel(QLabel):
    pressed = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.pressed.emit()
        super().mousePressEvent(event)


# ── Main window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Cove Meme Maker v{__version__}")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.resize(1380, 880)
        self.setMinimumSize(960, 640)
        self.setMouseTracking(True)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._frameless_resizer = FramelessResizer(self)

        self._source_path: Path | None = None
        self._preview_base: Image.Image | None = None
        self._top_pos: tuple[float, float] | None = None
        self._bottom_pos: tuple[float, float] | None = None
        self._top_size_pct: float | None = None
        self._bottom_size_pct: float | None = None
        self._top_rotation: float = 0.0
        self._bottom_rotation: float = 0.0
        self._pixmap_rect = QRectF()
        self._pixmap_src_size: tuple[int, int] = (0, 0)

        self._font_choices = fonts.list_choices()
        self._settings = QSettings("Cove", "cove-meme-maker")

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._build_ui()
        self._load_settings()
        self._update_controls_enabled()
        self._on_style_toggled()

        self._updater = updater.UpdateController(
            parent=self,
            current_version=__version__,
            repo="Sin213/cove-meme-maker",
            app_display_name="Cove Meme Maker",
            cache_subdir="cove-meme-maker",
        )
        QTimer.singleShot(4000, self._updater.check)

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = CoveRoot()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        chrome = QWidget()
        chrome.setObjectName("cove-chrome")
        outer.addWidget(chrome, stretch=1)
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)

        icon_path = str(ICON_PATH) if ICON_PATH.exists() else None
        self._titlebar = CoveTitleBar(
            self, icon_path=icon_path,
            title="Cove Meme Maker", version=f"v{__version__}",
        )
        chrome_layout.addWidget(self._titlebar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        chrome_layout.addWidget(body, stretch=1)

        # ── Canvas pane ──────────────────────────────────────────
        canvas_pane = QWidget()
        canvas_pane.setObjectName("canvas-pane")
        canvas_layout = QVBoxLayout(canvas_pane)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("canvas-toolbar")
        toolbar.setFixedHeight(52)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(18, 0, 18, 0)
        tb_layout.setSpacing(12)

        file_info = QWidget()
        fi_layout = QVBoxLayout(file_info)
        fi_layout.setContentsMargins(0, 0, 0, 0)
        fi_layout.setSpacing(1)
        self.file_name_label = QLabel("No image — drop a file or click Open")
        self.file_name_label.setProperty("role", "file-name")
        self.file_meta_label = QLabel("—")
        self.file_meta_label.setProperty("role", "file-meta")
        fi_layout.addWidget(self.file_name_label)
        fi_layout.addWidget(self.file_meta_label)
        tb_layout.addWidget(file_info, stretch=1)

        self.crop_btn = QPushButton("Crop")
        self.crop_btn.setProperty("class", "tb-btn")
        self.crop_btn.setToolTip("Crop the image")
        self.crop_btn.clicked.connect(self._on_crop_clicked)
        self.crop_btn.setEnabled(False)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setProperty("class", "tb-btn")
        self.reset_btn.setToolTip("Reset text position / size / rotation")
        self.reset_btn.clicked.connect(self._on_reset_text)
        self.reset_btn.setEnabled(False)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setProperty("class", "tb-btn")
        self.clear_btn.setToolTip("Remove the loaded image")
        self.clear_btn.clicked.connect(self._clear_source)
        self.clear_btn.setEnabled(False)

        tb_layout.addWidget(self.crop_btn)
        tb_layout.addWidget(self.reset_btn)
        tb_layout.addWidget(self.clear_btn)
        canvas_layout.addWidget(toolbar)

        # Stage
        self.stage = QWidget()
        self.stage.setObjectName("canvas-stage")
        self.stage.setAcceptDrops(True)
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(32, 32, 32, 32)
        stage_layout.setAlignment(Qt.AlignCenter)

        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self._on_file_dropped)
        self.drop_zone.clicked.connect(self._open_dialog)
        self.drop_zone.setMinimumSize(400, 300)
        stage_layout.addWidget(self.drop_zone)

        self.preview_label = PreviewLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("background: transparent;")
        self.preview_label.pressed.connect(self._on_preview_clicked)
        self.preview_label.hide()
        stage_layout.addWidget(self.preview_label, stretch=1)

        self.text_overlay = TextOverlay(self.preview_label)
        self.text_overlay.positionChanged.connect(self._on_text_position_changed)
        self.text_overlay.sizeChanged.connect(self._on_text_size_changed)
        self.text_overlay.rotationChanged.connect(self._on_text_rotation_changed)
        self.text_overlay.activeBlockChanged.connect(self._on_active_block_changed)
        self.text_overlay.hide()

        self.preview_label.installEventFilter(self)

        canvas_layout.addWidget(self.stage, stretch=1)

        # Status bar
        statusbar = QWidget()
        statusbar.setObjectName("statusbar")
        statusbar.setFixedHeight(26)
        sb_layout = QHBoxLayout(statusbar)
        sb_layout.setContentsMargins(14, 0, 14, 0)
        sb_layout.setSpacing(8)
        pulse = QWidget()
        pulse.setObjectName("pulse")
        pulse.setFixedSize(6, 6)
        sb_layout.addWidget(pulse)
        self.status_msg = QLabel("Ready")
        self.status_msg.setObjectName("status-msg")
        sb_layout.addWidget(self.status_msg)
        sb_layout.addStretch(1)
        self.status_doc = QLabel("—")
        self.status_doc.setObjectName("status-doc")
        sb_layout.addWidget(self.status_doc)
        canvas_layout.addWidget(statusbar)

        body_layout.addWidget(canvas_pane, stretch=1)

        # ── Inspector pane ───────────────────────────────────────
        inspector = QWidget()
        inspector.setObjectName("inspector")
        inspector.setFixedWidth(380)
        insp_layout = QVBoxLayout(inspector)
        insp_layout.setContentsMargins(0, 0, 0, 0)
        insp_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        self._insp_layout = QVBoxLayout(scroll_content)
        self._insp_layout.setContentsMargins(20, 18, 20, 14)
        self._insp_layout.setSpacing(22)
        scroll.setWidget(scroll_content)
        insp_layout.addWidget(scroll, stretch=1)

        # Section: STYLE
        self._add_section("STYLE")
        seg_frame = QWidget()
        seg_frame.setObjectName("seg-frame")
        seg_layout = QHBoxLayout(seg_frame)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(3)
        self.style_modern = QPushButton("Modern")
        self.style_modern.setProperty("class", "seg-btn")
        self.style_modern.setCheckable(True)
        self.style_modern.setChecked(True)
        self.style_classic = QPushButton("Classic")
        self.style_classic.setProperty("class", "seg-btn")
        self.style_classic.setCheckable(True)
        self.style_modern.clicked.connect(lambda: self._set_style("modern"))
        self.style_classic.clicked.connect(lambda: self._set_style("classic"))
        seg_layout.addWidget(self.style_modern, stretch=1)
        seg_layout.addWidget(self.style_classic, stretch=1)
        self._insp_layout.addWidget(seg_frame)

        # Section: CAPTION (modern)
        self._modern_section = QWidget()
        modern_layout = QVBoxLayout(self._modern_section)
        modern_layout.setContentsMargins(0, 0, 0, 0)
        modern_layout.setSpacing(6)
        cap_head = QHBoxLayout()
        cap_label = QLabel("Caption")
        cap_label.setProperty("role", "caption-label")
        cap_hint = QLabel("above image")
        cap_hint.setProperty("role", "caption-hint")
        cap_head.addWidget(cap_label)
        cap_head.addWidget(cap_hint)
        cap_head.addStretch(1)
        modern_layout.addLayout(cap_head)
        self.caption_swatch = ColorButton((0, 0, 0), "Text color")
        self.caption_swatch.colorChanged.connect(self._schedule_preview)
        modern_layout.addWidget(self.caption_swatch)
        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Caption text…")
        self.caption_edit.setFixedHeight(76)
        self.caption_edit.textChanged.connect(self._schedule_preview)
        modern_layout.addWidget(self.caption_edit)
        self._insp_layout.addWidget(self._modern_section)

        # Section: CAPTION (classic — top + bottom)
        self._classic_section = QWidget()
        classic_layout = QVBoxLayout(self._classic_section)
        classic_layout.setContentsMargins(0, 0, 0, 0)
        classic_layout.setSpacing(10)

        top_label = QLabel("Top text")
        top_label.setProperty("role", "caption-label")
        classic_layout.addWidget(top_label)
        self.top_edit = QTextEdit()
        self.top_edit.setPlaceholderText("TOP TEXT")
        self.top_edit.setFixedHeight(60)
        self.top_edit.textChanged.connect(self._schedule_preview)
        classic_layout.addWidget(self.top_edit)
        self.top_swatch = ColorButton((255, 255, 255), "Top color")
        self.top_swatch.colorChanged.connect(self._schedule_preview)
        classic_layout.addWidget(self.top_swatch)

        bot_label = QLabel("Bottom text")
        bot_label.setProperty("role", "caption-label")
        classic_layout.addWidget(bot_label)
        self.bottom_edit = QTextEdit()
        self.bottom_edit.setPlaceholderText("BOTTOM TEXT")
        self.bottom_edit.setFixedHeight(60)
        self.bottom_edit.textChanged.connect(self._schedule_preview)
        classic_layout.addWidget(self.bottom_edit)
        self.bottom_swatch = ColorButton((255, 255, 255), "Bottom color")
        self.bottom_swatch.colorChanged.connect(self._schedule_preview)
        classic_layout.addWidget(self.bottom_swatch)

        self.uppercase_check = QCheckBox("All caps")
        self.uppercase_check.setChecked(True)
        self.uppercase_check.toggled.connect(self._schedule_preview)
        classic_layout.addWidget(self.uppercase_check)

        self._insp_layout.addWidget(self._classic_section)

        # Section: TYPOGRAPHY
        self._add_section("TYPOGRAPHY")

        font_row = QHBoxLayout()
        font_lbl = QLabel("Font")
        font_lbl.setProperty("role", "field-label")
        font_lbl.setFixedWidth(56)
        self.font_combo = QComboBox()
        if self._font_choices:
            for label, path in self._font_choices:
                self.font_combo.addItem(label, str(path))
        else:
            self.font_combo.addItem("Default", "")
        self.font_combo.currentIndexChanged.connect(self._schedule_preview)
        self.add_font_btn = QPushButton(".ttf")
        self.add_font_btn.setProperty("class", "tb-btn")
        self.add_font_btn.clicked.connect(self._on_load_font)
        font_row.addWidget(font_lbl)
        font_row.addWidget(self.font_combo, stretch=1)
        font_row.addWidget(self.add_font_btn)
        font_row_w = QWidget()
        font_row_w.setLayout(font_row)
        font_row.setContentsMargins(0, 0, 0, 0)
        self._insp_layout.addWidget(font_row_w)

        self.size_slider = SliderRow("Size", 2, 30, 9, "%")
        self.size_slider.valueChanged.connect(self._on_global_size_changed)
        self._insp_layout.addWidget(self.size_slider)

        self.stroke_slider = SliderRow("Stroke", 0, 20, 8, "%")
        self.stroke_slider.valueChanged.connect(self._schedule_preview)
        self._insp_layout.addWidget(self.stroke_slider)

        self.pad_slider = SliderRow("Padding", 5, 60, 22, "%")
        self.pad_slider.valueChanged.connect(self._schedule_preview)
        self._insp_layout.addWidget(self.pad_slider)

        self._insp_layout.addStretch(1)

        # Footer
        footer = QWidget()
        footer.setObjectName("inspector-footer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(20, 14, 20, 18)
        footer_layout.setSpacing(8)

        self.export_btn = QPushButton("Export PNG")
        self.export_btn.setObjectName("btn-primary")
        self.export_btn.setMinimumHeight(38)
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.copy_btn = QPushButton("Copy to clipboard")
        self.copy_btn.setObjectName("btn-ghost")
        self.copy_btn.setMinimumHeight(38)
        self.copy_btn.clicked.connect(self._on_copy_clicked)

        footer_layout.addWidget(self.export_btn)
        footer_layout.addWidget(self.copy_btn)
        insp_layout.addWidget(footer)

        body_layout.addWidget(inspector)

        self.setAcceptDrops(True)

    def _add_section(self, title: str) -> None:
        lbl = QLabel(title)
        lbl.setProperty("role", "section")
        self._insp_layout.addWidget(lbl)

    # ── Style toggle ───────────────────────────────────────────────────

    def _set_style(self, style: str) -> None:
        classic = style == "classic"
        self.style_classic.setChecked(classic)
        self.style_modern.setChecked(not classic)
        self._on_style_toggled()

    def _on_style_toggled(self) -> None:
        classic = self.style_classic.isChecked()
        self._classic_section.setVisible(classic)
        self._modern_section.setVisible(not classic)
        self.stroke_slider.setEnabled(classic)
        self.pad_slider.setEnabled(not classic)
        if not classic:
            self.text_overlay.set_enabled_for_editing(False)
        elif self._preview_base is not None:
            self.text_overlay.set_enabled_for_editing(True)
        self._schedule_preview()

    # ── File handling ──────────────────────────────────────────────────

    def _on_preview_clicked(self) -> None:
        if self._source_path is None:
            self._open_dialog()

    def _open_dialog(self) -> None:
        start_dir = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", start_dir, OPEN_FILTERS,
        )
        if path:
            self._load(Path(path))

    def _on_file_dropped(self, path: str) -> None:
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in IMAGE_EXTS:
            QMessageBox.warning(
                self, "Unsupported file",
                f"Can't handle {suffix}. Drop an image "
                f"({', '.join(sorted(IMAGE_EXTS))}).",
            )
            return
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        self._source_path = path
        self._preview_base = img
        self._top_pos = None
        self._bottom_pos = None
        self._top_size_pct = None
        self._bottom_size_pct = None
        self._top_rotation = 0.0
        self._bottom_rotation = 0.0
        self.file_name_label.setText(path.name)
        self.file_meta_label.setText(f"{img.width}×{img.height}")
        self.status_doc.setText(f"{img.width}×{img.height}")
        self.drop_zone.hide()
        self.preview_label.show()
        self._status("Loaded")
        self._refresh_preview()
        self._update_controls_enabled()

    def _clear_source(self) -> None:
        self._source_path = None
        self._preview_base = None
        self._top_pos = None
        self._bottom_pos = None
        self._top_size_pct = None
        self._bottom_size_pct = None
        self._top_rotation = 0.0
        self._bottom_rotation = 0.0
        self.file_name_label.setText("No image — drop a file or click Open")
        self.file_meta_label.setText("—")
        self.status_doc.setText("—")
        self.preview_label.clear()
        self.preview_label.hide()
        self.text_overlay.hide()
        self.drop_zone.show()
        self.top_edit.clear()
        self.bottom_edit.clear()
        self.caption_edit.clear()
        self._status("Cleared")
        self._update_controls_enabled()

    def _on_load_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load font", "", "Fonts (*.ttf *.otf);;All files (*)",
        )
        if not path:
            return
        p = Path(path)
        self.font_combo.addItem(p.stem, str(p))
        self.font_combo.setCurrentIndex(self.font_combo.count() - 1)

    def _on_crop_clicked(self) -> None:
        if self._preview_base is None:
            return
        dlg = CropDialog(self._preview_base, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        cropped = dlg.cropped_image()
        if cropped.width < 1 or cropped.height < 1:
            return
        self._preview_base = cropped
        self._top_pos = None
        self._bottom_pos = None
        self._top_rotation = 0.0
        self._bottom_rotation = 0.0
        self.file_meta_label.setText(f"{cropped.width}×{cropped.height} (cropped)")
        self.status_doc.setText(f"{cropped.width}×{cropped.height}")
        self._status("Cropped")
        self._refresh_preview()

    def _on_reset_text(self) -> None:
        self._top_pos = None
        self._bottom_pos = None
        self._top_size_pct = None
        self._bottom_size_pct = None
        self._top_rotation = 0.0
        self._bottom_rotation = 0.0
        self.text_overlay.clear_active()
        self._status("Reset text transforms")
        self._refresh_preview()

    # ── Preview ────────────────────────────────────────────────────────

    def _current_spec(self) -> MemeSpec:
        font_data = self.font_combo.currentData()
        font_path = Path(font_data) if font_data else None
        return MemeSpec(
            style="classic" if self.style_classic.isChecked() else "modern",
            top=self.top_edit.toPlainText(),
            bottom=self.bottom_edit.toPlainText(),
            caption=self.caption_edit.toPlainText(),
            font_path=font_path,
            font_scale=self.size_slider.value() / 100.0,
            stroke_ratio=self.stroke_slider.value() / 100.0,
            padding_scale=self.pad_slider.value() / 100.0,
            top_color=self.top_swatch.color(),
            bottom_color=self.bottom_swatch.color(),
            caption_color=self.caption_swatch.color(),
            uppercase=self.uppercase_check.isChecked(),
            top_pos=self._top_pos,
            bottom_pos=self._bottom_pos,
            top_size_pct=self._top_size_pct,
            bottom_size_pct=self._bottom_size_pct,
            top_rotation=self._top_rotation,
            bottom_rotation=self._bottom_rotation,
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
            self._status(f"Preview error: {exc}")
            return
        self.preview_label.setText("")
        if rendered.mode != "RGB":
            rendered = rendered.convert("RGB")
        raw = rendered.tobytes("raw", "RGB")
        image = QImage(raw, rendered.width, rendered.height,
                       3 * rendered.width, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        lw, lh = self.preview_label.width(), self.preview_label.height()
        pw, ph = scaled.width(), scaled.height()
        self._pixmap_rect = QRectF((lw - pw) / 2, (lh - ph) / 2, pw, ph)
        self._pixmap_src_size = (rendered.width, rendered.height)
        self._sync_overlay()

    def _sync_overlay(self) -> None:
        if self._preview_base is None or not self.style_classic.isChecked():
            self.text_overlay.hide()
            return
        self.text_overlay.show()
        self.text_overlay.setGeometry(
            0, 0, self.preview_label.width(), self.preview_label.height(),
        )
        self.text_overlay.set_image_size(self._pixmap_src_size)
        self.text_overlay.set_display_rect(self._pixmap_rect)
        spec = self._current_spec()
        for which in ("top", "bottom"):
            geom = classic_block_geometry(self._pixmap_src_size, spec, which)
            if geom is None:
                self.text_overlay.set_block(which, BlockGeom(has_text=False))
                continue
            cx, cy, w, h, rot = geom
            size_pct = (
                self._top_size_pct if which == "top" else self._bottom_size_pct
            )
            if size_pct is None:
                size_pct = self.size_slider.value()
            self.text_overlay.set_block(which, BlockGeom(
                cx=cx, cy=cy, width=w, height=h, rotation=rot,
                has_text=True, size_pct=size_pct,
            ))

    def eventFilter(self, obj, event):  # noqa: ANN001
        if obj is self.preview_label and event.type() == QEvent.Resize:
            self.text_overlay.setGeometry(
                0, 0, self.preview_label.width(), self.preview_label.height(),
            )
            if self._preview_base is not None:
                self._refresh_preview()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if self._preview_base is not None:
            self._refresh_preview()

    # ── Overlay signal handlers ────────────────────────────────────────

    def _on_text_position_changed(self, which: str, cx: float, cy: float) -> None:
        if which == "top":
            self._top_pos = (cx, cy)
        elif which == "bottom":
            self._bottom_pos = (cx, cy)
        self._refresh_preview()

    def _on_text_size_changed(self, which: str, size_pct: float) -> None:
        if which == "top":
            self._top_size_pct = size_pct
        elif which == "bottom":
            self._bottom_size_pct = size_pct
        self._status(f"{which} text size: {size_pct:.1f}%")
        self._refresh_preview()

    def _on_text_rotation_changed(self, which: str, deg: float) -> None:
        if which == "top":
            self._top_rotation = deg
        elif which == "bottom":
            self._bottom_rotation = deg
        self._status(f"{which} rotation: {deg:.0f}°")
        self._refresh_preview()

    def _on_active_block_changed(self, which: str) -> None:
        if which:
            self._status(f"Editing {which} text — drag to move, corner to resize, bubble to rotate")

    def _on_global_size_changed(self) -> None:
        self._schedule_preview()

    # ── Export ─────────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        if self._source_path is None or self._preview_base is None:
            return
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
        size_kb = out.stat().st_size / 1024
        size = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        self._status(f"Saved {out.name} ({size})")

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
        self._status("Copied to clipboard")

    # ── Misc ───────────────────────────────────────────────────────────

    def _status(self, msg: str) -> None:
        self.status_msg.setText(msg)

    def _update_controls_enabled(self) -> None:
        loaded = self._preview_base is not None
        for w in (
            self.style_classic, self.style_modern,
            self.top_edit, self.bottom_edit, self.caption_edit,
            self.top_swatch, self.bottom_swatch, self.caption_swatch,
            self.uppercase_check,
            self.font_combo, self.add_font_btn,
            self.size_slider, self.stroke_slider, self.pad_slider,
            self.export_btn, self.copy_btn,
            self.crop_btn, self.reset_btn, self.clear_btn,
        ):
            w.setEnabled(loaded)
        self._on_style_toggled()

    # ── Settings ───────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        s = self._settings
        style = s.value("style", "classic")
        if style == "modern":
            self._set_style("modern")
        else:
            self._set_style("classic")
        font_label = s.value("font_label", "")
        if font_label:
            idx = self.font_combo.findText(font_label)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
        self.size_slider.setValue(int(s.value("size", self.size_slider.value())))
        self.stroke_slider.setValue(int(s.value("stroke", self.stroke_slider.value())))
        self.pad_slider.setValue(int(s.value("padding", self.pad_slider.value())))
        self.uppercase_check.setChecked(_as_bool(s.value("uppercase", True)))
        self.top_swatch.set_color(_parse_color(s.value("top_color", ""), (255, 255, 255)))
        self.bottom_swatch.set_color(_parse_color(s.value("bottom_color", ""), (255, 255, 255)))
        self.caption_swatch.set_color(_parse_color(s.value("caption_color", ""), (0, 0, 0)))

    def _save_settings(self) -> None:
        s = self._settings
        s.setValue("style", "classic" if self.style_classic.isChecked() else "modern")
        s.setValue("font_label", self.font_combo.currentText())
        s.setValue("size", self.size_slider.value())
        s.setValue("stroke", self.stroke_slider.value())
        s.setValue("padding", self.pad_slider.value())
        s.setValue("uppercase", self.uppercase_check.isChecked())
        s.setValue("top_color", _format_color(self.top_swatch.color()))
        s.setValue("bottom_color", _format_color(self.bottom_swatch.color()))
        s.setValue("caption_color", _format_color(self.caption_swatch.color()))

    # ── Window events ──────────────────────────────────────────────────

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._frameless_resizer.try_press(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._frameless_resizer.try_move(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._frameless_resizer.try_release(event):
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._frameless_resizer.clear_hover()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._save_settings()
        super().closeEvent(event)


# ── Helpers ────────────────────────────────────────────────────────────────

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
