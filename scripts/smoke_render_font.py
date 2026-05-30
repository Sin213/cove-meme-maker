"""Render smoke: bundled font fallback + style rendering.

Run:
    PYTHONPATH=src python scripts/smoke_render_font.py
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cove_meme_maker import image_renderer as r
from cove_meme_maker.image_renderer import MemeSpec


def _gradient(w: int = 400, h: int = 300) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // w, y * 255 // h, 128)
    return img


def _is_blank(img: Image.Image) -> bool:
    return all(lo == hi for lo, hi in img.convert("RGB").getextrema())


def test_bundled_file_exists():
    font_path = getattr(r, "_BUNDLED_FONT", None)
    assert font_path is not None, "_BUNDLED_FONT not defined in image_renderer"
    assert font_path.exists(), f"Bundled font missing: {font_path}"
    print(f"  bundled font: {font_path}")


def test_bundled_fallback_path():
    """_font must resolve to bundled DejaVuSans-Bold when requested fonts are missing."""
    font = r._font(("DefinitelyMissingFont-Smoke.ttf",), 48, None)
    path = str(getattr(font, "path", ""))
    assert "DejaVuSans-Bold.ttf" in path, f"Expected DejaVuSans-Bold.ttf in path, got: {path!r}"
    assert "assets" in path and "fonts" in path, f"Expected bundled assets/fonts path, got: {path!r}"
    print(f"  fallback font path: {path}")


def test_classic_render():
    src = _gradient()
    spec = MemeSpec(
        style="classic",
        top="TOP TEXT",
        bottom="BOTTOM TEXT",
        top_font_names=("DefinitelyMissingFont-Smoke.ttf",),
        bottom_font_names=("DefinitelyMissingFont-Smoke.ttf",),
    )
    out = r.render(src, spec)
    assert out.width > 0 and out.height > 0, f"Zero dimension: {out.size}"
    assert not _is_blank(out), "classic render produced blank image"
    print(f"  classic render OK: {out.size}")


def test_modern_render():
    src = _gradient()
    spec = MemeSpec(
        style="modern",
        caption="Modern caption fallback test",
    )
    out = r.render(src, spec)
    assert out.width > 0 and out.height > 0, f"Zero dimension: {out.size}"
    assert not _is_blank(out), "modern render produced blank image"
    print(f"  modern render OK: {out.size}")


if __name__ == "__main__":
    tests = [
        test_bundled_file_exists,
        test_bundled_fallback_path,
        test_classic_render,
        test_modern_render,
    ]
    failures = []
    for t in tests:
        print(f"[RUN] {t.__name__}")
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")
