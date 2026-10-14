"""Sidebar, header, and the overlays that sit above every screen."""

from __future__ import annotations

import os
import subprocess

from kivy.animation import Animation
from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import NoTransition, ScreenManager
from kivy.uix.widget import Widget

from vibewave.ui.files import pick_directory
from vibewave.ui.library import LIBRARY_SCREENS
from vibewave.ui.now_playing import NowPlaying
from vibewave.ui.overlays import ContextMenu, Modal, QueuePanel, Toast
from vibewave.ui.player_bar import PlayerBar
from vibewave.ui.sound import SOUND_SCREENS
from vibewave.ui.widgets import DesktopScroll, Icon, IconButton, SearchField, VWButton, VWLabel, pointer_inside, radii, theme, watch_theme
from kivy.clock import Clock
from kivy.graphics import RoundedRectangle

_NAV = (
    ("LIBRARY", (
        ("home", "Home", "home"),
        ("songs", "All Songs", "music"),
        ("albums", "Albums", "album"),
        ("artists", "Artists", "person"),
        ("favorites", "Favorites", "heart"),
        ("most_played", "Most Played", "chart"),
        ("recent", "Recently Played", "clock"),
        ("playlists", "Playlists", "list"),
    )),
    ("DISCOVER", (
        ("visualizer", "Audio Visualizer", "wave"),
        ("equalizer", "Equalizer", "sliders"),
        ("recommendations", "Recommendations", "spark"),
    )),
    ("TOOLS", (
        ("converter", "MP4 to MP3", "convert"),
        ("settings", "Settings", "settings"),
    )),
)

_TITLES = {
    "home": "Home",
    "songs": "All Songs",
    "albums": "Albums",
    "artists": "Artists",
    "favorites": "Favorites",
    "most_played": "Most Played",
    "recent": "Recently Played",
    "playlists": "Playlists",
    "playlist": "Playlist",
    "artist": "Artist",
    "album": "Album",
    "search": "Search",
    "visualizer": "Audio Visualizer",
    "equalizer": "Equalizer",
    "recommendations": "Recommendations",
    "converter": "MP4 to MP3",
    "settings": "Settings",
}

_PARENT = {"playlist": "playlists", "artist": "artists", "album": "albums", "search": "home"}

_DATA_SCREENS = {
    "home",
    "songs",
    "albums",
    "artists",
    "favorites",
    "most_played",
    "recent",
    "playlists",
    "playlist",
    "artist",
    "album",
    "search",
}


class NavButton(ButtonBehavior, BoxLayout):
    def __init__(self, screen: str, text: str, icon: str, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(10), padding=(dp(12), 0), **kwargs)
        self.screen_name = screen
        self.active = False
        self.hover = False
        self.icon = Icon(name=icon, size_hint=(None, None), size=(dp(18), dp(18)))
        self.label = VWLabel(text=text, role="body")
        self.add_widget(self.icon)
        self.add_widget(self.label)
        self.bind(on_release=lambda *_: App.get_running_app().root.go(self.screen_name))
        self.bind(pos=self._paint, size=self._paint, state=self._paint)
        Window.bind(mouse_pos=self._mouse)
        watch_theme(self, self._paint)

    def _mouse(self, _window, pos):
        inside = pointer_inside(self, pos)
        if inside != self.hover:
            self.hover = inside
            self._paint()

    def set_active(self, active: bool):
        self.active = active
        self._paint()

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors or self.width < 2:
            return
        if self.active:
            fill = (*colors.accent[:3], 0.2)
            ink = colors.accent
        elif self.hover or self.state == "down":
            fill = colors.hover
            ink = colors.text
        else:
            fill = (0, 0, 0, 0)
            ink = colors.text
        self.label.ink = ink
        self.icon.icon_color = ink
        if fill[3] <= 0:
            return
        with self.canvas.before:
            Color(*fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=radii(dp(12)))


class Sidebar(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None, 1), width=dp(228), **kwargs)
        self.collapsed = False
        self.buttons: list[NavButton] = []
        self.captions: list[VWLabel] = []
        self.word = VWLabel(text="VibeWave", role="section")
        logo = BoxLayout(size_hint_y=None, height=dp(64), padding=(dp(16), 0), spacing=dp(8))
        mark = Icon(name="spark", size_hint=(None, None), size=(dp(18), dp(18)))
        logo.add_widget(mark)
        logo.add_widget(self.word)
        self.add_widget(logo)
        nav = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2), padding=(dp(8), 0, dp(8), dp(12)))
        nav.bind(minimum_height=nav.setter("height"))
        for caption, items in _NAV:
            label = VWLabel(text=caption, role="micro", faint=True, size_hint_y=None, height=dp(22))
            nav.add_widget(label)
            self.captions.append(label)
            for screen, text, icon in items:
                button = NavButton(screen, text, icon)
                nav.add_widget(button)
                self.buttons.append(button)
        scroll = DesktopScroll()
        scroll.add_widget(nav)
        self.add_widget(scroll)
        self._mark = mark
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)
        self._tint_cb = lambda *_args: self._tint_mark(mark)
        Clock.schedule_once(self._tint_cb, 0)

    def _tint_mark(self, mark):
        colors = theme()
        if colors:
            mark.icon_color = colors.accent

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        self._mark.icon_color = colors.accent
        with self.canvas.before:
            Color(*colors.elev)
            Rectangle(pos=self.pos, size=self.size)
            Color(*colors.stroke)
            Rectangle(pos=(self.right - 1, self.y), size=(1, self.height))

    def set_active(self, name: str):
        for button in self.buttons:
            button.set_active(button.screen_name == name)

    def set_collapsed(self, collapsed: bool):
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        Animation.cancel_all(self)
        Animation(width=dp(76) if collapsed else dp(228), d=0.16).start(self)
        self.word.opacity = 0 if collapsed else 1
        for button in self.buttons:
            button.label.opacity = 0 if collapsed else 1
            button.label.size_hint_x = 0 if collapsed else 1
        for label in self.captions:
            label.opacity = 0 if collapsed else 1
            label.height = 0 if collapsed else dp(22)


class Header(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(64), padding=(dp(22), dp(12)), spacing=dp(12), **kwargs)
        self.title = VWLabel(text="Home", role="title", size_hint_x=None, width=dp(140), shorten=False)
        self.search = SearchField()
        self.search.size_hint_x = 1
        self.search.size_hint_y = None
        self.search.height = dp(42)
        self.status = VWLabel(text="", role="micro", muted=True, size_hint_x=None, width=dp(180), halign="right")
        scan = VWButton(text="Scan", icon="folder", kind="ghost")
        scan.width = dp(96)
        scan.bind(on_release=lambda *_: App.get_running_app().root.rescan())
        self.add_widget(self.title)
        self.add_widget(self.search)
        self.add_widget(self.status)
        self.add_widget(scan)
        self._event = None
        self.search.input.bind(text=self._typed)
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.stroke)
            Rectangle(pos=(self.x, self.y), size=(self.width, 1))

    def set_title(self, text: str):
        self.title.text = text
        self.title.width = min(dp(280), max(dp(108), dp(12.5) * len(text) + dp(8)))

    def set_scan(self, snap: dict, count: int):
        if snap.get("running"):
            total = int(snap.get("total") or 0)
            seen = int(snap.get("seen") or 0)
            name = snap.get("current") or ""
            self.status.text = f"{seen}/{total}  {name}" if total else (snap.get("message") or "Scanning")
        else:
            self.status.text = f"{count} songs"

    def _typed(self, _widget, text):
        if self._event is not None:
            self._event.cancel()
        self._search_cb = lambda _dt, value=text: self._search(value)
        self._event = Clock.schedule_once(self._search_cb, 0.2)

    def _search(self, text: str):
        root = App.get_running_app().root
        cleaned = text.strip()
        if cleaned:
            root.open_search(cleaned)
        elif root.manager.current == "search":
            root.go("home")


class Shell(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        app = App.get_running_app()
        self.player = app.player
        self.db = app.db
        self.bind(pos=self._paint, size=self._paint)
        watch_theme(self, self._paint)
        self.sidebar = Sidebar()
        self.header = Header()
        self.manager = ScreenManager(transition=NoTransition())
        self.pages = {}
        for cls in (*LIBRARY_SCREENS, *SOUND_SCREENS):
            screen = cls()
            self.pages[screen.name] = screen
            self.manager.add_widget(screen)
        main = BoxLayout(orientation="vertical")
        main.add_widget(self.header)
        main.add_widget(self.manager)
        top = BoxLayout()
        top.add_widget(self.sidebar)
        top.add_widget(main)
        self.bar = PlayerBar()
        column = BoxLayout(orientation="vertical")
        column.add_widget(top)
        column.add_widget(self.bar)
        self.add_widget(column)
        self.now = NowPlaying()
        self.queue_panel = QueuePanel()
        self.menu = ContextMenu()
        self.modal = Modal()
        self.toast = Toast()
        for overlay in (self.now, self.queue_panel, self.menu, self.modal, self.toast):
            self.add_widget(overlay)
        self.sidebar.set_active("home")
        self.player.bind(library_revision=self._on_library, stats_revision=self._on_stats, notice_seq=self._on_notice)

    def _paint(self, *_args):
        self.canvas.before.clear()
        colors = theme()
        if not colors:
            return
        with self.canvas.before:
            Color(*colors.bg)
            Rectangle(pos=self.pos, size=self.size)

    def go(self, name: str):
        if name not in self.pages:
            return
        self.menu.hide()
        if self.manager.current == name:
            screen = self.pages[name]
            if hasattr(screen, "refresh"):
                screen.refresh()
        else:
            self.manager.current = name
        self.sidebar.set_active(_PARENT.get(name, name))
        self.header.set_title(_TITLES.get(name, "VibeWave"))

    def open_artist(self, name: str):
        self.pages["artist"].prepare(name)
        self.go("artist")

    def open_album(self, artist: str, album: str):
        self.pages["album"].prepare(artist, album)
        self.go("album")

    def open_playlist(self, playlist_id: int):
        self.pages["playlist"].prepare(playlist_id)
        self.go("playlist")

    def open_search(self, text: str):
        self.pages["search"].query = text
        self.go("search")

    def show_now(self):
        self.now.show()

    def show_queue(self):
        self.queue_panel.show()

    def toggle_queue(self):
        self.queue_panel.toggle()

    def hide_overlays(self):
        self.now.hide()
        self.queue_panel.hide()
        self.menu.hide()
        self.modal.hide()

    def set_theme(self, mode: str | None = None, accent: str | None = None):
        colors = App.get_running_app().theme
        colors.apply(mode or colors.mode, accent or colors.accent_name)
        Window.clearcolor = colors.bg
        self.db.set_setting("theme_mode", colors.mode)
        self.db.set_setting("theme_accent", colors.accent_name)
        settings = self.pages.get("settings")
        if settings:
            settings.mark_theme()

    def on_resize(self):
        self.sidebar.set_collapsed(Window.width < 1180)

    def rescan(self):
        scanner = App.get_running_app().scanner
        if scanner.state.running:
            self.player.toast("A scan is already running")
            return
        if not scanner.start():
            self.player.toast(scanner.state.snapshot().get("message") or "Add a music folder first")

    def add_music_folder(self):
        path = pick_directory("Choose a music folder")
        if not path:
            return
        absolute = os.path.abspath(path)
        if not os.path.isdir(absolute):
            self.player.toast("That folder is not available")
            return
        drive, tail = os.path.splitdrive(absolute)
        if drive and tail.strip("\\/") == "":
            self.confirm(
                "Scan this whole drive?",
                f"{absolute} is an entire drive. Only audio files are read, and it can take a long time.",
                lambda: self._remember_folder(absolute),
                ok_text="Scan drive",
            )
            return
        self._remember_folder(absolute)

    def _remember_folder(self, path: str):
        self.db.add_folder(path)
        self.player.toast("Folder added. Scanning…")
        self.rescan()
        if self.manager.current == "settings":
            self.pages["settings"].refresh()

    def confirm(self, title, body, on_ok, ok_text="OK", danger=False):
        self.menu.hide()
        self.modal.confirm(title, body, on_ok, ok_text=ok_text, danger=danger)

    def prompt(self, title, hint, initial, on_ok):
        self.menu.hide()

        def submit(text):
            if text.strip():
                on_ok(text.strip())

        self.modal.prompt(title, hint, initial, submit)

    def choose(self, title, body, options, on_choice):
        self.menu.hide()
        self.modal.choose(title, body, options, on_choice)

    def confirm_clear_history(self):
        self.confirm(
            "Clear listening history?",
            "Play counts, skips, and recommendation history are removed. Favorites and ratings stay.",
            self._clear_history,
            ok_text="Clear history",
            danger=True,
        )

    def _clear_history(self):
        self.db.clear_history()
        self.player.stats_revision += 1
        self.player.toast("Listening history cleared")

    def open_track_menu(self, track_id: int, ids: list[int], item_id: int = 0):
        track = self.db.get_track(int(track_id))
        if not track:
            return
        favorite = "Remove from favorites" if track.get("favorite") else "Add to favorites"

        def toggle_fav():
            self.player.set_favorite_id(int(track_id), not bool(track.get("favorite")))

        actions = [
            ("Play", lambda: self.player.play_ids(list(ids) or [int(track_id)], int(track_id), user_skip=True)),
            ("Play next", lambda: self.player.play_next(int(track_id))),
            ("Add to queue", lambda: self.player.add_to_queue(int(track_id))),
            (favorite, toggle_fav),
            ("Add to playlist", lambda: self._playlist_picker(int(track_id))),
            ("Go to artist", lambda: self.open_artist(track.get("artist") or "")),
            ("Go to album", lambda: self.open_album(track.get("artist") or "", track.get("album") or "")),
            ("Exclude from library", lambda: self._confirm_exclude(track)),
            ("Show in Explorer", lambda: self._reveal(track.get("path") or "")),
        ]
        if item_id:
            actions.append(("Remove from playlist", lambda: self._remove_playlist_item(int(item_id))))
        self.menu.show(Window.mouse_pos, actions)

    def _playlist_picker(self, track_id: int):
        options = [(row["name"], "ghost", int(row["id"])) for row in self.db.list_playlists()]
        options.append(("New playlist", "primary", 0))

        def chosen(value):
            if not value:
                self.prompt("New playlist", "Name", "", lambda name: self._create_playlist(name, track_id))
                return
            self.db.add_to_playlist(int(value), track_id)
            self.player.library_revision += 1
            self.player.toast("Added to the playlist")

        self.choose("Add to playlist", "Pick a playlist for this song.", options, chosen)

    def _create_playlist(self, name: str, track_id: int):
        playlist_id = self.db.create_playlist(name)
        self.db.add_to_playlist(playlist_id, track_id)
        self.player.library_revision += 1
        self.player.toast(f"Added to {name}")

    def _remove_playlist_item(self, item_id: int):
        self.db.remove_from_playlist(item_id)
        self.player.library_revision += 1
        self.player.toast("Removed from the playlist")

    def _confirm_exclude(self, track: dict):
        self.confirm(
            "Exclude this file?",
            track.get("path") or track.get("title") or "This file",
            lambda: self._exclude(track),
            ok_text="Exclude",
            danger=True,
        )

    def _exclude(self, track: dict):
        track_id = int(track["id"])
        self.db.exclude_track(track_id)
        positions = [index for index, queued in enumerate(self.player.queue) if queued == track_id]
        for position in reversed(positions):
            self.player.remove_from_queue(position)
        self.player.library_revision += 1
        self.player.toast("Excluded from the library")

    def _reveal(self, path: str):
        if not path or not os.path.exists(path):
            self.player.toast("That file is not on disk")
            return
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])

    def poll_scan(self, _dt):
        scanner = App.get_running_app().scanner
        snap = scanner.state.snapshot()
        try:
            count = self.db.count_tracks()
        except Exception:
            count = 0
        self.header.set_scan(snap, count)
        result = scanner.state.consume_result()
        if not result:
            return
        if result.get("error"):
            self.player.toast(str(result["error"]))
        else:
            message = scanner.state.message or "Scan finished"
            errors = result.get("errors") or []
            if errors:
                message = f"{message}. {errors[0]}"
            self.player.library_revision += 1
            self.player.toast(message)

    def poll_convert(self, _dt):
        page = self.pages.get("converter")
        if page:
            page.poll()

    def _on_library(self, *_args):
        name = self.manager.current
        if name == "settings":
            self.pages["settings"].refresh()
        elif name in _DATA_SCREENS:
            screen = self.pages[name]
            if hasattr(screen, "refresh"):
                screen.refresh()
        try:
            self.header.set_scan(App.get_running_app().scanner.state.snapshot(), self.db.count_tracks())
        except Exception:
            pass

    def _on_stats(self, *_args):
        name = self.manager.current
        if name == "songs":
            self.pages["songs"].patch()
        elif name in {"home", "favorites", "most_played", "recent", "artist", "album", "playlist", "search"}:
            screen = self.pages[name]
            if hasattr(screen, "refresh"):
                screen.refresh()

    def _on_notice(self, *_args):
        if self.player.notice:
            self.toast.show(self.player.notice)

    def on_key(self, _window, key, _scancode, codepoint, modifiers):
        modifiers = modifiers or []
        if key == 27:
            if App.get_running_app().text_focused:
                self.header.search.input.focus = False
                return True
            if self.modal.opened:
                self.modal.hide()
                return True
            if self.menu.opened:
                self.menu.hide()
                return True
            if self.queue_panel.opened:
                self.queue_panel.hide()
                return True
            if self.now.opened:
                self.now.hide()
                return True
            return True
        if App.get_running_app().text_focused or self.modal.opened:
            return False
        ctrl = "ctrl" in modifiers
        char = (codepoint or "").lower()
        player = self.player
        if ctrl and key == 276:
            player.previous()
        elif ctrl and key == 275:
            player.next(user=True)
        elif ctrl and char == "f":
            self.header.search.input.focus = True
        elif ctrl and (char == "." or key == 46):
            player.stop()
        elif char == " " or key == 32:
            player.toggle()
        elif key == 276:
            player.seek(max(0.0, player.position - 5))
        elif key == 275:
            player.seek(player.position + 5)
        elif key == 273:
            player.nudge_volume(0.05)
        elif key == 274:
            player.nudge_volume(-0.05)
        elif char == "m":
            player.toggle_mute()
        elif char == "f":
            player.toggle_favorite()
        elif char == "s":
            player.toggle_shuffle()
        elif char == "r":
            player.cycle_repeat()
        elif char == "q":
            self.toggle_queue()
        elif char == "e":
            self.now.hide()
            self.go("equalizer")
        elif char == "n":
            self.show_now()
        else:
            return False
        return True
