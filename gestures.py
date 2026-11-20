"""Camera-independent gesture state machine. All distances are palm-normalized."""
from dataclasses import dataclass
import math


@dataclass
class Settings:
    camera: int = 0
    pinch: float = 0.26
    hold_seconds: float = 0.4
    smoothing: float = 0.065
    scroll_distance: float = 0.035
    margin: float = 0.18


@dataclass
class Hand:
    cursor: tuple[float, float]
    distances: tuple[float, float, float, float]
    scroll_pose: bool = False
    scroll_y: float = 0.5
    open_palm: bool = True

    @classmethod
    def from_landmarks(cls, points, width, height):
        # Correct the image aspect ratio before comparing finger distances.
        xy = [(p.x * width, p.y * height) for p in points]
        distance = lambda a, b: math.dist(xy[a], xy[b])
        scale = max(12.0, (distance(0, 9) + distance(5, 17)) / 2)
        # Ratios along each finger work for either hand and image rotation.
        straight = []
        folded = []
        for base in (5, 9, 13, 17):
            length = sum(distance(i, i + 1) for i in range(base, base + 3))
            ratio = distance(base, base + 3) / max(1.0, length)
            straight.append(ratio > 0.85 and distance(0, base + 3) > distance(0, base + 1) * 1.08)
            folded.append(ratio < 0.73)
        return cls(
            (points[8].x, points[8].y),
            tuple(distance(4, i) / scale for i in (8, 12, 16, 20)),
            straight[0] and straight[1] and folded[2] and folded[3],
            # Use the stable palm position for scrolling; bending fingertips
            # into the pose must not itself turn the wheel.
            sum(points[i].y for i in (0, 5, 9, 13, 17)) / 5,
            all(straight))


class GestureEngine:
    """Emit ('click'|'down'|'up', button) and ('scroll', signed detents)."""
    BUTTONS = ('left', 'right', 'middle')

    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.button = None
        self.started = 0.0
        self.held = False
        self.armed = False
        self.neutral_since = None
        self.scroll_since = None
        self.scrolling = False
        self.scroll_lost_since = None
        self.scroll_anchor = None
        self.scroll_filtered = None
        self.scroll_time = None
        self.scroll_last = -1.0
        self.blocked_pinch = False
        self.label = 'Покажите раскрытую ладонь'

    @property
    def freeze_cursor(self):
        return (self.button is not None and not self.held) or self.scroll_since is not None or self.scrolling

    def reset(self):
        events = [('up', self.button)] if self.held else []
        self.__init__(self.settings)
        return events

    def _cancel_pinch(self):
        events = [('up', self.button)] if self.held else []
        self.button = None
        self.held = False
        return events

    def update(self, hand, now):
        if hand is None:
            return self.reset()
        cfg = self.settings
        d = hand.distances
        release = cfg.pinch + 0.14
        events = []

        # Require neutral fingers on acquisition, after a pause, or after tracking loss.
        if not self.armed:
            if hand.open_palm and min(d) > release:
                if self.neutral_since is None:
                    self.neutral_since = now
                if now - self.neutral_since >= 0.16:
                    self.armed = True
            else:
                self.neutral_since = None
            self.label = 'Движение' if self.armed else 'Раскройте ладонь для начала'
            return events

        # Thumb must stay away from every fingertip: even a middle-button
        # pinch with index/middle extended cannot enter scroll mode.
        pose = hand.scroll_pose and min(d) > release + 0.05
        if self.scrolling:
            return self._scroll(hand, pose, now)

        clustered = sum(v < release for v in d) >= 3
        contacts = [i for i, value in enumerate(d[:3]) if value < cfg.pinch]
        # Several touching fingertips are a gathering gesture, not three clicks.
        if not self.held and (len(contacts) > 1 or clustered):
            events += self._cancel_pinch()
            self.blocked_pinch = True
            self.scroll_since = None
            self.label = 'Разведите пальцы перед следующим жестом'
            return events

        if self.blocked_pinch:
            if min(d[:3]) > release:
                self.blocked_pinch = False
            self.label = 'Разведите пальцы перед следующим кликом'
            return events

        # An existing pinch/drag always finishes before considering scroll.
        if self.button is None and pose:
            if self.scroll_since is None:
                self.scroll_since = now
            self.label = 'Два пальца: готовлю прокрутку…'
            if now - self.scroll_since >= 0.22:
                self.scrolling = True
                self._rebase_scroll(hand.scroll_y, now)
                self.label = 'ПРОКРУТКА · двигай руку вверх / вниз'
            return events
        self.scroll_since = None

        if self.button is not None:
            index = self.BUTTONS.index(self.button)
            if d[index] > release:
                if self.held:
                    events.append(('up', self.button))
                elif now - self.started >= 0.06:
                    events.append(('click', self.button))
                self.button = None
                self.held = False
            elif now - self.started >= cfg.hold_seconds and not self.held:
                self.held = True
                events.append(('down', self.button))
        elif len(contacts) == 1:
            self.button = self.BUTTONS[contacts[0]]
            self.started = now
        names = {'left': 'ЛКМ', 'right': 'ПКМ', 'middle': 'Средняя кнопка'}
        self.label = (f'{names[self.button]}: ' + ('зажата' if self.held else 'касание')
                      if self.button else 'Движение')
        return events

    def _rebase_scroll(self, y, now):
        self.scroll_anchor = y
        self.scroll_filtered = y
        self.scroll_time = now

    def _scroll(self, hand, pose, now):
        # No mouse buttons or cursor motion are emitted anywhere in this mode.
        if not pose:
            if self.scroll_lost_since is None:
                self.scroll_lost_since = now
            self._rebase_scroll(hand.scroll_y, now)
            self.label = 'Прокрутка остановлена · раскрой ладонь для выхода'
            if now - self.scroll_lost_since >= 0.14:
                self.reset()
                self.label = 'Раскрой ладонь: возврат к курсору'
            return []
        if self.scroll_lost_since is not None:
            self.scroll_lost_since = None
            self._rebase_scroll(hand.scroll_y, now)
            return []
        dt = max(0.001, now - self.scroll_time)
        self.scroll_time = now
        # Reject isolated landmark jumps, and never catch up old wheel ticks.
        if dt > 0.25 or abs(hand.scroll_y - self.scroll_filtered) > 0.15:
            self._rebase_scroll(hand.scroll_y, now)
            return []
        alpha = 1 - math.exp(-dt / 0.045)
        self.scroll_filtered += alpha * (hand.scroll_y - self.scroll_filtered)
        delta = self.scroll_anchor - self.scroll_filtered
        step = self.settings.scroll_distance
        count = int(abs(delta) / step)
        self.label = 'ПРОКРУТКА · вверх ↑ / вниз ↓ · раскрой ладонь для выхода'
        if count and now - self.scroll_last >= 0.075:
            signed = min(count, 3) * (1 if delta > 0 else -1)
            # Consume the full delta even when output is capped to avoid bursts.
            self.scroll_anchor -= math.copysign(count * step, delta)
            self.scroll_last = now
            return [('scroll', signed)]
        return []


class CursorFilter:
    def __init__(self):
        self.point = None
        self.time = None

    def update(self, point, now, settings):
        m = settings.margin
        target = tuple(min(1.0, max(0.0, (v - m) / (1 - 2 * m))) for v in point)
        if self.point is None:
            self.point = target
        else:
            dt = max(0.001, min(0.1, now - self.time))
            alpha = 1 - math.exp(-dt / max(0.005, settings.smoothing))
            self.point = tuple(a + alpha * (b - a) for a, b in zip(self.point, target))
        self.time = now
        return self.point
