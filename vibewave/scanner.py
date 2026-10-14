"""Background library scan.

Only folders the user added are walked. The scan never starts at a drive root
on its own. .opus files are ignored before metadata is read.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from vibewave.constants import AUDIO_EXTENSIONS, OPUS_EXTENSION
from vibewave.db import Database, path_key
from vibewave.metadata import is_opus_path, read_metadata


@dataclass
class ScanState:
    running: bool = False
    phase: str = "idle"
    seen: int = 0
    total: int = 0
    added: int = 0
    updated: int = 0
    moved: int = 0
    removed: int = 0
    duplicates: int = 0
    unchanged: int = 0
    current: str = ""
    message: str = ""
    errors: list[str] = field(default_factory=list)
    _done: dict | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "phase": self.phase,
                "seen": self.seen,
                "total": self.total,
                "added": self.added,
                "updated": self.updated,
                "moved": self.moved,
                "removed": self.removed,
                "duplicates": self.duplicates,
                "current": self.current,
                "message": self.message,
                "errors": list(self.errors),
            }

    def consume_result(self) -> dict | None:
        with self._lock:
            result = self._done
            self._done = None
            return result


def _under(path: str, folder_key: str) -> bool:
    key = path_key(path)
    return key == folder_key or key.startswith(folder_key + os.sep)


def _is_excluded_dir(directory: str, folder_keys: set[str]) -> bool:
    key = path_key(directory)
    for folder in folder_keys:
        if key == folder or key.startswith(folder + os.sep):
            return True
    return False


def collect_audio_files(roots: list[str], excluded_files: set[str], excluded_folders: set[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".")
                and not _is_excluded_dir(os.path.join(dirpath, name), excluded_folders)
            ]
            if _is_excluded_dir(dirpath, excluded_folders):
                dirnames[:] = []
                continue
            for name in filenames:
                if name.startswith("._") or name.lower() in {"desktop.ini", "thumbs.db"}:
                    continue
                suffix = Path(name).suffix.lower()
                if suffix == OPUS_EXTENSION or suffix not in AUDIO_EXTENSIONS:
                    continue
                full = os.path.abspath(os.path.join(dirpath, name))
                if is_opus_path(full):
                    continue
                key = path_key(full)
                if key in excluded_files or key in seen:
                    continue
                seen.add(key)
                found.append(full)
    return found


def _same_file(row: dict, meta: dict) -> bool:
    return (
        abs(float(row["mtime"] or 0) - float(meta["mtime"])) < 0.001
        and int(row["file_size"] or 0) == int(meta["file_size"])
        and not row["missing"]
        and not row["excluded"]
    )


def scan_library(db: Database, state: ScanState) -> dict:
    """Scan configured folders. Safe to call off the UI thread."""
    folders = [row["path"] for row in db.list_folders() if row["enabled"]]
    excluded_files, excluded_folders = db.exclusion_keys()
    with state._lock:
        state.running = True
        state.phase = "walking"
        state.errors = []
        state.added = state.updated = state.moved = 0
        state.removed = state.duplicates = state.unchanged = 0
        state.seen = 0
        state.total = 0
        state.message = "Looking through your music folders"
        state._done = None

    try:
        files = collect_audio_files(folders, excluded_files, excluded_folders)
        with state._lock:
            state.total = len(files)
            state.phase = "reading"
            state.message = f"Reading {len(files)} audio files"

        seen_keys: set[str] = set()
        root_keys = [path_key(folder) for folder in folders]

        for index, file_path in enumerate(files, start=1):
            key = path_key(file_path)
            seen_keys.add(key)
            with state._lock:
                state.seen = index
                state.current = os.path.basename(file_path)
                state.message = f"Reading {index} of {len(files)}"

            existing = db.find_by_path_key(key)
            try:
                stat_mtime = os.path.getmtime(file_path)
                stat_size = os.path.getsize(file_path)
            except OSError as exc:
                with state._lock:
                    if len(state.errors) < 200:
                        state.errors.append(f"{os.path.basename(file_path)}: {exc}")
                continue
            if existing and _same_file(existing, {"mtime": stat_mtime, "file_size": stat_size}):
                with state._lock:
                    state.unchanged += 1
                continue

            meta, error = read_metadata(file_path)
            if error or meta is None:
                with state._lock:
                    if len(state.errors) < 200:
                        state.errors.append(f"{os.path.basename(file_path)}: {error or 'Unreadable'}")
                continue

            if existing:
                db.update_track_meta(existing["id"], meta, origin="scan")
                with state._lock:
                    state.updated += 1
                continue

            twin = db.find_by_fingerprint(meta["fingerprint"]) if meta.get("fingerprint") else None
            if twin and twin["path_key"] != key:
                twin_exists = os.path.exists(twin["path"])
                if twin["missing"] or not twin_exists:
                    db.relocate_track(twin["id"], meta)
                    seen_keys.add(path_key(meta["path"]))
                    with state._lock:
                        state.moved += 1
                    continue
                with state._lock:
                    state.duplicates += 1
                continue

            db.insert_track(meta, origin="scan")
            with state._lock:
                state.added += 1

        missing_ids: list[int] = []
        for row in db.all_library_rows():
            if row["excluded"]:
                continue
            if row["path_key"] in seen_keys:
                continue
            under_root = any(_under(row["path"], root) for root in root_keys)
            file_exists = os.path.exists(row["path"])
            if row["origin"] == "import" and file_exists and not under_root:
                continue
            if not file_exists or under_root or row["origin"] != "import":
                if not row["missing"]:
                    missing_ids.append(row["id"])
        db.mark_missing(missing_ids)

        result = {
            "added": state.added,
            "updated": state.updated,
            "moved": state.moved,
            "removed": len(missing_ids),
            "duplicates": state.duplicates,
            "unchanged": state.unchanged,
            "errors": list(state.errors),
            "total": len(files),
        }
        summary = (
            f"Added {result['added']}, updated {result['updated']}, "
            f"removed {result['removed']}"
        )
        if result["duplicates"]:
            summary += f", skipped {result['duplicates']} duplicates"
        if result["errors"]:
            summary += f", {len(result['errors'])} unreadable"
        with state._lock:
            state.removed = len(missing_ids)
            state.phase = "done"
            state.running = False
            state.current = ""
            state.message = summary
            state._done = result
        return result
    except Exception as exc:
        with state._lock:
            state.phase = "error"
            state.running = False
            state.message = f"Scan failed: {exc}"
            state.errors.append(str(exc))
            state._done = {"error": str(exc), "errors": list(state.errors)}
        return state._done


class LibraryScanner:
    def __init__(self, db: Database):
        self.db = db
        self.state = ScanState()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self.state.running:
            return False
        if not any(row["enabled"] for row in self.db.list_folders()):
            with self.state._lock:
                self.state.message = "Add a music folder to scan"
                self.state.phase = "idle"
            return False
        self._thread = threading.Thread(
            target=scan_library,
            args=(self.db, self.state),
            name="vibewave-scan",
            daemon=True,
        )
        self._thread.start()
        return True
