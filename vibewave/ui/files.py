"""Native file dialogs. Tk stays off the audio and scanner threads."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog


def _root_window():
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    return root


def pick_directory(title: str) -> str:
    window = _root_window()
    try:
        chosen = filedialog.askdirectory(title=title, parent=window)
    finally:
        window.destroy()
    return chosen or ""


def pick_open_files(title: str) -> list[str]:
    window = _root_window()
    try:
        chosen = filedialog.askopenfilenames(
            title=title,
            parent=window,
            filetypes=[
                ("Video and audio", "*.mp4 *.m4v *.mov *.mkv *.webm *.avi *.wmv *.flv *.mpeg *.mpg *.ts *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma *.aiff *.aif"),
                ("All files", "*.*"),
            ],
        )
    finally:
        window.destroy()
    return list(chosen)
