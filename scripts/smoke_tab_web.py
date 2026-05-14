#!/usr/bin/env python3
"""Protocol smoke test for cove-meme-maker tab-web mode.

Creates a temporary Unix socket listener, launches the app with Nexus env vars,
then verifies:
  - app_ready message received with correct fields
  - tab_ready message received with correct fields
  - tab_ready.url starts with http://127.0.0.1:
  - tab_ready.runId matches the test run id
  - GET / returns HTML
  - /render happy path (1x1 white PNG)
  - /render rejects missing image_b64 (400)
  - /render rejects invalid base64 (400)
  - /render rejects oversized body claim (413)
  - process exits cleanly after socket close
  - no Qt window is constructed (process does not hang)

Run from the repo root (source):
  python scripts/smoke_tab_web.py

Run against a packaged executable or AppImage:
  python scripts/smoke_tab_web.py --exe /path/to/Cove-Meme-Maker-x.y.z.AppImage
"""
import base64
import io
import json
import os
import pathlib
import re
import socket
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")

RUN_ID = "smoke-test-001"
TIMEOUT = 10


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _minimal_png_b64() -> str:
    """Return a base64-encoded 1×1 white PNG."""
    # Minimal valid PNG: IHDR + IDAT + IEND
    def _chunk(tag: bytes, data: bytes) -> bytes:
        import zlib
        ln = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return ln + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\xff\xff"
    import zlib
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return base64.b64encode(sig + ihdr + idat + iend).decode("ascii")


def _http_post_json(url: str, payload: dict, timeout: int = 5):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Tab-web smoke test")
    parser.add_argument(
        "--exe",
        metavar="PATH",
        help="Packaged executable to test (AppImage or binary). "
             "Defaults to running from source via python -m cove_meme_maker.",
    )
    args = parser.parse_args()

    if args.exe:
        exe_path = pathlib.Path(args.exe).resolve()
        if not exe_path.exists():
            fail(f"--exe path does not exist: {exe_path}")
        print(f"Testing packaged executable: {exe_path}")
        cmd = [str(exe_path)]
        extra_env: dict = {}
    else:
        print("Testing source (python -m cove_meme_maker)")
        cmd = [sys.executable, "-m", "cove_meme_maker"]
        existing_path = os.environ.get("PYTHONPATH", "")
        python_path = SRC_DIR + (os.pathsep + existing_path if existing_path else "")
        extra_env = {"PYTHONPATH": python_path}

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "nexus.sock")

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(sock_path)
        listener.listen(1)
        listener.settimeout(TIMEOUT)

        env = {
            **os.environ,
            **extra_env,
            "COVE_NEXUS": "1",
            "COVE_NEXUS_OPEN_MODE": "tab-web",
            "COVE_NEXUS_SOCKET": sock_path,
            "COVE_NEXUS_RUN_ID": RUN_ID,
            "COVE_NEXUS_PROTOCOL_VERSION": "1",
        }

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            conn, _ = listener.accept()
        except socket.timeout:
            proc.kill()
            fail("app did not connect to socket within timeout")

        listener.close()
        conn.settimeout(TIMEOUT)
        f = conn.makefile("rb")

        # --- app_ready ---
        try:
            line1 = f.readline()
        except socket.timeout:
            proc.kill()
            fail("no app_ready message received")
        if not line1:
            proc.kill()
            fail("socket closed before app_ready")

        msg1 = json.loads(line1)
        assert msg1.get("type") == "app_ready", f"expected app_ready, got {msg1}"
        assert msg1.get("runId") == RUN_ID, f"runId mismatch: {msg1}"
        assert msg1.get("protocolVersion") == 1, f"protocolVersion mismatch: {msg1}"
        assert "ts" in msg1, f"missing ts in app_ready: {msg1}"
        print(f"  app_ready OK  ts={msg1['ts']}")

        # --- tab_ready ---
        try:
            line2 = f.readline()
        except socket.timeout:
            proc.kill()
            fail("no tab_ready message received")
        if not line2:
            proc.kill()
            fail("socket closed before tab_ready")

        msg2 = json.loads(line2)
        assert msg2.get("type") == "tab_ready", f"expected tab_ready, got {msg2}"
        assert msg2.get("runId") == RUN_ID, f"runId mismatch: {msg2}"
        assert msg2.get("protocolVersion") == 1, f"protocolVersion mismatch: {msg2}"
        assert "ts" in msg2, f"missing ts in tab_ready: {msg2}"
        url = msg2.get("url", "")
        assert url.startswith("http://127.0.0.1:"), f"url must start with http://127.0.0.1:, got {url!r}"
        assert not url.startswith("http://localhost"), f"url must not use localhost, got {url!r}"
        print(f"  tab_ready OK  url={url}")

        # --- HTTP GET / ---
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            html_body = resp.read()
            assert b"Cove Meme Maker" in html_body, "HTML page missing expected title"
            print(f"  HTTP GET / OK  ({len(html_body)} bytes)")
        except Exception as exc:
            proc.kill()
            fail(f"HTTP server not reachable: {exc}")

        render_url = url.rstrip("/") + "/render"

        # --- /render happy path ---
        status, data = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "style": "classic",
            "top": "HELLO",
            "bottom": "WORLD",
        })
        assert status == 200, f"/render happy path: expected 200, got {status}: {data}"
        assert "preview_b64" in data, f"/render missing preview_b64: {data}"
        preview_bytes = base64.b64decode(data["preview_b64"])
        assert preview_bytes[:4] == b"\x89PNG", f"/render preview_b64 not a PNG"
        print(f"  /render happy path OK  (preview {len(preview_bytes)} bytes)")

        # --- /render missing image_b64 ---
        status2, data2 = _http_post_json(render_url, {"top": "X"})
        assert status2 == 400, f"/render missing image_b64: expected 400, got {status2}"
        print(f"  /render missing image_b64 → 400 OK")

        # --- /render invalid base64 ---
        status3, data3 = _http_post_json(render_url, {"image_b64": "!!!notbase64!!!"})
        assert status3 == 400, f"/render invalid base64: expected 400, got {status3}"
        print(f"  /render invalid base64 → 400 OK")

        # --- /render oversized Content-Length claim ---
        big_body = json.dumps({"image_b64": "A"}).encode()
        req_big = urllib.request.Request(
            render_url,
            data=big_body,
            headers={"Content-Type": "application/json",
                     "Content-Length": str(21 * 1024 * 1024)},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req_big, timeout=5) as r:
                status4 = r.status
        except urllib.error.HTTPError as e:
            status4 = e.code
        assert status4 == 413, f"/render oversized: expected 413, got {status4}"
        print(f"  /render oversized body → 413 OK")

        # -------------------------------------------------------
        # /templates list
        # -------------------------------------------------------
        templates_url = url.rstrip("/") + "/templates"
        try:
            resp_tmpl = urllib.request.urlopen(templates_url, timeout=5)
        except Exception as exc:
            proc.kill()
            fail(f"GET /templates unreachable: {exc}")
        assert resp_tmpl.status == 200, \
            f"/templates: expected 200, got {resp_tmpl.status}"
        ctype_tmpl = resp_tmpl.getheader("Content-Type", "")
        assert "application/json" in ctype_tmpl, \
            f"/templates Content-Type: expected application/json, got {ctype_tmpl!r}"
        tmpl_data = json.loads(resp_tmpl.read())
        assert isinstance(tmpl_data, dict), \
            f"/templates: expected JSON object, got {type(tmpl_data)}"
        assert "templates" in tmpl_data, \
            f"/templates: missing 'templates' key: {tmpl_data}"
        templates = tmpl_data["templates"]
        assert isinstance(templates, list), \
            f"/templates: 'templates' must be a list, got {type(templates)}"
        assert len(templates) >= 1, \
            f"/templates: expected at least one starter template, got {len(templates)}"
        print(f"  GET /templates list → 200 OK  ({len(templates)} templates)")

        # slug safety: each id must match the server's slug pattern
        _SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
        for t in templates:
            tid = t.get("id", "")
            assert _SLUG_RE.match(tid), \
                f"/templates: id {tid!r} is not a safe slug"
            turl = t.get("url", "")
            assert not turl.startswith("http://") and not turl.startswith("https://"), \
                f"/templates: url {turl!r} must be relative, not a remote URL"
        print(f"  /templates slug safety and no remote URLs  OK")

        # no absolute filesystem paths exposed in template metadata
        def _assert_no_abs_paths(obj: object, label: str) -> None:
            if isinstance(obj, str):
                for prefix in ("/home/", "/root/", "/etc/", "/usr/", "/var/", "/tmp/"):
                    assert not obj.startswith(prefix), \
                        f"{label}: absolute path leak: {obj!r}"
            elif isinstance(obj, dict):
                for v in obj.values():
                    _assert_no_abs_paths(v, label)
            elif isinstance(obj, list):
                for v in obj:
                    _assert_no_abs_paths(v, label)

        _assert_no_abs_paths(tmpl_data, "GET /templates")
        print(f"  /templates no absolute path exposure  OK")

        # fetch first listed template image → 200 + image bytes
        first_slug = templates[0]["id"]
        tmpl_img_url = url.rstrip("/") + "/templates/" + first_slug
        try:
            resp_img = urllib.request.urlopen(tmpl_img_url, timeout=5)
        except Exception as exc:
            proc.kill()
            fail(f"GET /templates/{first_slug} unreachable: {exc}")
        assert resp_img.status == 200, \
            f"GET /templates/{first_slug}: expected 200, got {resp_img.status}"
        img_bytes = resp_img.read()
        assert len(img_bytes) >= 8, \
            f"GET /templates/{first_slug}: response too short ({len(img_bytes)} bytes)"
        assert img_bytes[:4] == b"\x89PNG", \
            f"GET /templates/{first_slug}: expected PNG magic, got {img_bytes[:4]!r}"
        print(f"  GET /templates/{first_slug} → 200 PNG OK  ({len(img_bytes)} bytes)")

        # unknown template ID → 404 with JSON error body
        unknown_url = url.rstrip("/") + "/templates/does-not-exist-xyz"
        try:
            urllib.request.urlopen(unknown_url, timeout=5)
            proc.kill()
            fail("/templates/does-not-exist-xyz: expected 404, got 200")
        except urllib.error.HTTPError as e:
            assert e.code == 404, \
                f"/templates/does-not-exist-xyz: expected 404, got {e.code}"
            err_body = json.loads(e.read())
            assert "error" in err_body, \
                f"/templates/does-not-exist-xyz: missing 'error' in 404 body: {err_body}"
        print(f"  /templates/does-not-exist-xyz → 404 JSON OK")

        # traversal / invalid slug attempts → safe 4xx
        traversal_cases = [
            ("blank%20white",  "percent-encoded slug"),
            ("BLANK-WHITE",    "uppercase slug"),
            ("blank_white",    "underscore slug"),
            ("..%2fetc%2fpasswd", "percent-encoded path traversal"),
        ]
        for bad_slug, label in traversal_cases:
            bad_url = url.rstrip("/") + "/templates/" + bad_slug
            try:
                urllib.request.urlopen(bad_url, timeout=5)
                proc.kill()
                fail(f"/templates/{bad_slug!r} ({label}): expected 4xx, got 200")
            except urllib.error.HTTPError as e:
                assert e.code in (400, 404), \
                    f"/templates/{bad_slug!r} ({label}): expected 4xx, got {e.code}"
        print(f"  /templates traversal/invalid slugs safely rejected  OK")

        # -------------------------------------------------------
        # /render with draggable position payloads
        # -------------------------------------------------------

        # valid positions → 200 + PNG
        status_pos, data_pos = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "style": "classic",
            "top": "HELLO",
            "bottom": "WORLD",
            "top_pos": [0.25, 0.20],
            "bottom_pos": [0.75, 0.80],
        })
        assert status_pos == 200, \
            f"/render valid positions: expected 200, got {status_pos}: {data_pos}"
        assert "preview_b64" in data_pos, \
            f"/render valid positions: missing preview_b64: {data_pos}"
        pos_png = base64.b64decode(data_pos["preview_b64"])
        assert pos_png[:4] == b"\x89PNG", \
            f"/render valid positions: preview_b64 not a PNG"
        print(f"  /render valid top_pos + bottom_pos → 200 PNG OK")

        # absent positions → 200 (preserves default server placement path)
        status_nopos, data_nopos = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "style": "classic",
            "top": "HELLO",
            "bottom": "WORLD",
        })
        assert status_nopos == 200, \
            f"/render absent positions: expected 200, got {status_nopos}: {data_nopos}"
        assert "preview_b64" in data_nopos, \
            f"/render absent positions: missing preview_b64"
        print(f"  /render absent positions → 200 OK")

        # explicit null positions → 200 (same default path)
        status_null, data_null = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "style": "classic",
            "top": "HELLO",
            "bottom": "WORLD",
            "top_pos": None,
            "bottom_pos": None,
        })
        assert status_null == 200, \
            f"/render null positions: expected 200, got {status_null}: {data_null}"
        print(f"  /render null positions → 200 OK")

        # out-of-range positions → 200 (server clamps, does not reject)
        status_oor, data_oor = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "style": "classic",
            "top_pos": [-1.0, 2.0],
            "bottom_pos": [1.5, -0.5],
        })
        assert status_oor == 200, \
            f"/render out-of-range positions: expected 200 (clamped), got {status_oor}: {data_oor}"
        print(f"  /render out-of-range positions → 200 (clamped)  OK")

        # malformed: string → 400
        s_str, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": "center",
        })
        assert s_str == 400, \
            f"/render top_pos='center' (string): expected 400, got {s_str}"
        print(f"  /render top_pos='center' (string) → 400 OK")

        # malformed: wrong array length → 400
        s_len, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": [0.5],
        })
        assert s_len == 400, \
            f"/render top_pos=[0.5] (length 1): expected 400, got {s_len}"
        print(f"  /render top_pos=[0.5] (wrong length) → 400 OK")

        # malformed: string values inside array → 400
        s_strval, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": ["left", "top"],
        })
        assert s_strval == 400, \
            f"/render top_pos=['left','top'] (string values): expected 400, got {s_strval}"
        print(f"  /render top_pos=['left','top'] (string values) → 400 OK")

        # malformed: object/dict → 400
        s_obj, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": {"x": 0.5, "y": 0.5},
        })
        assert s_obj == 400, \
            f"/render top_pos={{...}} (object): expected 400, got {s_obj}"
        print(f"  /render top_pos={{...}} (object) → 400 OK")

        # malformed: NaN → 400 (json.dumps encodes float('nan') as NaN;
        # server's json.loads rejects the non-standard token → 400 bad request)
        s_nan, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": [float("nan"), 0.5],
        })
        assert s_nan == 400, \
            f"/render top_pos=[NaN, 0.5]: expected 400, got {s_nan}"
        print(f"  /render top_pos=[NaN, 0.5] → 400 OK")

        # malformed: Infinity → 400 (same mechanism as NaN)
        s_inf, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": [float("inf"), 0.5],
        })
        assert s_inf == 400, \
            f"/render top_pos=[Infinity, 0.5]: expected 400, got {s_inf}"
        print(f"  /render top_pos=[Infinity, 0.5] → 400 OK")

        # malformed: one valid + one malformed → 400 (both fields validated)
        s_mix, _ = _http_post_json(render_url, {
            "image_b64": _minimal_png_b64(),
            "top_pos": [0.5, 0.1],
            "bottom_pos": "bottom",
        })
        assert s_mix == 400, \
            f"/render valid top_pos + malformed bottom_pos: expected 400, got {s_mix}"
        print(f"  /render valid top_pos + malformed bottom_pos → 400 OK")

        # --- clean shutdown on socket close ---
        f.close()   # close file-object first to release the dup'd fd
        conn.close()
        try:
            rc = proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            fail("process did not exit after socket close")

        assert rc == 0, f"non-zero exit code: {rc}"
        print(f"  clean exit OK  rc={rc}")

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
