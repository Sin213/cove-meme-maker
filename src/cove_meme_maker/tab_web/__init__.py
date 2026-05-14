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
<title>Cove Meme Maker</title>
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; script-src 'unsafe-inline'">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:"Geist",Inter,ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;font-size:13px;background:#0a0a0e;color:#ececf1}
#app{display:flex;height:100%}

/* Canvas pane */
#canvas-pane{display:flex;flex-direction:column;flex:1;overflow:hidden;border-right:1px solid rgba(255,255,255,0.06)}
#canvas-header{display:flex;align-items:center;gap:8px;padding:0 16px;height:36px;background:#0a0a0e;border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0}
#header-title{font-size:12.5px;font-weight:500;color:#9a9aae;flex:1}
#header-session{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:10px;color:#6b6b80}
#canvas-toolbar{display:flex;align-items:center;gap:8px;padding:0 12px;height:36px;background:rgba(255,255,255,0.01);border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0}
#file-name{font-size:12.5px;font-weight:500;color:#ececf1;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#file-meta{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:10.5px;color:#6b6b80;white-space:nowrap}
.tb-btn{background:transparent;color:#9a9aae;border:1px solid rgba(255,255,255,0.10);border-radius:6px;padding:0 10px;font-size:12px;height:26px;cursor:pointer;font-family:inherit;white-space:nowrap;flex-shrink:0;line-height:1}
.tb-btn:hover:not(:disabled){color:#ececf1;background:#161620}
.tb-btn:disabled{color:#6b6b80;border-color:rgba(255,255,255,0.06);cursor:default}
.tb-btn.accent{background:#50e6cf;color:#0a0a0e;border-color:rgba(255,255,255,0.18);font-weight:600}
.tb-btn.accent:hover:not(:disabled){background:#6cf0db}
.tb-btn.accent:disabled{background:#161620;color:#6b6b80;border-color:rgba(255,255,255,0.06)}

#canvas-stage{flex:1;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#08080d;transition:background 0.12s}
#canvas-stage.drag-over{background:rgba(80,230,207,0.04)}
#drop-zone{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;border:1.5px dashed rgba(255,255,255,0.16);border-radius:12px;width:90%;max-width:480px;padding:48px 32px;text-align:center;transition:border-color 0.12s}
#canvas-stage.drag-over #drop-zone{border-color:rgba(80,230,207,0.40)}
#dz-title{font-size:15px;font-weight:500;color:#9a9aae}
#dz-sub{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:11px;color:#6b6b80;letter-spacing:0.04em}
#choose-btn{margin-top:12px;background:transparent;color:#9a9aae;border:1px solid rgba(255,255,255,0.10);border-radius:8px;padding:8px 18px;font-size:12.5px;cursor:pointer;font-family:inherit}
#choose-btn:hover{color:#ececf1;background:#161620}
#preview-wrap{display:none;width:100%;height:100%;align-items:center;justify-content:center;padding:16px}
#preview-img{max-width:100%;max-height:100%;object-fit:contain;border-radius:4px}

#canvas-statusbar{display:flex;align-items:center;gap:8px;padding:0 12px;height:28px;background:rgba(255,255,255,0.012);border-top:1px solid rgba(255,255,255,0.06);flex-shrink:0}
#status-pulse{width:6px;height:6px;border-radius:3px;background:#3ddc97;flex-shrink:0;transition:background 0.2s}
#status-msg{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:10.5px;color:#6b6b80;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Inspector */
#inspector{display:flex;flex-direction:column;width:380px;flex-shrink:0;background:#0d0d13;overflow:hidden}
#inspector-body{flex:1;overflow-y:auto;overflow-x:hidden;padding-bottom:8px}
#inspector-body::-webkit-scrollbar{width:6px}
#inspector-body::-webkit-scrollbar-track{background:transparent}
#inspector-body::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:3px}

.sec-label{display:block;font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:10.5px;letter-spacing:0.12em;font-weight:500;color:#6b6b80;text-transform:uppercase;padding:16px 16px 8px}
.sec-divider{height:1px;background:rgba(255,255,255,0.06);margin:4px 0}
#seg-frame{display:flex;margin:0 12px 12px;background:#11111a;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:3px;gap:2px}
.seg-btn{flex:1;background:transparent;color:#9a9aae;border:none;border-radius:6px;padding:7px 0;font-size:12.5px;cursor:pointer;font-family:inherit}
.seg-btn:hover{color:#ececf1}
.seg-btn.active{background:#1c1c28;color:#ececf1}

.field-label{display:block;font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:12px;color:#9a9aae;padding:0 16px 6px}
.field-row{display:flex;align-items:flex-start;gap:8px;padding:0 12px 12px}
textarea.field-ta{flex:1;background:#11111a;color:#ececf1;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 10px;font-size:13px;font-family:inherit;resize:none;height:60px;line-height:1.4}
textarea.field-ta:focus{outline:none;border-color:rgba(80,230,207,0.32);background:#161620}
textarea.field-ta.caption{height:76px}

.color-btn{display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:6px;border:1px solid rgba(255,255,255,0.16);cursor:pointer;position:relative;flex-shrink:0;overflow:hidden;margin-top:6px}
.color-swatch{display:block;width:20px;height:20px;border-radius:3px;pointer-events:none}
.color-btn input[type="color"]{opacity:0;position:absolute;width:0;height:0;padding:0;border:none;cursor:pointer}

.check-row{display:flex;align-items:center;gap:8px;padding:0 16px 12px}
.check-row input[type="checkbox"]{width:16px;height:16px;accent-color:#50e6cf;cursor:pointer;flex-shrink:0}
.check-row label{font-size:12.5px;color:#ececf1;cursor:pointer}

.slider-row{display:flex;align-items:center;gap:10px;padding:0 16px 14px}
.slider-lbl{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:12px;color:#9a9aae;width:52px;flex-shrink:0}
input[type="range"].slider{flex:1;-webkit-appearance:none;appearance:none;height:4px;border-radius:2px;outline:none;cursor:pointer;background:#1c1c28}
input[type="range"].slider::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:#fff;border:2px solid #0a0a0e;cursor:pointer}
input[type="range"].slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:#fff;border:2px solid #0a0a0e;cursor:pointer}
.slider-val{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:12px;color:#9a9aae;width:36px;text-align:right;flex-shrink:0}

.font-row{display:flex;align-items:center;gap:8px;padding:0 12px 12px}
.font-display{flex:1;background:#11111a;color:#9a9aae;border:1px solid rgba(255,255,255,0.06);border-radius:7px;padding:7px 10px;font-size:12.5px}
.font-add-btn{background:transparent;color:#6b6b80;border:1px solid rgba(255,255,255,0.06);border-radius:7px;padding:7px 12px;font-size:12px;cursor:default;opacity:0.5;font-family:inherit}

#inspector-footer{display:flex;flex-direction:column;gap:8px;padding:12px;border-top:1px solid rgba(255,255,255,0.06);flex-shrink:0}
#export-btn{width:100%;padding:10px 18px;background:#50e6cf;color:#0a0a0e;border:1px solid rgba(255,255,255,0.18);border-radius:9px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit}
#export-btn:hover:not(:disabled){background:#6cf0db}
#export-btn:disabled{background:#161620;color:#6b6b80;border-color:rgba(255,255,255,0.06);cursor:default}
#copy-btn{width:100%;padding:10px 18px;background:#11111a;color:#9a9aae;border:1px solid rgba(255,255,255,0.06);border-radius:9px;font-size:13px;cursor:pointer;font-family:inherit}
#copy-btn:hover:not(:disabled){color:#ececf1;background:#161620;border-color:rgba(255,255,255,0.10)}
#copy-btn:disabled{color:#6b6b80;cursor:default}
</style>
</head>
<body>
<input type="file" id="file-input" accept="image/*" style="display:none">
<div id="app">

  <div id="canvas-pane">
    <div id="canvas-header">
      <span id="header-title">Cove Meme Maker</span>
      <span id="header-session">Session&#x2009;<code id="session-id" data-run-id="__RUN_ID_ATTR__"></code></span>
    </div>
    <div id="canvas-toolbar">
      <span id="file-name">No file</span>
      <span id="file-meta"></span>
      <button class="tb-btn accent" id="render-btn" disabled>Render</button>
      <button class="tb-btn" id="clear-btn" disabled>Clear</button>
    </div>
    <div id="canvas-stage">
      <div id="drop-zone">
        <div id="dz-title">Drop an image to begin</div>
        <div id="dz-sub">PNG&#x2009;&middot;&#x2009;JPG&#x2009;&middot;&#x2009;WebP&#x2009;&middot;&#x2009;BMP</div>
        <button id="choose-btn">Choose file</button>
      </div>
      <div id="preview-wrap">
        <img id="preview-img" alt="">
      </div>
    </div>
    <div id="canvas-statusbar">
      <div id="status-pulse"></div>
      <span id="status-msg">Ready</span>
    </div>
  </div>

  <div id="inspector">
    <div id="inspector-body">

      <span class="sec-label">Style</span>
      <div id="seg-frame">
        <button class="seg-btn active" id="btn-classic">Classic</button>
        <button class="seg-btn" id="btn-modern">Modern</button>
      </div>

      <div id="classic-section">
        <span class="field-label">Top text</span>
        <div class="field-row">
          <textarea class="field-ta" id="top-text" placeholder="TOP TEXT"></textarea>
          <label class="color-btn" title="Top text colour">
            <span class="color-swatch" id="top-swatch"></span>
            <input type="color" id="top-color" value="#ffffff">
          </label>
        </div>
        <span class="field-label">Bottom text</span>
        <div class="field-row">
          <textarea class="field-ta" id="bottom-text" placeholder="BOTTOM TEXT"></textarea>
          <label class="color-btn" title="Bottom text colour">
            <span class="color-swatch" id="bottom-swatch"></span>
            <input type="color" id="bottom-color" value="#ffffff">
          </label>
        </div>
        <div class="check-row">
          <input type="checkbox" id="all-caps" checked>
          <label for="all-caps">All caps</label>
        </div>
      </div>

      <div id="modern-section" style="display:none">
        <span class="field-label">Caption</span>
        <div class="field-row">
          <label class="color-btn" title="Caption colour">
            <span class="color-swatch" id="caption-swatch"></span>
            <input type="color" id="caption-color" value="#000000">
          </label>
          <textarea class="field-ta caption" id="caption-text" placeholder="Caption"></textarea>
        </div>
      </div>

      <div class="sec-divider"></div>
      <span class="sec-label">Typography</span>

      <div class="font-row">
        <div class="font-display">Impact</div>
        <button class="font-add-btn" disabled>+ Font</button>
      </div>

      <div class="slider-row">
        <span class="slider-lbl">Size</span>
        <input type="range" class="slider" id="size-sl" min="2" max="30" value="9">
        <span class="slider-val" id="size-val">9%</span>
      </div>
      <div class="slider-row">
        <span class="slider-lbl">Stroke</span>
        <input type="range" class="slider" id="stroke-sl" min="0" max="20" value="8">
        <span class="slider-val" id="stroke-val">8%</span>
      </div>
      <div class="slider-row">
        <span class="slider-lbl">Padding</span>
        <input type="range" class="slider" id="pad-sl" min="5" max="60" value="22">
        <span class="slider-val" id="pad-val">22%</span>
      </div>

    </div>

    <div id="inspector-footer">
      <button id="export-btn" disabled>Export PNG</button>
      <button id="copy-btn" disabled>Copy to clipboard</button>
    </div>
  </div>

</div>
<script>
(function () {
  'use strict';

  var sessionEl = document.getElementById('session-id');
  sessionEl.textContent = sessionEl.dataset.runId || '';

  var fileInput   = document.getElementById('file-input');
  var fileNameEl  = document.getElementById('file-name');
  var fileMetaEl  = document.getElementById('file-meta');
  var renderBtn   = document.getElementById('render-btn');
  var clearBtn    = document.getElementById('clear-btn');
  var stage       = document.getElementById('canvas-stage');
  var dropZone    = document.getElementById('drop-zone');
  var previewWrap = document.getElementById('preview-wrap');
  var previewImg  = document.getElementById('preview-img');
  var statusPulse = document.getElementById('status-pulse');
  var statusMsg   = document.getElementById('status-msg');
  var chooseBtn   = document.getElementById('choose-btn');
  var btnClassic  = document.getElementById('btn-classic');
  var btnModern   = document.getElementById('btn-modern');
  var classicSec  = document.getElementById('classic-section');
  var modernSec   = document.getElementById('modern-section');
  var topText     = document.getElementById('top-text');
  var bottomText  = document.getElementById('bottom-text');
  var captionText = document.getElementById('caption-text');
  var allCaps     = document.getElementById('all-caps');
  var topColor    = document.getElementById('top-color');
  var bottomColor = document.getElementById('bottom-color');
  var captionColor= document.getElementById('caption-color');
  var topSwatch   = document.getElementById('top-swatch');
  var bottomSwatch= document.getElementById('bottom-swatch');
  var captionSwatch=document.getElementById('caption-swatch');
  var sizeSl      = document.getElementById('size-sl');
  var strokeSl    = document.getElementById('stroke-sl');
  var padSl       = document.getElementById('pad-sl');
  var sizeVal     = document.getElementById('size-val');
  var strokeVal   = document.getElementById('stroke-val');
  var padVal      = document.getElementById('pad-val');
  var exportBtn   = document.getElementById('export-btn');
  var copyBtn     = document.getElementById('copy-btn');

  var styleMode    = 'classic';
  var currentDataUrl = null;
  var lastPng      = null;
  var renderToken  = 0;

  function setStatus(msg, pulse) {
    statusMsg.textContent = msg;
    statusPulse.style.background = pulse || '#3ddc97';
  }

  function fillSlider(sl) {
    var pct = ((sl.value - sl.min) / (sl.max - sl.min)) * 100;
    sl.style.background =
      'linear-gradient(to right,#50e6cf ' + pct + '%,#1c1c28 ' + pct + '%)';
  }
  [sizeSl, strokeSl, padSl].forEach(fillSlider);

  sizeSl.addEventListener('input', function () {
    sizeVal.textContent = sizeSl.value + '%'; fillSlider(sizeSl);
  });
  strokeSl.addEventListener('input', function () {
    strokeVal.textContent = strokeSl.value + '%'; fillSlider(strokeSl);
  });
  padSl.addEventListener('input', function () {
    padVal.textContent = padSl.value + '%'; fillSlider(padSl);
  });

  function syncSwatch(inp, sw) { sw.style.background = inp.value; }
  syncSwatch(topColor, topSwatch);
  syncSwatch(bottomColor, bottomSwatch);
  syncSwatch(captionColor, captionSwatch);
  topColor.addEventListener('input', function () { syncSwatch(topColor, topSwatch); });
  bottomColor.addEventListener('input', function () { syncSwatch(bottomColor, bottomSwatch); });
  captionColor.addEventListener('input', function () { syncSwatch(captionColor, captionSwatch); });

  function setStyle(mode) {
    styleMode = mode;
    btnClassic.classList.toggle('active', mode === 'classic');
    btnModern.classList.toggle('active', mode === 'modern');
    classicSec.style.display = mode === 'classic' ? '' : 'none';
    modernSec.style.display  = mode === 'modern'  ? '' : 'none';
  }
  btnClassic.addEventListener('click', function () { setStyle('classic'); });
  btnModern.addEventListener('click', function () { setStyle('modern'); });

  function loadFile(file) {
    if (!file) return;
    var myLoadToken = ++renderToken;
    currentDataUrl = null;
    lastPng = null;
    renderBtn.disabled = true;
    exportBtn.disabled = true;
    copyBtn.disabled   = true;
    fileNameEl.textContent = file.name;
    var reader = new FileReader();
    reader.onload = function (e) {
      if (myLoadToken !== renderToken) return;
      currentDataUrl = e.target.result;
      var img = new Image();
      img.onload = function () {
        if (myLoadToken !== renderToken) return;
        fileMetaEl.textContent =
          img.naturalWidth + ' × ' + img.naturalHeight +
          ' · ' + (file.size / 1024).toFixed(0) + ' KB';
        renderBtn.disabled = false;
        clearBtn.disabled  = false;
        dropZone.style.display    = 'none';
        previewWrap.style.display = 'flex';
        previewImg.src = currentDataUrl;
        setStatus('Image loaded — press Render');
      };
      img.onerror = function () {
        if (myLoadToken !== renderToken) return;
        currentDataUrl = null;
        fileMetaEl.textContent = '';
        previewWrap.style.display = 'none';
        previewImg.src = '';
        dropZone.style.display = '';
        setStatus('Not a valid image', '#ff6b6b');
      };
      img.src = e.target.result;
    };
    reader.onerror = function () {
      if (myLoadToken !== renderToken) return;
      currentDataUrl = null;
      fileMetaEl.textContent = '';
      previewWrap.style.display = 'none';
      previewImg.src = '';
      dropZone.style.display = '';
      setStatus('Could not read file', '#ff6b6b');
    };
    reader.readAsDataURL(file);
  }

  fileInput.addEventListener('change', function () {
    if (fileInput.files.length) loadFile(fileInput.files[0]);
  });
  chooseBtn.addEventListener('click', function () { fileInput.click(); });

  clearBtn.addEventListener('click', function () {
    renderToken++;
    currentDataUrl = null;
    lastPng = null;
    fileInput.value = '';
    fileNameEl.textContent = 'No file';
    fileMetaEl.textContent = '';
    renderBtn.disabled = true;
    clearBtn.disabled  = true;
    exportBtn.disabled = true;
    copyBtn.disabled   = true;
    previewWrap.style.display = 'none';
    previewImg.src = '';
    dropZone.style.display = '';
    setStatus('Ready');
  });

  stage.addEventListener('dragover', function (e) {
    e.preventDefault();
    stage.classList.add('drag-over');
  });
  stage.addEventListener('dragleave', function (e) {
    if (!stage.contains(e.relatedTarget)) {
      stage.classList.remove('drag-over');
    }
  });
  stage.addEventListener('drop', function (e) {
    e.preventDefault();
    stage.classList.remove('drag-over');
    var f = e.dataTransfer.files[0];
    if (f) loadFile(f);
  });

  renderBtn.addEventListener('click', function () {
    if (!currentDataUrl) return;
    var myToken = ++renderToken;
    var b64 = currentDataUrl.split(',')[1];
    setStatus('Rendering…', '#ffb454');
    renderBtn.disabled = true;
    exportBtn.disabled = true;
    copyBtn.disabled   = true;
    fetch('/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_b64: b64,
        style:     styleMode,
        top:       topText.value,
        bottom:    bottomText.value,
        caption:   captionText.value,
        uppercase: allCaps.checked,
      }),
    })
    .then(function (r) {
      if (!r.ok) {
        return r.json().then(function (d) {
          throw new Error(d.error || ('HTTP ' + r.status));
        });
      }
      return r.json();
    })
    .then(function (data) {
      if (myToken !== renderToken) return;
      lastPng = data.preview_b64;
      previewImg.src = 'data:image/png;base64,' + data.preview_b64;
      previewWrap.style.display = 'flex';
      dropZone.style.display    = 'none';
      exportBtn.disabled = false;
      copyBtn.disabled   = false;
      setStatus('Rendered');
    })
    .catch(function (err) {
      if (myToken !== renderToken) return;
      setStatus('Error: ' + err.message, '#ff6b6b');
    })
    .finally(function () {
      if (myToken !== renderToken) return;
      renderBtn.disabled = false;
    });
  });

  exportBtn.addEventListener('click', function () {
    if (!lastPng) return;
    var a = document.createElement('a');
    a.href = 'data:image/png;base64,' + lastPng;
    a.download = 'meme.png';
    a.click();
  });

  copyBtn.addEventListener('click', function () {
    if (!lastPng) return;
    if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) {
      setStatus('Clipboard write not available in this browser', '#ffb454');
      return;
    }
    var bin = atob(lastPng);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    var blob = new Blob([arr], { type: 'image/png' });
    navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      .then(function () { setStatus('Copied to clipboard'); })
      .catch(function (e) { setStatus('Copy failed: ' + e.message, '#ff6b6b'); });
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
        uppercase = bool(req.get("uppercase", True))

        # --- render ---
        try:
            from PIL import Image
            from ..image_renderer import MemeSpec, render as _render

            source = Image.open(io.BytesIO(img_bytes))
            if source.width * source.height > _MAX_IMAGE_PIXELS:
                self._json_error(413, "image dimensions too large")
                return
            spec = MemeSpec(style=style, top=top, bottom=bottom, caption=caption, uppercase=uppercase)
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
