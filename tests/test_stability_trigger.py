"""Unit tests for StabilityTrigger."""

from unittest.mock import patch

import pytest

from stability_trigger import Phase, StabilityState, StabilityTrigger


class TestStabilityTriggerMonitoring:
    """Tests for the MONITORING phase."""

    def test_initial_state_no_detection(self):
        """Detection failure returns non-triggered MONITORING state."""
        trigger = StabilityTrigger()
        state = trigger.update(False)

        assert state.triggered is False
        assert state.phase == Phase.MONITORING
        assert state.stability_progress == 0.0
        assert state.stability_elapsed == 0.0
        assert state.cooldown_remaining == 0.0

    def test_first_detection_starts_tracking(self):
        """First detection success starts stability tracking with zero elapsed."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            state = trigger.update(True)

        assert state.triggered is False
        assert state.phase == Phase.MONITORING
        assert state.stability_elapsed == 0.0
        assert state.stability_progress == 0.0

    def test_stability_progress_increases(self):
        """Progress increases as detection continues."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)

        with patch("stability_trigger.time.monotonic", return_value=101.0):
            state = trigger.update(True)

        assert state.triggered is False
        assert state.phase == Phase.MONITORING
        assert state.stability_elapsed == pytest.approx(1.0)
        assert state.stability_progress == pytest.approx(0.5)

    def test_detection_failure_resets_tracking(self):
        """Detection failure resets stability tracking."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)

        with patch("stability_trigger.time.monotonic", return_value=101.0):
            trigger.update(True)

        # Failure resets
        state = trigger.update(False)
        assert state.triggered is False
        assert state.stability_elapsed == 0.0
        assert state.stability_progress == 0.0

    def test_trigger_at_threshold(self):
        """Trigger fires when stability threshold is reached."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)

        with patch("stability_trigger.time.monotonic", return_value=102.0):
            state = trigger.update(True)

        assert state.triggered is True
        assert state.phase == Phase.COOLDOWN
        assert state.stability_progress == 1.0
        assert state.stability_elapsed == pytest.approx(2.0)
        assert state.cooldown_remaining == pytest.approx(3.0)

    def test_trigger_past_threshold(self):
        """Trigger fires when elapsed exceeds threshold."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)

        with patch("stability_trigger.time.monotonic", return_value=102.5):
            state = trigger.update(True)

        assert state.triggered is True
        assert state.stability_elapsed == pytest.approx(2.5)


class TestStabilityTriggerCooldown:
    """Tests for the COOLDOWN phase."""

    def _trigger_once(self, trigger: StabilityTrigger) -> None:
        """Helper to trigger once and enter cooldown."""
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)
        with patch("stability_trigger.time.monotonic", return_value=102.0):
            trigger.update(True)

    def test_cooldown_blocks_trigger(self):
        """During cooldown, no trigger fires even with detection success."""
        trigger = StabilityTrigger()
        self._trigger_once(trigger)

        with patch("stability_trigger.time.monotonic", return_value=103.0):
            state = trigger.update(True)

        assert state.triggered is False
        assert state.phase == Phase.COOLDOWN
        assert state.cooldown_remaining == pytest.approx(2.0)

    def test_cooldown_remaining_decreases(self):
        """Cooldown remaining decreases over time."""
        trigger = StabilityTrigger()
        self._trigger_once(trigger)

        with patch("stability_trigger.time.monotonic", return_value=104.0):
            state = trigger.update(True)

        assert state.cooldown_remaining == pytest.approx(1.0)

    def test_cooldown_ends_returns_to_monitoring(self):
        """Cooldown ends and returns to MONITORING."""
        trigger = StabilityTrigger()
        self._trigger_once(trigger)

        with patch("stability_trigger.time.monotonic", return_value=105.0):
            state = trigger.update(True)

        assert state.triggered is False
        assert state.phase == Phase.MONITORING
        assert state.cooldown_remaining == 0.0
        assert state.stability_elapsed == 0.0

    def test_second_trigger_after_cooldown(self):
        """Can trigger again after cooldown completes."""
        trigger = StabilityTrigger()
        self._trigger_once(trigger)

        # Cooldown ends at 105.0
        with patch("stability_trigger.time.monotonic", return_value=105.0):
            trigger.update(True)

        # Start new stability tracking
        with patch("stability_trigger.time.monotonic", return_value=105.1):
            state = trigger.update(True)
        assert state.triggered is False
        assert state.phase == Phase.MONITORING

        # Reach threshold again
        with patch("stability_trigger.time.monotonic", return_value=107.1):
            state = trigger.update(True)
        assert state.triggered is True
        assert state.phase == Phase.COOLDOWN

    def test_cooldown_not_affected_by_detection_failure(self):
        """Detection failure during cooldown doesn't affect cooldown."""
        trigger = StabilityTrigger()
        self._trigger_once(trigger)

        with patch("stability_trigger.time.monotonic", return_value=103.0):
            state = trigger.update(False)

        assert state.phase == Phase.COOLDOWN
        assert state.cooldown_remaining == pytest.approx(2.0)


class TestStabilityTriggerReset:
    """Tests for the reset() method."""

    def test_reset_from_monitoring(self):
        """Reset from MONITORING clears tracking."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)

        trigger.reset()

        with patch("stability_trigger.time.monotonic", return_value=101.0):
            state = trigger.update(True)

        # Should start fresh - elapsed is 0 because _stable_since was just set
        assert state.triggered is False
        assert state.phase == Phase.MONITORING
        assert state.stability_elapsed == 0.0

    def test_reset_from_cooldown(self):
        """Reset from COOLDOWN returns to MONITORING."""
        trigger = StabilityTrigger()
        with patch("stability_trigger.time.monotonic", return_value=100.0):
            trigger.update(True)
        with patch("stability_trigger.time.monotonic", return_value=102.0):
            trigger.update(True)

        trigger.reset()

        with patch("stability_trigger.time.monotonic", return_value=102.5):
            state = trigger.update(True)

        assert state.triggered is False
        assert state.phase == Phase.MONITORING
