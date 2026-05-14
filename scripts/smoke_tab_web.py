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
