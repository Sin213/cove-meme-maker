"""Updater tests: platform classification, release-asset selection, and the
macOS update prompt.

The first experimental macOS release is Apple Silicon only, unsigned, and
distributed as a ZIP (with a DMG as a secondary recognized asset). The
updater must recognize that such a build exists and send the user to the
GitHub release page - it must never download, extract, mount, replace, or
relaunch anything on macOS.

Every platform test monkeypatches ``sys.platform``/``sys.frozen`` through a
save-and-restore context manager so nothing leaks into later tests, and the
prompt tests swap in a fake QMessageBox so no real dialog or browser opens.
"""
import contextlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from cove_meme_maker import updater  # noqa: E402
from cove_meme_maker.updater import (  # noqa: E402
    UpdateInfo,
    bundle_kind,
    matching_sha256_asset,
    preferred_asset,
)

_app = QApplication.instance() or QApplication([])


@contextlib.contextmanager
def platform_as(platform: str, *, frozen: bool, appimage: str | None = None):
    """Temporarily present a different host platform to the updater.

    ``sys.frozen`` does not exist on a source interpreter, so restoring means
    deleting the attribute again rather than setting it False.
    """
    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)
    old_platform = sys.platform
    old_appimage = os.environ.get("APPIMAGE")
    sys.platform = platform
    if frozen:
        sys.frozen = True
    elif had_frozen:
        del sys.frozen
    if appimage is None:
        os.environ.pop("APPIMAGE", None)
    else:
        os.environ["APPIMAGE"] = appimage
    try:
        yield
    finally:
        sys.platform = old_platform
        if had_frozen:
            sys.frozen = old_frozen
        elif hasattr(sys, "frozen"):
            del sys.frozen
        if old_appimage is None:
            os.environ.pop("APPIMAGE", None)
        else:
            os.environ["APPIMAGE"] = old_appimage


def _asset(name: str) -> dict:
    return {
        "name": name,
        "browser_download_url": f"https://example.invalid/dl/{name}",
        "size": 1024,
    }


class BundleKindTest(unittest.TestCase):
    def test_frozen_darwin_is_macos(self):
        with platform_as("darwin", frozen=True):
            self.assertEqual(bundle_kind(), "macos")

    def test_source_darwin_is_source(self):
        with platform_as("darwin", frozen=False):
            self.assertEqual(bundle_kind(), "source")

    def test_appimage_unchanged(self):
        with platform_as("linux", frozen=True, appimage="/tmp/app.AppImage"):
            self.assertEqual(bundle_kind(), "appimage")

    def test_frozen_linux_is_deb(self):
        with platform_as("linux", frozen=True):
            self.assertEqual(bundle_kind(), "deb")

    def test_source_linux_is_source(self):
        with platform_as("linux", frozen=False):
            self.assertEqual(bundle_kind(), "source")

    def test_source_windows_is_source(self):
        with platform_as("win32", frozen=False):
            self.assertEqual(bundle_kind(), "source")

    def test_frozen_windows_is_portable_or_setup(self):
        with platform_as("win32", frozen=True):
            self.assertIn(bundle_kind(), ("win-setup", "win-portable"))

    def test_monkeypatch_does_not_leak(self):
        before = sys.platform
        had_frozen = hasattr(sys, "frozen")
        with platform_as("darwin", frozen=True):
            pass
        self.assertEqual(sys.platform, before)
        self.assertEqual(hasattr(sys, "frozen"), had_frozen)


MACOS_ZIP = "Cove-Meme-Maker-2.0.0-macOS-arm64.zip"
MACOS_DMG = "Cove-Meme-Maker-2.0.0-macOS-arm64.dmg"

MIXED_ASSETS = [
    _asset("Cove-Meme-Maker-2.0.0-x86_64.AppImage"),
    _asset("Cove-Meme-Maker-2.0.0-x86_64.AppImage.sha256"),
    _asset("cove-meme-maker_2.0.0_amd64.deb"),
    _asset("Cove-Meme-Maker-2.0.0-Setup.exe"),
    _asset("Cove-Meme-Maker-2.0.0-Portable.exe"),
    _asset("Cove-Meme-Maker-2.0.0-win64.zip"),
    _asset("Cove-Meme-Maker-2.0.0-linux-x86_64.tar.gz"),
    _asset("Source code.zip"),
    _asset("screenshots.zip"),
    _asset("Cove-Meme-Maker-2.0.0-macOS-x86_64.zip"),
]


class MacosPreferredAssetTest(unittest.TestCase):
    def test_selects_macos_arm64_zip(self):
        assets = MIXED_ASSETS + [_asset(MACOS_ZIP)]
        picked = preferred_asset("macos", assets)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["name"], MACOS_ZIP)

    def test_selects_dmg_when_no_zip(self):
        assets = MIXED_ASSETS + [_asset(MACOS_DMG)]
        picked = preferred_asset("macos", assets)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["name"], MACOS_DMG)

    def test_zip_preferred_over_dmg(self):
        assets = MIXED_ASSETS + [_asset(MACOS_DMG), _asset(MACOS_ZIP)]
        picked = preferred_asset("macos", assets)
        self.assertEqual(picked["name"], MACOS_ZIP)

    def test_accepts_case_and_separator_variants(self):
        for name in (
            "app-macos-arm64.zip",
            "app-macOS_arm64.zip",
            "APP-MACOS-ARM64.ZIP",
            "app-darwin-aarch64.zip",
            "app_darwin_arm64.zip",
            "app.macos.arm64.dmg",
        ):
            with self.subTest(name=name):
                picked = preferred_asset("macos", [_asset(name)])
                self.assertIsNotNone(picked)
                self.assertEqual(picked["name"], name)

    def test_rejects_incompatible_assets(self):
        for name in (
            "Cove-Meme-Maker-2.0.0-macOS-x86_64.zip",
            "Cove-Meme-Maker-2.0.0-macOS-universal2.zip",
            "Cove-Meme-Maker-2.0.0-macOS.dmg",
            "Cove-Meme-Maker-2.0.0-win64.zip",
            "Cove-Meme-Maker-2.0.0-Setup.exe",
            "Cove-Meme-Maker-2.0.0-linux-arm64.tar.gz",
            "Cove-Meme-Maker-2.0.0-arm64.AppImage",
            "Source code.zip",
            "source-code.zip",
            "screenshots.zip",
            "notes.zip",
            "Cove-Meme-Maker-2.0.0-macOS-arm64.zip.sha256",
        ):
            with self.subTest(name=name):
                self.assertIsNone(preferred_asset("macos", [_asset(name)]))

    def test_no_compatible_asset_returns_none(self):
        self.assertIsNone(preferred_asset("macos", MIXED_ASSETS))

    def test_empty_asset_list_returns_none(self):
        self.assertIsNone(preferred_asset("macos", []))

    def test_missing_asset_name_does_not_crash(self):
        assets = [{"browser_download_url": "https://example.invalid/x", "size": 1}]
        self.assertIsNone(preferred_asset("macos", assets))
        self.assertIsNone(preferred_asset("appimage", assets))


class MatchingSha256AssetTest(unittest.TestCase):
    """The sidecar scan walks the same asset list as ``preferred_asset``, so a
    malformed nameless asset must not crash the startup update check after a
    compatible macOS asset has already been selected."""

    def test_nameless_asset_does_not_crash_sidecar_scan(self):
        assets = [
            {"browser_download_url": "https://example.invalid/x", "size": 1},
            _asset(MACOS_ZIP),
        ]
        self.assertIsNone(matching_sha256_asset(MACOS_ZIP, assets))

    def test_finds_sidecar_alongside_nameless_asset(self):
        sidecar = _asset(f"{MACOS_ZIP}.sha256")
        assets = [
            {"browser_download_url": "https://example.invalid/x", "size": 1},
            _asset(MACOS_ZIP),
            sidecar,
        ]
        self.assertEqual(
            matching_sha256_asset(MACOS_ZIP, assets)["name"], sidecar["name"],
        )

    def test_finds_sidecar_in_normal_release(self):
        appimage = "Cove-Meme-Maker-2.0.0-x86_64.AppImage"
        self.assertEqual(
            matching_sha256_asset(appimage, MIXED_ASSETS)["name"],
            f"{appimage}.sha256",
        )


class ExistingPreferredAssetTest(unittest.TestCase):
    """Linux and Windows selection must be untouched by the macOS work."""

    def setUp(self):
        self.assets = MIXED_ASSETS + [_asset(MACOS_ZIP), _asset(MACOS_DMG)]

    def test_appimage(self):
        self.assertEqual(
            preferred_asset("appimage", self.assets)["name"],
            "Cove-Meme-Maker-2.0.0-x86_64.AppImage",
        )

    def test_deb(self):
        self.assertEqual(
            preferred_asset("deb", self.assets)["name"],
            "cove-meme-maker_2.0.0_amd64.deb",
        )

    def test_win_setup(self):
        self.assertEqual(
            preferred_asset("win-setup", self.assets)["name"],
            "Cove-Meme-Maker-2.0.0-Setup.exe",
        )

    def test_win_portable(self):
        self.assertEqual(
            preferred_asset("win-portable", self.assets)["name"],
            "Cove-Meme-Maker-2.0.0-Portable.exe",
        )

    def test_source_gets_nothing(self):
        self.assertIsNone(preferred_asset("source", self.assets))


class _FakeButton:
    def __init__(self, text, role):
        self.text = text
        self.role = role


class _FakeMessageBox:
    """Stand-in for QMessageBox that records the dialog instead of showing it.

    ``_prompt`` reads role constants off the module-global ``QMessageBox``,
    so the fake mirrors the ones it uses.
    """

    Information = QMessageBox.Information
    AcceptRole = QMessageBox.AcceptRole
    HelpRole = QMessageBox.HelpRole
    RejectRole = QMessageBox.RejectRole

    instances: list = []
    warnings: list = []
    click_text: str | None = None

    def __init__(self, parent=None):
        self.parent = parent
        self.buttons: list[_FakeButton] = []
        self.title = ""
        self.text = ""
        self.informative = ""
        self._clicked = None
        _FakeMessageBox.instances.append(self)

    @classmethod
    def reset(cls, click_text=None):
        cls.instances = []
        cls.warnings = []
        cls.click_text = click_text

    def setIcon(self, icon):
        pass

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setInformativeText(self, text):
        self.informative = text

    def addButton(self, text, role):
        button = _FakeButton(text, role)
        self.buttons.append(button)
        return button

    def exec(self):
        self._clicked = next(
            (b for b in self.buttons if b.text == _FakeMessageBox.click_text),
            None,
        )

    def clickedButton(self):
        return self._clicked

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.warnings.append(args)


class _Exploding:
    """Any use of this is a test failure: macOS must never download or install."""

    def __init__(self, label):
        self.label = label

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"{self.label} must not run on macOS")


MACOS_INFO = UpdateInfo(
    latest_version="2.0.0",
    release_url="https://github.com/Sin213/cove-meme-maker/releases/tag/v2.0.0",
    asset_name=MACOS_ZIP,
    asset_url=f"https://example.invalid/dl/{MACOS_ZIP}",
    asset_size=40 * 1024 * 1024,
    sha256_url=f"https://example.invalid/dl/{MACOS_ZIP}.sha256",
)


class MacosPromptTest(unittest.TestCase):
    def setUp(self):
        self.opened: list[str] = []
        self._saved = {
            "QMessageBox": updater.QMessageBox,
            "_open_url": updater._open_url,
            "DownloadWorker": updater.DownloadWorker,
            "swap_in_appimage": updater.swap_in_appimage,
            "relaunch": updater.relaunch,
        }
        updater.QMessageBox = _FakeMessageBox
        updater._open_url = self.opened.append
        updater.DownloadWorker = _Exploding("DownloadWorker")
        updater.swap_in_appimage = _Exploding("swap_in_appimage")
        updater.relaunch = _Exploding("relaunch")
        _FakeMessageBox.reset()
        self.parent = QWidget()
        self.controller = updater.UpdateController(
            parent=self.parent,
            current_version="1.0.0",
            repo="Sin213/cove-meme-maker",
            app_display_name="Cove Meme Maker",
            cache_subdir="cove-meme-maker",
        )

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(updater, name, value)
        _FakeMessageBox.reset()
        self.parent.deleteLater()

    def _prompt(self, click_text):
        _FakeMessageBox.reset(click_text)
        with platform_as("darwin", frozen=True):
            self.controller._on_update_available(MACOS_INFO)
        return _FakeMessageBox.instances[-1]

    def test_prompt_offers_release_page_only(self):
        box = self._prompt(None)
        labels = [b.text for b in box.buttons]
        self.assertIn("View release", labels)
        self.assertNotIn("Update now", labels)
        self.assertIn("v2.0.0", box.text)

    def test_accept_opens_release_page_not_asset(self):
        self._prompt("View release")
        self.assertEqual(self.opened, [MACOS_INFO.release_url])
        self.assertNotIn(MACOS_INFO.asset_url, self.opened)
        self.assertEqual(_FakeMessageBox.warnings, [])
        self.assertIsNone(self.controller._download_thread)

    def test_later_does_nothing(self):
        self._prompt("Later")
        self.assertEqual(self.opened, [])
        self.assertEqual(_FakeMessageBox.warnings, [])
        self.assertIsNone(self.controller._download_thread)

    def test_dismissed_dialog_does_nothing(self):
        self._prompt(None)
        self.assertEqual(self.opened, [])
        self.assertIsNone(self.controller._download_thread)


class MacosCheckWorkerTest(unittest.TestCase):
    """The check worker must recognize a compatible macOS release without
    touching the network."""

    def setUp(self):
        self._fetch = updater.fetch_latest_release

    def tearDown(self):
        updater.fetch_latest_release = self._fetch

    def _run(self, assets):
        updater.fetch_latest_release = lambda repo, timeout=8.0: {
            "tag_name": "v2.0.0",
            "html_url": (
                "https://github.com/Sin213/cove-meme-maker/releases/tag/v2.0.0"
            ),
            "assets": assets,
        }
        worker = updater.UpdateCheckWorker("1.0.0", "Sin213/cove-meme-maker")
        seen: list[UpdateInfo] = []
        worker.updateAvailable.connect(seen.append)
        with platform_as("darwin", frozen=True):
            worker.run()
        return seen

    def test_recognizes_macos_arm64_release(self):
        seen = self._run(MIXED_ASSETS + [_asset(MACOS_ZIP)])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].asset_name, MACOS_ZIP)
        self.assertTrue(seen[0].release_url.endswith("/releases/tag/v2.0.0"))

    def test_no_macos_asset_still_points_at_release_page(self):
        seen = self._run(MIXED_ASSETS)
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0].asset_name)
        self.assertIsNone(seen[0].asset_url)
        self.assertTrue(seen[0].release_url.endswith("/releases/tag/v2.0.0"))


if __name__ == "__main__":
    unittest.main()
