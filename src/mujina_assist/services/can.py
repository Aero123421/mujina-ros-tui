from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class CanLinkStatus:
    interface: str = "can0"
    present: bool = False
    operstate: str = "missing"
    controller_state: str = ""
    bitrate: int | None = None
    restart_ms: int | None = None
    txqueuelen: int | None = None
    rx_packets: int | None = None
    tx_packets: int | None = None
    rx_errors: int | None = None
    tx_errors: int | None = None
    bus_errors: int | None = None
    bus_off: int | None = None
    berr_tx: int | None = None
    berr_rx: int | None = None
    raw: str = ""
    ok: bool = False
    warn: bool = False

    def to_legacy_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SlcandProcess:
    pid: int
    command: str
    device: str = ""
    interface: str = ""


@dataclass(slots=True)
class CanHealth:
    present: bool
    ok: bool
    warn: bool
    reasons: list[str]


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def parse_ip_details_statistics(raw: str, *, interface: str = "can0", present: bool = True, operstate: str = "") -> CanLinkStatus:
    status = CanLinkStatus(interface=interface, present=present, raw=raw.strip())
    if operstate:
        status.operstate = operstate
    elif not present:
        status.operstate = "missing"

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+:\s+", stripped):
            _parse_link_header(stripped, status)
        elif "can state " in stripped:
            _parse_can_state_line(stripped, status)
        elif re.search(r"\bbitrate\s+\d+", stripped):
            status.bitrate = _int_after(stripped, "bitrate")

    _parse_packet_stats(raw, status)
    _derive_health(status)
    return status


def inspect_can_status(interface: str = "can0") -> dict[str, object]:
    present = Path(f"/sys/class/net/{interface}").exists()
    operstate = "missing"
    if present:
        operstate_path = Path(f"/sys/class/net/{interface}/operstate")
        if operstate_path.exists():
            operstate = operstate_path.read_text(encoding="utf-8", errors="ignore").strip()
        else:
            operstate = "unknown"

    if not present:
        return CanLinkStatus(interface=interface, present=False).to_legacy_dict()

    raw = ""
    if command_exists("ip"):
        result = subprocess.run(
            ["ip", "-details", "-statistics", "link", "show", interface],
            text=True,
            capture_output=True,
            check=False,
        )
        raw = ((result.stdout or "") + (result.stderr or "")).strip()

    return parse_ip_details_statistics(raw, interface=interface, present=present, operstate=operstate).to_legacy_dict()


def detect_slcand_processes(*, interface: str | None = None, device: str | None = None) -> list[SlcandProcess]:
    if not command_exists("ps"):
        return []
    result = subprocess.run(["ps", "-eo", "pid=,args="], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return []
    processes: list[SlcandProcess] = []
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or "slcand" not in stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        parsed_device, parsed_interface = _parse_slcand_args(command)
        if interface and parsed_interface and parsed_interface != interface:
            continue
        if device and parsed_device and parsed_device != device:
            continue
        processes.append(SlcandProcess(pid=pid, command=command, device=parsed_device, interface=parsed_interface))
    return processes


def slcand_summary(interface: str = "can0", device: str = "/dev/usb_can") -> str:
    processes = detect_slcand_processes(interface=interface, device=device)
    if not processes:
        return "not running"
    return ", ".join(f"pid={process.pid} {process.device or '?'}->{process.interface or '?'}" for process in processes)


def evaluate_can_health(status: CanLinkStatus | dict[str, object]) -> CanHealth:
    if isinstance(status, dict):
        status = CanLinkStatus(
            interface=str(status.get("interface", "can0")),
            present=bool(status.get("present", False)),
            operstate=str(status.get("operstate", "")),
            controller_state=str(status.get("controller_state", "")),
            bitrate=status.get("bitrate") if isinstance(status.get("bitrate"), int) else None,
            restart_ms=status.get("restart_ms") if isinstance(status.get("restart_ms"), int) else None,
            rx_errors=status.get("rx_errors") if isinstance(status.get("rx_errors"), int) else None,
            tx_errors=status.get("tx_errors") if isinstance(status.get("tx_errors"), int) else None,
            bus_errors=status.get("bus_errors") if isinstance(status.get("bus_errors"), int) else None,
            bus_off=status.get("bus_off") if isinstance(status.get("bus_off"), int) else None,
            ok=bool(status.get("ok", False)),
            warn=bool(status.get("warn", False)),
        )
    reasons: list[str] = []
    if not status.present:
        reasons.append(f"{status.interface} is missing")
    if status.present and (status.operstate or "").lower() != "up":
        reasons.append(f"operstate is {status.operstate or 'unknown'}")
    if status.present and (status.controller_state or "").lower() != "error-active":
        reasons.append(f"controller state is {status.controller_state or 'unknown'}")
    if status.bitrate != 1_000_000 and status.present:
        reasons.append("bitrate is unknown")
        if status.bitrate is not None:
            reasons[-1] = f"bitrate is {status.bitrate}, expected 1000000"
    for label, value in (
        ("rx_errors", status.rx_errors),
        ("tx_errors", status.tx_errors),
        ("bus_errors", status.bus_errors),
        ("bus_off", status.bus_off),
    ):
        if status.present and value != 0:
            reasons.append(f"{label} is {value if value is not None else 'unknown'}")
    ok = status.present and not reasons
    warn = status.present and not ok
    return CanHealth(present=status.present, ok=ok, warn=warn, reasons=reasons)


def _parse_link_header(line: str, status: CanLinkStatus) -> None:
    state_match = re.search(r"\bstate\s+(\S+)", line)
    if state_match:
        status.operstate = state_match.group(1).lower()
    qlen_match = re.search(r"\b(?:qlen|txqueuelen)\s+(\d+)", line)
    if qlen_match:
        status.txqueuelen = int(qlen_match.group(1))


def _parse_can_state_line(line: str, status: CanLinkStatus) -> None:
    state_match = re.search(r"\bcan\s+state\s+([A-Za-z0-9_-]+)", line)
    if state_match:
        status.controller_state = state_match.group(1).lower()
    restart_ms = _int_after(line, "restart-ms")
    if restart_ms is not None:
        status.restart_ms = restart_ms
    berr = re.search(r"berr-counter\s+tx\s+(\d+)\s+rx\s+(\d+)", line)
    if berr:
        status.berr_tx = int(berr.group(1))
        status.berr_rx = int(berr.group(2))


def _parse_packet_stats(raw: str, status: CanLinkStatus) -> None:
    lines = [line.strip() for line in raw.splitlines()]
    for index, line in enumerate(lines[:-1]):
        upper = line.upper()
        if upper.startswith("RX:"):
            values = _extract_ints(lines[index + 1])
            if len(values) >= 3:
                status.rx_packets = values[1]
                status.rx_errors = values[2]
        elif upper.startswith("TX:"):
            values = _extract_ints(lines[index + 1])
            if len(values) >= 3:
                status.tx_packets = values[1]
                status.tx_errors = values[2]
        elif "bus-errors" in line and index + 1 < len(lines):
            labels = line.split()
            values = _extract_ints(lines[index + 1])
            by_label = {label: values[pos] for pos, label in enumerate(labels) if pos < len(values)}
            status.bus_errors = by_label.get("bus-errors", status.bus_errors)
            status.bus_off = by_label.get("bus-off", status.bus_off)


def _derive_health(status: CanLinkStatus) -> None:
    health = evaluate_can_health(status)
    status.ok = health.ok
    status.warn = health.warn


def _int_after(line: str, key: str) -> int | None:
    match = re.search(rf"\b{re.escape(key)}\s+(\d+)", line)
    return int(match.group(1)) if match else None


def _extract_ints(line: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", line)]


def _parse_slcand_args(command: str) -> tuple[str, str]:
    tokens = command.split()
    positional = [token for token in tokens[1:] if not token.startswith("-")]
    device = next((token for token in positional if token.startswith("/dev/")), "")
    interface = ""
    if device and device in positional:
        index = positional.index(device)
        if index + 1 < len(positional):
            interface = positional[index + 1]
    elif positional:
        interface = positional[-1]
    return device, interface
