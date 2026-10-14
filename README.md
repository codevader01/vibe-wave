# VibeWave

<p align="center">
  <img src="vibewave.ico" alt="VibeWave Logo" width="250">
</p>

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
