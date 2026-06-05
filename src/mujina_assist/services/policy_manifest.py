from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import math

from mujina_assist.models import DEFAULT_MOTOR_IDS
from mujina_assist.services.checks import file_hash


DEFAULT_JOINT_ORDER = [
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
]

DEFAULT_OBSERVATION_ORDER = [
    "base_ang_vel_3",
    "projected_gravity_3",
    "command_3",
    "dof_pos_minus_default_12",
    "dof_vel_12",
    "last_actions_12",
]

EXPECTED_INPUT_SHAPE = [1, 45]
EXPECTED_OUTPUT_SHAPE = [1, 12]


@dataclass(slots=True)
class PolicyManifest:
    schema_version: int
    robot: str
    robot_revision: str
    framework: str
    input_shape: list[int]
    observation_order: list[str]
    output_shape: list[int]
    output_unit: str
    output_scale: float
    target_formula: str
    joint_order: list[str]
    onnx_sha256: str
    requires_sim_verification: bool
    real_world_approved: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyManifestValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: PolicyManifest | None = None


def load_policy_manifest(path: Path) -> PolicyManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("policy manifest must be a JSON object")
    return parse_policy_manifest(data)


def parse_policy_manifest(data: dict[str, Any]) -> PolicyManifest:
    input_data = _object_at(data, "input")
    output_data = _object_at(data, "output")
    hash_data = _object_at(data, "hash")
    safety_data = _object_at(data, "safety")
    return PolicyManifest(
        schema_version=_required_int(data.get("schema_version"), "schema_version"),
        robot=str(data.get("robot", "")),
        robot_revision=str(data.get("robot_revision", "")),
        framework=str(data.get("framework", "")),
        input_shape=_int_list(input_data.get("shape"), "input.shape"),
        observation_order=_str_list(input_data.get("observation_order"), "input.observation_order"),
        output_shape=_int_list(output_data.get("shape"), "output.shape"),
        output_unit=str(output_data.get("unit", "")),
        output_scale=_required_float(output_data.get("scale"), "output.scale"),
        target_formula=str(output_data.get("target_formula", "")),
        joint_order=_str_list(data.get("joint_order"), "joint_order"),
        onnx_sha256=str(hash_data.get("onnx_sha256", "")),
        requires_sim_verification=_required_bool(
            safety_data.get("requires_sim_verification", True),
            "safety.requires_sim_verification",
        ),
        real_world_approved=_required_bool(
            safety_data.get("real_world_approved", False),
            "safety.real_world_approved",
        ),
        raw=data,
    )


def validate_policy_manifest(
    manifest_or_path: PolicyManifest | Path,
    *,
    policy_path: Path | None = None,
    require_real_world_approved: bool = False,
) -> PolicyManifestValidation:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        manifest = load_policy_manifest(manifest_or_path) if isinstance(manifest_or_path, Path) else manifest_or_path
    except Exception as exc:
        return PolicyManifestValidation(ok=False, errors=[f"manifest を読み込めません: {exc}"])

    if manifest.schema_version != 1:
        errors.append("schema_version は 1 である必要があります。")
    if manifest.robot != "mujina":
        errors.append("robot は mujina である必要があります。")
    if not manifest.robot_revision:
        errors.append("robot_revision が未設定です。")
    if manifest.framework.lower() != "onnx":
        errors.append("framework は onnx である必要があります。")
    if manifest.input_shape != EXPECTED_INPUT_SHAPE:
        errors.append("input.shape は [1, 45] である必要があります。")
    if manifest.output_shape != EXPECTED_OUTPUT_SHAPE:
        errors.append("output.shape は [1, 12] である必要があります。")
    if manifest.joint_order != DEFAULT_JOINT_ORDER:
        errors.append("joint_order が Mujina の既定順序と一致しません。")
    if len(manifest.joint_order) != len(DEFAULT_MOTOR_IDS):
        errors.append("joint_order は 12 軸分である必要があります。")
    if manifest.requires_sim_verification is False:
        warnings.append("safety.requires_sim_verification が false です。実機投入前の SIM 確認は維持してください。")
    if require_real_world_approved and not manifest.real_world_approved:
        errors.append("safety.real_world_approved が true ではありません。")
    if not manifest.onnx_sha256:
        errors.append("hash.onnx_sha256 が未設定です。")
    elif policy_path is not None:
        actual_hash = file_hash(policy_path)
        if not actual_hash:
            errors.append(f"policy ファイルを読めません: {policy_path}")
        elif actual_hash != manifest.onnx_sha256:
            errors.append("manifest の onnx_sha256 が policy ファイルと一致しません。")

    return PolicyManifestValidation(ok=not errors, errors=errors, warnings=warnings, manifest=manifest)


def default_manifest_path(policy_path: Path) -> Path:
    return policy_path.with_suffix(".manifest.json")


def build_policy_manifest_template(
    policy_path: Path,
    *,
    robot_revision: str = "",
    real_world_approved: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "robot": "mujina",
        "robot_revision": robot_revision,
        "framework": "onnx",
        "input": {
            "shape": EXPECTED_INPUT_SHAPE,
            "observation_order": DEFAULT_OBSERVATION_ORDER,
        },
        "output": {
            "shape": EXPECTED_OUTPUT_SHAPE,
            "unit": "action",
            "scale": 0.25,
            "target_formula": "ref_angle = action * action_scale + DEFAULT_ANGLE",
        },
        "joint_order": DEFAULT_JOINT_ORDER,
        "hash": {"onnx_sha256": file_hash(policy_path)},
        "safety": {
            "requires_sim_verification": True,
            "real_world_approved": real_world_approved,
        },
        "notes": {
            "status": "draft",
            "next_steps": [
                "robot_revision を実機/学習対象に合わせて設定する",
                "input/output shape と joint_order が export 条件と一致するか確認する",
                "SIMで動作確認してから real_world_approved を true にする",
            ],
        },
    }


def write_policy_manifest_template(
    policy_path: Path,
    *,
    manifest_path: Path | None = None,
    overwrite: bool = False,
    robot_revision: str = "",
    real_world_approved: bool = False,
) -> Path:
    policy_path = policy_path.expanduser()
    if not policy_path.exists():
        raise FileNotFoundError(f"ONNX file not found: {policy_path}")
    if policy_path.suffix.lower() != ".onnx":
        raise ValueError("policy path must end with .onnx")
    target = manifest_path.expanduser() if manifest_path is not None else default_manifest_path(policy_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"manifest already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = build_policy_manifest_template(
        policy_path,
        robot_revision=robot_revision,
        real_world_approved=real_world_approved,
    )
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _object_at(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _int_list(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of integers")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f"{field_name} must not contain bool values")
        if not isinstance(item, int):
            raise ValueError(f"{field_name} must contain integers")
        result.append(item)
    return result


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must contain strings")
    return list(value)
