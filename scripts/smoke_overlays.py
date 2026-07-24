"""Overlay smoke: shared Pillow compositing for still-image memes.

Run:
    PYTHONPATH=src python scripts/smoke_overlays.py

No network. No GUI. No external image files.
"""
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cove_meme_maker.image_renderer import MemeSpec, OverlaySpec, render


def _base(w: int = 400, h: int = 300, color=(40, 40, 40)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _overlay(w: int, h: int, color) -> Image.Image:
    return Image.new("RGBA", (w, h), color)


def _is_blank(img: Image.Image) -> bool:
    extrema = img.convert("RGB").getextrema()
    return all(lo == hi for lo, hi in extrema)


def test_dimensions_classic_modern():
    base = _base()
    overlays = (
        OverlaySpec(image=_overlay(60, 60, (255, 0, 0, 255)), x=0.5, y=0.5, width=0.3),
    )
    classic = render(base, MemeSpec(style="classic", overlays=overlays))
    assert classic.size == (400, 300), classic.size
    plain_modern = render(base, MemeSpec(style="modern", caption="Smoke caption"))
    modern = render(
        base, MemeSpec(style="modern", caption="Smoke caption", overlays=overlays)
    )
    assert modern.size == plain_modern.size, (modern.size, plain_modern.size)
    assert modern.height > base.height, modern.height
    print("  ok: classic/modern dimensions")


def test_transparent_compositing():
    base = _base(100, 100, (255, 0, 0))
    ov = _overlay(40, 40, (0, 255, 0, 128))
    out = render(base, MemeSpec(overlays=(OverlaySpec(image=ov, x=0.5, y=0.5, width=0.5),)))
    r, g, b = out.getpixel((50, 50))
    assert r < 255 and g > 0 and b == 0, (r, g, b)
    assert out.getpixel((2, 2)) == (255, 0, 0)
    print("  ok: transparent compositing blends")


def test_z_order():
    base = _base(100, 100, (255, 255, 255))
    red = _overlay(40, 40, (255, 0, 0, 255))
    blue = _overlay(40, 40, (0, 0, 255, 255))
    out = render(base, MemeSpec(overlays=(
        OverlaySpec(image=red, x=0.5, y=0.5, width=0.4),
        OverlaySpec(image=blue, x=0.5, y=0.5, width=0.4),
    )))
    assert out.getpixel((50, 50)) == (0, 0, 255), out.getpixel((50, 50))
    print("  ok: later overlay wins z-order")


def test_partial_clipping():
    base = _base(100, 100, (255, 255, 255))
    green = _overlay(40, 40, (0, 200, 0, 255))
    out = render(base, MemeSpec(overlays=(OverlaySpec(image=green, x=0.0, y=0.0, width=0.4),)))
    assert out.size == (100, 100)
    assert out.getpixel((2, 2)) == (0, 200, 0), out.getpixel((2, 2))
    assert out.getpixel((99, 99)) == (255, 255, 255)
    print("  ok: partial clipping")


def test_not_blank():
    base = _base(200, 200, (10, 10, 10))
    ov = _overlay(80, 80, (255, 255, 0, 255))
    out = render(base, MemeSpec(overlays=(OverlaySpec(image=ov, x=0.5, y=0.5, width=0.5),)))
    assert not _is_blank(out)
    print("  ok: output not blank")


def test_many_overlays_timing():
    base = _base(2000, 2000, (20, 20, 20))
    overlays = []
    for i in range(10):
        c = (i * 25 % 256, (i * 55) % 256, (i * 90) % 256, 200)
        overlays.append(
            OverlaySpec(image=_overlay(300, 200, c), x=0.1 + 0.08 * i, y=0.5, width=0.2)
        )
    t0 = time.perf_counter()
    out = render(base, MemeSpec(overlays=tuple(overlays)))
    dt = time.perf_counter() - t0
    assert out.size == (2000, 2000)
    assert not _is_blank(out)
    print(f"  ok: ~10 overlays on 2000x2000 rendered in {dt * 1000:.1f} ms")


def main() -> None:
    print("Overlay smoke:")
    test_dimensions_classic_modern()
    test_transparent_compositing()
    test_z_order()
    test_partial_clipping()
    test_not_blank()
    test_many_overlays_timing()
    print("SMOKE OK: overlay compositing works")


if __name__ == "__main__":
    main()
