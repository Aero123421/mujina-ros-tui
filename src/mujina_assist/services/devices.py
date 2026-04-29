from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SerialCandidate:
    path: str
    kind: str
    exists: bool = True
    by_id: list[str] | None = None
    symlink_target: str = ""
    vendor_id: str = ""
    product_id: str = ""
    manufacturer: str = ""
    product: str = ""
    serial: str = ""

    def summary(self) -> str:
        parts = [self.path]
        if self.vendor_id or self.product_id:
            parts.append(f"vid:pid={self.vendor_id or '?'}:{self.product_id or '?'}")
        if self.product:
            parts.append(f"product={self.product}")
        if self.by_id:
            parts.append("by-id=" + ",".join(self.by_id))
        return " ".join(parts)


def detect_real_devices() -> dict[str, bool]:
    return {
        "/dev/rt_usb_imu": Path("/dev/rt_usb_imu").exists(),
        "/dev/usb_can": Path("/dev/usb_can").exists(),
        "/dev/input/js0": Path("/dev/input/js0").exists(),
        "can0": Path("/sys/class/net/can0").exists(),
    }


def list_serial_device_candidates() -> list[str]:
    return [candidate.path for candidate in list_serial_candidate_details()]


def list_serial_candidate_details() -> list[SerialCandidate]:
    paths: list[Path] = []
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial/by-id/*"):
        paths.extend(sorted(Path("/").glob(pattern.lstrip("/"))))

    by_id_index = _serial_by_id_index()
    seen: set[str] = set()
    candidates: list[SerialCandidate] = []
    for path in paths:
        display_path = str(path)
        real_path = _resolved_path(path)
        unique_key = str(real_path if "/dev/serial/by-id/" in display_path else path)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        candidate_path = real_path if "/dev/serial/by-id/" in display_path else path
        details = _serial_usb_metadata(candidate_path.name)
        candidates.append(
            SerialCandidate(
                path=str(candidate_path),
                kind="ttyACM" if candidate_path.name.startswith("ttyACM") else "ttyUSB" if candidate_path.name.startswith("ttyUSB") else "serial",
                exists=candidate_path.exists(),
                by_id=by_id_index.get(str(candidate_path), []),
                symlink_target=str(real_path) if path.is_symlink() else "",
                vendor_id=details.get("idVendor", ""),
                product_id=details.get("idProduct", ""),
                manufacturer=details.get("manufacturer", ""),
                product=details.get("product", ""),
                serial=details.get("serial", ""),
            )
        )
    return candidates


def resolve_imu_port() -> tuple[str | None, bool, list[str]]:
    fixed = Path("/dev/rt_usb_imu")
    candidates = list_serial_device_candidates()
    if fixed.exists():
        return str(fixed), False, candidates
    generic = [candidate for candidate in candidates if "/dev/ttyUSB" in candidate or "/dev/ttyACM" in candidate]
    if len(generic) == 1:
        return generic[0], True, candidates
    return None, False, candidates


def _serial_by_id_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    by_id_dir = Path("/dev/serial/by-id")
    if not by_id_dir.exists():
        return index
    for link in sorted(by_id_dir.glob("*")):
        target = str(_resolved_path(link))
        index.setdefault(target, []).append(str(link))
    return index


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _serial_usb_metadata(tty_name: str) -> dict[str, str]:
    if os.name == "nt":
        return {}
    device = Path("/sys/class/tty") / tty_name / "device"
    if not device.exists():
        return {}
    details: dict[str, str] = {}
    current = device.resolve(strict=False)
    for parent in (current, *current.parents):
        for key in ("idVendor", "idProduct", "manufacturer", "product", "serial"):
            if key in details:
                continue
            value_path = parent / key
            if value_path.exists():
                details[key] = value_path.read_text(encoding="utf-8", errors="ignore").strip()
        if "idVendor" in details and "idProduct" in details:
            break
    return details
