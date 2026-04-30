from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mujina_assist.models import DEFAULT_MOTOR_IDS


JOINT_ORDER = [
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


@dataclass(slots=True)
class MotorDescriptor:
    joint_name: str
    motor_id: int
    leg: str
    role: str
    direction: int = 1
    gear_ratio: float = 1.0


@dataclass(slots=True)
class MotorScanEntry:
    joint_name: str
    motor_id: int
    responded: bool = False
    position_rad: float | None = None
    velocity_rad_s: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    error_code: str = ""
    zero_state: str = "unknown"
    status: str = "timeout"
    message: str = ""


@dataclass(slots=True)
class MotorScanResult:
    schema_version: int
    created_at: str
    can_interface: str
    scan_kind: str
    motor_ids: list[int]
    joint_order: list[str]
    entries: list[MotorScanEntry] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_motor_descriptors() -> list[MotorDescriptor]:
    roles = ["collar", "hip", "knee"] * 4
    legs = ["RL"] * 3 + ["RR"] * 3 + ["FL"] * 3 + ["FR"] * 3
    return [
        MotorDescriptor(joint_name=joint, motor_id=motor_id, leg=leg, role=role)
        for joint, motor_id, leg, role in zip(JOINT_ORDER, DEFAULT_MOTOR_IDS, legs, roles)
    ]


def empty_scan_result(*, can_interface: str = "can0", scan_kind: str = "zero_gain_one_shot_query") -> MotorScanResult:
    entries = [
        MotorScanEntry(joint_name=descriptor.joint_name, motor_id=descriptor.motor_id)
        for descriptor in default_motor_descriptors()
    ]
    return build_scan_result(entries, can_interface=can_interface, scan_kind=scan_kind)


def build_scan_result(
    entries: list[MotorScanEntry],
    *,
    can_interface: str = "can0",
    scan_kind: str = "zero_gain_one_shot_query",
    created_at: str | None = None,
) -> MotorScanResult:
    motor_ids = [entry.motor_id for entry in entries]
    result = MotorScanResult(
        schema_version=1,
        created_at=created_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        can_interface=can_interface,
        scan_kind=scan_kind,
        motor_ids=motor_ids,
        joint_order=[entry.joint_name for entry in entries],
        entries=entries,
    )
    result.summary = summarize_scan_entries(entries)
    return result


def summarize_scan_entries(entries: list[MotorScanEntry]) -> dict[str, Any]:
    responded = [entry for entry in entries if entry.responded]
    temperatures = [entry.temperature_c for entry in responded if entry.temperature_c is not None]
    error_entries = [entry for entry in responded if entry.error_code not in {"", "0", "0x00"}]
    return {
        "total": len(entries),
        "responded": len(responded),
        "timeouts": len(entries) - len(responded),
        "max_temperature_c": max(temperatures) if temperatures else None,
        "error_count": len(error_entries),
        "ok": len(responded) == len(entries) and not error_entries,
    }


def save_scan_result(path: Path, result: MotorScanResult) -> None:
    _atomic_write_json(path, result.to_dict())


def load_scan_result(path: Path) -> MotorScanResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [MotorScanEntry(**entry) for entry in data.get("entries", [])]
    result = MotorScanResult(
        schema_version=int(data.get("schema_version", 1)),
        created_at=str(data.get("created_at", "")),
        can_interface=str(data.get("can_interface", "can0")),
        scan_kind=str(data.get("scan_kind", "zero_gain_one_shot_query")),
        motor_ids=[int(value) for value in data.get("motor_ids", [])],
        joint_order=[str(value) for value in data.get("joint_order", [])],
        entries=entries,
        summary=dict(data.get("summary", {})),
    )
    if not result.summary:
        result.summary = summarize_scan_entries(entries)
    return result


def parse_probe_output(output: str, *, descriptors: list[MotorDescriptor] | None = None) -> list[MotorScanEntry]:
    by_id = {descriptor.motor_id: descriptor for descriptor in (descriptors or default_motor_descriptors())}
    entries: dict[int, MotorScanEntry] = {}
    for line in output.splitlines():
        json_entry = _parse_probe_json_line(line, by_id)
        if json_entry is not None:
            entries[json_entry.motor_id] = json_entry
            continue
        match = re.search(
            r"motor\s+(?P<id>\d+):\s+pos=(?P<pos>[-+0-9.eE]+)\s+vel=(?P<vel>[-+0-9.eE]+)\s+cur=(?P<cur>[-+0-9.eE]+)\s+temp=(?P<temp>[-+0-9.eE]+)",
            line,
            re.IGNORECASE,
        )
        if match is None:
            match = re.search(
                r"Motor\s+(?P<id>\d+)\s+Position:\s+(?P<pos>[-+0-9.eE]+),\s+Velocity:\s+(?P<vel>[-+0-9.eE]+),\s+Torque:\s+(?P<cur>[-+0-9.eE]+),\s+Temp:\s+(?P<temp>[-+0-9.eE]+)",
                line,
            )
        if match is None:
            continue
        entry = _entry_from_match(match, by_id)
        entries[entry.motor_id] = entry
    return [entries.get(descriptor.motor_id, MotorScanEntry(descriptor.joint_name, descriptor.motor_id)) for descriptor in by_id.values()]


def _parse_probe_json_line(line: str, by_id: dict[int, MotorDescriptor]) -> MotorScanEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("event") not in {None, "motor_probe"}:
        return None
    try:
        motor_id = int(data["motor_id"])
    except (KeyError, TypeError, ValueError):
        return None
    descriptor = by_id.get(motor_id, MotorDescriptor(f"motor_{motor_id}", motor_id, "", ""))
    status = str(data.get("status", "ok"))
    return MotorScanEntry(
        joint_name=descriptor.joint_name,
        motor_id=motor_id,
        responded=status != "timeout",
        position_rad=_optional_float(data.get("position_rad", data.get("pos"))),
        velocity_rad_s=_optional_float(data.get("velocity_rad_s", data.get("vel"))),
        current_a=_optional_float(data.get("current_a", data.get("cur"))),
        temperature_c=_optional_float(data.get("temperature_c", data.get("temp"))),
        error_code=str(data.get("error_code", "0x00")),
        zero_state=str(data.get("zero_state", "unknown")),
        status=status,
        message=str(data.get("message", "")),
    )


def _entry_from_match(match: re.Match[str], by_id: dict[int, MotorDescriptor]) -> MotorScanEntry:
    motor_id = int(match.group("id"))
    descriptor = by_id.get(motor_id, MotorDescriptor(f"motor_{motor_id}", motor_id, "", ""))
    return MotorScanEntry(
        joint_name=descriptor.joint_name,
        motor_id=motor_id,
        responded=True,
        position_rad=float(match.group("pos")),
        velocity_rad_s=float(match.group("vel")),
        current_a=float(match.group("cur")),
        temperature_c=float(match.group("temp")),
        error_code="0x00",
        zero_state="unknown",
        status="ok",
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
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
