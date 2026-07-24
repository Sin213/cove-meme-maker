"""Transparent overlay for direct-manipulation editing of image overlays.

Sits between the preview label and the text overlay in the widget parent
chain::

    PreviewLabel
    └── ImageOverlay
        └── TextOverlay

The text overlay receives mouse input first; when it ignores empty space the
event propagates to this widget, which hit-tests image overlays topmost-first.
When this widget also ignores empty space the event reaches ``PreviewLabel``.

Canonical overlay geometry is normalised relative to the *base-image region*
(post-crop). The host maps that region to widget coordinates and hands us the
resulting rectangle via :meth:`set_base_rect`; we translate mouse drags into
``overlayMoved`` / ``overlayResized`` signals and never store widget-pixel
coordinates as canonical state.

The gesture model mirrors ``TextOverlay`` without importing its internals:
drag the body to MOVE, drag a corner handle to RESIZE (aspect-preserving).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


_HANDLE_SIZE = 9
_HANDLE_HIT = 14
_MIN_WIDTH_PX = 12  # minimum rendered overlay width, in base-image pixels

_ACCENT = "#5fb4ff"
_ACCENT_ON = "#0b1018"


@dataclass
class ImageGeom:
    """Geometry of one image overlay, normalised to the base-image region."""

    x: float = 0.5      # normalised centre X
    y: float = 0.5      # normalised centre Y
    width: float = 0.3  # width as a fraction of base width
    aspect: float = 1.0  # source height / source width


@dataclass
class _DragState:
    index: int = -1
    mode: str = ""  # "move" | "resize"
    grab_offset: QPointF = field(default_factory=QPointF)
    resize_anchor: QPointF = field(default_factory=QPointF)
    resize_start_dist: float = 1.0
    resize_start_width: float = 0.3


class ImageOverlay(QWidget):
    """Transparent editing overlay for image overlays on top of the preview."""

    overlaySelected = Signal(int)          # index, or -1 for none
    overlayMoved = Signal(int, float, float)  # index, x_norm, y_norm
    overlayResized = Signal(int, float)    # index, width_norm
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
        d = self._base_rect
        if d.width() == 0 or d.height() == 0:
            return QRectF()
        w = geom.width * d.width()
        h = w * geom.aspect
        c = self._norm_to_widget(geom.x, geom.y)
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def _handle_centers(self, geom: ImageGeom) -> dict[str, QPointF]:
        rect = self._overlay_rect(geom)
        if rect.isEmpty():
            return {}
        return {
            "tl": QPointF(rect.left(), rect.top()),
            "tr": QPointF(rect.right(), rect.top()),
            "bl": QPointF(rect.left(), rect.bottom()),
            "br": QPointF(rect.right(), rect.bottom()),
        }

    def _hit_overlay(self, p: QPointF) -> int:
        # Topmost-first: later overlays render on top, so iterate in reverse.
        for i in range(len(self._overlays) - 1, -1, -1):
            if self._overlay_rect(self._overlays[i]).contains(p):
                return i
        return -1

    def _hit_handle(self, geom: ImageGeom, p: QPointF) -> str:
        for name, c in self._handle_centers(geom).items():
            if abs(p.x() - c.x()) <= _HANDLE_HIT and abs(p.y() - c.y()) <= _HANDLE_HIT:
                return name
        return ""

    # -- mouse ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        p = event.position()
        # Corner handles only respond for the already-selected overlay.
        if 0 <= self._selected < len(self._overlays):
            geom = self._overlays[self._selected]
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drag.mode:
            self._drag = _DragState()
            self._release_mouse()
            self._update_hover(event.position())
            self.dragFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_hover(self, p: QPointF) -> None:
        if 0 <= self._selected < len(self._overlays):
            handle = self._hit_handle(self._overlays[self._selected], p)
            if handle in ("tl", "br"):
                self.setCursor(Qt.SizeFDiagCursor)
                return
            if handle in ("tr", "bl"):
                self.setCursor(Qt.SizeBDiagCursor)
                return
        if self._hit_overlay(p) != -1:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()

    # -- gesture starters ---------------------------------------------

    def _begin_move(self, index: int, p: QPointF) -> None:
        geom = self._overlays[index]
        c = self._norm_to_widget(geom.x, geom.y)
        self._drag = _DragState(index=index, mode="move", grab_offset=p - c)
        self.setCursor(Qt.SizeAllCursor)
        self._grab_mouse()

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
        self._grab_mouse()

    def _grab_mouse(self) -> None:
        # The topmost sibling (TextOverlay) receives the initial press and holds
        # the implicit mouse grab; without an explicit grab here the follow-up
        # move/release events never reach this widget and drag/resize appear
        # dead. Take the grab for the duration of the gesture.
        if QWidget.mouseGrabber() is not self:
            self.grabMouse()

    def _release_mouse(self) -> None:
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

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

    def hideEvent(self, event) -> None:  # noqa: ANN001
        # Never leave the app stuck with mouse capture if we are hidden mid-drag.
        self._drag = _DragState()
        self._release_mouse()
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
        rect = self._overlay_rect(self._overlays[self._selected])
        if rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = QPen(QColor(_ACCENT))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        painter.setPen(QPen(QColor(_ACCENT_ON), 1))
        painter.setBrush(QColor(_ACCENT))
        for c in self._handle_centers(self._overlays[self._selected]).values():
            painter.drawRect(QRectF(
                c.x() - _HANDLE_SIZE / 2, c.y() - _HANDLE_SIZE / 2,
                _HANDLE_SIZE, _HANDLE_SIZE,
            ))


def _length(p: QPointF) -> float:
    return math.sqrt(p.x() * p.x() + p.y() * p.y())
