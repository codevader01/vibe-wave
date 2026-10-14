"""Stream PCM out of FFmpeg. The player never asks Kivy to decode the file."""

from __future__ import annotations

import subprocess

import numpy as np


class DecoderError(RuntimeError):
    pass


class FFmpegDecoder:
    def __init__(self, ffmpeg: str, path: str, sample_rate: int, start_seconds: float = 0.0):
        self.ffmpeg = ffmpeg
        self.path = path
        self.sample_rate = sample_rate
        self.proc: subprocess.Popen | None = None
        self._start(max(0.0, start_seconds))

    def _start(self, start_seconds: float) -> None:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_seconds:.3f}",
            "-i",
            self.path,
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(self.sample_rate),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError as exc:
            raise DecoderError(str(exc)) from exc

    def read(self, frames: int) -> np.ndarray | None:
        if not self.proc or not self.proc.stdout:
            return None
        need = frames * 2 * 4
        chunks = []
        got = 0
        while got < need:
            piece = self.proc.stdout.read(need - got)
            if not piece:
                break
            chunks.append(piece)
            got += len(piece)
        if got < 8:
            return None
        usable = got - (got % 8)
        audio = np.frombuffer(b"".join(chunks)[:usable], dtype=np.float32)
        return audio.reshape(-1, 2).copy()

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if not proc:
            return
        try:
            if proc.stdout:
                proc.stdout.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
