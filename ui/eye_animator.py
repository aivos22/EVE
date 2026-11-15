"""
The eye's "brain": it decides WHAT the eye is doing, but draws nothing.

About 60 times a second it nudges a handful of numbers (ring angles,
how far each ring has pushed out, glow, pupil position...) towards the
values the current state wants. The eye widget reads those numbers and
paints them. Any other code (voice, AI) can drive the eye by calling:

    animator.set_state(EyeState.LISTENING)
    animator.set_audio_level(0.7)   # 0 = silent, 1 = loud

All values here are "normalised" (plain fractions like 0 to 1), not
pixels, so the animator doesn't care how big the eye is drawn.
"""

import math
import random

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

from ui import theme
from ui.eye_state import EyeState


def approach(current: float, target: float, rate: float, dt: float) -> float:
    """
    Move `current` smoothly towards `target`.

    `rate` is how snappy it is (bigger = faster). Using exp() makes the
    motion look the same whether the computer runs at 30 or 144 fps.
    """
    return current + (target - current) * (1 - math.exp(-rate * dt))


class Ring:
    """One ring of curved blocks in the iris. Holds only numbers."""

    def __init__(self, base_speed: float, direction: int):
        self.base_speed = base_speed  # degrees per second when idle
        self.direction = direction    # +1 clockwise, -1 anticlockwise
        self.angle = 0.0              # current rotation in degrees
        self.speed = 0.0              # current speed (smoothly changes)
        self.expand = 0.0             # 0 = resting, 1 = fully pushed outward
        self.twist = 0.0              # extra rotation used by the startup twist
        # A bright spot that drifts round the ring on its own (screen angle, degrees).
        self.highlight = random.uniform(0, 360)
        self.highlight_speed = random.choice([-1, 1]) * random.uniform(20, 45)
        # Sparks: short flashes on single blocks. Each is [angle on the ring, brightness 0-1].
        self.sparks: list[list[float]] = []


# How each state behaves. Keeping this as a table means you can tune
# E.V.E.'s personality by changing numbers instead of logic.
#   spin:   how many times faster than idle the rings turn
#   expand: how far the rings push outward (the dilation)
#   pupil:  pupil size (1 = normal)
#   glow:   base brightness of the glow (0 to 1)
STATE_SETTINGS = {
    EyeState.BOOTING:   {"spin": 0.5, "expand": 0.0, "pupil": 0.6, "glow": 0.3},
    EyeState.IDLE:      {"spin": 1.0, "expand": 0.0, "pupil": 1.0, "glow": 0.5},
    EyeState.LISTENING: {"spin": 2.5, "expand": 1.0, "pupil": 1.45, "glow": 0.8},
    EyeState.THINKING:  {"spin": 7.0, "expand": 0.3, "pupil": 0.8, "glow": 0.7},
    EyeState.SPEAKING:  {"spin": 1.5, "expand": 0.2, "pupil": 1.05, "glow": 0.7},
    EyeState.LOOKING:   {"spin": 1.2, "expand": 0.1, "pupil": 1.0, "glow": 0.6},
    EyeState.SHUTDOWN:  {"spin": 3.0, "expand": 0.0, "pupil": 0.3, "glow": 0.0},
}


class EyeAnimator(QObject):
    # A Signal is Qt's way of shouting "something happened" to anyone listening.
    updated = Signal()                 # fired every frame after the numbers change
    state_changed = Signal(EyeState)   # fired when the mood changes

    def __init__(self, parent=None):
        super().__init__(parent)

        # Four rings, outermost first. Alternate directions (+1, -1, ...)
        # so neighbouring rings turn opposite ways, like a mechanical iris.
        self.rings = [
            Ring(base_speed=6, direction=+1),
            Ring(base_speed=9, direction=-1),
            Ring(base_speed=12, direction=+1),
            Ring(base_speed=16, direction=-1),
        ]

        self.state = EyeState.BOOTING
        self.opening = 0.0       # startup: 0 = closed and twisted, 1 = fully open
        self.pupil_scale = 0.6
        self.glow = 0.0          # final glow brightness 0 to 1 (what gets drawn)
        self.pulse = 0.0         # speaking pulse 0 to 1
        self.look_x = 0.0        # pupil drift, -1 (left) to 1 (right)
        self.look_y = 0.0        # pupil drift, -1 (up) to 1 (down)
        self.blink = 0.0         # 0 = open, 1 = fully shut (mid-blink)
        self.flash_level = 0.0   # 0 = normal, 1 = flashing brightest (e.g. a timer went off)

        self._base_glow = 0.3
        self._time = 0.0                  # seconds since start, for wavy motion
        self._audio_level = 0.0           # latest volume from voice code
        self._audio_fresh_for = 0.0       # seconds the real audio level stays "fresh"
        self._look_target = (0.0, 0.0)
        self._next_look_change = 0.0
        self._gaze = (0.0, 0.0)           # where the mouse (or later a camera) wants us to look
        self._gaze_fresh_for = 0.0
        self._blink_time = -1.0           # seconds into the current blink, -1 = not blinking
        self._flash_time = -1.0           # seconds into the current flash, -1 = not flashing
        self._next_blink = random.uniform(3, 6)

        # A timer that calls _tick about 60 times a second.
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / theme.FPS))

    # --- Controls other code can use ------------------------------------

    def set_state(self, state: EyeState) -> None:
        """Change the eye's mood. The change is animated smoothly."""
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def restart_boot(self) -> None:
        """Snap the rings back to closed-and-twisted and play the startup again."""
        self.opening = 0.0
        self.set_state(EyeState.BOOTING)

    def set_gaze(self, x: float, y: float) -> None:
        """Ask the eye to look towards a point. -1..1 left/right and up/down."""
        self._gaze = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))
        self._gaze_fresh_for = 1.0   # follow it for a second unless told again

    def do_blink(self) -> None:
        """Blink right now."""
        if self._blink_time < 0:
            self._blink_time = 0.0

    def flash(self) -> None:
        """Flash brightly three times, to get sir's attention (e.g. a timer is done)."""
        self._flash_time = 0.0

    def set_audio_level(self, level: float) -> None:
        """Feed in the current voice volume (0 to 1) while speaking."""
        self._audio_level = max(0.0, min(1.0, level))
        self._audio_fresh_for = 0.5  # trust it for half a second

    # --- The animation loop ---------------------------------------------

    def _tick(self) -> None:
        # dt = seconds since the last frame (capped so a pause doesn't cause a jump)
        dt = min(self._clock.restart() / 1000.0, 0.1)
        self._time += dt
        settings = STATE_SETTINGS[self.state]

        self._update_opening(dt)
        self._update_rings(dt, settings)
        self._update_pulse(dt)
        self._update_look(dt)
        self._update_blink(dt)
        self._update_flash(dt)

        # Pupil and glow ease towards what the state wants.
        self.pupil_scale = approach(self.pupil_scale, settings["pupil"] + self.pulse * 0.15, 6, dt)
        self._base_glow = approach(self._base_glow, settings["glow"], 3, dt)
        breathing = 0.15 * math.sin(self._time * 1.2)  # slow in-and-out glow
        self.glow = max(0.0, min(1.0, self._base_glow + breathing + self.pulse * 0.3 + self.flash_level))

        self.updated.emit()

    def _update_opening(self, dt: float) -> None:
        # Open up (startup) normally; twist closed again when shutting down.
        if self.state == EyeState.SHUTDOWN:
            self.opening = approach(self.opening, 0.0, 2.0, dt)
        else:
            self.opening = approach(self.opening, 1.0, 1.2, dt)

    def _update_rings(self, dt: float, settings: dict) -> None:
        for i, ring in enumerate(self.rings):
            target_speed = ring.base_speed * settings["spin"] * ring.direction
            ring.speed = approach(ring.speed, target_speed, 3, dt)
            ring.angle = (ring.angle + ring.speed * dt) % 360

            # Inner rings push out a bit more, so the gap round the pupil opens up.
            target_expand = settings["expand"] * (0.6 + 0.4 * i / (len(self.rings) - 1))
            ring.expand = approach(ring.expand, target_expand, 5, dt)

            # Startup twist: each ring starts turned up to 180 degrees the
            # opposite way and untwists as `opening` goes from 0 to 1.
            ring.twist = (1 - self.opening) * 180 * -ring.direction

            # Drift the highlight round the ring (faster when the rings spin faster).
            ring.highlight = (ring.highlight + ring.highlight_speed * settings["spin"] ** 0.5 * dt) % 360

            # Now and then, flash a random block. Sparks fade out over about a second.
            if random.random() < dt * 0.8:
                ring.sparks.append([random.uniform(0, 360), 1.0])
            for spark in ring.sparks:
                spark[1] -= dt * 1.2
            ring.sparks = [sp for sp in ring.sparks if sp[1] > 0]

    def _update_pulse(self, dt: float) -> None:
        if self.state != EyeState.SPEAKING:
            target = 0.0
        elif self._audio_fresh_for > 0:
            target = self._audio_level  # real voice volume
        else:
            # No voice code yet: fake a talking rhythm by mixing two waves.
            target = 0.5 + 0.3 * math.sin(self._time * 9) + 0.2 * math.sin(self._time * 23)
        self._audio_fresh_for = max(0.0, self._audio_fresh_for - dt)
        self.pulse = approach(self.pulse, max(0.0, min(1.0, target)), 18, dt)

    def _update_look(self, dt: float) -> None:
        if self.state == EyeState.LOOKING:
            # Every 1 to 2.5 seconds pick a new spot to glance at.
            if self._time >= self._next_look_change:
                self._look_target = (random.uniform(-1, 1), random.uniform(-0.7, 0.7))
                self._next_look_change = self._time + random.uniform(1.0, 2.5)
            tx, ty = self._look_target
        elif self._gaze_fresh_for > 0 and self.state not in (EyeState.BOOTING, EyeState.SHUTDOWN):
            # Follow the mouse, but not all the way: 60% feels more natural.
            tx, ty = self._gaze[0] * 0.6, self._gaze[1] * 0.6
        else:
            tx, ty = 0.0, 0.0  # look straight ahead
        self._gaze_fresh_for = max(0.0, self._gaze_fresh_for - dt)
        self.look_x = approach(self.look_x, tx, 4, dt)
        self.look_y = approach(self.look_y, ty, 4, dt)


    def _update_blink(self, dt: float) -> None:
        # Every 3 to 7 seconds, blink (but not while booting).
        if self._blink_time < 0:
            self._next_blink -= dt
            if self._next_blink <= 0 and self.state not in (EyeState.BOOTING, EyeState.SHUTDOWN):
                self.do_blink()
                self._next_blink = random.uniform(3, 7)
            return
        # A blink: shut fast (0.08 s), open a little slower (0.15 s).
        self._blink_time += dt
        t = self._blink_time
        if t < 0.08:
            self.blink = t / 0.08
        elif t < 0.23:
            self.blink = 1 - (t - 0.08) / 0.15
        else:
            self.blink = 0.0
            self._blink_time = -1.0

    def _update_flash(self, dt: float) -> None:
        # Three bright pulses, 0.6 seconds each: up and down like a sine wave's hump.
        if self._flash_time < 0:
            return
        self._flash_time += dt
        if self._flash_time < 3 * 0.6:
            self.flash_level = abs(math.sin(math.pi * self._flash_time / 0.6))
        else:
            self.flash_level = 0.0
            self._flash_time = -1.0

if __name__ == "__main__":
    # Quick self-test with no window: run  .venv\Scripts\python -m ui.eye_animator
    # It walks through every state and prints the numbers, so you can see them change.
    import sys
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    animator = EyeAnimator()
    states = [EyeState.BOOTING, EyeState.IDLE, EyeState.LISTENING,
              EyeState.THINKING, EyeState.SPEAKING, EyeState.LOOKING]

    def report():
        r = animator.rings
        print(f"{animator.state.name:<10} opening={animator.opening:.2f} "
              f"pupil={animator.pupil_scale:.2f} glow={animator.glow:.2f} "
              f"pulse={animator.pulse:.2f} look=({animator.look_x:+.2f},{animator.look_y:+.2f}) "
              f"ring speeds=[{', '.join(f'{x.speed:+.0f}' for x in r)}] "
              f"expand=[{', '.join(f'{x.expand:.2f}' for x in r)}]")

    def next_state():
        if states:
            animator.set_state(states.pop(0))
        else:
            app.quit()

    printer = QTimer()
    printer.timeout.connect(report)
    printer.start(500)       # print twice a second
    switcher = QTimer()
    switcher.timeout.connect(next_state)
    switcher.start(1500)     # change state every 1.5 seconds
    next_state()
    app.exec()
