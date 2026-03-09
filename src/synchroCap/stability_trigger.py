"""Stability trigger engine for auto-capture during camera calibration.

Monitors consecutive board detection success over time and triggers
capture when the board has been stable for a threshold duration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto


class Phase(Enum):
    """Internal phase of stability detection."""
    MONITORING = auto()
    COOLDOWN = auto()


@dataclass
class StabilityState:
    """Stability detection state returned by StabilityTrigger.update()."""
    triggered: bool
    phase: Phase
    stability_progress: float
    stability_elapsed: float
    cooldown_remaining: float


class StabilityTrigger:
    """Stability detection trigger engine.

    Call update(detected) every frame. When StabilityState.triggered is True,
    execute a capture.
    """

    STABILITY_THRESHOLD: float = 2.0
    COOLDOWN_DURATION: float = 3.0

    def __init__(self) -> None:
        self._phase: Phase = Phase.MONITORING
        self._stable_since: float | None = None
        self._cooldown_start: float | None = None

    def update(self, detected: bool) -> StabilityState:
        """Update state with detection result and return current state.

        Args:
            detected: Whether board detection succeeded this frame.

        Returns:
            StabilityState with current trigger status.
        """
        now = time.monotonic()

        if self._phase == Phase.COOLDOWN:
            return self._update_cooldown(now)

        return self._update_monitoring(now, detected)

    def reset(self) -> None:
        """Reset all state. Called on camera switch or tab leave."""
        self._phase = Phase.MONITORING
        self._stable_since = None
        self._cooldown_start = None

    def _update_monitoring(self, now: float, detected: bool) -> StabilityState:
        if not detected:
            self._stable_since = None
            return StabilityState(
                triggered=False,
                phase=Phase.MONITORING,
                stability_progress=0.0,
                stability_elapsed=0.0,
                cooldown_remaining=0.0,
            )

        if self._stable_since is None:
            self._stable_since = now

        elapsed = now - self._stable_since
        progress = min(elapsed / self.STABILITY_THRESHOLD, 1.0)

        if elapsed >= self.STABILITY_THRESHOLD:
            self._phase = Phase.COOLDOWN
            self._cooldown_start = now
            self._stable_since = None
            return StabilityState(
                triggered=True,
                phase=Phase.COOLDOWN,
                stability_progress=1.0,
                stability_elapsed=elapsed,
                cooldown_remaining=self.COOLDOWN_DURATION,
            )

        return StabilityState(
            triggered=False,
            phase=Phase.MONITORING,
            stability_progress=progress,
            stability_elapsed=elapsed,
            cooldown_remaining=0.0,
        )

    def _update_cooldown(self, now: float) -> StabilityState:
        elapsed = now - self._cooldown_start
        remaining = self.COOLDOWN_DURATION - elapsed

        if remaining <= 0:
            self._phase = Phase.MONITORING
            self._stable_since = None
            self._cooldown_start = None
            return StabilityState(
                triggered=False,
                phase=Phase.MONITORING,
                stability_progress=0.0,
                stability_elapsed=0.0,
                cooldown_remaining=0.0,
            )

        return StabilityState(
            triggered=False,
            phase=Phase.COOLDOWN,
            stability_progress=0.0,
            stability_elapsed=0.0,
            cooldown_remaining=remaining,
        )
