"""Queue drawer, context menu, dialogs, and toasts.

A closed overlay must not use `disabled`. Kivy treats a disabled widget that
the pointer hits as the end of the touch, which would freeze the window.
"""

from __future__ import annotations

from kivy.animation import Animation
from kivy.app import App
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from vibewave.ui.widgets import DesktopScroll, IconButton, Panel, VWButton, VWLabel, VWTextInput, radii, theme, watch_theme


def _player():
    running = App.get_running_app()
    return running.player if running else None


class _Dismiss(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opened = False
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


class QueueRow(ButtonBehavior, BoxLayout):
    def __init__(self, row: dict, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8), padding=(dp(8), 0), **kwargs)
        self.position = int(row["position"])
        self.current = bool(row.get("current"))
        text = BoxLayout(orientation="vertical", padding=(0, dp(6)))
        title = VWLabel(text=row.get("title") or "Untitled", role="body", size_hint_y=None, height=dp(20))
        artist = VWLabel(text=row.get("artist") or "", role="micro", muted=True, size_hint_y=None, height=dp(16))
        text.add_widget(title)
        text.add_widget(artist)
        remove = IconButton(icon="close")
        remove.size = (dp(32), dp(32))
        remove.bind(on_release=lambda *_: self._remove())
        self.add_widget(text)
        self.add_widget(remove)
        self.bind(on_release=lambda *_: self._jump(), pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        if not self.current and self.state != "down":
            return
        fill = (*colors.accent[:3], 0.18) if self.current else colors.hover
        with self.canvas.before:
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(10)))

    def _jump(self):
        player = _player()
        if player:
            player.jump_queue(self.position)

    def _remove(self):
        player = _player()
        if player:
            player.remove_from_queue(self.position)
        running = App.get_running_app()
        if running and running.root:
            running.root.queue_panel.refresh()


class QueuePanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None, 1), width=dp(360), padding=(dp(16), dp(16)), spacing=dp(8), **kwargs)
        self.opened = False
        self.opacity = 0
        self.pos_hint = {"right": 1, "top": 1}
        header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        header.add_widget(VWLabel(text="Queue", role="section"))
        clear = VWButton(text="Clear upcoming", kind="ghost")
        clear.width = dp(150)
        clear.bind(on_release=lambda *_: self._clear())
        close = IconButton(icon="close")
        close.bind(on_release=lambda *_: self.hide())
        header.add_widget(clear)
        header.add_widget(close)
        self.scroll = DesktopScroll()
        self.rows = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.rows.bind(minimum_height=self.rows.setter("height"))
        self.scroll.add_widget(self.rows)
        self.empty = VWLabel(text="The queue is empty", role="small", muted=True, size_hint_y=None, height=dp(28))
        self.add_widget(header)
        self.add_widget(self.empty)
        self.add_widget(self.scroll)
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.elev)
            Rectangle(pos=self.pos, size=self.size)
            Color(*colors.stroke)
            Rectangle(pos=(self.x, self.y), size=(1, self.height))

    def show(self):
        self.opened = True
        self.opacity = 1
        self.refresh()

    def hide(self):
        self.opened = False
        self.opacity = 0

    def toggle(self):
        if self.opened:
            self.hide()
        else:
            self.show()

    def refresh(self):
        self.rows.clear_widgets()
        player = _player()
        rows = player.queue_rows() if player else []
        self.empty.opacity = 0 if rows else 1
        self.empty.height = 0 if rows else dp(28)
        for row in rows:
            self.rows.add_widget(QueueRow(row))

    def on_touch_down(self, touch):
        if not self.opened:
            return False
        if not self.collide_point(*touch.pos):
            self.hide()
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if not self.opened:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if not self.opened:
            return False
        return super().on_touch_up(touch)

    def _clear(self):
        player = _player()
        if player:
            player.clear_upcoming()
        self.refresh()


class ContextMenu(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None, None), width=dp(248), padding=dp(8), spacing=dp(4), **kwargs)
        self.opened = False
        self.opacity = 0
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.stroke)
            RoundedRectangle(pos=(self.x - 1, self.y - 1), size=(self.width + 2, self.height + 2), radius=radii(dp(14)))
            Color(*colors.elev)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(12)))

    def show(self, pos, actions: list[tuple[str, object]]):
        self.clear_widgets()
        for label, callback in actions:
            button = VWButton(text=label, kind="ghost")
            button.size_hint_x = 1
            button.bind(on_release=lambda *_, fn=callback: self._run(fn))
            self.add_widget(button)
        self.height = dp(16) + max(1, len(actions)) * dp(44)
        from kivy.core.window import Window

        x = min(max(dp(8), pos[0]), Window.width - self.width - dp(8))
        y = min(max(dp(8), pos[1] - dp(12)), Window.height - self.height - dp(8))
        self.pos = (x, y)
        self.opened = True
        self.opacity = 1

    def hide(self):
        self.opened = False
        self.opacity = 0

    def _run(self, callback):
        self.hide()
        if callback:
            callback()

    def on_touch_down(self, touch):
        if not self.opened:
            return False
        if self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self.hide()
        return True

    def on_touch_move(self, touch):
        if not self.opened:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if not self.opened:
            return False
        return super().on_touch_up(touch)


class Modal(_Dismiss):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._callback = None
        self._prompt = False
        self.card = Panel(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(480), dp(260)),
            pos_hint={"center_x": 0.5, "center_y": 0.55},
            padding=(dp(20), dp(18)),
            spacing=dp(10),
            radius=dp(18),
        )
        self.title = VWLabel(text="", role="title", size_hint_y=None, height=dp(32))
        self.body = VWLabel(text="", role="small", muted=True, wrap=True, size_hint_y=None, height=dp(52))
        self.field_wrap = Panel(size_hint_y=None, height=0, radius=dp(12), padding=(dp(6), 0))
        self.field = VWTextInput(hint_text="")
        self.field.bind(on_text_validate=lambda *_: self._accept())
        self.field_wrap.add_widget(self.field)
        self.actions = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(44), spacing=dp(8))
        self.card.add_widget(self.title)
        self.card.add_widget(self.body)
        self.card.add_widget(self.field_wrap)
        self.card.add_widget(self.actions)
        self.add_widget(self.card)
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.overlay)
            Rectangle(pos=self.pos, size=self.size)

    def confirm(self, title: str, body: str, on_ok, ok_text: str = "OK", danger: bool = False):
        self._open(
            title,
            body,
            [("Cancel", "ghost", None), (ok_text, "danger" if danger else "primary", on_ok)],
            prompt=False,
        )

    def prompt(self, title: str, hint: str, initial: str, on_ok):
        self.field.hint_text = hint
        self._open(title, "", [("Cancel", "ghost", None), ("Save", "primary", on_ok)], prompt=True, initial=initial)

    def choose(self, title: str, body: str, options: list[tuple[str, str, object]], on_choice):
        actions = [(label, kind, (lambda value=value: on_choice(value))) for label, kind, value in options]
        self._open(title, body, actions, prompt=False)

    def _open(self, title, body, actions, *, prompt: bool, initial: str = ""):
        self.title.text = title
        self.body.text = body
        self.body.height = dp(8) if not body else dp(56)
        self._prompt = prompt
        self._callback = actions[-1][2] if actions else None
        self.field.text = initial
        self.field_wrap.height = dp(44) if prompt else 0
        self.field_wrap.opacity = 1 if prompt else 0
        self.actions.clear_widgets()
        vertical = len(actions) > 3
        self.actions.orientation = "vertical" if vertical else "horizontal"
        self.actions.height = len(actions) * dp(46) if vertical else dp(44)
        for label, kind, callback in actions:
            button = VWButton(text=label, kind=kind)
            if not vertical:
                button.width = dp(140)
            else:
                button.size_hint_x = 1
            button.bind(on_release=lambda *_, fn=callback: self._finish(fn))
            if not vertical:
                self.actions.add_widget(Widget())
            self.actions.add_widget(button)
        rows = dp(150) + self.body.height + self.field_wrap.height + self.actions.height
        self.card.height = min(dp(540), max(dp(210), rows))
        self.opened = True
        self.opacity = 0
        Animation.cancel_all(self)
        Animation(opacity=1, d=0.12).start(self)
        if prompt:
            self.field.focus = True

    def hide(self):
        self.opened = False
        self.field.focus = False
        Animation.cancel_all(self)
        self.opacity = 0

    def _accept(self):
        if self._prompt:
            self._finish(self._callback)

    def _finish(self, callback):
        text = self.field.text.strip()
        prompted = self._prompt
        self.hide()
        if callback is None:
            return
        if prompted:
            callback(text)
        else:
            callback()

    def on_touch_down(self, touch):
        if not self.opened:
            return False
        if self.card.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self.hide()
        return True


class Toast(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            size_hint=(None, None),
            height=dp(42),
            padding=(dp(16), 0),
            pos_hint={"center_x": 0.5, "y": 0.14},
            **kwargs,
        )
        self.label = VWLabel(text="", role="small", halign="center", valign="middle", shorten=False)
        self.add_widget(self.label)
        self.opacity = 0
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.accent)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(21)))
        self.label.ink = colors.on_accent

    def show(self, text: str):
        self.label.text = text
        self.width = min(dp(720), max(dp(160), len(text) * dp(7.4) + dp(40)))
        Animation.cancel_all(self)
        self.opacity = 1
        anim = Animation(opacity=1, d=2.3) + Animation(opacity=0, d=0.35)
        anim.start(self)

    def on_touch_down(self, _touch):
        return False

    def on_touch_move(self, _touch):
        return False

    def on_touch_up(self, _touch):
        return False
