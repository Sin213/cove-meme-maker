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
import math
import pathlib
import re
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

_SIZE_PCT_MIN =  2.0    # smallest renderable per-block font size (% of image height)
_SIZE_PCT_MAX = 30.0
_ROTATION_MIN = -180.0  # clockwise degrees
_ROTATION_MAX =  180.0
_CROP_MIN_DIM =  0.01   # minimum width or height of crop region (normalised)

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = (pathlib.Path(__file__).parent.parent / "templates").resolve()

_TEMPLATE_CONTENT_TYPES: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Slug validation: lowercase alphanumeric + hyphens, 1–64 chars, must start with [a-z0-9].
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def _slugify(stem: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', stem.lower()).strip('-')


def _build_template_registry() -> dict[str, pathlib.Path]:
    """Scan _TEMPLATES_DIR and return {slug: resolved_path}.

    Built once at import time; result is read-only after startup.
    Unknown/missing dir yields an empty registry rather than erroring.
    """
    registry: dict[str, pathlib.Path] = {}
    if not _TEMPLATES_DIR.is_dir():
        return registry
    for p in sorted(_TEMPLATES_DIR.iterdir()):
        if p.suffix.lower() not in _TEMPLATE_CONTENT_TYPES:
            continue
        slug = _slugify(p.stem)
        if slug and slug not in registry:
            registry[slug] = p.resolve()
    return registry


_TEMPLATE_REGISTRY: dict[str, pathlib.Path] = _build_template_registry()

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
#preview-wrap{display:none;width:100%;height:100%;align-items:center;justify-content:center;padding:16px;position:relative}
#preview-img{max-width:100%;max-height:100%;object-fit:contain;border-radius:4px}
#handle-layer{position:absolute;inset:0;pointer-events:none}
.drag-handle{position:absolute;width:28px;height:28px;border-radius:50%;background:rgba(80,230,207,0.85);color:#0a0a0e;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;cursor:grab;transform:translate(-50%,-50%);pointer-events:all;user-select:none;border:2px solid rgba(255,255,255,0.6)}
.drag-handle:active{cursor:grabbing;background:rgba(80,230,207,1)}
.drag-handle.hidden{display:none}
.sub-handle{position:absolute;width:20px;height:20px;display:flex;align-items:center;justify-content:center;transform:translate(-50%,-50%);pointer-events:all;user-select:none;border:1.5px solid rgba(255,255,255,0.5);background:rgba(80,230,207,0.65);color:#0a0a0e;font-size:10px;font-weight:700}
.sub-handle.hidden{display:none}
.resize-handle{cursor:ew-resize;border-radius:3px}
.rotate-handle{cursor:ew-resize;border-radius:50%}

/* Crop overlay */
#crop-overlay{position:absolute;inset:0;pointer-events:none;display:none}
#crop-overlay.active{display:block}
#crop-shade-t,#crop-shade-b,#crop-shade-l,#crop-shade-r{position:absolute;background:rgba(0,0,0,0.55);pointer-events:none}
#crop-box{position:absolute;border:1.5px solid #50e6cf;box-sizing:border-box;pointer-events:none}
.crop-handle{position:absolute;width:14px;height:14px;background:#50e6cf;border-radius:2px;pointer-events:all;cursor:nwse-resize}
#crop-tl{top:-7px;left:-7px;cursor:nwse-resize}
#crop-tr{top:-7px;right:-7px;cursor:nesw-resize}
#crop-bl{bottom:-7px;left:-7px;cursor:nesw-resize}
#crop-br{bottom:-7px;right:-7px;cursor:nwse-resize}
.crop-btn{background:transparent;color:#9a9aae;border:1px solid rgba(255,255,255,0.10);border-radius:6px;padding:0 10px;font-size:12px;height:26px;cursor:pointer;font-family:inherit;white-space:nowrap;flex-shrink:0}
.crop-btn:disabled{color:#6b6b80;border-color:rgba(255,255,255,0.06);cursor:default}
.crop-btn.active{color:#50e6cf;border-color:#50e6cf}

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

/* Template gallery */
#gallery-strip{display:flex;gap:8px;overflow-x:auto;padding:0 12px 12px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.08) transparent}
#gallery-strip::-webkit-scrollbar{height:4px}
#gallery-strip::-webkit-scrollbar-track{background:transparent}
#gallery-strip::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:2px}
.tmpl-card{flex-shrink:0;width:72px;cursor:pointer;border-radius:7px;border:2px solid transparent;overflow:hidden;background:#11111a;transition:border-color 0.12s}
.tmpl-card:hover{border-color:rgba(255,255,255,0.16)}
.tmpl-card.selected{border-color:#50e6cf}
.tmpl-card img{display:block;width:72px;height:48px;object-fit:cover}
.tmpl-name{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:10px;color:#9a9aae;text-align:center;padding:4px 4px 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#gallery-empty{font-family:"Geist Mono","JetBrains Mono",ui-monospace,"Cascadia Mono",Menlo,monospace;font-size:11px;color:#6b6b80;padding:0 16px 12px}
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
        <div id="handle-layer">
          <div id="top-handle" class="drag-handle hidden">T</div>
          <div id="bottom-handle" class="drag-handle hidden">B</div>
          <div id="top-resize-handle" class="sub-handle resize-handle hidden">&#8596;</div>
          <div id="top-rotate-handle" class="sub-handle rotate-handle hidden">&#8635;</div>
          <div id="bottom-resize-handle" class="sub-handle resize-handle hidden">&#8596;</div>
          <div id="bottom-rotate-handle" class="sub-handle rotate-handle hidden">&#8635;</div>
        </div>
        <div id="crop-overlay">
          <div id="crop-shade-t"></div>
          <div id="crop-shade-b"></div>
          <div id="crop-shade-l"></div>
          <div id="crop-shade-r"></div>
          <div id="crop-box">
            <div class="crop-handle" id="crop-tl"></div>
            <div class="crop-handle" id="crop-tr"></div>
            <div class="crop-handle" id="crop-bl"></div>
            <div class="crop-handle" id="crop-br"></div>
          </div>
        </div>
      </div>
    </div>
    <div id="canvas-statusbar">
      <div id="status-pulse"></div>
      <span id="status-msg">Ready</span>
    </div>
  </div>

  <div id="inspector">
    <div id="inspector-body">

      <span class="sec-label">Templates</span>
      <div id="gallery-strip"></div>

      <div class="sec-divider"></div>
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
        <div class="slider-row">
          <span class="slider-lbl">Size</span>
          <input type="range" class="slider" id="top-size-sl" min="0" max="30" value="0">
          <span class="slider-val" id="top-size-val">Auto</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Angle</span>
          <input type="range" class="slider" id="top-rot-sl" min="-180" max="180" value="0">
          <span class="slider-val" id="top-rot-val">0&#xb0;</span>
        </div>
        <span class="field-label">Bottom text</span>
        <div class="field-row">
          <textarea class="field-ta" id="bottom-text" placeholder="BOTTOM TEXT"></textarea>
          <label class="color-btn" title="Bottom text colour">
            <span class="color-swatch" id="bottom-swatch"></span>
            <input type="color" id="bottom-color" value="#ffffff">
          </label>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Size</span>
          <input type="range" class="slider" id="bottom-size-sl" min="0" max="30" value="0">
          <span class="slider-val" id="bottom-size-val">Auto</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Angle</span>
          <input type="range" class="slider" id="bottom-rot-sl" min="-180" max="180" value="0">
          <span class="slider-val" id="bottom-rot-val">0&#xb0;</span>
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

      <div class="sec-divider"></div>
      <span class="sec-label">Crop / Frame</span>
      <div style="display:flex;align-items:center;gap:8px;padding:0 12px 12px">
        <button class="crop-btn" id="crop-toggle-btn" disabled>Enable crop</button>
        <button class="crop-btn" id="crop-reset-btn" disabled style="margin-left:auto">Reset</button>
      </div>
      <div id="crop-readout" style="display:none;padding:0 16px 12px">
        <span style="font-family:monospace;font-size:11px;color:#6b6b80" id="crop-readout-text"></span>
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
  var exportBtn    = document.getElementById('export-btn');
  var copyBtn      = document.getElementById('copy-btn');
  var galleryStrip = document.getElementById('gallery-strip');
  var topHandle    = document.getElementById('top-handle');
  var bottomHandle = document.getElementById('bottom-handle');
  var topResizeHandle    = document.getElementById('top-resize-handle');
  var topRotateHandle    = document.getElementById('top-rotate-handle');
  var bottomResizeHandle = document.getElementById('bottom-resize-handle');
  var bottomRotateHandle = document.getElementById('bottom-rotate-handle');
  var topSizeSl     = document.getElementById('top-size-sl');
  var bottomSizeSl  = document.getElementById('bottom-size-sl');
  var topRotSl      = document.getElementById('top-rot-sl');
  var bottomRotSl   = document.getElementById('bottom-rot-sl');
  var topSizeVal    = document.getElementById('top-size-val');
  var bottomSizeVal = document.getElementById('bottom-size-val');
  var topRotVal     = document.getElementById('top-rot-val');
  var bottomRotVal  = document.getElementById('bottom-rot-val');
  var cropToggleBtn = document.getElementById('crop-toggle-btn');
  var cropResetBtn  = document.getElementById('crop-reset-btn');
  var cropReadout   = document.getElementById('crop-readout');
  var cropReadoutTx = document.getElementById('crop-readout-text');
  var cropOverlay   = document.getElementById('crop-overlay');
  var cropBox       = document.getElementById('crop-box');
  var cropShadeT    = document.getElementById('crop-shade-t');
  var cropShadeB    = document.getElementById('crop-shade-b');
  var cropShadeL    = document.getElementById('crop-shade-l');
  var cropShadeR    = document.getElementById('crop-shade-r');

  var styleMode    = 'classic';
  var currentDataUrl = null;
  var lastPng      = null;
  var renderToken  = 0;
  var topPos    = null;
  var bottomPos = null;
  var dragging  = null;
  // Crop state: null = no crop; otherwise normalised {x, y, width, height}
  var cropActive = false;
  var cropRect   = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
  var cropDragging = null; // null | 'tl'|'tr'|'bl'|'br'
  var subDragging  = null; // null | {which:'top'|'bottom', type:'resize'|'rotate', startX, startVal}

  function setStatus(msg, pulse) {
    statusMsg.textContent = msg;
    statusPulse.style.background = pulse || '#3ddc97';
  }

  function _placeHandle(handle, nx, ny) {
    var imgRect  = previewImg.getBoundingClientRect();
    var wrapRect = previewWrap.getBoundingClientRect();
    handle.style.left = (imgRect.left - wrapRect.left + nx * imgRect.width)  + 'px';
    handle.style.top  = (imgRect.top  - wrapRect.top  + ny * imgRect.height) + 'px';
  }

  function _placeSubHandles(which, nx, ny) {
    var imgRect  = previewImg.getBoundingClientRect();
    var wrapRect = previewWrap.getBoundingClientRect();
    var cx = imgRect.left - wrapRect.left + nx * imgRect.width;
    var cy = imgRect.top  - wrapRect.top  + ny * imgRect.height;
    var rh = which === 'top' ? topResizeHandle    : bottomResizeHandle;
    var oh = which === 'top' ? topRotateHandle    : bottomRotateHandle;
    rh.style.left = (cx + 28) + 'px';
    rh.style.top  = cy + 'px';
    oh.style.left = cx + 'px';
    oh.style.top  = (cy - 28) + 'px';
  }

  function _showHandles() {
    var tnx = topPos    ? topPos[0]    : 0.5, tny = topPos    ? topPos[1]    : 0.10;
    var bnx = bottomPos ? bottomPos[0] : 0.5, bny = bottomPos ? bottomPos[1] : 0.90;
    _placeHandle(topHandle,    tnx, tny);
    _placeHandle(bottomHandle, bnx, bny);
    _placeSubHandles('top',    tnx, tny);
    _placeSubHandles('bottom', bnx, bny);
    topHandle.classList.remove('hidden');
    bottomHandle.classList.remove('hidden');
    topResizeHandle.classList.remove('hidden');
    topRotateHandle.classList.remove('hidden');
    bottomResizeHandle.classList.remove('hidden');
    bottomRotateHandle.classList.remove('hidden');
  }

  function _hideHandles() {
    topHandle.classList.add('hidden');
    bottomHandle.classList.add('hidden');
    topResizeHandle.classList.add('hidden');
    topRotateHandle.classList.add('hidden');
    bottomResizeHandle.classList.add('hidden');
    bottomRotateHandle.classList.add('hidden');
  }

  function _resetHandles() {
    topPos    = null;
    bottomPos = null;
    _hideHandles();
  }

  function _resetSizeRot() {
    topSizeSl.value    = '0'; topSizeVal.textContent    = 'Auto';    fillSlider(topSizeSl);
    bottomSizeSl.value = '0'; bottomSizeVal.textContent = 'Auto';    fillSlider(bottomSizeSl);
    topRotSl.value     = '0'; topRotVal.textContent     = '0\xb0'; fillSlider(topRotSl);
    bottomRotSl.value  = '0'; bottomRotVal.textContent  = '0\xb0'; fillSlider(bottomRotSl);
  }

  function _resetCrop() {
    cropActive = false;
    cropRect   = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
    cropDragging = null;
    cropOverlay.classList.remove('active');
    cropToggleBtn.textContent = 'Enable crop';
    cropToggleBtn.classList.remove('active');
    cropToggleBtn.disabled = true;
    cropResetBtn.disabled = true;
    cropReadout.style.display = 'none';
  }

  function _updateCropOverlay() {
    if (!cropActive) return;
    var imgRect  = previewImg.getBoundingClientRect();
    var wrapRect = previewWrap.getBoundingClientRect();
    var ox = imgRect.left - wrapRect.left;
    var oy = imgRect.top  - wrapRect.top;
    var iw = imgRect.width;
    var ih = imgRect.height;
    var bx = ox + cropRect.x * iw;
    var by = oy + cropRect.y * ih;
    var bw = cropRect.width  * iw;
    var bh = cropRect.height * ih;
    // shades
    cropShadeT.style.cssText = 'top:' + oy + 'px;left:' + ox + 'px;width:' + iw + 'px;height:' + (by - oy) + 'px';
    cropShadeB.style.cssText = 'top:' + (by + bh) + 'px;left:' + ox + 'px;width:' + iw + 'px;bottom:' + (wrapRect.height - oy - ih) + 'px';
    cropShadeL.style.cssText = 'top:' + by + 'px;left:' + ox + 'px;width:' + (bx - ox) + 'px;height:' + bh + 'px';
    cropShadeR.style.cssText = 'top:' + by + 'px;left:' + (bx + bw) + 'px;right:' + (wrapRect.width - ox - iw) + 'px;height:' + bh + 'px';
    // box
    cropBox.style.cssText = 'left:' + bx + 'px;top:' + by + 'px;width:' + bw + 'px;height:' + bh + 'px';
    // readout
    cropReadoutTx.textContent =
      'x:' + cropRect.x.toFixed(2) + ' y:' + cropRect.y.toFixed(2) +
      ' w:' + cropRect.width.toFixed(2) + ' h:' + cropRect.height.toFixed(2);
  }

  cropToggleBtn.addEventListener('click', function () {
    if (!currentDataUrl || cropToggleBtn.disabled) return;
    cropActive = !cropActive;
    if (cropActive) {
      cropOverlay.classList.add('active');
      cropToggleBtn.textContent = 'Disable crop';
      cropToggleBtn.classList.add('active');
      cropResetBtn.disabled = false;
      cropReadout.style.display = '';
      // Always calibrate against the source image. If previewImg currently
      // shows a rendered output (e.g. after a modern-mode render), restore
      // the source first and let layout settle before computing the overlay.
      if (previewImg.src !== currentDataUrl) {
        previewImg.src = currentDataUrl;
        requestAnimationFrame(function () { if (cropActive) _updateCropOverlay(); });
      } else {
        _updateCropOverlay();
      }
    } else {
      cropOverlay.classList.remove('active');
      cropToggleBtn.textContent = 'Enable crop';
      cropToggleBtn.classList.remove('active');
      cropResetBtn.disabled = true;
      cropReadout.style.display = 'none';
    }
  });

  cropResetBtn.addEventListener('click', function () {
    cropRect = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
    _updateCropOverlay();
  });

  (function () {
    var handles = [
      document.getElementById('crop-tl'),
      document.getElementById('crop-tr'),
      document.getElementById('crop-bl'),
      document.getElementById('crop-br'),
    ];
    var corners = ['tl', 'tr', 'bl', 'br'];
    var MIN_DIM = 0.01;
    corners.forEach(function (corner, i) {
      handles[i].addEventListener('mousedown', function (e) {
        e.preventDefault(); e.stopPropagation(); cropDragging = corner;
      });
      handles[i].addEventListener('touchstart', function (e) {
        e.preventDefault(); e.stopPropagation(); cropDragging = corner;
      }, { passive: false });
    });
    function _onCropMove(clientX, clientY) {
      if (!cropDragging) return;
      var imgRect = previewImg.getBoundingClientRect();
      var nx = Math.max(0, Math.min(1, (clientX - imgRect.left) / imgRect.width));
      var ny = Math.max(0, Math.min(1, (clientY - imgRect.top)  / imgRect.height));
      var r = cropRect;
      if (cropDragging === 'tl') {
        var nx2 = Math.min(nx, r.x + r.width  - MIN_DIM);
        var ny2 = Math.min(ny, r.y + r.height - MIN_DIM);
        r.width  += r.x - nx2;  r.x = nx2;
        r.height += r.y - ny2;  r.y = ny2;
      } else if (cropDragging === 'tr') {
        var ny2 = Math.min(ny, r.y + r.height - MIN_DIM);
        r.width  = Math.max(MIN_DIM, nx - r.x);
        r.height += r.y - ny2; r.y = ny2;
      } else if (cropDragging === 'bl') {
        var nx2 = Math.min(nx, r.x + r.width - MIN_DIM);
        r.height = Math.max(MIN_DIM, ny - r.y);
        r.width += r.x - nx2; r.x = nx2;
      } else {
        r.width  = Math.max(MIN_DIM, nx - r.x);
        r.height = Math.max(MIN_DIM, ny - r.y);
      }
      _updateCropOverlay();
    }
    window.addEventListener('mousemove', function (e) { if (cropDragging) _onCropMove(e.clientX, e.clientY); });
    window.addEventListener('mouseup',   function ()  { cropDragging = null; });
    window.addEventListener('touchmove', function (e) {
      if (cropDragging) { e.preventDefault(); var t = e.touches[0]; _onCropMove(t.clientX, t.clientY); }
    }, { passive: false });
    window.addEventListener('touchend',  function () { cropDragging = null; });
  })();

  function _onDragMove(clientX, clientY) {
    if (!dragging) return;
    var imgRect = previewImg.getBoundingClientRect();
    var nx = Math.max(0, Math.min(1, (clientX - imgRect.left) / imgRect.width));
    var ny = Math.max(0, Math.min(1, (clientY - imgRect.top)  / imgRect.height));
    if (dragging === 'top') {
      topPos = [nx, ny];
      _placeHandle(topHandle, nx, ny);
      _placeSubHandles('top', nx, ny);
    } else {
      bottomPos = [nx, ny];
      _placeHandle(bottomHandle, nx, ny);
      _placeSubHandles('bottom', nx, ny);
    }
  }

  topHandle.addEventListener('mousedown', function (e) { e.preventDefault(); dragging = 'top'; });
  bottomHandle.addEventListener('mousedown', function (e) { e.preventDefault(); dragging = 'bottom'; });
  window.addEventListener('mousemove', function (e) { if (dragging) _onDragMove(e.clientX, e.clientY); });
  window.addEventListener('mouseup', function () { dragging = null; });

  topHandle.addEventListener('touchstart', function (e) { e.preventDefault(); dragging = 'top'; }, { passive: false });
  bottomHandle.addEventListener('touchstart', function (e) { e.preventDefault(); dragging = 'bottom'; }, { passive: false });
  window.addEventListener('touchmove', function (e) {
    if (dragging) { e.preventDefault(); var t = e.touches[0]; _onDragMove(t.clientX, t.clientY); }
  }, { passive: false });
  window.addEventListener('touchend', function () { dragging = null; });

  function _onSubDragMove(clientX) {
    if (!subDragging) return;
    var dx = clientX - subDragging.startX;
    if (subDragging.type === 'resize') {
      var sl = subDragging.which === 'top' ? topSizeSl : bottomSizeSl;
      var vd = subDragging.which === 'top' ? topSizeVal : bottomSizeVal;
      var newVal = Math.round(Math.max(parseFloat(sl.min), Math.min(parseFloat(sl.max), subDragging.startVal + dx * 0.2)));
      sl.value = newVal;
      vd.textContent = newVal === 0 ? 'Auto' : newVal + '%';
      fillSlider(sl);
    } else {
      var sl = subDragging.which === 'top' ? topRotSl : bottomRotSl;
      var vd = subDragging.which === 'top' ? topRotVal : bottomRotVal;
      var newVal = Math.round(Math.max(parseFloat(sl.min), Math.min(parseFloat(sl.max), subDragging.startVal + dx * 1.0)));
      sl.value = newVal;
      vd.textContent = newVal + '°';
      fillSlider(sl);
    }
  }

  function _subHandleDown(e, which, type) {
    e.preventDefault();
    e.stopPropagation();
    var sl = type === 'resize'
      ? (which === 'top' ? topSizeSl : bottomSizeSl)
      : (which === 'top' ? topRotSl  : bottomRotSl);
    subDragging = { which: which, type: type, startX: e.clientX || (e.touches && e.touches[0].clientX), startVal: parseFloat(sl.value) };
  }

  topResizeHandle.addEventListener('mousedown',    function (e) { _subHandleDown(e, 'top',    'resize'); });
  topRotateHandle.addEventListener('mousedown',    function (e) { _subHandleDown(e, 'top',    'rotate'); });
  bottomResizeHandle.addEventListener('mousedown', function (e) { _subHandleDown(e, 'bottom', 'resize'); });
  bottomRotateHandle.addEventListener('mousedown', function (e) { _subHandleDown(e, 'bottom', 'rotate'); });

  topResizeHandle.addEventListener('touchstart',    function (e) { _subHandleDown(e, 'top',    'resize'); }, { passive: false });
  topRotateHandle.addEventListener('touchstart',    function (e) { _subHandleDown(e, 'top',    'rotate'); }, { passive: false });
  bottomResizeHandle.addEventListener('touchstart', function (e) { _subHandleDown(e, 'bottom', 'resize'); }, { passive: false });
  bottomRotateHandle.addEventListener('touchstart', function (e) { _subHandleDown(e, 'bottom', 'rotate'); }, { passive: false });

  window.addEventListener('mousemove', function (e) { if (subDragging) _onSubDragMove(e.clientX); });
  window.addEventListener('mouseup',   function ()  { subDragging = null; });
  window.addEventListener('touchmove', function (e) {
    if (subDragging) { e.preventDefault(); _onSubDragMove(e.touches[0].clientX); }
  }, { passive: false });
  window.addEventListener('touchend', function () { subDragging = null; });

  window.addEventListener('resize', function () {
    if (!topHandle.classList.contains('hidden')) {
      var tnx = topPos    ? topPos[0]    : 0.5, tny = topPos    ? topPos[1]    : 0.10;
      _placeHandle(topHandle,    tnx, tny);
      _placeSubHandles('top',    tnx, tny);
    }
    if (!bottomHandle.classList.contains('hidden')) {
      var bnx = bottomPos ? bottomPos[0] : 0.5, bny = bottomPos ? bottomPos[1] : 0.90;
      _placeHandle(bottomHandle, bnx, bny);
      _placeSubHandles('bottom', bnx, bny);
    }
    if (cropActive) _updateCropOverlay();
  });

  function _deselectTemplates() {
    var cards = galleryStrip.querySelectorAll('.tmpl-card.selected');
    for (var i = 0; i < cards.length; i++) { cards[i].classList.remove('selected'); }
  }

  function loadTemplate(id, name) {
    var myToken = ++renderToken;
    currentDataUrl = null;
    lastPng = null;
    renderBtn.disabled = true;
    exportBtn.disabled = true;
    copyBtn.disabled   = true;
    fileNameEl.textContent = name;
    fileMetaEl.textContent = '';
    setStatus('Loading template…', '#ffb454');

    fetch('/templates/' + encodeURIComponent(id))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
      })
      .then(function (blob) {
        if (myToken !== renderToken) return;
        var reader = new FileReader();
        reader.onload = function (e) {
          if (myToken !== renderToken) return;
          currentDataUrl = e.target.result;
          var img = new Image();
          img.onload = function () {
            if (myToken !== renderToken) return;
            fileMetaEl.textContent = img.naturalWidth + ' \xd7 ' + img.naturalHeight;
            renderBtn.disabled = false;
            clearBtn.disabled  = false;
            dropZone.style.display    = 'none';
            previewWrap.style.display = 'flex';
            previewImg.src = currentDataUrl;
            setStatus('Template loaded — press Render');
            _resetHandles();
            _resetSizeRot();
            _resetCrop();
            cropToggleBtn.disabled = false;
            if (styleMode === 'classic') {
              var tok = myToken;
              requestAnimationFrame(function () { if (tok === renderToken) _showHandles(); });
            }
          };
          img.onerror = function () {
            if (myToken !== renderToken) return;
            currentDataUrl = null;
            fileMetaEl.textContent = '';
            previewWrap.style.display = 'none';
            previewImg.src = '';
            dropZone.style.display = '';
            _deselectTemplates();
            setStatus('Template image failed to load', '#ff6b6b');
          };
          img.src = e.target.result;
        };
        reader.onerror = function () {
          if (myToken !== renderToken) return;
          currentDataUrl = null;
          fileMetaEl.textContent = '';
          previewWrap.style.display = 'none';
          previewImg.src = '';
          dropZone.style.display = '';
          _deselectTemplates();
          setStatus('Template read failed', '#ff6b6b');
        };
        reader.readAsDataURL(blob);
      })
      .catch(function (err) {
        if (myToken !== renderToken) return;
        _deselectTemplates();
        setStatus('Template error: ' + err.message, '#ff6b6b');
      });
  }

  function buildGallery(templates) {
    if (!templates || !templates.length) {
      var empty = document.createElement('div');
      empty.id = 'gallery-empty';
      empty.textContent = 'Drop images into the templates folder to add templates.';
      galleryStrip.replaceWith(empty);
      return;
    }
    for (var i = 0; i < templates.length; i++) {
      (function (t) {
        var card = document.createElement('div');
        card.className = 'tmpl-card';

        var img = document.createElement('img');
        img.src = '/templates/' + encodeURIComponent(t.id);
        img.alt = '';
        img.loading = 'lazy';

        var nameEl = document.createElement('div');
        nameEl.className = 'tmpl-name';
        nameEl.textContent = t.name;

        card.appendChild(img);
        card.appendChild(nameEl);
        card.addEventListener('click', function () {
          _deselectTemplates();
          card.classList.add('selected');
          fileInput.value = '';
          loadTemplate(t.id, t.name);
        });
        galleryStrip.appendChild(card);
      })(templates[i]);
    }
  }

  function fillSlider(sl) {
    var pct = ((sl.value - sl.min) / (sl.max - sl.min)) * 100;
    sl.style.background =
      'linear-gradient(to right,#50e6cf ' + pct + '%,#1c1c28 ' + pct + '%)';
  }
  [sizeSl, strokeSl, padSl, topSizeSl, bottomSizeSl, topRotSl, bottomRotSl].forEach(fillSlider);

  sizeSl.addEventListener('input', function () {
    sizeVal.textContent = sizeSl.value + '%'; fillSlider(sizeSl);
  });
  strokeSl.addEventListener('input', function () {
    strokeVal.textContent = strokeSl.value + '%'; fillSlider(strokeSl);
  });
  padSl.addEventListener('input', function () {
    padVal.textContent = padSl.value + '%'; fillSlider(padSl);
  });
  topSizeSl.addEventListener('input', function () {
    topSizeVal.textContent = topSizeSl.value === '0' ? 'Auto' : topSizeSl.value + '%';
    fillSlider(topSizeSl);
  });
  bottomSizeSl.addEventListener('input', function () {
    bottomSizeVal.textContent = bottomSizeSl.value === '0' ? 'Auto' : bottomSizeSl.value + '%';
    fillSlider(bottomSizeSl);
  });
  topRotSl.addEventListener('input', function () {
    topRotVal.textContent = topRotSl.value + '\xb0';
    fillSlider(topRotSl);
  });
  bottomRotSl.addEventListener('input', function () {
    bottomRotVal.textContent = bottomRotSl.value + '\xb0';
    fillSlider(bottomRotSl);
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
    if (currentDataUrl) {
      if (mode === 'classic') {
        if (previewImg.src !== currentDataUrl) {
          lastPng = null;
          exportBtn.disabled = true;
          copyBtn.disabled   = true;
          previewImg.src = currentDataUrl;
          requestAnimationFrame(function () { if (styleMode === 'classic') _showHandles(); });
        } else {
          _showHandles();
        }
      } else {
        _hideHandles();
      }
    }
  }
  btnClassic.addEventListener('click', function () { setStyle('classic'); });
  btnModern.addEventListener('click', function () { setStyle('modern'); });

  function loadFile(file) {
    if (!file) return;
    _deselectTemplates();
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
        _resetHandles();
        _resetSizeRot();
        _resetCrop();
        cropToggleBtn.disabled = false;
        if (styleMode === 'classic') {
          var tok = myLoadToken;
          requestAnimationFrame(function () { if (tok === renderToken) _showHandles(); });
        }
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
    _deselectTemplates();
    _resetHandles();
    _resetSizeRot();
    _resetCrop();
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
    // When crop is active, convert source-normalised handle positions into
    // crop-local coordinates (the renderer applies crop before placing text).
    // Does not mutate the stored drag state; null handles pass through as null.
    function _toCropLocal(pos) {
      if (!pos) return null;
      var lx = Math.max(0, Math.min(1, (pos[0] - cropRect.x) / cropRect.width));
      var ly = Math.max(0, Math.min(1, (pos[1] - cropRect.y) / cropRect.height));
      return [lx, ly];
    }
    fetch('/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_b64:     b64,
        style:         styleMode,
        top:           topText.value,
        bottom:        bottomText.value,
        caption:       captionText.value,
        uppercase:     allCaps.checked,
        top_color:     topColor.value,
        bottom_color:  bottomColor.value,
        caption_color: captionColor.value,
        font_scale:    parseInt(sizeSl.value, 10),
        stroke_ratio:  parseInt(strokeSl.value, 10),
        padding_scale: parseInt(padSl.value, 10),
        top_pos:        cropActive ? _toCropLocal(topPos)    : topPos,
        bottom_pos:     cropActive ? _toCropLocal(bottomPos) : bottomPos,
        top_size_pct:    topSizeSl.value === '0' ? null : parseInt(topSizeSl.value, 10),
        bottom_size_pct: bottomSizeSl.value === '0' ? null : parseInt(bottomSizeSl.value, 10),
        top_rotation:    parseInt(topRotSl.value, 10),
        bottom_rotation: parseInt(bottomRotSl.value, 10),
        crop: cropActive ? { x: cropRect.x, y: cropRect.y, width: cropRect.width, height: cropRect.height } : null,
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
      // When crop is active keep the source image in previewImg so the crop
      // overlay stays calibrated to the original geometry. The rendered output
      // is available via Export/Copy; lastPng already holds it.
      if (cropActive) {
        previewImg.src = currentDataUrl;
        var _raf_tok = myToken;
        requestAnimationFrame(function () { if (_raf_tok === renderToken) _updateCropOverlay(); });
      } else {
        previewImg.src = 'data:image/png;base64,' + data.preview_b64;
      }
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

  fetch('/templates')
    .then(function (r) { return r.json(); })
    .then(function (data) { buildGallery(data.templates || []); })
    .catch(function () { /* gallery stays empty on network error — not critical */ });

}());
</script>
</body>
</html>
"""


_HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


def _parse_hex_color(val: object, default: tuple) -> tuple:
    """Parse a CSS #rrggbb string into an (r, g, b) int tuple.
    Returns default for any invalid/missing input."""
    if not isinstance(val, str) or not _HEX_COLOR_RE.match(val):
        return default
    return (int(val[1:3], 16), int(val[3:5], 16), int(val[5:7], 16))


def _safe_pct(val: object, spec_default: float) -> float:
    """Convert an integer-percent client value to a float fraction.
    Returns spec_default when val is None, non-numeric, or non-finite."""
    if val is None:
        return spec_default
    try:
        v = float(val)
        if not math.isfinite(v):
            return spec_default
        return v / 100.0
    except (TypeError, ValueError):
        return spec_default


def _parse_pos(val: object) -> "tuple[float, float] | None":
    """Parse a normalized [x, y] position from the client.
    Returns None if absent. Raises ValueError for present-but-malformed input.
    Returns (cx, cy) clamped to [0.0, 1.0] for valid input."""
    if val is None:
        return None
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        raise ValueError("pos must be a two-element array")
    try:
        x = float(val[0])
        y = float(val[1])
    except (TypeError, ValueError):
        raise ValueError("pos values must be numbers")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("pos values must be finite")
    return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))


def _parse_size_pct(val: object) -> "float | None":
    """Parse a per-block font size as a percentage of image height.
    Returns None (fall back to global font_scale) when absent or 0.
    Clamps valid finite values to [_SIZE_PCT_MIN, _SIZE_PCT_MAX].
    Raises ValueError for present-but-malformed input."""
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        raise ValueError("size_pct must be a number")
    if not math.isfinite(v):
        raise ValueError("size_pct must be finite")
    if v == 0.0:
        return None
    return max(_SIZE_PCT_MIN, min(_SIZE_PCT_MAX, v))


def _parse_rotation(val: object) -> float:
    """Parse a clockwise rotation in degrees.
    Returns 0.0 when absent. Clamps finite values to [_ROTATION_MIN, _ROTATION_MAX].
    Raises ValueError for present-but-malformed input."""
    if val is None:
        return 0.0
    try:
        v = float(val)
    except (TypeError, ValueError):
        raise ValueError("rotation must be a number")
    if not math.isfinite(v):
        raise ValueError("rotation must be finite")
    return max(_ROTATION_MIN, min(_ROTATION_MAX, v))


def _parse_crop(val: object) -> "tuple[float, float, float, float] | None":
    """Parse a normalised crop region {x, y, width, height}.
    Returns None when absent. Clamps each field to [0, 1].
    Raises ValueError for present-but-malformed input or zero-area region."""
    if val is None:
        return None
    if not isinstance(val, dict):
        raise ValueError("crop must be an object")
    for key in ("x", "y", "width", "height"):
        if key not in val:
            raise ValueError(f"crop missing field: {key}")
    try:
        x  = float(val["x"])
        y  = float(val["y"])
        cw = float(val["width"])
        ch = float(val["height"])
    except (TypeError, ValueError):
        raise ValueError("crop fields must be numbers")
    for v in (x, y, cw, ch):
        if not math.isfinite(v):
            raise ValueError("crop fields must be finite")
    x  = max(0.0, min(1.0, x))
    y  = max(0.0, min(1.0, y))
    cw = max(0.0, min(1.0, cw))
    ch = max(0.0, min(1.0, ch))
    # Compute the effective in-bounds extent so x+eff_w and y+eff_h never
    # exceed 1.0. Reject if either effective dimension is too small, which
    # catches e.g. x=1.0 (nothing left in the image) before the renderer sees it.
    eff_w = min(1.0, x + cw) - x
    eff_h = min(1.0, y + ch) - y
    if eff_w < _CROP_MIN_DIM or eff_h < _CROP_MIN_DIM:
        raise ValueError("crop region is too small")
    return (x, y, eff_w, eff_h)


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
        elif self.path == "/templates":
            self._serve_template_list()
        elif self.path.startswith("/templates/"):
            self._serve_template_image(self.path[len("/templates/"):])
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

    def _serve_template_list(self) -> None:
        items = [
            {"id": slug, "name": slug.replace("-", " ").title(),
             "url": f"/templates/{slug}"}
            for slug in _TEMPLATE_REGISTRY
        ]
        body = json.dumps({"templates": items}).encode("utf-8")
        self._reply(200, "application/json", body)

    def _serve_template_image(self, slug: str) -> None:
        if not _SLUG_RE.match(slug):
            self._json_error(404, "not found")
            return
        p = _TEMPLATE_REGISTRY.get(slug)
        if p is None:
            self._json_error(404, "not found")
            return
        # Defense-in-depth: confirm path is inside _TEMPLATES_DIR.
        # The registry only contains resolved paths built at startup, so this
        # guard is a belt-and-suspenders check rather than the primary defense.
        try:
            p.relative_to(_TEMPLATES_DIR)
        except ValueError:
            self._json_error(404, "not found")
            return
        try:
            data = p.read_bytes()
        except OSError:
            self._json_error(500, "template unavailable")
            return
        ctype = _TEMPLATE_CONTENT_TYPES.get(p.suffix.lower(), "application/octet-stream")
        self._reply(200, ctype, data)

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

        # Colors — validated from #rrggbb; fall back to MemeSpec defaults on invalid input
        top_color     = _parse_hex_color(req.get("top_color"),     (255, 255, 255))
        bottom_color  = _parse_hex_color(req.get("bottom_color"),  (255, 255, 255))
        caption_color = _parse_hex_color(req.get("caption_color"), (0, 0, 0))

        # Numeric sliders — client sends integer percentage; server clamps to safe range.
        # Absent field → MemeSpec dataclass default (0.085 / 0.08 / 0.22).
        font_scale    = max(0.02, min(0.30, _safe_pct(req.get("font_scale"),    0.085)))
        stroke_ratio  = max(0.00, min(0.20, _safe_pct(req.get("stroke_ratio"),  0.08)))
        padding_scale = max(0.05, min(0.60, _safe_pct(req.get("padding_scale"), 0.22)))

        # Draggable text positions — None → renderer default.
        try:
            top_pos    = _parse_pos(req.get("top_pos"))
            bottom_pos = _parse_pos(req.get("bottom_pos"))
        except ValueError as exc:
            self._json_error(400, f"invalid position: {exc}")
            return

        # Per-block size and rotation — validated; absent/0 → renderer default.
        try:
            top_size_pct    = _parse_size_pct(req.get("top_size_pct"))
            bottom_size_pct = _parse_size_pct(req.get("bottom_size_pct"))
            top_rotation    = _parse_rotation(req.get("top_rotation"))
            bottom_rotation = _parse_rotation(req.get("bottom_rotation"))
        except ValueError as exc:
            self._json_error(400, f"invalid size/rotation: {exc}")
            return

        # Crop region — optional normalised {x, y, width, height}.
        try:
            crop = _parse_crop(req.get("crop"))
        except ValueError as exc:
            self._json_error(400, f"invalid crop: {exc}")
            return

        # --- render ---
        try:
            from PIL import Image
            from ..image_renderer import MemeSpec, render as _render

            source = Image.open(io.BytesIO(img_bytes))
            if source.width * source.height > _MAX_IMAGE_PIXELS:
                self._json_error(413, "image dimensions too large")
                return
            spec = MemeSpec(
                style=style,
                top=top,
                bottom=bottom,
                caption=caption,
                uppercase=uppercase,
                top_color=top_color,
                bottom_color=bottom_color,
                caption_color=caption_color,
                font_scale=font_scale,
                stroke_ratio=stroke_ratio,
                padding_scale=padding_scale,
                top_pos=top_pos,
                bottom_pos=bottom_pos,
                top_size_pct=top_size_pct,
                bottom_size_pct=bottom_size_pct,
                top_rotation=top_rotation,
                bottom_rotation=bottom_rotation,
                crop=crop,
            )
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
