"""Cove design system for the Meme Maker.

Mirrors the look of Cove Nexus / Cove GIF Maker: teal accent on a deep,
slightly purple-tinted dark background, Geist for text, Geist Mono for
technical metadata.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# ── Palette ────────────────────────────────────────────────────────────────

BG          = "#0a0a0e"
BG_2        = "#0d0d13"
BG_GRAD_TOP = "#0d0d13"
BG_GRAD_BOT = "#0a0a0e"
SURFACE     = "#11111a"
SURFACE_2   = "#161620"
SURFACE_3   = "#1c1c28"
SURFACE_4   = "#232331"
BORDER      = "rgba(255,255,255,0.06)"
BORDER_HARD = "rgba(255,255,255,0.10)"
BORDER_STRONG = "rgba(255,255,255,0.16)"

TEXT         = "#ececf1"
TEXT_DIM     = "#9a9aae"
TEXT_FAINT   = "#6b6b80"
TEXT_FAINTER = "#4a4a5c"

ACCENT       = "#50e6cf"
ACCENT_2     = "#7af5e0"
ACCENT_SOFT  = "rgba(80,230,207,0.13)"
ACCENT_RING  = "rgba(80,230,207,0.32)"
ACCENT_GLOW  = "rgba(80,230,207,0.45)"
ACCENT_ON    = "#0a0a0e"

GOOD        = "#3ddc97"
WARN        = "#ffb454"
DANGER      = "#ff6b6b"

# Solid-color helpers for paint code.
QC_BG          = QColor(BG)
QC_BG_2        = QColor(BG_2)
QC_SURFACE     = QColor(SURFACE)
QC_SURFACE_2   = QColor(SURFACE_2)
QC_SURFACE_3   = QColor(SURFACE_3)
QC_TEXT        = QColor(TEXT)
QC_TEXT_DIM    = QColor(TEXT_DIM)
QC_TEXT_FAINT  = QColor(TEXT_FAINT)
QC_ACCENT      = QColor(ACCENT)
QC_ACCENT_2    = QColor(ACCENT_2)
QC_ACCENT_SOFT = QColor(80, 230, 207, 33)
QC_ACCENT_RING = QColor(80, 230, 207, 82)
QC_BORDER      = QColor(255, 255, 255, 15)

# ── Geometry & typography ──────────────────────────────────────────────────

RADIUS     = 12
RADIUS_SM  = 8
RADIUS_XS  = 6

FONT_SANS = "Geist"
FONT_MONO = "Geist Mono"
FONT_FALLBACK_SANS = "Inter, ui-sans-serif, system-ui, Segoe UI, Roboto, sans-serif"
FONT_FALLBACK_MONO = "JetBrains Mono, ui-monospace, Cascadia Mono, Menlo, monospace"


# ── App-wide QSS ──────────────────────────────────────────────────────────

def _stylesheet() -> str:
    return f"""
    /* ---- Window / chrome ------------------------------------------ */
    QMainWindow, QWidget#cove-root {{
        background: {BG};
        color: {TEXT};
    }}
    QWidget#cove-chrome {{
        background: {BG};
        border: none;
    }}

    QToolTip {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER_HARD};
        padding: 6px 9px;
        border-radius: {RADIUS_SM}px;
        font-size: 11.5px;
    }}

    /* ---- Canvas pane ---------------------------------------------- */
    QWidget#canvas-pane {{
        background: {BG};
        border-right: 1px solid {BORDER};
    }}
    QWidget#canvas-toolbar {{
        background: rgba(255,255,255,0.01);
        border-bottom: 1px solid {BORDER};
    }}
    QWidget#canvas-stage {{
        background: #08080d;
    }}
    QWidget#statusbar {{
        background: rgba(255,255,255,0.012);
        border-top: 1px solid {BORDER};
    }}
    QLabel#status-msg {{
        color: {TEXT_FAINT};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 10.5px;
        background: transparent;
    }}
    QLabel#status-doc {{
        color: {TEXT_FAINT};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 10.5px;
        background: transparent;
    }}
    QWidget#pulse {{
        background: {GOOD};
        border-radius: 3px;
        max-width: 6px; min-width: 6px;
        max-height: 6px; min-height: 6px;
    }}

    /* ---- Inspector pane ------------------------------------------- */
    QWidget#inspector {{
        background: {BG_2};
    }}
    QWidget#inspector-footer {{
        background: transparent;
        border-top: 1px solid {BORDER};
    }}

    /* ---- Labels --------------------------------------------------- */
    QLabel {{ color: {TEXT}; background: transparent; }}
    QLabel[role="dim"]     {{ color: {TEXT_DIM}; }}
    QLabel[role="faint"]   {{ color: {TEXT_FAINT}; font-size: 11px; }}
    QLabel[role="section"] {{
        color: {TEXT_FAINT};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 10.5px;
        letter-spacing: 0.12em;
        font-weight: 500;
    }}
    QLabel[role="file-name"] {{
        color: {TEXT};
        font-size: 13px;
        font-weight: 500;
    }}
    QLabel[role="file-meta"] {{
        color: {TEXT_FAINT};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 10.5px;
    }}
    QLabel[role="caption-label"] {{
        color: {TEXT};
        font-size: 12.5px;
        font-weight: 500;
    }}
    QLabel[role="caption-hint"] {{
        color: {TEXT_FAINT};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 10.5px;
    }}
    QLabel[role="field-label"] {{
        color: {TEXT_DIM};
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 12px;
    }}

    /* ---- Segmented control ---------------------------------------- */
    QWidget#seg-frame {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
    }}
    QPushButton.seg-btn {{
        background: transparent;
        color: {TEXT_DIM};
        border: none;
        border-radius: 6px;
        padding: 7px 0;
        font-size: 12.5px;
    }}
    QPushButton.seg-btn:hover {{ color: {TEXT}; }}
    QPushButton.seg-btn:checked {{
        background: {SURFACE_3};
        color: {TEXT};
    }}

    /* ---- Buttons -------------------------------------------------- */
    QPushButton, QToolButton {{
        background: transparent;
        color: {TEXT_DIM};
        border: 1px solid {BORDER_HARD};
        padding: 6px 12px;
        border-radius: {RADIUS_SM}px;
        font-size: 12.5px;
    }}
    QPushButton:hover, QToolButton:hover {{
        color: {TEXT};
        background: {SURFACE_2};
        border-color: {BORDER_HARD};
    }}
    QPushButton:pressed, QToolButton:pressed {{ background: {SURFACE_3}; }}
    QPushButton:disabled, QToolButton:disabled {{
        color: {TEXT_FAINT};
        background: transparent;
        border-color: {BORDER};
    }}

    QPushButton#btn-primary {{
        color: #ffffff;
        background: {ACCENT};
        border: 1px solid rgba(255,255,255,0.18);
        font-weight: 600;
        padding: 10px 18px;
        font-size: 13px;
        border-radius: 9px;
    }}
    QPushButton#btn-primary:hover    {{ background: #6cf0db; color: #ffffff; }}
    QPushButton#btn-primary:pressed  {{ background: #44d4be; color: #ffffff; }}
    QPushButton#btn-primary:disabled {{
        color: {TEXT_FAINT}; background: {SURFACE_2}; border-color: {BORDER};
    }}

    QPushButton#btn-ghost {{
        color: {TEXT_DIM};
        border: 1px solid {BORDER};
        background: {SURFACE};
        border-radius: 9px;
        padding: 10px 18px;
        font-size: 13px;
    }}
    QPushButton#btn-ghost:hover {{
        color: {TEXT}; background: {SURFACE_2}; border-color: {BORDER_HARD};
    }}

    QPushButton.tb-btn {{
        background: transparent;
        color: {TEXT_DIM};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 0 10px;
        font-size: 12px;
        min-height: 26px; max-height: 26px;
    }}
    QPushButton.tb-btn:hover {{
        color: {TEXT}; background: {SURFACE}; border-color: {BORDER_HARD};
    }}
    QPushButton.tb-btn:disabled {{
        color: {TEXT_FAINT}; border-color: {BORDER};
    }}

    /* ---- Text inputs ---------------------------------------------- */
    QTextEdit {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 8px 10px;
        font-size: 13px;
        selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT};
    }}
    QTextEdit:focus {{
        border-color: {ACCENT_RING};
        background: {SURFACE_2};
    }}

    /* ---- Combo boxes ---------------------------------------------- */
    QComboBox {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 7px 10px;
        min-height: 22px;
        font-size: 12.5px;
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_ON};
    }}
    QComboBox:hover {{ border-color: {BORDER_HARD}; }}
    QComboBox:focus {{ border-color: {ACCENT_RING}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 22px; border: none; background: transparent;
    }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER_HARD};
        border-radius: {RADIUS_SM}px;
        padding: 4px;
        outline: 0;
        selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT};
    }}

    /* ---- Sliders -------------------------------------------------- */
    QSlider {{
        background: transparent;
        border: none;
        height: 20px;
    }}
    QSlider::groove:horizontal {{
        background: {SURFACE_3};
        height: 4px;
        border-radius: 2px;
        border: none;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {ACCENT}, stop:1 {ACCENT_2});
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::add-page:horizontal {{
        background: {SURFACE_3};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        border: 2px solid {BG};
        width: 14px; height: 14px;
        margin: -7px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{
        border-color: {ACCENT};
    }}
    QSlider::groove:horizontal:disabled {{
        background: {SURFACE_2};
    }}
    QSlider::sub-page:horizontal:disabled {{
        background: {SURFACE_3};
    }}
    QSlider::add-page:horizontal:disabled {{
        background: {SURFACE_2};
    }}
    QSlider::handle:horizontal:disabled {{
        background: {TEXT_FAINT};
        border: 2px solid {BG};
        width: 14px; height: 14px;
        margin: -7px 0;
        border-radius: 9px;
    }}

    /* ---- Spin boxes (numeric readout beside sliders) -------------- */
    QSpinBox {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px 6px;
        font-family: "{FONT_MONO}", {FONT_FALLBACK_MONO};
        font-size: 12px;
        min-width: 50px;
    }}
    QSpinBox:focus {{
        border-color: {ACCENT_RING};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0; border: none;
    }}

    /* ---- Checkbox ------------------------------------------------- */
    QCheckBox {{
        color: {TEXT};
        font-size: 12.5px;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 4px;
        border: 1px solid {BORDER_STRONG};
        background: {SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
        image: none;
    }}
    QCheckBox::indicator:disabled {{
        background: {SURFACE_2};
        border-color: {BORDER};
    }}

    /* ---- Drop zone ------------------------------------------------ */
    QFrame#drop-zone {{
        border: 1.5px dashed {BORDER_STRONG};
        border-radius: 12px;
        background: transparent;
    }}
    QFrame#drop-zone:hover {{
        border-color: {ACCENT_RING};
    }}

    /* ---- Scrollbars ----------------------------------------------- */
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent; border: none; margin: 0;
        width: 10px; height: 10px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: rgba(255,255,255,0.08);
        border-radius: 5px; min-height: 24px; min-width: 24px;
    }}
    QScrollBar::handle:hover {{ background: rgba(255,255,255,0.16); }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; }}

    /* ---- Scroll area ---------------------------------------------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* ---- Menu / message box --------------------------------------- */
    QMenu {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER_HARD};
        border-radius: {RADIUS_SM}px;
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

    QMessageBox {{ background: {SURFACE}; }}
    QMessageBox QLabel {{ color: {TEXT}; }}
    """


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")

    base_font = QFont(FONT_SANS, 10)
    base_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(base_font)

    p = QPalette()
    p.setColor(QPalette.Window,          QColor(BG))
    p.setColor(QPalette.WindowText,      QColor(TEXT))
    p.setColor(QPalette.Base,            QColor(SURFACE_2))
    p.setColor(QPalette.AlternateBase,   QColor(SURFACE_3))
    p.setColor(QPalette.ToolTipBase,     QColor(SURFACE_2))
    p.setColor(QPalette.ToolTipText,     QColor(TEXT))
    p.setColor(QPalette.Text,            QColor(TEXT))
    p.setColor(QPalette.Button,          QColor(SURFACE))
    p.setColor(QPalette.ButtonText,      QColor(TEXT))
    p.setColor(QPalette.BrightText,      QColor(DANGER))
    p.setColor(QPalette.Link,            QColor(ACCENT))
    p.setColor(QPalette.Highlight,       QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor(ACCENT_ON))
    p.setColor(QPalette.PlaceholderText, QColor(TEXT_FAINT))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(TEXT_FAINT))
    app.setPalette(p)

    app.setStyleSheet(_stylesheet())
