"""Walk the main screens and save PNGs. Used by VIBEWAVE_SMOKE=1."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from kivy.clock import Clock

log = logging.getLogger(__name__)
OUT = Path(__file__).resolve().parents[2] / ".smoke"


def _trace(text: str) -> None:
    with (OUT / "trace.txt").open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def run_smoke(app) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _trace("scheduled")
    root = app.root
    steps: list[tuple[float, object]] = []

    def shot(name: str):
        root.export_to_png(str(OUT / f"{name}.png"))

    def show(name: str):
        root.hide_overlays()
        root.go(name)

    steps.append((1.1, lambda: show("home")))
    steps.append((0.55, lambda: shot("01-home")))
    for index, name in enumerate(
        ("songs", "albums", "artists", "favorites", "most_played", "recent", "playlists", "visualizer", "equalizer", "recommendations", "settings", "converter"),
        start=2,
    ):
        steps.append((0.15, lambda name=name: show(name)))
        steps.append((0.5, lambda name=name, index=index: shot(f"{index:02d}-{name}")))

    def search():
        root.hide_overlays()
        root.open_search("Ava")

    def artist():
        rows = app.db.artists(sort="plays")
        if rows:
            root.open_artist(rows[0]["artist"])

    def album():
        rows = app.db.albums(sort="plays")
        if rows:
            root.open_album(rows[0]["artist"], rows[0]["album"])

    def playlist():
        rows = app.db.list_playlists()
        if rows:
            root.open_playlist(int(rows[0]["id"]))

    def now():
        root.hide_overlays()
        tracks = app.db.query_tracks(search="Glass Room", sort="title")
        tracks = [row for row in tracks if row["title"] == "Glass Room"] or app.db.query_tracks(limit=1)
        if tracks:
            app.player.set_volume(0.05)
            app.player.play_ids([int(row["id"]) for row in tracks], int(tracks[0]["id"]))
        root.show_now()

    def queue():
        root.show_queue()

    steps.append((0.2, search))
    steps.append((0.5, lambda: shot("14-search")))
    steps.append((0.15, artist))
    steps.append((0.5, lambda: shot("15-artist")))
    steps.append((0.15, album))
    steps.append((0.5, lambda: shot("16-album")))
    steps.append((0.15, playlist))
    steps.append((0.5, lambda: shot("17-playlist")))
    steps.append((0.2, now))
    steps.append((1.1, lambda: shot("18-now-playing")))
    steps.append((0.2, queue))
    steps.append((0.45, lambda: shot("19-queue")))
    steps.append((0.2, app.stop))

    class _Runner:
        """Bound-method clock callback. Nested lambdas are not kept alive by Kivy's clock."""

        def __init__(self):
            self.steps = steps
            self.index = 0
            self.left = 0.2
            self.mode = "wait"

        def pump(self, dt):
            self.left -= dt
            if self.left > 0:
                return
            if self.mode == "wait":
                if self.index >= len(self.steps):
                    app.stop()
                    return False
                self.left = self.steps[self.index][0]
                self.mode = "run"
                return
            _trace(f"step {self.index}")
            try:
                self.steps[self.index][1]()
            except Exception:
                log.exception("smoke step %s", self.index)
                (OUT / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                app.stop()
                return False
            self.index += 1
            self.left = 0.05
            self.mode = "wait"
            if self.index >= len(self.steps):
                app.stop()
                return False

    app._smoke_runner = _Runner()
    Clock.schedule_interval(app._smoke_runner.pump, 0)
