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


def is_animated(img: Image.Image) -> bool:
    return bool(getattr(img, "is_animated", False)) and getattr(img, "n_frames", 1) > 1


def load_animation(path: Path) -> tuple[list[Image.Image], list[int]]:
    """Return (RGB frames, per-frame durations in ms). Works for animated GIF
    and animated WebP; raises for static images.
    """
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(path) as img:
        n = getattr(img, "n_frames", 1)
        for i in range(n):
            img.seek(i)
            # .convert on the open-handle frame creates a detached copy we can
            # keep after the context exits.
            frames.append(img.convert("RGB"))
            durations.append(int(img.info.get("duration", 100) or 100))
    return frames, durations


def render_sequence(frames: list[Image.Image], spec: MemeSpec) -> list[Image.Image]:
    return [render(frame, spec) for frame in frames]


def save_animation(
    frames: list[Image.Image],
    durations: list[int],
    out: Path,
    *,
    fmt: str = "gif",
    loop: int = 0,
) -> Path:
    if not frames:
        raise ValueError("no frames to save")
    fmt = fmt.lower()
    if fmt == "gif":
        # Pillow's GIF writer picks a decent adaptive palette per frame when
        # the source has alpha / mixed content, at the cost of some dithering.
        frames[0].save(
            out,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            optimize=True,
            disposal=2,
        )
    elif fmt == "webp":
        frames[0].save(
            out,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            quality=85,
            method=6,
        )
    else:
        raise ValueError(f"unsupported animation format: {fmt}")
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


def _render_classic(img: Image.Image, spec: MemeSpec) -> Image.Image:
    out = img.copy()
    if not spec.top and not spec.bottom:
        return out
    draw = ImageDraw.Draw(out)
    w, h = out.size
    font_size = max(12, int(h * spec.font_scale))
    font = _font(spec.font_path, font_size)
    stroke = max(1, int(font_size * spec.stroke_ratio))
    max_width = int(w * (1.0 - 2 * spec.side_margin))
    xform = str.upper if spec.uppercase else (lambda s: s)

    if spec.top:
        lines = _wrap(xform(spec.top), font, max_width, draw)
        _draw_block(
            draw, lines, font, w, h, stroke,
            anchor="top", pos=spec.top_pos,
            fill=spec.top_color, stroke_fill=spec.stroke_color,
        )
    if spec.bottom:
        lines = _wrap(xform(spec.bottom), font, max_width, draw)
        _draw_block(
            draw, lines, font, w, h, stroke,
            anchor="bottom", pos=spec.bottom_pos,
            fill=spec.bottom_color, stroke_fill=spec.stroke_color,
        )
    return out


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


def classic_block_rect(
    img_size: tuple[int, int],
    spec: MemeSpec,
    which: Literal["top", "bottom"],
) -> tuple[int, int, int, int] | None:
    """Pixel bounding rect (x, y, w, h) of the classic top/bottom text block,
    or ``None`` if that block has no text. Used by the preview to hit-test
    mouse drags. Returns coordinates in the source image's pixel space.
    """
    text = spec.top if which == "top" else spec.bottom
    if not text.strip():
        return None
    w, h = img_size
    font_size = max(12, int(h * spec.font_scale))
    font = _font(spec.font_path, font_size)
    stroke = max(1, int(font_size * spec.stroke_ratio))
    max_width = int(w * (1.0 - 2 * spec.side_margin))
    xform = str.upper if spec.uppercase else (lambda s: s)

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap(xform(text), font, max_width, measurer)
    if not lines:
        return None
    line_h = _line_height(font)
    gap = max(2, line_h // 10)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    block_w = max(_text_width(measurer, line, font) for line in lines)

    pos = spec.top_pos if which == "top" else spec.bottom_pos
    margin = int(h * 0.02) + stroke
    if pos is not None:
        cx = max(0.0, min(1.0, pos[0]))
        cy = max(0.0, min(1.0, pos[1]))
        y = int(cy * h - block_h / 2)
        y = max(margin, min(h - block_h - margin, y))
        x = int(cx * w - block_w / 2)
        x = max(margin, min(w - block_w - margin, x))
    elif which == "top":
        y = margin
        x = (w - block_w) // 2
    else:
        y = h - block_h - margin
        x = (w - block_w) // 2
    # Pad the hit rect a touch so the stroke edges remain grabbable.
    pad = max(4, stroke)
    return (
        max(0, x - pad),
        max(0, y - pad),
        min(w, block_w + 2 * pad),
        min(h, block_h + 2 * pad),
    )


def _draw_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    w: int,
    h: int,
    stroke: int,
    *,
    anchor: Literal["top", "bottom"],
    pos: tuple[float, float] | None = None,
    fill: RGB = (255, 255, 255),
    stroke_fill: RGB = (0, 0, 0),
) -> None:
    line_h = _line_height(font)
    gap = max(2, line_h // 10)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    margin = int(h * 0.02) + stroke
    if pos is not None:
        # Treat (cx, cy) as the centre of the rendered block.
        cy = max(0.0, min(1.0, pos[1]))
        y = int(cy * h - block_h / 2)
        y = max(margin, min(h - block_h - margin, y))
    elif anchor == "top":
        y = margin
    else:
        y = h - block_h - margin
    for line in lines:
        tw = _text_width(draw, line, font)
        if pos is not None:
            cx = max(0.0, min(1.0, pos[0]))
            x = int(cx * w - tw / 2)
            x = max(margin, min(w - tw - margin, x))
        else:
            x = (w - tw) // 2
        draw.text(
            (x, y),
            line,
            fill=fill,
            font=font,
            stroke_width=stroke,
            stroke_fill=stroke_fill,
        )
        y += line_h + gap


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
