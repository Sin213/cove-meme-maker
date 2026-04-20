from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegMissingError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegMissingError("ffmpeg not found on PATH")
    return path


def require_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise FFmpegMissingError("ffprobe not found on PATH")
    return path


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    fps: float


def probe(video: Path) -> VideoInfo:
    cmd = [
        require_ffprobe(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json",
        str(video),
    ]
    out = subprocess.check_output(cmd, text=True)
    data = json.loads(out)
    stream = data["streams"][0]
    duration = float(data["format"]["duration"])
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return VideoInfo(
        duration=duration,
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
    )


def extract_frame(video: Path, time: float, out: Path) -> None:
    """Grab a single frame at ``time`` seconds for use in the live preview."""
    cmd = [
        require_ffmpeg(),
        "-y",
        "-ss", f"{time:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def ffmpeg_escape_path(p: Path) -> str:
    """Escape a font path for use inside an ffmpeg ``drawtext`` filter value.

    drawtext treats ``:`` as an option separator and ``\\`` as an escape, so
    backslashes double and colons (Windows drive letters) must be quoted.
    """
    s = str(p).replace("\\", "/")
    return s.replace(":", r"\:").replace("'", r"\'")


def ffmpeg_escape_text(s: str) -> str:
    """Escape arbitrary text for use inside a single-quoted drawtext value."""
    # Order matters: escape backslashes first, then the other metachars.
    s = s.replace("\\", r"\\")
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    # Newlines inside drawtext need an unescaped literal newline to wrap, but
    # we expose explicit line breaks via `\n` (two chars) which drawtext reads
    # when `:expansion=normal` is set.
    s = s.replace("\n", r"\n")
    return s
