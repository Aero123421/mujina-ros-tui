from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths, RuntimeState
from mujina_assist.services.state import load_runtime_state, save_runtime_state


class RuntimeStateSerializationDesignTest(unittest.TestCase):
    def test_saves_and_loads_real_launch_safety_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            state = RuntimeState(
                active_policy_hash="policy-sha256",
                last_sim_success=True,
                last_sim_policy_hash="policy-sha256",
                last_sim_verified_workspace_signature="38ff97f+patches-abc",
                manual_recovery_required=True,
                manual_recovery_kind="workspace",
                manual_recovery_summary="patch apply failed",
            )

            save_runtime_state(paths.runtime_state_file, state)
            loaded = load_runtime_state(paths.runtime_state_file)

            self.assertEqual(loaded.active_policy_hash, "policy-sha256")
            self.assertTrue(loaded.last_sim_success)
            self.assertEqual(loaded.last_sim_verified_workspace_signature, "38ff97f+patches-abc")
            self.assertTrue(loaded.manual_recovery_required)
            self.assertEqual(loaded.manual_recovery_kind, "workspace")
            self.assertEqual(loaded.manual_recovery_summary, "patch apply failed")

    def test_ignores_future_nested_state_without_quarantining_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            payload = {
                "active_policy_hash": "policy-sha256",
                "patch_state": {
                    "mode": "assisted",
                    "upstream_commit": "38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
                    "patch_set_hash": "patches-abc",
                    "dirty": False,
                },
                "zero": {
                    "profile_id": "zero-20260430T120000",
                    "workspace_signature": "38ff97f+patches-abc",
                    "verified": True,
                },
            }
            paths.runtime_state_file.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_runtime_state(paths.runtime_state_file)

            self.assertEqual(loaded.active_policy_hash, "policy-sha256")
            self.assertTrue(paths.runtime_state_file.exists())
            self.assertEqual(list(paths.state_dir.glob("runtime.json.corrupt.*")), [])


if __name__ == "__main__":
    unittest.main()
