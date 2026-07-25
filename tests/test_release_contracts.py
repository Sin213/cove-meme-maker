"""Deterministic contracts for the v2.3.7 release candidate.

Two classes of regression are covered:

* **Version drift.** The release version lives in four active places
  (package, project metadata, and the Linux/Windows build-script defaults).
  A release built from a drifted default produces mislabeled artifacts, which
  the updater then fails to match. These tests fail when any one drifts.
* **Workflow packaging contracts.** Checksum sidecars must be generated
  *before* uploads (otherwise the uploaded artifacts silently omit them, as
  happened for Linux and Windows), uploads must include the sidecars, and each
  platform must launch-test its packaged artifact before release.

The workflow is checked with stdlib text/structure assertions rather than a
YAML parser so the suite needs no dependency beyond the project's own.
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_PY = REPO_ROOT / "src" / "cove_meme_maker" / "__init__.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
BUILD_PS1 = REPO_ROOT / "build.ps1"
BUILD_LINUX = REPO_ROOT / "scripts" / "build-release.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
NOTES_DIR = REPO_ROOT / ".github"

TARGET_VERSION = "2.3.7"


def _canonical_version() -> str:
    m = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']', INIT_PY.read_text(), re.M
    )
    assert m, "could not read __version__"
    return m.group(1)


def _job_block(text: str, job: str) -> str:
    """Return the YAML lines belonging to one top-level job."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(f"  {job}:"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        # Next sibling job: exactly two spaces of indent, then a key.
        if re.match(r"^  \S.*:\s*$", line) and not line.startswith("    "):
            end = i
            break
    return "\n".join(lines[start:end])


class VersionSyncTest(unittest.TestCase):
    """All active release-version sources must agree."""

    def test_canonical_version_is_target(self):
        self.assertEqual(_canonical_version(), TARGET_VERSION)

    def test_pyproject_matches(self):
        m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), _canonical_version())

    def test_windows_build_default_matches(self):
        m = re.search(r'\$Version\s*=\s*"([^"]+)"', BUILD_PS1.read_text())
        self.assertIsNotNone(m, "build.ps1 has no -Version default")
        self.assertEqual(
            m.group(1), _canonical_version(),
            "build.ps1 default drifted; a local Windows build would mislabel artifacts",
        )

    def test_linux_build_default_matches(self):
        m = re.search(r'VERSION="\$\{VERSION:-([^}]+)\}"', BUILD_LINUX.read_text())
        self.assertIsNotNone(m, "build-release.sh has no VERSION default")
        self.assertEqual(
            m.group(1), _canonical_version(),
            "build-release.sh default drifted; a local Linux build would mislabel artifacts",
        )

    def test_macos_build_derives_version(self):
        """build-macos.sh derives from the package, so it cannot drift."""
        self.assertIn(
            "cove_meme_maker.__version__",
            (REPO_ROOT / "scripts" / "build-macos.sh").read_text(),
        )


class ReleaseNotesTest(unittest.TestCase):
    def test_notes_exist_for_canonical_version(self):
        notes = NOTES_DIR / f"RELEASE_NOTES_v{_canonical_version()}.md"
        self.assertTrue(
            notes.exists(),
            f"{notes.name} missing; every tag job uses it as body_path and "
            "the release attach step would fail",
        )
        self.assertGreater(len(notes.read_text().strip()), 200)

    def test_workflow_uses_version_specific_body_path(self):
        text = WORKFLOW.read_text()
        self.assertEqual(
            text.count(
                ".github/RELEASE_NOTES_v${{ needs.resolve-version.outputs.version }}.md"
            ),
            3,
            "each platform job must attach the version-specific notes",
        )

    def test_notes_state_macos_limitations(self):
        notes = (NOTES_DIR / f"RELEASE_NOTES_v{_canonical_version()}.md").read_text()
        low = notes.lower()
        for required in ("arm64", "not notarized", "experimental"):
            self.assertIn(required, low, f"notes must state: {required}")

    def test_notes_disclaim_unsupported_macos_builds(self):
        """Out-of-scope macOS variants must appear only as explicit exclusions.

        A bare substring check is wrong here - "no universal2 build" is a
        correct disclaimer, not a claim - so assert the negated phrasing.
        """
        low = (NOTES_DIR / f"RELEASE_NOTES_v{_canonical_version()}.md").read_text().lower()
        for disclaimer in ("no intel build", "no universal2 build", "not developer id signed"):
            self.assertIn(disclaimer, low, f"notes must state: {disclaimer}")
        # Rosetta implies Intel support and must not appear at all.
        self.assertNotIn("rosetta", low)
        # Automatic macOS install is not implemented.
        self.assertIn("not** installed automatically", low)


class SidecarOrderingTest(unittest.TestCase):
    """Sidecars must be generated before uploads, and be uploaded."""

    def setUp(self):
        self.text = WORKFLOW.read_text()

    def _assert_sidecars_before_uploads(self, job: str):
        block = _job_block(self.text, job)
        gen = block.index("name: Generate SHA256 sidecars")
        uploads = [m.start() for m in re.finditer(r"name: Upload ", block)]
        self.assertTrue(uploads, f"{job} uploads nothing")
        self.assertTrue(
            all(gen < u for u in uploads),
            f"{job} uploads before generating sidecars; artifacts would omit them",
        )

    def test_linux_generates_sidecars_before_upload(self):
        self._assert_sidecars_before_uploads("build-linux")

    def test_windows_generates_sidecars_before_upload(self):
        self._assert_sidecars_before_uploads("build-windows")

    def test_macos_generates_sidecars_before_upload(self):
        self._assert_sidecars_before_uploads("build-macos")

    def test_linux_uploads_include_sidecars(self):
        block = _job_block(self.text, "build-linux")
        self.assertIn("release/*.AppImage.sha256", block)
        self.assertIn("release/*.deb.sha256", block)

    def test_windows_uploads_include_sidecars(self):
        block = _job_block(self.text, "build-windows")
        self.assertIn("release/*-Setup.exe.sha256", block)
        self.assertIn("release/*-Portable.exe.sha256", block)


class PackagedSmokeCoverageTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_linux_smokes_the_appimage(self):
        block = _job_block(self.text, "build-linux")
        self.assertIn("smoke_tab_web.py --exe \"$APPIMAGE\"", block)
        self.assertIn("x86_64.AppImage", block)

    def test_linux_installs_smokes_and_removes_the_deb(self):
        block = _job_block(self.text, "build-linux")
        self.assertIn("apt-get install -y", block)
        self.assertIn("smoke_tab_web.py --exe \"$INSTALLED\"", block)
        self.assertIn("apt-get remove -y cove-meme-maker", block)
        self.assertIn("Status: install ok installed", block)

    def test_windows_smokes_portable(self):
        block = _job_block(self.text, "build-windows")
        self.assertIn("smoke_launch_windows.ps1", block)
        self.assertIn("-Portable.exe", block)

    def test_windows_installs_smokes_and_uninstalls_setup(self):
        block = _job_block(self.text, "build-windows")
        self.assertIn("/VERYSILENT", block)
        self.assertIn("/DIR=$installDir", block)
        self.assertIn("unins000.exe", block)
        self.assertIn("Uninstaller failed with exit code", block)

    def test_windows_setup_installs_to_temp_not_permanent(self):
        block = _job_block(self.text, "build-windows")
        self.assertIn("RUNNER_TEMP", block)

    def test_macos_packaged_smoke_preserved(self):
        block = _job_block(self.text, "build-macos")
        self.assertIn("smoke_tab_web.py --exe", block)
        self.assertIn("runs-on: macos-14", block)
        self.assertIn("lipo -archs", block)


class WorkflowStabilityTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_triggers_unchanged(self):
        self.assertIn("  push:\n    tags:\n      - 'v*'", self.text)
        self.assertIn("workflow_dispatch:", self.text)

    def test_all_three_platform_jobs_present(self):
        for job in ("build-linux", "build-macos", "build-windows"):
            self.assertIn(f"  {job}:", self.text)

    def test_no_tagging_or_pushing_in_workflow(self):
        for banned in ("git tag", "git push"):
            self.assertNotIn(banned, self.text)


if __name__ == "__main__":
    unittest.main()
