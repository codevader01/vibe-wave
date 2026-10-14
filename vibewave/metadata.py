"""Read tags, duration, ReplayGain, and embedded artwork.

Missing or broken tags fall back to the filename. Unreadable files return an
error string instead of raising, so a scan can continue.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from vibewave.constants import OPUS_EXTENSION
from vibewave.paths import artwork_dir
from vibewave.tools import ffprobe_path

_TRACK_PREFIX = re.compile(r"^\s*\d{1,3}\s*[\.\-_)]+\s*")
_YEAR = re.compile(r"(19|20)\d{2}")
_GAIN = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*dB", re.IGNORECASE)


def is_opus_path(path: str) -> bool:
    return Path(path).suffix.lower() == OPUS_EXTENSION


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).replace("\x00", "").strip()


def fallback_names(path: str, title: str, artist: str, album: str) -> tuple[str, str, str]:
    """Fill empty title, artist, and album from the filename.

    "Artist - Title.mp3" and "01 - Artist - Title.mp3" are recognized.
    Otherwise the stem becomes the title and the artist is "Unknown Artist".
    """
    stem = Path(path).stem.strip() or "Untitled"
    cleaned = _TRACK_PREFIX.sub("", stem).strip() or stem
    left = ""
    right = cleaned
    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        left, right = left.strip(), right.strip()
    if not title:
        title = right or cleaned or stem
    if not artist:
        artist = left or "Unknown Artist"
    if not album:
        album = "Unknown Album"
    return title, artist, album


def _first(tags, key: str) -> str:
    if not tags or key not in tags:
        return ""
    try:
        return clean_text(tags.get(key))
    except Exception:
        return ""


def _parse_track_number(raw: str) -> int | None:
    raw = clean_text(raw)
    if not raw:
        return None
    head = raw.split("/", 1)[0].strip()
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return None
    try:
        number = int(digits)
    except ValueError:
        return None
    return number if number > 0 else None


def _parse_year(raw: str) -> int | None:
    match = _YEAR.search(clean_text(raw))
    if not match:
        return None
    year = int(match.group(0))
    if 1900 <= year <= 2100:
        return year
    return None


def _parse_gain(raw: str) -> float | None:
    match = _GAIN.search(clean_text(raw))
    if not match:
        # Some tags are a bare number.
        try:
            return float(clean_text(raw).split()[0])
        except (ValueError, IndexError):
            return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _artwork_bytes(audio) -> bytes | None:
    if audio is None or audio.tags is None:
        return None
    tags = audio.tags
    try:
        getter = getattr(tags, "getall", None)
        if getter:
            for frame in getter("APIC"):
                data = getattr(frame, "data", None)
                if data:
                    return bytes(data)
    except Exception:
        pass
    pictures = getattr(audio, "pictures", None)
    if pictures:
        try:
            return bytes(pictures[0].data)
        except Exception:
            pass
    try:
        if "covr" in tags:
            cover = tags["covr"][0]
            return bytes(cover)
    except Exception:
        pass
    return None


def save_artwork(data: bytes) -> str | None:
    """Write embedded art to the cache and return the JPEG path."""
    if not data:
        return None
    try:
        image = Image.open(BytesIO(data))
        image = image.convert("RGB")
        image.thumbnail((700, 700))
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    digest = hashlib.sha1(data).hexdigest()
    dest = artwork_dir() / f"{digest}.jpg"
    if not dest.exists():
        try:
            image.save(dest, "JPEG", quality=88)
        except OSError:
            return None
    return str(dest)


def probe_duration(path: str) -> float | None:
    exe = ffprobe_path()
    if not exe:
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run(
            [
                exe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        value = float((out.stdout or "").strip())
    except ValueError:
        return None
    if value > 0:
        return value
    return None


def fingerprint(path: str, duration: float) -> str:
    """Identity of the file contents, used to collapse duplicate copies."""
    digest = hashlib.sha1()
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    digest.update(str(size).encode())
    digest.update(f"|{duration:.2f}|".encode())
    try:
        with open(path, "rb") as handle:
            digest.update(handle.read(65536))
    except OSError:
        digest.update(path.encode("utf-8", "replace"))
    return digest.hexdigest()


def read_metadata(path: str) -> tuple[dict | None, str | None]:
    """Return (metadata, error). One of the two is None."""
    if is_opus_path(path):
        return None, "OPUS files are excluded"
    try:
        file_size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
    except OSError as exc:
        return None, f"Cannot access file ({exc.__class__.__name__})"

    audio = None
    easy = None
    try:
        from mutagen import File

        audio = File(path)
        easy = File(path, easy=True)
    except Exception as exc:
        audio = None
        easy = None
        easy_error = str(exc)
    else:
        easy_error = ""

    duration = 0.0
    if audio is not None and getattr(audio, "info", None) is not None:
        length = getattr(audio.info, "length", 0) or 0
        try:
            duration = float(length)
        except (TypeError, ValueError):
            duration = 0.0
    if duration <= 0:
        probed = probe_duration(path)
        if probed:
            duration = probed
    if duration <= 0:
        detail = easy_error or "no duration"
        return None, f"Unreadable audio ({detail})"

    title = _first(easy, "title")
    artist = _first(easy, "artist") or _first(easy, "albumartist")
    album = _first(easy, "album")
    genre = _first(easy, "genre")
    title, artist, album = fallback_names(path, title, artist, album)
    track_number = _parse_track_number(_first(easy, "tracknumber"))
    disc_number = _parse_track_number(_first(easy, "discnumber"))
    year = _parse_year(_first(easy, "date") or _first(easy, "year"))
    gain = _parse_gain(_first(easy, "replaygain_track_gain"))
    peak_raw = _first(easy, "replaygain_track_peak")
    try:
        peak = float(peak_raw) if peak_raw else None
    except ValueError:
        peak = None

    art_path = None
    try:
        blob = _artwork_bytes(audio)
        if blob:
            art_path = save_artwork(blob)
    except Exception:
        art_path = None

    return {
        "path": os.path.abspath(path),
        "filename": Path(path).name,
        "title": title,
        "artist": artist,
        "album": album,
        "genre": genre,
        "track_number": track_number,
        "disc_number": disc_number,
        "year": year,
        "duration": float(duration),
        "file_size": int(file_size),
        "mtime": float(mtime),
        "artwork_path": art_path,
        "replaygain_db": gain,
        "replaygain_peak": peak,
        "fingerprint": fingerprint(path, duration),
    }, None
