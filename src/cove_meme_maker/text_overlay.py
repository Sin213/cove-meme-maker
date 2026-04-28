"""Transparent overlay for direct-manipulation editing of meme text.

Sits on top of the preview label and draws editing chrome (dashed border,
corner resize handles, rotation bubble) for whichever classic text block
the user has clicked. The actual text rendering is still done by Pillow
into the preview pixmap — the overlay only paints handles and translates
mouse drags into ``positionChanged`` / ``sizeChanged`` / ``rotationChanged``
signals so ``MainWindow`` can update the spec and re-render.

Mirrors the gesture model from ``cove-gif-maker``'s ``CaptionOverlay``:
drag the body to MOVE, drag a corner handle to RESIZE, drag the rotation
bubble above the text to ROTATE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget


_HANDLE_SIZE = 9
_HANDLE_HIT = 14
_ROTATE_OFFSET = 26
_ROTATE_RADIUS = 6
_ROTATE_HIT = 14

_ACCENT = "#5fb4ff"
_ACCENT_ON = "#0b1018"


@dataclass
class BlockGeom:
    """Geometry of one text block, in source-image pixel coords."""

    cx: float = 0.0
    cy: float = 0.0
    width: float = 0.0   # unrotated bbox width
    height: float = 0.0  # unrotated bbox height
    rotation: float = 0.0  # clockwise degrees
    has_text: bool = False
    size_pct: float = 9.0  # current font size as % of image height


@dataclass
class _DragState:
    which: str = ""           # "top" | "bottom"
    mode: str = ""            # "move" | "resize" | "rotate"
    grab_offset: QPointF = field(default_factory=QPointF)
    resize_anchor: QPointF = field(default_factory=QPointF)
    resize_start_dist: float = 1.0
    resize_start_size_pct: float = 9.0
    rotate_start_cursor_deg: float = 0.0
    rotate_start_block_deg: float = 0.0


class TextOverlay(QWidget):
    """Transparent editing overlay positioned on top of the preview.

    Source-image coords are mapped to widget coords via ``set_display_rect``,
    which the host calls each time the preview is re-rendered.
    """

    positionChanged = Signal(str, float, float)   # which, cx_norm, cy_norm
    sizeChanged = Signal(str, float)              # which, size_pct
    rotationChanged = Signal(str, float)          # which, deg
    activeBlockChanged = Signal(str)              # "" | "top" | "bottom"
    dragFinished = Signal()                       # mouse release after drag

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._image_size: tuple[int, int] = (0, 0)
        self._display_rect = QRectF()
        self._blocks: dict[str, BlockGeom] = {
            "top": BlockGeom(),
            "bottom": BlockGeom(),
        }
        self._active: str = ""
        self._drag = _DragState()

    # -- public state plumbing -----------------------------------------

    def set_image_size(self, size: tuple[int, int]) -> None:
        self._image_size = size

    def set_display_rect(self, rect: QRectF) -> None:
        self._display_rect = QRectF(rect)
        self.update()

    def set_block(self, which: str, geom: BlockGeom) -> None:
        if which not in self._blocks:
            return
        self._blocks[which] = geom
        if not geom.has_text and self._active == which:
            self._active = ""
            self.activeBlockChanged.emit("")
        self.update()

    def set_enabled_for_editing(self, enabled: bool) -> None:
        """Hide all chrome and stop accepting clicks (used when the modern
        style is active and there are no draggable blocks)."""
        self.setVisible(enabled)
        if not enabled:
            self._active = ""
            self._drag = _DragState()

    def active_block(self) -> str:
        return self._active

    def clear_active(self) -> None:
        if self._active:
            self._active = ""
            self.activeBlockChanged.emit("")
            self.update()

    # -- coordinate helpers --------------------------------------------

    def _src_to_widget(self, p: QPointF) -> QPointF:
        sw, sh = self._image_size
        d = self._display_rect
        if sw == 0 or sh == 0 or d.width() == 0 or d.height() == 0:
            return QPointF()
        return QPointF(
            d.x() + p.x() / sw * d.width(),
            d.y() + p.y() / sh * d.height(),
        )

    def _widget_to_src(self, p: QPointF) -> QPointF:
        sw, sh = self._image_size
        d = self._display_rect
        if sw == 0 or sh == 0 or d.width() == 0 or d.height() == 0:
            return QPointF()
        return QPointF(
            (p.x() - d.x()) / d.width() * sw,
            (p.y() - d.y()) / d.height() * sh,
        )

    def _scale_widget_per_src(self) -> float:
        sw, _ = self._image_size
        d = self._display_rect
        if sw == 0 or d.width() == 0:
            return 1.0
        return d.width() / sw

    def _block_rect_widget(self, geom: BlockGeom) -> QRectF:
        if not geom.has_text:
            return QRectF()
        scale = self._scale_widget_per_src()
        c = self._src_to_widget(QPointF(geom.cx, geom.cy))
        w = geom.width * scale
        h = geom.height * scale
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def _block_polygon(self, geom: BlockGeom) -> QPolygonF:
        rect = self._block_rect_widget(geom)
        if rect.isEmpty():
            return QPolygonF()
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(geom.rotation)
        t.translate(-c.x(), -c.y())
        return t.map(QPolygonF([
            rect.topLeft(), rect.topRight(),
            rect.bottomRight(), rect.bottomLeft(),
        ]))

    def _handle_centers(self, geom: BlockGeom) -> dict[str, QPointF]:
        rect = self._block_rect_widget(geom)
        if rect.isEmpty():
            return {}
        corners = {
            "tl": QPointF(rect.left(), rect.top()),
            "tr": QPointF(rect.right(), rect.top()),
            "bl": QPointF(rect.left(), rect.bottom()),
            "br": QPointF(rect.right(), rect.bottom()),
        }
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(geom.rotation)
        t.translate(-c.x(), -c.y())
        return {k: t.map(v) for k, v in corners.items()}

    def _rotate_handle(self, geom: BlockGeom) -> QPointF:
        rect = self._block_rect_widget(geom)
        if rect.isEmpty():
            return QPointF()
        pre = QPointF(rect.center().x(), rect.top() - _ROTATE_OFFSET)
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(geom.rotation)
        t.translate(-c.x(), -c.y())
        return t.map(pre)

    def _hit_block(self, p: QPointF) -> str:
        # Reverse iteration so the visually-on-top block (we draw bottom last)
        # gets first dibs on overlapping clicks.
        for which in ("bottom", "top"):
            geom = self._blocks[which]
            if geom.has_text and self._block_polygon(geom).containsPoint(p, Qt.OddEvenFill):
                return which
        return ""

    def _hit_handle(self, geom: BlockGeom, p: QPointF) -> str:
        for name, c in self._handle_centers(geom).items():
            if abs(p.x() - c.x()) <= _HANDLE_HIT and abs(p.y() - c.y()) <= _HANDLE_HIT:
                return name
        return ""

    def _hit_rotate(self, geom: BlockGeom, p: QPointF) -> bool:
        rh = self._rotate_handle(geom)
        if rh.isNull():
            return False
        dx = p.x() - rh.x()
        dy = p.y() - rh.y()
        return dx * dx + dy * dy <= _ROTATE_HIT * _ROTATE_HIT

    def _angle_to(self, geom: BlockGeom, p: QPointF) -> float:
        rect = self._block_rect_widget(geom)
        c = rect.center()
        return math.degrees(math.atan2(p.y() - c.y(), p.x() - c.x()))

    # -- mouse ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        p = event.position()
        # Rotation handle and corner handles only respond for the active block.
        if self._active:
            geom = self._blocks[self._active]
            if self._hit_rotate(geom, p):
                self._begin_rotate(self._active, p)
                event.accept()
                return
            handle = self._hit_handle(geom, p)
            if handle:
                self._begin_resize(self._active, p)
                event.accept()
                return
        which = self._hit_block(p)
        if not which:
            if self._active:
                self.clear_active()
            event.ignore()
            return
        if which != self._active:
            self._active = which
            self.activeBlockChanged.emit(which)
        self._begin_move(which, p)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        p = event.position()
        if not self._drag.mode:
            self._update_hover(p)
            return
        if self._drag.mode == "move":
            self._do_move(p)
        elif self._drag.mode == "resize":
            self._do_resize(p)
        elif self._drag.mode == "rotate":
            self._do_rotate(p)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drag.mode:
            self._drag = _DragState()
            self._update_hover(event.position())
            self.dragFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_hover(self, p: QPointF) -> None:
        if self._active:
            geom = self._blocks[self._active]
            if self._hit_rotate(geom, p):
                self.setCursor(Qt.CrossCursor)
                return
            if self._hit_handle(geom, p):
                self.setCursor(Qt.SizeFDiagCursor)
                return
        which = self._hit_block(p)
        if which:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    # -- gesture starters ---------------------------------------------

    def _begin_move(self, which: str, p: QPointF) -> None:
        geom = self._blocks[which]
        c = self._src_to_widget(QPointF(geom.cx, geom.cy))
        self._drag = _DragState(
            which=which, mode="move",
            grab_offset=p - c,
        )
        self.setCursor(Qt.ClosedHandCursor)

    def _begin_resize(self, which: str, p: QPointF) -> None:
        geom = self._blocks[which]
        c = self._src_to_widget(QPointF(geom.cx, geom.cy))
        dist = max(1.0, _length(p - c))
        self._drag = _DragState(
            which=which, mode="resize",
            resize_anchor=c,
            resize_start_dist=dist,
            resize_start_size_pct=geom.size_pct,
        )
        self.setCursor(Qt.SizeFDiagCursor)

    def _begin_rotate(self, which: str, p: QPointF) -> None:
        geom = self._blocks[which]
        self._drag = _DragState(
            which=which, mode="rotate",
            rotate_start_cursor_deg=self._angle_to(geom, p),
            rotate_start_block_deg=geom.rotation,
        )
        self.setCursor(Qt.CrossCursor)

    # -- gesture handlers ---------------------------------------------

    def _do_move(self, p: QPointF) -> None:
        target_widget = p - self._drag.grab_offset
        src = self._widget_to_src(target_widget)
        sw, sh = self._image_size
        if sw == 0 or sh == 0:
            return
        nx = max(0.0, min(1.0, src.x() / sw))
        ny = max(0.0, min(1.0, src.y() / sh))
        self.positionChanged.emit(self._drag.which, nx, ny)

    def _do_resize(self, p: QPointF) -> None:
        cur_dist = max(1.0, _length(p - self._drag.resize_anchor))
        scale = cur_dist / self._drag.resize_start_dist
        new_pct = max(2.0, min(40.0, self._drag.resize_start_size_pct * scale))
        self.sizeChanged.emit(self._drag.which, new_pct)

    def _do_rotate(self, p: QPointF) -> None:
        geom = self._blocks[self._drag.which]
        cur = self._angle_to(geom, p)
        delta = cur - self._drag.rotate_start_cursor_deg
        new_rot = (self._drag.rotate_start_block_deg + delta) % 360
        if new_rot > 180:
            new_rot -= 360
        self.rotationChanged.emit(self._drag.which, new_rot)

    # -- painting ------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        if not self._active:
            return
        geom = self._blocks.get(self._active)
        if geom is None or not geom.has_text:
            return
        poly = self._block_polygon(geom)
        if poly.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = QPen(QColor(_ACCENT))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolygon(poly)

        painter.setPen(QPen(QColor(_ACCENT_ON), 1))
        painter.setBrush(QColor(_ACCENT))
        for c in self._handle_centers(geom).values():
            painter.drawRect(QRectF(
                c.x() - _HANDLE_SIZE / 2, c.y() - _HANDLE_SIZE / 2,
                _HANDLE_SIZE, _HANDLE_SIZE,
            ))

        rh = self._rotate_handle(geom)
        rect = self._block_rect_widget(geom)
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(geom.rotation)
        t.translate(-c.x(), -c.y())
        top_mid = t.map(QPointF(c.x(), rect.top()))
        line_pen = QPen(QColor(_ACCENT))
        line_pen.setStyle(Qt.DashLine)
        painter.setPen(line_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(top_mid, rh)
        painter.setPen(QPen(QColor(_ACCENT_ON), 1))
        painter.setBrush(QColor(_ACCENT))
        painter.drawEllipse(rh, _ROTATE_RADIUS, _ROTATE_RADIUS)


def _length(p: QPointF) -> float:
    return math.sqrt(p.x() * p.x() + p.y() * p.y())
