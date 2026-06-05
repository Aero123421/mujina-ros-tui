from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths, DEFAULT_MOTOR_IDS
from mujina_assist.services.motors import JOINT_ORDER, MotorScanEntry, build_scan_result, validate_scan_for_real_launch
from mujina_assist.services.startup_pose import (
    load_active_startup_pose_profile,
    save_startup_pose_profile_from_scan,
    startup_pose_scan_errors,
    validate_startup_pose_profile,
)


def _scan_at(positions: list[float]):
    entries = [
        MotorScanEntry(
            joint,
            motor_id,
            responded=True,
            position_rad=position,
            velocity_rad_s=0.0,
            current_a=0.0,
            temperature_c=31.0,
            error_code="0x00",
            status="ok",
        )
        for joint, motor_id, position in zip(JOINT_ORDER, DEFAULT_MOTOR_IDS, positions)
    ]
    return build_scan_result(entries)


class StartupPoseTest(unittest.TestCase):
    def test_startup_pose_profile_allows_non_standby_real_launch_pose(self) -> None:
        startup_positions = [0.4, 0.8, -1.8, -0.4, 0.8, -1.8, 0.4, 0.8, -1.8, -0.4, 0.8, -1.8]
        scan = _scan_at(startup_positions)

        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            saved = save_startup_pose_profile_from_scan(paths, scan, upstream_commit="abc", patch_set_hash="patch")
            loaded = load_active_startup_pose_profile(paths)
            validation = validate_startup_pose_profile(
                saved,
                expected_upstream_commit="abc",
                expected_patch_set_hash="patch",
            )

            self.assertIsNotNone(loaded)
            self.assertTrue(validation.ok)
            self.assertEqual(loaded.positions_rad, startup_positions)
            self.assertEqual(
                validate_scan_for_real_launch(scan, extra_safe_poses={"startup_pose": loaded.positions_rad}),
                [],
            )

    def test_startup_pose_scan_rejects_moving_or_incomplete_robot(self) -> None:
        scan = _scan_at([0.0] * 12)
        scan.entries[0].velocity_rad_s = 0.5
        scan.entries[1].responded = False
        scan.summary = {"responded": 11, "error_count": 0}

        errors = startup_pose_scan_errors(scan)

        self.assertTrue(any("11/12" in error for error in errors))
        self.assertTrue(any("velocity" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
