"""Persistent transport. This bar is not inside a Screen, so its spectrum can draw."""

from __future__ import annotations

from kivy.app import App
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

from vibewave.formatutil import format_duration
from vibewave.ui.widgets import IconButton, PrettySlider, SpectrumBars, VWLabel, WaveformSeek, theme, watch_theme


def _player():
    running = App.get_running_app()
    return running.player if running else None


class _Identity(ButtonBehavior, BoxLayout):
    pass


class PlayerBar(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(112),
            padding=(dp(16), dp(6), dp(16), dp(8)),
            spacing=dp(2),
            **kwargs,
        )
        self.seek = WaveformSeek(size_hint_y=None, height=dp(26))
        self.seek.drag_started = self._drag_seek
        self.seek.released = self._release_seek
        self.elapsed = VWLabel(text="0:00", role="micro", muted=True, size_hint_x=None, width=dp(54), halign="right")
        self.total = VWLabel(text="0:00", role="micro", muted=True, size_hint_x=None, width=dp(54))
        seek_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        seek_row.add_widget(self.elapsed)
        seek_row.add_widget(self.seek)
        seek_row.add_widget(self.total)

        self.cover_title = VWLabel(text="Nothing playing", role="body", size_hint_y=None, height=dp(22))
        self.cover_artist = VWLabel(text="Choose a song to begin", role="small", muted=True, size_hint_y=None, height=dp(18))
        text_col = BoxLayout(orientation="vertical", padding=(0, dp(6)))
        text_col.add_widget(self.cover_title)
        text_col.add_widget(self.cover_artist)

        from vibewave.ui.widgets import CoverImage

        self.art = CoverImage(size_hint=(None, None), size=(dp(48), dp(48)), radius=dp(10))
        self.identity = _Identity(spacing=dp(10), size_hint_x=0.36)
        self.identity.add_widget(self.art)
        self.identity.add_widget(text_col)
        self.identity.bind(on_release=lambda *_: self._open_now())

        self.shuffle_btn = IconButton(icon="shuffle")
        self.prev_btn = IconButton(icon="prev")
        self.play_btn = IconButton(icon="play", kind="primary")
        self.play_btn.size = (dp(52), dp(52))
        self.next_btn = IconButton(icon="next")
        self.repeat_btn = IconButton(icon="repeat")
        for button, handler in (
            (self.shuffle_btn, self._shuffle),
            (self.prev_btn, self._previous),
            (self.play_btn, self._toggle),
            (self.next_btn, self._next),
            (self.repeat_btn, self._repeat),
        ):
            button.bind(on_release=lambda *_, fn=handler: fn())

        center = BoxLayout(size_hint_x=0.30, spacing=dp(4))
        center.add_widget(Widget())
        for button in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            center.add_widget(button)
        center.add_widget(Widget())

        self.volume_btn = IconButton(icon="volume")
        self.volume_btn.bind(on_release=lambda *_: self._mute())
        self.volume = PrettySlider(size_hint=(None, None), size=(dp(110), dp(28)), min_value=0, max_value=1, value=0.85)
        self.volume.changed = self._volume
        self.spectrum = SpectrumBars(count=12, size_hint=(None, None), size=(dp(86), dp(32)))
        self.queue_btn = IconButton(icon="queue")
        self.expand_btn = IconButton(icon="expand")
        self.queue_btn.bind(on_release=lambda *_: self._queue())
        self.expand_btn.bind(on_release=lambda *_: self._open_now())

        right = BoxLayout(size_hint_x=0.34, spacing=dp(4))
        right.add_widget(Widget())
        right.add_widget(self.spectrum)
        right.add_widget(self.volume_btn)
        right.add_widget(self.volume)
        right.add_widget(self.queue_btn)
        right.add_widget(self.expand_btn)

        row = BoxLayout(spacing=dp(8))
        row.add_widget(self.identity)
        row.add_widget(center)
        row.add_widget(right)
        self.add_widget(seek_row)
        self.add_widget(row)
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)
        from kivy.clock import Clock

        Clock.schedule_once(self._bind, 0)

    def _bind(self, *_args):
        player = _player()
        if not player:
            return
        player.bind(
            title=self._sync_track,
            artist=self._sync_track,
            artwork=self._sync_track,
            playing=self._sync_transport,
            shuffle=self._sync_transport,
            repeat_mode=self._sync_transport,
            muted=self._sync_transport,
            volume=self._sync_transport,
            position=self._sync_time,
            duration=self._sync_time,
            peaks=self._sync_peaks,
            has_track=self._sync_track,
        )
        self.volume.value = player.volume
        self._sync_track()
        self._sync_transport()
        self._sync_time()

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        with self.canvas.before:
            Color(*colors.elev)
            Rectangle(pos=self.pos, size=self.size)
            Color(*colors.stroke)
            Rectangle(pos=(self.x, self.top - 1), size=(self.width, 1))

    def _sync_track(self, *_args):
        player = _player()
        if not player:
            return
        self.cover_title.text = player.title or "Nothing playing"
        self.cover_artist.text = player.artist or ""
        self.art.source = player.artwork or ""
        self.art.title = player.title or ""

    def _sync_transport(self, *_args):
        player = _player()
        colors = theme()
        if not player or not colors:
            return
        self.play_btn.icon = "pause" if player.playing else "play"
        self.shuffle_btn.icon_color = colors.accent if player.shuffle else [1, 1, 1, 1]
        if player.repeat_mode == "one":
            self.repeat_btn.icon = "repeat_one"
            self.repeat_btn.icon_color = colors.accent
        elif player.repeat_mode == "all":
            self.repeat_btn.icon = "repeat"
            self.repeat_btn.icon_color = colors.accent
        else:
            self.repeat_btn.icon = "repeat"
            self.repeat_btn.icon_color = [1, 1, 1, 1]
        self.volume_btn.icon = "mute" if player.muted or player.volume <= 0.001 else "volume"
        if not self.volume.dragging:
            self.volume.value = player.volume

    def _sync_time(self, *_args):
        player = _player()
        if not player:
            return
        if not self.seek.dragging and not player.user_seeking:
            self.seek.maximum = max(float(player.duration or 0), 0.01)
            self.seek.value = min(float(player.position or 0), self.seek.maximum)
        self.elapsed.text = format_duration(player.position)
        self.total.text = format_duration(player.duration)

    def _sync_peaks(self, *_args):
        player = _player()
        if player:
            self.seek.peaks = list(player.peaks or [])

    def _drag_seek(self):
        player = _player()
        if player:
            player.user_seeking = True

    def _release_seek(self, value):
        player = _player()
        if not player:
            return
        player.seek(value)
        player.user_seeking = False

    def _volume(self, value):
        player = _player()
        if player:
            player.set_volume(value)

    def _toggle(self):
        player = _player()
        if player:
            player.toggle()

    def _previous(self):
        player = _player()
        if player:
            player.previous()

    def _next(self):
        player = _player()
        if player:
            player.next(user=True)

    def _shuffle(self):
        player = _player()
        if player:
            player.toggle_shuffle()

    def _repeat(self):
        player = _player()
        if player:
            player.cycle_repeat()

    def _mute(self):
        player = _player()
        if player:
            player.toggle_mute()

    def _open_now(self):
        running = App.get_running_app()
        if running and running.root:
            running.root.show_now()

    def _queue(self):
        running = App.get_running_app()
        if running and running.root:
            running.root.toggle_queue()
