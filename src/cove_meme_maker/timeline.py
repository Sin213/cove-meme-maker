"""Lightweight dual-handle trim slider for video input.

A trimmed-down port of the cove-gif-maker ``TrimBar``: no thumbnail strip
and no playhead — the preview here is a single extracted frame, not a
playing video, so those affordances don't apply.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


HANDLE_W = 10
TRACK_PAD = HANDLE_W // 2


@dataclass
class _Drag:
    target: str  # "start", "end", or ""


class TrimBar(QWidget):
    rangeChanged = Signal(float, float)
    rangePreviewing = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(54)
        self.setMouseTracking(True)
        self._duration: float = 0.0
        self._start: float = 0.0
        self._end: float = 0.0
        self._drag = _Drag(target="")

    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        self._start = 0.0
        self._end = self._duration
        self.update()

    def clear(self) -> None:
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self.update()

    def start(self) -> float:
        return self._start

    def end(self) -> float:
        return self._end

    def duration(self) -> float:
        return self._duration

    # --- geometry -----------------------------------------------------

    def _track_rect(self) -> QRect:
        return self.rect().adjusted(TRACK_PAD, 6, -TRACK_PAD, -20)

    def _time_to_x(self, t: float) -> int:
        if self._duration <= 0:
            return self._track_rect().left()
        track = self._track_rect()
        return int(track.left() + (t / self._duration) * track.width())

    def _x_to_time(self, x: int) -> float:
        if self._duration <= 0:
            return 0.0
        track = self._track_rect()
        ratio = (x - track.left()) / max(1, track.width())
        return max(0.0, min(self._duration, ratio * self._duration))

    # --- painting -----------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1f2024"))
        track = self._track_rect()
        p.fillRect(track, QColor("#101115"))

        if self._duration > 0:
            sx = self._time_to_x(self._start)
            ex = self._time_to_x(self._end)
            # selected band
            p.fillRect(QRect(sx, track.top(), max(1, ex - sx), track.height()),
                       QColor(95, 180, 255, 60))
            # outer dim
            dim = QColor(0, 0, 0, 140)
            p.fillRect(QRect(track.left(), track.top(), sx - track.left(), track.height()), dim)
            p.fillRect(QRect(ex, track.top(), track.right() - ex + 1, track.height()), dim)
            # border
            sel_pen = QPen(QColor("#5fb4ff"))
            sel_pen.setWidth(2)
            p.setPen(sel_pen)
            p.drawRect(QRect(sx, track.top(), max(1, ex - sx), track.height() - 1))
            # handles
            self._draw_handle(p, sx, track)
            self._draw_handle(p, ex, track)
            # labels
            p.setPen(QColor("#cfd0d4"))
            f = p.font()
            f.setPointSize(8)
            p.setFont(f)
            label_y = track.bottom() + 14
            p.drawText(QPoint(sx, label_y), _fmt_time(self._start))
            end_text = _fmt_time(self._end)
            tw = p.fontMetrics().horizontalAdvance(end_text)
            p.drawText(QPoint(min(ex, self.rect().right() - tw - 2), label_y), end_text)
        p.end()

    def _draw_handle(self, p: QPainter, x: int, track: QRect) -> None:
        rect = QRect(x - HANDLE_W // 2, track.top() - 2, HANDLE_W, track.height() + 4)
        p.fillRect(rect, QColor("#5fb4ff"))
        p.setPen(QPen(QColor("#0d1216"), 1))
        notch_x = rect.center().x()
        p.drawLine(notch_x, rect.top() + 4, notch_x, rect.bottom() - 4)

    # --- mouse --------------------------------------------------------

    def _hit_test(self, pos: QPoint) -> str:
        if self._duration <= 0:
            return ""
        sx = self._time_to_x(self._start)
        ex = self._time_to_x(self._end)
        if abs(pos.x() - sx) <= HANDLE_W:
            return "start"
        if abs(pos.x() - ex) <= HANDLE_W:
            return "end"
        return ""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._duration <= 0:
            return
        target = self._hit_test(event.position().toPoint())
        if not target:
            x = event.position().x()
            sx = self._time_to_x(self._start)
            ex = self._time_to_x(self._end)
            target = "start" if abs(x - sx) <= abs(x - ex) else "end"
        self._drag = _Drag(target=target)
        self._apply_drag(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag.target:
            self._apply_drag(event.position().x())
        else:
            cursor_target = self._hit_test(event.position().toPoint())
            if cursor_target in ("start", "end"):
                self.setCursor(Qt.SplitHCursor)
            else:
                self.unsetCursor()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag.target:
            self.rangeChanged.emit(self._start, self._end)
        self._drag = _Drag(target="")

    def _apply_drag(self, x: float) -> None:
        t = self._x_to_time(int(x))
        min_gap = max(0.05, self._duration * 0.005)
        if self._drag.target == "start":
            self._start = max(0.0, min(t, self._end - min_gap))
            self.rangePreviewing.emit(self._start, self._end)
        elif self._drag.target == "end":
            self._end = min(self._duration, max(t, self._start + min_gap))
            self.rangePreviewing.emit(self._start, self._end)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 56)


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"
