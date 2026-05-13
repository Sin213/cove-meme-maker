#!/usr/bin/env python3
"""Protocol smoke test for cove-meme-maker tab-web mode.

Creates a temporary Unix socket listener, launches the app with Nexus env vars,
then verifies:
  - app_ready message received with correct fields
  - tab_ready message received with correct fields
  - tab_ready.url starts with http://127.0.0.1:
  - tab_ready.runId matches the test run id
  - process exits cleanly after socket close
  - no Qt window is constructed (process does not hang)

Run from the repo root:
  python scripts/smoke_tab_web.py
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")

RUN_ID = "smoke-test-001"
TIMEOUT = 10


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "nexus.sock")

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(sock_path)
        listener.listen(1)
        listener.settimeout(TIMEOUT)

        # Ensure the package src dir is on PYTHONPATH for the subprocess
        # (supports both editable-installed and bare source checkouts).
        existing_path = os.environ.get("PYTHONPATH", "")
        python_path = SRC_DIR + (os.pathsep + existing_path if existing_path else "")
        env = {
            **os.environ,
            "PYTHONPATH": python_path,
            "COVE_NEXUS": "1",
            "COVE_NEXUS_OPEN_MODE": "tab-web",
            "COVE_NEXUS_SOCKET": sock_path,
            "COVE_NEXUS_RUN_ID": RUN_ID,
            "COVE_NEXUS_PROTOCOL_VERSION": "1",
        }

        proc = subprocess.Popen(
            [sys.executable, "-m", "cove_meme_maker"],
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

        # --- HTTP server reachable ---
        import urllib.request
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            html_body = resp.read()
            assert b"Cove Meme Maker" in html_body, "HTML page missing expected title"
            print(f"  HTTP GET / OK  ({len(html_body)} bytes)")
        except Exception as exc:
            proc.kill()
            fail(f"HTTP server not reachable: {exc}")

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
