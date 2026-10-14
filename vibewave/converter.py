"""Extract audio to MP3 with FFmpeg. The UI stays responsive; work is on a thread."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

from vibewave.constants import BITRATES
from vibewave.tools import ffmpeg_path, ffprobe_path

_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def plan_outputs(sources: list[str], destination: str) -> list[tuple[str, str]]:
    """Pair each source with an MP3 path. Two sources that share a name get (2), (3), ..."""
    used: set[str] = set()
    planned = []
    folder = Path(destination)
    for source in sources:
        stem = Path(source).stem.strip() or "audio"
        stem = stem.replace("\x00", "")
        candidate = folder / f"{stem}.mp3"
        number = 2
        while candidate.name.lower() in used:
            candidate = folder / f"{stem} ({number}).mp3"
            number += 1
        used.add(candidate.name.lower())
        planned.append((source, str(candidate)))
    return planned


def probe_duration(path: str) -> float:
    exe = ffprobe_path() or ffmpeg_path()
    if not exe:
        return 0.0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if ffprobe_path():
        command = [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            path,
        ]
    else:
        return 0.0
    try:
        out = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=40,
            creationflags=flags,
            check=False,
        )
        return max(0.0, float((out.stdout or "").strip()))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0.0


class ConversionManager:
    def __init__(self):
        self.jobs: list[dict] = []
        self.running = False
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [dict(job) for job in self.jobs]

    def mark_imported(self, index: int) -> None:
        with self.lock:
            if 0 <= index < len(self.jobs):
                self.jobs[index]["imported"] = True

    def start(self, plans: list[tuple[str, str]], bitrate: int, overwrite: bool) -> str | None:
        """Start a batch. Returns an error string when FFmpeg is missing."""
        if self.running:
            return "A conversion is already running."
        exe = ffmpeg_path()
        if not exe:
            return "FFmpeg was not found. Install FFmpeg and reopen VibeWave."
        if bitrate not in BITRATES:
            return "Choose 128, 192, 256, or 320 kbps."
        if not plans:
            return "Choose at least one file."
        jobs = []
        for source, dest in plans:
            jobs.append({
                "src": source,
                "dest": dest,
                "status": "pending",
                "progress": 0.0,
                "error": "",
                "duration": probe_duration(source),
                "imported": False,
            })
        self._cancel.clear()
        with self.lock:
            self.jobs = jobs
            self.running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(exe, bitrate, overwrite),
            name="vibewave-convert",
            daemon=True,
        )
        self._thread.start()
        return None

    def cancel(self) -> None:
        self._cancel.set()
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()

    def _run(self, ffmpeg: str, bitrate: int, overwrite: bool) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            for index in range(len(self.jobs)):
                if self._cancel.is_set():
                    self._mark_rest(index, "cancelled", "Cancelled")
                    break
                with self.lock:
                    job = self.jobs[index]
                    dest = job["dest"]
                    source = job["src"]
                if os.path.exists(dest) and not overwrite:
                    self._update(index, status="skipped", error="File already exists", progress=0)
                    continue
                folder = os.path.dirname(dest)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                self._update(index, status="running", progress=0, error="")
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-y" if overwrite else "-n",
                    "-i",
                    source,
                    "-vn",
                    "-map_metadata",
                    "0",
                    "-id3v2_version",
                    "3",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    f"{bitrate}k",
                    dest,
                ]
                try:
                    proc = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.DEVNULL,
                        creationflags=flags,
                    )
                except OSError as exc:
                    self._update(index, status="error", error=str(exc))
                    self._delete_partial(dest)
                    continue
                self._process = proc
                error_tail = self._pump(proc, index)
                code = proc.wait()
                self._process = None
                if self._cancel.is_set():
                    self._update(index, status="cancelled", error="Cancelled")
                    self._delete_partial(dest)
                    self._mark_rest(index + 1, "cancelled", "Cancelled")
                    break
                if code != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 128:
                    self._delete_partial(dest)
                    self._update(index, status="error", error=error_tail or f"FFmpeg exited with code {code}")
                    continue
                self._update(index, status="done", progress=1.0, error="")
        finally:
            with self.lock:
                self.running = False
            self._process = None

    def _pump(self, proc: subprocess.Popen, index: int) -> str:
        assert proc.stderr is not None
        pending = ""
        last_error = ""
        while True:
            if self._cancel.is_set():
                proc.terminate()
            chunk = proc.stderr.read(256)
            if not chunk:
                break
            pending += chunk.decode("utf-8", "replace")
            pieces = re.split(r"[\r\n]+", pending)
            pending = pieces.pop() if pieces else ""
            for piece in pieces:
                if piece.strip():
                    last_error = piece.strip()[-240:]
                match = _TIME.search(piece)
                if not match:
                    continue
                hours, minutes, seconds = match.groups()
                current = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                with self.lock:
                    duration = self.jobs[index]["duration"] or 0
                progress = current / duration if duration else 0
                self._update(index, progress=min(0.99, progress))
        return last_error

    def _update(self, index: int, **fields) -> None:
        with self.lock:
            if 0 <= index < len(self.jobs):
                self.jobs[index].update(fields)

    def _mark_rest(self, start: int, status: str, error: str) -> None:
        with self.lock:
            for job in self.jobs[start:]:
                if job["status"] in {"pending", "running"}:
                    job["status"] = status
                    job["error"] = error

    @staticmethod
    def _delete_partial(path: str) -> None:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
