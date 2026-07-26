"""Focused tests for the Nexus/tab-web execution path.

Covers the properties the desktop app and the smoke test depend on:

* the tab-web server module imports no Qt (server-only path is headless);
* the ``python -m cove_meme_maker`` entrypoint takes the tab-web branch
  *before* any Qt import, verified with a PySide6 import tripwire;
* the server binds ``127.0.0.1`` and completes its readiness handshake;
* the /render token-bucket limiter keeps its production defaults while the
  env override used by the smoke removes rate limiting deterministically;
* the ``modern`` style routes through ``_render_modern`` (caption band) and is
  never silently downgraded to ``classic``.
"""
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC_DIR)

from PIL import Image  # noqa: E402

from cove_meme_maker.image_renderer import MemeSpec, render  # noqa: E402
import cove_meme_maker.tab_web as tab_web  # noqa: E402
from cove_meme_maker.tab_web import (  # noqa: E402
    _RenderRateLimiter,
    _rate_limit_params,
)

_QT_MODULES = ("PySide6", "PyQt6", "PyQt5", "PySide2")

_TRIPWIRE = 'raise RuntimeError("Qt imported in tab-web mode")\n'


def _child_env(*extra_paths: str, **overrides: str) -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in (*extra_paths, SRC_DIR, existing) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.update(overrides)
    return env


class TabWebImportOrderTest(unittest.TestCase):
    def test_tab_web_import_pulls_no_qt(self):
        """Importing the server module (and renderer) must not pull in Qt."""
        script = textwrap.dedent(
            """
            import sys
            import cove_meme_maker.tab_web            # noqa: F401
            import cove_meme_maker.image_renderer     # noqa: F401
            bad = [m for m in ("PySide6", "PyQt6", "PyQt5", "PySide2")
                   if m in sys.modules]
            if bad:
                print("QT_IMPORTED:" + ",".join(bad))
                sys.exit(1)
            print("OK")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"tab-web import pulled in Qt: {proc.stdout}{proc.stderr}",
        )
        self.assertIn("OK", proc.stdout)

    def test_pyside6_tripwire_fires_on_direct_import(self):
        """The tripwire used by the gate test must actually shadow PySide6.

        Without this control the gate test could pass simply because Qt is not
        installed, giving false confidence.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "PySide6"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(_TRIPWIRE)
            proc = subprocess.run(
                [sys.executable, "-c", "import PySide6"],
                env=_child_env(tmp),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Qt imported in tab-web mode", proc.stderr)

    def test_gate_selects_tab_web_before_qt(self):
        """`python -m cove_meme_maker` in tab-web mode must reach readiness
        without importing Qt, bind 127.0.0.1, and exit cleanly.

        A PySide6 import tripwire sits ahead of the real package on the child's
        path: if the gate imported Qt before branching, the child would crash
        before app_ready and this test would fail.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "PySide6"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(_TRIPWIRE)

            sock_path = os.path.join(tmp, "nexus.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(sock_path)
            listener.listen(1)
            listener.settimeout(15)

            env = _child_env(
                tmp,
                COVE_NEXUS="1",
                COVE_NEXUS_OPEN_MODE="tab-web",
                COVE_NEXUS_SOCKET=sock_path,
                COVE_NEXUS_RUN_ID="gate-test-001",
            )
            proc = subprocess.Popen(
                [sys.executable, "-m", "cove_meme_maker"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    proc.kill()
                    _, err = proc.communicate(timeout=10)
                    self.fail(
                        "child never connected (Qt tripwire may have fired): "
                        + err.decode(errors="replace")
                    )
                listener.close()
                conn.settimeout(15)
                f = conn.makefile("rb")

                msg1 = json.loads(f.readline())
                self.assertEqual(msg1.get("type"), "app_ready")
                self.assertEqual(msg1.get("runId"), "gate-test-001")

                msg2 = json.loads(f.readline())
                self.assertEqual(msg2.get("type"), "tab_ready")
                url = msg2.get("url", "")
                self.assertTrue(
                    url.startswith("http://127.0.0.1:"),
                    f"url must bind 127.0.0.1, got {url!r}",
                )
                self.assertFalse(url.startswith("http://localhost"))

                f.close()
                conn.close()
                rc = proc.wait(timeout=15)
                self.assertEqual(rc, 0, "child did not exit cleanly")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)


class RenderRateLimiterTest(unittest.TestCase):
    def test_default_limits_burst(self):
        """Default production limiter allows the burst capacity, then denies."""
        limiter = _RenderRateLimiter()  # production defaults: capacity 10
        allowed = sum(1 for _ in range(10) if limiter.acquire())
        self.assertEqual(allowed, 10)
        self.assertFalse(limiter.acquire(), "11th immediate acquire must be denied")

    def test_env_override_raises_capacity(self):
        saved = {k: os.environ.get(k) for k in
                 ("COVE_NEXUS_RENDER_RATE_CAPACITY", "COVE_NEXUS_RENDER_RATE_REFILL")}
        try:
            # No env → production defaults, byte-identical to before.
            for k in saved:
                os.environ.pop(k, None)
            self.assertEqual(_rate_limit_params(), (10.0, 4.0))

            # Override → honored.
            os.environ["COVE_NEXUS_RENDER_RATE_CAPACITY"] = "100000"
            os.environ["COVE_NEXUS_RENDER_RATE_REFILL"] = "100000"
            cap, refill = _rate_limit_params()
            self.assertEqual((cap, refill), (100000.0, 100000.0))
            limiter = _RenderRateLimiter(cap, refill)
            self.assertTrue(all(limiter.acquire() for _ in range(1000)))

            # Invalid / non-positive → fall back to defaults.
            os.environ["COVE_NEXUS_RENDER_RATE_CAPACITY"] = "not-a-number"
            os.environ["COVE_NEXUS_RENDER_RATE_REFILL"] = "0"
            self.assertEqual(_rate_limit_params(), (10.0, 4.0))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class ModernStylePathTest(unittest.TestCase):
    def test_modern_adds_band_classic_preserves_dims(self):
        """`modern` routes to _render_modern (taller output); `classic` keeps
        the source dimensions. Proves modern is not downgraded to classic."""
        src = Image.new("RGB", (64, 64), (20, 120, 200))

        modern = render(src, MemeSpec(style="modern", caption="a caption"))
        classic = render(src, MemeSpec(style="classic", top="HI", bottom="THERE"))

        self.assertEqual(classic.size, (64, 64), "classic must preserve dims")
        self.assertEqual(modern.width, 64)
        self.assertGreater(
            modern.height, 64,
            "modern must prepend a caption band (taller than source)",
        )
        self.assertGreater(
            modern.height, classic.height,
            "modern output must be taller than classic for the same source",
        )

    def test_modern_output_is_nonblank(self):
        """The modern band must contain rendered caption pixels (not all white)."""
        src = Image.new("RGB", (64, 64), (20, 120, 200))
        out = render(src, MemeSpec(style="modern", caption="VISIBLE"))
        colors = out.convert("RGB").getcolors(maxcolors=100000)
        self.assertIsNotNone(colors)
        # More than just the white band + solid source → text pixels present.
        self.assertGreater(len(colors), 2, "modern caption produced no text pixels")


class TabWebOverlayRenderTest(unittest.TestCase):
    """HTTP-level /render tests for the "Add Image" overlay port.

    Spins up an in-process ThreadingHTTPServer with the real handler and a
    high-capacity token bucket so request bursts are never throttled.
    """

    @classmethod
    def setUpClass(cls):
        cls._saved_limiter = tab_web._render_rate_limiter
        tab_web._render_rate_limiter = _RenderRateLimiter(100000.0, 100000.0)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), tab_web._Handler)
        cls._thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls._thread.start()
        cls._url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/render"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        tab_web._render_rate_limiter = cls._saved_limiter

    @staticmethod
    def _png_b64(color, size=(64, 64)) -> str:
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _post(self, payload: dict) -> "tuple[int, dict]":
        req = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _render_ok(self, payload: dict) -> Image.Image:
        status, data = self._post(payload)
        self.assertEqual(status, 200, f"render failed: {data}")
        raw = base64.b64decode(data["preview_b64"])
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n", "response is not a PNG")
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def test_single_overlay_changes_output(self):
        base = self._png_b64((20, 120, 200))
        ovl = self._png_b64((255, 0, 0))
        plain = self._render_ok({"image_b64": base})
        with_ovl = self._render_ok({
            "image_b64": base,
            "overlays": [{"image_b64": ovl, "x": 0.5, "y": 0.5, "width": 0.5}],
        })
        self.assertEqual(plain.size, with_ovl.size)
        self.assertNotEqual(plain.tobytes(), with_ovl.tobytes(),
                            "overlay render must differ from no-overlay render")
        self.assertEqual(with_ovl.getpixel((32, 32)), (255, 0, 0),
                         "overlay colour must appear at the base centre")

    def test_later_overlay_wins_at_overlap(self):
        base = self._png_b64((20, 120, 200))
        red = self._png_b64((255, 0, 0))
        blue = self._png_b64((0, 0, 255))

        def _stacked(first_b64, second_b64):
            return self._render_ok({
                "image_b64": base,
                "overlays": [
                    {"image_b64": first_b64, "x": 0.5, "y": 0.5, "width": 0.5},
                    {"image_b64": second_b64, "x": 0.5, "y": 0.5, "width": 0.5},
                ],
            })

        self.assertEqual(_stacked(red, blue).getpixel((32, 32)), (0, 0, 255),
                         "later overlay must render on top")
        self.assertEqual(_stacked(blue, red).getpixel((32, 32)), (255, 0, 0),
                         "reversing the order must reverse the overlap colour")

    def test_rotation_90_differs_from_rotation_0(self):
        base = self._png_b64((20, 120, 200))
        # Non-square overlay: rotation visibly changes the footprint.
        ovl = self._png_b64((255, 0, 0), size=(64, 32))

        def _rot(deg):
            return self._render_ok({
                "image_b64": base,
                "overlays": [{"image_b64": ovl, "x": 0.5, "y": 0.5,
                              "width": 0.5, "rotation": deg}],
            })

        r0 = _rot(0)
        r90 = _rot(90)
        self.assertNotEqual(r0.tobytes(), r90.tobytes(),
                            "rotation=90 must differ from rotation=0")

    def test_invalid_overlays_rejected(self):
        base = self._png_b64((20, 120, 200))
        ovl = self._png_b64((255, 0, 0))

        status, data = self._post({"image_b64": base, "overlays": "not-a-list"})
        self.assertEqual(status, 400, f"non-array overlays must 400: {data}")

        status, data = self._post({
            "image_b64": base,
            "overlays": [{"image_b64": ovl} for _ in range(9)],
        })
        self.assertEqual(status, 400, f"9 overlays must 400: {data}")

        status, data = self._post({
            "image_b64": base,
            "overlays": [{"image_b64": "!!!notbase64!!!"}],
        })
        self.assertEqual(status, 400, f"invalid overlay base64 must 400: {data}")

        status, data = self._post({
            "image_b64": base,
            "overlays": [{"x": 0.5, "y": 0.5}],
        })
        self.assertEqual(status, 400, f"missing image_b64 must 400: {data}")

    def test_overlay_position_boundaries_accepted(self):
        """x/y at (0,0) and (1,1) must render fine (renderer does not clamp
        beyond the [0,1] input validation)."""
        base = self._png_b64((20, 120, 200))
        ovl = self._png_b64((255, 0, 0))
        for x, y in ((0.0, 0.0), (1.0, 1.0)):
            status, data = self._post({
                "image_b64": base,
                "overlays": [{"image_b64": ovl, "x": x, "y": y, "width": 0.3}],
            })
            self.assertEqual(status, 200, f"overlay at ({x}, {y}) must 200: {data}")


if __name__ == "__main__":
    unittest.main()
