"""Library browser, detail pages, and search."""

from __future__ import annotations

import time

from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from vibewave.constants import SORT_OPTIONS
from vibewave.formatutil import format_listen_time, format_when
from vibewave.recommend import similar_tracks
from vibewave.ui.kit import (
    MediaCard,
    StatPill,
    chip_scroller,
    heading,
    hstrip,
    page_scroll,
    play_tracks,
    wrapping,
)
from vibewave.ui.kit import app as running_app
from vibewave.ui.kit import root as shell
from vibewave.ui.widgets import CoverImage, EmptyState, Icon, IconButton, Panel, TrackList, VWButton, VWLabel


def _db():
    return running_app().db


class ArtistRow(ButtonBehavior, Panel):
    def __init__(self, row: dict, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(76),
            padding=(dp(10), dp(10)),
            spacing=dp(12),
            radius=dp(16),
            **kwargs,
        )
        self.artist_name = row.get("artist") or "Unknown Artist"
        art = CoverImage(source=row.get("artwork") or "", title=self.artist_name, radius=dp(12), size_hint=(None, None), size=(dp(52), dp(52)))
        text = BoxLayout(orientation="vertical", padding=(0, dp(4)))
        text.add_widget(VWLabel(text=self.artist_name, role="body", size_hint_y=None, height=dp(22)))
        detail = (
            f"{int(row.get('track_count') or 0)} songs"
            f"   ·   {int(row.get('plays') or 0)} plays"
            f"   ·   {format_listen_time(row.get('listen_time'))}"
        )
        text.add_widget(VWLabel(text=detail, role="micro", muted=True, size_hint_y=None, height=dp(16)))
        play = IconButton(icon="play", kind="primary")
        play.size = (dp(36), dp(36))
        play.bind(on_release=lambda *_: self._play())
        chevron = Icon(name="chevron", size_hint=(None, None), size=(dp(16), dp(16)))
        self.add_widget(art)
        self.add_widget(text)
        self.add_widget(play)
        self.add_widget(chevron)
        self.bind(on_release=lambda *_: shell().open_artist(self.artist_name))

    def _play(self):
        play_tracks(_db().query_tracks(artist=self.artist_name, sort="title"), shuffle=False)


class HistoryRow(ButtonBehavior, Panel):
    def __init__(self, row: dict, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            padding=(dp(12), dp(8)),
            spacing=dp(8),
            radius=dp(14),
            **kwargs,
        )
        self.row = row
        title = row.get("title") or "Removed from the library"
        flag = "Skipped" if row.get("skipped") else ("Finished" if row.get("completed") else "Played")
        text = BoxLayout(orientation="vertical")
        text.add_widget(VWLabel(text=title, role="body", size_hint_y=None, height=dp(22)))
        text.add_widget(
            VWLabel(
                text=f"{row.get('artist') or ''}   ·   {flag}   ·   {format_when(row.get('played_at'))}",
                role="micro",
                muted=True,
                size_hint_y=None,
                height=dp(16),
            )
        )
        self.add_widget(text)
        self.bind(on_release=self._play)

    def _play(self, *_args):
        if self.row.get("missing") or self.row.get("excluded") or not self.row.get("track_id"):
            running_app().player.toast("That song is no longer available")
            return
        running_app().player.play_track(int(self.row["track_id"]))


def _album_card(row: dict, *, stretch: bool) -> MediaCard:
    subtitle = f"{row.get('artist') or ''}  ·  {int(row.get('plays') or 0)} plays"
    return MediaCard(
        row.get("album") or "Unknown Album",
        subtitle,
        row.get("artwork") or "",
        on_open=lambda artist=row.get("artist") or "", album=row.get("album") or "": shell().open_album(artist, album),
        on_play=lambda artist=row.get("artist") or "", album=row.get("album") or "": play_tracks(
            _db().album_tracks(artist, album)
        ),
        stretch=stretch,
    )


def _track_card(track: dict, group: list[dict]) -> MediaCard:
    return MediaCard(
        track.get("title") or "Untitled",
        track.get("artist") or "",
        track.get("artwork_path") or "",
        on_open=lambda item=track, rows=group: play_tracks(rows, start=item),
        stretch=False,
    )


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="home", **kwargs)
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.body.clear_widgets()
        database = _db()
        if database.count_tracks() == 0:
            self.body.add_widget(
                EmptyState(
                    "Add your music",
                    "Choose the folders VibeWave should read. Only those folders are scanned.",
                    "Add a music folder",
                    lambda: shell().add_music_folder(),
                )
            )
            return
        hour = time.localtime().tm_hour
        if hour < 12:
            greet = "Good morning"
        elif hour < 18:
            greet = "Good afternoon"
        else:
            greet = "Good evening"
        self.body.add_widget(VWLabel(text=greet, role="display", size_hint_y=None, height=dp(40)))
        stats = database.library_stats()
        pills = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(10))
        for value, label in (
            (str(stats["tracks"]), "Songs"),
            (str(stats["albums"]), "Albums"),
            (str(stats["artists"]), "Artists"),
            (str(int(stats["plays"])), "Plays"),
            (format_listen_time(stats["listen"]), "Listened"),
        ):
            pills.add_widget(StatPill(value, label))
        pills.add_widget(Widget())
        self.body.add_widget(pills)

        recent = database.query_tracks(sort="date_added", limit=12)
        if recent:
            self.body.add_widget(heading("Recently added"))
            self.body.add_widget(hstrip([_track_card(track, recent) for track in recent], dp(240)))

        played = database.query_tracks(sort="play_count", min_plays=1, limit=12)
        if played:
            self.body.add_widget(heading("Most played"))
            self.body.add_widget(hstrip([_track_card(track, played) for track in played], dp(240)))

        artists = [row for row in database.artists(sort="plays") if int(row.get("plays") or 0) > 0][:8]
        if artists:
            self.body.add_widget(heading("Artists you play"))
            block = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
            block.bind(minimum_height=block.setter("height"))
            for row in artists:
                block.add_widget(ArtistRow(row))
            self.body.add_widget(block)

        albums = database.favorite_albums() or database.albums(sort="plays")[:8]
        if albums:
            title = "Favorite albums" if database.favorite_albums() else "Albums"
            self.body.add_widget(heading(title))
            self.body.add_widget(hstrip([_album_card(row, stretch=False) for row in albums[:8]], dp(286)))


class SongsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="songs", **kwargs)
        self.sort_key = running_app().db.get_setting("song_sort", "title") or "title"
        if self.sort_key not in {key for key, _label in SORT_OPTIONS}:
            self.sort_key = "title"
        self.count = VWLabel(text="", role="small", muted=True, size_hint_y=None, height=dp(22))
        pairs = [(key, label) for key, label in SORT_OPTIONS]
        self.chips_box, self.chips = chip_scroller(pairs, self.sort_key, self._pick_sort)
        self.tracks = TrackList()
        root = BoxLayout(orientation="vertical", padding=(dp(22), dp(12), dp(22), dp(8)), spacing=dp(8))
        root.add_widget(self.count)
        root.add_widget(self.chips_box)
        root.add_widget(self.tracks)
        self.add_widget(root)

    def on_enter(self):
        self.refresh()

    def _pick_sort(self, key: str):
        self.sort_key = key
        _db().set_setting("song_sort", key)
        for chip, (name, _label) in zip(self.chips, SORT_OPTIONS):
            chip.selected = name == key
        self.refresh()

    def refresh(self):
        rows = _db().query_tracks(sort=self.sort_key)
        self.tracks.set_rows(rows)
        self.count.text = f"{len(rows)} songs"

    def patch(self):
        self.tracks.patch_stats(_db().track_stats_map(self.tracks.ids))


class AlbumsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="albums", **kwargs)
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.body.clear_widgets()
        rows = _db().albums(sort="name")
        if not rows:
            self.body.add_widget(EmptyState("No albums yet", "Scan a music folder and albums will be grouped here."))
            return
        self.body.add_widget(heading(f"{len(rows)} albums"))
        grid = GridLayout(cols=4, spacing=dp(14), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        grid.bind(width=lambda *_: setattr(grid, "cols", max(2, int(max(grid.width, dp(200)) / dp(210)))))
        for row in rows:
            grid.add_widget(_album_card(row, stretch=True))
        self.body.add_widget(grid)


class ArtistsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="artists", **kwargs)
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.body.clear_widgets()
        rows = _db().artists(sort="name")
        if not rows:
            self.body.add_widget(EmptyState("No artists yet", "Artists appear after a folder scan."))
            return
        self.body.add_widget(heading(f"{len(rows)} artists"))
        for row in rows:
            self.body.add_widget(ArtistRow(row))


class FavoritesScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="favorites", **kwargs)
        self.count = VWLabel(text="Favorites", role="small", muted=True, size_hint_y=None, height=dp(22))
        self.tracks = TrackList()
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(12), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(self.count)
        layout.add_widget(self.tracks)
        self.add_widget(layout)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        rows = _db().query_tracks(favorite=True, sort="title")
        self.tracks.set_rows(rows)
        self.tracks.empty.text = "No favorites yet. Tap the heart on a song."
        self.count.text = f"{len(rows)} favorites"


class MostPlayedScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="most_played", **kwargs)
        self.mode = "songs"
        pairs = [("songs", "Songs"), ("artists", "Artists"), ("albums", "Albums")]
        self.chips_box, self.chips = chip_scroller(pairs, self.mode, self._pick)
        self.tracks = TrackList()
        self.scroll, self.body = page_scroll()
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(8), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(self.chips_box)
        holder = BoxLayout()
        holder.add_widget(self.tracks)
        holder.add_widget(self.scroll)
        layout.add_widget(holder)
        self.add_widget(layout)

    def on_enter(self):
        self.refresh()

    def _pick(self, mode: str):
        self.mode = mode
        for chip, key in zip(self.chips, ("songs", "artists", "albums")):
            chip.selected = key == mode
        self.refresh()

    def _show_tracks(self, show: bool):
        self.tracks.size_hint_y = 1 if show else None
        self.tracks.opacity = 1 if show else 0
        if not show:
            self.tracks.height = 0
        self.scroll.size_hint_y = None if show else 1
        self.scroll.opacity = 0 if show else 1
        if show:
            self.scroll.height = 0

    def refresh(self):
        if self.mode == "songs":
            self._show_tracks(True)
            rows = _db().query_tracks(sort="play_count", min_plays=1)
            self.tracks.set_rows(rows)
            self.tracks.empty.text = "Play a few songs and the ones you return to will gather here."
            return
        self._show_tracks(False)
        self.body.clear_widgets()
        if self.mode == "artists":
            rows = [row for row in _db().artists(sort="plays") if int(row.get("plays") or 0) > 0]
            if not rows:
                self.body.add_widget(EmptyState("No artist plays yet", "Listening time is counted per song, then added up for the artist."))
                return
            self.body.add_widget(heading("Most played artists"))
            self.body.add_widget(wrapping("An artist's place here is the sum of their songs, not one track's play count."))
            for row in rows:
                self.body.add_widget(ArtistRow(row))
            return
        rows = [row for row in _db().albums(sort="plays") if int(row.get("plays") or 0) > 0]
        if not rows:
            self.body.add_widget(EmptyState("No album plays yet", "Album totals add every song on the album."))
            return
        self.body.add_widget(heading("Most played albums"))
        grid = GridLayout(cols=3, spacing=dp(14), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        grid.bind(width=lambda *_: setattr(grid, "cols", max(2, int(max(grid.width, dp(200)) / dp(220)))))
        for row in rows:
            grid.add_widget(_album_card(row, stretch=True))
        self.body.add_widget(grid)


class RecentScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="recent", **kwargs)
        self.mode = "played"
        pairs = [("played", "Recently played"), ("added", "Recently added"), ("history", "History")]
        self.chips_box, self.chips = chip_scroller(pairs, self.mode, self._pick)
        self.tracks = TrackList()
        self.scroll, self.body = page_scroll()
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(8), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(self.chips_box)
        holder = BoxLayout()
        holder.add_widget(self.tracks)
        holder.add_widget(self.scroll)
        layout.add_widget(holder)
        self.add_widget(layout)

    def on_enter(self):
        self.refresh()

    def _pick(self, mode: str):
        self.mode = mode
        for chip, key in zip(self.chips, ("played", "added", "history")):
            chip.selected = key == mode
        self.refresh()

    def refresh(self):
        show_tracks = self.mode != "history"
        self.tracks.size_hint_y = 1 if show_tracks else None
        self.tracks.opacity = 1 if show_tracks else 0
        if not show_tracks:
            self.tracks.height = 0
        self.scroll.size_hint_y = None if show_tracks else 1
        self.scroll.opacity = 0 if show_tracks else 1
        if show_tracks:
            self.scroll.height = 0
        if self.mode == "played":
            rows = _db().query_tracks(sort="last_played", played_only=True)
            self.tracks.set_rows(rows)
            self.tracks.empty.text = "Songs you listen to will show up here."
            return
        if self.mode == "added":
            rows = _db().query_tracks(sort="date_added", limit=200)
            self.tracks.set_rows(rows)
            self.tracks.empty.text = "Nothing has been added yet."
            return
        self.body.clear_widgets()
        clear = VWButton(text="Clear history", kind="danger")
        clear.width = dp(150)
        clear.bind(on_release=lambda *_: shell().confirm_clear_history())
        holder = BoxLayout(size_hint_y=None, height=dp(44))
        holder.add_widget(clear)
        holder.add_widget(Widget())
        self.body.add_widget(holder)
        rows = _db().history_rows()
        if not rows:
            self.body.add_widget(EmptyState("No listening history", "Plays and skips are stored on this computer."))
            return
        for row in rows:
            self.body.add_widget(HistoryRow(row))


class PlaylistsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="playlists", **kwargs)
        self.scroll, self.body = page_scroll()
        self.add_widget(self.scroll)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.body.clear_widgets()
        new = VWButton(text="New playlist", icon="plus", kind="primary")
        new.width = dp(160)
        new.bind(on_release=lambda *_: shell().prompt("New playlist", "Name", "", self._create))
        holder = BoxLayout(size_hint_y=None, height=dp(44))
        holder.add_widget(new)
        holder.add_widget(Widget())
        self.body.add_widget(holder)
        rows = _db().list_playlists()
        if not rows:
            self.body.add_widget(EmptyState("No playlists", "Create one, then add songs from the right-click menu."))
            return
        for row in rows:
            self.body.add_widget(_PlaylistButton(row))

    def _create(self, name: str):
        if not name.strip():
            return
        playlist_id = _db().create_playlist(name.strip())
        running_app().player.library_revision += 1
        shell().open_playlist(playlist_id)


class _PlaylistButton(ButtonBehavior, Panel):
    def __init__(self, row: dict, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=(dp(14), dp(10)),
            spacing=dp(8),
            radius=dp(16),
            **kwargs,
        )
        self.playlist_id = int(row["id"])
        text = BoxLayout(orientation="vertical")
        text.add_widget(VWLabel(text=row.get("name") or "Playlist", role="body", size_hint_y=None, height=dp(22)))
        text.add_widget(VWLabel(text=f"{int(row.get('track_count') or 0)} songs", role="micro", muted=True, size_hint_y=None, height=dp(16)))
        self.add_widget(text)
        self.add_widget(Icon(name="chevron", size_hint=(None, None), size=(dp(16), dp(16))))
        self.bind(on_release=lambda *_: shell().open_playlist(self.playlist_id))


class PlaylistScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="playlist", **kwargs)
        self.playlist_id = 0
        self.title_label = VWLabel(text="Playlist", role="title", size_hint_y=None, height=dp(32))
        back = IconButton(icon="back")
        back.bind(on_release=lambda *_: shell().go("playlists"))
        play = VWButton(text="Play", icon="play", kind="primary")
        play.width = dp(110)
        shuffle = VWButton(text="Shuffle", icon="shuffle", kind="ghost")
        shuffle.width = dp(120)
        rename = VWButton(text="Rename", kind="ghost")
        rename.width = dp(110)
        delete = VWButton(text="Delete", kind="danger")
        delete.width = dp(110)
        play.bind(on_release=lambda *_: self._play(False))
        shuffle.bind(on_release=lambda *_: self._play(True))
        rename.bind(on_release=lambda *_: shell().prompt("Rename playlist", "Name", self.title_label.text, self._rename))
        delete.bind(on_release=lambda *_: shell().confirm("Delete this playlist?", "The songs stay in your library.", self._delete, ok_text="Delete", danger=True))
        top = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        top.add_widget(back)
        top.add_widget(self.title_label)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for button in (play, shuffle, rename, delete):
            actions.add_widget(button)
        actions.add_widget(Widget())
        self.tracks = TrackList()
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(12), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(top)
        layout.add_widget(actions)
        layout.add_widget(self.tracks)
        self.add_widget(layout)

    def prepare(self, playlist_id: int):
        self.playlist_id = int(playlist_id)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        playlist = _db().get_playlist(self.playlist_id)
        if not playlist:
            self.title_label.text = "Playlist"
            self.tracks.set_rows([])
            return
        self.title_label.text = playlist["name"]
        rows = _db().playlist_tracks(self.playlist_id)
        self.tracks.set_rows(rows)
        self.tracks.empty.text = "This playlist is empty. Right-click a song and choose Add to playlist."

    def _play(self, shuffle: bool):
        play_tracks(_db().playlist_tracks(self.playlist_id), shuffle=shuffle)

    def _rename(self, name: str):
        if not name.strip():
            return
        _db().rename_playlist(self.playlist_id, name.strip())
        running_app().player.library_revision += 1

    def _delete(self):
        _db().delete_playlist(self.playlist_id)
        running_app().player.library_revision += 1
        shell().go("playlists")


class ArtistScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="artist", **kwargs)
        self.artist_name = ""
        self.mode = "tracks"
        self.title_label = VWLabel(text="Artist", role="title")
        self.meta = VWLabel(text="", role="small", muted=True, size_hint_y=None, height=dp(22))
        back = IconButton(icon="back")
        back.bind(on_release=lambda *_: shell().go("artists"))
        play = VWButton(text="Play all", icon="play", kind="primary")
        play.width = dp(120)
        shuffle = VWButton(text="Shuffle all", icon="shuffle", kind="ghost")
        shuffle.width = dp(140)
        play.bind(on_release=lambda *_: self._play(False))
        shuffle.bind(on_release=lambda *_: self._play(True))
        top = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        top.add_widget(back)
        top.add_widget(self.title_label)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        actions.add_widget(play)
        actions.add_widget(shuffle)
        actions.add_widget(Widget())
        pairs = [
            ("tracks", "All tracks"),
            ("albums", "Albums"),
            ("most", "Most played"),
            ("favorites", "Favorites"),
            ("similar", "Similar"),
        ]
        self.chips_box, self.chips = chip_scroller(pairs, self.mode, self._pick)
        self.tracks = TrackList()
        self.scroll, self.body = page_scroll()
        holder = BoxLayout()
        holder.add_widget(self.tracks)
        holder.add_widget(self.scroll)
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(10), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(top)
        layout.add_widget(self.meta)
        layout.add_widget(actions)
        layout.add_widget(self.chips_box)
        layout.add_widget(holder)
        self.add_widget(layout)

    def prepare(self, name: str):
        self.artist_name = name
        self.mode = "tracks"

    def on_enter(self):
        self.refresh()

    def _pick(self, mode: str):
        self.mode = mode
        keys = ("tracks", "albums", "most", "favorites", "similar")
        for chip, key in zip(self.chips, keys):
            chip.selected = key == mode
        self.refresh()

    def _show_tracks(self, show: bool):
        self.tracks.size_hint_y = 1 if show else None
        self.tracks.opacity = 1 if show else 0
        if not show:
            self.tracks.height = 0
        self.scroll.size_hint_y = None if show else 1
        self.scroll.opacity = 0 if show else 1
        if show:
            self.scroll.height = 0

    def refresh(self):
        summary = _db().artist_summary(self.artist_name) if self.artist_name else None
        self.title_label.text = self.artist_name or "Artist"
        if not summary:
            self.meta.text = "This artist is not in the library."
            self._show_tracks(True)
            self.tracks.set_rows([])
            return
        self.meta.text = (
            f"{int(summary.get('track_count') or 0)} songs"
            f"   ·   {int(summary.get('album_count') or 0)} albums"
            f"   ·   {int(summary.get('plays') or 0)} plays"
            f"   ·   {format_listen_time(summary.get('listen_time'))}"
        )
        if self.mode == "albums":
            self._show_tracks(False)
            self.body.clear_widgets()
            rows = _db().albums(artist=self.artist_name, sort="year")
            if not rows:
                self.body.add_widget(EmptyState("No albums", "Songs by this artist are not grouped into an album."))
                return
            grid = GridLayout(cols=3, spacing=dp(14), size_hint_y=None)
            grid.bind(minimum_height=grid.setter("height"))
            grid.bind(width=lambda *_: setattr(grid, "cols", max(2, int(max(grid.width, dp(180)) / dp(220)))))
            for row in rows:
                grid.add_widget(_album_card(row, stretch=True))
            self.body.add_widget(grid)
            return
        self._show_tracks(True)
        if self.mode == "most":
            rows = _db().query_tracks(artist=self.artist_name, sort="play_count", min_plays=1)
        elif self.mode == "favorites":
            rows = _db().query_tracks(artist=self.artist_name, favorite=True, sort="title")
        elif self.mode == "similar":
            packs = similar_tracks(_db(), self.artist_name)
            rows = []
            for pack in packs:
                row = dict(pack["track"])
                row["album"] = pack["reason"]
                rows.append(row)
        else:
            rows = _db().query_tracks(artist=self.artist_name, sort="album")
        self.tracks.set_rows(rows)
        self.tracks.empty.text = "Nothing in this view yet."

    def _play(self, shuffle: bool):
        play_tracks(_db().query_tracks(artist=self.artist_name, sort="title"), shuffle=shuffle)


class AlbumScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="album", **kwargs)
        self.artist_name = ""
        self.album_name = ""
        self.by_plays = False
        self.cover = CoverImage(size_hint=(None, None), size=(dp(148), dp(148)), radius=dp(16))
        self.title_label = VWLabel(text="Album", role="title", size_hint_y=None, height=dp(30))
        self.meta = VWLabel(text="", role="small", muted=True, wrap=True, size_hint_y=None, height=dp(40))
        back = IconButton(icon="back")
        back.bind(on_release=lambda *_: shell().go("albums"))
        play = VWButton(text="Play", icon="play", kind="primary")
        play.width = dp(110)
        shuffle = VWButton(text="Shuffle", icon="shuffle", kind="ghost")
        shuffle.width = dp(120)
        self.fav = VWButton(text="Favorite", icon="heart", kind="ghost")
        self.fav.width = dp(130)
        play.bind(on_release=lambda *_: self._play(False))
        shuffle.bind(on_release=lambda *_: self._play(True))
        self.fav.bind(on_release=lambda *_: self._toggle_fav())
        self.order = VWButton(text="Album order", kind="ghost")
        self.order.width = dp(140)
        self.order.bind(on_release=lambda *_: self._toggle_order())
        info = BoxLayout(orientation="vertical", spacing=dp(4))
        info.add_widget(self.title_label)
        info.add_widget(self.meta)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for button in (play, shuffle, self.fav, self.order):
            actions.add_widget(button)
        actions.add_widget(Widget())
        info.add_widget(actions)
        header = BoxLayout(size_hint_y=None, height=dp(168), spacing=dp(16))
        header.add_widget(back)
        header.add_widget(self.cover)
        header.add_widget(info)
        self.tracks = TrackList(show_album=False)
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(12), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(header)
        layout.add_widget(self.tracks)
        self.add_widget(layout)

    def prepare(self, artist: str, album: str):
        self.artist_name = artist
        self.album_name = album
        self.by_plays = False

    def on_enter(self):
        self.refresh()

    def refresh(self):
        summary = _db().album_summary(self.artist_name, self.album_name)
        self.title_label.text = self.album_name or "Album"
        self.cover.title = self.album_name or "?"
        if not summary:
            self.meta.text = ""
            self.tracks.set_rows([])
            return
        self.cover.source = summary.get("artwork") or ""
        when = format_when(summary.get("last_played")) if summary.get("last_played") else "Never played"
        self.meta.text = (
            f"{summary.get('artist') or ''}"
            f"   ·   {int(summary.get('track_count') or 0)} songs"
            f"   ·   {int(summary.get('plays') or 0)} plays"
            f"   ·   Last played {when}"
        )
        favorite = _db().album_is_favorite(self.artist_name, self.album_name)
        self.fav.text = "Favorited" if favorite else "Favorite"
        rows = _db().album_tracks(self.artist_name, self.album_name)
        if self.by_plays:
            rows = sorted(rows, key=lambda row: int(row.get("play_count") or 0), reverse=True)
            self.order.text = "By plays"
        else:
            self.order.text = "Album order"
        self.tracks.set_rows(rows, numbers="track" if not self.by_plays else "index")

    def _toggle_order(self):
        self.by_plays = not self.by_plays
        self.refresh()

    def _toggle_fav(self):
        favorite = not _db().album_is_favorite(self.artist_name, self.album_name)
        _db().set_album_favorite(self.artist_name, self.album_name, favorite)
        running_app().player.toast("Album favorited" if favorite else "Album removed from favorites")
        self.refresh()

    def _play(self, shuffle: bool):
        play_tracks(_db().album_tracks(self.artist_name, self.album_name), shuffle=shuffle)


class SearchScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(name="search", **kwargs)
        self.query = ""
        self.banner = VWLabel(text="Search", role="small", muted=True, size_hint_y=None, height=dp(22))
        self.hit_scroll = ScrollView(size_hint_y=None, height=0, do_scroll_x=False, bar_width=dp(4))
        self.hits = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.hits.bind(minimum_height=self.hits.setter("height"))
        self.hit_scroll.add_widget(self.hits)
        self.tracks = TrackList()
        layout = BoxLayout(orientation="vertical", padding=(dp(22), dp(12), dp(22), dp(8)), spacing=dp(8))
        layout.add_widget(self.banner)
        layout.add_widget(self.hit_scroll)
        layout.add_widget(self.tracks)
        self.add_widget(layout)

    def on_enter(self):
        self.refresh()

    def refresh(self):
        query = (self.query or "").strip()
        self.banner.text = f"Results for “{query}”" if query else "Search"
        self.hits.clear_widgets()
        if not query:
            self.tracks.set_rows([])
            self.hit_scroll.height = 0
            return
        artists = _db().artists(search=query)[:8]
        albums = _db().albums(search=query)[:8]
        for row in artists:
            button = VWButton(text=row["artist"] or "Unknown Artist", icon="person", kind="ghost")
            button.size_hint = (None, None)
            button.width = dp(280)
            button.bind(on_release=lambda *_, name=row.get("artist") or "": shell().open_artist(name))
            self.hits.add_widget(button)
        for row in albums:
            label = f"{row.get('album')} — {row.get('artist')}"
            button = VWButton(text=label, icon="album", kind="ghost")
            button.size_hint = (None, None)
            button.width = dp(360)
            button.bind(
                on_release=lambda *_, artist=row.get("artist") or "", album=row.get("album") or "": shell().open_album(artist, album)
            )
            self.hits.add_widget(button)
        self.hit_scroll.height = 0 if not (artists or albums) else min(dp(180), dp(8) + (len(artists) + len(albums)) * dp(44))
        rows = _db().query_tracks(search=query, sort="title")
        self.tracks.set_rows(rows)
        self.tracks.empty.text = "No songs match that search."


LIBRARY_SCREENS = [
    HomeScreen,
    SongsScreen,
    AlbumsScreen,
    ArtistsScreen,
    FavoritesScreen,
    MostPlayedScreen,
    RecentScreen,
    PlaylistsScreen,
    PlaylistScreen,
    ArtistScreen,
    AlbumScreen,
    SearchScreen,
]
