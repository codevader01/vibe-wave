"""Sample library used by the screenshot pass.

Runs only when VIBEWAVE_DEMO=1. Files go into the active data directory, which
the screenshot launch points at a temporary folder rather than %APPDATA%.
"""

from __future__ import annotations

import math
import time
import wave

import numpy as np
from PIL import Image, ImageDraw

from vibewave.db import Database
from vibewave.paths import data_dir
from vibewave.scanner import ScanState, scan_library

CATALOG = (
    ("Ava Cole", "Neon Harbor", "Electronic", (92, 64, 210), ("Glass Room", "Harbor Lights", "Soft Circuit")),
    ("Ava Cole", "Low Tide Notes", "Electronic", (36, 110, 150), ("Paper Boat", "Night Pier")),
    ("Jonah Hale", "North Window", "Folk", (64, 122, 78), ("Pine Radio", "February Map")),
    ("Mira Santos", "Late Service", "Jazz", (176, 112, 58), ("After the Set", "Blue Invoice")),
    ("The Low Keys", "City Static", "Rock", (150, 58, 72), ("Overpass", "Room Tone", "Last Train")),
)


def seed(db: Database) -> None:
    if db.get_setting("demo_seeded") == "1":
        return
    root = data_dir() / "demo_music"
    covers = root / "covers"
    root.mkdir(parents=True, exist_ok=True)
    covers.mkdir(parents=True, exist_ok=True)
    (root / "skip-me.OPUS").write_bytes(b"not-an-opus-file")

    planned: dict[str, tuple[str, str, str, str]] = {}
    index = 0
    for artist, album, genre, color, titles in CATALOG:
        for title in titles:
            index += 1
            audio = root / f"{artist} - {title}.wav"
            cover = covers / f"{index}.jpg"
            _write_wav(audio, 180 + index * 55, 8.0)
            _write_cover(cover, color, title[:1])
            planned[title] = (artist, album, genre, str(cover))
            if title == "Glass Room":
                audio.with_suffix(".lrc").write_text(
                    "[00:00.50] Glass on the water\n[00:02.00] The harbor keeps the light\n[00:04.00] Soft circuit, slow night\n",
                    encoding="utf-8",
                )

    db.add_folder(str(root))
    scan_library(db, ScanState())
    tracks = {row["title"]: row for row in db.query_tracks(sort="title")}
    with db._tx():
        for title, (artist, album, genre, cover) in planned.items():
            row = tracks.get(title)
            if not row:
                continue
            db.conn.execute(
                """
                UPDATE tracks
                SET artist = ?, album = ?, genre = ?, artwork_path = ?
                WHERE id = ?
                """,
                (artist, album, genre, cover, row["id"]),
            )

    def track_id(title: str) -> int:
        row = db.query_tracks(search=title, sort="title")
        for item in row:
            if item["title"] == title:
                return int(item["id"])
        raise KeyError(title)

    for title in ("Glass Room", "Harbor Lights", "Pine Radio", "Overpass", "After the Set"):
        identifier = track_id(title)
        for _ in range(4):
            history_id = db.record_play(identifier, 90)
            db.mark_completed(history_id, identifier)
    glass = track_id("Glass Room")
    db.set_rating(glass, 5)
    db.set_favorite(glass, True)
    db.set_favorite(track_id("Harbor Lights"), True)

    forgotten = track_id("Paper Boat")
    db.set_favorite(forgotten, True)
    with db._tx():
        db.conn.execute(
            """
            UPDATE tracks
            SET play_count = 3, listen_duration = 400, last_played = ?, completed_listens = 2
            WHERE id = ?
            """,
            (time.time() - 40 * 86400, forgotten),
        )
    db.record_skip(track_id("Room Tone"), 6)
    db.set_album_favorite("Ava Cole", "Neon Harbor", True)
    playlist_id = db.create_playlist("Late night")
    for title in ("Glass Room", "Night Pier", "Blue Invoice"):
        db.add_to_playlist(playlist_id, track_id(title))
    db.set_setting("demo_seeded", "1")


def _write_wav(path, frequency: float, seconds: float, rate: int = 44100) -> None:
    frames = int(rate * seconds)
    times = np.arange(frames) / rate
    samples = (0.32 * np.sin(2 * math.pi * frequency * times) * 32767).astype("<i2")
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


def _write_cover(path, color: tuple[int, int, int], letter: str) -> None:
    image = Image.new("RGB", (640, 640), color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 150, 490, 490), fill=(245, 245, 250))
    draw.text((292, 286), letter, fill=color)
    image.save(path, "JPEG", quality=90)
