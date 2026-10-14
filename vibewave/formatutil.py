"""Small display formatters shared by the UI and tests."""

from __future__ import annotations

import time


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        seconds = 0
    total = int(seconds + 0.5)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_listen_time(seconds: float | None) -> str:
    if not seconds or seconds < 1:
        return "0 min"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    hours = seconds / 3600
    if hours < 10:
        return f"{hours:.1f} h"
    return f"{int(round(hours))} h"


def format_added(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return time.strftime("%b %d, %Y", time.localtime(timestamp))


def format_when(timestamp: float | None) -> str:
    if not timestamp:
        return "Never"
    delta = max(0, time.time() - timestamp)
    if delta < 60:
        return "Just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)} h ago"
    if delta < 86400 * 14:
        return f"{int(delta // 86400)} d ago"
    return format_added(timestamp)
