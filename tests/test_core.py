"""Core behavior that does not open a window.

These tests stay off Kivy and off PlayerController. Playback counting,
scanning, recommendations, and the equalizer are checked directly.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
import wave
from pathlib import Path

import numpy as np

from vibewave.audio.dsp import DSPChain
from vibewave.audio.spectrum import band_energies
from vibewave.constants import AUDIO_EXTENSIONS, OPUS_EXTENSION
from vibewave.converter import ConversionManager, plan_outputs
from vibewave.db import Database
from vibewave.metadata import fallback_names, is_opus_path, read_metadata
from vibewave.recommend import WEIGHTS, build_recommendations, score_track, similar_tracks
from vibewave.rules import play_threshold_seconds, should_count_play, should_mark_complete, is_skip
from vibewave.scanner import ScanState, collect_audio_files, scan_library
from vibewave.tools import ffmpeg_path


def _wav(path: Path, seconds: float = 0.35, frequency: float = 440.0, rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(rate * seconds)
    times = np.arange(frames) / rate
    samples = (0.2 * np.sin(2 * np.pi * frequency * times) * 32767).astype("<i2")
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


def _sine(frequency: float, rate: int, count: int, amplitude: float = 0.25) -> np.ndarray:
    times = np.arange(count) / rate
    mono = amplitude * np.sin(2 * np.pi * frequency * times)
    return np.column_stack((mono, mono))


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio))))


class RulesTests(unittest.TestCase):
    def test_threshold_is_thirty_or_half(self):
        self.assertEqual(play_threshold_seconds(240), 30)
        self.assertEqual(play_threshold_seconds(40), 20)
        self.assertEqual(play_threshold_seconds(0), 0)

    def test_play_is_not_counted_for_a_short_listen(self):
        self.assertFalse(should_count_play(10, 200, natural_end=False, already=False))
        self.assertTrue(should_count_play(30, 200, natural_end=False, already=False))
        self.assertFalse(should_count_play(30, 200, natural_end=False, already=True))

    def test_short_track_counts_at_halfway_or_a_real_ending(self):
        self.assertFalse(should_count_play(1.5, 8, natural_end=False, already=False))
        self.assertTrue(should_count_play(4, 8, natural_end=False, already=False))
        self.assertTrue(should_count_play(0.5, 8, natural_end=True, already=False))
        self.assertFalse(should_count_play(0.1, 8, natural_end=True, already=False))

    def test_completion_and_skip_grace(self):
        self.assertTrue(should_mark_complete(180, 200, natural_end=False, already=False))
        self.assertTrue(should_mark_complete(0.5, 200, natural_end=True, already=False))
        self.assertFalse(is_skip(1.0, 200, False))
        self.assertTrue(is_skip(8.0, 200, False))
        self.assertFalse(is_skip(40.0, 200, True))
        self.assertFalse(is_skip(40.0, 200, False))


class NameTests(unittest.TestCase):
    def test_filename_fallback(self):
        title, artist, album = fallback_names("01 - Ava Cole - Glass.mp3", "", "", "")
        self.assertEqual((title, artist, album), ("Glass", "Ava Cole", "Unknown Album"))
        title, artist, album = fallback_names("Glass.mp3", "", "", "")
        self.assertEqual((title, artist, album), ("Glass", "Unknown Artist", "Unknown Album"))

    def test_wav_metadata_uses_the_filename(self):
        folder = Path(tempfile.mkdtemp(prefix="vw-meta-"))
        try:
            path = folder / "01 - Ava Cole - Glass.wav"
            _wav(path)
            meta, error = read_metadata(str(path))
            self.assertIsNone(error)
            self.assertEqual(meta["title"], "Glass")
            self.assertEqual(meta["artist"], "Ava Cole")
            self.assertEqual(meta["album"], "Unknown Album")
            self.assertGreater(meta["duration"], 0)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_opus_is_refused_by_metadata(self):
        self.assertTrue(is_opus_path("Song.OPUS"))
        self.assertNotIn(OPUS_EXTENSION, AUDIO_EXTENSIONS)
        meta, error = read_metadata("anywhere/track.OpUs")
        self.assertIsNone(meta)
        self.assertIn("OPUS", error or "")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vw-lib-"))
        self.db = Database(self.tmp / "library.db")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scan(self) -> dict:
        return scan_library(self.db, ScanState())

    def test_opus_is_not_collected_or_kept(self):
        root = self.tmp / "music"
        _wav(root / "keep.wav")
        (root / "nested").mkdir()
        (root / "nested" / "secret.OPUS").write_bytes(b"nope")
        (root / "Other.OpUs").write_bytes(b"nope")
        found = collect_audio_files([str(root)], set(), set())
        self.assertEqual([Path(path).name for path in found], ["keep.wav"])
        self.db.insert_track(
            {
                "path": str(root / "legacy.opus"),
                "filename": "legacy.opus",
                "title": "Legacy",
                "artist": "X",
                "album": "Y",
                "duration": 10,
                "file_size": 10,
                "mtime": 1,
                "fingerprint": "opus-row",
            }
        )
        self.assertEqual(self.db.purge_opus(), 1)
        self.assertEqual(self.db.count_tracks(), 0)

    def test_scan_adds_wav_skips_garbage_and_keeps_going(self):
        root = self.tmp / "music"
        _wav(root / "good.wav")
        (root / "broken.mp3").write_bytes(b"this is not an mp3")
        self.db.add_folder(str(root))
        result = self._scan()
        self.assertEqual(result["added"], 1)
        self.assertTrue(result["errors"])
        self.assertEqual(self.db.count_tracks(), 1)
        self.assertEqual(self.db.query_tracks()[0]["title"], "good")

    def test_exclusions_skip_files_and_folders(self):
        root = self.tmp / "music"
        _wav(root / "stay.wav")
        _wav(root / "hide.wav")
        _wav(root / "skip" / "inside.wav")
        self.db.add_folder(str(root))
        self.db.add_exclusion(str(root / "hide.wav"), "file")
        self.db.add_exclusion(str(root / "skip"), "folder")
        result = self._scan()
        titles = {row["title"] for row in self.db.query_tracks()}
        self.assertEqual(titles, {"stay"})
        self.assertEqual(result["added"], 1)

    def test_duplicate_copy_is_not_a_second_track(self):
        root = self.tmp / "music"
        _wav(root / "original.wav", frequency=330)
        shutil.copy(root / "original.wav", root / "copy.wav")
        self.db.add_folder(str(root))
        result = self._scan()
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.db.count_tracks(), 1)

    def test_moved_file_keeps_its_id(self):
        root = self.tmp / "music"
        source = root / "song.wav"
        _wav(source, frequency=220)
        self.db.add_folder(str(root))
        self._scan()
        original = self.db.query_tracks()[0]
        self.db.set_favorite(original["id"], True)
        destination = root / "renamed.wav"
        os.replace(source, destination)
        self._scan()
        rows = self.db.query_tracks()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], original["id"])
        self.assertTrue(rows[0]["path"].endswith("renamed.wav"))
        self.assertEqual(rows[0]["favorite"], 1)
        self.assertEqual(self.db.get_track(original["id"])["missing"], 0)

    def test_deleted_file_is_marked_missing(self):
        root = self.tmp / "music"
        path = root / "gone.wav"
        _wav(path)
        self.db.add_folder(str(root))
        self._scan()
        track_id = self.db.query_tracks()[0]["id"]
        path.unlink()
        result = self._scan()
        self.assertEqual(result["removed"], 1)
        self.assertEqual(self.db.count_tracks(), 0)
        self.assertEqual(self.db.get_track(track_id)["missing"], 1)

    def test_removed_scan_root_hides_scan_rows_and_keeps_imports(self):
        folder_a = self.tmp / "a"
        folder_b = self.tmp / "b"
        outside = self.tmp / "imports"
        _wav(folder_a / "alpha.wav", frequency=200)
        _wav(folder_b / "beta.wav", frequency=300)
        _wav(outside / "imported.wav", frequency=400)
        id_a = self.db.add_folder(str(folder_a))
        self.db.add_folder(str(folder_b))
        self._scan()
        meta, error = read_metadata(str(outside / "imported.wav"))
        self.assertIsNone(error)
        imported_id = self.db.insert_track(meta, origin="import")
        self.db.remove_folder(self.db.list_folders()[0]["id"] if False else next(
            row["id"] for row in self.db.list_folders() if row["id"] != id_a
        ))
        self._scan()
        visible = {row["title"] for row in self.db.query_tracks()}
        self.assertIn("alpha", visible)
        self.assertIn("imported", visible)
        self.assertNotIn("beta", visible)
        beta = [row for row in self.db.all_library_rows() if row["title"] == "beta"]
        self.assertEqual(beta[0]["missing"], 1)
        self.assertEqual(self.db.get_track(imported_id)["missing"], 0)


class ListeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vw-listen-"))
        self.db = Database(self.tmp / "library.db")
        self.now = 1_700_000_000.0

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, name: str, artist: str, album: str, genre: str = "Electronic") -> int:
        return self.db.insert_track(
            {
                "path": str(self.tmp / f"{name}.wav"),
                "filename": f"{name}.wav",
                "title": name,
                "artist": artist,
                "album": album,
                "genre": genre,
                "duration": 180,
                "file_size": 1000,
                "mtime": 1,
                "fingerprint": name,
            }
        )

    def _stamp(self, track_id: int, **fields) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.db._tx():
            self.db.conn.execute(
                f"UPDATE tracks SET {assignments} WHERE id = ?",
                (*fields.values(), track_id),
            )

    def _history(self, track_id: int, played_at: float, *, listened=120, completed=1, skipped=0) -> None:
        with self.db._tx():
            self.db.conn.execute(
                """
                INSERT INTO history(track_id, played_at, listened, completed, skipped)
                VALUES(?, ?, ?, ?, ?)
                """,
                (track_id, played_at, listened, completed, skipped),
            )

    def test_album_favorite_does_not_favorite_the_song(self):
        track_id = self._add("Glass", "Ava Cole", "Neon Harbor")
        self.db.set_album_favorite("Ava Cole", "Neon Harbor", True)
        self.assertTrue(self.db.album_is_favorite("ava cole", "neon harbor"))
        self.assertEqual(self.db.get_track(track_id)["favorite"], 0)
        self.assertTrue(self.db.favorite_albums())

    def test_clear_history_keeps_favorites(self):
        track_id = self._add("Glass", "Ava Cole", "Neon Harbor")
        self.db.set_favorite(track_id, True)
        self.db.set_rating(track_id, 5)
        self._stamp(track_id, play_count=4, listen_duration=500, last_played=self.now)
        self._history(track_id, self.now)
        self.db.clear_history()
        row = self.db.get_track(track_id)
        self.assertEqual(row["favorite"], 1)
        self.assertEqual(row["rating"], 5)
        self.assertEqual(row["play_count"], 0)
        self.assertEqual(row["listen_duration"], 0)
        self.assertEqual(self.db.history_rows(), [])

    def test_new_library_says_to_play_a_few_songs(self):
        self._add("Glass", "Ava Cole", "Neon Harbor")
        sections = build_recommendations(self.db, now=self.now, log=False)
        self.assertIn("Play a few songs", sections["recommended"][0]["reason"])

    def test_recommendations_follow_the_listened_artist(self):
        glass = self._add("Glass", "Ava Cole", "Neon Harbor")
        paper = self._add("Paper", "Ava Cole", "Low Tide")
        pine = self._add("Pine", "Jonah Hale", "North Window", "Folk")
        self._stamp(
            glass,
            play_count=8,
            completed_listens=6,
            listen_duration=2400,
            last_played=self.now - 86400,
            favorite=1,
        )
        self._history(glass, self.now - 86400, listened=160, completed=1)
        self._stamp(paper, play_count=0, favorite=1, last_played=self.now - 40 * 86400)
        sections = build_recommendations(self.db, now=self.now, log=False)
        artist_names = {pack["track"]["artist"] for pack in sections["artists"]}
        self.assertEqual(artist_names, {"Ava Cole"})
        discover = {pack["track"]["title"] for pack in sections["discover"]}
        self.assertIn("Paper", discover)
        self.assertNotIn("Pine", discover)
        forgotten = {pack["track"]["title"] for pack in sections["forgotten"]}
        self.assertIn("Paper", forgotten)
        replayed = {pack["track"]["title"] for pack in sections["replayed"]}
        self.assertIn("Glass", replayed)
        self.assertNotIn(pine, {pack["track"]["id"] for pack in sections["artists"]})

    def test_showing_recommendations_lowers_the_next_score(self):
        track_id = self._add("Glass", "Ava Cole", "Neon Harbor")
        self._stamp(track_id, play_count=5, completed_listens=4, listen_duration=900, last_played=self.now, favorite=1)
        self._history(track_id, self.now)
        first = build_recommendations(self.db, now=self.now, log=True)
        second = build_recommendations(self.db, now=self.now, log=False)
        before = first["recommended"][0]["score"]
        after = second["recommended"][0]["score"]
        self.assertLess(after, before * 0.6)
        self.assertAlmostEqual(after, round(before * WEIGHTS["repeat_penalty"], 4), delta=0.02)

    def test_skip_part_is_negative_and_old_plays_decay(self):
        now = self.now
        common = {
            "play_count": 4,
            "completed_listens": 2,
            "listen_duration": 400,
            "favorite": 0,
            "rating": 0,
            "skip_count": 0,
        }
        fresh = {"id": 1, **common, "last_played": now}
        old = {"id": 2, **common, "last_played": now - 90 * 86400}
        skipped = {"id": 3, **common, "play_count": 1, "skip_count": 8, "last_played": now}
        _, fresh_parts = score_track(fresh, artist_affinity=0, album_affinity=0, genre_affinity=0, now=now, day_seed=1)
        _, old_parts = score_track(old, artist_affinity=0, album_affinity=0, genre_affinity=0, now=now, day_seed=1)
        _, skip_parts = score_track(skipped, artist_affinity=0, album_affinity=0, genre_affinity=0, now=now, day_seed=1)
        self.assertLess(skip_parts["skip"], 0)
        self.assertAlmostEqual(old_parts["recency"], fresh_parts["recency"] * 0.25, places=5)

    def test_similar_tracks_use_a_thirty_minute_window(self):
        ava = self._add("Glass", "Ava Cole", "Neon Harbor")
        jonah = self._add("Pine", "Jonah Hale", "North Window", "Folk")
        self._history(ava, self.now - 1000)
        self._history(jonah, self.now - 400)
        rows = similar_tracks(self.db, "Ava Cole", now=self.now)
        self.assertEqual(rows[0]["track"]["title"], "Pine")
        self._history(self._add("Far", "Mira Santos", "Late", "Jazz"), self.now - 8000)
        later = similar_tracks(self.db, "Ava Cole", now=self.now)
        titles = [pack["track"]["title"] for pack in later]
        self.assertEqual(titles[0], "Pine")
        self.assertNotIn("Far", titles)


class DspTests(unittest.TestCase):
    def test_flat_eq_matches_the_input(self):
        chain = DSPChain(44100)
        audio = np.random.default_rng(3).uniform(-0.4, 0.4, size=(4096, 2))
        processed = chain.process(audio)
        np.testing.assert_allclose(processed, audio, atol=1e-5)

    def test_bass_boost_lifts_low_frequencies_more_than_high(self):
        rate = 44100
        count = rate
        low = _sine(80, rate, count)
        high = _sine(8000, rate, count)
        chain_low = DSPChain(rate)
        chain_high = DSPChain(rate)
        gains = [10, 6, 2, 0, 0, 0, 0]
        chain_low.set_params(gains=gains, bass_db=6)
        chain_high.set_params(gains=gains, bass_db=6)
        skip = 2000
        low_ratio = _rms(chain_low.process(low)[skip:]) / _rms(low[skip:])
        high_ratio = _rms(chain_high.process(high)[skip:]) / _rms(high[skip:])
        self.assertGreater(low_ratio, high_ratio * 1.5)

    def test_hot_boost_stays_inside_the_clip(self):
        chain = DSPChain(44100)
        chain.set_params(gains=[12] * 7, bass_db=12, treble_db=12, preamp_db=12)
        hot = np.full((2048, 2), 0.9)
        processed = chain.process(hot)
        self.assertLessEqual(float(np.max(np.abs(processed))), 1.0)

    def test_full_left_mutes_the_right_channel(self):
        chain = DSPChain(44100)
        chain.set_params(balance=-1)
        audio = np.full((512, 2), 0.5)
        processed = chain.process(audio)
        self.assertLess(float(np.max(np.abs(processed[:, 1]))), 1e-5)
        self.assertGreater(float(np.mean(np.abs(processed[:, 0]))), 0.4)

    def test_one_kilohertz_sits_in_the_middle_bars(self):
        rate = 44100
        count = 4096
        bars = band_energies(_sine(1000, rate, count, amplitude=0.8), rate, 40)
        peak = int(np.argmax(bars))
        self.assertGreaterEqual(peak, 12)
        self.assertLessEqual(peak, 30)
        self.assertGreater(bars[peak], bars[0])
        self.assertGreater(bars[peak], bars[-1])


class ConverterTests(unittest.TestCase):
    def test_shared_names_get_a_numeric_suffix(self):
        planned = plan_outputs(
            [r"C:\videos\Song.mp4", r"C:\other\song.mkv", r"C:\third\Song.mov"],
            r"C:\out",
        )
        names = [Path(dest).name for _src, dest in planned]
        self.assertEqual(names, ["Song.mp3", "song (2).mp3", "Song (3).mp3"])

    @unittest.skipUnless(ffmpeg_path(), "ffmpeg is not on PATH")
    def test_wav_converts_to_mp3(self):
        folder = Path(tempfile.mkdtemp(prefix="vw-convert-"))
        try:
            source = folder / "take.wav"
            _wav(source, seconds=0.6, frequency=523)
            dest_dir = folder / "out"
            manager = ConversionManager()
            error = manager.start(plan_outputs([str(source)], str(dest_dir)), 128, True)
            self.assertIsNone(error)
            manager._thread.join(40)
            self.assertFalse(manager.running)
            jobs = manager.snapshot()
            self.assertEqual(jobs[0]["status"], "done", jobs[0].get("error"))
            self.assertGreater(os.path.getsize(jobs[0]["dest"]), 128)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class EngineTests(unittest.TestCase):
    @unittest.skipUnless(ffmpeg_path(), "ffmpeg is not on PATH")
    def test_quiet_playback_still_reports_position_and_spectrum(self):
        from vibewave.audio.engine import AudioEngine

        folder = Path(tempfile.mkdtemp(prefix="vw-engine-"))
        engine = AudioEngine()
        try:
            if not engine.start():
                self.skipTest(engine.error)
            path = folder / "tone.wav"
            _wav(path, seconds=1.6, frequency=880)
            engine.set_volume(0)
            engine.load(str(path), 1.6, autoplay=True)
            time.sleep(1.2)
            self.assertGreater(engine.position(), 0.05)
            self.assertGreater(float(engine.spectrum_copy().max()), 0)
        finally:
            engine.shutdown()
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
