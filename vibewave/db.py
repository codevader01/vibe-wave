"""SQLite storage for the library, listening history, and settings.

The connection is shared by the UI thread and the scanner thread. Every public
method takes the same lock. Rows are plain dicts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from vibewave.constants import SORT_OPTIONS

_SORT_SQL = {key: key for key, _label in SORT_OPTIONS}
_SORT_SQL.update({
    "title": "title COLLATE NOCASE ASC, artist COLLATE NOCASE ASC",
    "artist": "artist COLLATE NOCASE ASC, album COLLATE NOCASE ASC, title COLLATE NOCASE ASC",
    "album": "album COLLATE NOCASE ASC, artist COLLATE NOCASE ASC, disc_number ASC, track_number ASC",
    "duration": "duration DESC, title COLLATE NOCASE ASC",
    "date_added": "date_added DESC, title COLLATE NOCASE ASC",
    "play_count": "play_count DESC, title COLLATE NOCASE ASC",
    "last_played": "CASE WHEN last_played IS NULL THEN 1 ELSE 0 END, last_played DESC",
})

_VISIBLE = "missing = 0 AND excluded = 0"


def path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


class Database:
    def __init__(self, path: str | os.PathLike):
        self.path = str(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self.purge_opus()

    def close(self) -> None:
        with self.lock:
            conn = self.conn
            self.conn = None
            if conn is not None:
                conn.close()

    @contextmanager
    def _tx(self):
        with self.lock:
            conn = self.conn
            if conn is None:
                yield
                return
            try:
                yield
                if self.conn is not None:
                    self.conn.commit()
            except Exception:
                if self.conn is not None:
                    self.conn.rollback()
                raise

    def _migrate(self) -> None:
        with self._tx():
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    path_key TEXT NOT NULL UNIQUE,
                    filename TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    genre TEXT,
                    track_number INTEGER,
                    disc_number INTEGER,
                    year INTEGER,
                    duration REAL DEFAULT 0,
                    file_size INTEGER DEFAULT 0,
                    mtime REAL DEFAULT 0,
                    artwork_path TEXT,
                    date_added REAL,
                    play_count INTEGER DEFAULT 0,
                    last_played REAL,
                    listen_duration REAL DEFAULT 0,
                    completed_listens INTEGER DEFAULT 0,
                    favorite INTEGER DEFAULT 0,
                    rating INTEGER DEFAULT 0,
                    skip_count INTEGER DEFAULT 0,
                    last_skipped REAL,
                    replaygain_db REAL,
                    replaygain_peak REAL,
                    fingerprint TEXT,
                    origin TEXT DEFAULT 'scan',
                    missing INTEGER DEFAULT 0,
                    excluded INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
                CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(artist, album);
                CREATE INDEX IF NOT EXISTS idx_tracks_plays ON tracks(play_count);
                CREATE INDEX IF NOT EXISTS idx_tracks_last ON tracks(last_played);
                CREATE INDEX IF NOT EXISTS idx_tracks_fp ON tracks(fingerprint);
                CREATE INDEX IF NOT EXISTS idx_tracks_visible ON tracks(missing, excluded);

                CREATE TABLE IF NOT EXISTS scan_folders (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    path_key TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    added REAL
                );

                CREATE TABLE IF NOT EXISTS exclusions (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    path_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    created REAL,
                    updated REAL
                );

                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY,
                    playlist_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER,
                    played_at REAL,
                    listened REAL DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0,
                    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_played ON history(played_at);
                CREATE INDEX IF NOT EXISTS idx_history_track ON history(track_id);

                CREATE TABLE IF NOT EXISTS album_favorites (
                    artist_key TEXT NOT NULL,
                    album_key TEXT NOT NULL,
                    artist TEXT,
                    album TEXT,
                    created REAL,
                    PRIMARY KEY (artist_key, album_key)
                );

                CREATE TABLE IF NOT EXISTS recommendation_log (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER,
                    section TEXT,
                    shown_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_reco_shown ON recommendation_log(shown_at);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    def purge_opus(self) -> int:
        """Remove any .opus row that reached the database by an older version."""
        with self.lock:
            rows = self.conn.execute("SELECT id, path FROM tracks").fetchall()
            doomed = [row["id"] for row in rows if str(row["path"]).lower().endswith(".opus")]
        if not doomed:
            return 0
        with self._tx():
            self.conn.executemany("DELETE FROM tracks WHERE id = ?", [(item,) for item in doomed])
        return len(doomed)

    # ----- settings -------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_setting(self, key: str, value: str) -> None:
        with self._tx():
            if self.conn is None:
                return
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_json(self, key: str, default):
        raw = self.get_setting(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def set_json(self, key: str, value) -> None:
        self.set_setting(key, json.dumps(value))

    # ----- folders and exclusions -----------------------------------------

    def list_folders(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM scan_folders ORDER BY path COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_folder(self, path: str) -> int:
        key = path_key(path)
        absolute = os.path.abspath(path)
        with self._tx():
            self.conn.execute(
                "INSERT INTO scan_folders(path, path_key, enabled, added) VALUES(?, ?, 1, ?) "
                "ON CONFLICT(path_key) DO UPDATE SET path = excluded.path, enabled = 1",
                (absolute, key, time.time()),
            )
            row = self.conn.execute(
                "SELECT id FROM scan_folders WHERE path_key = ?", (key,)
            ).fetchone()
        return int(row["id"])

    def remove_folder(self, folder_id: int) -> None:
        with self._tx():
            self.conn.execute("DELETE FROM scan_folders WHERE id = ?", (folder_id,))

    def list_exclusions(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM exclusions ORDER BY kind, path COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_exclusion(self, path: str, kind: str) -> None:
        absolute = os.path.abspath(path)
        with self._tx():
            self.conn.execute(
                "INSERT INTO exclusions(path, path_key, kind) VALUES(?, ?, ?) "
                "ON CONFLICT(path_key) DO UPDATE SET path = excluded.path, kind = excluded.kind",
                (absolute, path_key(path), kind),
            )
            if kind == "file":
                self.conn.execute(
                    "UPDATE tracks SET excluded = 1 WHERE path_key = ?",
                    (path_key(path),),
                )

    def remove_exclusion(self, exclusion_id: int) -> None:
        with self._tx():
            row = self.conn.execute(
                "SELECT path_key, kind FROM exclusions WHERE id = ?", (exclusion_id,)
            ).fetchone()
            self.conn.execute("DELETE FROM exclusions WHERE id = ?", (exclusion_id,))
            if row and row["kind"] == "file":
                self.conn.execute(
                    "UPDATE tracks SET excluded = 0, missing = 0 WHERE path_key = ?",
                    (row["path_key"],),
                )

    def exclusion_keys(self) -> tuple[set[str], set[str]]:
        with self.lock:
            rows = self.conn.execute("SELECT path_key, kind FROM exclusions").fetchall()
        files = {row["path_key"] for row in rows if row["kind"] == "file"}
        folders = {row["path_key"] for row in rows if row["kind"] == "folder"}
        return files, folders

    # ----- track identity --------------------------------------------------

    def find_by_path_key(self, key: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM tracks WHERE path_key = ?", (key,)).fetchone()
        return _dict(row)

    def find_by_fingerprint(self, fingerprint: str) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM tracks WHERE fingerprint = ? ORDER BY missing ASC, id ASC LIMIT 1",
                (fingerprint,),
            ).fetchone()
        return _dict(row)

    def get_track(self, track_id: int) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        return _dict(row)

    def _apply_meta(self, track_id: int, meta: dict, *, origin: str | None = None) -> None:
        fields = {
            "path": meta["path"],
            "path_key": path_key(meta["path"]),
            "filename": meta["filename"],
            "title": meta["title"],
            "artist": meta["artist"],
            "album": meta["album"],
            "genre": meta.get("genre") or "",
            "track_number": meta.get("track_number"),
            "disc_number": meta.get("disc_number"),
            "year": meta.get("year"),
            "duration": meta.get("duration") or 0,
            "file_size": meta.get("file_size") or 0,
            "mtime": meta.get("mtime") or 0,
            "artwork_path": meta.get("artwork_path"),
            "replaygain_db": meta.get("replaygain_db"),
            "replaygain_peak": meta.get("replaygain_peak"),
            "fingerprint": meta.get("fingerprint"),
            "missing": 0,
            "excluded": 0,
        }
        if origin:
            fields["origin"] = origin
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = list(fields.values()) + [track_id]
        self.conn.execute(f"UPDATE tracks SET {assignments} WHERE id = ?", values)

    def insert_track(self, meta: dict, origin: str = "scan") -> int:
        now = time.time()
        with self._tx():
            cur = self.conn.execute(
                """
                INSERT INTO tracks (
                    path, path_key, filename, title, artist, album, genre,
                    track_number, disc_number, year, duration, file_size, mtime,
                    artwork_path, date_added, replaygain_db, replaygain_peak,
                    fingerprint, origin, missing, excluded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                """,
                (
                    meta["path"],
                    path_key(meta["path"]),
                    meta["filename"],
                    meta["title"],
                    meta["artist"],
                    meta["album"],
                    meta.get("genre") or "",
                    meta.get("track_number"),
                    meta.get("disc_number"),
                    meta.get("year"),
                    meta.get("duration") or 0,
                    meta.get("file_size") or 0,
                    meta.get("mtime") or 0,
                    meta.get("artwork_path"),
                    now,
                    meta.get("replaygain_db"),
                    meta.get("replaygain_peak"),
                    meta.get("fingerprint"),
                    origin,
                ),
            )
            return int(cur.lastrowid)

    def update_track_meta(self, track_id: int, meta: dict, origin: str | None = None) -> None:
        with self._tx():
            self._apply_meta(track_id, meta, origin=origin)

    def relocate_track(self, track_id: int, meta: dict) -> None:
        """Point an existing row at a file that moved, keeping play history."""
        with self._tx():
            self._apply_meta(track_id, meta)

    def mark_missing(self, track_ids: list[int]) -> None:
        if not track_ids:
            return
        with self._tx():
            self.conn.executemany(
                "UPDATE tracks SET missing = 1 WHERE id = ?",
                [(item,) for item in track_ids],
            )

    def exclude_track(self, track_id: int) -> None:
        track = self.get_track(track_id)
        if not track:
            return
        self.add_exclusion(track["path"], "file")

    def all_library_rows(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, path, path_key, fingerprint, origin, mtime, file_size, "
                "missing, excluded, title FROM tracks"
            ).fetchall()
        return [dict(row) for row in rows]

    # ----- queries ---------------------------------------------------------

    def _where(self, **filters) -> tuple[str, list]:
        clauses = [_VISIBLE]
        args: list = []
        search = (filters.get("search") or "").strip()
        if search:
            token = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{token}%"
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' "
                "OR album LIKE ? ESCAPE '\\' OR genre LIKE ? ESCAPE '\\' "
                "OR filename LIKE ? ESCAPE '\\')"
            )
            args.extend([like, like, like, like, like])
        if filters.get("artist"):
            clauses.append("artist = ? COLLATE NOCASE")
            args.append(filters["artist"])
        if filters.get("album"):
            clauses.append("album = ? COLLATE NOCASE")
            args.append(filters["album"])
        if filters.get("favorite") is True:
            clauses.append("favorite = 1")
        if filters.get("min_plays"):
            clauses.append("play_count >= ?")
            args.append(int(filters["min_plays"]))
        if filters.get("played_only"):
            clauses.append("last_played IS NOT NULL")
        return " AND ".join(clauses), args

    def query_tracks(self, *, sort: str = "title", limit: int | None = None, **filters) -> list[dict]:
        where, args = self._where(**filters)
        order = _SORT_SQL.get(sort, _SORT_SQL["title"])
        sql = f"SELECT * FROM tracks WHERE {where} ORDER BY {order}"
        if limit:
            sql += " LIMIT ?"
            args.append(int(limit))
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def count_tracks(self) -> int:
        with self.lock:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM tracks WHERE {_VISIBLE}").fetchone()
        return int(row["n"])

    def library_stats(self) -> dict:
        with self.lock:
            row = self.conn.execute(
                f"""
                SELECT COUNT(*) AS tracks,
                       COALESCE(SUM(listen_duration), 0) AS listen,
                       COALESCE(SUM(play_count), 0) AS plays,
                       COALESCE(SUM(favorite), 0) AS favorites,
                       COUNT(DISTINCT artist) AS artists
                FROM tracks WHERE {_VISIBLE}
                """
            ).fetchone()
            albums = self.conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM (
                    SELECT 1 FROM tracks WHERE {_VISIBLE}
                    GROUP BY artist COLLATE NOCASE, album COLLATE NOCASE
                )
                """
            ).fetchone()
        data = dict(row)
        data["albums"] = int(albums["n"])
        return data

    def track_stats_map(self, track_ids: list[int]) -> dict[int, dict]:
        if not track_ids:
            return {}
        placeholders = ",".join("?" for _ in track_ids)
        with self.lock:
            rows = self.conn.execute(
                f"SELECT id, play_count, favorite, rating, last_played FROM tracks WHERE id IN ({placeholders})",
                track_ids,
            ).fetchall()
        return {row["id"]: dict(row) for row in rows}

    def artists(self, *, search: str = "", sort: str = "plays") -> list[dict]:
        where, args = self._where(search=search)
        order = {
            "plays": "plays DESC, artist COLLATE NOCASE ASC",
            "name": "artist COLLATE NOCASE ASC",
            "listen": "listen_time DESC, artist COLLATE NOCASE ASC",
        }.get(sort, "plays DESC, artist COLLATE NOCASE ASC")
        sql = f"""
            SELECT artist,
                   COUNT(*) AS track_count,
                   COUNT(DISTINCT album) AS album_count,
                   COALESCE(SUM(play_count), 0) AS plays,
                   COALESCE(SUM(listen_duration), 0) AS listen_time,
                   COALESCE(SUM(favorite), 0) AS favorites,
                   MAX(last_played) AS last_played,
                   MAX(artwork_path) AS artwork
            FROM tracks
            WHERE {where}
            GROUP BY artist COLLATE NOCASE
            ORDER BY {order}
        """
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def albums(self, *, search: str = "", artist: str | None = None, sort: str = "plays") -> list[dict]:
        filters = {"search": search}
        if artist:
            filters["artist"] = artist
        where, args = self._where(**filters)
        order = {
            "plays": "plays DESC, album COLLATE NOCASE ASC",
            "name": "album COLLATE NOCASE ASC",
            "recent": "last_played DESC",
            "year": "year DESC, album COLLATE NOCASE ASC",
        }.get(sort, "plays DESC")
        sql = f"""
            SELECT artist, album,
                   COUNT(*) AS track_count,
                   COALESCE(SUM(play_count), 0) AS plays,
                   COALESCE(SUM(listen_duration), 0) AS listen_time,
                   MAX(last_played) AS last_played,
                   MAX(artwork_path) AS artwork,
                   MAX(year) AS year
            FROM tracks
            WHERE {where}
            GROUP BY artist COLLATE NOCASE, album COLLATE NOCASE
            ORDER BY {order}
        """
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def album_tracks(self, artist: str, album: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM tracks
                WHERE {_VISIBLE} AND artist = ? COLLATE NOCASE AND album = ? COLLATE NOCASE
                ORDER BY CASE WHEN disc_number IS NULL THEN 1 ELSE 0 END, disc_number,
                         CASE WHEN track_number IS NULL THEN 1 ELSE 0 END, track_number,
                         title COLLATE NOCASE
                """,
                (artist, album),
            ).fetchall()
        return [dict(row) for row in rows]

    def album_summary(self, artist: str, album: str) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                f"""
                SELECT artist, album,
                       COUNT(*) AS track_count,
                       COALESCE(SUM(duration), 0) AS duration,
                       COALESCE(SUM(play_count), 0) AS plays,
                       COALESCE(SUM(listen_duration), 0) AS listen_time,
                       MAX(last_played) AS last_played,
                       MAX(artwork_path) AS artwork,
                       MAX(year) AS year
                FROM tracks
                WHERE {_VISIBLE} AND artist = ? COLLATE NOCASE AND album = ? COLLATE NOCASE
                GROUP BY artist COLLATE NOCASE, album COLLATE NOCASE
                """,
                (artist, album),
            ).fetchone()
        return _dict(row)

    def artist_summary(self, artist: str) -> dict | None:
        rows = self.artists()
        for row in rows:
            if (row["artist"] or "").casefold() == (artist or "").casefold():
                return row
        return None

    def set_favorite(self, track_id: int, favorite: bool) -> None:
        with self._tx():
            self.conn.execute(
                "UPDATE tracks SET favorite = ? WHERE id = ?",
                (1 if favorite else 0, track_id),
            )

    def set_rating(self, track_id: int, rating: int) -> None:
        rating = max(0, min(5, int(rating)))
        with self._tx():
            self.conn.execute("UPDATE tracks SET rating = ? WHERE id = ?", (rating, track_id))

    def set_album_favorite(self, artist: str, album: str, favorite: bool) -> None:
        artist_key = (artist or "").casefold()
        album_key = (album or "").casefold()
        with self._tx():
            if favorite:
                self.conn.execute(
                    """
                    INSERT INTO album_favorites(artist_key, album_key, artist, album, created)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(artist_key, album_key) DO UPDATE SET
                        artist = excluded.artist, album = excluded.album
                    """,
                    (artist_key, album_key, artist, album, time.time()),
                )
            else:
                self.conn.execute(
                    "DELETE FROM album_favorites WHERE artist_key = ? AND album_key = ?",
                    (artist_key, album_key),
                )

    def album_is_favorite(self, artist: str, album: str) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM album_favorites WHERE artist_key = ? AND album_key = ?",
                ((artist or "").casefold(), (album or "").casefold()),
            ).fetchone()
        return row is not None

    def favorite_albums(self) -> list[dict]:
        with self.lock:
            favs = self.conn.execute(
                "SELECT artist, album FROM album_favorites ORDER BY created DESC"
            ).fetchall()
        found = []
        for fav in favs:
            summary = self.album_summary(fav["artist"], fav["album"])
            if summary:
                summary["favorite"] = True
                found.append(summary)
        return found

    # ----- listening -------------------------------------------------------

    def add_listen_time(self, track_id: int, seconds: float, history_id: int | None = None) -> None:
        if seconds <= 0:
            return
        with self._tx():
            self.conn.execute(
                "UPDATE tracks SET listen_duration = listen_duration + ? WHERE id = ?",
                (seconds, track_id),
            )
            if history_id:
                self.conn.execute(
                    "UPDATE history SET listened = listened + ? WHERE id = ?",
                    (seconds, history_id),
                )

    def record_play(self, track_id: int, listened: float) -> int:
        now = time.time()
        with self._tx():
            self.conn.execute(
                "UPDATE tracks SET play_count = play_count + 1, last_played = ? WHERE id = ?",
                (now, track_id),
            )
            cur = self.conn.execute(
                """
                INSERT INTO history(track_id, played_at, listened, completed, skipped)
                VALUES(?, ?, ?, 0, 0)
                """,
                (track_id, now, max(0.0, listened)),
            )
            return int(cur.lastrowid)

    def mark_completed(self, history_id: int | None, track_id: int) -> None:
        with self._tx():
            self.conn.execute(
                "UPDATE tracks SET completed_listens = completed_listens + 1 WHERE id = ?",
                (track_id,),
            )
            if history_id:
                self.conn.execute(
                    "UPDATE history SET completed = 1 WHERE id = ? AND completed = 0",
                    (history_id,),
                )

    def record_skip(self, track_id: int, listened: float) -> None:
        now = time.time()
        with self._tx():
            self.conn.execute(
                "UPDATE tracks SET skip_count = skip_count + 1, last_skipped = ? WHERE id = ?",
                (now, track_id),
            )
            self.conn.execute(
                """
                INSERT INTO history(track_id, played_at, listened, completed, skipped)
                VALUES(?, ?, ?, 0, 1)
                """,
                (track_id, now, max(0.0, listened)),
            )

    def history_rows(self, limit: int = 300) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT h.id, h.track_id, h.played_at, h.listened, h.completed, h.skipped,
                       t.title, t.artist, t.album, t.path, t.artwork_path, t.duration,
                       t.missing, t.excluded
                FROM history h
                LEFT JOIN tracks t ON t.id = h.track_id
                ORDER BY h.played_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def history_since(self, since: float) -> list[dict]:
        """Listening events joined to the track fields the recommender needs."""
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT h.track_id, h.played_at, h.listened, h.completed, h.skipped,
                       t.title, t.artist, t.album, t.genre, t.duration, t.favorite
                FROM history h
                LEFT JOIN tracks t ON t.id = h.track_id
                WHERE h.played_at >= ?
                ORDER BY h.played_at ASC
                """,
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_history(self) -> None:
        """Clear listening evidence. Favorites, ratings, and the files stay."""
        with self._tx():
            self.conn.execute("DELETE FROM history")
            self.conn.execute("DELETE FROM recommendation_log")
            self.conn.execute(
                """
                UPDATE tracks SET
                    play_count = 0,
                    last_played = NULL,
                    listen_duration = 0,
                    completed_listens = 0,
                    skip_count = 0,
                    last_skipped = NULL
                """
            )

    def tracks_for_recommend(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                f"""
                SELECT id, title, artist, album, genre, duration, play_count, last_played,
                       listen_duration, completed_listens, favorite, rating, skip_count,
                       last_skipped, artwork_path, date_added
                FROM tracks WHERE {_VISIBLE}
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def log_recommendations(self, items: list[tuple[int, str]]) -> None:
        if not items:
            return
        now = time.time()
        with self._tx():
            self.conn.executemany(
                "INSERT INTO recommendation_log(track_id, section, shown_at) VALUES(?, ?, ?)",
                [(track_id, section, now) for track_id, section in items],
            )

    def recently_recommended(self, since: float) -> set[int]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT DISTINCT track_id FROM recommendation_log WHERE shown_at >= ? AND track_id IS NOT NULL",
                (since,),
            ).fetchall()
        return {row["track_id"] for row in rows}

    # ----- playlists -------------------------------------------------------

    def list_playlists(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT p.*, COUNT(i.id) AS track_count
                FROM playlists p
                LEFT JOIN playlist_items i ON i.playlist_id = p.id
                GROUP BY p.id
                ORDER BY p.name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_playlist(self, playlist_id: int) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        return _dict(row)

    def create_playlist(self, name: str) -> int:
        now = time.time()
        clean = (name or "").strip() or "New playlist"
        with self._tx():
            cur = self.conn.execute(
                "INSERT INTO playlists(name, created, updated) VALUES(?, ?, ?)",
                (clean, now, now),
            )
            return int(cur.lastrowid)

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        with self._tx():
            self.conn.execute(
                "UPDATE playlists SET name = ?, updated = ? WHERE id = ?",
                ((name or "").strip() or "Playlist", time.time(), playlist_id),
            )

    def delete_playlist(self, playlist_id: int) -> None:
        with self._tx():
            self.conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def playlist_tracks(self, playlist_id: int) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                f"""
                SELECT t.*, i.position, i.id AS item_id
                FROM playlist_items i
                JOIN tracks t ON t.id = i.track_id
                WHERE i.playlist_id = ? AND t.missing = 0 AND t.excluded = 0
                ORDER BY i.position ASC, i.id ASC
                """,
                (playlist_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_to_playlist(self, playlist_id: int, track_id: int) -> None:
        with self._tx():
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS n FROM playlist_items WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            self.conn.execute(
                "INSERT INTO playlist_items(playlist_id, track_id, position) VALUES(?, ?, ?)",
                (playlist_id, track_id, int(row["n"]) + 1),
            )
            self.conn.execute(
                "UPDATE playlists SET updated = ? WHERE id = ?",
                (time.time(), playlist_id),
            )

    def remove_from_playlist(self, item_id: int) -> None:
        with self._tx():
            self.conn.execute("DELETE FROM playlist_items WHERE id = ?", (item_id,))
