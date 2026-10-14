"""Shared controls. Nothing here uses Kivy's default button or slider skin."""

from __future__ import annotations

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle, StencilPop, StencilPush, StencilUnUse, StencilUse
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from vibewave.palette import palette_from_text
from vibewave.ui.icons import draw_icon

_FONT = "Roboto"


def register_font() -> str:
    global _FONT
    regular = r"C:\Windows\Fonts\segoeui.ttf"
    bold = r"C:\Windows\Fonts\segoeuib.ttf"
    if os.path.exists(regular):
        LabelBase.register(
            name="UI",
            fn_regular=regular,
            fn_bold=bold if os.path.exists(bold) else regular,
        )
        _FONT = "UI"
    return _FONT


def font_name() -> str:
    return _FONT


def radii(radius: float):
    return [(radius, radius), (radius, radius), (radius, radius), (radius, radius)]


def theme():
    app = App.get_running_app()
    return app.theme if app else None


def watch_theme(widget, redraw) -> None:
    def connect(_dt):
        app = App.get_running_app()
        if app and app.theme:
            app.theme.fbind("revision", redraw)
            redraw()

    # Clock keeps only a weak reference. The widget has to own the callback.
    widget._theme_connect = connect
    Clock.schedule_once(connect, 0)


def pointer_inside(widget, win_pos) -> bool:
    if widget.get_root_window() is None or widget.width < 2 or widget.height < 2:
        return False
    x, y = widget.to_window(widget.x, widget.y)
    x2, y2 = widget.to_window(widget.right, widget.top)
    wx, wy = win_pos
    return min(x, x2) <= wx <= max(x, x2) and min(y, y2) <= wy <= max(y, y2)


def mix(a, b, amount: float):
    return tuple(a[i] + (b[i] - a[i]) * amount for i in range(4))


class VWLabel(Label):
    role = StringProperty("body")
    muted = BooleanProperty(False)
    faint = BooleanProperty(False)
    wrap = BooleanProperty(False)
    # Alpha above 0 locks the color so immersive screens stay light-on-dark.
    ink = ListProperty([0, 0, 0, 0])

    _sizes = {"display": 30, "title": 22, "section": 16, "body": 14, "small": 12, "micro": 10}

    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", _FONT)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("shorten", True)
        kwargs.setdefault("shorten_from", "right")
        super().__init__(**kwargs)
        self.bind(
            size=self._sync_text,
            pos=self._sync_text,
            role=self._apply_role,
            muted=self._apply_color,
            faint=self._apply_color,
            wrap=self._sync_text,
            ink=self._apply_color,
        )
        self._apply_role()
        watch_theme(self, self._apply_color)

    def _sync_text(self, *_args):
        if self.wrap:
            self.text_size = (self.width, None)
            self.shorten = False
        else:
            self.text_size = self.size

    def _apply_role(self, *_args):
        self.font_size = dp(self._sizes.get(self.role, 14))
        self.bold = self.role in {"display", "title", "section"}

    def _apply_color(self, *_args):
        if len(self.ink) >= 4 and self.ink[3] > 0:
            self.color = self.ink
            return
        colors = theme()
        if not colors:
            return
        if self.faint:
            self.color = colors.faint
        elif self.muted:
            self.color = colors.muted
        else:
            self.color = colors.text


class Icon(Widget):
    name = StringProperty("dot")
    icon_color = ListProperty([1, 1, 1, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.redraw, size=self.redraw, name=self.redraw, icon_color=self.redraw)

    def redraw(self, *_args):
        self.canvas.clear()
        if self.width < 2 or self.height < 2:
            return
        with self.canvas:
            Color(*self.icon_color)
            draw_icon(self.name, self._px, max(1.05, self.width / 16))

    def _px(self, gx, gy):
        return (self.x + gx / 24 * self.width, self.y + gy / 24 * self.height)


class Panel(BoxLayout):
    radius = NumericProperty(18)
    fill = StringProperty("surface")
    padded = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.redraw, size=self.redraw, radius=self.redraw, fill=self.redraw)
        watch_theme(self, self.redraw)

    def redraw(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        fill = getattr(colors, self.fill, colors.surface)
        with self.canvas.before:
            Color(*colors.stroke)
            RoundedRectangle(pos=(self.x - 1, self.y - 1), size=(self.width + 2, self.height + 2), radius=radii(self.radius + 1))
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(self.radius))


class VWButton(ButtonBehavior, BoxLayout):
    text = StringProperty("")
    icon = StringProperty("")
    kind = StringProperty("ghost")
    hover = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(8), padding=(dp(14), 0), size_hint=(None, None), height=dp(40), **kwargs)
        self._icon = Icon(size_hint=(None, None), size=(dp(16), dp(16)))
        self._label = VWLabel(halign="center", valign="middle")
        self.add_widget(self._icon)
        self.add_widget(self._label)
        self.bind(text=self._sync, icon=self._sync, pos=self.redraw, size=self.redraw, kind=self.redraw, hover=self.redraw, state=self.redraw)
        self._sync()
        Window.bind(mouse_pos=self._mouse)
        watch_theme(self, self.redraw)

    def _sync(self, *_args):
        self._label.text = self.text
        self._icon.name = self.icon or "dot"
        self._icon.opacity = 1 if self.icon else 0
        self._icon.size = (dp(16), dp(16)) if self.icon else (0, 0)
        self._icon.width = dp(16) if self.icon else 0
        if self.width <= 10:
            self.width = dp(148)

    def _mouse(self, _win, pos):
        inside = pointer_inside(self, pos)
        if inside != self.hover:
            self.hover = inside
            if inside:
                try:
                    Window.set_system_cursor("hand")
                except Exception:
                    pass
            else:
                try:
                    Window.set_system_cursor("arrow")
                except Exception:
                    pass

    def redraw(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        if self.kind == "primary":
            fill = colors.accent
            ink = colors.on_accent
        elif self.kind == "danger":
            fill = colors.danger
            ink = (1, 1, 1, 1)
        elif self.kind == "solid":
            fill = colors.surface_2
            ink = colors.text
        else:
            fill = colors.hover if self.hover else (0, 0, 0, 0)
            ink = colors.text
        if self.hover and self.kind in {"primary", "danger", "solid"}:
            fill = mix(fill, (1, 1, 1, 1), 0.12)
        if self.state == "down":
            fill = mix(fill, (0, 0, 0, 1), 0.12)
        with self.canvas.before:
            if fill[3] > 0:
                Color(*fill)
                RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(12)))
        self._label.color = ink
        self._icon.icon_color = ink
        self._label.halign = "center"


class IconButton(ButtonBehavior, Widget):
    icon = StringProperty("play")
    kind = StringProperty("quiet")
    hover = BooleanProperty(False)
    icon_color = ListProperty([1, 1, 1, 1])
    immersive = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(42), dp(42)), **kwargs)
        self.bind(
            pos=self.redraw,
            size=self.redraw,
            icon=self.redraw,
            kind=self.redraw,
            hover=self.redraw,
            state=self.redraw,
            icon_color=self.redraw,
            immersive=self.redraw,
        )
        Window.bind(mouse_pos=self._mouse)
        watch_theme(self, self.redraw)

    def _mouse(self, _win, pos):
        inside = pointer_inside(self, pos)
        if inside != self.hover:
            self.hover = inside

    def redraw(self, *_args):
        self.canvas.before.clear()
        self.canvas.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        if self.immersive:
            text = (0.96, 0.96, 0.98, 1)
            surface = (1, 1, 1, 0.10)
            quiet = (1, 1, 1, 0.16) if self.hover or self.state == "down" else (1, 1, 1, 0.06)
            on_accent = (1, 1, 1, 1)
        else:
            text = colors.text
            surface = colors.surface_2
            quiet = surface if self.hover or self.state == "down" else (1, 1, 1, 0.04 if colors.mode == "dark" else 0.0)
            on_accent = colors.on_accent
        custom = list(self.icon_color) != [1, 1, 1, 1]
        if self.kind == "primary":
            fill = colors.accent
            ink = on_accent
        elif self.kind == "toggle":
            active = self.state == "down" or getattr(self, "active", False)
            fill = colors.accent if active else surface
            ink = on_accent if active else text
        else:
            fill = quiet
            ink = tuple(self.icon_color) if custom else text
        if self.hover and self.kind == "primary":
            fill = mix(fill, (1, 1, 1, 1), 0.1)
        with self.canvas.before:
            Color(*fill)
            Ellipse(pos=self.pos, size=self.size)
        pad = self.width * 0.28
        box = (self.x + pad, self.y + pad, self.width - pad * 2, self.height - pad * 2)

        def px(gx, gy, box=box):
            return box[0] + gx / 24 * box[2], box[1] + gy / 24 * box[3]

        with self.canvas:
            Color(*ink)
            draw_icon(self.icon, px, max(1.15, box[2] / 14))


class Chip(ButtonBehavior, BoxLayout):
    text = StringProperty("")
    selected = BooleanProperty(False)
    hover = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), height=dp(32), padding=(dp(12), 0), **kwargs)
        self.label = VWLabel(role="small", halign="center", valign="middle", shorten=False)
        self.add_widget(self.label)
        self.bind(text=self._sync, selected=self.redraw, hover=self.redraw, pos=self.redraw, size=self.redraw, state=self.redraw)
        self.label.bind(texture_size=self._fit)
        Window.bind(mouse_pos=self._mouse)
        self._sync()
        watch_theme(self, self.redraw)

    def _sync(self, *_args):
        self.label.text = self.text

    def _fit(self, *_args):
        self.width = max(dp(64), self.label.texture_size[0] + dp(24))

    def _mouse(self, _win, pos):
        inside = pointer_inside(self, pos)
        if inside != self.hover:
            self.hover = inside

    def redraw(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        if self.selected:
            fill = colors.accent
            ink = colors.on_accent
        else:
            fill = colors.surface_2 if self.hover else colors.surface
            ink = colors.text
        with self.canvas.before:
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(16)))
        self.label.color = ink


class VWSwitch(ButtonBehavior, Widget):
    active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(46), dp(26)), **kwargs)
        self.bind(pos=self.redraw, size=self.redraw, active=self.redraw)
        watch_theme(self, self.redraw)

    def on_press(self):
        self.active = not self.active

    def redraw(self, *_args):
        self.canvas.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas:
            Color(*(colors.accent if self.active else colors.surface_2))
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(self.height / 2))
            knob = self.height - dp(6)
            x = self.right - knob - dp(3) if self.active else self.x + dp(3)
            Color(*(colors.on_accent if self.active else colors.text))
            Ellipse(pos=(x, self.y + dp(3)), size=(knob, knob))


class PrettySlider(Widget):
    value = NumericProperty(0)
    min_value = NumericProperty(0)
    max_value = NumericProperty(1)
    step = NumericProperty(0)
    orientation = StringProperty("horizontal")
    bipolar = BooleanProperty(False)
    dragging = BooleanProperty(False)
    # Names must not start with on_. Kivy calls on_<property> when that property changes.
    drag_started = ObjectProperty(None, rebind=True, allownone=True)
    released = ObjectProperty(None, rebind=True, allownone=True)
    changed = ObjectProperty(None, rebind=True, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.redraw, size=self.redraw, value=self.redraw, min_value=self.redraw, max_value=self.redraw)
        watch_theme(self, self.redraw)

    def _ratio(self) -> float:
        span = self.max_value - self.min_value
        if span == 0:
            return 0
        return min(1, max(0, (self.value - self.min_value) / span))

    def _value_from_touch(self, touch) -> float:
        if self.orientation == "vertical":
            ratio = (touch.y - self.y) / max(1, self.height)
        else:
            ratio = (touch.x - self.x) / max(1, self.width)
        ratio = min(1, max(0, ratio))
        value = self.min_value + ratio * (self.max_value - self.min_value)
        if self.step:
            value = round(value / self.step) * self.step
        return float(min(self.max_value, max(self.min_value, value)))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or touch.button != "left":
            return False
        touch.grab(self)
        self.dragging = True
        self.value = self._value_from_touch(touch)
        if self.drag_started:
            self.drag_started()
        if self.changed:
            self.changed(self.value)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self.value = self._value_from_touch(touch)
        if self.changed:
            self.changed(self.value)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self.value = self._value_from_touch(touch)
        self.dragging = False
        if self.released:
            self.released(self.value)
        return True

    def redraw(self, *_args):
        self.canvas.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        ratio = self._ratio()
        with self.canvas:
            Color(*colors.surface_2)
            if self.orientation == "vertical":
                track_x = self.center_x - dp(2)
                RoundedRectangle(pos=(track_x, self.y), size=(dp(4), self.height), radius=radii(dp(2)))
                Color(*colors.accent)
                if self.bipolar:
                    center = self.y + self.height * 0.5
                    handle = self.y + ratio * self.height
                    bottom = min(center, handle)
                    RoundedRectangle(pos=(track_x, bottom), size=(dp(4), abs(handle - center) or 1), radius=radii(dp(2)))
                else:
                    RoundedRectangle(pos=(track_x, self.y), size=(dp(4), max(1, self.height * ratio)), radius=radii(dp(2)))
                Color(*colors.text)
                handle_y = self.y + ratio * self.height - dp(7)
                Ellipse(pos=(self.center_x - dp(7), handle_y), size=(dp(14), dp(14)))
            else:
                track_y = self.center_y - dp(2)
                RoundedRectangle(pos=(self.x, track_y), size=(self.width, dp(4)), radius=radii(dp(2)))
                Color(*colors.accent)
                RoundedRectangle(pos=(self.x, track_y), size=(max(1, self.width * ratio), dp(4)), radius=radii(dp(2)))
                Color(*colors.text)
                Ellipse(pos=(self.x + ratio * self.width - dp(7), self.center_y - dp(7)), size=(dp(14), dp(14)))


class VWTextInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(
            font_name=_FONT,
            font_size=dp(14),
            multiline=False,
            background_normal="",
            background_active="",
            background_color=(0, 0, 0, 0),
            foreground_color=(1, 1, 1, 1),
            cursor_color=(0.7, 0.6, 1, 1),
            padding=(dp(12), dp(10)),
            **kwargs,
        )
        self.bind(focus=self._focus)
        watch_theme(self, self._colors)

    def _focus(self, *_args):
        app = App.get_running_app()
        if app:
            app.text_focused = bool(self.focus)

    def _colors(self, *_args):
        colors = theme()
        if not colors:
            return
        self.foreground_color = colors.text
        self.cursor_color = colors.accent
        self.selection_color = (*colors.accent[:3], 0.35)
        self.hint_text_color = colors.faint


class SearchField(Panel):
    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint=(None, None), size=(dp(460), dp(42)), radius=dp(21), padding=(dp(14), 0), spacing=dp(8), fill="surface", **kwargs)
        self.icon = Icon(name="search", size_hint=(None, None), size=(dp(16), dp(16)))
        self.input = VWTextInput(hint_text="Search songs, artists, albums")
        self.add_widget(self.icon)
        self.add_widget(self.input)
        watch_theme(self, self._tint)

    def _tint(self, *_args):
        colors = theme()
        if colors:
            self.icon.icon_color = colors.muted


_TEXTURES: dict[str, object] = {}


def _texture(path: str):
    cached = _TEXTURES.get(path)
    if cached is not None:
        return cached
    if not path or not os.path.isfile(path):
        return None
    try:
        texture = CoreImage(path).texture
    except Exception:
        return None
    _TEXTURES[path] = texture
    if len(_TEXTURES) > 180:
        _TEXTURES.pop(next(iter(_TEXTURES)))
    return texture


class CoverImage(Widget):
    source = StringProperty("")
    title = StringProperty("")
    radius = NumericProperty(12)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.letter = Label(font_name=_FONT, bold=True, font_size=dp(28), color=(1, 1, 1, 0.94), halign="center", valign="middle")
        self.add_widget(self.letter)
        self.bind(pos=self.redraw, size=self.redraw, source=self.redraw, title=self.redraw, radius=self.redraw)
        self.letter.bind(size=lambda *_: setattr(self.letter, "text_size", self.letter.size))

    def redraw(self, *_args):
        self.canvas.before.clear()
        self.letter.size = self.size
        self.letter.pos = self.pos
        self.letter.text = (self.title or "?").strip()[:1].upper()
        texture = _texture(self.source)
        self.letter.opacity = 0 if texture else 1
        glow, _deep, _deep2 = palette_from_text(self.title or self.source or "track")
        with self.canvas.before:
            StencilPush()
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(self.radius))
            StencilUse()
            if texture:
                tw, th = texture.size
                scale = max(self.width / max(tw, 1), self.height / max(th, 1))
                dw, dh = tw * scale, th * scale
                Color(1, 1, 1, 1)
                Rectangle(texture=texture, pos=(self.center_x - dw / 2, self.center_y - dh / 2), size=(dw, dh))
            else:
                Color(*glow)
                Rectangle(pos=self.pos, size=self.size)
            StencilUnUse()
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(self.radius))
            StencilPop()


class EmptyState(BoxLayout):
    def __init__(self, title: str, subtitle: str, button: str = "", on_press=None, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(8), dp(16)), spacing=dp(8), size_hint_y=None, **kwargs)
        title_label = VWLabel(text=title, role="section", halign="center", shorten=False, size_hint_y=None, height=dp(30))
        self.add_widget(title_label)
        body = VWLabel(text=subtitle, role="small", muted=True, halign="center", wrap=True, size_hint_y=None, height=dp(40))
        body.bind(texture_size=lambda widget, size: setattr(widget, "height", max(dp(20), size[1] + dp(4))))
        self.add_widget(body)
        if button and on_press:
            action = VWButton(text=button, kind="primary")
            action.width = dp(180)
            action.bind(on_press=lambda *_: on_press())
            wrap = BoxLayout(size_hint_y=None, height=dp(44))
            wrap.add_widget(Widget())
            wrap.add_widget(action)
            wrap.add_widget(Widget())
            self.add_widget(wrap)
        self.bind(minimum_height=self.setter("height"))


class SpectrumBars(Widget):
    count = NumericProperty(32)
    running = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._levels = [0.0] * int(self.count)
        self._clock = Clock.schedule_interval(self._tick, 1 / 30)
        self.bind(count=self._reset, pos=self._draw, size=self._draw)

    def _reset(self, *_args):
        self._levels = [0.0] * int(self.count)

    def _visible(self) -> bool:
        from kivy.uix.screenmanager import Screen

        if not self.running or self.get_root_window() is None or self.width < 4:
            return False
        app = App.get_running_app()
        if app and app.reduced_motion:
            return False
        node = self.parent
        # Window.parent is the window itself. Stop there or the walk never ends.
        while node is not None and node.parent is not node:
            if isinstance(node, Screen):
                return bool(node.manager and node.manager.current == node.name)
            node = node.parent
        return self.opacity > 0 and not self.disabled

    def _tick(self, _dt):
        if not self._visible():
            return
        app = App.get_running_app()
        target = []
        if app and app.player and app.engine:
            full = app.engine.spectrum_copy()
            if len(full) and int(self.count) > 0:
                group = max(1, int(len(full) / int(self.count)))
                for index in range(int(self.count)):
                    chunk = full[index * group : (index + 1) * group]
                    target.append(float(chunk.mean()) if len(chunk) else 0.0)
        if len(target) != len(self._levels):
            self._levels = target or [0.0] * int(self.count)
        else:
            self._levels = [max(new, old * 0.72) for old, new in zip(self._levels, target or self._levels)]
        self._draw()

    def _draw(self, *_args):
        self.canvas.clear()
        colors = theme()
        if not colors or self.width < 4 or not self._levels:
            return
        gap = dp(3)
        width = max(dp(2), (self.width - gap * (len(self._levels) - 1)) / len(self._levels))
        with self.canvas:
            for index, level in enumerate(self._levels):
                height = max(dp(2), self.height * min(1, level))
                Color(*(colors.accent if index % 4 else colors.accent_2))
                Rectangle(pos=(self.x + index * (width + gap), self.y), size=(width, height))


class WaveformSeek(Widget):
    value = NumericProperty(0)
    maximum = NumericProperty(1)
    peaks = ListProperty([])
    dragging = BooleanProperty(False)
    immersive = BooleanProperty(False)
    released = ObjectProperty(None, rebind=True, allownone=True)
    drag_started = ObjectProperty(None, rebind=True, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(
            pos=self.redraw,
            size=self.redraw,
            value=self.redraw,
            maximum=self.redraw,
            peaks=self.redraw,
            immersive=self.redraw,
        )
        watch_theme(self, self.redraw)

    def _ratio_at(self, touch) -> float:
        return min(1, max(0, (touch.x - self.x) / max(1, self.width)))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or touch.button != "left":
            return False
        touch.grab(self)
        self.dragging = True
        if self.drag_started:
            self.drag_started()
        self.value = self._ratio_at(touch) * max(self.maximum, 0)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self.value = self._ratio_at(touch) * max(self.maximum, 0)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self.value = self._ratio_at(touch) * max(self.maximum, 0)
        self.dragging = False
        if self.released:
            self.released(self.value)
        return True

    def redraw(self, *_args):
        self.canvas.clear()
        colors = theme()
        if not colors or self.width < 4:
            return
        progress = 0 if self.maximum <= 0 else min(1, self.value / self.maximum)
        played_x = self.x + self.width * progress
        if self.immersive:
            idle = (1, 1, 1, 0.16)
            unmet = (1, 1, 1, 0.30)
            handle = (1, 1, 1, 0.95)
        else:
            idle = colors.surface_2
            unmet = colors.faint
            handle = colors.text
        with self.canvas:
            if not self.peaks:
                Color(*idle)
                Rectangle(pos=(self.x, self.center_y - dp(1.5)), size=(self.width, dp(3)))
                Color(*colors.accent)
                Rectangle(pos=(self.x, self.center_y - dp(1.5)), size=(self.width * progress, dp(3)))
            else:
                gap = 1.5
                count = len(self.peaks)
                bar_w = max(1.0, (self.width - gap * count) / max(1, count))
                for index, peak in enumerate(self.peaks):
                    bx = self.x + index * (bar_w + gap)
                    height = max(dp(2), (0.18 + 0.82 * float(peak)) * self.height)
                    Color(*(colors.accent if bx <= played_x else unmet))
                    Rectangle(pos=(bx, self.center_y - height / 2), size=(bar_w, height))
            Color(*handle)
            Ellipse(pos=(played_x - dp(6), self.center_y - dp(6)), size=(dp(12), dp(12)))


class TrackRow(RecycleDataViewBehavior, BoxLayout):
    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)
    track_id = NumericProperty(0)
    item_id = NumericProperty(0)
    num_text = StringProperty("")
    title_text = StringProperty("")
    artist_text = StringProperty("")
    album_text = StringProperty("")
    duration_text = StringProperty("")
    plays_text = StringProperty("")
    favorite = BooleanProperty(False)
    show_album = BooleanProperty(True)
    hover = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(54), padding=(dp(8), 0), spacing=dp(8), **kwargs)
        self.num_l = VWLabel(role="small", muted=True, size_hint_x=None, width=dp(36), halign="right")
        self.title_l = VWLabel(role="body")
        self.artist_l = VWLabel(role="small", muted=True, size_hint_x=0.24)
        self.album_l = VWLabel(role="small", muted=True, size_hint_x=0.22)
        self.duration_l = VWLabel(role="small", muted=True, size_hint_x=None, width=dp(62), halign="right")
        self.plays_l = VWLabel(role="small", faint=True, size_hint_x=None, width=dp(36), halign="right")
        self.fav_wrap = BoxLayout(size_hint_x=None, width=dp(36), padding=(dp(8), dp(16)))
        self.fav = Icon(name="heart")
        self.fav_wrap.add_widget(self.fav)
        for widget in (self.num_l, self.title_l, self.artist_l, self.album_l, self.duration_l, self.plays_l, self.fav_wrap):
            self.add_widget(widget)
        self.bind(
            pos=self._paint,
            size=self._paint,
            selected=self._paint,
            hover=self._paint,
            favorite=self._fav,
            show_album=self._album,
        )
        Window.bind(mouse_pos=self._mouse)
        watch_theme(self, self._paint)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        result = super().refresh_view_attrs(rv, index, data)
        self.num_l.text = self.num_text
        self.title_l.text = self.title_text
        self.artist_l.text = self.artist_text
        self.album_l.text = self.album_text
        self.duration_l.text = self.duration_text
        self.plays_l.text = self.plays_text
        self._album()
        self._fav()
        return result

    def _album(self, *_args):
        self.album_l.opacity = 1 if self.show_album else 0
        self.album_l.size_hint_x = 0.22 if self.show_album else 0
        self.album_l.width = 0 if not self.show_album else self.album_l.width

    def _fav(self, *_args):
        colors = theme()
        self.fav.name = "heart_fill" if self.favorite else "heart"
        if colors:
            self.fav.icon_color = colors.accent if self.favorite else colors.faint

    def _mouse(self, _win, pos):
        inside = pointer_inside(self, pos)
        if inside != self.hover:
            self.hover = inside

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        if not (self.selected or self.hover):
            return
        fill = (*colors.accent[:3], 0.18) if self.selected else colors.hover
        with self.canvas.before:
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(10)))
        self._fav()

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected

    def _browser(self):
        node = self.parent
        while node is not None and node.parent is not node and not isinstance(node, TrackList):
            node = node.parent
        return node if isinstance(node, TrackList) else None

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.fav_wrap.collide_point(*touch.pos):
            app = App.get_running_app()
            if app and app.player and self.track_id:
                app.player.set_favorite_id(int(self.track_id), not self.favorite)
                self.favorite = not self.favorite
            return True
        if touch.button == "right":
            browser = self._browser()
            App.get_running_app().root.open_track_menu(int(self.track_id), browser.ids if browser else [], int(self.item_id))
            return True
        if touch.is_double_tap:
            browser = self._browser()
            ids = browser.ids if browser else [int(self.track_id)]
            App.get_running_app().player.play_ids(ids, int(self.track_id), user_skip=True)
            return True
        if self.parent:
            return self.parent.select_with_touch(self.index, touch)
        return True


class TrackList(BoxLayout):
    show_album = BooleanProperty(True)

    def __init__(self, **kwargs):
        show_album = kwargs.pop("show_album", True)
        super().__init__(orientation="vertical", spacing=dp(4), **kwargs)
        self.show_album = show_album
        self.ids_list: list[int] = []
        self.empty = VWLabel(text="No songs to show", role="small", muted=True, halign="center", size_hint_y=None, height=dp(48))
        self.rv = RecycleView(bar_width=dp(6), scroll_type=["bars", "content"])
        layout = RecycleBoxLayout(
            default_size=(None, dp(54)),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            spacing=dp(2),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.rv.add_widget(layout)
        # viewclass is stored on the layout. Setting it before the layout exists drops it.
        self.rv.viewclass = "TrackRow"
        self.add_widget(self.rv)
        self.add_widget(self.empty)
        self.empty.opacity = 0

    @property
    def ids(self) -> list[int]:
        return self.ids_list

    def set_rows(self, tracks: list[dict], *, numbers: str = "index") -> None:
        self.ids_list = [int(track["id"]) for track in tracks]
        data = []
        for index, track in enumerate(tracks, start=1):
            number = track.get("track_number") if numbers == "track" and track.get("track_number") else index
            data.append({
                "track_id": int(track["id"]),
                "item_id": int(track.get("item_id") or 0),
                "num_text": str(number),
                "title_text": track.get("title") or "Untitled",
                "artist_text": track.get("artist") or "Unknown Artist",
                "album_text": track.get("album") or "",
                "duration_text": _duration(track.get("duration") or 0),
                "plays_text": str(int(track.get("play_count") or 0)),
                "favorite": bool(track.get("favorite")),
                "show_album": self.show_album,
            })
        self.rv.data = data
        has_rows = bool(data)
        self.empty.opacity = 0 if has_rows else 1
        self.empty.height = 0 if has_rows else dp(48)
        self.rv.opacity = 1 if has_rows else 0
        self.rv.size_hint_y = 1 if has_rows else None
        if not has_rows:
            self.rv.height = 0

    def patch_stats(self, stats: dict) -> None:
        changed = False
        for item in self.rv.data:
            row = stats.get(int(item["track_id"]))
            if not row:
                continue
            favorite = bool(row.get("favorite"))
            plays = str(int(row.get("play_count") or 0))
            if item.get("favorite") != favorite or item.get("plays_text") != plays:
                item["favorite"] = favorite
                item["plays_text"] = plays
                changed = True
        if changed:
            self.rv.refresh_from_data()


def _duration(seconds: float) -> str:
    from vibewave.formatutil import format_duration

    return format_duration(seconds)


Factory.register("TrackRow", cls=TrackRow)
