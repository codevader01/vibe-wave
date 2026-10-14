"""Visualizer, equalizer, recommendations, converter, and settings."""

from __future__ import annotations

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget

from vibewave.constants import BITRATES, EQ_BANDS, PRESET_ORDER
from vibewave.converter import plan_outputs
from vibewave.db import path_key
from vibewave.metadata import is_opus_path, read_metadata
from vibewave.paths import data_dir
from vibewave.recommend import SECTION_ORDER, build_recommendations
from vibewave.tools import ffmpeg_path, tool_status
from vibewave.ui.files import pick_directory, pick_open_files
from vibewave.ui.kit import chip_scroller, heading, hstrip, page_scroll, play_tracks, wrapping
from vibewave.ui.kit import app as running_app
from vibewave.ui.kit import root as shell
from vibewave.ui.widgets import Chip, EmptyState, Panel, PrettySlider, SpectrumBars, VWButton, VWLabel, VWSwitch, theme


class LevelRing(FloatLayout):
    """Ring size follows the engine's output level. It is not a spectrum."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.level = 0.0
        self.caption = VWLabel(
            text="Output level",
            role="micro",
            muted=True,
            halign="center",
            size_hint=(1, None),
            height=dp(18),
            pos_hint={"center_x": 0.5, "y": 0},
        )
        self.add_widget(self.caption)
        Clock.schedule_interval(self._tick, 1 / 30)
        self.bind(pos=self._draw, size=self._draw)

    def _current(self) -> bool:
        node = self.parent
        # Window.parent is the window itself. Stop there or the walk never ends.
        while node is not None and node.parent is not node:
            if isinstance(node, Screen):
                return bool(node.manager and node.manager.current == node.name)
            node = node.parent
        return False

    def _tick(self, _dt):
        running = running_app()
        if not self._current() or (running and running.reduced_motion):
            return
        target = running.engine.output_level() if running and running.engine else 0.0
        self.level = self.level * 0.82 + float(target) * 0.18
        self._draw()

    def _draw(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 4:
            return
        radius = dp(26) + self.level * min(dp(48), self.height * 0.28)
        with self.canvas.before:
            Color(*colors.accent[:3], 0.16 + self.level * 0.4)
            Ellipse(pos=(self.center_x - radius, self.center_y - radius), size=(radius * 2, radius * 2))


class VisualizerScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="visualizer", **kwargs)
        self.title = VWLabel(text="Nothing playing", role="title", size_hint_y=None, height=dp(32))
        self.artist = VWLabel(text="", role="small", muted=True, size_hint_y=None, height=dp(20))
        layout = BoxLayout(orientation="vertical", padding=(dp(28), dp(20)), spacing=dp(10))
        layout.add_widget(heading("Audio Visualizer"))
        layout.add_widget(
            wrapping(
                "The bars are a live FFT of the audio being played, from about 30 Hz to 16 kHz. "
                "The ring follows output level. Neither one is a decorative animation."
            )
        )
        layout.add_widget(LevelRing(size_hint_y=None, height=dp(150)))
        layout.add_widget(SpectrumBars(count=40, size_hint_y=None, height=dp(180)))
        layout.add_widget(self.title)
        layout.add_widget(self.artist)
        self.add_widget(layout)
        Clock.schedule_once(self._bind, 0)

    def _bind(self, *_args):
        player = running_app().player
        player.bind(title=self._sync, artist=self._sync)
        self._sync()

    def _sync(self, *_args):
        player = running_app().player
        self.title.text = player.title
        self.artist.text = player.artist

    def on_enter(self):
        self._sync()


class EqualizerScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="equalizer", **kwargs)
        self._guard = False
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)
        self.body.add_widget(heading("Equalizer"))
        self.body.add_widget(
            wrapping(
                "These filters run on the audio itself: seven peaking bands, a bass shelf, a treble shelf, "
                "balance, fades, ReplayGain, and optional reverb. Moving a slider changes the sound, then saves."
            )
        )
        pairs = [(name, name) for name in PRESET_ORDER]
        self.preset_scroll, self.preset_chips = chip_scroller(pairs, "Flat", self._preset)
        self.body.add_widget(self.preset_scroll)

        bands = BoxLayout(size_hint_y=None, height=dp(280), spacing=dp(6))
        self.band_sliders = []
        for index, (label, _frequency) in enumerate(EQ_BANDS):
            column = BoxLayout(orientation="vertical", spacing=dp(4))
            value = VWLabel(text="0", role="small", halign="center", size_hint_y=None, height=dp(18))
            slider = PrettySlider(orientation="vertical", bipolar=True, min_value=-12, max_value=12, step=0.5, value=0)
            slider.changed = lambda new, i=index: self._gain(i, new, save=False)
            slider.released = lambda new, i=index: self._gain(i, new, save=True)
            slider.bind(value=lambda _s, new, lab=value: setattr(lab, "text", f"{new:+.0f}"))
            caption = VWLabel(text=label, role="micro", muted=True, halign="center", size_hint_y=None, height=dp(28))
            column.add_widget(value)
            column.add_widget(slider)
            column.add_widget(caption)
            bands.add_widget(column)
            self.band_sliders.append(slider)
        self.body.add_widget(bands)

        self.effect_sliders = {}
        for key, label, low, high, step in (
            ("bass", "Bass shelf", -12, 12, 0.5),
            ("treble", "Treble shelf", -12, 12, 0.5),
            ("balance", "Balance", -1, 1, 0.05),
            ("crossfade", "Crossfade seconds", 0, 12, 0.5),
            ("fade_in", "Fade in seconds", 0, 8, 0.1),
            ("fade_out", "Fade out seconds", 0, 8, 0.1),
            ("reverb", "Reverb mix", 0, 1, 0.05),
            ("preamp", "Preamp dB", -12, 12, 0.5),
            ("rg_preamp", "ReplayGain preamp", -12, 12, 0.5),
        ):
            self.body.add_widget(self._effect_row(key, label, low, high, step))

        gain_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(12))
        gain_row.add_widget(VWLabel(text="ReplayGain / normalization", role="body"))
        self.replaygain = VWSwitch()
        self.replaygain.bind(active=self._replaygain)
        gain_row.add_widget(self.replaygain)
        gain_row.add_widget(Widget())
        self.body.add_widget(gain_row)

        reset = VWButton(text="Reset to flat", kind="ghost")
        reset.width = dp(150)
        reset.bind(on_release=lambda *_: self._preset("Flat"))
        holder = BoxLayout(size_hint_y=None, height=dp(44))
        holder.add_widget(reset)
        holder.add_widget(Widget())
        self.body.add_widget(holder)

    def _effect_row(self, key, label, low, high, step):
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        row.add_widget(VWLabel(text=label, size_hint_x=None, width=dp(180)))
        value = VWLabel(text="0", role="small", muted=True, size_hint_x=None, width=dp(70))
        slider = PrettySlider(min_value=low, max_value=high, step=step, value=0, bipolar=(low < 0 < high))
        slider.changed = lambda new, item=key: self._effect(item, new, save=False)
        slider.released = lambda new, item=key: self._effect(item, new, save=True)
        slider.bind(value=lambda _s, new, lab=value, item=key: setattr(lab, "text", self._format_effect(item, new)))
        row.add_widget(slider)
        row.add_widget(value)
        self.effect_sliders[key] = slider
        return row

    def _format_effect(self, key: str, value: float) -> str:
        if key == "balance":
            if abs(value) < 0.05:
                return "Center"
            side = "Left" if value < 0 else "Right"
            return f"{side} {int(abs(value) * 100)}"
        if key in {"crossfade", "fade_in", "fade_out", "reverb"}:
            return f"{value:.1f}"
        return f"{value:+.1f}"

    def on_enter(self):
        self.sync()

    def sync(self):
        player = running_app().player
        eq = player.eq
        self._guard = True
        gains = list(eq.get("gains") or [0] * 7)
        for slider, gain in zip(self.band_sliders, gains):
            slider.value = float(gain)
        for key, slider in self.effect_sliders.items():
            slider.value = float(eq.get(key) or 0)
        self.replaygain.active = bool(eq.get("replaygain", True))
        self._guard = False
        preset = eq.get("preset") or "Flat"
        for chip, name in zip(self.preset_chips, PRESET_ORDER):
            chip.selected = name == preset

    def _preset(self, name: str):
        running_app().player.apply_preset(name)
        self.sync()

    def _gain(self, index: int, value: float, save: bool):
        if self._guard:
            return
        player = running_app().player
        gains = [float(item) for item in player.eq.get("gains") or [0] * 7]
        while len(gains) < 7:
            gains.append(0.0)
        gains[index] = max(-12.0, min(12.0, float(value)))
        player.eq["gains"] = gains
        player.eq["preset"] = "Custom"
        if save:
            player.save_equalizer()
        else:
            player._push_audio_settings()
        for chip, name in zip(self.preset_chips, PRESET_ORDER):
            chip.selected = name == "Custom"

    def _effect(self, key: str, value: float, save: bool):
        if self._guard:
            return
        player = running_app().player
        player.eq[key] = float(value)
        if key in {"bass", "treble"}:
            player.eq["preset"] = "Custom"
            for chip, name in zip(self.preset_chips, PRESET_ORDER):
                chip.selected = name == "Custom"
        if save:
            player.save_equalizer()
        else:
            player._push_audio_settings()

    def _replaygain(self, _switch, active: bool):
        if self._guard:
            return
        player = running_app().player
        player.eq["replaygain"] = bool(active)
        player.save_equalizer()


class RecommendScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="recommendations", **kwargs)
        self._shown = False
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)

    def on_enter(self):
        self.refresh(log=not self._shown)
        self._shown = True

    def refresh(self, log: bool = True):
        self.body.clear_widgets()
        self.body.add_widget(heading("Music Recommendations"))
        self.body.add_widget(
            wrapping(
                "Ranked from plays, finishes, favorites, ratings, listening time, recency, skips, "
                "and artist, album, and genre affinity on this computer. The weights are in recommend.py."
            )
        )
        button = VWButton(text="Refresh", icon="spark", kind="primary")
        button.width = dp(130)
        button.bind(on_release=lambda *_: self.refresh(log=True))
        holder = BoxLayout(size_hint_y=None, height=dp(44))
        holder.add_widget(button)
        holder.add_widget(Widget())
        self.body.add_widget(holder)
        player = running_app().player
        exclude = {int(player.track_id)} if player.track_id else set()
        sections = build_recommendations(_db(), exclude_ids=exclude, log=log)
        any_rows = False
        for key, title in SECTION_ORDER:
            rows = sections.get(key) or []
            if not rows:
                continue
            any_rows = True
            self.body.add_widget(heading(title))
            cards = []
            ordered = [pack["track"] for pack in rows]
            for pack in rows:
                track = pack["track"]
                from vibewave.ui.kit import MediaCard

                cards.append(
                    MediaCard(
                        track.get("title") or "Untitled",
                        pack.get("reason") or "",
                        track.get("artwork_path") or "",
                        on_open=lambda item=track, group=ordered: play_tracks(group, start=item),
                    )
                )
            self.body.add_widget(hstrip(cards, dp(250)))
        if not any_rows:
            self.body.add_widget(EmptyState("Nothing to recommend", "Add music, then play a few songs."))


def _db():
    return running_app().db


class ConverterScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="converter", **kwargs)
        self.files: list[str] = []
        self._signature = None
        stored = _db().get_setting("convert_bitrate", "192") or "192"
        self.bitrate = int(stored) if str(stored).isdigit() else 192
        if self.bitrate not in BITRATES:
            self.bitrate = 192
        self.destination = _db().get_setting("convert_dest") or str(data_dir() / "Converted")
        self.import_on = (_db().get_setting("import_converted", "1") or "1") != "0"
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)
        self.body.add_widget(heading("MP4 to MP3"))
        self.ffmpeg = VWLabel(text="", role="small", wrap=True, size_hint_y=None, height=dp(36))
        self.body.add_widget(self.ffmpeg)
        self.body.add_widget(wrapping("FFmpeg extracts the audio and writes an MP3. The window stays responsive."))
        pick = VWButton(text="Choose files", icon="folder", kind="primary")
        pick.width = dp(150)
        pick.bind(on_release=lambda *_: self._pick())
        self.file_label = VWLabel(text="No files selected", role="small", muted=True, size_hint_y=None, height=dp(22))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        row.add_widget(pick)
        row.add_widget(self.file_label)
        self.body.add_widget(row)
        pairs = [(str(rate), f"{rate} kbps") for rate in BITRATES]
        self.rate_scroll, self.rate_chips = chip_scroller(pairs, str(self.bitrate), self._rate)
        self.body.add_widget(self.rate_scroll)
        dest = VWButton(text="Destination", icon="folder", kind="ghost")
        dest.width = dp(140)
        dest.bind(on_release=lambda *_: self._dest())
        self.dest_label = VWLabel(text=self.destination, role="small", muted=True)
        dest_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        dest_row.add_widget(dest)
        dest_row.add_widget(self.dest_label)
        self.body.add_widget(dest_row)
        switch_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(10))
        switch_row.add_widget(VWLabel(text="Add converted files to the library", role="body"))
        self.switch = VWSwitch(active=self.import_on)
        self.switch.bind(active=self._import_flag)
        switch_row.add_widget(self.switch)
        switch_row.add_widget(Widget())
        self.body.add_widget(switch_row)
        start = VWButton(text="Convert", icon="convert", kind="primary")
        start.width = dp(130)
        start.bind(on_release=lambda *_: self._start())
        cancel = VWButton(text="Cancel", kind="danger")
        cancel.width = dp(110)
        cancel.bind(on_release=lambda *_: running_app().converter.cancel())
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        actions.add_widget(start)
        actions.add_widget(cancel)
        actions.add_widget(Widget())
        self.body.add_widget(actions)
        self.state = VWLabel(text="Idle", role="small", muted=True, size_hint_y=None, height=dp(22))
        self.body.add_widget(self.state)
        self.jobs = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.jobs.bind(minimum_height=self.jobs.setter("height"))
        self.body.add_widget(self.jobs)
        self._banner()

    def on_enter(self):
        self._banner()

    def _banner(self):
        status = tool_status()
        if status["ffmpeg"]:
            self.ffmpeg.text = status["ffmpeg_version"] or "FFmpeg is available"
            self.ffmpeg.ink = (0, 0, 0, 0)
        else:
            self.ffmpeg.text = "FFmpeg was not found. Conversion and playback need it."
            colors = theme()
            if colors:
                self.ffmpeg.ink = colors.danger

    def _pick(self):
        chosen = pick_open_files("Choose media files")
        if not chosen:
            return
        self.files = list(chosen)
        names = ", ".join(os.path.basename(path) for path in self.files[:3])
        extra = "" if len(self.files) <= 3 else f"  +{len(self.files) - 3}"
        self.file_label.text = f"{len(self.files)} selected: {names}{extra}"

    def _rate(self, value: str):
        self.bitrate = int(value)
        _db().set_setting("convert_bitrate", value)
        for chip, rate in zip(self.rate_chips, BITRATES):
            chip.selected = str(rate) == value

    def _dest(self):
        chosen = pick_directory("Choose a destination folder")
        if not chosen:
            return
        self.destination = chosen
        self.dest_label.text = chosen
        _db().set_setting("convert_dest", chosen)

    def _import_flag(self, _switch, active: bool):
        self.import_on = bool(active)
        _db().set_setting("import_converted", "1" if active else "0")

    def _start(self):
        if not self.files:
            running_app().player.toast("Choose at least one file")
            return
        if not ffmpeg_path():
            running_app().player.toast("FFmpeg was not found")
            return
        os.makedirs(self.destination, exist_ok=True)
        plans = plan_outputs(self.files, self.destination)
        existing = [dest for _src, dest in plans if os.path.exists(dest)]
        if existing:
            shell().choose(
                "Some files already exist",
                f"{len(existing)} MP3 files are already in the destination.",
                [
                    ("Overwrite all", "danger", "overwrite"),
                    ("Skip existing", "ghost", "skip"),
                    ("Cancel", "ghost", "cancel"),
                ],
                self._begin,
            )
            return
        self._begin("overwrite")

    def _begin(self, mode: str):
        if mode == "cancel":
            return
        plans = plan_outputs(self.files, self.destination)
        error = running_app().converter.start(plans, self.bitrate, overwrite=(mode == "overwrite"))
        if error:
            running_app().player.toast(error)

    def poll(self):
        manager = running_app().converter
        jobs = manager.snapshot()
        self.state.text = "Converting…" if manager.running else ("Idle" if not jobs else "Finished")
        signature = tuple(
            (job["src"], job["status"], int(float(job["progress"]) * 20), job["error"], job["imported"]) for job in jobs
        )
        if signature != self._signature:
            self._signature = signature
            self.jobs.clear_widgets()
            for job in jobs:
                percent = int(float(job["progress"]) * 100)
                detail = job["error"] or job["status"]
                self.jobs.add_widget(
                    VWLabel(
                        text=f"{os.path.basename(job['src'])}    {percent}%    {detail}",
                        role="small",
                        size_hint_y=None,
                        height=dp(22),
                    )
                )
        if self.import_on:
            for index, job in enumerate(jobs):
                if job["status"] == "done" and not job["imported"]:
                    self._import_job(index, job)
                    break

    def _import_job(self, index: int, job: dict):
        running_app().converter.mark_imported(index)
        if is_opus_path(job["dest"]):
            return
        meta, error = read_metadata(job["dest"])
        if error or not meta:
            running_app().player.toast(f"Converted, but not added to the library ({error or 'unreadable'})")
            return
        database = _db()
        existing = database.find_by_path_key(path_key(meta["path"]))
        if existing:
            database.update_track_meta(existing["id"], meta, origin="import")
        else:
            twin = database.find_by_fingerprint(meta["fingerprint"]) if meta.get("fingerprint") else None
            if twin and (twin.get("missing") or not os.path.exists(twin["path"])):
                database.relocate_track(twin["id"], meta)
            elif twin:
                running_app().player.toast("That audio is already in the library")
                return
            else:
                database.insert_track(meta, origin="import")
        running_app().player.library_revision += 1
        running_app().player.toast(f"Added {meta['title']}")


class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="settings", **kwargs)
        self._guard = False
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)
        self.body.add_widget(heading("Settings"))
        self.body.add_widget(wrapping("Appearance, folders, and listening history stay on this computer."))
        self.body.add_widget(heading("Theme"))
        mode = running_app().theme.mode
        accent = running_app().theme.accent_name
        self.mode_scroll, self.mode_chips = chip_scroller(
            [("dark", "Dark"), ("light", "Light")],
            mode,
            lambda value: shell().set_theme(mode=value),
        )
        accents = [(name, name.title()) for name in ("violet", "cyan", "magenta", "emerald", "amber")]
        self.accent_scroll, self.accent_chips = chip_scroller(
            accents,
            accent,
            lambda value: shell().set_theme(accent=value),
        )
        self.body.add_widget(self.mode_scroll)
        self.body.add_widget(self.accent_scroll)
        self.body.add_widget(heading("Library"))
        scan_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(10))
        scan_row.add_widget(VWLabel(text="Scan folders when VibeWave opens", role="body"))
        initial = (_db().get_setting("scan_on_startup", "1") or "1") != "0"
        self.scan_switch = VWSwitch(active=initial)
        self.scan_switch.bind(active=self._scan_flag)
        scan_row.add_widget(self.scan_switch)
        scan_row.add_widget(Widget())
        self.body.add_widget(scan_row)
        add = VWButton(text="Add folder", icon="folder", kind="primary")
        add.width = dp(140)
        add.bind(on_release=lambda *_: shell().add_music_folder())
        exclude = VWButton(text="Exclude folder", icon="close", kind="ghost")
        exclude.width = dp(160)
        exclude.bind(on_release=lambda *_: self._exclude_folder())
        rescan = VWButton(text="Rescan", kind="ghost")
        rescan.width = dp(110)
        rescan.bind(on_release=lambda *_: shell().rescan())
        tools = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        tools.add_widget(add)
        tools.add_widget(exclude)
        tools.add_widget(rescan)
        tools.add_widget(Widget())
        self.body.add_widget(tools)
        self.folder_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.folder_box.bind(minimum_height=self.folder_box.setter("height"))
        self.exclusion_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.exclusion_box.bind(minimum_height=self.exclusion_box.setter("height"))
        self.body.add_widget(self.folder_box)
        self.body.add_widget(heading("Exclusions"))
        self.body.add_widget(self.exclusion_box)
        self.body.add_widget(heading("History"))
        self.body.add_widget(wrapping("Clearing history removes play counts and skips. Favorites and ratings stay."))
        clear = VWButton(text="Clear history", kind="danger")
        clear.width = dp(150)
        clear.bind(on_release=lambda *_: shell().confirm_clear_history())
        clear_row = BoxLayout(size_hint_y=None, height=dp(44))
        clear_row.add_widget(clear)
        clear_row.add_widget(Widget())
        self.body.add_widget(clear_row)
        self.body.add_widget(heading("FFmpeg"))
        self.ffmpeg = wrapping("Checking FFmpeg…")
        self.body.add_widget(self.ffmpeg)
        convert = VWButton(text="Open converter", icon="convert", kind="ghost")
        convert.width = dp(170)
        convert.bind(on_release=lambda *_: shell().go("converter"))
        convert_row = BoxLayout(size_hint_y=None, height=dp(44))
        convert_row.add_widget(convert)
        convert_row.add_widget(Widget())
        self.body.add_widget(convert_row)
        self.body.add_widget(heading("Shortcuts"))
        self.body.add_widget(
            wrapping(
                "Space play/pause. Left/right seek 5 seconds. Up/down volume. "
                "Ctrl+Left / Ctrl+Right previous and next. M mute. F favorite. S shuffle. R repeat. "
                "Q queue. E equalizer. N now playing. Ctrl+F search. Ctrl+. stop. Esc closes panels."
            )
        )
        self._built = True

    def on_enter(self):
        self.refresh()

    def mark_theme(self):
        mode = running_app().theme.mode
        accent = running_app().theme.accent_name
        for chip, key in zip(self.mode_chips, ("dark", "light")):
            chip.selected = key == mode
        for chip, key in zip(self.accent_chips, ("violet", "cyan", "magenta", "emerald", "amber")):
            chip.selected = key == accent

    def _scan_flag(self, _switch, active: bool):
        if self._guard:
            return
        _db().set_setting("scan_on_startup", "1" if active else "0")

    def _exclude_folder(self):
        chosen = pick_directory("Choose a folder to exclude")
        if not chosen:
            return
        _db().add_exclusion(chosen, "folder")
        running_app().player.toast("Folder excluded. Rescan to apply it.")
        self.refresh()

    def refresh(self):
        self.mark_theme()
        self._guard = True
        self.scan_switch.active = (_db().get_setting("scan_on_startup", "1") or "1") != "0"
        self._guard = False
        self.folder_box.clear_widgets()
        folders = _db().list_folders()
        if not folders:
            self.folder_box.add_widget(VWLabel(text="No music folders yet.", role="small", muted=True, size_hint_y=None, height=dp(24)))
        for folder in folders:
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            row.add_widget(VWLabel(text=folder["path"], role="small"))
            remove = VWButton(text="Remove", kind="ghost")
            remove.width = dp(100)
            remove.bind(on_release=lambda *_, folder_id=folder["id"]: self._remove_folder(folder_id))
            row.add_widget(remove)
            self.folder_box.add_widget(row)
        self.exclusion_box.clear_widgets()
        exclusions = _db().list_exclusions()
        if not exclusions:
            self.exclusion_box.add_widget(VWLabel(text="Nothing is excluded.", role="small", muted=True, size_hint_y=None, height=dp(24)))
        for item in exclusions:
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            row.add_widget(VWLabel(text=f"{item['kind']}: {item['path']}", role="small"))
            remove = VWButton(text="Allow", kind="ghost")
            remove.width = dp(90)
            remove.bind(on_release=lambda *_, exclusion_id=item["id"]: self._allow(exclusion_id))
            row.add_widget(remove)
            self.exclusion_box.add_widget(row)
        status = tool_status()
        if status["ffmpeg"]:
            self.ffmpeg.text = status["ffmpeg_version"] or status["ffmpeg"]
        else:
            self.ffmpeg.text = "FFmpeg was not found. Install it, then reopen VibeWave."

    def _remove_folder(self, folder_id: int):
        _db().remove_folder(folder_id)
        running_app().player.toast("Folder removed. Rescan to update the library.")
        self.refresh()

    def _allow(self, exclusion_id: int):
        _db().remove_exclusion(exclusion_id)
        running_app().player.library_revision += 1
        running_app().player.toast("Exclusion removed")
        self.refresh()


SOUND_SCREENS = [
    VisualizerScreen,
    EqualizerScreen,
    RecommendScreen,
    ConverterScreen,
    SettingsScreen,
]
