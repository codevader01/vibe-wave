"""Color themes. Widgets redraw when `revision` changes."""

from __future__ import annotations

from kivy.event import EventDispatcher
from kivy.properties import ColorProperty, NumericProperty, StringProperty

ACCENTS = {
    "violet": ((0.545, 0.424, 1.0, 1), (0.18, 0.78, 0.96, 1)),
    "cyan": ((0.13, 0.83, 0.93, 1), (0.45, 0.55, 1.0, 1)),
    "magenta": ((0.96, 0.45, 0.71, 1), (0.62, 0.45, 1.0, 1)),
    "emerald": ((0.20, 0.83, 0.60, 1), (0.35, 0.78, 0.95, 1)),
    "amber": ((0.98, 0.75, 0.25, 1), (1.0, 0.55, 0.35, 1)),
}

_DARK = {
    "bg": (0.055, 0.055, 0.075, 1),
    "elev": (0.078, 0.078, 0.105, 1),
    "surface": (0.12, 0.12, 0.16, 1),
    "surface_2": (0.16, 0.16, 0.21, 1),
    "stroke": (1, 1, 1, 0.08),
    "text": (0.96, 0.96, 0.98, 1),
    "muted": (0.62, 0.63, 0.72, 1),
    "faint": (0.45, 0.46, 0.55, 1),
    "hover": (1, 1, 1, 0.06),
    "overlay": (0.02, 0.02, 0.04, 0.62),
}

_LIGHT = {
    "bg": (0.945, 0.945, 0.96, 1),
    "elev": (0.975, 0.975, 0.985, 1),
    "surface": (1, 1, 1, 1),
    "surface_2": (0.92, 0.925, 0.95, 1),
    "stroke": (0, 0, 0, 0.08),
    "text": (0.09, 0.09, 0.13, 1),
    "muted": (0.33, 0.34, 0.42, 1),
    "faint": (0.48, 0.49, 0.56, 1),
    "hover": (0, 0, 0, 0.05),
    "overlay": (0.08, 0.08, 0.12, 0.35),
}


class Theme(EventDispatcher):
    revision = NumericProperty(0)
    mode = StringProperty("dark")
    accent_name = StringProperty("violet")
    bg = ColorProperty((0.055, 0.055, 0.075, 1))
    elev = ColorProperty((0.078, 0.078, 0.105, 1))
    surface = ColorProperty((0.12, 0.12, 0.16, 1))
    surface_2 = ColorProperty((0.16, 0.16, 0.21, 1))
    stroke = ColorProperty((1, 1, 1, 0.08))
    text = ColorProperty((0.96, 0.96, 0.98, 1))
    muted = ColorProperty((0.62, 0.63, 0.72, 1))
    faint = ColorProperty((0.45, 0.46, 0.55, 1))
    hover = ColorProperty((1, 1, 1, 0.06))
    overlay = ColorProperty((0.02, 0.02, 0.04, 0.62))
    accent = ColorProperty((0.545, 0.424, 1, 1))
    accent_2 = ColorProperty((0.18, 0.78, 0.96, 1))
    on_accent = ColorProperty((1, 1, 1, 1))
    danger = ColorProperty((0.95, 0.35, 0.42, 1))
    ok = ColorProperty((0.25, 0.82, 0.58, 1))

    def apply(self, mode: str, accent: str) -> None:
        palette = _LIGHT if mode == "light" else _DARK
        accent_name = accent if accent in ACCENTS else "violet"
        primary, secondary = ACCENTS[accent_name]
        self.mode = "light" if mode == "light" else "dark"
        self.accent_name = accent_name
        for key, value in palette.items():
            setattr(self, key, value)
        self.accent = primary
        self.accent_2 = secondary
        self.on_accent = (0.08, 0.08, 0.1, 1) if accent_name == "amber" and self.mode == "light" else (1, 1, 1, 1)
        self.revision += 1
