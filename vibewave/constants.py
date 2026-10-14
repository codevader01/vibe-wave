"""Shared constants for scanning, playback, and the equalizer."""

from __future__ import annotations

APP_NAME = "VibeWave"
VERSION = "1.0.0"

# Formats the scanner will import. Matching is case-insensitive.
# .oga is an Ogg container alias used by some taggers and rippers.
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga"})

# Explicit product rule: never import or play .opus, regardless of letter case.
OPUS_EXTENSION = ".opus"

# Video and other inputs the converter offers in the file picker.
CONVERT_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpeg", ".mpg", ".ts",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".aiff", ".aif",
})

BITRATES = (128, 192, 256, 320)

# 7-band graphic EQ. Frequencies are the peaking-filter centers.
EQ_BANDS: tuple[tuple[str, float], ...] = (
    ("60 Hz", 60.0),
    ("150 Hz", 150.0),
    ("400 Hz", 400.0),
    ("1 kHz", 1000.0),
    ("2.4 kHz", 2400.0),
    ("6 kHz", 6000.0),
    ("15 kHz", 15000.0),
)

EQ_MIN_DB = -12.0
EQ_MAX_DB = 12.0

# Factory presets set the 7 bands plus the low-shelf and high-shelf trims.
# Shelves are real filters at 120 Hz and 8 kHz, separate from the graphic bands.
EQ_PRESETS: dict[str, dict[str, list[float] | float]] = {
    "Flat": {"gains": [0, 0, 0, 0, 0, 0, 0], "bass": 0, "treble": 0},
    "Bass Boost": {"gains": [6, 4, 2, 0, 0, 0, 0], "bass": 3, "treble": 0},
    "Deep Bass": {"gains": [9, 7, 4, 1, 0, -1, 0], "bass": 4, "treble": 0},
    "Treble Boost": {"gains": [0, 0, 0, 0, 2, 5, 6], "bass": 0, "treble": 3},
    "Vocal": {"gains": [-2, -1, 1, 4, 4, 2, 0], "bass": -1, "treble": 1},
    "Acoustic": {"gains": [3, 2, 1, 2, 2, 1, 2], "bass": 1, "treble": 1},
    "Classical": {"gains": [0, 0, 0, 0, 1, 3, 4], "bass": 0, "treble": 2},
    "Rock": {"gains": [5, 3, -1, 0, 2, 3, 4], "bass": 2, "treble": 1},
    "Pop": {"gains": [2, 3, 1, 1, 2, 3, 3], "bass": 1, "treble": 1},
    "Electronic": {"gains": [6, 4, 0, -1, 2, 4, 5], "bass": 3, "treble": 2},
    "Jazz": {"gains": [3, 2, 1, 2, -1, 2, 3], "bass": 1, "treble": 2},
}

PRESET_ORDER = (
    "Flat",
    "Bass Boost",
    "Deep Bass",
    "Treble Boost",
    "Vocal",
    "Acoustic",
    "Classical",
    "Rock",
    "Pop",
    "Electronic",
    "Jazz",
    "Custom",
)

SORT_OPTIONS = (
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("duration", "Duration"),
    ("date_added", "Date added"),
    ("play_count", "Play count"),
    ("last_played", "Recently played"),
)
