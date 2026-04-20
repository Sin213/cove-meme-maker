"""Build ffmpeg commands that burn meme text onto videos and export to
MP4, GIF, or WebP. The classic/modern semantics match ``image_renderer``
so the preview (rendered on an extracted frame with Pillow) and the final
video stay visually aligned.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .ffmpeg_utils import ffmpeg_escape_path, require_ffmpeg
from .image_renderer import MemeSpec

VideoFormat = Literal["mp4", "gif", "webp"]


@dataclass
class VideoJob:
    source: Path
    output: Path
    width: int
    height: int
    spec: MemeSpec
    fmt: VideoFormat = "gif"
    fps: int = 15
    scale_pct: int = 100
    # GIF-only
    palette_colors: int = 192
    # WebP-only
    webp_quality: int = 80
    loop: int = 0  # 0 = infinite for gif/webp
    # Trim range in seconds; None means full clip.
    start: float | None = None
    end: float | None = None
    # MP4-only: keep the original audio track (False → strip it).
    keep_audio: bool = True


def _drawtext(
    textfile: Path,
    font_path: Path | None,
    font_size: int,
    *,
    fill: str,
    x: str,
    y: str,
    stroke: int = 0,
    stroke_color: str = "black",
) -> str:
    """Build a ``drawtext=...`` filter. Reads text via ``textfile=`` so
    apostrophes and colons in the caption survive ffmpeg's filter parser
    unchanged — no fragile manual escaping required.
    """
    # ffmpeg filter syntax: ``filter_name=k=v:k=v`` — the first separator
    # after the filter name is ``=``, subsequent options are joined by ``:``.
    opts = [
        f"textfile='{ffmpeg_escape_path(textfile)}'",
        f"fontsize={font_size}",
        f"fontcolor={fill}",
        f"x={x}",
        f"y={y}",
        "line_spacing=6",
    ]
    if font_path is not None:
        opts.append(f"fontfile='{ffmpeg_escape_path(font_path)}'")
    if stroke > 0:
        opts.append(f"bordercolor={stroke_color}")
        opts.append(f"borderw={stroke}")
    return "drawtext=" + ":".join(opts)


def _chain(*filters: str) -> str:
    return ",".join(f for f in filters if f)


def _write_text(dir: Path, name: str, text: str) -> Path:
    path = dir / name
    path.write_text(text, encoding="utf-8")
    return path


def build_video_filter(job: VideoJob, workdir: Path) -> str:
    """Filter chain that burns the meme onto the video before format-specific
    post-processing (palette, scaling, etc.). ``workdir`` must live at least
    until ffmpeg finishes — we stage caption text there.
    """
    spec = job.spec
    w, h = job.width, job.height
    font_size = max(12, int(h * spec.font_scale))

    if spec.style == "classic":
        stroke = max(1, int(font_size * spec.stroke_ratio))
        margin = max(10, int(h * 0.03))
        xform = str.upper if spec.uppercase else (lambda s: s)
        filters: list[str] = []
        if spec.top.strip():
            tf = _write_text(workdir, "top.txt", xform(spec.top))
            x, y = _classic_xy(spec.top_pos, "top", margin)
            filters.append(_drawtext(
                tf, spec.font_path, font_size,
                fill=_hex(spec.top_color), x=x, y=y,
                stroke=stroke, stroke_color=_hex(spec.stroke_color),
            ))
        if spec.bottom.strip():
            tf = _write_text(workdir, "bottom.txt", xform(spec.bottom))
            x, y = _classic_xy(spec.bottom_pos, "bottom", margin)
            filters.append(_drawtext(
                tf, spec.font_path, font_size,
                fill=_hex(spec.bottom_color), x=x, y=y,
                stroke=stroke, stroke_color=_hex(spec.stroke_color),
            ))
        return _chain(*filters)

    # Modern: white band above the video.
    band = max(int(h * spec.padding_scale), int(font_size * 2.4))
    pad_filter = f"pad=iw:ih+{band}:0:{band}:color=white"
    caption = spec.caption
    if not caption.strip():
        return pad_filter
    tf = _write_text(workdir, "caption.txt", caption)
    draw = _drawtext(
        tf, spec.font_path, font_size,
        fill=_hex(spec.caption_color),
        x="(w-text_w)/2", y=f"({band}-text_h)/2",
    )
    return _chain(pad_filter, draw)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _classic_xy(
    pos: tuple[float, float] | None,
    anchor: str,
    margin: int,
) -> tuple[str, str]:
    """Compute ffmpeg x/y expressions for a classic text block.

    With ``pos=None`` we fall back to centred top/bottom placement. Otherwise
    we interpret ``pos`` as normalised (cx, cy) for the block centre and turn
    that into ffmpeg expressions referencing runtime ``w``/``h``/``text_w``/``text_h``.
    """
    if pos is None:
        x = "(w-text_w)/2"
        y = f"{margin}" if anchor == "top" else f"h-text_h-{margin}"
        return x, y
    cx = max(0.0, min(1.0, pos[0]))
    cy = max(0.0, min(1.0, pos[1]))
    x = f"w*{cx:.4f}-text_w/2"
    y = f"h*{cy:.4f}-text_h/2"
    return x, y


def _scale_filter(job: VideoJob) -> str:
    if job.scale_pct == 100:
        return ""
    return f"scale=iw*{job.scale_pct/100:.4f}:-2:flags=lanczos"


def _fps_filter(job: VideoJob) -> str:
    return f"fps={job.fps}"


def build_command(job: VideoJob, workdir: Path) -> list[str]:
    """Single-command ffmpeg pipeline for the chosen output format.

    ``workdir`` holds staged text files referenced by ``drawtext=textfile=...``
    and must outlive the ffmpeg process. The caller owns its lifetime.
    """
    ff = require_ffmpeg()
    meme = build_video_filter(job, workdir)
    scale = _scale_filter(job)
    common = _chain(meme, _fps_filter(job), scale) if job.fmt != "mp4" else _chain(meme, scale)

    trim_in = _trim_input_args(job)

    if job.fmt == "gif":
        palette = (
            f"split[m][p];"
            f"[p]palettegen=max_colors={job.palette_colors}:stats_mode=diff[pal];"
            f"[m][pal]paletteuse=dither=sierra2_4a"
        )
        filter_complex = f"[0:v]{common}[base];[base]{palette}"
        return [
            ff, "-y",
            *trim_in,
            "-i", str(job.source),
            "-filter_complex", filter_complex,
            "-loop", str(job.loop),
            "-an",
            str(job.output),
        ]
    if job.fmt == "webp":
        return [
            ff, "-y",
            *trim_in,
            "-i", str(job.source),
            "-vf", common,
            "-vcodec", "libwebp",
            "-lossless", "0",
            "-q:v", str(job.webp_quality),
            "-loop", str(job.loop),
            "-an",
            "-vsync", "0",
            str(job.output),
        ]
    # mp4
    audio_args = ["-c:a", "copy"] if job.keep_audio else ["-an"]
    return [
        ff, "-y",
        *trim_in,
        "-i", str(job.source),
        "-vf", common,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "20",
        *audio_args,
        "-movflags", "+faststart",
        str(job.output),
    ]


def _trim_input_args(job: VideoJob) -> list[str]:
    """Input-side ``-ss``/``-t`` args. Placed before ``-i`` for fast seeking."""
    args: list[str] = []
    if job.start is not None and job.start > 0:
        args += ["-ss", f"{job.start:.3f}"]
    if job.end is not None and job.end > (job.start or 0):
        duration = job.end - (job.start or 0)
        args += ["-t", f"{duration:.3f}"]
    return args
