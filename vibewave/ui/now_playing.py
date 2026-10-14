"""Expanded player. Stays dark even when the library theme is light.

Spectrum bars are a real FFT from the playback engine. Particles and the slow
glow are visual effects. The waveform peaks are measured from the file.
"""

from __future__ import annotations

import math

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, PopMatrix, PushMatrix, Rectangle, Rotate
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from vibewave.formatutil import format_listen_time
from vibewave.ui.widgets import CoverImage, IconButton, SpectrumBars, VWLabel, WaveformSeek

_WHITE = (0.97, 0.97, 0.99, 1)
_MUTED = (0.78, 0.80, 0.88, 1)
_FAINT = (0.64, 0.66, 0.76, 1)
_CAPTION = (
    "Bars are a live FFT of playback, about 30 Hz to 16 kHz. "
    "The waveform is measured from the file. "
    "Particles and the breathing glow are visual effects; the glow also follows the output level."
)
_CAPTION_WAIT = (
    "Bars are a live FFT of playback, about 30 Hz to 16 kHz. "
    "A plain progress line shows until the file waveform is ready. "
    "Particles and the breathing glow are visual effects; the glow also follows the output level."
)


def _player():
    running = App.get_running_app()
    return running.player if running else None


class _Stage(Widget):
    phase = NumericProperty(0)
    color_a = ListProperty([0.16, 0.08, 0.28, 1])
    color_b = ListProperty([0.05, 0.08, 0.16, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.particles = []
        seed = 0.17
        for index in range(18):
            seed = (seed * 37.2 + index * 0.13) % 1
            self.particles.append((seed, (seed * 3.1) % 1, 0.45 + (index % 5) * 0.12))
        self.bind(pos=self.redraw, size=self.redraw, phase=self.redraw, color_a=self.redraw, color_b=self.redraw)

    def redraw(self, *_args):
        self.canvas.before.clear()
        self.canvas.clear()
        if self.width < 4:
            return
        with self.canvas.before:
            Color(0.035, 0.035, 0.055, 1)
            Rectangle(pos=self.pos, size=self.size)
            Color(self.color_a[0], self.color_a[1], self.color_a[2], 0.55)
            Ellipse(
                pos=(self.x - self.width * 0.08, self.y + self.height * 0.25),
                size=(self.width * 0.62, self.height * 0.72),
            )
            Color(self.color_b[0], self.color_b[1], self.color_b[2], 0.42)
            Ellipse(
                pos=(self.right - self.width * 0.5, self.y - self.height * 0.08),
                size=(self.width * 0.58, self.height * 0.6),
            )
        with self.canvas:
            for px, py, speed in self.particles:
                shift = (self.phase * 0.015 * speed) % 1
                x = self.x + ((px + shift) % 1) * self.width
                y = self.y + ((py + math.sin(self.phase * speed) * 0.015) % 1) * self.height
                size = dp(3 if speed > 0.7 else 2)
                Color(1, 1, 1, 0.14)
                Ellipse(pos=(x, y), size=(size, size))


class _SpinCover(FloatLayout):
    angle = NumericProperty(0)
    glow = ListProperty([0.55, 0.42, 1, 0.35])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cover = CoverImage(size_hint=(None, None), radius=dp(24))
        self.add_widget(self.cover)
        with self.canvas.before:
            self._gcolor = Color(1, 1, 1, 0.3)
            self._glow = Ellipse()
            PushMatrix()
            self._rotate = Rotate(angle=0, origin=self.center)
        with self.canvas.after:
            PopMatrix()
        self.bind(pos=self._layout, size=self._layout, angle=self._spin, glow=self._tint)

    def _layout(self, *_args):
        side = min(self.width, self.height) * 0.78
        self.cover.size = (side, side)
        self.cover.center = self.center
        glow_side = side * 1.22
        self._glow.pos = (self.center_x - glow_side / 2, self.center_y - glow_side / 2)
        self._glow.size = (glow_side, glow_side)
        self._rotate.origin = self.center

    def _spin(self, *_args):
        self._rotate.angle = self.angle
        self._rotate.origin = self.center

    def _tint(self, *_args):
        glow = self.glow
        self._gcolor.rgba = (glow[0], glow[1], glow[2], glow[3] if len(glow) > 3 else 0.35)


class NowPlaying(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opened = False
        self.opacity = 0
        self._phase = 0.0
        self._angle = 0.0
        self._settled = False
        self.stage = _Stage()
        self.add_widget(self.stage)

        self.spin = _SpinCover()
        left = BoxLayout(orientation="vertical", padding=(dp(36), dp(24)), size_hint_x=0.42)
        left.add_widget(self.spin)

        self.title = VWLabel(text="Nothing playing", role="display", ink=_WHITE, size_hint_y=None, height=dp(42))
        self.artist = VWLabel(text="Choose a song", role="title", ink=_MUTED, size_hint_y=None, height=dp(30))
        self.album = VWLabel(text="", role="body", ink=_FAINT, size_hint_y=None, height=dp(22))
        self.seek = WaveformSeek(immersive=True, size_hint_y=None, height=dp(42))
        self.seek.drag_started = self._drag
        self.seek.released = self._release
        self.elapsed = VWLabel(text="0:00", role="small", ink=_MUTED, size_hint_x=None, width=dp(64))
        self.duration = VWLabel(text="0:00", role="small", ink=_MUTED, size_hint_x=None, width=dp(64), halign="right")
        times = BoxLayout(size_hint_y=None, height=dp(20))
        times.add_widget(self.elapsed)
        times.add_widget(Widget())
        times.add_widget(self.duration)

        self.prev_btn = IconButton(icon="prev", immersive=True)
        self.play_btn = IconButton(icon="play", kind="primary", immersive=True)
        self.play_btn.size = (dp(64), dp(64))
        self.next_btn = IconButton(icon="next", immersive=True)
        self.prev_btn.bind(on_release=lambda *_: self._call("previous"))
        self.play_btn.bind(on_release=lambda *_: self._call("toggle"))
        self.next_btn.bind(on_release=lambda *_: self._call("next"))
        transport = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(8))
        transport.add_widget(Widget())
        transport.add_widget(self.prev_btn)
        transport.add_widget(self.play_btn)
        transport.add_widget(self.next_btn)
        transport.add_widget(Widget())

        self.fav_btn = IconButton(icon="heart", immersive=True)
        self.album_btn = IconButton(icon="album", immersive=True)
        self.queue_btn = IconButton(icon="queue", immersive=True)
        self.eq_btn = IconButton(icon="sliders", immersive=True)
        self.fav_btn.bind(on_release=lambda *_: self._call("toggle_favorite"))
        self.album_btn.bind(on_release=lambda *_: self._open_album())
        self.queue_btn.bind(on_release=lambda *_: self._open_queue())
        self.eq_btn.bind(on_release=lambda *_: self._open_eq())
        extras = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(4))
        extras.add_widget(Widget())
        for button in (self.fav_btn, self.album_btn, self.queue_btn, self.eq_btn):
            extras.add_widget(button)
        extras.add_widget(Widget())

        self.stars = []
        star_row = BoxLayout(size_hint_y=None, height=dp(36))
        star_row.add_widget(Widget())
        for number in range(1, 6):
            button = IconButton(icon="star", immersive=True)
            button.size = (dp(34), dp(34))
            button.bind(on_release=lambda *_, stars=number: self._rate(stars))
            self.stars.append(button)
            star_row.add_widget(button)
        star_row.add_widget(Widget())

        self.lyric = VWLabel(text="", role="title", ink=_WHITE, size_hint_y=None, height=0)
        self.details = VWLabel(text="", role="small", ink=_FAINT, size_hint_y=None, height=dp(22))
        self.gain = VWLabel(text="", role="micro", ink=_FAINT, size_hint_y=None, height=dp(16))
        self.spectrum = SpectrumBars(count=40, running=False)
        self.caption = VWLabel(text=_CAPTION_WAIT, role="micro", ink=_FAINT, wrap=True, size_hint_y=None, height=dp(48))

        right = BoxLayout(orientation="vertical", padding=(dp(8), dp(18), dp(36), dp(16)), spacing=dp(6))
        for widget in (
            self.title,
            self.artist,
            self.album,
            self.seek,
            times,
            transport,
            extras,
            star_row,
            self.lyric,
            self.details,
            self.gain,
            self.spectrum,
            self.caption,
        ):
            right.add_widget(widget)

        body = BoxLayout()
        body.add_widget(left)
        body.add_widget(right)

        top = BoxLayout(size_hint_y=None, height=dp(56), padding=(dp(18), dp(8)), spacing=dp(8))
        close = IconButton(icon="close", immersive=True)
        close.bind(on_release=lambda *_: self.hide())
        label = VWLabel(text="Now Playing", role="body", ink=_MUTED)
        self.shuffle_btn = IconButton(icon="shuffle", immersive=True)
        self.repeat_btn = IconButton(icon="repeat", immersive=True)
        self.shuffle_btn.bind(on_release=lambda *_: self._call("toggle_shuffle"))
        self.repeat_btn.bind(on_release=lambda *_: self._call("cycle_repeat"))
        top.add_widget(close)
        top.add_widget(label)
        top.add_widget(Widget())
        top.add_widget(self.shuffle_btn)
        top.add_widget(self.repeat_btn)

        column = BoxLayout(orientation="vertical")
        column.add_widget(top)
        column.add_widget(body)
        self.add_widget(column)
        Clock.schedule_interval(self._tick, 1 / 30)
        Clock.schedule_once(self._bind, 0)

    def _bind(self, *_args):
        player = _player()
        if not player:
            return
        player.bind(
            title=self._track,
            artist=self._track,
            album=self._track,
            artwork=self._track,
            playing=self._transport,
            favorite=self._transport,
            shuffle=self._transport,
            repeat_mode=self._transport,
            rating=self._stars,
            position=self._time,
            duration=self._time,
            peaks=self._peaks,
            lyric_line=self._lyric,
            lyrics_mode=self._lyric,
            lyrics_revision=self._lyric,
            color_revision=self._colors,
            track_id=self._details,
            stats_revision=self._details,
            replaygain_label=self._details,
        )
        self._track()
        self._transport()
        self._stars()
        self._colors()
        self._lyric()
        self._details()

    def show(self):
        self.opened = True
        self.spectrum.running = True
        self._settled = False
        Animation.cancel_all(self)
        Animation(opacity=1, d=0.18).start(self)

    def hide(self):
        self.opened = False
        self.spectrum.running = False
        Animation.cancel_all(self)
        self.opacity = 0

    def on_touch_down(self, touch):
        if not self.opened:
            return False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if not self.opened:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if not self.opened:
            return False
        return super().on_touch_up(touch)

    def _tick(self, dt):
        if not self.opened:
            return
        running = App.get_running_app()
        player = _player()
        moving = bool(player and player.playing and running and not running.reduced_motion)
        if not moving:
            if not self._settled:
                self._apply_motion()
                self._settled = True
            return
        self._settled = False
        self._phase += dt
        self._angle = (self._angle + dt * 8.0) % 360
        self._apply_motion()

    def _apply_motion(self):
        player = _player()
        running = App.get_running_app()
        level = running.engine.output_level() if running and running.engine else 0.0
        pulse = 0.22 + 0.08 * math.sin(self._phase * 1.4) + min(0.28, level * 0.45)
        glow = list(player.color_glow) if player else [0.55, 0.42, 1, 1]
        if len(glow) < 4:
            glow = list(glow) + [1]
        glow[3] = pulse
        self.spin.glow = glow
        self.spin.angle = self._angle if player and player.playing else self._angle
        self.stage.phase = self._phase

    def _track(self, *_args):
        player = _player()
        if not player:
            return
        self.title.text = player.title
        self.artist.text = player.artist
        self.album.text = player.album
        self.spin.cover.source = player.artwork or ""
        self.spin.cover.title = player.title or ""
        if self.opened:
            self.title.opacity = 0.35
            Animation(opacity=1, d=0.22).start(self.title)

    def _transport(self, *_args):
        player = _player()
        running = App.get_running_app()
        if not player or not running:
            return
        accent = running.theme.accent
        self.play_btn.icon = "pause" if player.playing else "play"
        self.fav_btn.icon = "heart_fill" if player.favorite else "heart"
        self.fav_btn.icon_color = accent if player.favorite else [1, 1, 1, 1]
        self.shuffle_btn.icon_color = accent if player.shuffle else [1, 1, 1, 1]
        if player.repeat_mode == "one":
            self.repeat_btn.icon = "repeat_one"
            self.repeat_btn.icon_color = accent
        else:
            self.repeat_btn.icon = "repeat"
            self.repeat_btn.icon_color = accent if player.repeat_mode == "all" else [1, 1, 1, 1]
        self._settled = False

    def _stars(self, *_args):
        player = _player()
        running = App.get_running_app()
        if not player or not running:
            return
        rating = int(player.rating or 0)
        accent = running.theme.accent
        for index, button in enumerate(self.stars, start=1):
            button.icon = "star_fill" if index <= rating else "star"
            button.icon_color = accent if index <= rating else [1, 1, 1, 1]

    def _time(self, *_args):
        player = _player()
        if not player or self.seek.dragging or player.user_seeking:
            if player:
                self.elapsed.text = format_time(player.position)
                self.duration.text = format_time(player.duration)
            return
        self.seek.maximum = max(float(player.duration or 0), 0.01)
        self.seek.value = min(float(player.position or 0), self.seek.maximum)
        self.elapsed.text = format_time(player.position)
        self.duration.text = format_time(player.duration)

    def _peaks(self, *_args):
        player = _player()
        if not player:
            return
        self.seek.peaks = list(player.peaks or [])
        self.caption.text = _CAPTION if player.peaks else _CAPTION_WAIT

    def _colors(self, *_args):
        player = _player()
        if not player:
            return
        self.stage.color_a = list(player.color_a)
        self.stage.color_b = list(player.color_b)
        self._settled = False

    def _lyric(self, *_args):
        player = _player()
        if not player:
            return
        if player.lyrics_mode == "lrc":
            self.lyric.height = dp(36)
            self.lyric.opacity = 1
            self.lyric.text = player.lyric_line or "…"
        elif player.lyrics_mode == "text":
            self.lyric.height = dp(48)
            self.lyric.opacity = 1
            self.lyric.text = player.lyrics_text
        else:
            self.lyric.height = 0
            self.lyric.opacity = 0
            self.lyric.text = ""

    def _details(self, *_args):
        player = _player()
        running = App.get_running_app()
        if not player or not running or not player.track_id:
            self.details.text = ""
            self.gain.text = ""
            return
        track = running.db.get_track(int(player.track_id))
        if not track:
            return
        genre = track.get("genre") or "Unknown genre"
        year = str(track["year"]) if track.get("year") else "Year unknown"
        plays = int(track.get("play_count") or 0)
        self.details.text = f"{genre}   ·   {year}   ·   {plays} plays   ·   {format_listen_time(track.get('listen_duration'))}"
        self.gain.text = player.replaygain_label or ""

    def _drag(self):
        player = _player()
        if player:
            player.user_seeking = True

    def _release(self, value):
        player = _player()
        if not player:
            return
        player.seek(value)
        player.user_seeking = False

    def _rate(self, stars: int):
        player = _player()
        if player:
            player.set_rating(stars)

    def _call(self, name: str):
        player = _player()
        if not player:
            return
        if name == "next":
            player.next(user=True)
            return
        getattr(player, name)()

    def _open_album(self):
        player = _player()
        running = App.get_running_app()
        if not player or not running or not player.album:
            return
        self.hide()
        running.root.open_album(player.artist, player.album)

    def _open_queue(self):
        running = App.get_running_app()
        if running and running.root:
            running.root.show_queue()

    def _open_eq(self):
        running = App.get_running_app()
        if not running or not running.root:
            return
        self.hide()
        running.root.go("equalizer")


def format_time(seconds: float) -> str:
    from vibewave.formatutil import format_duration

    return format_duration(seconds)
