from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import DEFAULT_MOTOR_IDS
from mujina_assist.services.motors import (
    JOINT_ORDER,
    MotorScanEntry,
    build_scan_result,
    default_motor_descriptors,
    load_scan_result,
    parse_probe_output,
    save_scan_result,
    validate_scan_for_real_launch,
    validate_scan_for_zero,
)


class MotorsServiceTest(unittest.TestCase):
    def test_default_motor_descriptors_match_mujina_joint_order(self) -> None:
        descriptors = default_motor_descriptors()

        self.assertEqual([descriptor.motor_id for descriptor in descriptors], DEFAULT_MOTOR_IDS)
        self.assertEqual([descriptor.joint_name for descriptor in descriptors], JOINT_ORDER)
        self.assertEqual(descriptors[0].leg, "RL")
        self.assertEqual(descriptors[-1].joint_name, "FR_knee_joint")

    def test_scan_result_summary_and_json_round_trip(self) -> None:
        entries = [
            MotorScanEntry("RL_collar_joint", 10, responded=True, temperature_c=32.5, error_code="0x00", status="ok"),
            MotorScanEntry("RL_hip_joint", 11, responded=False, status="timeout"),
        ]
        result = build_scan_result(entries, created_at="2026-04-30T10:00:00+09:00")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.json"
            save_scan_result(path, result)
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded = load_scan_result(path)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["summary"]["responded"], 1)
        self.assertEqual(payload["summary"]["timeouts"], 1)
        self.assertFalse(payload["summary"]["ok"])
        self.assertEqual(loaded.entries[0].temperature_c, 32.5)

    def test_parse_probe_output_maps_motor_ids_to_joint_names(self) -> None:
        output = """# motor ids: [10, 11]
motor 10: pos=-0.003 vel=0.000 cur=0.100 temp=32.1
motor 11: pos=0.002 vel=0.001 cur=0.200 temp=31.9
"""
        entries = parse_probe_output(output)

        self.assertEqual(entries[0].joint_name, "RL_collar_joint")
        self.assertTrue(entries[0].responded)
        self.assertEqual(entries[0].position_rad, -0.003)
        self.assertEqual(entries[1].motor_id, 11)
        self.assertEqual(entries[2].status, "timeout")

    def test_validate_scan_for_real_launch_requires_all_axes_stationary(self) -> None:
        entries = [
            MotorScanEntry(joint, motor_id, responded=True, position_rad=0.0, velocity_rad_s=0.0, temperature_c=31.0, error_code="0x00", status="ok")
            for joint, motor_id in zip(JOINT_ORDER, DEFAULT_MOTOR_IDS)
        ]
        result = build_scan_result(entries)

        self.assertEqual(validate_scan_for_real_launch(result), [])

        entries[0].velocity_rad_s = 1.0
        result = build_scan_result(entries)

        self.assertTrue(validate_scan_for_real_launch(result))

    def test_validate_scan_for_zero_checks_only_target_axes_with_tighter_velocity(self) -> None:
        entries = [
            MotorScanEntry(joint, motor_id, responded=True, position_rad=0.0, velocity_rad_s=0.0, temperature_c=31.0, error_code="0x00", status="ok")
            for joint, motor_id in zip(JOINT_ORDER, DEFAULT_MOTOR_IDS)
        ]
        result = build_scan_result(entries)

        self.assertEqual(validate_scan_for_zero(result, [DEFAULT_MOTOR_IDS[0]]), [])

        entries[0].velocity_rad_s = 0.021
        entries[1].error_code = "0x10"
        result = build_scan_result(entries)

        errors = validate_scan_for_zero(result, [DEFAULT_MOTOR_IDS[0]])

        self.assertEqual(len(errors), 1)
        self.assertIn("velocity", errors[0])

    def test_validate_scan_for_zero_blocks_error_code_temperature_and_missing_response(self) -> None:
        entries = [
            MotorScanEntry("RL_collar_joint", 10, responded=True, velocity_rad_s=0.0, temperature_c=71.0, error_code="0x00", status="ok"),
            MotorScanEntry("RL_hip_joint", 11, responded=True, velocity_rad_s=0.0, temperature_c=31.0, error_code="0x01", status="ok"),
            MotorScanEntry("RL_knee_joint", 12, responded=False, status="timeout"),
        ]
        result = build_scan_result(entries)

        errors = validate_scan_for_zero(result, [10, 11, 12])

        self.assertTrue(any("temperature" in error for error in errors))
        self.assertTrue(any("error_code" in error for error in errors))
        self.assertTrue(any("応答していません" in error for error in errors))

    def test_parse_probe_output_accepts_upstream_probe_format(self) -> None:
        output = "Motor 10 Position: -0.003, Velocity: 0.0, Torque: 0.1, Temp: 32.1\n"

        entries = parse_probe_output(output)

        self.assertTrue(entries[0].responded)
        self.assertEqual(entries[0].position_rad, -0.003)
        self.assertEqual(entries[0].current_a, 0.1)

    def test_parse_probe_output_accepts_jsonl(self) -> None:
        output = (
            '{"event": "motor_probe", "motor_id": 10, "position_rad": -0.004, '
            '"velocity_rad_s": 0.0, "current_a": 0.1, "temperature_c": 32.1, '
            '"error_code": "0x00", "status": "ok"}\n'
        )

        entries = parse_probe_output(output)

        self.assertTrue(entries[0].responded)
        self.assertEqual(entries[0].position_rad, -0.004)
        self.assertEqual(entries[0].temperature_c, 32.1)


if __name__ == "__main__":
    unittest.main()
