"""Unit tests for image-overlay compositing in the shared Pillow renderer."""
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from cove_meme_maker.image_renderer import MemeSpec, OverlaySpec, render  # noqa: E402


def _solid(w: int, h: int, color, mode: str = "RGB") -> Image.Image:
    return Image.new(mode, (w, h), color)


class ZeroOverlayRegressionTest(unittest.TestCase):
    def test_empty_overlays_match_no_overlays_classic(self):
        base = _solid(160, 120, (30, 90, 200))
        spec = MemeSpec(style="classic", top="Hello", bottom="World")
        existing = render(base, spec)
        empty = render(base, replace(spec, overlays=()))
        self.assertEqual(existing.tobytes(), empty.tobytes())

    def test_empty_overlays_match_no_overlays_modern(self):
        base = _solid(160, 120, (30, 90, 200))
        spec = MemeSpec(style="modern", caption="A caption here")
        existing = render(base, spec)
        empty = render(base, replace(spec, overlays=()))
        self.assertEqual(existing.tobytes(), empty.tobytes())


class TransparentOverlayTest(unittest.TestCase):
    def test_semitransparent_overlay_blends_center(self):
        base = _solid(100, 100, (255, 0, 0))
        overlay_img = _solid(40, 40, (0, 255, 0, 128), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.4),),
        )
        out = render(base, spec)
        cr, cg, cb = out.getpixel((50, 50))
        # ~50% green over red: red channel drops, green rises, blue stays 0.
        self.assertLess(cr, 200)
        self.assertGreater(cg, 90)
        self.assertEqual(cb, 0)
        # A corner well outside the overlay stays pure red.
        self.assertEqual(out.getpixel((2, 2)), (255, 0, 0))

    def test_fully_transparent_overlay_leaves_base_unchanged(self):
        base = _solid(80, 80, (10, 20, 30))
        overlay_img = _solid(40, 40, (255, 255, 255, 0), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.5),),
        )
        out = render(base, spec)
        self.assertEqual(out.tobytes(), render(base, MemeSpec(style="classic")).tobytes())


class ZOrderTest(unittest.TestCase):
    def test_later_overlay_wins_at_overlap(self):
        base = _solid(100, 100, (255, 255, 255))
        red = _solid(40, 40, (255, 0, 0, 255), mode="RGBA")
        blue = _solid(40, 40, (0, 0, 255, 255), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(
                OverlaySpec(image=red, x=0.5, y=0.5, width=0.4),
                OverlaySpec(image=blue, x=0.5, y=0.5, width=0.4),
            ),
        )
        out = render(base, spec)
        self.assertEqual(out.getpixel((50, 50)), (0, 0, 255))


class PartialClipTest(unittest.TestCase):
    def test_overlay_partly_off_top_left_edge(self):
        base = _solid(100, 100, (255, 255, 255))
        green = _solid(40, 40, (0, 200, 0, 255), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=green, x=0.0, y=0.0, width=0.4),),
        )
        out = render(base, spec)
        self.assertEqual(out.size, (100, 100))
        # Center of the overlay is off-canvas; its visible quadrant sits at (0,0).
        self.assertEqual(out.getpixel((2, 2)), (0, 200, 0))
        # Far corner is untouched base.
        self.assertEqual(out.getpixel((99, 99)), (255, 255, 255))


class FullyOffCanvasTest(unittest.TestCase):
    def test_off_canvas_overlay_matches_no_overlay(self):
        base = _solid(100, 100, (123, 45, 67))
        green = _solid(40, 40, (0, 200, 0, 255), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=green, x=5.0, y=5.0, width=0.4),),
        )
        out = render(base, spec)
        self.assertEqual(out.tobytes(), render(base, MemeSpec(style="classic")).tobytes())


class AspectRatioTest(unittest.TestCase):
    def test_non_square_overlay_preserves_source_aspect(self):
        base = _solid(200, 200, (255, 255, 255))
        # Source 40x20 -> aspect (h/w) 0.5.
        overlay_img = _solid(40, 20, (255, 0, 255, 255), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.5),),
        )
        out = render(base, spec)
        xs, ys = [], []
        for y in range(200):
            for x in range(200):
                if out.getpixel((x, y)) == (255, 0, 255):
                    xs.append(x)
                    ys.append(y)
        self.assertTrue(xs and ys)
        w = max(xs) - min(xs) + 1
        h = max(ys) - min(ys) + 1
        # width = 0.5 * 200 = 100; height = 100 * 0.5 = 50.
        self.assertAlmostEqual(w, 100, delta=2)
        self.assertAlmostEqual(h, 50, delta=2)


class ClassicPlacementTest(unittest.TestCase):
    def test_overlay_appears_at_base_center(self):
        base = _solid(120, 120, (255, 255, 255))
        overlay_img = _solid(30, 30, (10, 60, 220, 255), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.3),),
        )
        out = render(base, spec)
        self.assertEqual(out.size, (120, 120))
        self.assertEqual(out.getpixel((60, 60)), (10, 60, 220))


class ModernPlacementTest(unittest.TestCase):
    def test_overlay_offset_by_caption_band_not_into_band(self):
        base = _solid(100, 100, (255, 255, 255))
        overlay_img = _solid(30, 30, (200, 30, 30, 255), mode="RGBA")
        plain = MemeSpec(style="modern", caption="Caption")
        empty_out = render(base, plain)
        out = render(
            base,
            replace(
                plain,
                overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.3),),
            ),
        )
        self.assertEqual(out.size, empty_out.size)
        band_offset = out.height - 100
        self.assertGreater(band_offset, 0)
        # Overlay centered in the base region.
        self.assertEqual(out.getpixel((50, band_offset + 50)), (200, 30, 30))
        # Nothing painted into the caption band above the base region.
        self.assertNotEqual(out.getpixel((50, band_offset // 2)), (200, 30, 30))


class ExportTest(unittest.TestCase):
    def test_png_and_jpg_export_roundtrip(self):
        base = _solid(100, 80, (40, 40, 40))
        overlay_img = _solid(30, 30, (0, 255, 0, 200), mode="RGBA")
        spec = MemeSpec(
            style="classic",
            overlays=(OverlaySpec(image=overlay_img, x=0.5, y=0.5, width=0.3),),
        )
        out = render(base, spec)
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "out.png"
            jpg = Path(d) / "out.jpg"
            out.save(png)
            out.convert("RGB").save(jpg)
            with Image.open(png) as reopened_png:
                self.assertEqual(reopened_png.size, (100, 80))
            with Image.open(jpg) as reopened_jpg:
                self.assertEqual(reopened_jpg.size, (100, 80))
                self.assertEqual(reopened_jpg.convert("RGB").mode, "RGB")


if __name__ == "__main__":
    unittest.main()
