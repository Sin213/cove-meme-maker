"""Background worker that runs the ffmpeg video-export command and reports
progress back to the UI thread. For image jobs the call is synchronous and
fast enough that we don't need a thread at all — the caller just uses
:mod:`image_renderer` directly.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal

from .ffmpeg_utils import probe
from .image_renderer import MemeSpec, render, save_animation
from .video_renderer import VideoJob, build_command


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _parse_time(line: str) -> float | None:
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


class VideoExportWorker(QObject):
    progress = Signal(int)   # 0..100
    log = Signal(str)
    finished = Signal(Path)
    failed = Signal(str)

    def __init__(self, job: VideoJob) -> None:
        super().__init__()
        self._job = job
        self._proc: subprocess.Popen | None = None
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        job = self._job
        with tempfile.TemporaryDirectory(prefix="cove-meme-export-") as tdir:
            workdir = Path(tdir)
            try:
                info = probe(job.source)
                full = max(0.01, info.duration)
                if job.end is not None and job.start is not None:
                    duration = max(0.01, job.end - job.start)
                elif job.end is not None:
                    duration = max(0.01, job.end)
                else:
                    duration = full
                cmd = build_command(job, workdir)
                self.log.emit("starting ffmpeg…")
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                assert self._proc.stderr is not None
                for raw in self._proc.stderr:
                    if self._cancel:
                        break
                    t = _parse_time(raw)
                    if t is not None:
                        pct = min(99, int(t / duration * 100))
                        self.progress.emit(pct)
                rc = self._proc.wait()
                if self._cancel:
                    self.failed.emit("cancelled")
                    return
                if rc != 0:
                    self.failed.emit(f"ffmpeg exited with code {rc}")
                    return
                self.progress.emit(100)
                self.finished.emit(job.output)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))


@dataclass
class AnimatedJob:
    frames: list[Image.Image]
    durations: list[int]
    spec: MemeSpec
    output: Path
    fmt: str = "gif"  # "gif" | "webp"
    loop: int = 0


class AnimatedExportWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(Path)
    failed = Signal(str)

    def __init__(self, job: AnimatedJob) -> None:
        super().__init__()
        self._job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        job = self._job
        try:
            rendered: list[Image.Image] = []
            n = len(job.frames) or 1
            for i, frame in enumerate(job.frames):
                if self._cancel:
                    self.failed.emit("cancelled")
                    return
                rendered.append(render(frame, job.spec))
                # cap progress at 90 so the save step can push us to 100.
                self.progress.emit(min(90, int((i + 1) / n * 90)))
            self.log.emit("writing file…")
            save_animation(rendered, job.durations, job.output, fmt=job.fmt, loop=job.loop)
            self.progress.emit(100)
            self.finished.emit(job.output)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def start_animated_export(job: AnimatedJob) -> tuple[QThread, AnimatedExportWorker]:
    thread = QThread()
    worker = AnimatedExportWorker(job)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker


def start_export(job: VideoJob) -> tuple[QThread, VideoExportWorker]:
    thread = QThread()
    worker = VideoExportWorker(job)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker
