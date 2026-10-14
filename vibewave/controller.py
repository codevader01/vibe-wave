"""Playback queue, play counting, and session restore.

Seeking updates the playhead only. Play count moves when listened time crosses
the threshold in rules.py, or when the file plays through to the end.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)

from vibewave.audio.engine import AudioEngine
from vibewave.audio.waveform import extract_peaks
from vibewave.constants import EQ_BANDS, EQ_PRESETS
from vibewave.db import Database
from vibewave.lyrics import find_lyrics, line_at
from vibewave.metadata import is_opus_path
from vibewave.palette import palette_from_image, palette_from_text
from vibewave.rules import is_skip, should_count_play, should_mark_complete

log = logging.getLogger(__name__)

_DEFAULT_EQ = {
    "gains": [0.0] * len(EQ_BANDS),
    "preset": "Flat",
    "preamp": 0.0,
    "bass": 0.0,
    "treble": 0.0,
    "balance": 0.0,
    "crossfade": 0.0,
    "fade_in": 0.2,
    "fade_out": 0.25,
    "replaygain": True,
    "rg_preamp": 0.0,
    "reverb": 0.0,
}


class PlayerController(EventDispatcher):
    title = StringProperty("Nothing playing")
    artist = StringProperty("Choose a song to begin")
    album = StringProperty("")
    artwork = StringProperty("")
    genre = StringProperty("")
    year = StringProperty("")
    position = NumericProperty(0)
    duration = NumericProperty(0)
    playing = BooleanProperty(False)
    volume = NumericProperty(0.85)
    muted = BooleanProperty(False)
    shuffle = BooleanProperty(False)
    repeat_mode = StringProperty("off")
    favorite = BooleanProperty(False)
    rating = NumericProperty(0)
    has_track = BooleanProperty(False)
    track_id = NumericProperty(0)
    queue_length = NumericProperty(0)
    queue_index = NumericProperty(-1)
    library_revision = NumericProperty(0)
    stats_revision = NumericProperty(0)
    notice = StringProperty("")
    notice_seq = NumericProperty(0)
    peaks = ListProperty([])
    lyric_line = StringProperty("")
    lyrics_mode = StringProperty("none")
    lyrics_text = StringProperty("")
    lyrics_revision = NumericProperty(0)
    replaygain_label = StringProperty("")
    color_a = ListProperty([0.12, 0.08, 0.2, 1])
    color_b = ListProperty([0.05, 0.08, 0.12, 1])
    color_glow = ListProperty([0.55, 0.42, 1, 1])
    color_revision = NumericProperty(0)
    user_seeking = BooleanProperty(False)
    error = StringProperty("")

    def __init__(self, db: Database, engine: AudioEngine, **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.engine = engine
        self.queue: list[int] = []
        self._linear: list[int] | None = None
        self.index = -1
        self._listened = 0.0
        self._pending_listen = 0.0
        self._counted = False
        self._completed = False
        self._history_id: int | None = None
        self._session_open = False
        self._xfade_armed = False
        self._xfade_index = -1
        self._peaks_token = 0
        self._lyric_lines: list[tuple[float, str]] = []
        self.eq = dict(_DEFAULT_EQ)
        self.eq["gains"] = list(_DEFAULT_EQ["gains"])
        self._restored = False

    def toast(self, message: str) -> None:
        self.notice = message
        self.notice_seq += 1

    def boot(self) -> None:
        stored = self.db.get_json("equalizer", None)
        if isinstance(stored, dict):
            self.eq.update(stored)
            self.eq["gains"] = list(stored.get("gains") or self.eq["gains"])
        self.volume = float(self.db.get_json("volume", 0.85))
        self.shuffle = bool(self.db.get_json("shuffle", False))
        self.repeat_mode = self.db.get_json("repeat", "off") or "off"
        if self.repeat_mode not in {"off", "all", "one"}:
            self.repeat_mode = "off"
        self._push_audio_settings()
        self.engine.set_volume(self.volume)
        self._restore_queue()

    def _push_audio_settings(self) -> None:
        gains = [float(value) for value in self.eq.get("gains", [0] * 7)]
        self.engine.set_dsp(
            gains=gains,
            bass_db=float(self.eq.get("bass") or 0),
            treble_db=float(self.eq.get("treble") or 0),
            preamp_db=float(self.eq.get("preamp") or 0),
            balance=float(self.eq.get("balance") or 0),
            reverb_mix=float(self.eq.get("reverb") or 0),
        )
        self.engine.set_crossfade(float(self.eq.get("crossfade") or 0))
        self.engine.set_fades(float(self.eq.get("fade_in") or 0), float(self.eq.get("fade_out") or 0))
        self.engine.set_replaygain(bool(self.eq.get("replaygain", True)), float(self.eq.get("rg_preamp") or 0))

    def save_equalizer(self) -> None:
        self.db.set_json("equalizer", self.eq)
        self._push_audio_settings()

    def apply_preset(self, name: str) -> None:
        if name == "Custom":
            self.eq["preset"] = "Custom"
            self.save_equalizer()
            return
        preset = EQ_PRESETS.get(name)
        if not preset:
            return
        self.eq["preset"] = name
        self.eq["gains"] = [float(value) for value in preset["gains"]]
        self.eq["bass"] = float(preset["bass"])
        self.eq["treble"] = float(preset["treble"])
        self.save_equalizer()

    def set_eq_gain(self, index: int, value: float) -> None:
        gains = [float(item) for item in self.eq.get("gains", [0] * 7)]
        while len(gains) < 7:
            gains.append(0.0)
        gains[index] = max(-12.0, min(12.0, float(value)))
        self.eq["gains"] = gains
        self.eq["preset"] = "Custom"
        self.save_equalizer()

    def set_eq_value(self, key: str, value: float) -> None:
        self.eq[key] = float(value)
        if key in {"bass", "treble"}:
            self.eq["preset"] = "Custom"
        self.save_equalizer()

    # -- queue --------------------------------------------------------------

    def play_ids(self, ids: list[int], start_id: int, *, user_skip: bool = False) -> None:
        clean = [int(item) for item in ids if item]
        if start_id not in clean:
            return
        if self._session_open and user_skip:
            self._close_session(natural=False, user_skip=True)
        elif self._session_open:
            self._close_session(natural=False, user_skip=False)
        self.engine.cancel_next()
        self._xfade_armed = False
        self.queue = clean
        self._linear = list(clean)
        self.index = clean.index(start_id)
        if self.shuffle:
            self._shuffle_around_current()
        self.queue_length = len(self.queue)
        self._load_current(autoplay=True)

    def play_track(self, track_id: int, context: list[int] | None = None) -> None:
        ids = context or [track_id]
        self.play_ids(ids, track_id, user_skip=self._session_open)

    def add_to_queue(self, track_id: int) -> None:
        self.queue.append(int(track_id))
        if self._linear is not None:
            self._linear.append(int(track_id))
        if self.index < 0:
            self.index = 0
            self._load_current(autoplay=True)
        self.queue_length = len(self.queue)
        self.toast("Added to the queue")
        self._save_session()

    def play_next(self, track_id: int) -> None:
        track_id = int(track_id)
        if self.index < 0 or not self.queue:
            self.play_ids([track_id], track_id)
            return
        self.queue.insert(self.index + 1, track_id)
        if self._linear is not None:
            current = self.queue[self.index]
            try:
                at = self._linear.index(current)
            except ValueError:
                at = len(self._linear) - 1
            self._linear.insert(at + 1, track_id)
        self.queue_length = len(self.queue)
        self._xfade_armed = False
        self.engine.cancel_next()
        self.toast("Will play next")
        self._save_session()

    def remove_from_queue(self, position: int) -> None:
        if position < 0 or position >= len(self.queue):
            return
        removed = self.queue.pop(position)
        if self._linear and removed in self._linear:
            self._linear.remove(removed)
        if not self.queue:
            self.stop()
            return
        if position < self.index:
            self.index -= 1
        elif position == self.index:
            self._close_session(natural=False, user_skip=True)
            self.index = min(position, len(self.queue) - 1)
            self._load_current(autoplay=self.playing or True)
        self.queue_length = len(self.queue)
        self.queue_index = self.index
        self._save_session()

    def clear_upcoming(self) -> None:
        if self.index < 0:
            self.queue = []
        else:
            self.queue = self.queue[: self.index + 1]
        self._linear = list(self.queue)
        self.queue_length = len(self.queue)
        self.engine.cancel_next()
        self._xfade_armed = False
        self._save_session()

    def jump_queue(self, position: int) -> None:
        if position < 0 or position >= len(self.queue):
            return
        if position == self.index:
            self.seek(0)
            self.engine.play()
            return
        self._close_session(natural=False, user_skip=True)
        self.engine.cancel_next()
        self._xfade_armed = False
        self.index = position
        self._load_current(autoplay=True)

    def toggle_shuffle(self) -> None:
        self.shuffle = not self.shuffle
        if self.shuffle:
            self._linear = list(self.queue) if self._linear is None else self._linear
            self._shuffle_around_current()
        elif self._linear:
            current = self.track_id
            self.queue = list(self._linear)
            if current in self.queue:
                self.index = self.queue.index(current)
            elif self.queue:
                self.index = min(self.index, len(self.queue) - 1)
        self.queue_length = len(self.queue)
        self.queue_index = self.index
        self.db.set_json("shuffle", self.shuffle)
        self._save_session()

    def cycle_repeat(self) -> None:
        self.repeat_mode = {"off": "all", "all": "one", "one": "off"}[self.repeat_mode]
        self.db.set_json("repeat", self.repeat_mode)
        self._save_session()

    def _shuffle_around_current(self) -> None:
        if not self.queue:
            return
        if self.index < 0:
            random.shuffle(self.queue)
            self.index = 0
            return
        current = self.queue[self.index]
        rest = self.queue[: self.index] + self.queue[self.index + 1 :]
        random.shuffle(rest)
        self.queue = [current, *rest]
        self.index = 0

    def queue_rows(self) -> list[dict]:
        rows = []
        for position, track_id in enumerate(self.queue):
            track = self.db.get_track(track_id)
            if not track:
                continue
            rows.append({
                "position": position,
                "track_id": track_id,
                "title": track["title"],
                "artist": track["artist"],
                "current": position == self.index,
            })
        return rows

    # -- transport ----------------------------------------------------------

    def toggle(self) -> None:
        if not self.has_track:
            return
        if self.engine.is_playing():
            self.engine.pause()
        else:
            self.engine.play()

    def next(self, user: bool = True) -> None:
        self.engine.cancel_next()
        self._xfade_armed = False
        if self._session_open:
            self._close_session(natural=False, user_skip=user)
        self._advance(1)

    def previous(self) -> None:
        if self.position > 3 and self.has_track:
            # Restart. This is not a skip. A play already counted stays counted.
            self.engine.cancel_next()
            self._xfade_armed = False
            self.engine.seek(0)
            if not self._counted:
                self._listened = 0.0
            self.engine.play()
            return
        self.engine.cancel_next()
        self._xfade_armed = False
        if self._session_open:
            self._close_session(natural=False, user_skip=False)
        if self.index > 0:
            self.index -= 1
            self._load_current(autoplay=True)
        elif self.repeat_mode == "all" and self.queue:
            self.index = len(self.queue) - 1
            self._load_current(autoplay=True)
        else:
            self.engine.seek(0)
            self.engine.play()

    def seek(self, seconds: float) -> None:
        # The slider calls this on release. Moving it does not change play count.
        if not self.has_track:
            return
        seconds = max(0.0, min(float(seconds), self.duration or float(seconds)))
        self.engine.seek(seconds)
        self.position = seconds
        self._xfade_armed = False

    def stop(self) -> None:
        if self._session_open:
            self._close_session(natural=False, user_skip=False)
        self.engine.stop()
        self.playing = False
        self.position = 0

    def set_volume(self, value: float) -> None:
        self.volume = min(1.0, max(0.0, float(value)))
        if self.volume > 0 and self.muted:
            self.muted = False
            self.engine.set_muted(False)
        self.engine.set_volume(0 if self.muted else self.volume)
        self.db.set_json("volume", self.volume)

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        self.engine.set_muted(self.muted)
        self.engine.set_volume(0 if self.muted else self.volume)

    def nudge_volume(self, delta: float) -> None:
        self.set_volume(self.volume + delta)

    def toggle_favorite(self) -> None:
        if not self.track_id:
            return
        self.favorite = not self.favorite
        self.db.set_favorite(int(self.track_id), self.favorite)
        self.stats_revision += 1

    def set_rating(self, stars: int) -> None:
        if not self.track_id:
            return
        stars = 0 if int(self.rating) == int(stars) else int(stars)
        self.rating = stars
        self.db.set_rating(int(self.track_id), stars)
        self.stats_revision += 1

    def set_favorite_id(self, track_id: int, favorite: bool) -> None:
        self.db.set_favorite(track_id, favorite)
        if track_id == self.track_id:
            self.favorite = favorite
        self.stats_revision += 1

    # -- internals ----------------------------------------------------------

    def _advance(self, step: int) -> None:
        if not self.queue:
            self.engine.pause()
            return
        if self.repeat_mode == "one" and step > 0 and self.has_track:
            self.index = max(self.index, 0)
            self._load_current(autoplay=True)
            return
        nxt = self.index + step
        if 0 <= nxt < len(self.queue):
            self.index = nxt
            self._load_current(autoplay=True)
            return
        if step > 0 and self.repeat_mode == "all" and self.queue:
            self.index = 0
            self._load_current(autoplay=True)
            return
        self.engine.pause()
        self.playing = False

    def _drop_and_continue(self, autoplay: bool) -> None:
        if 0 <= self.index < len(self.queue):
            self.queue.pop(self.index)
        self.queue_length = len(self.queue)
        if not self.queue:
            self.has_track = False
            self.index = -1
            self.queue_index = -1
            return
        self.index = min(self.index, len(self.queue) - 1)
        self._load_current(autoplay)

    def _load_current(self, autoplay: bool) -> None:
        if not self.queue or self.index < 0 or self.index >= len(self.queue):
            return
        track = self.db.get_track(self.queue[self.index])
        if not track or track.get("missing") or track.get("excluded"):
            self.toast("That file is no longer in the library")
            self.queue.pop(self.index)
            self.queue_length = len(self.queue)
            if self.queue:
                self.index = min(self.index, len(self.queue) - 1)
                self._load_current(autoplay)
            return
        if is_opus_path(track["path"]):
            self.toast("OPUS files are excluded from playback")
            self._drop_and_continue(autoplay)
            return
        if not os.path.exists(track["path"]):
            self.toast(f"Missing file: {track['title']}")
            self.db.mark_missing([track["id"]])
            self.library_revision += 1
            self._drop_and_continue(autoplay)
            return
        if not self.engine.available:
            self.error = self.engine.error or "Audio output is unavailable"
            self.toast(self.error)
        self._show_track(track)
        self._begin_session()
        gain = float(track.get("replaygain_db") or 0)
        self.engine.load(track["path"], float(track.get("duration") or 0), gain, autoplay=autoplay)
        if autoplay:
            self.playing = True
        self._save_session()
        self._request_artwork_extras(track)

    def _show_track(self, track: dict) -> None:
        self.track_id = int(track["id"])
        self.has_track = True
        self.title = track["title"] or "Untitled"
        self.artist = track["artist"] or "Unknown Artist"
        self.album = track["album"] or ""
        self.genre = track.get("genre") or ""
        self.year = str(track["year"]) if track.get("year") else ""
        self.artwork = track.get("artwork_path") or ""
        self.duration = float(track.get("duration") or 0)
        self.position = 0
        self.favorite = bool(track.get("favorite"))
        self.rating = int(track.get("rating") or 0)
        self.queue_index = self.index
        self.queue_length = len(self.queue)
        gain = track.get("replaygain_db")
        if self.eq.get("replaygain", True) and gain not in (None, 0):
            self.replaygain_label = f"ReplayGain {gain:+.1f} dB"
        elif self.eq.get("replaygain", True):
            self.replaygain_label = "No ReplayGain tag"
        else:
            self.replaygain_label = ""
        mode, lines, text = find_lyrics(track["path"])
        self._lyric_lines = lines
        self.lyrics_mode = mode
        self.lyrics_text = text
        self.lyric_line = lines[0][1] if lines else ""
        self.lyrics_revision += 1
        self.peaks = []

    def _begin_session(self) -> None:
        self._listened = 0.0
        self._pending_listen = 0.0
        self._counted = False
        self._completed = False
        self._history_id = None
        self._session_open = True
        self._xfade_armed = False

    def _close_session(self, *, natural: bool, user_skip: bool) -> None:
        if not self._session_open or not self.track_id:
            self._session_open = False
            return
        self._flush_listen()
        duration = float(self.duration or 0)
        if user_skip and is_skip(self._listened, duration, self._counted):
            self.db.record_skip(int(self.track_id), self._listened)
            self._counted = True
            self.stats_revision += 1
        elif should_count_play(self._listened, duration, natural_end=natural, already=self._counted):
            self._history_id = self.db.record_play(int(self.track_id), self._listened)
            self._counted = True
            self.stats_revision += 1
        if should_mark_complete(self._listened, duration, natural_end=natural, already=self._completed):
            if self._counted:
                self.db.mark_completed(self._history_id, int(self.track_id))
                self._completed = True
        self._session_open = False

    def _flush_listen(self) -> None:
        if self._pending_listen > 0.05 and self.track_id:
            self.db.add_listen_time(int(self.track_id), self._pending_listen, self._history_id)
            self._pending_listen = 0.0

    def _request_artwork_extras(self, track: dict) -> None:
        self._peaks_token += 1
        token = self._peaks_token
        path = track["path"]
        duration = float(track.get("duration") or 0)
        artwork = track.get("artwork_path") or ""
        label = f"{track.get('artist')}|{track.get('album')}|{track.get('title')}"

        def work():
            peaks = extract_peaks(path, duration)
            if artwork and os.path.exists(artwork):
                colors = palette_from_image(artwork)
            else:
                colors = None
            if colors is None:
                colors = palette_from_text(label)

            def apply(_dt):
                if token != self._peaks_token:
                    return
                self.peaks = peaks
                glow, first, second = colors
                self.color_glow = list(glow)
                self.color_a = list(first)
                self.color_b = list(second)
                self.color_revision += 1

            # The clock will not call a nested function unless something else holds it.
            self._apply_artwork = apply
            Clock.schedule_once(apply, 0)

        threading.Thread(target=work, name="vibewave-art", daemon=True).start()

    def poll(self, dt: float) -> None:
        dt = min(max(dt, 0.0), 0.5)
        self._drain_messages()
        engine_playing = self.engine.is_playing()
        self.playing = engine_playing
        if not self.user_seeking and self.has_track:
            self.position = self.engine.position()
            if self.duration <= 0:
                self.duration = self.engine.duration
        if engine_playing and self.has_track and not self._session_open:
            self._begin_session()
        if engine_playing and self._session_open and self.track_id:
            self._listened += dt
            self._pending_listen += dt
            if self._pending_listen >= 5:
                self._flush_listen()
            self._maybe_count(natural=False)
            self._maybe_crossfade()
        if self._lyric_lines:
            self.lyric_line = line_at(self._lyric_lines, self.position)

    def _maybe_count(self, natural: bool) -> None:
        if not self.track_id:
            return
        if should_count_play(self._listened, self.duration, natural_end=natural, already=self._counted):
            self._history_id = self.db.record_play(int(self.track_id), self._listened)
            self._counted = True
            self.stats_revision += 1
        if should_mark_complete(self._listened, self.duration, natural_end=natural, already=self._completed) and self._counted:
            self.db.mark_completed(self._history_id, int(self.track_id))
            self._completed = True

    def _maybe_crossfade(self) -> None:
        if self._xfade_armed or self.repeat_mode == "one":
            return
        span = float(self.eq.get("crossfade") or 0)
        if span <= 0 or self.duration <= span * 2:
            return
        remaining = self.duration - self.position
        if remaining > span + 1.0 or remaining < 0.05:
            return
        nxt = self._following_index()
        if nxt is None:
            return
        track = self.db.get_track(self.queue[nxt])
        if not track or is_opus_path(track["path"]) or not os.path.exists(track["path"]):
            return
        self._xfade_index = nxt
        self._xfade_armed = True
        self.engine.prepare_next(track["path"], float(track.get("duration") or 0), float(track.get("replaygain_db") or 0))

    def _following_index(self) -> int | None:
        if self.index + 1 < len(self.queue):
            return self.index + 1
        if self.repeat_mode == "all" and self.queue:
            return 0
        return None

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.engine.messages.get_nowait()
            except Exception:
                break
            kind = message[0]
            if kind == "error":
                self.error = message[1]
                self.toast(message[1])
            elif kind == "advanced":
                self._on_advanced()
            elif kind == "ended":
                self._on_ended()

    def _on_ended(self) -> None:
        if self._session_open:
            self._close_session(natural=True, user_skip=False)
        if self.repeat_mode == "one" and self.has_track:
            self._load_current(autoplay=True)
            return
        following = self._following_index()
        if following is None:
            self.playing = False
            self.position = self.duration
            return
        self.index = following
        self._load_current(autoplay=True)

    def _on_advanced(self) -> None:
        # The engine is already playing the following file. Do not load it again.
        if self._session_open:
            self._close_session(natural=True, user_skip=False)
        if self._xfade_index < 0 or self._xfade_index >= len(self.queue):
            return
        self.index = self._xfade_index
        track = self.db.get_track(self.queue[self.index])
        if not track:
            return
        self._show_track(track)
        self._begin_session()
        self._listened = max(0.0, self.engine.position())
        self.position = self._listened
        self._request_artwork_extras(track)
        self._save_session()

    def _save_session(self) -> None:
        self.db.set_json("session", {
            "ids": self.queue,
            "index": self.index,
            "position": self.position,
            "repeat": self.repeat_mode,
            "shuffle": self.shuffle,
        })

    def _restore_queue(self) -> None:
        data = self.db.get_json("session", None)
        if not isinstance(data, dict):
            return
        ids = []
        for track_id in data.get("ids") or []:
            track = self.db.get_track(int(track_id))
            if track and not track.get("missing") and not track.get("excluded") and not is_opus_path(track["path"]):
                if os.path.exists(track["path"]):
                    ids.append(int(track_id))
        if not ids:
            return
        self.queue = ids
        self._linear = list(ids)
        index = int(data.get("index") or 0)
        self.index = min(max(index, 0), len(ids) - 1)
        self.queue_length = len(self.queue)
        track = self.db.get_track(self.queue[self.index])
        if not track:
            return
        self._show_track(track)
        self._begin_session()
        self.engine.load(track["path"], float(track.get("duration") or 0), float(track.get("replaygain_db") or 0), autoplay=False)
        position = float(data.get("position") or 0)
        if position > 1:
            self.engine.seek(position)
            self.position = position
        self._session_open = False
        self._restored = True

    def shutdown(self) -> None:
        if self._session_open:
            self._flush_listen()
            self._close_session(natural=False, user_skip=False)
        self._save_session()
        self.engine.shutdown()
