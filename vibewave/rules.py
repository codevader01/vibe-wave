"""Playback counting rules.

Play count is based on listened time, never on seek-bar motion.
A play is counted at 30 seconds or at 50 percent of the duration, whichever
comes first. Tracks under a minute therefore count at the halfway point.
"""

from __future__ import annotations

# Accidental next-presses shorter than this are not stored as skips.
SKIP_GRACE_SECONDS = 2.0


def play_threshold_seconds(duration: float) -> float:
    """Return the listened time required before a play is counted."""
    if duration <= 0:
        return 0.0
    return min(30.0, duration * 0.5)


def should_count_play(
    listened: float,
    duration: float,
    *,
    natural_end: bool,
    already: bool,
) -> bool:
    """Return True when this playback session should increment play count once."""
    if already or duration <= 0 or listened <= 0:
        return False
    if listened >= play_threshold_seconds(duration):
        return True
    # The decoder reached the end of the file. Count it when the listener
    # actually stayed through the ending, even if the poll interval undershot
    # the threshold by a fraction of a second.
    if natural_end and listened >= min(0.5, duration):
        return True
    return False


def should_mark_complete(
    listened: float,
    duration: float,
    *,
    natural_end: bool,
    already: bool,
) -> bool:
    """A completed listen is a natural ending or at least 90 percent heard."""
    if already or duration <= 0 or listened <= 0:
        return False
    if natural_end and listened >= min(0.5, duration):
        return True
    return listened >= duration * 0.9


def is_skip(listened: float, duration: float, counted: bool) -> bool:
    """User left the track before the play threshold, after the grace period.

    Seeking inside the same track is not a skip. The caller only uses this
    when the user advances to a different track.
    """
    if counted or duration <= 0:
        return False
    if listened < SKIP_GRACE_SECONDS:
        return False
    return listened < play_threshold_seconds(duration)
