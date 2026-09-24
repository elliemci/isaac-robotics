import math
from dataclasses import dataclass, field

import numpy as np


MIN_DISTANCE = 10.0
MAX_DISTANCE = 5000.0
MAX_ELEVATION = math.pi / 2.0 - 0.02


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 1e-8 or not math.isfinite(n):
        return np.array([0.0, 1.0, 0.0], dtype=np.float64)
    return v / n


@dataclass
class OrbitCamera:
    width: int
    height: int
    target: np.ndarray = field(default_factory=lambda: np.array([-620.0, -1125.0, 121.0], dtype=np.float64))
    distance: float = 455.0
    azimuth: float = 0.0
    elevation: float = 0.34
    world_up: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0], dtype=np.float64))
    _button: int | None = None
    _last_x: float = 0.0
    _last_y: float = 0.0
    _press_x: float = 0.0
    _press_y: float = 0.0
    _dragged: bool = False

    def sanitize(self) -> None:
        if not math.isfinite(float(self.azimuth)):
            self.azimuth = 0.0
        if not math.isfinite(float(self.elevation)):
            self.elevation = 0.34
        self.elevation = max(-MAX_ELEVATION, min(MAX_ELEVATION, float(self.elevation)))
        if not math.isfinite(float(self.distance)):
            self.distance = 455.0
        self.distance = max(MIN_DISTANCE, min(MAX_DISTANCE, float(self.distance)))
        target = np.asarray(self.target, dtype=np.float64)
        if target.shape != (3,) or not np.isfinite(target).all():
            target = np.array([-620.0, -1125.0, 121.0], dtype=np.float64)
        self.target = target

    def eye(self) -> np.ndarray:
        self.sanitize()
        ce = math.cos(self.elevation)
        offset = np.array([
            math.sin(self.azimuth) * ce,
            -math.cos(self.azimuth) * ce,
            math.sin(self.elevation),
        ], dtype=np.float64) * self.distance
        return self.target + offset

    def basis(self):
        eye = self.eye()
        forward = _normalize(self.target - eye)
        right = _normalize(np.cross(forward, self.world_up))
        up = _normalize(np.cross(right, forward))
        return eye, forward, right, up

    def get_camera_xform(self) -> np.ndarray:
        eye, forward, right, up = self.basis()
        matrix = np.eye(4, dtype=np.float64)
        matrix[0, 0:3] = right
        matrix[1, 0:3] = up
        matrix[2, 0:3] = -forward
        matrix[3, 0:3] = eye
        return matrix

    def on_mouse_button_down(self, x: float, y: float, button: int) -> None:
        self._button = button
        self._last_x = self._press_x = float(x)
        self._last_y = self._press_y = float(y)
        self._dragged = False

    def on_mouse_button_up(self, x: float, y: float, button: int) -> bool:
        was_click = self._button == button and not self._dragged
        self._button = None
        self._last_x = float(x)
        self._last_y = float(y)
        return was_click

    def on_mouse_move(self, x: float, y: float) -> None:
        x = float(x)
        y = float(y)
        dx = x - self._last_x
        dy = y - self._last_y
        if abs(x - self._press_x) > 4.0 or abs(y - self._press_y) > 4.0:
            self._dragged = True
        self._last_x = x
        self._last_y = y
        if self._button is None:
            return
        if self._button == 0:
            self.orbit_delta(dx, dy)
        elif self._button == 1:
            self.pan_delta(dx, dy)
        elif self._button == 2:
            self.dolly_delta(dy)

    def orbit_delta(self, dx: float, dy: float) -> None:
        self.azimuth -= float(dx) * 0.006
        self.elevation += float(dy) * 0.006
        self.sanitize()

    def pan_delta(self, dx: float, dy: float) -> None:
        _, _, right, up = self.basis()
        scale = self.distance / max(1.0, float(self.height))
        self.target += (-right * float(dx) + up * float(dy)) * scale
        self.sanitize()

    def dolly_delta(self, dy: float) -> None:
        self.distance *= math.exp(float(dy) * 0.008)
        self.sanitize()

    def on_scroll(self, delta: float) -> None:
        self.distance *= math.exp(-float(delta) * 0.08)
        self.sanitize()

    def fit_attic(self) -> None:
        self.target = np.array([-620.0, -1125.0, 121.0], dtype=np.float64)
        self.distance = 455.0
        self.azimuth = 0.0
        self.elevation = 0.34
        self.cancel_interaction()
        self.sanitize()

    def cancel_interaction(self) -> None:
        self._button = None
        self._dragged = False
