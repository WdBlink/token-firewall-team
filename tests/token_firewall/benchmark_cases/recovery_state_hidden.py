from __future__ import annotations

import ast
import math
import sys
import unittest

import server.pipeline.recovery_state as module
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
        "lost_threshold": 0.2,
        "degraded_threshold": 0.4,
        "tracking_threshold": 0.7,
        "degraded_frames": 2,
        "lost_frames": 2,
        "tracking_frames": 2,
        "recovery_frames": 3,
    }
    values.update(overrides)
    return RecoveryConfig(**values)


class HiddenRecoveryStateTests(unittest.TestCase):
    def machine(self, **overrides):
        return RecoveryStateMachine(config(**overrides))

    @staticmethod
    def observe(machine, frame_id, quality):
        return machine.observe_quality(QualityObservation(frame_id=frame_id, quality=quality))

    @staticmethod
    def evidence(machine, frame_id, geometric_ok, temporal_ok):
        return machine.observe_relocalization(
            RelocalizationEvidence(
                frame_id=frame_id,
                geometric_ok=geometric_ok,
                temporal_ok=temporal_ok,
            )
        )

    def drive_lost(self, machine, start=0):
        self.observe(machine, start, 0.39)
        self.observe(machine, start + 1, 0.39)
        self.observe(machine, start + 2, 0.2)
        self.observe(machine, start + 3, 0.2)
        self.assertEqual(machine.state, RecoveryState.LOST)
        return start + 4

    def drive_recovered(self, machine, start=0):
        frame = self.drive_lost(machine, start)
        machine.start_relocalization(frame)
        self.evidence(machine, frame + 1, True, True)
        self.evidence(machine, frame + 2, True, True)
        self.evidence(machine, frame + 3, True, True)
        self.assertEqual(machine.state, RecoveryState.RECOVERED)
        return frame + 4

    def snapshot(self, machine):
        return machine.state, tuple(item.as_dict() for item in machine.history)

    def test_h01_threshold_boundaries_and_nth_frame(self):
        machine = self.machine()
        self.assertIsNone(self.observe(machine, 0, 0.4))
        self.assertIsNone(self.observe(machine, 1, 0.39))
        transition = self.observe(machine, 2, 0.39)
        self.assertEqual((transition.from_state, transition.to_state), (RecoveryState.TRACKING, RecoveryState.DEGRADED))
        self.assertIsNone(self.observe(machine, 3, 0.2))
        transition = self.observe(machine, 4, 0.2)
        self.assertEqual(transition.to_state, RecoveryState.LOST)

        restored = self.machine()
        self.observe(restored, 0, 0.1)
        self.observe(restored, 1, 0.1)
        self.assertEqual(restored.state, RecoveryState.DEGRADED)
        self.assertIsNone(self.observe(restored, 2, 0.7))
        self.assertEqual(self.observe(restored, 3, 0.7).to_state, RecoveryState.TRACKING)

    def test_h02_hysteresis_interrupts_stale_streaks(self):
        machine = self.machine()
        self.observe(machine, 0, 0.39)
        self.observe(machine, 1, 0.6)
        self.observe(machine, 2, 0.39)
        self.assertEqual(machine.state, RecoveryState.TRACKING)
        self.observe(machine, 3, 0.39)
        self.assertEqual(machine.state, RecoveryState.DEGRADED)
        self.observe(machine, 4, 0.2)
        self.observe(machine, 5, 0.5)
        self.observe(machine, 6, 0.2)
        self.assertEqual(machine.state, RecoveryState.DEGRADED)
        self.observe(machine, 7, 0.2)
        self.assertEqual(machine.state, RecoveryState.LOST)

    def test_h03_frame_ids_are_strict_and_fail_atomically(self):
        machine = self.machine()
        self.observe(machine, 3, 0.9)
        before = self.snapshot(machine)
        for bad in (3, 2, -1, True, 1.5):
            with self.assertRaises((InvalidEventError, TypeError, ValueError)):
                self.observe(machine, bad, 0.9)
            self.assertEqual(self.snapshot(machine), before)
        self.observe(machine, 4, 0.9)

    def test_h04_directional_counters_do_not_leak(self):
        machine = self.machine(degraded_frames=2, lost_frames=2, tracking_frames=2)
        self.observe(machine, 0, 0.39)
        self.observe(machine, 1, 0.39)
        self.observe(machine, 2, 0.2)
        self.observe(machine, 3, 0.8)
        self.observe(machine, 4, 0.2)
        self.assertEqual(machine.state, RecoveryState.DEGRADED)
        self.observe(machine, 5, 0.2)
        self.assertEqual(machine.state, RecoveryState.LOST)

    def test_h05_relocalization_requires_same_frame_dual_gate_and_continuity(self):
        machine = self.machine(recovery_frames=3)
        frame = self.drive_lost(machine)
        transition = machine.start_relocalization(frame)
        self.assertEqual(transition.reason, "relocalization_started")
        self.evidence(machine, frame + 1, True, False)
        self.evidence(machine, frame + 2, False, True)
        self.evidence(machine, frame + 3, True, True)
        self.evidence(machine, frame + 4, True, True)
        self.assertEqual(machine.state, RecoveryState.RELOCALIZING)
        self.evidence(machine, frame + 5, False, False)
        self.evidence(machine, frame + 6, True, True)
        self.evidence(machine, frame + 7, True, True)
        transition = self.evidence(machine, frame + 8, True, True)
        self.assertEqual(transition.to_state, RecoveryState.RECOVERED)

    def test_h06_illegal_event_matrix_is_atomic(self):
        tracking = self.machine()
        before = self.snapshot(tracking)
        with self.assertRaises(InvalidEventError):
            tracking.start_relocalization(0)
        self.assertEqual(self.snapshot(tracking), before)
        self.observe(tracking, 0, 0.9)

        degraded = self.machine()
        self.observe(degraded, 0, 0.1)
        self.observe(degraded, 1, 0.1)
        before = self.snapshot(degraded)
        with self.assertRaises(InvalidEventError):
            degraded.start_relocalization(2)
        self.assertEqual(self.snapshot(degraded), before)
        self.observe(degraded, 2, 0.8)

        lost = self.machine()
        frame = self.drive_lost(lost)
        before = self.snapshot(lost)
        with self.assertRaises(InvalidEventError):
            self.observe(lost, frame, 0.9)
        self.assertEqual(self.snapshot(lost), before)
        lost.start_relocalization(frame)

        relocalizing = self.machine()
        frame = self.drive_lost(relocalizing)
        relocalizing.start_relocalization(frame)
        before = self.snapshot(relocalizing)
        with self.assertRaises(InvalidEventError):
            relocalizing.start_relocalization(frame + 1)
        self.assertEqual(self.snapshot(relocalizing), before)
        self.evidence(relocalizing, frame + 1, True, True)

    def test_h07_numeric_and_config_validation(self):
        for bad in (math.nan, math.inf, -math.inf, -0.01, 1.01, True, "0.5"):
            machine = self.machine()
            with self.assertRaises((InvalidEventError, TypeError, ValueError)):
                self.observe(machine, 0, bad)
            self.assertEqual(machine.state, RecoveryState.TRACKING)
            self.assertEqual(tuple(machine.history), ())
        invalid_configs = [
            {"lost_threshold": 0.4},
            {"degraded_threshold": 0.7},
            {"degraded_frames": 0},
            {"lost_frames": -1},
            {"tracking_frames": True},
            {"recovery_frames": 0},
        ]
        for values in invalid_configs:
            with self.assertRaises((TypeError, ValueError)):
                config(**values)

    def test_h08_reset_clears_streaks_without_erasing_history(self):
        machine = self.machine()
        self.observe(machine, 0, 0.39)
        self.observe(machine, 1, 0.39)
        self.observe(machine, 2, 0.2)
        before_length = len(machine.history)
        transition = machine.reset(3)
        self.assertEqual(transition.reason, "reset")
        self.assertEqual(machine.state, RecoveryState.TRACKING)
        self.assertEqual(len(machine.history), before_length + 1)
        self.observe(machine, 4, 0.39)
        self.assertEqual(machine.state, RecoveryState.TRACKING)
        self.observe(machine, 5, 0.39)
        self.assertEqual(machine.state, RecoveryState.DEGRADED)

        fresh = self.machine()
        self.assertIsNone(fresh.reset(0))
        self.assertEqual(tuple(fresh.history), ())

        relocalizing = self.machine()
        frame = self.drive_lost(relocalizing)
        relocalizing.start_relocalization(frame)
        self.evidence(relocalizing, frame + 1, True, True)
        relocalizing.reset(frame + 2)
        self.assertEqual(relocalizing.state, RecoveryState.TRACKING)

        recovered = self.machine()
        frame = self.drive_recovered(recovered)
        recovered.reset(frame)
        self.assertEqual(recovered.state, RecoveryState.TRACKING)

    def test_h09_history_and_serialization_do_not_leak_mutability(self):
        machine = self.machine()
        self.observe(machine, 0, 0.1)
        transition = self.observe(machine, 1, 0.1)
        expected = {
            "from": "TRACKING",
            "to": "DEGRADED",
            "reason": "quality_degraded",
            "frame_id": 1,
        }
        self.assertEqual(transition.as_dict(), expected)
        exported = transition.as_dict()
        exported["to"] = "CORRUPTED"
        self.assertEqual(machine.history[-1].as_dict(), expected)
        external = machine.history
        if hasattr(external, "append"):
            try:
                external.append(transition)
            except (AttributeError, TypeError):
                pass
        self.assertEqual(len(machine.history), 1)

    def test_h10_instances_and_replays_are_isolated_and_deterministic(self):
        first = self.machine()
        second = self.machine()
        self.observe(first, 0, 0.1)
        self.observe(first, 1, 0.1)
        self.assertEqual(second.state, RecoveryState.TRACKING)
        self.assertEqual(tuple(second.history), ())

        def replay():
            machine = self.machine()
            for frame, quality in enumerate((0.1, 0.1, 0.2, 0.2)):
                self.observe(machine, frame, quality)
            machine.start_relocalization(4)
            for frame in (5, 6, 7):
                self.evidence(machine, frame, True, True)
            return [item.as_dict() for item in machine.history]

        self.assertEqual(replay(), replay())

    def test_h11_module_uses_standard_library_and_no_io_primitives(self):
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        imported = set()
        aliases = {}
        forbidden_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    imported.add(root)
                    aliases[alias.asname or root] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                imported.add(root)
                for alias in node.names:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    full_name = aliases.get(node.func.id, node.func.id)
                    if full_name == "open" or full_name.startswith(("subprocess.", "socket.", "urllib.request.")):
                        forbidden_calls.add(full_name)
                elif isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        base = aliases.get(node.func.value.id, node.func.value.id)
                        full_name = f"{base}.{node.func.attr}"
                        if full_name.startswith(("subprocess.", "socket.", "urllib.request.")):
                            forbidden_calls.add(full_name)
                    if node.func.attr in {
                        "write_text", "write_bytes", "read_text", "read_bytes", "touch", "unlink", "mkdir", "rmdir"
                    }:
                        forbidden_calls.add(node.func.attr)
        non_standard = {
            name
            for name in imported
            if name != "__future__" and name not in sys.stdlib_module_names
        }
        self.assertFalse(non_standard)
        self.assertFalse(forbidden_calls)

    def test_h12_public_surface_and_state_values_are_exact(self):
        expected = {"TRACKING", "DEGRADED", "LOST", "RELOCALIZING", "RECOVERED"}
        actual = set()
        for name in expected:
            item = getattr(RecoveryState, name)
            actual.add(getattr(item, "value", item))
        self.assertEqual(actual, expected)
        for name in (
            "RecoveryConfig",
            "QualityObservation",
            "RelocalizationEvidence",
            "Transition",
            "InvalidEventError",
            "RecoveryStateMachine",
        ):
            self.assertTrue(hasattr(module, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
