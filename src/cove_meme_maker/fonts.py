from __future__ import annotations

import os
import sys
from pathlib import Path

# Candidates for the "Impact-like" classic meme font, in preference order.
# Impact is preinstalled on Windows; on Linux/macOS we fall back to the
# heaviest condensed/bold sans available.
_IMPACT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\Impact.ttf",
    # macOS
    "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    # Linux — user-installed MS core fonts
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/TTF/Impact.ttf",
    "/usr/share/fonts/impact.ttf",
    # Linux fallbacks
    "/usr/share/fonts/TTF/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

_REGULAR_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\Arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    # Linux
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

_REGULAR_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _first_existing(candidates: list[str]) -> Path | None:
    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    return None


def impact_font() -> Path | None:
    """Path to a heavy, condensed sans suitable for classic top/bottom text."""
    return _first_existing(_IMPACT_CANDIDATES)


def regular_font(bold: bool = True) -> Path | None:
    """Path to a plain sans for modern white-padding memes."""
    if bold:
        p = _first_existing(_REGULAR_BOLD_CANDIDATES)
        if p is not None:
            return p
    return _first_existing(_REGULAR_CANDIDATES)


def list_choices() -> list[tuple[str, Path]]:
    """Ordered, de-duplicated list of (label, path) for the font picker."""
    seen: set[Path] = set()
    out: list[tuple[str, Path]] = []

    def add(label: str, path: Path | None) -> None:
        if path is None or path in seen:
            return
        seen.add(path)
        out.append((label, path))

    add("Impact (classic)", impact_font())
    add("Sans Bold", regular_font(bold=True))
    add("Sans", regular_font(bold=False))
    return out
