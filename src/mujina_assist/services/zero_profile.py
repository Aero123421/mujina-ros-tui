from __future__ import annotations

import json
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
    if data.get("schema_version", 1) != 1:
        reasons.append("schema version is unsupported")
    workspace_signature = str(data.get("workspace_signature", ""))
    if current_workspace_signature and workspace_signature != current_workspace_signature:
        reasons.append("workspace signature mismatch")
    policy_hash = str(data.get("policy_hash", ""))
    if current_policy_hash and policy_hash != current_policy_hash:
        reasons.append("policy hash mismatch")
    motor_ids = data.get("motor_ids", DEFAULT_MOTOR_IDS)
    if list(motor_ids) != DEFAULT_MOTOR_IDS:
        reasons.append("motor ids do not match Mujina defaults")
    try:
        post_zero_error = float(data.get("post_zero_max_abs_position_rad", 999.0))
    except (TypeError, ValueError):
        post_zero_error = 999.0
    if post_zero_error > max_abs_position_rad:
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
