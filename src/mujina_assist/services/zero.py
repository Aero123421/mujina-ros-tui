from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mujina_assist.models import AppPaths, DEFAULT_MOTOR_IDS
from mujina_assist.services.policy_manifest import DEFAULT_JOINT_ORDER


MAX_POST_ZERO_ABS_POSITION_RAD = 0.05


@dataclass(slots=True)
class ZeroProfile:
    schema_version: int
    created_at: str
    upstream_commit: str
    patch_set_hash: str
    can_interface: str
    motor_ids: list[int]
    joint_order: list[str]
    result: str
    operator_confirmed: bool
    post_zero_max_abs_position_rad: float
    source: str = ""


@dataclass(slots=True)
class ZeroProfileValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    profile: ZeroProfile | None = None


def new_zero_profile(
    *,
    upstream_commit: str = "",
    patch_set_hash: str = "",
    can_interface: str = "can0",
    motor_ids: list[int] | None = None,
    joint_order: list[str] | None = None,
    result: str = "verified",
    operator_confirmed: bool = True,
    post_zero_max_abs_position_rad: float = 0.0,
    source: str = "mujina_assist",
) -> ZeroProfile:
    return ZeroProfile(
        schema_version=1,
        created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        upstream_commit=upstream_commit,
        patch_set_hash=patch_set_hash,
        can_interface=can_interface,
        motor_ids=list(motor_ids or DEFAULT_MOTOR_IDS),
        joint_order=list(joint_order or DEFAULT_JOINT_ORDER),
        result=result,
        operator_confirmed=operator_confirmed,
        post_zero_max_abs_position_rad=float(post_zero_max_abs_position_rad),
        source=source,
    )


def load_zero_profile(path: Path) -> ZeroProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("zero profile must be a JSON object")
    return parse_zero_profile(data)


def parse_zero_profile(data: dict[str, Any]) -> ZeroProfile:
    return ZeroProfile(
        schema_version=_int_value(data.get("schema_version")),
        created_at=str(data.get("created_at", "")),
        upstream_commit=str(data.get("upstream_commit", "")),
        patch_set_hash=str(data.get("patch_set_hash", "")),
        can_interface=str(data.get("can_interface", "")),
        motor_ids=_int_list(data.get("motor_ids")),
        joint_order=_str_list(data.get("joint_order")),
        result=str(data.get("result", "")),
        operator_confirmed=bool(data.get("operator_confirmed", False)),
        post_zero_max_abs_position_rad=_float_value(data.get("post_zero_max_abs_position_rad")),
        source=str(data.get("source", "")),
    )


def save_zero_profile(paths: AppPaths, profile: ZeroProfile, *, activate: bool = True) -> Path:
    paths.zero_profiles_dir.mkdir(parents=True, exist_ok=True)
    safe_created_at = profile.created_at.replace(":", "").replace("+", "_").replace("-", "")
    target = paths.zero_profiles_dir / f"zero-{safe_created_at}.json"
    _atomic_write_json(target, asdict(profile))
    if activate:
        _atomic_write_json(paths.active_zero_profile_file, asdict(profile))
    return target


def load_active_zero_profile(paths: AppPaths) -> ZeroProfile | None:
    if not paths.active_zero_profile_file.exists():
        return None
    return load_zero_profile(paths.active_zero_profile_file)


def validate_zero_profile(
    profile_or_path: ZeroProfile | Path | None,
    *,
    expected_upstream_commit: str = "",
    expected_patch_set_hash: str = "",
    max_abs_position_rad: float = MAX_POST_ZERO_ABS_POSITION_RAD,
) -> ZeroProfileValidation:
    if profile_or_path is None:
        return ZeroProfileValidation(ok=False, errors=["zero profile がありません。"])
    try:
        profile = load_zero_profile(profile_or_path) if isinstance(profile_or_path, Path) else profile_or_path
    except Exception as exc:
        return ZeroProfileValidation(ok=False, errors=[f"zero profile を読み込めません: {exc}"])

    errors: list[str] = []
    warnings: list[str] = []
    if profile.schema_version != 1:
        errors.append("zero profile の schema_version は 1 である必要があります。")
    if profile.result != "verified":
        errors.append("zero profile が verified ではありません。")
    if not profile.operator_confirmed:
        errors.append("operator_confirmed が true ではありません。")
    if profile.motor_ids != DEFAULT_MOTOR_IDS:
        errors.append("motor_ids が Mujina の既定 12 軸と一致しません。")
    if profile.joint_order != DEFAULT_JOINT_ORDER:
        errors.append("joint_order が Mujina の既定順序と一致しません。")
    if profile.post_zero_max_abs_position_rad > max_abs_position_rad:
        errors.append(f"post-zero 位置誤差が大きすぎます: {profile.post_zero_max_abs_position_rad:.3f} rad")
    if expected_upstream_commit and profile.upstream_commit and profile.upstream_commit != expected_upstream_commit:
        warnings.append("zero profile 作成時の upstream commit と現在の commit が異なります。")
    if expected_patch_set_hash and profile.patch_set_hash and profile.patch_set_hash != expected_patch_set_hash:
        warnings.append("zero profile 作成時の patch set と現在の patch set が異なります。")
    return ZeroProfileValidation(ok=not errors, errors=errors, warnings=warnings, profile=profile)


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


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        return []


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
