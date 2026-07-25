"""Focused coverage for the experimental macOS arm64 packaging path.

These tests are deterministic and run on any platform - they cover the
contracts that a Linux checkout can actually verify:

* the smoke test's Unix socket path is short, unique per run, and cleaned up
  (macOS ``sun_path`` is capped at 104 bytes, and the default macOS temp dir
  under ``/var/folders`` is long enough to break ``bind()``);
* the artifact names the build script emits are the ones the updater's
  macOS/arm64 matcher accepts, and the old architecture-ambiguous DMG name
  stays rejected;
* the build script and release workflow keep their arm64-only guarantees.

Building or executing the .app itself is only possible on the macos-14 CI job.
"""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = str(REPO_ROOT / "src")
SCRIPTS_DIR = str(REPO_ROOT / "scripts")
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-macos.sh"
MACOS_SPEC = REPO_ROOT / "packaging" / "cove-meme-maker-macos.spec"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

for _p in (SRC_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import smoke_tab_web  # noqa: E402

from cove_meme_maker.updater import preferred_asset  # noqa: E402


def _project_version() -> str:
    text = (REPO_ROOT / "src" / "cove_meme_maker" / "__init__.py").read_text()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    assert m, "could not read __version__"
    return m.group(1)


def _script_code(path: Path) -> str:
    """Shell source with whole-line comments stripped (prose is not behavior)."""
    return "\n".join(
        line for line in path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )


def _asset(name: str) -> dict:
    return {"name": name, "browser_download_url": f"https://example.invalid/{name}"}


class ShortSocketPathTest(unittest.TestCase):
    def test_path_is_under_short_base(self):
        with smoke_tab_web.short_socket_path() as sock_path:
            self.assertTrue(
                sock_path.startswith(smoke_tab_web.SOCKET_BASE + os.sep),
                f"socket must live under {smoke_tab_web.SOCKET_BASE}, got {sock_path}",
            )

    def test_path_fits_macos_sun_path_limit(self):
        with smoke_tab_web.short_socket_path() as sock_path:
            self.assertLess(
                len(sock_path.encode()), smoke_tab_web.SOCKET_PATH_LIMIT,
                f"socket path too long for macOS sun_path: {sock_path}",
            )

    def test_separate_runs_get_distinct_paths(self):
        with smoke_tab_web.short_socket_path() as a:
            with smoke_tab_web.short_socket_path() as b:
                self.assertNotEqual(a, b, "concurrent runs must not share a socket")

    def test_cleanup_removes_socket_and_directory(self):
        import socket as _socket

        with smoke_tab_web.short_socket_path() as sock_path:
            listener = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            try:
                listener.bind(sock_path)
                listener.listen(1)
                self.assertTrue(os.path.exists(sock_path))
            finally:
                listener.close()
        self.assertFalse(os.path.exists(sock_path), "socket left behind")
        self.assertFalse(
            os.path.isdir(os.path.dirname(sock_path)), "temp dir left behind"
        )

    def test_cleanup_runs_on_exception(self):
        captured = {}
        with self.assertRaises(RuntimeError):
            with smoke_tab_web.short_socket_path() as sock_path:
                captured["dir"] = os.path.dirname(sock_path)
                raise RuntimeError("boom")
        self.assertFalse(os.path.isdir(captured["dir"]))


class ArtifactNameContractTest(unittest.TestCase):
    """The names the build script writes must be the names the updater picks."""

    def setUp(self):
        self.version = _project_version()
        self.zip_name = f"Cove-Meme-Maker-{self.version}-macOS-arm64.zip"
        self.dmg_name = f"Cove-Meme-Maker-{self.version}-macOS-arm64.dmg"
        self.legacy_dmg = f"Cove-Meme-Maker-{self.version}-macOS.dmg"

    def test_zip_is_preferred_over_dmg(self):
        assets = [_asset(self.dmg_name), _asset(self.zip_name)]
        picked = preferred_asset("macos", assets)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["name"], self.zip_name)

    def test_dmg_accepted_when_zip_absent(self):
        picked = preferred_asset("macos", [_asset(self.dmg_name)])
        self.assertIsNotNone(picked)
        self.assertEqual(picked["name"], self.dmg_name)

    def test_legacy_ambiguous_dmg_still_rejected(self):
        self.assertIsNone(
            preferred_asset("macos", [_asset(self.legacy_dmg)]),
            "architecture-ambiguous macOS DMG must not be selected",
        )

    def test_build_script_emits_only_arm64_names(self):
        text = BUILD_SCRIPT.read_text()
        self.assertIn('${SLUG}-${VERSION}-macOS-arm64.zip', text)
        self.assertIn('${SLUG}-${VERSION}-macOS-arm64.dmg', text)
        self.assertNotIn('-macOS.dmg', text, "ambiguous DMG name still generated")


class BuildScriptContractTest(unittest.TestCase):
    def test_syntax_is_valid(self):
        proc = subprocess.run(
            ["bash", "-n", str(BUILD_SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_version_is_not_hardcoded(self):
        text = BUILD_SCRIPT.read_text()
        self.assertNotIn('VERSION:-2.3.0', text)
        self.assertIn("src/cove_meme_maker/__init__.py", text)

    def test_enforces_arm64_and_uses_ditto(self):
        text = BUILD_SCRIPT.read_text()
        self.assertIn('lipo -archs', text)
        self.assertIn('uname -m', text)
        self.assertIn('ditto -c -k', text)

    def test_spec_targets_arm64_only(self):
        text = MACOS_SPEC.read_text()
        targets = re.findall(r'target_arch\s*=\s*["\']([^"\']+)["\']', text)
        self.assertEqual(targets, ["arm64"], f"unexpected target_arch: {targets}")
        # GUI/windowed bootloader: no terminal window on desktop launch.
        self.assertIn('console=False', text)

    def test_no_signing_or_notarization_commands(self):
        """Comments may mention Developer ID; no command may require it."""
        code = _script_code(BUILD_SCRIPT)
        for banned in ("notarytool", "altool", "--keychain", "codesign_identity"):
            self.assertNotIn(banned, code, f"unexpected signing step: {banned}")
        # codesign is only used read-only, never to re-sign the bundle.
        for line in code.splitlines():
            if "codesign" in line:
                self.assertIn("--display", line, f"unexpected codesign call: {line}")


class MacOSWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_uses_apple_silicon_runner(self):
        self.assertIn("runs-on: macos-14", self.text)
        self.assertNotIn("runs-on: macos-latest", self.text)

    def test_linux_and_windows_jobs_preserved(self):
        self.assertIn("runs-on: ubuntu-latest", self.text)
        self.assertIn("runs-on: windows-latest", self.text)

    def test_uploads_arm64_artifacts_only(self):
        self.assertIn("release/*-macOS-arm64.zip", self.text)
        self.assertIn("release/*-macOS-arm64.dmg", self.text)

    def test_runs_packaged_smoke(self):
        self.assertIn("scripts/smoke_tab_web.py --exe", self.text)


if __name__ == "__main__":
    unittest.main()
