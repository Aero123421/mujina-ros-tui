from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths
from mujina_assist.services.zero import load_active_zero_profile, new_zero_profile, save_zero_profile, validate_zero_profile


class ZeroProfileTest(unittest.TestCase):
    def test_save_load_and_validate_zero_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            profile = new_zero_profile(upstream_commit="abc", post_zero_max_abs_position_rad=0.02)

            saved = save_zero_profile(paths, profile)
            loaded = load_active_zero_profile(paths)
            result = validate_zero_profile(loaded, expected_upstream_commit="abc")

            self.assertTrue(saved.exists())
            self.assertIsNotNone(loaded)
            self.assertTrue(result.ok)

    def test_validate_zero_profile_rejects_unverified_profile(self) -> None:
        profile = new_zero_profile(result="failed", operator_confirmed=False, post_zero_max_abs_position_rad=0.2)

        result = validate_zero_profile(profile)

        self.assertFalse(result.ok)
        self.assertGreaterEqual(len(result.errors), 3)


if __name__ == "__main__":
    unittest.main()
