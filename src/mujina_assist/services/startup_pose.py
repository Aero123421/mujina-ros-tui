from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mujina_assist.models import AppPaths, DEFAULT_MOTOR_IDS
from mujina_assist.services.motors import JOINT_ORDER, MotorScanResult


MAX_STARTUP_POSE_VELOCITY_RAD_S = 0.2
MAX_STARTUP_POSE_CURRENT_A = 10.0
MAX_STARTUP_POSE_TEMPERATURE_C = 70.0


@dataclass(slots=True)
class StartupPoseProfile:
    schema_version: int
    created_at: str
    upstream_commit: str
    patch_set_hash: str
    can_interface: str
    motor_ids: list[int]
    joint_order: list[str]
    positions_rad: list[float]
    operator_confirmed: bool
    source: str = ""
    label: str = "startup_pose"


@dataclass(slots=True)
class StartupPoseValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    profile: StartupPoseProfile | None = None


def new_startup_pose_profile(
    *,
    positions_rad: list[float],
    upstream_commit: str = "",
    patch_set_hash: str = "",
    can_interface: str = "can0",
    motor_ids: list[int] | None = None,
    joint_order: list[str] | None = None,
    operator_confirmed: bool = False,
    source: str = "mujina_assist",
    label: str = "startup_pose",
) -> StartupPoseProfile:
    return StartupPoseProfile(
        schema_version=1,
        created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        upstream_commit=upstream_commit,
        patch_set_hash=patch_set_hash,
        can_interface=can_interface,
        motor_ids=list(motor_ids or DEFAULT_MOTOR_IDS),
        joint_order=list(joint_order or JOINT_ORDER),
        positions_rad=[float(value) for value in positions_rad],
        operator_confirmed=operator_confirmed,
        source=source,
        label=label,
    )


def startup_pose_scan_errors(
    scan_result: MotorScanResult,
    *,
    max_abs_velocity_rad_s: float = MAX_STARTUP_POSE_VELOCITY_RAD_S,
    max_abs_current_a: float = MAX_STARTUP_POSE_CURRENT_A,
    max_temperature_c: float = MAX_STARTUP_POSE_TEMPERATURE_C,
) -> list[str]:
    errors: list[str] = []
    if scan_result.motor_ids != DEFAULT_MOTOR_IDS:
        errors.append("motor_ids が Mujina の既定 12 軸と一致しません。")
    if scan_result.joint_order != JOINT_ORDER:
        errors.append("joint_order が Mujina の既定順序と一致しません。")
    if scan_result.summary.get("responded") != len(DEFAULT_MOTOR_IDS):
        errors.append(f"応答した motor が {scan_result.summary.get('responded', 0)}/12 です。")
    if scan_result.summary.get("error_count", 0):
        errors.append("error_code を返した motor があります。")
    for entry in scan_result.entries:
        if not entry.responded:
            errors.append(f"motor {entry.motor_id} が応答していません。")
            continue
        if entry.position_rad is None:
            errors.append(f"motor {entry.motor_id} position が読めません。")
        if entry.velocity_rad_s is None:
            errors.append(f"motor {entry.motor_id} velocity が読めません。")
        elif abs(entry.velocity_rad_s) > max_abs_velocity_rad_s:
            errors.append(f"motor {entry.motor_id} velocity={entry.velocity_rad_s:.3f} rad/s が大きすぎます。")
        if entry.current_a is None:
            errors.append(f"motor {entry.motor_id} current が読めません。")
        elif abs(entry.current_a) > max_abs_current_a:
            errors.append(f"motor {entry.motor_id} current={entry.current_a:.3f} A が大きすぎます。")
        if entry.temperature_c is None:
            errors.append(f"motor {entry.motor_id} temperature が読めません。")
        elif entry.temperature_c > max_temperature_c:
            errors.append(f"motor {entry.motor_id} temperature={entry.temperature_c:.1f}C が高すぎます。")
    return errors


def startup_pose_profile_from_scan(
    scan_result: MotorScanResult,
    *,
    upstream_commit: str = "",
    patch_set_hash: str = "",
    operator_confirmed: bool = True,
    source: str = "startup_pose_scan",
    label: str = "startup_pose",
) -> StartupPoseProfile:
    if not operator_confirmed:
        raise ValueError("operator confirmation is required for a startup pose profile")
    errors = startup_pose_scan_errors(scan_result)
    if errors:
        raise ValueError("startup pose scan is not safe to record: " + " / ".join(errors[:4]))
    positions = [entry.position_rad for entry in scan_result.entries if entry.responded and entry.position_rad is not None]
    if len(positions) != len(DEFAULT_MOTOR_IDS):
        raise ValueError("startup pose scan does not contain all motor positions")
    return new_startup_pose_profile(
        positions_rad=[float(position) for position in positions],
        upstream_commit=upstream_commit,
        patch_set_hash=patch_set_hash,
        can_interface=scan_result.can_interface,
        motor_ids=scan_result.motor_ids,
        joint_order=scan_result.joint_order,
        operator_confirmed=operator_confirmed,
        source=source,
        label=label,
    )


def save_startup_pose_profile(paths: AppPaths, profile: StartupPoseProfile, *, activate: bool = True) -> Path:
    paths.startup_poses_dir.mkdir(parents=True, exist_ok=True)
    safe_created_at = profile.created_at.replace(":", "").replace("+", "_").replace("-", "")
    target = paths.startup_poses_dir / f"startup-pose-{safe_created_at}.json"
    _atomic_write_json(target, asdict(profile))
    if activate:
        _atomic_write_json(paths.active_startup_pose_file, asdict(profile))
    return target


def save_startup_pose_profile_from_scan(
    paths: AppPaths,
    scan_result: MotorScanResult,
    *,
    upstream_commit: str = "",
    patch_set_hash: str = "",
    operator_confirmed: bool = True,
    activate: bool = True,
    label: str = "startup_pose",
) -> Path:
    profile = startup_pose_profile_from_scan(
        scan_result,
        upstream_commit=upstream_commit,
        patch_set_hash=patch_set_hash,
        operator_confirmed=operator_confirmed,
        label=label,
    )
    return save_startup_pose_profile(paths, profile, activate=activate)


def load_startup_pose_profile(path: Path) -> StartupPoseProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("startup pose profile must be a JSON object")
    return parse_startup_pose_profile(data)


def load_active_startup_pose_profile(paths: AppPaths) -> StartupPoseProfile | None:
    if not paths.active_startup_pose_file.exists():
        return None
    return load_startup_pose_profile(paths.active_startup_pose_file)


def parse_startup_pose_profile(data: dict[str, Any]) -> StartupPoseProfile:
    return StartupPoseProfile(
        schema_version=_required_int(data.get("schema_version"), "schema_version"),
        created_at=str(data.get("created_at", "")),
        upstream_commit=str(data.get("upstream_commit", "")),
        patch_set_hash=str(data.get("patch_set_hash", "")),
        can_interface=str(data.get("can_interface", "")),
        motor_ids=_int_list(data.get("motor_ids"), "motor_ids"),
        joint_order=_str_list(data.get("joint_order"), "joint_order"),
        positions_rad=_float_list(data.get("positions_rad"), "positions_rad"),
        operator_confirmed=_required_bool(data.get("operator_confirmed", False), "operator_confirmed"),
        source=str(data.get("source", "")),
        label=str(data.get("label", "startup_pose")),
    )


def validate_startup_pose_profile(
    profile_or_path: StartupPoseProfile | Path | None,
    *,
    expected_upstream_commit: str = "",
    expected_patch_set_hash: str = "",
) -> StartupPoseValidation:
    if profile_or_path is None:
        return StartupPoseValidation(ok=False, errors=["startup pose profile がありません。"])
    try:
        profile = load_startup_pose_profile(profile_or_path) if isinstance(profile_or_path, Path) else profile_or_path
    except Exception as exc:
        return StartupPoseValidation(ok=False, errors=[f"startup pose profile を読み込めません: {exc}"])

    errors: list[str] = []
    warnings: list[str] = []
    if profile.schema_version != 1:
        errors.append("startup pose profile の schema_version は 1 である必要があります。")
    if not profile.operator_confirmed:
        errors.append("operator_confirmed が true ではありません。")
    if profile.motor_ids != DEFAULT_MOTOR_IDS:
        errors.append("motor_ids が Mujina の既定 12 軸と一致しません。")
    if profile.joint_order != JOINT_ORDER:
        errors.append("joint_order が Mujina の既定順序と一致しません。")
    if len(profile.positions_rad) != len(DEFAULT_MOTOR_IDS):
        errors.append("positions_rad は 12 軸分である必要があります。")
    if expected_upstream_commit:
        if not profile.upstream_commit:
            warnings.append("startup pose profile 作成時の upstream commit が記録されていません。")
        elif profile.upstream_commit != expected_upstream_commit:
            warnings.append("startup pose profile 作成時の upstream commit と現在の commit が異なります。")
    if expected_patch_set_hash:
        if not profile.patch_set_hash:
            warnings.append("startup pose profile 作成時の patch set が記録されていません。")
        elif profile.patch_set_hash != expected_patch_set_hash:
            warnings.append("startup pose profile 作成時の patch set と現在の patch set が異なります。")
    return StartupPoseValidation(ok=not errors, errors=errors, warnings=warnings, profile=profile)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    backup_path = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        shutil.copy2(path, backup_path)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _int_list(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of integers")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{field_name} must contain integers")
        result.append(item)
    return result


def _float_list(value: Any, field_name: str) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of finite numbers")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field_name} must contain finite numbers")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{field_name} must contain finite numbers")
        result.append(number)
    return result


def _str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must contain strings")
    return list(value)


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value
