"""Small layout helpers shared by the screens."""

from __future__ import annotations

from kivy.app import App
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from vibewave.ui.widgets import (
    Chip,
    CoverImage,
    Panel,
    VWButton,
    VWLabel,
    radii,
    theme,
    watch_theme,
)


def app():
    return App.get_running_app()


def root():
    running = app()
    return running.root if running else None


def page_scroll():
    scroll = ScrollView(bar_width=dp(6), scroll_type=["bars", "content"], do_scroll_x=False)
    body = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        spacing=dp(14),
        padding=(dp(28), dp(18), dp(28), dp(28)),
    )
    body.bind(minimum_height=body.setter("height"))
    scroll.add_widget(body)
    return scroll, body


def heading(text: str) -> VWLabel:
    return VWLabel(text=text, role="section", size_hint_y=None, height=dp(30))


def wrapping(text: str, role: str = "small", muted: bool = True) -> VWLabel:
    label = VWLabel(text=text, role=role, muted=muted, wrap=True, size_hint_y=None, height=dp(20))
    label.bind(texture_size=lambda widget, size: setattr(widget, "height", max(dp(18), size[1] + dp(2))))
    return label


def play_tracks(tracks: list[dict], *, start: dict | None = None, shuffle: bool = False) -> None:
    import random

    ids = [int(track["id"]) for track in tracks if track.get("id")]
    if not ids:
        running = app()
        if running:
            running.player.toast("Nothing to play")
        return
    if shuffle:
        random.shuffle(ids)
        start_id = ids[0]
    elif start and int(start["id"]) in ids:
        start_id = int(start["id"])
    else:
        start_id = ids[0]
    app().player.play_ids(ids, start_id, user_skip=True)


def chip_scroller(pairs: list[tuple[str, str]], selected: str, on_pick):
    scroller = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(42), bar_width=0)
    row = BoxLayout(orientation="horizontal", size_hint=(None, None), height=dp(34), spacing=dp(8))
    row.bind(minimum_width=row.setter("width"))
    chips = []
    for key, label in pairs:
        chip = Chip(text=label)
        chip.selected = key == selected
        chip.bind(on_release=lambda *_, item=key: on_pick(item))
        row.add_widget(chip)
        chips.append(chip)
    scroller.add_widget(row)
    return scroller, chips


def hstrip(widgets: list, height: float):
    scroller = ScrollView(
        do_scroll_y=False,
        size_hint_y=None,
        height=height,
        bar_width=0,
        scroll_type=["content"],
    )
    row = BoxLayout(
        orientation="horizontal",
        size_hint=(None, None),
        height=height - dp(8),
        spacing=dp(12),
    )
    row.bind(minimum_width=row.setter("width"))
    for widget in widgets:
        row.add_widget(widget)
    if not widgets:
        row.width = dp(4)
    scroller.add_widget(row)
    return scroller


class MediaCard(ButtonBehavior, BoxLayout):
    """Album, artist, or recommendation card. The play control does not open the page."""

    def __init__(self, title: str, subtitle: str, art: str, on_open, on_play=None, stretch: bool = False, **kwargs):
        height = dp(274) if on_play else dp(228)
        size_hint = (1, None) if stretch else (None, None)
        super().__init__(
            orientation="vertical",
            padding=(dp(10), dp(10)),
            spacing=dp(6),
            size_hint=size_hint,
            size=(dp(188), height),
            **kwargs,
        )
        self.cover = CoverImage(source=art or "", title=title or "?", radius=dp(14), size_hint_y=None, height=dp(148))
        self.add_widget(self.cover)
        self.add_widget(VWLabel(text=title or "Untitled", role="body", size_hint_y=None, height=dp(22)))
        self.add_widget(VWLabel(text=subtitle or "", role="small", muted=True, size_hint_y=None, height=dp(18)))
        if on_play:
            play = VWButton(text="Play", icon="play", kind="primary")
            play.width = dp(92)
            play.height = dp(34)
            play.bind(on_release=lambda *_: on_play())
            holder = BoxLayout(size_hint_y=None, height=dp(36))
            holder.add_widget(play)
            holder.add_widget(Widget())
            self.add_widget(holder)
        self.bind(on_release=lambda *_: on_open())
        self.bind(pos=self._paint, size=self._paint, state=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        fill = colors.surface_2 if self.state == "down" else colors.surface
        with self.canvas.before:
            Color(*colors.stroke)
            RoundedRectangle(pos=(self.x - 1, self.y - 1), size=(self.width + 2, self.height + 2), radius=radii(dp(18)))
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(16)))


class StatPill(Panel):
    def __init__(self, value: str, label: str, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(148), dp(74)),
            padding=(dp(14), dp(10)),
            spacing=0,
            radius=dp(16),
            **kwargs,
        )
        self.value_label = VWLabel(text=value, role="title", size_hint_y=None, height=dp(30))
        self.caption = VWLabel(text=label, role="micro", muted=True, size_hint_y=None, height=dp(16))
        self.add_widget(self.value_label)
        self.add_widget(self.caption)
