"""Pillow-based meme rendering for still images.

Two styles:

* ``classic`` — top and bottom text burned onto the image in white with a
  black stroke, Impact-style.
* ``modern`` — a white band is added above the image and the caption is
  written in plain black text inside it.

Both entrypoints return a fresh :class:`PIL.Image.Image` and never mutate
the source; the caller decides whether to save or show it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Style = Literal["classic", "modern"]


RGB = tuple[int, int, int]


@dataclass
class MemeSpec:
    style: Style = "classic"
    top: str = ""
    bottom: str = ""
    caption: str = ""
    font_path: Path | None = None
    # As a fraction of image height. Keeps text readable across resolutions.
    font_scale: float = 0.085
    # Stroke thickness as a fraction of font size (classic only).
    stroke_ratio: float = 0.08
    # Modern-only: white band height as a fraction of image height.
    padding_scale: float = 0.22
    # Per-element colours.
    top_color: RGB = (255, 255, 255)
    bottom_color: RGB = (255, 255, 255)
    stroke_color: RGB = (0, 0, 0)
    caption_color: RGB = (0, 0, 0)
    background_color: RGB = (255, 255, 255)
    # Classic uppercasing (off = respect original case).
    uppercase: bool = True
    # Horizontal side margin as a fraction of width.
    side_margin: float = 0.04
    # Optional draggable anchors for classic text. Normalised (cx, cy) where
    # (0.5, 0.5) is the image centre. None means "use the default top / bottom
    # placement" so callers that don't care about dragging keep working.
    top_pos: tuple[float, float] | None = None
    bottom_pos: tuple[float, float] | None = None
    # Per-block size override expressed as font-size % of image height.
    # None falls back to ``font_scale * 100``.
    top_size_pct: float | None = None
    bottom_size_pct: float | None = None
    # Clockwise rotation in degrees applied around the block centre.
    top_rotation: float = 0.0
    bottom_rotation: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render(source: Image.Image | Path, spec: MemeSpec) -> Image.Image:
    img = _load(source).convert("RGB")
    if spec.style == "classic":
        return _render_classic(img, spec)
    return _render_modern(img, spec)


def render_to_file(source: Image.Image | Path, spec: MemeSpec, out: Path) -> Path:
    img = render(source, spec)
    suffix = out.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        img.save(out, quality=92, optimize=True)
    elif suffix == ".webp":
        img.save(out, quality=92, method=6)
    else:
        img.save(out, optimize=True)
    return out


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _load(source: Image.Image | Path) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.copy()
    return Image.open(source)


def _font(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _block_font_size(h: int, spec: MemeSpec, which: Literal["top", "bottom"]) -> int:
    pct = spec.top_size_pct if which == "top" else spec.bottom_size_pct
    if pct is not None:
        return max(8, int(h * pct / 100.0))
    return max(12, int(h * spec.font_scale))


def _block_rotation(spec: MemeSpec, which: Literal["top", "bottom"]) -> float:
    return spec.top_rotation if which == "top" else spec.bottom_rotation


def _render_classic(img: Image.Image, spec: MemeSpec) -> Image.Image:
    if not spec.top and not spec.bottom:
        return img.copy()
    canvas = img.convert("RGBA")
    for which in ("top", "bottom"):
        text = spec.top if which == "top" else spec.bottom
        if not text.strip():
            continue
        fill = spec.top_color if which == "top" else spec.bottom_color
        block = _render_classic_block(canvas.size, spec, which, text, fill)
        if block is None:
            continue
        layer, cx, cy = block
        rot = _block_rotation(spec, which)
        if rot:
            # PIL rotates CCW for positive angles; pass -rot for clockwise.
            layer = layer.rotate(-rot, resample=Image.BICUBIC, expand=True)
        paste_x = int(round(cx - layer.width / 2))
        paste_y = int(round(cy - layer.height / 2))
        canvas.alpha_composite(layer, (paste_x, paste_y))
    return canvas.convert("RGB")


def _render_classic_block(
    img_size: tuple[int, int],
    spec: MemeSpec,
    which: Literal["top", "bottom"],
    text: str,
    fill: RGB,
) -> tuple[Image.Image, float, float] | None:
    """Render one classic text block to a transparent RGBA layer.

    Returns ``(layer, cx, cy)`` where ``cx, cy`` is the block centre in
    source pixel coords. The layer is unrotated; callers rotate it if
    ``spec`` calls for a non-zero rotation.
    """
    w, h = img_size
    font_size = _block_font_size(h, spec, which)
    font = _font(spec.font_path, font_size)
    stroke = 0 if spec.stroke_ratio == 0.0 else max(1, int(font_size * spec.stroke_ratio))
    max_width = int(w * (1.0 - 2 * spec.side_margin))
    xform = str.upper if spec.uppercase else (lambda s: s)

    measurer = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap(xform(text), font, max_width, measurer)
    if not lines:
        return None
    line_h = _line_height(font)
    gap = max(2, line_h // 10)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    block_w = max(_text_width(measurer, line, font) for line in lines)

    pad = stroke + 2
    layer = Image.new("RGBA", (block_w + 2 * pad, block_h + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    y = pad
    fill_rgba = (*fill, 255)
    stroke_rgba = (*spec.stroke_color, 255)
    for line in lines:
        tw = _text_width(draw, line, font)
        x = pad + (block_w - tw) // 2
        draw.text(
            (x, y), line,
            fill=fill_rgba, font=font,
            stroke_width=stroke, stroke_fill=stroke_rgba,
        )
        y += line_h + gap

    cx, cy = _classic_block_centre((w, h), spec, which, block_w, block_h, stroke)
    return layer, cx, cy


def _classic_block_centre(
    img_size: tuple[int, int],
    spec: MemeSpec,
    which: Literal["top", "bottom"],
    block_w: int,
    block_h: int,
    stroke: int,
) -> tuple[float, float]:
    w, h = img_size
    pos = spec.top_pos if which == "top" else spec.bottom_pos
    margin = int(h * 0.02) + stroke
    rot = _block_rotation(spec, which)
    if pos is not None:
        cx = max(0.0, min(1.0, pos[0])) * w
        cy = max(0.0, min(1.0, pos[1])) * h
        if not rot:
            # Keep the unrotated block fully inside the image. Skipped when
            # rotated because the bbox shape changes mid-rotation and clamping
            # makes the drag feel jittery.
            cx = max(margin + block_w / 2, min(w - margin - block_w / 2, cx))
            cy = max(margin + block_h / 2, min(h - margin - block_h / 2, cy))
        return cx, cy
    if which == "top":
        return w / 2, margin + block_h / 2
    return w / 2, h - margin - block_h / 2


def _render_modern(img: Image.Image, spec: MemeSpec) -> Image.Image:
    w, h = img.size
    if not spec.caption.strip():
        return img.copy()

    font_size = max(12, int(h * spec.font_scale))
    font = _font(spec.font_path, font_size)
    max_width = int(w * (1.0 - 2 * spec.side_margin))

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap(spec.caption, font, max_width, measurer)
    line_h = _line_height(font)
    gap = max(2, font_size // 8)
    text_block_h = len(lines) * line_h + (len(lines) - 1) * gap
    min_band = max(int(h * spec.padding_scale), text_block_h + int(font_size * 1.2))

    canvas = Image.new("RGB", (w, h + min_band), spec.background_color)
    canvas.paste(img, (0, min_band))

    draw = ImageDraw.Draw(canvas)
    y = (min_band - text_block_h) // 2
    for line in lines:
        tw = _text_width(draw, line, font)
        draw.text(
            ((w - tw) // 2, y),
            line,
            fill=spec.caption_color,
            font=font,
        )
        y += line_h + gap
    return canvas


def classic_block_geometry(
    img_size: tuple[int, int],
    spec: MemeSpec,
    which: Literal["top", "bottom"],
) -> tuple[float, float, int, int, float] | None:
    """Return ``(cx, cy, block_w, block_h, rotation_deg)`` for a classic text
    block, in source image pixel coords. ``cx, cy`` is the block centre.
    ``rotation_deg`` is clockwise. Returns ``None`` if the block has no text.

    The bounding box is unrotated; callers that need the rotated polygon
    apply the rotation transform themselves around ``(cx, cy)``.
    """
    text = spec.top if which == "top" else spec.bottom
    if not text.strip():
        return None
    w, h = img_size
    font_size = _block_font_size(h, spec, which)
    font = _font(spec.font_path, font_size)
    stroke = 0 if spec.stroke_ratio == 0.0 else max(1, int(font_size * spec.stroke_ratio))
    max_width = int(w * (1.0 - 2 * spec.side_margin))
    xform = str.upper if spec.uppercase else (lambda s: s)

    measurer = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap(xform(text), font, max_width, measurer)
    if not lines:
        return None
    line_h = _line_height(font)
    gap = max(2, line_h // 10)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    block_w = max(_text_width(measurer, line, font) for line in lines)

    pad = max(4, stroke)
    cx, cy = _classic_block_centre((w, h), spec, which, block_w, block_h, stroke)
    rot = _block_rotation(spec, which)
    return cx, cy, block_w + 2 * pad, block_h + 2 * pad, rot


def _wrap(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Greedy word wrap. Preserves explicit newlines from the user."""
    result: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if _text_width(draw, trial, font) <= max_width:
                current = trial
            else:
                result.append(current)
                current = word
        result.append(current)
    return result


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _line_height(font: ImageFont.ImageFont) -> int:
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except AttributeError:
        # Bitmap fallback font
        bbox = font.getbbox("Ag")  # type: ignore[attr-defined]
        return bbox[3] - bbox[1]
