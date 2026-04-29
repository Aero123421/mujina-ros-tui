from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mujina_assist.services.policy_manifest import DEFAULT_JOINT_ORDER, validate_policy_manifest
from mujina_assist.services.checks import file_hash


def _manifest(policy_hash: str) -> dict:
    return {
        "schema_version": 1,
        "robot": "mujina",
        "robot_revision": "v1",
        "framework": "onnx",
        "input": {
            "shape": [1, 45],
            "observation_order": [
                "base_ang_vel_3",
                "projected_gravity_3",
                "command_3",
                "dof_pos_minus_default_12",
                "dof_vel_12",
                "last_actions_12",
            ],
        },
        "output": {
            "shape": [1, 12],
            "unit": "action",
            "scale": 0.25,
            "target_formula": "ref_angle = action * action_scale + DEFAULT_ANGLE",
        },
        "joint_order": DEFAULT_JOINT_ORDER,
        "hash": {"onnx_sha256": policy_hash},
        "safety": {"requires_sim_verification": True, "real_world_approved": False},
    }


class PolicyManifestTest(unittest.TestCase):
    def test_validate_policy_manifest_accepts_expected_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.onnx"
            policy.write_bytes(b"policy")

            result = validate_policy_manifest(
                Path(tmp) / "unused.json",
                policy_path=policy,
            )
            self.assertFalse(result.ok)

            result = validate_policy_manifest_from_dict(_manifest(file_hash(policy)), policy)
            self.assertTrue(result.ok)

    def test_validate_policy_manifest_rejects_bad_shapes_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.onnx"
            policy.write_bytes(b"policy")
            data = _manifest("bad")
            data["input"]["shape"] = [1, 44]

            result = validate_policy_manifest_from_dict(data, policy)

            self.assertFalse(result.ok)
            self.assertIn("input.shape", " ".join(result.errors))
            self.assertIn("onnx_sha256", " ".join(result.errors))


def validate_policy_manifest_from_dict(data: dict, policy: Path):
    from mujina_assist.services.policy_manifest import parse_policy_manifest

    return validate_policy_manifest(parse_policy_manifest(data), policy_path=policy)


if __name__ == "__main__":
    unittest.main()
