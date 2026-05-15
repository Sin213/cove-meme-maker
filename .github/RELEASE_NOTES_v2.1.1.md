## v2.1.1 — Foxy Mode live preview parity

Patch release that fixes the Foxy Mode (tab-web) editor so its Modern caption preview behaves the same as the standalone Meme Maker. No protocol or Qt behavior changes.

### Fixes

- **Modern caption band appears live** the moment caption text becomes non-empty — no more blank Modern preview until you click Render.
- **Modern caption band disappears live** when the caption is cleared — the white band is removed immediately instead of lingering.
- **Stale scheduled Modern layout callback** can no longer reopen an empty caption band after you clear the text. Pending `requestAnimationFrame` work is now invalidated on each layout pass.
- **Crop overlay recalibrates** when the Modern caption layout is cleared, so the crop region stays anchored to the actual image after the band collapses.

### Changes

- Removed the obsolete **Render** button and its render-first workflow from the Foxy Mode toolbar. The editor is now fully live.
- **Export PNG** and **Copy to clipboard** still render the current editor state on demand — those paths are unchanged.

### Unchanged

- No Cove Nexus protocol changes.
- No standalone Qt (desktop) behavior changes.

### Downloads

| Platform | File |
| -------- | ---- |
| Windows (installer) | `cove-meme-maker-2.1.1-Setup.exe` |
| Windows (portable) | `cove-meme-maker-2.1.1-Portable.exe` |
| Linux (AppImage) | `Cove-Meme-Maker-2.1.1-x86_64.AppImage` |
| Linux (Debian / Ubuntu) | `cove-meme-maker_2.1.1_amd64.deb` |

SHA-256 checksums are provided as `.sha256` sidecar files alongside each binary.
