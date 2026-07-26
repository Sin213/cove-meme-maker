## Cove Meme Maker v2.4.0

**Image overlays come to Nexus foxy mode.** The tab-web UI served inside Cove Nexus now has the same add-image overlay feature as the desktop app: drop logos and stickers onto a meme, then move, resize and rotate them before exporting.

### What's new

- **Add Image in foxy mode.** The tab-web toolbar gains an Add Image button. Up to 8 image overlays per meme, each draggable, resizable and rotatable directly on the canvas, with bring-forward/send-back z-order controls and per-overlay delete.
- **Crop-aware overlays.** Overlay positions follow the crop region, so what you arrange while cropping is what the exported image shows.
- **Shared render path.** Tab-web overlays composite through the same Pillow `OverlaySpec` renderer as the desktop app, so the hosted preview and the desktop export agree pixel for pixel.
- **Server-side validation.** Overlay uploads are size- and dimension-capped, base64-validated, and covered by the same rate limiting as the existing render endpoint.

### Changelog

Commits since v2.3.7:

| Commit | Change |
|---|---|
| `15174d1` | feat(tab-web): add image overlays to the Nexus tab-web UI |

### macOS limitations, read before downloading

The macOS build is **experimental** and deliberately narrow in scope:

- **Apple Silicon (arm64) only.** There is no Intel build and no universal2 build.
- **Not Developer ID signed.** The app is ad-hoc signed only.
- **Not notarized.** macOS Gatekeeper will block it on first launch. Right-click the app and choose **Open**, or allow it under **System Settings > Privacy & Security**.
- **Updates are **not** installed automatically.** The app opens the GitHub release page instead.

### Downloads

| Platform | File |
|---|---|
| macOS 12+ (Apple Silicon, experimental) | `Cove-Meme-Maker-2.4.0-macOS-arm64.zip` |
| macOS 12+ (Apple Silicon, experimental, disk image) | `Cove-Meme-Maker-2.4.0-macOS-arm64.dmg` |
| Linux | `Cove-Meme-Maker-2.4.0-x86_64.AppImage` |
| Linux (Debian/Ubuntu) | `cove-meme-maker_2.4.0_amd64.deb` |
| Windows (installer) | `cove-meme-maker-2.4.0-Setup.exe` |
| Windows (portable) | `cove-meme-maker-2.4.0-Portable.exe` |

SHA256 checksums are provided alongside each file.

**Full Changelog**: https://github.com/Sin213/cove-meme-maker/compare/v2.3.7...v2.4.0
