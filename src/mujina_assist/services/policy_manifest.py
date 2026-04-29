from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
        schema_version=_int_value(data.get("schema_version")),
        robot=str(data.get("robot", "")),
        robot_revision=str(data.get("robot_revision", "")),
        framework=str(data.get("framework", "")),
        input_shape=_int_list(input_data.get("shape")),
        observation_order=_str_list(input_data.get("observation_order")),
        output_shape=_int_list(output_data.get("shape")),
        output_unit=str(output_data.get("unit", "")),
        output_scale=_float_value(output_data.get("scale")),
        target_formula=str(output_data.get("target_formula", "")),
        joint_order=_str_list(data.get("joint_order")),
        onnx_sha256=str(hash_data.get("onnx_sha256", "")),
        requires_sim_verification=bool(safety_data.get("requires_sim_verification", True)),
        real_world_approved=bool(safety_data.get("real_world_approved", False)),
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


def _object_at(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            return []
    return result


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
