from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mujina_assist.models import AppPaths, DEFAULT_MOTOR_IDS


MAX_POST_ZERO_ABS_POSITION_RAD = 0.05


@dataclass(slots=True)
class ZeroProfileCheck:
    ok: bool = False
    allowed: bool = False
    errors: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def zero_profile_path(paths: AppPaths) -> Path:
    return paths.active_zero_profile_file


def save_zero_profile(path: Path, profile: dict[str, Any]) -> None:
    _atomic_write_json(path, profile)


def load_zero_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("zero profile must be a JSON object")
    return data


def validate_zero_profile(
    profile: dict[str, Any] | Path,
    *,
    current_workspace_signature: str = "",
    current_policy_hash: str = "",
    max_abs_position_rad: float = MAX_POST_ZERO_ABS_POSITION_RAD,
) -> ZeroProfileCheck:
    data = load_zero_profile(profile) if isinstance(profile, Path) else profile
    reasons: list[str] = []
    if not isinstance(data, dict):
        return ZeroProfileCheck(ok=False, allowed=False, errors=["zero profile must be a JSON object"], reasons=["zero profile must be a JSON object"])
    schema_version = data.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        reasons.append("schema version is unsupported")
    workspace_signature = data.get("workspace_signature", "")
    if not isinstance(workspace_signature, str) or not workspace_signature:
        reasons.append("workspace signature is missing")
    elif current_workspace_signature and workspace_signature != current_workspace_signature:
        reasons.append("workspace signature mismatch")
    policy_hash = data.get("policy_hash", "")
    if not isinstance(policy_hash, str) or not policy_hash:
        reasons.append("policy hash is missing")
    elif current_policy_hash and policy_hash != current_policy_hash:
        reasons.append("policy hash mismatch")
    motor_ids = data.get("motor_ids", DEFAULT_MOTOR_IDS)
    if (
        not isinstance(motor_ids, list)
        or any(isinstance(motor_id, bool) or not isinstance(motor_id, int) for motor_id in motor_ids)
        or list(motor_ids) != DEFAULT_MOTOR_IDS
    ):
        reasons.append("motor ids do not match Mujina defaults")
    post_zero_error = data.get("post_zero_max_abs_position_rad")
    if isinstance(post_zero_error, bool) or not isinstance(post_zero_error, (int, float)):
        reasons.append("post-zero error must be a finite number")
    elif not math.isfinite(float(post_zero_error)):
        reasons.append("post-zero error must be a finite number")
    elif float(post_zero_error) > max_abs_position_rad:
        reasons.append(f"post-zero error is too large: {post_zero_error:.3f} rad")
    ok = not reasons
    return ZeroProfileCheck(ok=ok, allowed=ok, errors=reasons, reasons=reasons)


def zero_profile_allows_real_launch(
    profile: dict[str, Any] | Path | None,
    *,
    current_workspace_signature: str,
    current_policy_hash: str,
) -> ZeroProfileCheck:
    if profile is None:
        return ZeroProfileCheck(ok=False, allowed=False, errors=["zero profile is missing"], reasons=["zero profile is missing"])
    return validate_zero_profile(
        profile,
        current_workspace_signature=current_workspace_signature,
        current_policy_hash=current_policy_hash,
    )


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
