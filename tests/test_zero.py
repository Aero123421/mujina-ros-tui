from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths
from mujina_assist.services.motors import MotorScanEntry, build_scan_result
from mujina_assist.services.zero import (
    load_active_zero_profile,
    new_zero_profile,
    save_verified_zero_profile_from_scan,
    save_zero_profile,
    validate_zero_profile,
)


class ZeroProfileTest(unittest.TestCase):
    def test_save_load_and_validate_zero_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            profile = new_zero_profile(
                upstream_commit="abc",
                result="verified",
                operator_confirmed=True,
                post_zero_max_abs_position_rad=0.02,
            )

            saved = save_zero_profile(paths, profile)
            loaded = load_active_zero_profile(paths)
            result = validate_zero_profile(loaded, expected_upstream_commit="abc")

            self.assertTrue(saved.exists())
            self.assertIsNotNone(loaded)
            self.assertTrue(result.ok)

    def test_new_zero_profile_defaults_to_unverified_pending(self) -> None:
        profile = new_zero_profile()

        self.assertEqual(profile.result, "pending")
        self.assertFalse(profile.operator_confirmed)
        self.assertEqual(profile.post_zero_max_abs_position_rad, 999.0)

    def test_save_verified_zero_profile_from_scan_activates_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            entries = [
                MotorScanEntry(joint, motor_id, responded=True, position_rad=0.01, error_code="0x00", status="ok")
                for joint, motor_id in zip(
                    [
                        "RL_collar_joint",
                        "RL_hip_joint",
                        "RL_knee_joint",
                        "RR_collar_joint",
                        "RR_hip_joint",
                        "RR_knee_joint",
                        "FL_collar_joint",
                        "FL_hip_joint",
                        "FL_knee_joint",
                        "FR_collar_joint",
                        "FR_hip_joint",
                        "FR_knee_joint",
                    ],
                    [10, 11, 12, 7, 8, 9, 4, 5, 6, 1, 2, 3],
                )
            ]
            scan = build_scan_result(entries)

            saved = save_verified_zero_profile_from_scan(paths, scan, upstream_commit="abc")
            loaded = load_active_zero_profile(paths)
            result = validate_zero_profile(loaded, expected_upstream_commit="abc")

            self.assertTrue(saved.exists())
            self.assertIsNotNone(loaded)
            self.assertTrue(result.ok)
            self.assertEqual(loaded.source, "post_zero_scan")

    def test_validate_zero_profile_rejects_unverified_profile(self) -> None:
        profile = new_zero_profile(result="failed", operator_confirmed=False, post_zero_max_abs_position_rad=0.2)

        result = validate_zero_profile(profile)

        self.assertFalse(result.ok)
        self.assertGreaterEqual(len(result.errors), 3)

    def test_validate_zero_profile_warns_when_workspace_identity_is_missing_or_stale(self) -> None:
        missing_identity = new_zero_profile(
            result="verified",
            operator_confirmed=True,
            post_zero_max_abs_position_rad=0.01,
        )
        stale_identity = new_zero_profile(
            upstream_commit="old",
            patch_set_hash="old-patches",
            result="verified",
            operator_confirmed=True,
            post_zero_max_abs_position_rad=0.01,
        )

        missing = validate_zero_profile(
            missing_identity,
            expected_upstream_commit="current",
            expected_patch_set_hash="current-patches",
        )
        stale = validate_zero_profile(
            stale_identity,
            expected_upstream_commit="current",
            expected_patch_set_hash="current-patches",
        )

        self.assertTrue(missing.ok)
        self.assertEqual(len(missing.warnings), 2)
        self.assertTrue(stale.ok)
        self.assertEqual(len(stale.warnings), 2)


if __name__ == "__main__":
    unittest.main()
