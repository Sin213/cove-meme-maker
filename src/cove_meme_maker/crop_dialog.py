from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

HANDLE_PX = 10
MIN_CROP_PX = 10

_CURSOR_FOR_HANDLE = {
    "nw": Qt.SizeFDiagCursor,
    "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor,
    "sw": Qt.SizeBDiagCursor,
    "n": Qt.SizeVerCursor,
    "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor,
    "w": Qt.SizeHorCursor,
}


class CropArea(QWidget):
    """Displays a Pillow image and lets the user drag a rectangular crop region.

    The crop rectangle is stored in source-image pixel coordinates so the
    selection survives widget resizes without rounding drift.
    """

    cropChanged = Signal(QRect)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap: QPixmap | None = None
        self._image_size: tuple[int, int] = (0, 0)
        self._crop = QRect()
        self._display_rect = QRect()
        self._drag_kind: str | None = None
        self._drag_anchor = QPoint()
        self._drag_start_crop = QRect()

    # -- public --------------------------------------------------------

    def set_image(self, image: Image.Image) -> None:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        qimg = QImage.fromData(buf.getvalue(), "PNG")
        self._pixmap = QPixmap.fromImage(qimg)
        self._image_size = (image.width, image.height)
        self._crop = QRect(0, 0, image.width, image.height)
        self._update_display_rect()
        self.update()
        self.cropChanged.emit(QRect(self._crop))

    def crop_rect(self) -> QRect:
        return QRect(self._crop)

    def reset_crop(self) -> None:
        sw, sh = self._image_size
        if sw == 0 or sh == 0:
            return
        self._crop = QRect(0, 0, sw, sh)
        self.update()
        self.cropChanged.emit(QRect(self._crop))

    # -- coordinate helpers --------------------------------------------

    def _update_display_rect(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self._display_rect = QRect()
            return
        sw, sh = self._image_size
        ww, wh = self.width(), self.height()
        if sw == 0 or sh == 0 or ww == 0 or wh == 0:
            self._display_rect = QRect()
            return
        scale = min(ww / sw, wh / sh)
        dw = max(1, int(sw * scale))
        dh = max(1, int(sh * scale))
        x = (ww - dw) // 2
        y = (wh - dh) // 2
        self._display_rect = QRect(x, y, dw, dh)

    def _src_to_widget_rect(self, r: QRect) -> QRect:
        sw, sh = self._image_size
        d = self._display_rect
        if sw == 0 or sh == 0 or d.width() == 0 or d.height() == 0:
            return QRect()
        x1 = d.x() + r.x() / sw * d.width()
        y1 = d.y() + r.y() / sh * d.height()
        x2 = d.x() + (r.x() + r.width()) / sw * d.width()
        y2 = d.y() + (r.y() + r.height()) / sh * d.height()
        return QRect(int(round(x1)), int(round(y1)),
                     int(round(x2 - x1)), int(round(y2 - y1)))

    def _handle_rects(self) -> dict[str, QRect]:
        wr = self._src_to_widget_rect(self._crop)
        if wr.isEmpty():
            return {}
        s = HANDLE_PX
        h = s // 2
        cx = wr.x() + wr.width() // 2
        cy = wr.y() + wr.height() // 2
        return {
            "nw": QRect(wr.left() - h, wr.top() - h, s, s),
            "ne": QRect(wr.right() - h, wr.top() - h, s, s),
            "sw": QRect(wr.left() - h, wr.bottom() - h, s, s),
            "se": QRect(wr.right() - h, wr.bottom() - h, s, s),
            "n": QRect(cx - h, wr.top() - h, s, s),
            "s": QRect(cx - h, wr.bottom() - h, s, s),
            "w": QRect(wr.left() - h, cy - h, s, s),
            "e": QRect(wr.right() - h, cy - h, s, s),
        }

    # -- mouse ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._pixmap is None:
            return
        p = event.position().toPoint()
        for kind, rect in self._handle_rects().items():
            if rect.contains(p):
                self._drag_kind = kind
                self._drag_anchor = p
                self._drag_start_crop = QRect(self._crop)
                return
        wr = self._src_to_widget_rect(self._crop)
        if wr.contains(p):
            self._drag_kind = "move"
            self._drag_anchor = p
            self._drag_start_crop = QRect(self._crop)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        p = event.position().toPoint()
        if self._drag_kind is None:
            self._update_hover_cursor(p)
            return
        sw, sh = self._image_size
        d = self._display_rect
        if d.width() == 0 or d.height() == 0:
            return
        scale_x = sw / d.width()
        scale_y = sh / d.height()
        dx = int(round((p.x() - self._drag_anchor.x()) * scale_x))
        dy = int(round((p.y() - self._drag_anchor.y()) * scale_y))
        sc = self._drag_start_crop
        if self._drag_kind == "move":
            new_x = max(0, min(sw - sc.width(), sc.x() + dx))
            new_y = max(0, min(sh - sc.height(), sc.y() + dy))
            self._crop = QRect(new_x, new_y, sc.width(), sc.height())
        else:
            left, top = sc.left(), sc.top()
            right = sc.left() + sc.width()
            bottom = sc.top() + sc.height()
            kind = self._drag_kind
            if "n" in kind:
                top = max(0, min(bottom - MIN_CROP_PX, top + dy))
            if "s" in kind:
                bottom = max(top + MIN_CROP_PX, min(sh, bottom + dy))
            if "w" in kind:
                left = max(0, min(right - MIN_CROP_PX, left + dx))
            if "e" in kind:
                right = max(left + MIN_CROP_PX, min(sw, right + dx))
            self._crop = QRect(left, top, right - left, bottom - top)
        self.update()
        self.cropChanged.emit(QRect(self._crop))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drag_kind is not None:
            self._drag_kind = None
            self._update_hover_cursor(event.position().toPoint())

    def _update_hover_cursor(self, p: QPoint) -> None:
        for kind, rect in self._handle_rects().items():
            if rect.contains(p):
                self.setCursor(_CURSOR_FOR_HANDLE[kind])
                return
        wr = self._src_to_widget_rect(self._crop)
        if wr.contains(p):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()

    # -- paint / resize ------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._update_display_rect()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(14, 17, 22))
        if self._pixmap is None or self._display_rect.isEmpty():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self._display_rect, self._pixmap)

        wr = self._src_to_widget_rect(self._crop)
        d = self._display_rect
        overlay = QColor(0, 0, 0, 140)
        # Dim the four bands around the crop rect (clipped to displayed image).
        if wr.top() > d.top():
            painter.fillRect(QRect(d.left(), d.top(), d.width(), wr.top() - d.top()), overlay)
        if wr.bottom() < d.bottom():
            painter.fillRect(
                QRect(d.left(), wr.bottom(), d.width(), d.bottom() - wr.bottom()),
                overlay,
            )
        if wr.left() > d.left():
            painter.fillRect(
                QRect(d.left(), wr.top(), wr.left() - d.left(), wr.height()),
                overlay,
            )
        if wr.right() < d.right():
            painter.fillRect(
                QRect(wr.right(), wr.top(), d.right() - wr.right(), wr.height()),
                overlay,
            )

        # Thirds guide.
        guide_pen = QPen(QColor(255, 255, 255, 110))
        guide_pen.setWidth(1)
        painter.setPen(guide_pen)
        for i in (1, 2):
            x = wr.left() + wr.width() * i // 3
            y = wr.top() + wr.height() * i // 3
            painter.drawLine(x, wr.top(), x, wr.bottom())
            painter.drawLine(wr.left(), y, wr.right(), y)

        # Border.
        border_pen = QPen(QColor(255, 255, 255))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(wr)

        # Handles.
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QColor(95, 180, 255))
        for rect in self._handle_rects().values():
            painter.drawRect(rect)


class CropDialog(QDialog):
    """Modal dialog that lets the user crop a Pillow image."""

    def __init__(self, image: Image.Image, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop image")
        self.resize(820, 720)
        self._source = image

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.area = CropArea()
        self.area.setMinimumSize(560, 480)
        self.area.cropChanged.connect(self._update_info)
        layout.addWidget(self.area, stretch=1)

        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        self.info_label = QLabel()
        self.info_label.setStyleSheet("color:#cfd0d4;")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Restore the crop rectangle to the full image")
        self.reset_btn.clicked.connect(self.area.reset_crop)
        info_row.addWidget(self.info_label, stretch=1)
        info_row.addWidget(self.reset_btn)
        layout.addLayout(info_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply crop")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.area.set_image(image)

    def _update_info(self, rect: QRect) -> None:
        self.info_label.setText(
            f"{rect.width()} × {rect.height()} px  ·  origin ({rect.x()}, {rect.y()})"
        )

    def cropped_image(self) -> Image.Image:
        r = self.area.crop_rect()
        left = max(0, r.x())
        top = max(0, r.y())
        right = min(self._source.width, r.x() + r.width())
        bottom = min(self._source.height, r.y() + r.height())
        if right - left < 1 or bottom - top < 1:
            return self._source
        return self._source.crop((left, top, right, bottom))
