# VibeWave

Desktop music player for a folder you choose. It scans that folder, plays the files, and keeps favorites, history, and recommendations on this computer.

## Requirements

- Python 3.11 or newer (developed on 3.12)
- FFmpeg and ffprobe on `PATH` (decode, waveforms, and MP4-to-MP3)
- A working audio output device

Kivy 2.3.1 draws the interface. KivyMD is not used: the 1.x widgets fight this layout, and the 2.x API is not stable against this Kivy line. Playback does not use Kivy's SDL2 audio. FFmpeg decodes to float PCM, SciPy runs the equalizer, and `sounddevice` plays the result.

## Run

```powershell
cd C:\Users\samuel\VibeWave
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The first launch asks for music folders. Nothing outside those folders is scanned. Scan-on-startup, theme, equalizer, volume, and the last queue are stored between sessions.

Library data lives in `%APPDATA%\VibeWave` (`library.db`, artwork cache, log). Set `VIBEWAVE_DATA` to use another folder.

Supported library types: MP3, WAV, FLAC, M4A, AAC, OGG, and OGA. `.opus` files are ignored in every letter case. They are not imported and cannot be played. MP4 and other video files are converter inputs, not library tracks.

## Screens

Home, All Songs, Albums, Artists, Favorites, Most Played, Recently Played, Playlists, Audio Visualizer, Equalizer, Music Recommendations, MP4 to MP3, and Settings. The bar at the bottom stays up. Click the artwork or press `N` for the expanded player.

A play is counted after 30 seconds or half the track, whichever comes first. Moving the progress slider does not add a play.

## Shortcuts

| Key | Action |
| --- | --- |
| Space | Play / pause |
| Left / Right | Seek 5 seconds |
| Up / Down | Volume |
| Ctrl+Left / Ctrl+Right | Previous / next |
| M | Mute |
| F | Favorite |
| S | Shuffle |
| R | Repeat off, all, one |
| Q | Queue |
| E | Equalizer |
| N | Now playing |
| Ctrl+F | Search |
| Ctrl+. | Stop |
| Esc | Close the open panel |

## Recommendations

Scores are computed locally from plays, finishes, favorites, ratings, listening time, recency, skips, and artist, album, and genre affinity. There is no network call and no trained model. Weights live in `vibewave/recommend.py` (`WEIGHTS`).

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_core -v
```

`VIBEWAVE_DEMO=1` seeds a small library into the active data folder. `VIBEWAVE_SMOKE=1` walks the screens and writes PNGs to `.smoke\`. Point `VIBEWAVE_DATA` at a temporary folder before either flag so the real library is left alone.
