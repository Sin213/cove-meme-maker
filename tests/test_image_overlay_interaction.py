"""Interaction regression tests for the desktop image-overlay widget.

Covers the transform gestures (move / resize / rotate) and the lightweight
hit-test predicates the host's event-filter router relies on
(``is_dragging`` / ``wants_press`` / ``cursor_for``).

The image overlay sits *beneath* the topmost text overlay in the real app, so
hover and in-flight drag moves reach it via an event filter on the text overlay
rather than a ``QWidget.grabMouse()`` (unsupported for non-popups on Wayland).
These tests deliver real ``QMouseEvent``s straight to a standalone
``ImageOverlay`` (which is therefore itself topmost) so its own mouse-event
path is exercised; the nested routing is covered by live validation.
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

from cove_meme_maker.image_overlay import (  # noqa: E402
    _ROTATE_OFFSET,
    ImageGeom,
    ImageOverlay,
)

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
        self.rotated = []
        self.selected = []
        self.ov.overlayMoved.connect(lambda i, x, y: self.moved.append((i, x, y)))
        self.ov.overlayResized.connect(lambda i, w: self.resized.append((i, w)))
        self.ov.overlayRotated.connect(lambda i, d: self.rotated.append((i, d)))
        self.ov.overlaySelected.connect(lambda i: self.selected.append(i))

    def tearDown(self):
        self.ov.deleteLater()
        QApplication.processEvents()

    def _rotate_handle(self):
        rect = self.ov._overlay_rect(self.ov._overlays[0])
        return (rect.center().x(), rect.top() - _ROTATE_OFFSET)

    # -- move / resize (unchanged gestures) ----------------------------

    def test_body_drag_moves_overlay(self):
        _press(self.ov, (200, 150))
        self.assertTrue(self.ov.is_dragging(), "body press starts a gesture")
        _move(self.ov, (260, 180))
        _move(self.ov, (280, 200))
        _release(self.ov, (280, 200))
        self.assertTrue(self.moved, "overlayMoved should fire during a body drag")
        i, x, y = self.moved[-1]
        self.assertEqual(i, 0)
        self.assertGreater(x, 0.5)  # moved right
        self.assertGreater(y, 0.5)  # moved down
        self.assertFalse(self.ov.is_dragging(), "gesture ends on mouse up")

    def test_corner_resize_grows_and_respects_min(self):
        # SE handle at (300, 250).
        _press(self.ov, (300, 250))
        self.assertTrue(self.ov.is_dragging())
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
        corners = {
            "tl": (100, 50), "tr": (300, 50),
            "bl": (100, 250), "br": (300, 250),
        }
        for name, (hx, hy) in corners.items():
            self.ov.set_overlays([ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0)], 0)
            self.resized.clear()
            _press(self.ov, (hx, hy))
            self.assertTrue(self.ov.is_dragging(), f"{name} must start a gesture")
            out_x = hx + (-40 if hx < 200 else 40)
            out_y = hy + (-40 if hy < 150 else 40)
            _move(self.ov, (out_x, out_y))
            _release(self.ov, (out_x, out_y))
            self.assertTrue(self.resized, f"{name} handle should resize")
            self.assertGreater(self.resized[-1][1], 0.5, f"{name} should grow")

    # -- rotation ------------------------------------------------------

    def test_rotate_handle_press_enters_rotate_not_move(self):
        rx, ry = self._rotate_handle()
        _press(self.ov, (rx, ry))
        self.assertTrue(self.ov.is_dragging(), "rotate handle press starts a gesture")
        # Drag the handle clockwise (to the right of centre).
        _move(self.ov, (rx + 40, ry))
        _release(self.ov, (rx + 40, ry))
        self.assertTrue(self.rotated, "overlayRotated should fire")
        self.assertFalse(self.moved, "rotation must not move the overlay")
        self.assertFalse(self.resized, "rotation must not resize the overlay")
        i, deg = self.rotated[-1]
        self.assertEqual(i, 0)
        self.assertGreater(deg, 0.0, "dragging the handle rightward rotates clockwise")
        self.assertFalse(self.ov.is_dragging(), "gesture ends on mouse up")

    def test_rotate_opposite_direction_is_negative(self):
        rx, ry = self._rotate_handle()
        _press(self.ov, (rx, ry))
        _move(self.ov, (rx - 40, ry))  # to the left of centre
        _release(self.ov, (rx - 40, ry))
        self.assertTrue(self.rotated)
        self.assertLess(self.rotated[-1][1], 0.0, "leftward drag rotates anticlockwise")

    def test_rotate_handle_has_priority_over_body(self):
        # A press at the rotate handle must never be interpreted as a body move.
        rx, ry = self._rotate_handle()
        self.assertTrue(self.ov.wants_press(QPointF(rx, ry)))
        _press(self.ov, (rx, ry))
        _move(self.ov, (rx + 20, ry + 5))
        _release(self.ov, (rx + 20, ry + 5))
        self.assertTrue(self.rotated)
        self.assertFalse(self.moved)

    def test_corner_handle_still_resizes_not_rotates(self):
        _press(self.ov, (300, 250))
        _move(self.ov, (340, 290))
        _release(self.ov, (340, 290))
        self.assertTrue(self.resized, "corner still resizes")
        self.assertFalse(self.rotated, "corner does not rotate")
        self.assertFalse(self.moved, "corner does not move")

    def test_rotate_handle_moves_with_rotation(self):
        # With rotation applied the handle is carried around the pivot, so it is
        # no longer at the unrotated top-centre position.
        self.ov.set_overlays(
            [ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0, rotation=90.0)], 0
        )
        geom = self.ov._overlays[0]
        rect = self.ov._overlay_rect(geom)
        rh = self.ov._rotate_handle(geom)
        unrotated = QPointF(rect.center().x(), rect.top() - _ROTATE_OFFSET)
        self.assertGreater((rh - unrotated).manhattanLength(), 1.0)
        # It stays at the pivot distance (offset + half height) from the centre.
        expected = rect.height() / 2 + _ROTATE_OFFSET
        actual = (rh - rect.center()).manhattanLength()
        self.assertAlmostEqual(actual, expected, delta=2.0)

    # -- selection / hit predicates (used by the host router) ----------

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
        self.assertFalse(self.ov.is_dragging(), "empty press must not start a gesture")
        _move(self.ov, (60, 60))
        _release(self.ov, (60, 60))
        self.assertFalse(self.moved, "empty-space press must not move an overlay")

    def test_wants_press_matches_interactive_regions(self):
        rx, ry = self._rotate_handle()
        self.assertTrue(self.ov.wants_press(QPointF(rx, ry)), "rotate handle")
        self.assertTrue(self.ov.wants_press(QPointF(300, 250)), "corner handle")
        self.assertTrue(self.ov.wants_press(QPointF(200, 150)), "body")
        self.assertFalse(self.ov.wants_press(QPointF(5, 5)), "empty space")

    def test_cursor_for_reflects_region(self):
        rx, ry = self._rotate_handle()
        self.assertEqual(self.ov.cursor_for(QPointF(rx, ry)), Qt.CrossCursor)
        self.assertEqual(self.ov.cursor_for(QPointF(300, 250)), Qt.SizeFDiagCursor)
        self.assertEqual(self.ov.cursor_for(QPointF(200, 150)), Qt.SizeAllCursor)
        self.assertIsNone(self.ov.cursor_for(QPointF(5, 5)), "empty space -> no cursor")

    def test_cursor_for_ignores_handles_when_not_selected(self):
        # Handles/rotate only respond for the selected overlay.
        self.ov.set_overlays([ImageGeom(x=0.5, y=0.5, width=0.5, aspect=1.0)], -1)
        rx, ry = self._rotate_handle()
        self.assertIsNone(self.ov.cursor_for(QPointF(rx, ry)))
        # ...but hovering the body still offers the move cursor for selection.
        self.assertEqual(self.ov.cursor_for(QPointF(200, 150)), Qt.SizeAllCursor)


if __name__ == "__main__":
    unittest.main()
