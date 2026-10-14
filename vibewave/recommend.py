"""Local listening recommendations.

No network calls and no trained model. Scores come from play counts, finishes,
favorites, ratings, listening time, recency, skips, and artist, album, and
genre affinity. The weights below are the whole model. Change a number and the
ranking changes with it.

Score for a track
-----------------
    score =
          w_play       * log1p(play_count)
        + w_completion * completion_rate
        + w_favorite   * favorite
        + w_rating     * rating / 5
        + w_listen     * min(1, listen_seconds / listen_cap_seconds)
        + w_recency    * exp(-ln(2) * days_since_last_play / half_life_days)
        + w_artist     * artist_affinity
        + w_album      * album_affinity
        + w_genre      * genre_affinity
        + w_explore    * artist_affinity / (1 + play_count)
        + day_jitter
        - w_skip       * skip_ratio

Affinity is the listener's decayed time with that artist, album, or genre,
divided by their top artist, album, or genre. A play from `half_life_days`
ago counts half as much as a play from today, so old habits fade.

`w_explore` lifts less-played tracks by artists the listener already likes.
Tracks shown in the last two days are multiplied by `repeat_penalty` so the
same few songs do not occupy every refresh.

Skip ratio is skip_count / (skip_count + play_count). Seeking inside a song
does not create a skip. Only leaving the song early does.
"""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict

# These weights are meant to be edited.
WEIGHTS = {
    "play": 1.0,
    "completion": 1.6,
    "favorite": 2.4,
    "rating": 1.3,
    "listen": 1.1,
    "recency": 1.4,
    "artist": 2.2,
    "album": 1.5,
    "genre": 0.8,
    "skip": 2.0,
    "explore": 0.9,
    "jitter": 0.22,
    "repeat_penalty": 0.45,
    "half_life_days": 45.0,
    "listen_cap_seconds": 1200.0,
}

SECTION_ORDER = (
    ("recommended", "Recommended for You"),
    ("artists", "Based on Your Favorite Artists"),
    ("albums", "Based on Your Favorite Albums"),
    ("discover", "Discover More from Your Top Artists"),
    ("forgotten", "Forgotten Favorites"),
    ("replayed", "Frequently Replayed"),
    ("recent", "Recently Enjoyed"),
)


def _key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _decay(timestamp: float | None, now: float, half_life: float) -> float:
    if not timestamp or half_life <= 0:
        return 0.0
    age_days = max(0.0, (now - timestamp) / 86400)
    return math.exp(-math.log(2) * age_days / half_life)


def _affinity(table: dict[str, float], key: str) -> float:
    if not table or not key:
        return 0.0
    peak = max(table.values()) if table else 0
    if peak <= 0:
        return 0.0
    return max(0.0, table.get(key, 0.0) / peak)


def _profiles(tracks: list[dict], history: list[dict], now: float) -> tuple[dict, dict, dict]:
    """Build decayed artist, album, and genre weights from history."""
    half = WEIGHTS["half_life_days"]
    artist_w: dict[str, float] = defaultdict(float)
    album_w: dict[str, float] = defaultdict(float)
    genre_w: dict[str, float] = defaultdict(float)
    used_history = False
    for event in history:
        if not event.get("track_id"):
            continue
        decay = _decay(event.get("played_at"), now, half)
        if event.get("skipped"):
            magnitude = -decay * WEIGHTS["skip"] * 0.35
        else:
            listened = float(event.get("listened") or 0)
            magnitude = decay * (0.35 + min(1.0, listened / 180))
            if event.get("completed"):
                magnitude += decay * 0.45
            if event.get("favorite"):
                magnitude += decay * 0.2
        if magnitude == 0:
            continue
        used_history = True
        artist_w[_key(event.get("artist"))] += magnitude
        album_w[_key(event.get("artist")) + "\n" + _key(event.get("album"))] += magnitude
        genre = _key(event.get("genre"))
        if genre:
            genre_w[genre] += magnitude

    if used_history:
        return artist_w, album_w, genre_w

    # Before any history exists, fall back to the totals stored on each track.
    for track in tracks:
        decay = _decay(track.get("last_played"), now, half) or 0.15
        weight = decay * (
            float(track.get("play_count") or 0)
            + 2 * int(track.get("favorite") or 0)
            + float(track.get("listen_duration") or 0) / 600
        )
        if weight <= 0:
            continue
        artist_w[_key(track.get("artist"))] += weight
        album_w[_key(track.get("artist")) + "\n" + _key(track.get("album"))] += weight
        genre = _key(track.get("genre"))
        if genre:
            genre_w[genre] += weight
    return artist_w, album_w, genre_w


def score_track(
    track: dict,
    *,
    artist_affinity: float,
    album_affinity: float,
    genre_affinity: float,
    now: float,
    day_seed: int,
) -> tuple[float, dict[str, float]]:
    """Return (score, named contributions). Contributions are what the UI explains."""
    plays = float(track.get("play_count") or 0)
    completed = float(track.get("completed_listens") or 0)
    skips = float(track.get("skip_count") or 0)
    completion_rate = completed / plays if plays else 0.0
    skip_ratio = skips / (skips + plays) if (skips + plays) else 0.0
    listen_norm = min(1.0, float(track.get("listen_duration") or 0) / WEIGHTS["listen_cap_seconds"])
    recency = _decay(track.get("last_played"), now, WEIGHTS["half_life_days"])
    favorite = 1.0 if track.get("favorite") else 0.0
    rating = max(0.0, min(5.0, float(track.get("rating") or 0))) / 5
    explore = artist_affinity / (1 + plays)
    rng = random.Random((day_seed * 1_000_003) ^ int(track["id"]))
    jitter = rng.uniform(0, WEIGHTS["jitter"])

    parts = {
        "play": WEIGHTS["play"] * math.log1p(plays),
        "completion": WEIGHTS["completion"] * completion_rate,
        "favorite": WEIGHTS["favorite"] * favorite,
        "rating": WEIGHTS["rating"] * rating,
        "listen": WEIGHTS["listen"] * listen_norm,
        "recency": WEIGHTS["recency"] * recency,
        "artist": WEIGHTS["artist"] * artist_affinity,
        "album": WEIGHTS["album"] * album_affinity,
        "genre": WEIGHTS["genre"] * genre_affinity,
        "explore": WEIGHTS["explore"] * explore,
        "skip": -WEIGHTS["skip"] * skip_ratio,
        "jitter": jitter,
    }
    return sum(parts.values()), parts


def _reason(parts: dict[str, float], track: dict) -> str:
    ranked = sorted(parts.items(), key=lambda item: item[1], reverse=True)
    for name, value in ranked:
        if value <= 0:
            continue
        artist = track.get("artist") or "this artist"
        album = track.get("album") or "this album"
        genre = track.get("genre") or ""
        if name == "artist":
            return f"Because you listen to {artist}"
        if name == "album":
            return f"From {album}, an album you return to"
        if name == "favorite":
            return "One of your favorites"
        if name == "play":
            return "You play this often"
        if name == "recency":
            return "You have been playing this lately"
        if name == "explore":
            return f"Less played, by {artist}"
        if name == "genre" and genre:
            return f"Fits your {genre} listening"
        if name == "completion":
            return "You usually hear this all the way through"
        if name == "listen":
            return "You have spent real time with this song"
        if name == "rating":
            return "You rated this highly"
    return "From your library"


def _pack(track: dict, score: float, reason: str) -> dict:
    return {"track": track, "score": round(score, 4), "reason": reason}


def _top_keys(table: dict[str, float], count: int) -> list[str]:
    ordered = sorted(table.items(), key=lambda item: item[1], reverse=True)
    return [key for key, value in ordered if value > 0][:count]


def build_recommendations(
    db,
    *,
    now: float | None = None,
    exclude_ids: set[int] | None = None,
    log: bool = False,
    limit: int = 12,
) -> dict:
    """Return the recommendation sections. Pass log=True when the UI shows them."""
    now = time.time() if now is None else now
    exclude_ids = exclude_ids or set()
    tracks = db.tracks_for_recommend()
    half = WEIGHTS["half_life_days"]
    history = db.history_since(now - half * 4 * 86400)
    shown = db.recently_recommended(now - 2 * 86400)
    artist_w, album_w, genre_w = _profiles(tracks, history, now)
    day_seed = int(now // 86400)

    scored: list[tuple[float, dict, dict]] = []
    by_id: dict[int, tuple[float, dict, dict]] = {}
    for track in tracks:
        if track["id"] in exclude_ids:
            continue
        artist_key = _key(track.get("artist"))
        album_key = artist_key + "\n" + _key(track.get("album"))
        genre_key = _key(track.get("genre"))
        score, parts = score_track(
            track,
            artist_affinity=_affinity(artist_w, artist_key),
            album_affinity=_affinity(album_w, album_key),
            genre_affinity=_affinity(genre_w, genre_key),
            now=now,
            day_seed=day_seed,
        )
        if track["id"] in shown:
            score *= WEIGHTS["repeat_penalty"]
        scored.append((score, parts, track))
        by_id[track["id"]] = (score, parts, track)

    has_taste = any(value > 0 for value in artist_w.values())
    top_artists = set(_top_keys(artist_w, 5))
    top_albums = set(_top_keys(album_w, 5))

    def ranked(predicate, reason_for=None, count=limit):
        pool = []
        for score, parts, track in scored:
            if predicate(track, score, parts):
                reason = reason_for(track, parts) if reason_for else _reason(parts, track)
                pool.append((score, _pack(track, score, reason)))
        pool.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in pool[:count]]

    recommended = ranked(
        lambda track, score, parts: True,
        count=limit,
    ) if has_taste else []

    if not has_taste:
        fresh = list(tracks)
        rng = random.Random(day_seed)
        rng.shuffle(fresh)
        recommended = [
            _pack(track, 0, "Play a few songs and this list will follow your taste")
            for track in fresh[:limit]
        ]

    artists = ranked(
        lambda track, score, parts: _key(track.get("artist")) in top_artists,
        lambda track, parts: f"Because you listen to {track.get('artist')}",
    ) if top_artists else []

    albums = ranked(
        lambda track, score, parts: (
            _key(track.get("artist")) + "\n" + _key(track.get("album"))
        ) in top_albums,
        lambda track, parts: f"From {track.get('album')}, an album you play",
    ) if top_albums else []

    discover = ranked(
        lambda track, score, parts: (
            _key(track.get("artist")) in top_artists and int(track.get("play_count") or 0) <= 1
        ),
        lambda track, parts: f"Still new from {track.get('artist')}",
    ) if top_artists else []

    forgotten_pool = []
    for track in tracks:
        if not track.get("favorite"):
            continue
        last = track.get("last_played")
        age_days = (now - last) / 86400 if last else 999
        if age_days >= 21:
            forgotten_pool.append((age_days, track))
    forgotten_pool.sort(key=lambda item: item[0], reverse=True)
    forgotten = [
        _pack(track, age, "A favorite you have not played in a while")
        for age, track in forgotten_pool[:limit]
    ]

    replayed = ranked(
        lambda track, score, parts: int(track.get("play_count") or 0) >= 3,
        lambda track, parts: "You come back to this one",
    )

    recent_cutoff = now - 14 * 86400
    recent_best: dict[int, dict] = {}
    for event in history:
        if event.get("skipped") or not event.get("track_id"):
            continue
        if (event.get("played_at") or 0) < recent_cutoff:
            continue
        if int(event.get("completed") or 0) != 1 and float(event.get("listened") or 0) < 30:
            continue
        current = recent_best.get(event["track_id"])
        if current is None or event["played_at"] > current["played_at"]:
            recent_best[event["track_id"]] = event
    recent_ids = sorted(recent_best.values(), key=lambda item: item["played_at"], reverse=True)
    track_by_id = {track["id"]: track for track in tracks}
    recent = []
    for event in recent_ids[:limit]:
        track = track_by_id.get(event["track_id"])
        if not track:
            continue
        recent.append(_pack(track, event["played_at"], "You finished this recently"))

    sections = {
        "recommended": recommended,
        "artists": artists,
        "albums": albums,
        "discover": discover,
        "forgotten": forgotten,
        "replayed": replayed,
        "recent": recent,
    }
    if log:
        logged = []
        for name, rows in sections.items():
            for row in rows:
                logged.append((row["track"]["id"], name))
        db.log_recommendations(logged)
    return sections


def similar_tracks(db, artist: str, *, limit: int = 12, now: float | None = None) -> list[dict]:
    """Tracks that show up in the same listening sessions as this artist.

    A session is a pair of history rows within 30 minutes. When that evidence
    is thin, tracks that share a genre with this artist fill the rest.
    """
    now = time.time() if now is None else now
    artist_key = _key(artist)
    history = db.history_since(now - 180 * 86400)
    own_times = [
        event["played_at"]
        for event in history
        if _key(event.get("artist")) == artist_key and event.get("played_at") and not event.get("skipped")
    ]
    counts: dict[int, float] = defaultdict(float)
    for event in history:
        if event.get("skipped") or not event.get("track_id") or not event.get("played_at"):
            continue
        if _key(event.get("artist")) == artist_key:
            continue
        for moment in own_times:
            gap = abs(event["played_at"] - moment)
            if gap <= 1800:
                counts[event["track_id"]] += 1.0 / (1 + gap / 600)
                break
    tracks = db.tracks_for_recommend()
    by_id = {track["id"]: track for track in tracks}
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    results = []
    used = set()
    for track_id, weight in ranked:
        track = by_id.get(track_id)
        if not track:
            continue
        results.append(_pack(track, weight, f"Often played around {artist}"))
        used.add(track_id)
        if len(results) >= limit:
            return results

    genres = {
        _key(track.get("genre"))
        for track in tracks
        if _key(track.get("artist")) == artist_key and _key(track.get("genre"))
    }
    if genres:
        for track in tracks:
            if track["id"] in used or _key(track.get("artist")) == artist_key:
                continue
            if _key(track.get("genre")) in genres:
                results.append(_pack(track, 0.1, f"Shares a genre with {artist}"))
                if len(results) >= limit:
                    break
    return results
