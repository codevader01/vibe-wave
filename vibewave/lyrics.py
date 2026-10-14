"""Lyrics from a sidecar file next to the audio. No network lookups."""

from __future__ import annotations

import os
import re

_STAMP = re.compile(r"\[(\d{1,2}):(\d{2}(?:\.\d+)?)\]")


def _read(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def parse_lrc(text: str) -> list[tuple[float, str]]:
    lines = []
    for raw in text.splitlines():
        stamps = list(_STAMP.finditer(raw))
        if not stamps:
            continue
        lyric = _STAMP.sub("", raw).strip()
        if not lyric:
            continue
        for stamp in stamps:
            minutes = int(stamp.group(1))
            seconds = float(stamp.group(2))
            lines.append((minutes * 60 + seconds, lyric))
    lines.sort(key=lambda item: item[0])
    return lines


def find_lyrics(audio_path: str) -> tuple[str, list[tuple[float, str]], str]:
    """Return (mode, synced lines, plain text). mode is 'lrc', 'text', or 'none'."""
    if not audio_path:
        return "none", [], ""
    base, _ext = os.path.splitext(audio_path)
    for extension in (".lrc", ".txt"):
        candidate = base + extension
        if not os.path.isfile(candidate):
            continue
        text = _read(candidate).strip()
        if not text:
            continue
        synced = parse_lrc(text)
        if synced:
            return "lrc", synced, ""
        if extension == ".txt":
            return "text", [], text
    return "none", [], ""


def line_at(lines: list[tuple[float, str]], position: float) -> str:
    current = ""
    for stamp, text in lines:
        if stamp <= position + 0.05:
            current = text
        else:
            break
    return current
