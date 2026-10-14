"""External tool discovery. FFmpeg is required for decode, waveform, and conversion."""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _bundled_dirs() -> list[Path]:
    """Folders a frozen build may keep ffmpeg in. Dev runs return nothing."""
    if not getattr(sys, "frozen", False):
        return []
    folders = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        folders.append(Path(meipass))
    folders.append(Path(sys.executable).resolve().parent)
    return folders


def _find_tool(name: str) -> str | None:
    filename = name if name.lower().endswith(".exe") else f"{name}.exe"
    for folder in _bundled_dirs():
        candidate = folder / filename
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


@lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    return _find_tool("ffmpeg")


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    return _find_tool("ffprobe")


def ffmpeg_version() -> str:
    exe = ffmpeg_path()
    if not exe:
        return ""
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        out = subprocess.run(
            [exe, "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    line = (out.stdout or out.stderr or "").splitlines()
    return line[0].strip() if line else ""


def tool_status() -> dict[str, str]:
    ff = ffmpeg_path()
    return {
        "ffmpeg": ff or "",
        "ffprobe": ffprobe_path() or "",
        "ffmpeg_version": ffmpeg_version() if ff else "",
    }
