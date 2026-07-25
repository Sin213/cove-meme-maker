"""Transparent overlay for direct-manipulation editing of image overlays.

Sits between the preview label and the text overlay in the widget parent
chain::

    PreviewLabel
    └── ImageOverlay
        └── TextOverlay

The text overlay is the topmost widget and receives mouse input first. When it
ignores an event (empty space) the *press* propagates down to this widget, which
hit-tests image overlays topmost-first. Hover moves and drag moves are NOT
propagated by Qt, so while the text overlay is on top the host installs an event
filter on it that forwards in-flight gesture moves/releases here and drives the
hover cursor (see ``MainWindow._route_image_overlay_event``). This mirrors the
proven text-overlay interaction (which works purely because it is topmost) and
avoids a ``QWidget.grabMouse()`` — unsupported for non-popups on Wayland.

Canonical overlay geometry is normalised relative to the *base-image region*
(post-crop). The host maps that region to widget coordinates and hands us the
resulting rectangle via :meth:`set_base_rect`; we translate mouse drags into
``overlayMoved`` / ``overlayResized`` / ``overlayRotated`` signals and never
store widget-pixel coordinates as canonical state.

The gesture model mirrors ``TextOverlay`` without importing its internals: drag
the body to MOVE, drag a corner handle to RESIZE (aspect-preserving), drag the
top bubble to ROTATE (around the overlay centre).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QWidget


_HANDLE_SIZE = 9
_HANDLE_HIT = 14
_MIN_WIDTH_PX = 12  # minimum rendered overlay width, in base-image pixels
# Top rotate handle, mirroring the text overlay's bubble spacing/size.
_ROTATE_OFFSET = 26  # gap above the selection rectangle
_ROTATE_RADIUS = 6   # drawn bubble radius
_ROTATE_HIT = 14     # click tolerance radius

_ACCENT = "#5fb4ff"
_ACCENT_ON = "#0b1018"


@dataclass
class ImageGeom:
    """Geometry of one image overlay, normalised to the base-image region."""

    x: float = 0.5      # normalised centre X
    y: float = 0.5      # normalised centre Y
    width: float = 0.3  # width as a fraction of base width
    aspect: float = 1.0  # source height / source width
    rotation: float = 0.0  # clockwise degrees around the overlay centre


@dataclass
class _DragState:
    index: int = -1
    mode: str = ""  # "move" | "resize" | "rotate"
    grab_offset: QPointF = field(default_factory=QPointF)
    resize_anchor: QPointF = field(default_factory=QPointF)
    resize_start_dist: float = 1.0
    resize_start_width: float = 0.3
    rotate_start_cursor_deg: float = 0.0
    rotate_start_rotation: float = 0.0


class ImageOverlay(QWidget):
    """Transparent editing overlay for image overlays on top of the preview."""

    overlaySelected = Signal(int)          # index, or -1 for none
    overlayMoved = Signal(int, float, float)  # index, x_norm, y_norm
    overlayResized = Signal(int, float)    # index, width_norm
    overlayRotated = Signal(int, float)    # index, degrees (clockwise)
    overlayDeleted = Signal(int)           # index
    dragFinished = Signal()                # mouse release after a drag

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.ClickFocus)
        self._base_rect = QRectF()
        self._base_size: tuple[int, int] = (0, 0)
        self._overlays: list[ImageGeom] = []
        self._selected: int = -1
        self._drag = _DragState()

    # -- public state plumbing -----------------------------------------

    def set_base_rect(self, rect: QRectF) -> None:
        """Base-image region in widget coordinates (post-crop, band-offset)."""
        self._base_rect = QRectF(rect)
        self.update()

    def set_base_size(self, size: tuple[int, int]) -> None:
        self._base_size = size

    def set_overlays(self, overlays: list[ImageGeom], selected: int) -> None:
        self._overlays = list(overlays)
        self._selected = selected if 0 <= selected < len(overlays) else -1
        self.update()

    def selected_index(self) -> int:
        return self._selected

    def clear_selection(self) -> None:
        if self._selected != -1:
            self._selected = -1
            self.update()

    def is_dragging(self) -> bool:
        """True while a move/resize/rotate gesture is in progress."""
        return bool(self._drag.mode)

    # -- coordinate helpers --------------------------------------------

    def _min_width_norm(self) -> float:
        bw, _ = self._base_size
        if bw <= 0:
            return 0.0
        return _MIN_WIDTH_PX / bw

    def _norm_to_widget(self, x: float, y: float) -> QPointF:
        d = self._base_rect
        return QPointF(d.x() + x * d.width(), d.y() + y * d.height())

    def _widget_to_norm(self, p: QPointF) -> tuple[float, float]:
        d = self._base_rect
        if d.width() == 0 or d.height() == 0:
            return 0.0, 0.0
        return (p.x() - d.x()) / d.width(), (p.y() - d.y()) / d.height()

    def _overlay_rect(self, geom: ImageGeom) -> QRectF:
        """Axis-aligned (unrotated) bounding rectangle in widget coords."""
        d = self._base_rect
        if d.width() == 0 or d.height() == 0:
            return QRectF()
        w = geom.width * d.width()
        h = w * geom.aspect
        c = self._norm_to_widget(geom.x, geom.y)
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def _rotation_transform(self, geom: ImageGeom) -> QTransform:
        c = self._overlay_rect(geom).center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(geom.rotation)
        t.translate(-c.x(), -c.y())
        return t

    def _overlay_polygon(self, geom: ImageGeom) -> QPolygonF:
        rect = self._overlay_rect(geom)
        if rect.isEmpty():
            return QPolygonF()
        return self._rotation_transform(geom).map(QPolygonF([
            rect.topLeft(), rect.topRight(),
            rect.bottomRight(), rect.bottomLeft(),
        ]))

    def _handle_centers(self, geom: ImageGeom) -> dict[str, QPointF]:
        rect = self._overlay_rect(geom)
        if rect.isEmpty():
            return {}
        corners = {
            "tl": QPointF(rect.left(), rect.top()),
            "tr": QPointF(rect.right(), rect.top()),
            "bl": QPointF(rect.left(), rect.bottom()),
            "br": QPointF(rect.right(), rect.bottom()),
        }
        t = self._rotation_transform(geom)
        return {k: t.map(v) for k, v in corners.items()}

    def _rotate_handle(self, geom: ImageGeom) -> QPointF:
        rect = self._overlay_rect(geom)
        if rect.isEmpty():
            return QPointF()
        pre = QPointF(rect.center().x(), rect.top() - _ROTATE_OFFSET)
        return self._rotation_transform(geom).map(pre)

    def _hit_overlay(self, p: QPointF) -> int:
        # Topmost-first: later overlays render on top, so iterate in reverse.
        for i in range(len(self._overlays) - 1, -1, -1):
            poly = self._overlay_polygon(self._overlays[i])
            if not poly.isEmpty() and poly.containsPoint(p, Qt.OddEvenFill):
                return i
        return -1

    def _hit_handle(self, geom: ImageGeom, p: QPointF) -> str:
        for name, c in self._handle_centers(geom).items():
            if abs(p.x() - c.x()) <= _HANDLE_HIT and abs(p.y() - c.y()) <= _HANDLE_HIT:
                return name
        return ""

    def _hit_rotate(self, geom: ImageGeom, p: QPointF) -> bool:
        rh = self._rotate_handle(geom)
        if rh.isNull():
            return False
        dx = p.x() - rh.x()
        dy = p.y() - rh.y()
        return dx * dx + dy * dy <= _ROTATE_HIT * _ROTATE_HIT

    def _angle_to(self, geom: ImageGeom, p: QPointF) -> float:
        c = self._overlay_rect(geom).center()
        return math.degrees(math.atan2(p.y() - c.y(), p.x() - c.x()))

    # -- host-facing hit predicates (used by the event-filter router) --

    def wants_press(self, p: QPointF) -> bool:
        """True when a left-press at ``p`` is an image-overlay interaction.

        The host routes the press here only when this returns True; otherwise it
        lets the text overlay (and its ignore-propagation) run unchanged.
        """
        if 0 <= self._selected < len(self._overlays):
            geom = self._overlays[self._selected]
            if self._hit_rotate(geom, p) or self._hit_handle(geom, p):
                return True
        return self._hit_overlay(p) != -1

    def cursor_for(self, p: QPointF):
        """Cursor shape for hovering ``p``, or ``None`` when not over an overlay."""
        if 0 <= self._selected < len(self._overlays):
            geom = self._overlays[self._selected]
            if self._hit_rotate(geom, p):
                return Qt.CrossCursor
            if self._hit_handle(geom, p):
                return Qt.SizeFDiagCursor
        if self._hit_overlay(p) != -1:
            return Qt.SizeAllCursor
        return None

    # -- mouse ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        p = event.position()
        # Hit-test priority: rotate handle, then corner handles, then body,
        # then empty space. The rotate handle and corner handles only respond
        # for the already-selected overlay.
        if 0 <= self._selected < len(self._overlays):
            geom = self._overlays[self._selected]
            if self._hit_rotate(geom, p):
                self._begin_rotate(self._selected, p)
                event.accept()
                return
            if self._hit_handle(geom, p):
                self._begin_resize(self._selected, p)
                event.accept()
                return
        index = self._hit_overlay(p)
        if index == -1:
            if self._selected != -1:
                self._selected = -1
                self.overlaySelected.emit(-1)
                self.update()
            event.ignore()
            return
        if index != self._selected:
            self._selected = index
            self.overlaySelected.emit(index)
            self.update()
        self.setFocus(Qt.MouseFocusReason)
        self._begin_move(index, p)
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
        cur = self.cursor_for(p)
        if cur is None:
            self.unsetCursor()
        else:
            self.setCursor(cur)

    # -- gesture starters ---------------------------------------------

    def _begin_move(self, index: int, p: QPointF) -> None:
        geom = self._overlays[index]
        c = self._norm_to_widget(geom.x, geom.y)
        self._drag = _DragState(index=index, mode="move", grab_offset=p - c)
        self.setCursor(Qt.SizeAllCursor)

    def _begin_resize(self, index: int, p: QPointF) -> None:
        geom = self._overlays[index]
        c = self._norm_to_widget(geom.x, geom.y)
        dist = max(1.0, _length(p - c))
        self._drag = _DragState(
            index=index, mode="resize",
            resize_anchor=c,
            resize_start_dist=dist,
            resize_start_width=geom.width,
        )
        self.setCursor(Qt.SizeFDiagCursor)

    def _begin_rotate(self, index: int, p: QPointF) -> None:
        geom = self._overlays[index]
        self._drag = _DragState(
            index=index, mode="rotate",
            rotate_start_cursor_deg=self._angle_to(geom, p),
            rotate_start_rotation=geom.rotation,
        )
        self.setCursor(Qt.CrossCursor)

    # -- gesture handlers ---------------------------------------------

    def _do_move(self, p: QPointF) -> None:
        target = p - self._drag.grab_offset
        nx, ny = self._widget_to_norm(target)
        self.overlayMoved.emit(self._drag.index, nx, ny)

    def _do_resize(self, p: QPointF) -> None:
        cur_dist = max(1.0, _length(p - self._drag.resize_anchor))
        scale = cur_dist / self._drag.resize_start_dist
        new_width = max(self._min_width_norm(), self._drag.resize_start_width * scale)
        self.overlayResized.emit(self._drag.index, new_width)

    def _do_rotate(self, p: QPointF) -> None:
        geom = self._overlays[self._drag.index]
        cur = self._angle_to(geom, p)
        delta = cur - self._drag.rotate_start_cursor_deg
        new_rot = (self._drag.rotate_start_rotation + delta) % 360
        if new_rot > 180:
            new_rot -= 360
        self.overlayRotated.emit(self._drag.index, new_rot)

    def hideEvent(self, event) -> None:  # noqa: ANN001
        # Never leave a half-finished gesture active if we are hidden mid-drag.
        self._drag = _DragState()
        super().hideEvent(event)

    # -- keyboard ------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
            and 0 <= self._selected < len(self._overlays)
        ):
            self.overlayDeleted.emit(self._selected)
            event.accept()
            return
        super().keyPressEvent(event)

    # -- painting ------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        if not (0 <= self._selected < len(self._overlays)):
            return
        geom = self._overlays[self._selected]
        poly = self._overlay_polygon(geom)
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

        # Top rotate handle: dashed connector from the (rotated) top edge to the
        # bubble, mirroring the text overlay's chrome.
        rh = self._rotate_handle(geom)
        rect = self._overlay_rect(geom)
        top_mid = self._rotation_transform(geom).map(
            QPointF(rect.center().x(), rect.top())
        )
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
