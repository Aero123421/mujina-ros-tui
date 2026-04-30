from __future__ import annotations

import shutil
import subprocess

from mujina_assist.models import LiveHealth
from mujina_assist.services.can import evaluate_can_health, inspect_can_status, slcand_summary
from mujina_assist.services.devices import detect_real_devices


def collect_live_health(*, can_mode: str = "net") -> LiveHealth:
    devices = detect_real_devices()
    can_status = inspect_can_status()
    can_health = evaluate_can_health(can_status)
    ros_available, ros_summary = _ros_status()

    warnings: list[str] = []
    can_summary = "can0 error-active, 1Mbps, zero errors" if can_health.ok else "; ".join(can_health.reasons)
    if can_mode == "serial":
        summary = slcand_summary(interface="can0", device="/dev/usb_can")
        if summary == "not running":
            warnings.append("serial CAN requires slcand on /dev/usb_can -> can0.")
        can_summary = f"{can_summary}; slcand={summary}"

    imu_ok = devices.get("/dev/rt_usb_imu", False)
    joy_ok = devices.get("/dev/input/js0", False)
    if not ros_available:
        warnings.append("ROS 2 is not available; topic-level live checks were skipped.")

    return LiveHealth(
        can_ok=can_health.ok,
        can_summary=can_summary,
        imu_ok=imu_ok,
        imu_summary="/dev/rt_usb_imu" if imu_ok else "/dev/rt_usb_imu missing",
        joy_ok=joy_ok,
        joy_summary="/dev/input/js0" if joy_ok else "/dev/input/js0 missing",
        ros_available=ros_available,
        ros_summary=ros_summary,
        warnings=warnings,
    )


def _ros_status() -> tuple[bool, str]:
    if shutil.which("ros2") is None:
        return False, "ros2 command not found"
    try:
        result = subprocess.run(["ros2", "topic", "list"], text=True, capture_output=True, check=False, timeout=2.0)
    except Exception as exc:
        return False, f"ros2 unavailable: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "ros2 topic list failed"
    return True, "ros2 topic list ok"
