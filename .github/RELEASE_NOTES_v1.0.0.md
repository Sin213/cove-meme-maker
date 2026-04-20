First public release of **Cove Meme Maker** — a focused, offline meme generator for Linux and Windows. No template library, no cloud, no account. Drop in your own image, GIF, or video, type some text, and export.

## Highlights

- **Two styles** — *Classic* (white top/bottom text with a black outline, Impact-style, burned inside the image) and *Modern* (black caption on a white band above the image).
- **Works on stills, animated GIFs, and video** — single code path, same controls. Animated GIF / WebP input is preserved frame-by-frame through Pillow (no lossy ffmpeg re-encode).
- **Draggable text** — grab the top or bottom text on the preview and put it anywhere on the image. The cursor changes to a hand when text is grabbable.
- **Per-line colour pickers** for top, bottom, and caption text. Click the small swatch next to each label.
- **ALL CAPS toggle** — on by default for Classic (keeps the Impact feel), off if you want to respect the case you typed.
- **Video trim bar** — dual-handle blue slider under the preview; drag to pick the clip range before export.
- **Video export formats** — **WebP** (default, compact), **GIF** (two-pass palette so it doesn't look deep-fried), **MP4** (x264 with optional audio passthrough via the *Keep audio* checkbox).
- **Copy to clipboard** — paste the rendered meme straight into a chat app, no file save required.
- **Remembers your settings** — style, font, sizes, colours, all-caps, last video format, and audio preference persist across sessions.
- **Drag-and-drop or click** anywhere on the preview to load a file. A **Clear** button up top drops the loaded file so you can start over without confusion.
- **Fonts** — auto-picks Impact on Windows, DejaVu Sans Condensed Bold on Linux; **Load .ttf…** to supply your own.

## Downloads

| Platform | File |
| -------- | ---- |
| Windows (installer) | `cove-meme-maker-1.0.0-Setup.exe` |
| Windows (portable) | `cove-meme-maker-1.0.0-Portable.exe` |
| Linux (AppImage) | `Cove-Meme-Maker-1.0.0-x86_64.AppImage` |
| Linux (Debian / Ubuntu) | `cove-meme-maker_1.0.0_amd64.deb` |

## Installation

### Windows

Run the **Setup.exe** for a standard install with Start Menu / desktop shortcuts, or grab the **Portable.exe** and double-click — no install required, runs from anywhere (USB, Downloads folder, etc.).

ffmpeg is **bundled** in both Windows builds, so video input works out of the box.

### Linux

**AppImage** — make executable and run:

```bash
chmod +x Cove-Meme-Maker-1.0.0-x86_64.AppImage
./Cove-Meme-Maker-1.0.0-x86_64.AppImage
```

**.deb** (Debian / Ubuntu / Mint):

```bash
sudo apt install ./cove-meme-maker_1.0.0_amd64.deb
```

Install `ffmpeg` via your package manager for video input:

```bash
sudo apt install ffmpeg           # Debian / Ubuntu
sudo pacman -S ffmpeg             # Arch / EndeavourOS
```

## Formats

| Input | Output |
| ----- | ------ |
| PNG, JPG, JPEG, WebP, BMP (static) | PNG, JPG, WebP |
| GIF, animated WebP | animated GIF, animated WebP |
| MP4, MKV, WebM, MOV, AVI, M4V | GIF, WebP, MP4 |

Enjoy — and please file bugs at [Issues](https://github.com/Sin213/cove-meme-maker/issues).
