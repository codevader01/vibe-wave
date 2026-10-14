"""Downsampled peak waveform for the progress display.

Peaks come from a mono decode of the file. Until they arrive the UI draws a
plain progress line, not a fake waveform.
"""

from __future__ import annotations

import subprocess

import numpy as np

from vibewave.tools import ffmpeg_path


def extract_peaks(path: str, duration: float, buckets: int = 220) -> list[float]:
    exe = ffmpeg_path()
    if not exe or duration <= 0.2:
        return []
    # Long files use a lower rate so the pipe stays small. Peaks are computed
    # while reading, so the whole file is never stored as PCM.
    rate = 2000 if duration < 30 * 60 else 800
    if duration > 3 * 60 * 60:
        return []
    command = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(rate),
        "-f",
        "f32le",
        "pipe:1",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError:
        return []
    peaks = np.zeros(buckets, dtype=np.float32)
    per_bucket = max(1.0, duration * rate / buckets)
    index = 0
    assert proc.stdout is not None
    try:
        while True:
            raw = proc.stdout.read(8192 * 4)
            if not raw:
                break
            usable = len(raw) - (len(raw) % 4)
            if usable <= 0:
                continue
            samples = np.frombuffer(raw[:usable], dtype=np.float32)
            positions = np.arange(index, index + len(samples))
            bin_index = np.minimum(buckets - 1, (positions / per_bucket).astype(np.int32))
            np.maximum.at(peaks, bin_index, np.abs(samples))
            index += len(samples)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    peak = float(peaks.max()) if peaks.size else 0
    if peak <= 1e-6:
        return []
    normalized = np.clip(peaks / peak, 0, 1)
    return normalized.astype(float).tolist()
