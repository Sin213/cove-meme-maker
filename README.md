# Cove Meme Maker

A focused, offline meme generator for **Linux** and **Windows**. No cloud,
no template library, no account — drop in your own image, GIF, or video,
type some text, and export.

![icon](cove_icon.png)

## Download (v1.0.0)

| Platform | File |
| -------- | ---- |
| Windows (installer) | `cove-meme-maker-1.0.0-Setup.exe` |
| Windows (portable) | `cove-meme-maker-1.0.0-Portable.exe` |
| Linux (AppImage) | `Cove-Meme-Maker-1.0.0-x86_64.AppImage` |
| Linux (Debian / Ubuntu) | `cove-meme-maker_1.0.0_amd64.deb` |

Grab the artifacts from the [Releases page](https://github.com/Sin213/cove-meme-maker/releases).

## Styles

- **Classic** — white top/bottom text with a black outline, Impact-style,
  burned inside the image. Text can be **dragged** anywhere on the preview.
- **Modern** — a black caption on a white band above the image, the
  "Tumblr-style" meme.

Both styles work the same way on stills, animated GIFs, and video.

## Features

- **Drag-and-drop or click** the preview pane to load a file.
- **Live preview** — every text or settings change re-renders on the spot.
- **Per-line colour pickers** for the top, bottom, and caption text.
- **ALL CAPS toggle** — on by default for Classic (keeps the Impact feel),
  off if you want to respect the case you typed.
- **Draggable text** — grab the top or bottom text on the preview and move
  it anywhere. The hand cursor shows what's draggable.
- **Font picker** with sensible system fallbacks; **Load .ttf…** to supply
  your own (e.g. bring your own Impact on Linux).
- **Size / stroke / padding sliders** as a percentage of image height —
  renders look the same across resolutions.
- **Animated GIF / WebP preservation** — frames go through Pillow directly,
  no re-encode through ffmpeg. Frame timing is preserved.
- **Video trim bar** — drag the blue handles to pick the clip range before
  export. Labels update in real time.
- **Video output formats** — WebP (default, compact), GIF (two-pass
  palette), MP4 (x264, optional audio passthrough via the *Keep audio*
  toggle).
- **Copy to clipboard** — paste the rendered meme straight into a chat app,
  no file save required.
- **Remembers your settings** — style, font, sizes, colours, all-caps, last
  video format, and audio preference persist between sessions via QSettings.

## Formats

| Input | Output |
| ----- | ------ |
| `.png` `.jpg` `.jpeg` `.webp` `.bmp` (static) | PNG, JPG, WebP |
| `.gif` `.webp` (animated) | animated GIF, animated WebP |
| `.mp4` `.mkv` `.webm` `.mov` `.avi` `.m4v` | GIF, WebP, MP4 |

GIFs use ffmpeg's two-pass palette pipeline so they don't look
deep-fried; WebP uses `libwebp` with a quality slider.

## Requirements

- Python 3.10+
- `PySide6` and `Pillow` (installed automatically by `pip`)
- `ffmpeg` and `ffprobe` on `PATH` for video input
  - Arch / EndeavourOS: `sudo pacman -S ffmpeg`
  - Debian / Ubuntu: `sudo apt install ffmpeg`
  - Windows: bundled inside the .exe / installer builds; otherwise install
    from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

Animated GIF/WebP handling and all image output do **not** need ffmpeg.

## Running from source

```bash
pip install -e .
cove-meme-maker
```

Or without installing:

```bash
PYTHONPATH=src python -m cove_meme_maker
```

## Building release artifacts

### Linux (AppImage + .deb)

```bash
VERSION=1.0.0 ./scripts/build-release.sh
```

Produces `Cove-Meme-Maker-<version>-x86_64.AppImage` and
`cove-meme-maker_<version>_amd64.deb` under `release/`.

### Windows (Setup.exe + Portable.exe)

```powershell
.\build.ps1 -Version 1.0.0
```

Requires Python 3.12+, [Inno Setup 6](https://jrsoftware.org/isdl.php),
and an internet connection the first time (downloads a portable ffmpeg).
Produces `cove-meme-maker-<version>-Setup.exe` and
`cove-meme-maker-<version>-Portable.exe` under `release\`.

### GitHub Actions

Tagging a commit `vX.Y.Z` triggers `.github/workflows/release.yml`, which
produces all four artifacts and attaches them to a GitHub release.

## Fonts

Impact ships with Windows, so Classic memes look right there out of the
box. The Windows builds bundle DejaVu Sans Bold as a guaranteed fallback.
On Linux the app falls back to DejaVu Sans Condensed Bold / Liberation
Sans Bold — install the `ttf-ms-fonts` / `msttcorefonts` package for the
authentic look, or use **Load .ttf…** in the font picker to supply your
own.

## License

MIT — see [LICENSE](LICENSE).
