from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths


try:
    zero_module = importlib.import_module("mujina_assist.services.zero_profile")
except ImportError:  # pragma: no cover - documents the expected zero profile service while it is absent.
    zero_module = None


REQUIRED_ZERO_PROFILE_API = (
    "zero_profile_path",
    "save_zero_profile",
    "load_zero_profile",
    "validate_zero_profile",
    "zero_profile_allows_real_launch",
)


@unittest.skipIf(
    zero_module is None,
    "mujina_assist.services.zero_profile is not implemented yet. "
    f"Expected API: {', '.join(REQUIRED_ZERO_PROFILE_API)}",
)
class ZeroProfileTest(unittest.TestCase):
    def _api(self, name: str):
        value = getattr(zero_module, name, None)
        if value is None:
            self.fail(f"mujina_assist.services.zero_profile.{name} is required")
        return value

    def test_zero_profile_round_trips_post_zero_verification_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            profile_path = self._api("zero_profile_path")(paths)
            profile = {
                "schema_version": 1,
                "created_at": "2026-04-30T12:00:00+09:00",
                "workspace_signature": "38ff97f+patches-abc",
                "policy_hash": "policy-sha256",
                "can_interface": "can0",
                "motor_ids": [10, 11, 12, 7, 8, 9, 4, 5, 6, 1, 2, 3],
                "post_zero_max_abs_position_rad": 0.02,
            }

            self._api("save_zero_profile")(profile_path, profile)
            loaded = self._api("load_zero_profile")(profile_path)
            result = self._api("validate_zero_profile")(
                loaded,
                current_workspace_signature="38ff97f+patches-abc",
                current_policy_hash="policy-sha256",
            )

            self.assertEqual(loaded["can_interface"], "can0")
            self.assertEqual(loaded["post_zero_max_abs_position_rad"], 0.02)
            self.assertTrue(result.ok, result.errors)

    def test_zero_profile_blocks_real_launch_when_workspace_signature_is_stale(self) -> None:
        result = self._api("zero_profile_allows_real_launch")(
            {
                "workspace_signature": "old",
                "policy_hash": "policy-sha256",
                "post_zero_max_abs_position_rad": 0.02,
            },
            current_workspace_signature="38ff97f+patches-abc",
            current_policy_hash="policy-sha256",
        )

        self.assertFalse(result.allowed)
        self.assertIn("workspace", " ".join(result.reasons).lower())

    def test_zero_profile_blocks_real_launch_when_post_zero_error_is_too_large(self) -> None:
        result = self._api("zero_profile_allows_real_launch")(
            {
                "workspace_signature": "38ff97f+patches-abc",
                "policy_hash": "policy-sha256",
                "post_zero_max_abs_position_rad": 0.25,
            },
            current_workspace_signature="38ff97f+patches-abc",
            current_policy_hash="policy-sha256",
        )

        self.assertFalse(result.allowed)
        self.assertIn("zero", " ".join(result.reasons).lower())


if __name__ == "__main__":
    unittest.main()
