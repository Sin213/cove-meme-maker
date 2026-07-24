"""Interaction regression tests for the desktop image-overlay widget.

Reproduces the live-GUI bug where a selected overlay could not be dragged or
resized: the widget handled the (propagated) press and set its drag state, but
never received the follow-up move events because the topmost sibling held the
implicit mouse grab. The fix is an explicit mouse grab for the duration of a
drag/resize gesture.

These deliver real ``QMouseEvent``s to ``ImageOverlay`` so its mouse-event path
(``mousePressEvent`` / ``mouseMoveEvent`` / ``mouseReleaseEvent``) is exercised,
not the app's signal handlers. The mouse-grab assertions pin the root cause;
full nested-window routing must still be confirmed in a real window.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from cove_meme_maker.image_overlay import ImageGeom, ImageOverlay  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _send(widget, etype, pos, button=Qt.LeftButton, buttons=Qt.LeftButton):
    p = QPointF(float(pos[0]), float(pos[1]))
    ev = QMouseEvent(etype, p, p, button, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)
    QApplication.processEvents()


def _press(w, pos):
    _send(w, QEvent.Type.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton)


def _move(w, pos):
    _send(w, QEvent.Type.MouseMove, pos, Qt.NoButton, Qt.LeftButton)


def _release(w, pos):
    _send(w, QEvent.Type.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton)


class ImageOverlayInteractionTest(unittest.TestCase):
    def setUp(self):
        # Base region == full widget for straightforward coordinates.
        self.ov = ImageOverlay()
        self.ov.resize(400, 300)
        self.ov.set_base_rect(QRectF(0, 0, 400, 300))
        self.ov.set_base_size((400, 300))
        # One overlay centered, width 0.5 -> 200px sq, widget rect (100,50,200,200).
        self.ov.set_overlays([ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0)], 0)
        self.ov.show()
        QApplication.processEvents()
        self.moved = []
        self.resized = []
        self.selected = []
        self.ov.overlayMoved.connect(lambda i, x, y: self.moved.append((i, x, y)))
        self.ov.overlayResized.connect(lambda i, w: self.resized.append((i, w)))
        self.ov.overlaySelected.connect(lambda i: self.selected.append(i))

    def tearDown(self):
        if QWidget.mouseGrabber() is self.ov:
            self.ov.releaseMouse()
        self.ov.deleteLater()
        QApplication.processEvents()

    def test_body_drag_moves_overlay(self):
        _press(self.ov, (200, 150))
        # Root cause: the widget must own the mouse grab so it keeps receiving
        # moves even though a sibling sits on top at the press point.
        self.assertIs(QWidget.mouseGrabber(), self.ov)
        _move(self.ov, (260, 180))
        _move(self.ov, (280, 200))
        _release(self.ov, (280, 200))
        self.assertTrue(self.moved, "overlayMoved should fire during a body drag")
        i, x, y = self.moved[-1]
        self.assertEqual(i, 0)
        self.assertGreater(x, 0.5)  # moved right
        self.assertGreater(y, 0.5)  # moved down
        self.assertIsNone(QWidget.mouseGrabber(), "grab released on mouse up")

    def test_corner_resize_grows_and_respects_min(self):
        # SE handle at (300, 250).
        _press(self.ov, (300, 250))
        self.assertIs(QWidget.mouseGrabber(), self.ov)
        _move(self.ov, (350, 300))  # outward from centre
        _release(self.ov, (350, 300))
        self.assertTrue(self.resized, "overlayResized should fire during a resize")
        self.assertGreater(self.resized[-1][1], 0.5, "width should grow")

        # Now shrink hard toward the centre; min width = 12/400 = 0.03.
        self.resized.clear()
        _press(self.ov, (300, 250))
        _move(self.ov, (202, 152))  # almost at centre -> below minimum
        _release(self.ov, (202, 152))
        self.assertTrue(self.resized)
        self.assertAlmostEqual(self.resized[-1][1], 12.0 / 400, places=6)

    def test_all_four_corner_handles_resize(self):
        # Overlay rect is (100, 50, 200, 200): tl/tr/bl/br at these points.
        corners = {
            "tl": (100, 50), "tr": (300, 50),
            "bl": (100, 250), "br": (300, 250),
        }
        for name, (hx, hy) in corners.items():
            self.ov.set_overlays([ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0)], 0)
            self.resized.clear()
            _press(self.ov, (hx, hy))
            self.assertIs(QWidget.mouseGrabber(), self.ov, f"{name} must grab")
            # Drag the handle diagonally away from centre.
            out_x = hx + (-40 if hx < 200 else 40)
            out_y = hy + (-40 if hy < 150 else 40)
            _move(self.ov, (out_x, out_y))
            _release(self.ov, (out_x, out_y))
            self.assertTrue(self.resized, f"{name} handle should resize")
            self.assertGreater(self.resized[-1][1], 0.5, f"{name} should grow")

    def test_click_selects_topmost(self):
        self.ov.set_overlays(
            [
                ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0),
                ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0),
            ],
            -1,
        )
        _press(self.ov, (200, 150))
        _release(self.ov, (200, 150))
        self.assertEqual(self.selected[-1], 1, "topmost (last) overlay is selected")

    def test_empty_space_press_does_not_start_drag(self):
        _press(self.ov, (5, 5))  # outside the centered overlay
        self.assertIsNone(QWidget.mouseGrabber(), "empty press must not grab")
        _move(self.ov, (60, 60))
        _release(self.ov, (60, 60))
        self.assertFalse(self.moved, "empty-space press must not move an overlay")


if __name__ == "__main__":
    unittest.main()
