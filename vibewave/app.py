"""Application object. Window config is applied before Kivy opens a window."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.config import Config

Config.set("input", "mouse", "mouse,multitouch_on_demand")
Config.set("graphics", "width", "1280")
Config.set("graphics", "height", "800")
Config.set("graphics", "minimum_width", "1024")
Config.set("graphics", "minimum_height", "680")
Config.set("graphics", "resizable", "1")
Config.set("kivy", "exit_on_escape", "0")
Config.set("kivy", "pause_on_minimize", "0")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import BooleanProperty, ObjectProperty

from vibewave.audio.engine import AudioEngine
from vibewave.controller import PlayerController
from vibewave.converter import ConversionManager
from vibewave.db import Database
from vibewave.paths import data_dir, db_path
from vibewave.scanner import LibraryScanner
from vibewave.theme import Theme
from vibewave.ui.shell import Shell
from vibewave.ui.widgets import register_font

log = logging.getLogger(__name__)


def _window_icon() -> str:
    icon = data_dir() / "window_icon.png"
    if icon.exists():
        return str(icon)
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(110, 86, 255, 255))
    draw.polygon([(26, 16), (26, 48), (50, 32)], fill=(255, 255, 255, 255))
    image.save(icon)
    return str(icon)


Config.set("kivy", "window_icon", _window_icon())


class VibeWaveApp(App):
    title = "VibeWave"
    text_focused = BooleanProperty(False)
    reduced_motion = BooleanProperty(False)
    player = ObjectProperty(None, allownone=True)
    engine = ObjectProperty(None, allownone=True)
    theme = ObjectProperty(None, allownone=True)

    def build(self):
        register_font()
        self.theme = Theme()
        self.db = Database(db_path())
        removed = self.db.purge_opus()
        if removed:
            log.info("Removed %s excluded opus row(s)", removed)
        mode = self.db.get_setting("theme_mode", "dark") or "dark"
        accent = self.db.get_setting("theme_accent", "violet") or "violet"
        self.theme.apply(mode, accent)
        Window.clearcolor = self.theme.bg
        if os.environ.get("VIBEWAVE_DEMO") == "1":
            from vibewave.demo import seed

            seed(self.db)
        self.engine = AudioEngine()
        self.player = PlayerController(self.db, self.engine)
        self.scanner = LibraryScanner(self.db)
        self.converter = ConversionManager()
        return Shell()

    def on_start(self):
        started = self.engine.start()
        self.player.boot()
        if not started and self.engine.error:
            self.player.toast(self.engine.error)
        Clock.schedule_interval(self.player.poll, 0.25)
        Clock.schedule_interval(self.root.poll_scan, 0.45)
        Clock.schedule_interval(self.root.poll_convert, 0.4)
        Window.bind(on_key_down=self.root.on_key)
        Window.bind(on_minimize=self._minimized)
        Window.bind(on_restore=self._restored)
        Window.bind(on_resize=lambda *_args: self.root.on_resize())
        self.root.on_resize()
        scan_on_start = (self.db.get_setting("scan_on_startup", "1") or "1") != "0"
        if scan_on_start and os.environ.get("VIBEWAVE_DEMO") != "1":
            self.scanner.start()
        if os.environ.get("VIBEWAVE_SMOKE") == "1":
            from vibewave.ui.smoke import run_smoke

            run_smoke(self)

    def _minimized(self, *_args):
        self.reduced_motion = True

    def _restored(self, *_args):
        self.reduced_motion = False

    def on_stop(self):
        try:
            self.converter.cancel()
        except Exception:
            log.exception("converter cancel")
        try:
            self.player.shutdown()
        except Exception:
            log.exception("player shutdown")
        try:
            self.db.close()
        except Exception:
            log.exception("database close")


def main() -> None:
    VibeWaveApp().run()
