## Cove Meme Maker v2.3.7

**Image overlays + experimental Apple Silicon build** — Multi-image overlays are now movable, resizable and rotatable on the desktop, and macOS gets its first Apple Silicon build alongside a more reliable release pipeline.

### What's new

- **Multi-image overlays on the desktop.** Drop several images onto a meme and position each one independently. Overlays share the same Pillow render path as the exported image, so what you arrange is what you get.
- **Drag, resize and rotate.** Image overlays can be dragged and resized directly on the canvas, moved from a dedicated top anchor, and rotated with the top handle.
- **Experimental macOS Apple Silicon build.** A native `.app` bundle is now published as a ZIP, with a DMG alongside it. See the limitations below before downloading.
- **macOS update awareness.** A frozen macOS build now recognizes its own release asset and opens the GitHub release page when a newer version exists. macOS updates are **not** installed automatically — you download and replace the app yourself. Linux and Windows update behavior is unchanged.
- **Nexus/tab-web reliability.** The embedded tab-web server keeps its `127.0.0.1` binding and pre-Qt startup gate under test, and Modern-style rendering is now verified to route through the caption-band renderer instead of silently falling back to Classic.
- **Release and packaging reliability.** Checksum sidecars are now generated before artifacts are uploaded, so every published binary ships with its `.sha256`. Linux, Windows and macOS packages are launch-tested in CI before release.

### macOS limitations — read before downloading

The macOS build is **experimental** and deliberately narrow in scope:

- **Apple Silicon (arm64) only.** There is no Intel build and no universal2 build.
- **Not Developer ID signed.** The app is ad-hoc signed only.
- **Not notarized.** macOS Gatekeeper will block it on first launch — right-click the app and choose **Open**, or allow it under **System Settings → Privacy & Security**.
- **Updates are not installed automatically.** The app opens the GitHub release page instead.

### Downloads

| Platform | File |
|---|---|
| macOS 12+ (Apple Silicon, experimental) | `Cove-Meme-Maker-2.3.7-macOS-arm64.zip` |
| macOS 12+ (Apple Silicon, experimental, disk image) | `Cove-Meme-Maker-2.3.7-macOS-arm64.dmg` |
| Linux | `Cove-Meme-Maker-2.3.7-x86_64.AppImage` |
| Linux (Debian/Ubuntu) | `cove-meme-maker_2.3.7_amd64.deb` |
| Windows (installer) | `cove-meme-maker-2.3.7-Setup.exe` |
| Windows (portable) | `cove-meme-maker-2.3.7-Portable.exe` |

SHA256 checksums are provided alongside each file.

**Full Changelog**: https://github.com/Sin213/cove-meme-maker/compare/v2.3.6...v2.3.7
