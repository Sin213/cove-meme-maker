## Cove Meme Maker v2.3.0

**macOS support + font reliability** — First macOS DMG release, bundled font fallback for all platforms, and a render smoke test to catch regressions.

### What's new

- **macOS DMG.** Native `.app` bundle packaged as a drag-to-Applications DMG. Supports macOS 12 Ventura and later (Apple Silicon and Intel via Rosetta). Since the app is not notarized, macOS will block it on first launch — go to **System Settings → Privacy & Security** and click **Open Anyway** to allow it.
- **Bundled font fallback.** DejaVu Sans Bold is now shipped inside every build (AppImage, .deb, DMG, Windows exe). If system fonts are unavailable — as on a clean macOS install — rendering falls back to the bundled font automatically instead of dropping to a bitmap default.
- **Render smoke test.** `smoke_render_font.py` verifies both Classic and Modern styles survive a missing-font scenario. Runs in CI with no GUI or network.

### Downloads

| Platform | File |
|---|---|
| macOS (12+) | `Cove-Meme-Maker-2.3.0-macOS.dmg` |
| Linux | `Cove-Meme-Maker-2.3.0-x86_64.AppImage` |
| Linux (Debian/Ubuntu) | `cove-meme-maker_2.3.0_amd64.deb` |
| Windows (installer) | `cove-meme-maker-2.3.0-Setup.exe` |
| Windows (portable) | `cove-meme-maker-2.3.0-Portable.exe` |

SHA256 checksums are provided alongside each file.

**Full Changelog**: https://github.com/Sin213/cove-meme-maker/compare/v2.2.0...v2.3.0
