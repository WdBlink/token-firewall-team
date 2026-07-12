from __future__ import annotations

import io
import math
import tokenize
import unittest
from pathlib import Path

from server.pipeline.recovery_state import (
    InvalidEventError,
    QualityObservation,
    RecoveryConfig,
    RecoveryState,
    RecoveryStateMachine,
    RelocalizationEvidence,
)


def config(**overrides):
    values = {
        "lost_threshold": 0.1,
        "degraded_threshold": 0.4,
        "tracking_threshold": 0.7,
        "degraded_frames": 2,
        "lost_frames": 2,
        "tracking_frames": 2,
        "recovery_frames": 2,
    }
    values.update(overrides)
    return RecoveryConfig(**values)


def to_lost(machine: RecoveryStateMachine, start: int = 0) -> int:
    frame = start
    for _ in range(4):
        machine.observe_quality(QualityObservation(frame, 0.0))
        frame += 1
    if machine.state != RecoveryState.LOST:
        raise AssertionError("fixture did not reach LOST")
    return frame


class ReworkHiddenTests(unittest.TestCase):
    def assert_atomic(self, machine, action) -> None:
        state = machine.state
        history = machine.history
        with self.assertRaises(InvalidEventError):
            action()
        self.assertEqual(machine.state, state)
        self.assertEqual(machine.history, history)

    def test_inapplicable_event_wins_over_malformed_payload(self):
        machine = RecoveryStateMachine(config())
        self.assert_atomic(machine, lambda: machine.start_relocalization(-1))
        self.assert_atomic(machine, lambda: machine.observe_relocalization(object()))
        next_frame = to_lost(machine)
        self.assert_atomic(machine, lambda: machine.observe_quality(object()))
        transition = machine.start_relocalization(next_frame)
        self.assertEqual(transition.reason, "relocalization_started")

    def test_illegal_event_preserves_partial_streaks_and_cursor(self):
        machine = RecoveryStateMachine(config(degraded_frames=2))
        machine.observe_quality(QualityObservation(10, 0.0))
        self.assert_atomic(machine, lambda: machine.start_relocalization(999))
        transition = machine.observe_quality(QualityObservation(11, 0.0))
        self.assertEqual(transition.to_state, RecoveryState.DEGRADED)

        machine.observe_quality(QualityObservation(12, 0.9))
        self.assert_atomic(machine, lambda: machine.observe_relocalization(object()))
        restored = machine.observe_quality(QualityObservation(13, 0.9))
        self.assertEqual(restored.to_state, RecoveryState.TRACKING)

        machine = RecoveryStateMachine(config(recovery_frames=2))
        frame = to_lost(machine)
        machine.start_relocalization(frame)
        machine.observe_relocalization(RelocalizationEvidence(frame + 1, True, True))
        self.assert_atomic(machine, lambda: machine.observe_quality(object()))
        recovered = machine.observe_relocalization(
            RelocalizationEvidence(frame + 2, True, True)
        )
        self.assertEqual(recovered.to_state, RecoveryState.RECOVERED)

    def test_thresholds_are_finite_ordered_reals_not_quality_bounds(self):
        cfg = config(lost_threshold=-2.0, degraded_threshold=-1.0, tracking_threshold=2.0)
        self.assertEqual((cfg.lost_threshold, cfg.degraded_threshold, cfg.tracking_threshold), (-2.0, -1.0, 2.0))
        for invalid in (math.nan, math.inf, -math.inf, True, "0"):
            with self.assertRaises((TypeError, ValueError)):
                config(lost_threshold=invalid)
        machine = RecoveryStateMachine(config())
        for quality in (-0.01, 1.01):
            with self.assertRaises((TypeError, ValueError)):
                machine.observe_quality(QualityObservation(0, quality))

    def test_reset_from_every_non_tracking_state_clears_streaks(self):
        degraded = RecoveryStateMachine(config())
        degraded.observe_quality(QualityObservation(0, 0.0))
        degraded.observe_quality(QualityObservation(1, 0.0))
        self.assertEqual(degraded.reset(2).from_state, RecoveryState.DEGRADED)

        relocalizing = RecoveryStateMachine(config())
        frame = to_lost(relocalizing)
        relocalizing.start_relocalization(frame)
        relocalizing.observe_relocalization(RelocalizationEvidence(frame + 1, True, True))
        self.assertEqual(relocalizing.reset(frame + 2).from_state, RecoveryState.RELOCALIZING)
        relocalizing.observe_quality(QualityObservation(frame + 3, 0.0))
        self.assertEqual(relocalizing.state, RecoveryState.TRACKING)

        recovered = RecoveryStateMachine(config(recovery_frames=1))
        frame = to_lost(recovered)
        recovered.start_relocalization(frame)
        recovered.observe_relocalization(RelocalizationEvidence(frame + 1, True, True))
        self.assertEqual(recovered.reset(frame + 2).from_state, RecoveryState.RECOVERED)

    def test_source_has_no_semicolon_statement_packing(self):
        for relative in ("server/pipeline/recovery_state.py", "test/test_recovery_state.py"):
            source = Path(relative).read_text(encoding="utf-8")
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            semicolons = [token.start for token in tokens if token.string == ";"]
            self.assertEqual(semicolons, [], relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
