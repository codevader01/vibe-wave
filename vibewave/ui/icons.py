"""Small vector icons drawn into the current Kivy canvas.

Coordinates are a 24 by 24 grid, y pointing up. `px(gx, gy)` maps that grid
into the widget. `lw` is the stroke width in pixels.
"""

from __future__ import annotations

from kivy.graphics import Ellipse, Line, Rectangle, Triangle


def _line(points, lw):
    Line(points=points, width=lw, cap="round", joint="round")


def _poly(px, lw, pairs):
    points = []
    for gx, gy in pairs:
        x, y = px(gx, gy)
        points.extend((x, y))
    _line(points, lw)


def draw_icon(name: str, px, lw: float) -> None:
    painter = _PAINTERS.get(name, _dot)
    painter(px, lw)


def _dot(px, lw):
    x, y = px(10, 10)
    Ellipse(pos=(x, y), size=(px(14, 14)[0] - x, px(14, 14)[1] - y))


def _play(px, lw):
    x1, y1 = px(8, 5)
    x2, y2 = px(8, 19)
    x3, y3 = px(19, 12)
    Triangle(points=[x1, y1, x2, y2, x3, y3])


def _pause(px, lw):
    for gx in (7, 13):
        x, y = px(gx, 5)
        w = px(gx + 3.2, 19)[0] - x
        h = px(gx, 19)[1] - y
        Rectangle(pos=(x, y), size=(w, h))


def _stop(px, lw):
    x, y = px(6, 6)
    w = px(18, 18)[0] - x
    h = px(18, 18)[1] - y
    Rectangle(pos=(x, y), size=(w, h))


def _prev(px, lw):
    x, y = px(5, 6)
    Rectangle(pos=(x, y), size=(px(7.2, 18)[0] - x, px(5, 18)[1] - y))
    x1, y1 = px(9, 5)
    x2, y2 = px(9, 19)
    x3, y3 = px(19, 12)
    Triangle(points=[x3, y1, x2, y2, x1, y3])


def _next(px, lw):
    x1, y1 = px(5, 5)
    x2, y2 = px(15, 12)
    x3, y3 = px(5, 19)
    Triangle(points=[x1, y1, x1, y3, x2, y2])
    x, y = px(16.5, 6)
    Rectangle(pos=(x, y), size=(px(18.8, 18)[0] - x, px(16.5, 18)[1] - y))


def _heart(px, lw, filled=False):
    left = px(4.5, 10.2)
    right = px(10.5, 10.2)
    size = (px(13.5, 19)[0] - px(4.5, 10)[0], px(4.5, 19)[1] - px(4.5, 10.2)[1])
    Ellipse(pos=left, size=size)
    Ellipse(pos=right, size=size)
    a, b, c = px(5.1, 13.2), px(18.9, 13.2), px(12, 4.2)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])
    if not filled:
        # A second, smaller heart is not cut out; the stroke version is the fill.
        # Callers pick a muted color for the outline state and accent for the fill.
        return


def _home(px, lw):
    _poly(px, lw, [(3, 11), (12, 20), (21, 11)])
    _poly(px, lw, [(7, 11), (7, 4), (17, 4), (17, 11)])


def _music(px, lw):
    _poly(px, lw, [(8, 18), (16, 16.5), (16, 8)])
    _poly(px, lw, [(8, 18), (8, 9)])
    c1 = px(5, 5)
    Ellipse(pos=c1, size=(px(11, 9)[0] - c1[0], px(5, 9)[1] - c1[1]))
    c2 = px(13, 4)
    Ellipse(pos=c2, size=(px(19, 8)[0] - c2[0], px(13, 8)[1] - c2[1]))


def _album(px, lw):
    c = px(12, 12)
    Line(circle=(c[0], c[1], px(20, 12)[0] - c[0]), width=lw)
    Ellipse(pos=px(10, 10), size=(px(14, 14)[0] - px(10, 10)[0], px(10, 14)[1] - px(10, 10)[1]))


def _person(px, lw):
    head = px(8.5, 13)
    Ellipse(pos=head, size=(px(15.5, 20.5)[0] - head[0], px(8.5, 20.5)[1] - head[1]))
    _poly(px, lw, [(4.5, 5), (7.5, 11), (16.5, 11), (19.5, 5)])


def _chart(px, lw):
    for gx, gy, gw, gh in ((4, 4, 3.5, 7), (10, 4, 3.5, 12), (16, 4, 3.5, 9)):
        x, y = px(gx, gy)
        Rectangle(pos=(x, y), size=(px(gx + gw, gy)[0] - x, px(gx, gy + gh)[1] - y))


def _clock(px, lw):
    c = px(12, 12)
    Line(circle=(c[0], c[1], px(20, 12)[0] - c[0]), width=lw)
    _poly(px, lw, [(12, 12), (12, 17)])
    _poly(px, lw, [(12, 12), (16, 12)])


def _list(px, lw):
    for gy in (6, 12, 18):
        _poly(px, lw, [(4, gy), (20, gy)])
        x, y = px(4, gy - 1.1)
        Ellipse(pos=(x, y), size=(px(6.2, gy + 1.1)[0] - x, px(4, gy + 1.1)[1] - y))


def _wave(px, lw):
    points = []
    for index, gy in enumerate((12, 7, 17, 5, 19, 8, 16, 12)):
        points.append((4 + index * 2.3, gy))
    _poly(px, lw, points)


def _sliders(px, lw):
    for gx, knob in ((6, 15), (12, 8), (18, 13)):
        _poly(px, lw, [(gx, 4), (gx, 20)])
        x, y = px(gx - 2.1, knob - 2.1)
        Ellipse(pos=(x, y), size=(px(gx + 2.1, knob + 2.1)[0] - x, px(gx - 2.1, knob + 2.1)[1] - y))


def _spark(px, lw):
    _poly(px, lw, [(12, 3), (12, 21)])
    _poly(px, lw, [(3, 12), (21, 12)])
    _poly(px, lw, [(6, 6), (18, 18)])
    _poly(px, lw, [(18, 6), (6, 18)])


def _convert(px, lw):
    _poly(px, lw, [(5, 8), (5, 16), (14, 16)])
    a, b, c = px(12, 19), px(12, 13), px(18, 16)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])
    _poly(px, lw, [(19, 16), (19, 8), (10, 8)])
    a, b, c = px(12, 5), px(12, 11), px(6, 8)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])


def _settings(px, lw):
    c = px(12, 12)
    Line(circle=(c[0], c[1], px(16, 12)[0] - c[0]), width=lw)
    for gx, gy, hx, hy in (
        (12, 12, 12, 20),
        (12, 12, 12, 4),
        (12, 12, 19, 16),
        (12, 12, 5, 16),
        (12, 12, 18, 8),
        (12, 12, 6, 8),
    ):
        _poly(px, lw, [(gx, gy), (hx, hy)])


def _search(px, lw):
    c = px(10, 13)
    Line(circle=(c[0], c[1], px(16, 13)[0] - c[0]), width=lw)
    _poly(px, lw, [(14.5, 9), (20, 4)])


def _shuffle(px, lw):
    _poly(px, lw, [(4, 7), (9, 7), (15, 17), (20, 17)])
    _poly(px, lw, [(4, 17), (9, 17), (15, 7), (20, 7)])
    a, b, c = px(16, 19.5), px(16, 14.5), px(21, 17)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])
    a, b, c = px(16, 9.5), px(16, 4.5), px(21, 7)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])


def _repeat(px, lw):
    _poly(px, lw, [(7, 7), (16, 7), (16, 12)])
    _poly(px, lw, [(17, 17), (8, 17), (8, 12)])
    a, b, c = px(13, 14.5), px(13, 9.5), px(18, 12)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])
    a, b, c = px(11, 14.5), px(11, 19.5), px(6, 17)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])


def _repeat_one(px, lw):
    _repeat(px, lw)
    x, y = px(11.2, 10)
    Rectangle(pos=(x, y), size=(px(12.6, 14.5)[0] - x, px(11.2, 14.5)[1] - y))


def _volume(px, lw):
    x, y = px(4, 9)
    Rectangle(pos=(x, y), size=(px(8, 15)[0] - x, px(4, 15)[1] - y))
    a, b, c = px(8, 8), px(8, 16), px(13, 19)
    d = px(13, 5)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])
    Triangle(points=[a[0], a[1], d[0], d[1], c[0], c[1]])
    _poly(px, lw, [(16, 9), (18.5, 12), (16, 15)])


def _mute(px, lw):
    _volume(px, lw)
    _poly(px, lw, [(15, 7), (21, 17)])
    _poly(px, lw, [(21, 7), (15, 17)])


def _queue(px, lw):
    for gy in (6, 12, 18):
        _poly(px, lw, [(4, gy), (14, gy)])
    a, b, c = px(16, 8), px(16, 16), px(21, 12)
    Triangle(points=[a[0], a[1], b[0], b[1], c[0], c[1]])


def _expand(px, lw):
    _poly(px, lw, [(6, 9), (12, 15), (18, 9)])


def _chevron(px, lw):
    _poly(px, lw, [(14, 5), (8, 12), (14, 19)])


def _folder(px, lw):
    _poly(px, lw, [(3, 6), (3, 18), (10, 18), (12, 15), (21, 15), (21, 6), (3, 6)])


def _plus(px, lw):
    _poly(px, lw, [(12, 5), (12, 19)])
    _poly(px, lw, [(5, 12), (19, 12)])


def _close(px, lw):
    _poly(px, lw, [(6, 6), (18, 18)])
    _poly(px, lw, [(18, 6), (6, 18)])


def _check(px, lw):
    _poly(px, lw, [(5, 12), (10, 7), (19, 17)])


def _more(px, lw):
    for gx in (5, 12, 19):
        x, y = px(gx - 1.4, 10.6)
        Ellipse(pos=(x, y), size=(px(gx + 1.4, 13.4)[0] - x, px(gx - 1.4, 13.4)[1] - y))


def _star(px, lw):
    _poly(px, lw, [(12, 20), (14.4, 14.2), (20.5, 13.6), (16, 9.2), (17.4, 3.2), (12, 6.4), (6.6, 3.2), (8, 9.2), (3.5, 13.6), (9.6, 14.2), (12, 20)])


def _back(px, lw):
    _chevron(px, lw)


_PAINTERS = {
    "dot": _dot,
    "play": _play,
    "pause": _pause,
    "stop": _stop,
    "prev": _prev,
    "next": _next,
    "heart": lambda px, lw: _heart(px, lw, False),
    "heart_fill": lambda px, lw: _heart(px, lw, True),
    "home": _home,
    "music": _music,
    "album": _album,
    "person": _person,
    "chart": _chart,
    "clock": _clock,
    "list": _list,
    "wave": _wave,
    "sliders": _sliders,
    "spark": _spark,
    "convert": _convert,
    "settings": _settings,
    "search": _search,
    "shuffle": _shuffle,
    "repeat": _repeat,
    "repeat_one": _repeat_one,
    "volume": _volume,
    "mute": _mute,
    "queue": _queue,
    "expand": _expand,
    "chevron": _chevron,
    "folder": _folder,
    "plus": _plus,
    "close": _close,
    "check": _check,
    "more": _more,
    "star": _star,
    "star_fill": _star,
    "back": _back,
}
