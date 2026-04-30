from __future__ import annotations

from dataclasses import dataclass, field

from mujina_assist.models import DoctorReport, RuntimeState
from mujina_assist.services.policy_manifest import PolicyManifestValidation
from mujina_assist.services.zero import ZeroProfileValidation


P0 = "P0"
P1 = "P1"
P2 = "P2"


@dataclass(slots=True)
class LockReason:
    priority: str
    code: str
    message: str


@dataclass(slots=True)
class SafetyState:
    real_launch_locked: bool
    lock_reasons: list[str] = field(default_factory=list)
    standup_locked: bool = True
    walk_locked: bool = True
    emergency_stop_required: bool = False
    manual_recovery_required: bool = False
    manual_recovery_summary: str = ""
    reasons: list[LockReason] = field(default_factory=list)


def evaluate_real_preflight(
    report: DoctorReport,
    state: RuntimeState,
    *,
    policy_manifest: PolicyManifestValidation | None = None,
    zero_profile: ZeroProfileValidation | None = None,
    can_mode: str = "net",
    active_job_kinds: set[str] | None = None,
    operator_checklist_complete: bool = False,
    real_confirmation: str = "",
) -> SafetyState:
    reasons: list[LockReason] = []
    active_jobs = active_job_kinds or set()

    _add_if(reasons, not report.workspace_built, P0, "build_missing", "workspace のビルドが完了していません。")
    _add_if(reasons, not report.active_policy_hash, P0, "policy_unknown", "active policy が不明です。")
    _add_if(reasons, not report.sim_ready, P0, "sim_unverified", "現在の workspace + policy は SIM 確認済みではありません。")
    _add_if(reasons, state.manual_recovery_required, P0, "manual_recovery", state.manual_recovery_summary or "前回の手動復旧が未解決です。")

    policy_required = _external_policy_requires_manifest(report)
    if policy_required:
        if policy_manifest is None:
            _add(reasons, P0, "policy_manifest_missing", "external policy には manifest が必要です。")
        elif not policy_manifest.ok:
            for error in policy_manifest.errors:
                _add(reasons, P0, "policy_manifest_invalid", error)
    if policy_manifest is not None:
        for warning in policy_manifest.warnings:
            _add(reasons, P1, "policy_manifest_warning", warning)

    if zero_profile is None:
        _add(reasons, P0, "zero_profile_missing", "verified zero profile がありません。")
    elif not zero_profile.ok:
        for error in zero_profile.errors:
            _add(reasons, P0, "zero_profile_invalid", error)
    if zero_profile is not None:
        for warning in zero_profile.warnings:
            _add(reasons, P1, "zero_profile_warning", warning)

    devices = report.real_devices
    imu_ok = bool(report.imu_port_label and not report.imu_port_fallback)
    _add_if(reasons, not imu_ok, P0, "imu_missing", "固定名 IMU `/dev/rt_usb_imu` が確認できません。")
    _add_if(reasons, not devices.get("/dev/input/js0", False), P1, "joy_missing", "ゲームパッドが未検出です。")
    if can_mode == "serial":
        _add_if(reasons, not devices.get("/dev/usb_can", False), P0, "serial_can_missing", "`/dev/usb_can` が確認できません。")
        _add_if(reasons, not devices.get("can0", False), P0, "serial_can0_missing", "serial CAN の slcand/can0 が確認できません。")
        _add_if(reasons, not report.tool_status.get("slcand", False), P0, "slcand_missing", "serial CAN の slcand が確認できません。")
    else:
        _add_if(reasons, not devices.get("can0", False), P0, "can0_missing", "`can0` が確認できません。")

    can_check = _check_by_key(report, "can")
    if can_check == "ng":
        _add(reasons, P0, "can_unhealthy", "CAN が NG です。")
    elif can_check == "warn":
        _add(reasons, P0, "can_unhealthy", "CAN が WARN です。")
    _add_if(reasons, bool(active_jobs & {"real_main"}), P0, "real_main_running", "real_main が既に起動しています。")
    _add_if(reasons, bool(active_jobs & {"motor_read", "zero"}), P0, "motor_operation_running", "motor read / zero 操作が実行中です。")
    _add_if(reasons, not operator_checklist_complete, P0, "operator_checklist", "operator checklist が未完了です。")
    _add_if(reasons, real_confirmation != "REAL", P0, "real_confirmation", "`REAL` confirmation が未入力です。")

    real_locked = any(reason.priority == P0 for reason in reasons)
    standup_locked = real_locked or any(reason.priority in {P0, P1} for reason in reasons)
    return SafetyState(
        real_launch_locked=real_locked,
        lock_reasons=[reason.message for reason in reasons],
        standup_locked=standup_locked,
        walk_locked=True,
        emergency_stop_required=state.manual_recovery_required,
        manual_recovery_required=state.manual_recovery_required,
        manual_recovery_summary=state.manual_recovery_summary,
        reasons=reasons,
    )


def p0_reasons(safety: SafetyState) -> list[LockReason]:
    return [reason for reason in safety.reasons if reason.priority == P0]


def _external_policy_requires_manifest(report: DoctorReport) -> bool:
    label = report.active_policy_label or ""
    source = report.active_policy_source or ""
    if label in {"", "未設定", "公式デフォルト"}:
        return False
    if "default_policy.onnx" in source.replace("\\", "/"):
        return False
    return True


def _check_by_key(report: DoctorReport, key: str) -> str:
    for check in report.checks:
        if check.key == key:
            return check.status
    return ""


def _add_if(reasons: list[LockReason], condition: bool, priority: str, code: str, message: str) -> None:
    if condition:
        _add(reasons, priority, code, message)


def _add(reasons: list[LockReason], priority: str, code: str, message: str) -> None:
    reasons.append(LockReason(priority=priority, code=code, message=message))
