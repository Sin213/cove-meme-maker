## v2.0.0 — The Redesign

Cove Meme Maker has been rebuilt from the ground up with a new look and a sharper focus on what it does best: making memes from your own images, fast.

![Cove Meme Maker v2.0.0](https://raw.githubusercontent.com/Sin213/cove-meme-maker/main/assets/screenshot.png)

### What's new

- **Cove dark theme** — deep, teal-accented dark UI matching the Cove design system. Custom frameless window chrome with Windows-style minimize / maximize / close controls and edge-drag resizing.
- **Direct text manipulation** — click a classic text block to select it, then drag to move, pull a corner handle to resize, or grab the rotation bubble to rotate. All changes are reflected in real time on the preview.
- **Crop tool** — open the crop dialog to trim your image before adding text. Drag the region or pull edge/corner handles; a rule-of-thirds guide helps with composition.
- **Per-line colour pickers** — set custom colours for the top text, bottom text, and modern caption independently.
- **Streamlined image focus** — the app is now purpose-built for static images (PNG, JPG, WebP, BMP). Video and GIF animation support has been removed to keep the tool lean and dependency-free — no ffmpeg required.

### Breaking changes

- **Video and animated GIF/WebP support removed.** If you need animated output, check out [Cove GIF Maker](https://github.com/Sin213/cove-gif-maker).
- **ffmpeg is no longer bundled or required.** The Windows builds are smaller as a result.

### Downloads

| Platform | File |
| -------- | ---- |
| Windows (installer) | `cove-meme-maker-2.0.0-Setup.exe` |
| Windows (portable) | `cove-meme-maker-2.0.0-Portable.exe` |
| Linux (AppImage) | `Cove-Meme-Maker-2.0.0-x86_64.AppImage` |
| Linux (Debian / Ubuntu) | `cove-meme-maker_2.0.0_amd64.deb` |

SHA-256 checksums are provided as `.sha256` sidecar files alongside each binary.
