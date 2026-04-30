from __future__ import annotations

import math
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from mujina_assist.models import LiveHealth
from mujina_assist.services.can import evaluate_can_health, inspect_can_status, slcand_summary
from mujina_assist.services.devices import detect_real_devices


@dataclass(slots=True)
class TopicSample:
    exists: bool = False
    hz: float | None = None
    last_age_s: float | None = None
    quaternion_norm: float | None = None
    gyro_finite: bool = False
    axes_count: int = 0
    buttons_count: int = 0
    summary: str = ""


def collect_live_health(*, can_mode: str = "net", require_topics: bool = False) -> LiveHealth:
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
        imu_sample = TopicSample(summary=ros_summary)
        joy_sample = TopicSample(summary=ros_summary)
    else:
        imu_sample = inspect_imu_topic()
        joy_sample = inspect_joy_topic()
        if require_topics and not imu_sample.exists:
            warnings.append("/imu/data topic is not live.")
        if require_topics and not joy_sample.exists:
            warnings.append("/joy topic is not live.")

    return LiveHealth(
        can_ok=can_health.ok,
        can_summary=can_summary,
        imu_ok=imu_ok and (not require_topics or _imu_sample_ok(imu_sample)),
        imu_summary=_imu_summary(imu_ok, imu_sample),
        imu_topic_ok=_imu_sample_ok(imu_sample),
        imu_hz=imu_sample.hz,
        imu_quaternion_norm=imu_sample.quaternion_norm,
        imu_last_age_s=imu_sample.last_age_s,
        joy_ok=joy_ok and (not require_topics or _joy_sample_ok(joy_sample)),
        joy_summary=_joy_summary(joy_ok, joy_sample),
        joy_topic_ok=_joy_sample_ok(joy_sample),
        joy_axes_count=joy_sample.axes_count,
        joy_buttons_count=joy_sample.buttons_count,
        joy_last_age_s=joy_sample.last_age_s,
        ros_available=ros_available,
        ros_summary=ros_summary,
        warnings=warnings,
    )


def wait_for_topic_health(topic: str, *, timeout_s: float = 10.0, min_hz: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if topic == "/imu/data":
            sample = inspect_imu_topic()
            if _imu_sample_ok(sample, min_hz=min_hz):
                return True
        elif topic == "/joy":
            sample = inspect_joy_topic()
            if _joy_sample_ok(sample):
                return True
        else:
            sample = inspect_topic(topic)
            if sample.exists and (sample.hz is None or sample.hz >= min_hz):
                return True
        time.sleep(0.5)
    return False


def inspect_topic(topic: str) -> TopicSample:
    topics = _ros_topic_list()
    if topic not in topics:
        return TopicSample(exists=False, summary=f"{topic} is not listed")
    return TopicSample(exists=True, hz=_topic_hz(topic), summary=f"{topic} listed")


def inspect_imu_topic(topic: str = "/imu/data") -> TopicSample:
    sample = inspect_topic(topic)
    if not sample.exists:
        return sample
    echo = _topic_echo_once(topic)
    sample.hz = sample.hz if sample.hz is not None else _topic_hz(topic)
    if not echo:
        sample.summary = f"{topic} listed but echo --once returned no message"
        return sample
    quat = [_yaml_number(echo, key) for key in ("orientation.x", "orientation.y", "orientation.z", "orientation.w")]
    gyro = [_yaml_number(echo, key) for key in ("angular_velocity.x", "angular_velocity.y", "angular_velocity.z")]
    if all(value is not None and math.isfinite(value) for value in quat):
        sample.quaternion_norm = math.sqrt(sum(float(value) * float(value) for value in quat if value is not None))
    sample.gyro_finite = all(value is not None and math.isfinite(value) for value in gyro)
    sec = _yaml_number(echo, "header.stamp.sec")
    nanosec = _yaml_number(echo, "header.stamp.nanosec")
    if sec is not None and sec > 0:
        sample.last_age_s = max(0.0, time.time() - (sec + (nanosec or 0) / 1_000_000_000))
    sample.summary = _imu_summary(True, sample)
    return sample


def inspect_joy_topic(topic: str = "/joy") -> TopicSample:
    sample = inspect_topic(topic)
    if not sample.exists:
        return sample
    echo = _topic_echo_once(topic)
    if not echo:
        sample.summary = f"{topic} listed but echo --once returned no message"
        return sample
    sample.axes_count = _yaml_sequence_count(echo, "axes")
    sample.buttons_count = _yaml_sequence_count(echo, "buttons")
    sec = _yaml_number(echo, "header.stamp.sec")
    nanosec = _yaml_number(echo, "header.stamp.nanosec")
    if sec is not None and sec > 0:
        sample.last_age_s = max(0.0, time.time() - (sec + (nanosec or 0) / 1_000_000_000))
    sample.summary = _joy_summary(True, sample)
    return sample


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


def _ros_topic_list() -> set[str]:
    if shutil.which("ros2") is None:
        return set()
    try:
        result = subprocess.run(["ros2", "topic", "list"], text=True, capture_output=True, check=False, timeout=2.0)
    except Exception:
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def _topic_hz(topic: str) -> float | None:
    if shutil.which("ros2") is None:
        return None
    try:
        result = subprocess.run(["ros2", "topic", "hz", topic], text=True, capture_output=True, check=False, timeout=2.5)
    except Exception:
        return None
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    match = re.search(r"average rate:\s*([0-9.]+)", text)
    return float(match.group(1)) if match else None


def _topic_echo_once(topic: str) -> str:
    if shutil.which("ros2") is None:
        return ""
    try:
        result = subprocess.run(["ros2", "topic", "echo", topic, "--once"], text=True, capture_output=True, check=False, timeout=2.5)
    except Exception:
        return ""
    return result.stdout or ""


def _yaml_number(text: str, dotted_path: str) -> float | None:
    parts = dotted_path.split(".")
    indent = -1
    for part in parts:
        pattern = re.compile(rf"^(?P<indent>\s*){re.escape(part)}:\s*(?P<value>[-+0-9.eE]+)?\s*$")
        for line in text.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            current_indent = len(match.group("indent"))
            if current_indent <= indent:
                continue
            indent = current_indent
            value = match.group("value")
            if value is None:
                break
            try:
                return float(value)
            except ValueError:
                return None
            break
        else:
            return None
    return None


def _yaml_sequence_count(text: str, key: str) -> int:
    inline = re.search(rf"^\s*{re.escape(key)}:\s*\[(?P<body>[^\]]*)\]\s*$", text, flags=re.MULTILINE)
    if inline:
        body = inline.group("body").strip()
        return 0 if not body else len([item for item in body.split(",") if item.strip()])
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^\s*{re.escape(key)}:\s*$", line):
            continue
        base_indent = len(line) - len(line.lstrip())
        count = 0
        for child in lines[index + 1 :]:
            if not child.strip():
                continue
            indent = len(child) - len(child.lstrip())
            if indent <= base_indent:
                break
            if child.lstrip().startswith("-"):
                count += 1
        return count
    return 0


def _imu_sample_ok(sample: TopicSample, *, min_hz: float = 50.0, max_age_s: float = 0.2) -> bool:
    return bool(
        sample.exists
        and sample.hz is not None
        and sample.hz >= min_hz
        and sample.quaternion_norm is not None
        and 0.95 <= sample.quaternion_norm <= 1.05
        and sample.gyro_finite
        and (sample.last_age_s is None or sample.last_age_s <= max_age_s)
    )


def _joy_sample_ok(sample: TopicSample, *, min_axes: int = 4, min_buttons: int = 3, max_age_s: float = 0.5) -> bool:
    return bool(
        sample.exists
        and sample.axes_count >= min_axes
        and sample.buttons_count >= min_buttons
        and (sample.last_age_s is None or sample.last_age_s <= max_age_s)
    )


def _imu_summary(device_ok: bool, sample: TopicSample) -> str:
    device = "/dev/rt_usb_imu" if device_ok else "/dev/rt_usb_imu missing"
    if not sample.exists:
        return f"{device}; /imu/data not live"
    hz = "unknown" if sample.hz is None else f"{sample.hz:.1f}Hz"
    norm = "unknown" if sample.quaternion_norm is None else f"norm={sample.quaternion_norm:.3f}"
    age = "unknown" if sample.last_age_s is None else f"age={sample.last_age_s:.3f}s"
    return f"{device}; /imu/data {hz} {age} {norm}"


def _joy_summary(device_ok: bool, sample: TopicSample) -> str:
    device = "/dev/input/js0" if device_ok else "/dev/input/js0 missing"
    if not sample.exists:
        return f"{device}; /joy not live"
    age = "unknown" if sample.last_age_s is None else f"age={sample.last_age_s:.3f}s"
    return f"{device}; /joy axes={sample.axes_count} buttons={sample.buttons_count} {age}"
