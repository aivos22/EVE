"""
The eye's "artist": it paints the eye, but decides nothing.

Every frame it reads the numbers from an EyeAnimator and draws them
with QPainter (Qt's drawing toolkit: circles, arcs, gradients...).
It never changes the animator's numbers itself.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui import theme
from ui.eye_animator import EyeAnimator

# The shape of each iris ring, outermost first (same order as animator.rings).
# Sizes are fractions of the eye's radius, so the eye scales with the window.
#   inner/outer: where the ring starts and ends, measured from the centre
#   segments:    how many curved blocks it's cut into
#   gap:         empty space between blocks, in degrees
#   push:        how far the ring moves outward when fully dilated
RING_SHAPES = [
    {"inner": 0.64, "outer": 0.80, "segments": 8,  "gap": 7, "push": 0.06},
    {"inner": 0.49, "outer": 0.60, "segments": 12, "gap": 6, "push": 0.08},
    {"inner": 0.36, "outer": 0.45, "segments": 18, "gap": 5, "push": 0.10},
    {"inner": 0.25, "outer": 0.32, "segments": 24, "gap": 4, "push": 0.11},
]
PUPIL_RADIUS = 0.19      # fraction of the eye radius
FRAME_RADIUS = 0.95      # the big outer circle from Chris's sketch
LOOK_DISTANCE = 0.10     # how far the iris can drift when looking around


def with_alpha(color: QColor, alpha: float) -> QColor:
    """Copy a colour with a new see-through-ness (alpha given as 0 to 1)."""
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class EyeWidget(QWidget):
    def __init__(self, animator: EyeAnimator, parent=None):
        super().__init__(parent)
        self.animator = animator
        # Every time the animator updates its numbers, ask Qt to repaint us.
        animator.updated.connect(self.update)
        self.setMinimumSize(200, 200)   # it grows to fill the window when the HUD is resized

    def paintEvent(self, event):
        # Qt calls this whenever the widget needs drawing.
        a = self.animator
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)  # smooth edges instead of jaggies

        centre = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 * 0.95

        # The iris (rings + pupil) drifts when looking around; the frame stays put.
        iris_centre = QPointF(centre.x() + a.look_x * LOOK_DISTANCE * radius,
                              centre.y() + a.look_y * LOOK_DISTANCE * radius)

        # During startup the rings start squeezed in and grow to full size.
        open_scale = 0.35 + 0.65 * a.opening
        # Speaking makes the whole iris swell slightly with each pulse.
        size = radius * open_scale * (1 + a.pulse * 0.05)

        self._draw_frame(p, centre, radius)

        # Blink: squash the iris flat vertically, like an eyelid closing.
        # translate/scale/translate = "squash around the iris centre, not the corner".
        p.save()
        p.translate(iris_centre)
        p.scale(1.0, 1.0 - 0.92 * a.blink)
        p.translate(-iris_centre)
        self._draw_glow(p, iris_centre, size)
        self._draw_rings(p, iris_centre, size)
        self._draw_pupil(p, iris_centre, size)
        p.restore()
        p.end()

    # --- Each layer of the eye ------------------------------------------

    def _draw_frame(self, p: QPainter, c: QPointF, r: float) -> None:
        """The big outer circle, plus small tick marks like a dial."""
        flash = self.animator.flash_level   # brighter and thicker while flashing
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(with_alpha(theme.CYAN, 0.55 + 0.45 * flash), 2 + 2 * flash))
        p.drawEllipse(c, r * FRAME_RADIUS, r * FRAME_RADIUS)
        p.setPen(QPen(with_alpha(theme.CYAN, 0.18), 1))
        p.drawEllipse(c, r * (FRAME_RADIUS - 0.04), r * (FRAME_RADIUS - 0.04))

        # 60 ticks round the edge; every 5th one is longer.
        p.setPen(QPen(with_alpha(theme.CYAN, 0.35), 1.5))
        for i in range(60):
            angle = math.radians(i * 6)
            length = 0.04 if i % 5 == 0 else 0.015
            outer = r * FRAME_RADIUS
            inner = r * (FRAME_RADIUS - length)
            p.drawLine(QPointF(c.x() + math.cos(angle) * inner, c.y() + math.sin(angle) * inner),
                       QPointF(c.x() + math.cos(angle) * outer, c.y() + math.sin(angle) * outer))

    def _draw_glow(self, p: QPainter, c: QPointF, size: float) -> None:
        """A soft cyan haze behind the iris that breathes in and out."""
        g = QRadialGradient(c, size * 0.9)
        g.setColorAt(0.0, with_alpha(theme.CYAN, 0.35 * self.animator.glow))
        g.setColorAt(0.5, with_alpha(theme.CYAN, 0.10 * self.animator.glow))
        g.setColorAt(1.0, with_alpha(theme.CYAN, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, size * 0.9, size * 0.9)

    def _draw_rings(self, p: QPainter, c: QPointF, size: float) -> None:
        """The mechanical iris: each ring is a circle cut into curved blocks."""
        a = self.animator
        fade_in = a.opening  # rings fade in during startup
        for ring, shape in zip(a.rings, RING_SHAPES):
            push = shape["push"] * ring.expand
            inner = (shape["inner"] + push) * size
            outer = (shape["outer"] + push) * size
            rotation = ring.angle + ring.twist

            step = 360 / shape["segments"]
            span = step - shape["gap"]
            for i in range(shape["segments"]):
                start = rotation + i * step
                # While flashing, every block lights up together.
                strength = max(self._block_brightness(ring, i, step, start + span / 2), a.flash_level)
                fill = with_alpha(theme.CYAN, (0.10 + 0.55 * strength) * (0.6 + 0.4 * a.glow) * fade_in)
                edge = with_alpha(theme.CYAN, (0.30 + 0.70 * strength) * fade_in)
                p.setBrush(fill)
                p.setPen(QPen(edge, 1.2))
                p.drawPath(self._block_path(c, inner, outer, start, span))

    @staticmethod
    def _block_brightness(ring, index: int, step: float, centre_angle: float) -> float:
        """
        How lit one block is, from 0 (dim) to 1 (bright). Three things add up:
        a small fixed variation per block, the drifting highlight, and any sparks.
        """
        base = 0.25 + 0.15 * ((index * 7) % 5) / 4   # same every frame, so it looks built-in

        # How far (in degrees) this block is from the ring's drifting highlight.
        distance = abs((centre_angle - ring.highlight + 180) % 360 - 180)
        highlight = 0.75 * math.exp(-(distance / 35) ** 2)

        # Sparks are stored as angles on the ring, so they turn with it.
        spark = 0.0
        local = (index + 0.5) * step
        for angle, brightness in ring.sparks:
            if abs((angle - local + 180) % 360 - 180) < step / 2:
                spark = max(spark, brightness)

        return min(1.0, base + highlight + spark * 0.8)

    @staticmethod
    def _block_path(c: QPointF, inner: float, outer: float, start: float, span: float) -> QPainterPath:
        """
        One curved block: an arc along the outside, a line in, an arc back
        along the inside, and close the shape. Angles are in degrees.
        """
        outer_box = QRectF(c.x() - outer, c.y() - outer, outer * 2, outer * 2)
        inner_box = QRectF(c.x() - inner, c.y() - inner, inner * 2, inner * 2)
        path = QPainterPath()
        path.arcMoveTo(outer_box, start)
        path.arcTo(outer_box, start, span)
        path.arcTo(inner_box, start + span, -span)
        path.closeSubpath()
        return path

    def _draw_pupil(self, p: QPainter, c: QPointF, size: float) -> None:
        """
        The glowing core, in layers: a soft halo that bleeds into the inner
        ring, a bright disc, a rim, an inner lens line and a small reflection.
        """
        a = self.animator
        r = PUPIL_RADIUS * size * a.pupil_scale
        g = a.glow
        p.setPen(Qt.NoPen)

        # 1. Halo: a big soft glow reaching out past the pupil into the inner ring.
        halo = QRadialGradient(c, r * 2.3)
        halo.setColorAt(0.0, with_alpha(theme.CYAN, 0.55 * g))
        halo.setColorAt(0.45, with_alpha(theme.CYAN, 0.22 * g))
        halo.setColorAt(1.0, with_alpha(theme.CYAN, 0.0))
        p.setBrush(halo)
        p.drawEllipse(c, r * 2.3, r * 2.3)

        # 2. The core disc: white-hot centre fading to deep cyan at the edge.
        core = QRadialGradient(c, r)
        core.setColorAt(0.0, with_alpha(QColor(235, 255, 255), 0.95))
        core.setColorAt(0.25, with_alpha(QColor(150, 245, 255), 0.85 + 0.15 * g))
        core.setColorAt(0.65, with_alpha(theme.CYAN, 0.55 + 0.3 * g))
        core.setColorAt(0.92, QColor(0, 70, 90, 230))
        core.setColorAt(1.0, QColor(0, 40, 55, 240))
        p.setBrush(core)
        p.drawEllipse(c, r, r)

        # 3. Rim and an inner "lens" line.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(with_alpha(theme.CYAN, 0.7 + 0.3 * g), 2))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(with_alpha(QColor(220, 255, 255), 0.25), 1))
        p.drawEllipse(c, r * 0.7, r * 0.7)

        # 4. A small reflection up and to the left, which makes it read as an eye.
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(QColor(255, 255, 255), 0.55))
        p.drawEllipse(QPointF(c.x() - r * 0.35, c.y() - r * 0.38), r * 0.13, r * 0.09)


if __name__ == "__main__":
    # Visual test: run  .venv\Scripts\python -m ui.eye_widget
    # Keys: 1 idle, 2 listening, 3 thinking, 4 speaking, 5 looking,
    #       B replay the startup, Esc close.
    import sys
    from PySide6.QtWidgets import QApplication
    from ui.eye_state import STATE_KEYS

    class TestWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("E.V.E. eye test  (1-5 states, B boot, Esc quit)")
            self.setStyleSheet(f"background-color: {theme.BACKGROUND.name()};")
            self.resize(700, 700)
            self.animator = EyeAnimator(self)
            self.eye = EyeWidget(self.animator, self)
            self.animator.state_changed.connect(
                lambda s: self.setWindowTitle(f"E.V.E. eye test: {s.name}"))

        def resizeEvent(self, event):
            self.eye.setGeometry(self.rect())

        def keyPressEvent(self, event):
            key = event.text().lower()
            if key in STATE_KEYS:
                self.animator.set_state(STATE_KEYS[key])
            elif key == "b":
                self.animator.restart_boot()
            elif event.key() == Qt.Key_Escape:
                self.close()

    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
