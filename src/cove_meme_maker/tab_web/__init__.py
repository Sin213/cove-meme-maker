"""Tab-web mode runner for cove-meme-maker.

Activated when all four env vars are set:
  COVE_NEXUS=1
  COVE_NEXUS_OPEN_MODE=tab-web
  COVE_NEXUS_SOCKET=<unix socket path>
  COVE_NEXUS_RUN_ID=<run id>

Binds ThreadingHTTPServer to 127.0.0.1:0 and announces the URL via NDJSON
over the Nexus Unix domain socket.  No PySide6/Qt is imported in this path.
"""
from __future__ import annotations

import base64
import html
import io
import json
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _send_msg(sock: socket.socket, **fields) -> None:
    line = json.dumps(fields, separators=(",", ":")) + "\n"
    sock.sendall(line.encode("utf-8"))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# /render request and image size limits
# ---------------------------------------------------------------------------

_MAX_REQUEST_BODY = 20 * 1024 * 1024   # 20 MB — JSON body including base64 image
_MAX_IMAGE_BYTES  = 10 * 1024 * 1024   # 10 MB — decoded image bytes
_MAX_IMAGE_PIXELS = 4096 * 4096        # 16 MP — source image width × height

# Minimal HTML page
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cove Meme Maker — tab-web mode</title>
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; script-src 'unsafe-inline'">
<style>
body {
  font-family: system-ui, sans-serif;
  max-width: 640px;
  margin: 2rem auto;
  padding: 0 1rem;
  background: #1a1a2e;
  color: #eee;
}
h1 { font-size: 1.2rem; color: #a0c4ff; margin-bottom: 0.2rem; }
.meta { font-size: 0.75rem; color: #666; margin-bottom: 1.5rem; }
label { display: block; margin-bottom: 0.25rem; font-size: 0.85rem; color: #aaa; }
input[type=text], select {
  width: 100%;
  box-sizing: border-box;
  padding: 0.4rem 0.6rem;
  background: #2a2a3e;
  border: 1px solid #444;
  border-radius: 4px;
  color: #eee;
  margin-bottom: 0.75rem;
}
input[type=file] { margin-bottom: 0.75rem; }
button {
  padding: 0.5rem 1.2rem;
  background: #4a7fbf;
  border: none;
  border-radius: 4px;
  color: #fff;
  cursor: pointer;
  margin-right: 0.5rem;
}
button:disabled { opacity: 0.4; cursor: not-allowed; }
#preview img { max-width: 100%; border-radius: 6px; margin-top: 1rem; }
#status { font-size: 0.8rem; color: #aaa; margin-top: 0.5rem; min-height: 1.2em; }
.note {
  background: #2a2a1e;
  border-left: 3px solid #a08040;
  padding: 0.5rem 0.75rem;
  font-size: 0.8rem;
  color: #cca;
  margin-top: 1.5rem;
  border-radius: 0 4px 4px 0;
}
</style>
</head>
<body>
<h1>Cove Meme Maker — tab-web mode</h1>
<p class="meta">Session: <code id="sessionId" data-run-id="__RUN_ID_ATTR__"></code></p>

<label>Source image</label>
<input type="file" id="imageFile" accept="image/*">

<label>Style</label>
<select id="style">
  <option value="classic">Classic (top/bottom text)</option>
  <option value="modern">Modern (caption band)</option>
</select>

<div id="classicFields">
  <label>Top text</label>
  <input type="text" id="topText" placeholder="TOP TEXT">

  <label>Bottom text</label>
  <input type="text" id="bottomText" placeholder="BOTTOM TEXT">
</div>

<div id="modernFields" style="display:none">
  <label>Caption</label>
  <input type="text" id="captionText" placeholder="Caption">
</div>

<button id="renderBtn" disabled>Render</button>
<button id="exportBtn" disabled>Export PNG</button>

<div id="status"></div>
<div id="preview"></div>

<div class="note">
  <strong>Phase 2 scope:</strong> drag handles, font picker, colour picker,
  rotation, template discovery, and full UI parity are deferred to a later phase.
</div>

<script>
(function () {
  var sessionEl = document.getElementById('sessionId');
  var RUN_ID = sessionEl.dataset.runId || '';
  sessionEl.textContent = RUN_ID;

  var styleEl   = document.getElementById('style');
  var classic   = document.getElementById('classicFields');
  var modern    = document.getElementById('modernFields');
  styleEl.addEventListener('change', function () {
    classic.style.display = styleEl.value === 'classic' ? '' : 'none';
    modern.style.display  = styleEl.value === 'modern'  ? '' : 'none';
  });

  var fileInput = document.getElementById('imageFile');
  var renderBtn = document.getElementById('renderBtn');
  var exportBtn = document.getElementById('exportBtn');
  var statusEl  = document.getElementById('status');
  var previewEl = document.getElementById('preview');
  var lastPng   = null;

  fileInput.addEventListener('change', function () {
    renderBtn.disabled = !fileInput.files.length;
  });

  renderBtn.addEventListener('click', function () {
    if (!fileInput.files.length) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      var b64 = e.target.result.split(',')[1];
      statusEl.textContent = 'Rendering…';
      renderBtn.disabled = true;
      exportBtn.disabled = true;
      fetch('/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_b64: b64,
          style:     styleEl.value,
          top:       document.getElementById('topText').value,
          bottom:    document.getElementById('bottomText').value,
          caption:   document.getElementById('captionText').value
        })
      })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || r.status); });
        return r.json();
      })
      .then(function (data) {
        lastPng = data.preview_b64;
        previewEl.innerHTML = '';
        var img = new Image();
        img.src = 'data:image/png;base64,' + data.preview_b64;
        previewEl.appendChild(img);
        exportBtn.disabled = false;
        statusEl.textContent = 'Done.';
      })
      .catch(function (err) {
        statusEl.textContent = 'Error: ' + err.message;
      })
      .finally(function () {
        renderBtn.disabled = false;
      });
    };
    reader.readAsDataURL(fileInput.files[0]);
  });

  exportBtn.addEventListener('click', function () {
    if (!lastPng) return;
    var a = document.createElement('a');
    a.href = 'data:image/png;base64,' + lastPng;
    a.download = 'meme.png';
    a.click();
  });
}());
</script>
</body>
</html>
"""


def _build_html(run_id: str) -> bytes:
    attr_val = html.escape(run_id, quote=True)
    return _HTML.replace("__RUN_ID_ATTR__", attr_val).encode("utf-8")


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    # Set once before the server starts.
    _html_cache: bytes = b""

    def log_message(self, fmt, *args) -> None:  # suppress access log
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_html()
        else:
            self._reply(404, "text/plain", b"Not found")

    def do_POST(self) -> None:
        if self.path == "/render":
            self._handle_render()
        else:
            self._reply(404, "text/plain", b"Not found")

    # --- helpers ---

    def _reply(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self) -> None:
        body = _Handler._html_cache
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "img-src 'self' data:; script-src 'unsafe-inline'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, code: int, msg: str) -> None:
        self._reply(code, "application/json",
                    json.dumps({"error": msg}).encode())

    def _handle_render(self) -> None:
        # --- Content-Length validation ---
        raw_cl = self.headers.get("Content-Length")
        if raw_cl is None:
            self._json_error(400, "Content-Length required")
            return
        try:
            length = int(raw_cl)
        except ValueError:
            self._json_error(400, "Content-Length must be an integer")
            return
        if length < 0:
            self._json_error(400, "Content-Length must not be negative")
            return
        if length > _MAX_REQUEST_BODY:
            self._json_error(413, "request body too large")
            return

        # --- parse body ---
        try:
            raw = self.rfile.read(length)
            req = json.loads(raw)
        except Exception as exc:
            self._json_error(400, f"bad request: {exc}")
            return

        if not isinstance(req, dict):
            self._json_error(400, "request body must be a JSON object")
            return

        img_b64: str = req.get("image_b64", "")
        if not img_b64:
            self._json_error(400, "image_b64 required")
            return

        # --- decode and validate image size ---
        try:
            img_bytes = base64.b64decode(img_b64, validate=True)
        except Exception as exc:
            self._json_error(400, f"invalid base64: {exc}")
            return
        if len(img_bytes) > _MAX_IMAGE_BYTES:
            self._json_error(413, "decoded image too large")
            return

        top     = str(req.get("top", ""))
        bottom  = str(req.get("bottom", ""))
        caption = str(req.get("caption", bottom))
        style   = req.get("style", "classic")
        if style not in ("classic", "modern"):
            style = "classic"

        # --- render ---
        try:
            from PIL import Image
            from ..image_renderer import MemeSpec, render as _render

            source = Image.open(io.BytesIO(img_bytes))
            if source.width * source.height > _MAX_IMAGE_PIXELS:
                self._json_error(413, "image dimensions too large")
                return
            spec = MemeSpec(style=style, top=top, bottom=bottom, caption=caption)
            result = _render(source, spec)
            buf = io.BytesIO()
            result.save(buf, format="PNG")
            preview_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as exc:
            self._reply(500, "application/json",
                        json.dumps({"error": f"render error: {exc}"}).encode())
            return

        body = json.dumps({"preview_b64": preview_b64}).encode("utf-8")
        self._reply(200, "application/json", body)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(nexus_socket: str, run_id: str) -> int:
    """Start tab-web mode.  Returns an exit code (0 = clean shutdown)."""

    shutdown = threading.Event()

    def _on_sigterm(signum, frame) -> None:
        shutdown.set()

    signal.signal(signal.SIGTERM, _on_sigterm)

    # 1. Connect to Nexus Unix socket before starting anything else.
    #    If this fails there is no point launching an HTTP server we cannot announce.
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(nexus_socket)
    except OSError as exc:
        print(f"tab-web: cannot connect to {nexus_socket!r}: {exc}", file=sys.stderr)
        return 1

    httpd: ThreadingHTTPServer | None = None

    try:
        # 2. Announce readiness before the HTTP server is up.
        _send_msg(sock, type="app_ready", runId=run_id, ts=_ts(), protocolVersion=1)

        # 3. Bind HTTP server to an ephemeral port on loopback only.
        _Handler._html_cache = _build_html(run_id)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = httpd.server_address[1]

        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        # 4. Tell Nexus the URL.  Literal 127.0.0.1 — never "localhost".
        _send_msg(sock, type="tab_ready", runId=run_id, ts=_ts(),
                  protocolVersion=1, url=f"http://127.0.0.1:{port}/")

        # 5. Watch the socket; EOF means Nexus closed — trigger shutdown.
        def _watch() -> None:
            try:
                while True:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
            except OSError:
                pass
            shutdown.set()

        threading.Thread(target=_watch, daemon=True).start()

        # 6. Block until SIGTERM, socket EOF, or KeyboardInterrupt.
        shutdown.wait()

    except KeyboardInterrupt:
        pass

    finally:
        # 7. Send app_exiting, then clean up resources.
        try:
            _send_msg(sock, type="app_exiting", runId=run_id, ts=_ts(), protocolVersion=1)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass

    return 0
