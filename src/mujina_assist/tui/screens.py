from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.markup import escape
from rich.table import Table

from mujina_assist.models import DEFAULT_MOTOR_IDS
from mujina_assist.services.checks import (
    build_doctor_report,
    detect_real_devices,
    inspect_can_status,
    list_serial_device_candidates,
)
from mujina_assist.services.jobs import list_jobs, live_jobs, recent_jobs, stale_jobs, summarize_job
from mujina_assist.services.policy_manifest import validate_policy_manifest
from mujina_assist.services.safety import SafetyState, evaluate_real_preflight
from mujina_assist.services.zero import validate_zero_profile

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mujina_assist.models import AppPaths, DoctorReport, RuntimeState

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.screen import Screen
    from textual.widgets import DataTable, Footer, Header, Input, Label, ListItem, ListView, Static
except Exception as exc:  # pragma: no cover - exercised only when optional deps are absent
    TEXTUAL_IMPORT_ERROR: Exception | None = exc
else:
    TEXTUAL_IMPORT_ERROR = None


SCREEN_ROUTES: dict[str, str] = {
    "dashboard": "dashboard",
    "setup": "setup",
    "device": "device",
    "can": "can",
    "motor": "motor",
    "zero": "zero",
    "policy": "policy",
    "simulation": "simulation",
    "real-preflight": "real-preflight",
    "real-launch": "real-launch",
    "logs": "logs",
    "help": "help",
}


@dataclass(frozen=True, slots=True)
class FlowItem:
    key: str
    label: str
    status: str
    summary: str


def _status_icon(status: str) -> str:
    return {"ok": "OK", "warn": "WARN", "ng": "NG", "wait": "WAIT", "lock": "LOCK"}.get(status, status.upper())


def _badge(status: str) -> str:
    labels = {
        "ok": "[black on green] OK [/]",
        "warn": "[black on yellow] WARN [/]",
        "ng": "[white on red] NG [/]",
        "wait": "[black on cyan] WAIT [/]",
        "lock": "[white on red] LOCK [/]",
    }
    return labels.get(status, f"[b]{status.upper()}[/b]")


def _yn(value: bool) -> str:
    return "[green]OK[/]" if value else "[red]missing[/]"


def _reason_status(priority: str) -> str:
    return {"P0": "lock", "P1": "warn", "P2": "wait"}.get(priority, "warn")


def _environment_short(report: "DoctorReport") -> str:
    return {
        "vm": "VM/SIM",
        "real": "実機接続",
        "mixed": "実機準備中",
    }.get(report.environment_mode, "未判定")


def _safety_state(
    paths: "AppPaths",
    state: "RuntimeState",
    report: "DoctorReport",
    *,
    can_mode: str = "net",
    operator_checklist_complete: bool = False,
    real_confirmation: str = "",
) -> SafetyState:
    manifest = _active_policy_manifest_validation(report)
    zero_profile = (
        validate_zero_profile(
            paths.active_zero_profile_file,
            expected_upstream_commit=state.workspace_upstream_commit,
            expected_patch_set_hash=state.workspace_patch_set_hash,
        )
        if paths.active_zero_profile_file.exists()
        else None
    )
    return evaluate_real_preflight(
        report,
        state,
        policy_manifest=manifest,
        zero_profile=zero_profile,
        can_mode=can_mode,
        active_job_kinds={job.kind for job in live_jobs(paths)},
        operator_checklist_complete=operator_checklist_complete,
        real_confirmation=real_confirmation,
    )


def _active_policy_manifest_validation(report: "DoctorReport"):
    label = report.active_policy_label or ""
    source = report.active_policy_source or ""
    if label in {"", "未設定", "公式デフォルト"}:
        return None
    normalized_source = source.replace("\\", "/")
    if "default_policy.onnx" in normalized_source:
        return None
    if not source:
        return None
    policy_path = Path(source)
    manifest_path = policy_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        return None
    return validate_policy_manifest(manifest_path, policy_path=policy_path)


def _status_from_reasons(safety: SafetyState, reason_codes: set[str], *, default: str = "ok") -> str:
    matched = [reason for reason in safety.reasons if reason.code in reason_codes]
    if any(reason.priority == "P0" for reason in matched):
        return "lock"
    if any(reason.priority == "P1" for reason in matched):
        return "warn"
    if any(reason.priority == "P2" for reason in matched):
        return "wait"
    return default


def _add_rows(table: Table, rows: "Iterable[tuple[str, str, str]]") -> Table:
    for name, status, summary in rows:
        table.add_row(name, _status_icon(status), summary)
    return table


def _tail(path: Path, max_lines: int = 14) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return [line.rstrip("\n") for line in handle.readlines()[-max_lines:]]
    except OSError:
        return []


if TEXTUAL_IMPORT_ERROR is None:

    class MujinaBaseScreen(Screen):
        BINDINGS = [
            ("escape", "app.pop_screen", "戻る"),
            ("q", "app.request_quit", "終了"),
            ("d", "app.open_screen('dashboard')", "Doctor"),
            ("s", "app.open_screen('setup')", "Setup"),
            ("y", "app.open_screen('simulation')", "SIM"),
            ("p", "app.open_screen('policy')", "Policy"),
            ("m", "app.open_screen('motor')", "Motor"),
            ("z", "app.open_screen('zero')", "Zero"),
            ("c", "app.open_screen('can')", "CAN"),
            ("i", "app.open_screen('device')", "Device"),
            ("r", "app.open_screen('real-preflight')", "Real"),
            ("l", "app.open_screen('logs')", "Logs"),
            ("x", "app.show_repair_command", "Repair"),
            ("?", "app.open_screen('help')", "Help"),
        ]

        title = "Mujina Assist"
        subtitle = ""

        @property
        def paths(self) -> "AppPaths":
            return self.app.paths

        @property
        def state(self) -> "RuntimeState":
            return self.app.state

        def doctor_report(self) -> "DoctorReport":
            self.app.refresh_runtime_state()
            return build_doctor_report(self.paths, self.state)

        def header(self, heading: str, subheading: str = "") -> Static:
            text = f"[b]{heading}[/b]"
            if subheading:
                text += f"\n[dim]{subheading}[/dim]"
            return Static(text, classes="screen-heading")


    class DashboardScreen(MujinaBaseScreen):
        """常時見るメイン画面。"""

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                Static(id="dashboard-title", classes="screen-heading"),
                Horizontal(
                    Vertical(Static(id="status-summary"), Static(id="lock-summary"), Static(id="job-summary"), classes="pane", id="left-pane"),
                    Vertical(ListView(id="flow-list"), Static(id="detail-pane"), classes="pane", id="right-pane"),
                    id="dashboard-grid",
                ),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            self._refresh()
            self.set_interval(2.0, self._refresh)

        def _flow_items(self, report: "DoctorReport", safety: SafetyState) -> list[FlowItem]:
            vm_mode = report.environment_mode == "vm"
            policy_status = _status_from_reasons(
                safety,
                {"policy_unknown", "sim_unverified", "policy_manifest_missing", "policy_manifest_invalid", "policy_manifest_warning"},
                default="ok" if report.active_policy_hash else "warn",
            )
            can_status = _status_from_reasons(
                safety,
                {"can0_missing", "serial_can_missing", "can_unhealthy", "can_warning"},
                default="ok" if report.real_devices.get("can0") else "warn",
            )
            imu_status = _status_from_reasons(safety, {"imu_missing"}, default="ok" if report.imu_port_label else "warn")
            if vm_mode:
                can_status = "wait"
                imu_status = "wait"
                policy_status = "ok" if report.active_policy_hash else "warn"
            zero_status = _status_from_reasons(
                safety,
                {"zero_profile_missing", "zero_profile_invalid", "zero_profile_warning"},
                default="ok",
            )
            if vm_mode:
                zero_status = "wait"
            preflight_status = "lock" if safety.real_launch_locked else ("warn" if safety.standup_locked else "ok")
            return [
                FlowItem("setup", "Setup", "ok" if report.workspace_cloned else "warn", "workspace / upstream 準備"),
                FlowItem("device", "Device", imu_status, "VMでは未接続OK" if vm_mode else "IMU / USB-CAN / joy"),
                FlowItem("can", "CAN", can_status, "VMでは未接続OK" if vm_mode else "SocketCAN / serial CAN"),
                FlowItem("motor", "Motor", "wait", "12軸の zero-gain one-shot query"),
                FlowItem("zero", "Zero", zero_status, "zero profile / post verification"),
                FlowItem("policy", "Policy", policy_status, report.active_policy_label),
                FlowItem("simulation", "Simulation", "ok" if report.sim_ready else "warn", "policy変更後のSIM確認"),
                FlowItem("real-preflight", "Real Preflight", preflight_status, "P0/P1/P2確認"),
                FlowItem("real-launch", "Real Launch", "lock" if safety.real_launch_locked else "warn", "段階起動"),
                FlowItem("logs", "Logs", "wait", "job log tail"),
                FlowItem("help", "Help", "ok", "keybind一覧"),
            ]

        def _refresh(self) -> None:
            report = self.doctor_report()
            safety = _safety_state(self.paths, self.state, report)
            self.query_one("#dashboard-title", Static).update(
                "[b]Mujina Assist[/b]  [dim]実機運用コックピット[/dim]\n"
                f"[dim]{_environment_short(report)}  "
                f"workspace={'ready' if report.workspace_cloned else 'missing'}  "
                f"build={'ready' if report.workspace_built else 'pending'}  "
                f"policy={report.active_policy_label}  "
                f"sim={'verified' if report.sim_ready else 'not verified'}[/dim]"
            )

            status_lines = [
                "[b]System[/b]",
                f"Mode       {_badge('ok' if report.environment_mode == 'real' else 'wait')}  {_environment_short(report)}",
                f"Workspace  {_badge('ok' if report.workspace_cloned else 'warn')}  {'ready' if report.workspace_cloned else 'missing'}",
                f"Build      {_badge('ok' if report.workspace_built else 'warn')}  {'complete' if report.workspace_built else 'pending'}",
                f"Policy     {_badge('ok' if report.active_policy_hash else 'warn')}  {report.active_policy_label}",
                f"SIM        {_badge('ok' if report.sim_ready else 'warn')}  {report.sim_verified_at or 'not verified'}",
                "",
                "[b]Devices[/b]",
                f"IMU        {_badge('ok' if report.imu_port_label and not report.imu_port_fallback else 'warn')}  {report.imu_port_label or 'missing'}",
                f"CAN        {_badge('ok' if report.real_devices.get('can0') or report.real_devices.get('/dev/usb_can') else 'warn')}  can0={_yn(report.real_devices.get('can0', False))} / usb={_yn(report.real_devices.get('/dev/usb_can', False))}",
                f"Joy        {_badge('ok' if report.real_devices.get('/dev/input/js0') else 'warn')}  {_yn(report.real_devices.get('/dev/input/js0', False))}",
            ]
            if report.recommendation:
                status_lines.extend(["", f"[b]Next[/b]  {report.recommendation}"])
            self.query_one("#status-summary", Static).update("\n".join(status_lines))

            locks = ["[b]Real Launch Locks[/b]  [dim]実機起動だけの制約です[/dim]"]
            if report.environment_mode == "vm":
                locks.append("[cyan]- VM/SIM確認中: IMU/CAN未接続は故障ではありません。[/]")
            if safety.manual_recovery_required:
                locks.append(f"{_badge('lock')} P0 manual recovery: {safety.manual_recovery_summary or '未解決'}")
            for reason in safety.reasons:
                locks.append(f"{_badge(_reason_status(reason.priority))} {reason.priority} {reason.code}: {reason.message}")
            if len(locks) == 1:
                locks.append("[green]- P0 blockなし。Preflightへ進めます。[/]")
            self.query_one("#lock-summary", Static).update("\n".join(locks[:7]))

            jobs = live_jobs(self.paths)
            stale = stale_jobs(self.paths)
            job_lines = ["[b]Running Jobs[/b]"]
            if jobs:
                job_lines.extend(f"- {job.name} ({job.kind})" for job in jobs[:6])
            else:
                job_lines.append("- 実行中ジョブなし")
            if stale:
                job_lines.append("")
                job_lines.append("[b]Needs Attention[/b]")
                job_lines.extend(f"- {job.name}: {job.status} stale" for job in stale[:3])
            self.query_one("#job-summary", Static).update("\n".join(job_lines))

            flow = self.query_one("#flow-list", ListView)
            highlighted_key = ""
            if flow.highlighted_child is not None:
                highlighted_key = getattr(flow.highlighted_child, "mujina_key", "")
            flow.clear()
            new_index = 0
            for index, item in enumerate(self._flow_items(report, safety)):
                row = ListItem(Label(f"{_status_icon(item.status):<4} {item.label}"))
                row.mujina_key = item.key
                flow.append(row)
                if item.key == highlighted_key:
                    new_index = index
            flow.index = new_index

            details = ["[b]Doctor Checks[/b]"]
            details.extend(f"- {_badge(check.status)} [b]{check.label}[/b]: {check.summary}" for check in report.checks)
            if safety.reasons:
                details.append("\n[b]Safety Reasons[/b]")
                details.extend(f"- {reason.priority} {reason.code}: {reason.message}" for reason in safety.reasons[:8])
            if report.notes:
                details.append("\n[b]Notes[/b]")
                details.extend(f"- {note}" for note in report.notes[:5])
            self.query_one("#detail-pane", Static).update("\n".join(details))

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            key = getattr(event.item, "mujina_key", "")
            if key:
                self.app.action_open_screen(key)


    class SetupFlowScreen(MujinaBaseScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("u", "start_setup", "Setup開始"),
            ("b", "start_build", "Build開始"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Setup Flow", "初回セットアップからSIM準備までの流れ"),
                DataTable(id="setup-table"),
                Static(id="setup-actions"),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            report = self.doctor_report()
            table = self.query_one("#setup-table", DataTable)
            table.add_columns("Step", "Status", "Summary")
            rows = [
                ("OS確認", "ok" if report.ubuntu_24_04 else "warn", report.os_label),
                ("ROS 2 Jazzy確認", "ok" if report.ros_installed else "ng", "導入済み" if report.ros_installed else "未導入"),
                ("workspace準備", "ok" if report.workspace_cloned else "ng", "clone済み" if report.workspace_cloned else "未作成"),
                ("patch適用状態確認", "ok" if self.state.workspace_patch_set_hash else "warn", self.state.workspace_patch_set_hash or "patch queue なし"),
                ("colcon build", "ok" if report.workspace_built else "warn", "完了" if report.workspace_built else "未実行"),
                ("udev / dialout", "warn", "実機用設定を確認"),
                ("device確認", "ok" if report.imu_port_label else "warn", report.imu_port_label or "IMU未検出"),
                ("SIM準備", "ok" if report.sim_ready else "warn", "確認済み" if report.sim_ready else "未確認"),
            ]
            _add_rows(table, rows)
            self.query_one("#setup-actions", Static).update(
                "\n".join(
                    [
                        "[b]Actions[/b]",
                        "u: 初回セットアップ job を起動します（実機 udev/dialout は含めません）。",
                        "b: workspace build job を起動します。",
                        "実機用 udev/dialout を設定する場合は確認付き CLI: `./start.sh setup` を使ってください。",
                    ]
                )
            )

        def action_start_setup(self) -> None:
            self.app.launch_tui_job(kind="setup", name="初回セットアップ", payload={"skip_upgrade": False, "setup_real_devices": False})

        def action_start_build(self) -> None:
            self.app.launch_tui_job(kind="build", name="workspace ビルド")


    class DeviceScreen(MujinaBaseScreen):
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(self.header("Device", "固定名デバイスと候補一覧"), DataTable(id="device-table"), Static(id="serial-list"), classes="screen-body")
            yield Footer()

        def on_mount(self) -> None:
            devices = detect_real_devices()
            report = self.doctor_report()
            table = self.query_one("#device-table", DataTable)
            table.add_columns("Device", "Status", "Summary")
            rows = [
                ("/dev/rt_usb_imu", "ok" if devices.get("/dev/rt_usb_imu") else "warn", report.imu_port_label or "missing"),
                ("/dev/usb_can", "ok" if devices.get("/dev/usb_can") else "warn", "serial CAN fixed symlink"),
                ("can0", "ok" if devices.get("can0") else "warn", "SocketCAN interface"),
                ("/dev/input/js0", "ok" if devices.get("/dev/input/js0") else "warn", "gamepad"),
            ]
            _add_rows(table, rows)
            candidates = list_serial_device_candidates()
            text = "[b]Serial candidates[/b]\n" + ("\n".join(f"- {item}" for item in candidates[:12]) if candidates else "- なし")
            self.query_one("#serial-list", Static).update(text)


    class CANScreen(MujinaBaseScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("n", "start_can_net", "CAN net"),
            ("u", "start_can_serial", "CAN serial"),
            ("f5", "refresh", "更新"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("CAN", "can0 / slcand / statistics"),
                DataTable(id="can-table"),
                Static(id="can-raw"),
                Static(id="can-actions"),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            self._refresh()
            self.set_interval(3.0, self._refresh)

        def _refresh(self) -> None:
            status = inspect_can_status()
            table = self.query_one("#can-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Item", "Value")
            for key in ("present", "operstate", "controller_state", "txqueuelen", "ok", "warn"):
                table.add_row(key, str(status.get(key, "")))
            raw = str(status.get("raw") or "")
            self.query_one("#can-raw", Static).update("[b]Raw[/b]\n" + (raw[:2000] if raw else "ip details unavailable"))
            self.query_one("#can-actions", Static).update(
                "\n".join(
                    [
                        "[b]Actions[/b]",
                        "n: network CAN setup job (`can_setup_net.sh`) を起動します。",
                        "u: serial CAN setup job (`can_setup_serial.sh`) を起動します。",
                        "F5: CAN状態を再取得します。",
                        "diagnostic mode では CAN状態表示と setup 手順確認までに留め、実機起動へは進めません。",
                    ]
                )
            )

        def action_refresh(self) -> None:
            self._refresh()

        def action_start_can_net(self) -> None:
            self.app.launch_tui_job(kind="can_setup", name="CAN setup (network)", payload={"can_mode": "net"})

        def action_start_can_serial(self) -> None:
            self.app.launch_tui_job(kind="can_setup", name="CAN setup (serial)", payload={"can_mode": "serial"})


    class MotorScreen(MujinaBaseScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("n", "read_net", "Read net"),
            ("u", "read_serial", "Read serial"),
            ("g", "diagnostics", "診断CLI"),
        ]

        JOINTS = [
            ("RL_collar_joint", 10),
            ("RL_hip_joint", 11),
            ("RL_knee_joint", 12),
            ("RR_collar_joint", 7),
            ("RR_hip_joint", 8),
            ("RR_knee_joint", 9),
            ("FL_collar_joint", 4),
            ("FL_hip_joint", 5),
            ("FL_knee_joint", 6),
            ("FR_collar_joint", 1),
            ("FR_hip_joint", 2),
            ("FR_knee_joint", 3),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Motor", "12軸 zero-gain one-shot query / read-only job"),
                DataTable(id="motor-table"),
                Static(id="motor-actions"),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#motor-table", DataTable)
            table.add_columns("Joint", "ID", "Resp", "Pos(rad)", "Vel(rad/s)", "Temp(C)", "Err", "Zero")
            for joint, motor_id in self.JOINTS:
                table.add_row(joint, str(motor_id), "WAIT", "-", "-", "-", "-", "unknown")
            self.query_one("#motor-actions", Static).update(
                "\n".join(
                    [
                        "[b]Actions[/b]",
                        "n: network CAN で全12軸 read-only motor query job を起動します。",
                        "u: serial CAN で全12軸 read-only motor query job を起動します。",
                        "g: 確認付き CLI `./start.sh motor-diagnostics` の利用を案内します。",
                        "表示は最後のscan値ではなく操作入口です。応答値は Logs の job log で確認します。",
                    ]
                )
            )

        def _start_read(self, can_mode: str) -> None:
            self.app.launch_tui_job(
                kind="motor_read",
                name=f"モータ確認 ({can_mode})",
                payload={"ids": list(DEFAULT_MOTOR_IDS), "can_mode": can_mode},
            )

        def action_read_net(self) -> None:
            self._start_read("net")

        def action_read_serial(self) -> None:
            self._start_read("serial")

        def action_diagnostics(self) -> None:
            self.app.show_cli_required("./start.sh motor-diagnostics", "自動診断はCAN選択と失敗時の案内をCLIで確認してください")


    class SkeletonScreen(MujinaBaseScreen):
        SCREEN_TITLE = "Screen"
        SCREEN_SUMMARY = ""
        ITEMS: list[tuple[str, str, str]] = []

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(self.header(self.SCREEN_TITLE, self.SCREEN_SUMMARY), DataTable(id="skeleton-table"), Static(id="skeleton-note"), classes="screen-body")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#skeleton-table", DataTable)
            table.add_columns("Item", "Status", "Summary")
            _add_rows(table, self.ITEMS)
            self.query_one("#skeleton-note", Static).update(
                "[yellow]未接続または確認付きCLIに委譲する操作があります。ここに表示される WAIT/LOCK だけを安全判定として扱わないでください。[/yellow]\n"
                "[dim]実際のロック状態は Dashboard / Real Preflight の evaluate_real_preflight 表示を確認してください。[/dim]"
            )


    class ZeroWizardScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("x", "zero_cli", "Zero CLI"),
            ("n", "probe_net", "Probe net"),
            ("u", "probe_serial", "Probe serial"),
        ]
        SCREEN_TITLE = "Zero Wizard"
        SCREEN_SUMMARY = "pre-scan / confirmation / upstream zero / post verification"
        ITEMS = [
            ("CAN状態確認", "wait", "can0 healthy required"),
            ("対象motor選択", "wait", "all / leg / single"),
            ("zero-gain one-shot query", "wait", "kp/kd/tau=0 の一回問い合わせ"),
            ("operator checklist", "lock", "所定姿勢と停止手段"),
            ("upstream zero script", "lock", "motor_set_zero_position.py"),
            ("zero profile保存", "wait", "post-zero verification後に保存"),
        ]

        def action_zero_cli(self) -> None:
            self.app.show_cli_required("./start.sh zero", "原点書き込みは所定姿勢チェックと `ZERO ...` 入力が必要です")

        def action_probe_net(self) -> None:
            self.app.launch_tui_job(
                kind="motor_read",
                name="Zero前 motor probe (network)",
                payload={"ids": list(DEFAULT_MOTOR_IDS), "can_mode": "net"},
            )

        def action_probe_serial(self) -> None:
            self.app.launch_tui_job(
                kind="motor_read",
                name="Zero前 motor probe (serial)",
                payload={"ids": list(DEFAULT_MOTOR_IDS), "can_mode": "serial"},
            )


    class PolicyScreen(MujinaBaseScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("t", "policy_test", "ONNX test"),
            ("a", "arm_policy", "候補確認"),
            ("w", "policy_switch", "切替"),
            ("f5", "refresh", "更新"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Policy", "default / cache / USB ONNX を自動検出"),
                Horizontal(
                    Vertical(ListView(id="policy-list"), Static(id="policy-actions"), classes="pane"),
                    Vertical(Static(id="policy-detail"), Static(id="policy-warning"), classes="pane"),
                ),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            self._armed_key: tuple[str, str, str] | None = None
            self._candidates = []
            self._refresh()

        def _candidate_key(self, candidate: PolicyCandidate) -> tuple[str, str, str]:
            return (candidate.policy_hash or "", str(candidate.path), candidate.source_type)

        def _armed_candidate(self) -> PolicyCandidate | None:
            if self._armed_key is None:
                return None
            for candidate in self._candidates:
                if self._candidate_key(candidate) == self._armed_key:
                    return candidate
            return None

        def _refresh(self) -> None:
            report = self.doctor_report()
            self._candidates = self.app.policy_candidates()
            policy_list = self.query_one("#policy-list", ListView)
            previous_index = policy_list.index or 0
            policy_list.clear()
            for index, candidate in enumerate(self._candidates):
                chips: list[str] = []
                if candidate.is_active:
                    chips.append("使用中")
                if candidate.sim_verified:
                    chips.append("SIM済")
                if candidate.source_type == "usb":
                    chips.append("USB")
                if candidate.manifest_path and candidate.manifest_path.exists():
                    chips.append("manifest")
                elif candidate.source_type in {"usb", "path"}:
                    chips.append("manifestなし")
                prefix = "ARM " if self._armed_key == self._candidate_key(candidate) else ""
                suffix = f" [{' / '.join(chips)}]" if chips else ""
                policy_list.append(ListItem(Label(f"{prefix}{escape(candidate.label)}{suffix}")))
            if self._candidates:
                policy_list.index = min(previous_index, len(self._candidates) - 1)
            self._update_detail()
            self.query_one("#policy-actions", Static).update(
                "\n".join(
                    [
                        "[b]Actions[/b]",
                        "↑/↓: policy候補を選択",
                        "a: 選択候補を切替対象として確認",
                        "w: ARM済み候補へ切替jobを起動",
                        "t: 現在policyのONNX読み込みテスト",
                        "F5: USB/cache候補を再スキャン",
                        "",
                        "[dim]USB上の .onnx は自動検出します。外部policyはmanifest付きだけTUI切替できます。[/dim]",
                        f"[dim]current: {escape(report.active_policy_label)} / SIM {'verified' if report.sim_ready else 'not verified'}[/dim]",
                    ]
                )
            )

        def _selected_index(self) -> int | None:
            if not self._candidates:
                return None
            index = self.query_one("#policy-list", ListView).index
            if index is None:
                return 0
            return max(0, min(index, len(self._candidates) - 1))

        def _selected_candidate(self):
            index = self._selected_index()
            return self._candidates[index] if index is not None else None

        def _update_detail(self) -> None:
            candidate = self._selected_candidate()
            if candidate is None:
                self.query_one("#policy-detail", Static).update("[b]候補なし[/b]\nUSBを挿すか、先にSetup/Buildを完了してください。")
                self.query_one("#policy-warning", Static).update("")
                return
            manifest = str(candidate.manifest_path) if candidate.manifest_path else "なし"
            lines = [
                f"[b]{escape(candidate.label)}[/b]",
                f"source: {escape(candidate.source_type)}",
                f"path: {escape(str(candidate.path))}",
                f"manifest: {escape(manifest)}",
                f"hash: {(candidate.policy_hash or '')[:12] or '未計算'}",
                f"size: {candidate.size_bytes / (1024 * 1024):.1f} MB" if candidate.size_bytes else "size: unknown",
            ]
            if candidate.description:
                lines.append(f"description: {escape(candidate.description)}")
            if candidate.is_active:
                lines.append("[green]現在使用中です。[/]")
            if candidate.sim_verified:
                lines.append("[green]このpolicyはSIM確認済みです。[/]")
            self.query_one("#policy-detail", Static).update("\n".join(lines))
            warnings = []
            if candidate.source_type in {"usb", "path"} and not (candidate.manifest_path and candidate.manifest_path.exists()):
                warnings.append("[red]外部policyにmanifestがありません。TUI切替はロックします。[/]")
            if self._armed_key is not None:
                armed = self._armed_candidate()
                if armed is None:
                    self._armed_key = None
                    warnings.append("[yellow]ARM済み候補が見つかりません。再スキャン後に選び直してください。[/]")
                else:
                    warnings.append(f"[yellow]ARM済み: {escape(armed.label)}。wで切替jobを起動します。切替後はSIM確認が無効になります。[/]")
            self.query_one("#policy-warning", Static).update("\n".join(warnings))

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            self._update_detail()

        def action_refresh(self) -> None:
            self._armed_key = None
            self._refresh()

        def action_policy_test(self) -> None:
            self.app.launch_tui_job(kind="policy_test", name="ONNX 読み込みテスト")

        def action_arm_policy(self) -> None:
            index = self._selected_index()
            if index is None:
                self.app.notify("切替候補がありません。USB/cacheを確認してください。", severity="warning", timeout=8)
                return
            candidate = self._candidates[index]
            if candidate.source_type in {"usb", "path"} and not (candidate.manifest_path and candidate.manifest_path.exists()):
                self.app.notify("manifestなし外部policyはTUIでARMできません。./start.sh policy で明示確認してください。", severity="error", timeout=10)
                return
            self._armed_key = self._candidate_key(candidate)
            self._refresh()

        def action_policy_switch(self) -> None:
            if self._armed_key is None:
                self.app.notify("先に a で切替候補をARMしてください。", severity="warning", timeout=8)
                return
            candidate = self._armed_candidate()
            if candidate is None:
                self.app.notify("候補一覧が変わっています。F5で再スキャンしてください。", severity="warning", timeout=8)
                return
            launched = self.app.launch_policy_switch_from_tui(candidate)
            if launched:
                self._armed_key = None
            self._refresh()


    class SimulationScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("o", "start_sim", "SIM起動"),
            ("v", "mark_verified", "確認済み"),
            ("f5", "refresh", "更新"),
        ]
        SCREEN_TITLE = "Simulation"
        SCREEN_SUMMARY = "policy変更後の実機前確認"

        def on_mount(self) -> None:
            self._refresh()
            self.set_interval(2.0, self._refresh)

        def _refresh(self) -> None:
            report = self.doctor_report()
            jobs = live_jobs(self.paths)
            running_kinds = {job.kind for job in jobs}
            table = self.query_one("#skeleton-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Item", "Status", "Summary")
            rows = [
                ("workspace", "ok" if report.workspace_cloned else "warn", "ready" if report.workspace_cloned else "Setupで初回セットアップ"),
                ("build", "ok" if report.workspace_built else "warn", "complete" if report.workspace_built else "Setupでbuild"),
                ("policy", "ok" if report.active_policy_hash else "warn", report.active_policy_label),
                ("SIM main", "ok" if "sim_main" in running_kinds else "wait", "mujina_main --sim"),
                ("joy node", "ok" if "sim_joy" in running_kinds else "wait", "joy_linux_node"),
                ("SIM verified", "ok" if report.sim_ready else "lock", report.sim_verified_at or "未確認"),
            ]
            _add_rows(table, rows)
            self.query_one("#skeleton-note", Static).update(
                "\n".join(
                    [
                        "[b]Actions[/b]",
                        "o: SIM 本体と joy ノードをペアで起動します。",
                        "v: MuJoCoの姿勢とgamepad入力を確認した後、現在のpolicy/workspaceをSIM確認済みにします。",
                        "F5: 状態を更新します。",
                        "",
                        "[dim]CLIで同じ操作をする場合は `./start.sh sim` / `./start.sh sim-verified` です。[/dim]",
                    ]
                )
            )

        def action_refresh(self) -> None:
            self._refresh()

        def action_start_sim(self) -> None:
            self.app.launch_sim_from_tui()
            self._refresh()

        def action_mark_verified(self) -> None:
            self.app.mark_sim_verified_from_tui()
            self._refresh()


    class RealPreflightScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("f", "preflight_cli", "Preflight CLI"),
        ]
        SCREEN_TITLE = "Real Preflight"
        SCREEN_SUMMARY = "P0/P1/P2 lock reasons"

        def on_mount(self) -> None:
            self._refresh()
            self.set_interval(2.0, self._refresh)

        def _refresh(self) -> None:
            report = self.doctor_report()
            safety = _safety_state(self.paths, self.state, report)
            table = self.query_one("#skeleton-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Priority", "Status", "Code", "Summary")
            if safety.reasons:
                for reason in safety.reasons:
                    table.add_row(reason.priority, _status_icon(_reason_status(reason.priority)), reason.code, reason.message)
            else:
                table.add_row("-", "OK", "clear", "P0/P1/P2 reason はありません。")
            note = "[b]Real Launch[/b] " + (_badge("lock") if safety.real_launch_locked else _badge("ok"))
            note += "  [b]Standup[/b] " + (_badge("lock") if safety.standup_locked else _badge("ok"))
            note += "  [b]Walk[/b] " + (_badge("lock") if safety.walk_locked else _badge("ok"))
            if safety.manual_recovery_required:
                note += f"\n[red]manual recovery required:[/] {safety.manual_recovery_summary or '未解決'}"
            note += "\n\nf: 確認付き CLI `./start.sh preflight` を起動して CAN mode を選びます。"
            self.query_one("#skeleton-note", Static).update(note)

        def action_preflight_cli(self) -> None:
            self.app.show_cli_required("./start.sh preflight", "preflightはCAN mode選択をCLIで確認してください")


    class RealLaunchScreen(MujinaBaseScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("n", "select_net", "CAN net"),
            ("ctrl+n", "select_net", "CAN net"),
            ("u", "select_serial", "CAN serial"),
            ("ctrl+u", "select_serial", "CAN serial"),
            ("1", "toggle_pose", "姿勢/停止"),
            ("f1", "toggle_pose", "姿勢/停止"),
            ("2", "toggle_gamepad", "gamepad"),
            ("f2", "toggle_gamepad", "gamepad"),
            ("3", "toggle_policy", "policy理解"),
            ("f3", "toggle_policy", "policy理解"),
            ("ctrl+e", "execute_real", "起動"),
            ("f", "open_preflight", "Preflight"),
            ("f5", "refresh", "更新"),
        ]
        SCREEN_TITLE = "Real Launch"
        SCREEN_SUMMARY = "段階起動"

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Real Launch", "P0/P1/P2確認後に IMU -> main -> joy を段階起動"),
                DataTable(id="real-launch-table"),
                Static(id="real-checklist"),
                Input(placeholder="実機起動する場合だけ REAL と入力", id="real-confirm"),
                Static(id="real-launch-note"),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            self._can_mode = "net"
            self._pose_ok = False
            self._gamepad_ok = False
            self._policy_ok = False
            self._refresh()
            self.set_interval(2.0, self._refresh)

        def _refresh(self) -> None:
            report = self.doctor_report()
            checklist_complete = self._pose_ok and self._gamepad_ok and self._policy_ok
            try:
                real_confirmation = self.query_one("#real-confirm", Input).value.strip()
            except Exception:
                real_confirmation = ""
            safety = _safety_state(
                self.paths,
                self.state,
                report,
                can_mode=self._can_mode,
                operator_checklist_complete=checklist_complete,
                real_confirmation=real_confirmation,
            )
            table = self.query_one("#real-launch-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Gate", "Status", "Summary")
            rows = [
                ("CAN mode", "ok" if self._can_mode in {"net", "serial"} else "warn", self._can_mode),
                ("workspace", "ok" if report.workspace_built else "lock", "build済み" if report.workspace_built else "build未完了"),
                ("policy", _status_from_reasons(safety, {"policy_unknown", "policy_manifest_missing", "policy_manifest_invalid"}, default="ok"), report.active_policy_label),
                ("SIM verified", "ok" if report.sim_ready else "lock", report.sim_verified_at or "未確認"),
                ("zero profile", _status_from_reasons(safety, {"zero_profile_missing", "zero_profile_invalid", "zero_profile_warning"}), "verified required"),
                ("IMU", "ok" if report.imu_port_label and not report.imu_port_fallback else "lock", report.imu_port_label or "missing"),
                ("CAN", _status_from_reasons(safety, {"can0_missing", "serial_can_missing", "serial_can0_missing", "slcand_missing", "can_unhealthy"}, default="ok"), "can0 / usb_can"),
                ("joy", "ok" if report.real_devices.get("/dev/input/js0") else "warn", "/dev/input/js0"),
            ]
            blocking_codes = [reason.code for reason in safety.reasons if reason.code not in {"operator_checklist", "real_confirmation"}]
            final_codes = [reason.code for reason in safety.reasons if reason.code in {"operator_checklist", "real_confirmation"}]
            rows.append(
                (
                    "Launch locks",
                    "lock" if blocking_codes else "warn" if final_codes else "ok",
                    ", ".join(blocking_codes or final_codes) or "clear",
                )
            )
            _add_rows(table, rows)
            checks = [
                f"1 [{'x' if self._pose_ok else ' '}] 原点/STANDBY姿勢、周囲離隔、補助者、物理停止手段",
                f"2 [{'x' if self._gamepad_ok else ' '}] gamepad X mode / MODE LED OFF / /joy応答",
                f"3 [{'x' if self._policy_ok else ' '}] policyの由来、学習条件、robot revisionを把握",
            ]
            self.query_one("#real-checklist", Static).update("[b]Operator Checklist[/b]\n" + "\n".join(checks))
            action_lines = [
                "[b]Actions[/b]",
                "n/u または Ctrl+N/Ctrl+U: CAN modeを net / serial に切替",
                "1/2/3 または F1/F2/F3: checklistをtoggle",
                "REAL入力後 Enter / Ctrl+E: CAN setup -> 12軸zero-gain scan -> 最終preflight -> 段階起動",
                "f: Real Preflight画面へ",
            ]
            if blocking_codes:
                action_lines.append("[red]起動不可: " + ", ".join(blocking_codes[:6]) + "[/]")
                action_lines.append("[dim]P1/P2も実機起動前に解消します。[/dim]")
            elif final_codes:
                action_lines.append("[yellow]残りは最終確認のみです。checklistとREAL入力後に Enter / Ctrl+E で起動できます。[/]")
            else:
                action_lines.append("[green]実機起動条件は揃っています。Enter / Ctrl+E で段階起動できます。[/]")
            self.query_one("#real-launch-note", Static).update("\n".join(action_lines))

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "real-confirm":
                self.action_execute_real()

        def action_refresh(self) -> None:
            self._refresh()

        def action_open_preflight(self) -> None:
            self.app.action_open_screen("real-preflight")

        def action_select_net(self) -> None:
            self._can_mode = "net"
            self._refresh()

        def action_select_serial(self) -> None:
            self._can_mode = "serial"
            self._refresh()

        def action_toggle_pose(self) -> None:
            self._pose_ok = not self._pose_ok
            self._refresh()

        def action_toggle_gamepad(self) -> None:
            self._gamepad_ok = not self._gamepad_ok
            self._refresh()

        def action_toggle_policy(self) -> None:
            self._policy_ok = not self._policy_ok
            self._refresh()

        def action_execute_real(self) -> None:
            confirm = self.query_one("#real-confirm", Input).value.strip()
            checklist_complete = self._pose_ok and self._gamepad_ok and self._policy_ok
            self.app.launch_real_from_tui(
                can_mode=self._can_mode,
                real_confirmation=confirm,
                checklist_complete=checklist_complete,
            )
            self._refresh()


    class LogScreen(MujinaBaseScreen):
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(self.header("Logs", "job履歴と最新ログ末尾"), DataTable(id="jobs-table"), Static(id="log-tail"), classes="screen-body")
            yield Footer()

        def on_mount(self) -> None:
            jobs = list_jobs(self.paths)
            table = self.query_one("#jobs-table", DataTable)
            stale = {job.job_id for job in stale_jobs(self.paths)}
            table.add_columns("Job", "Status", "Log")
            for job in jobs[:12]:
                status = f"{job.status} / stale" if job.job_id in stale else job.status
                table.add_row(job.name, status, Path(job.log_path).name)
            recent = recent_jobs(self.paths, limit=1)
            if recent:
                lines = _tail(Path(recent[0].log_path))
                body = "\n".join(lines) if lines else "ログはまだありません。"
                self.query_one("#log-tail", Static).update(f"[b]{summarize_job(recent[0])}[/b]\n{body}")
            else:
                self.query_one("#log-tail", Static).update("まだジョブ履歴がありません。")


    class HelpScreen(MujinaBaseScreen):
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Help", "主要keybind"),
                Static(
                    "\n".join(
                        [
                            "[b]Navigation[/b]",
                            "Enter: Dashboard の選択中 flow 項目を開く",
                            "d: Dashboard / Doctor",
                            "s: Setup",
                            "y: Simulation",
                            "p: Policy",
                            "m: Motor",
                            "z: Zero Wizard",
                            "c: CAN",
                            "i: Device",
                            "r: Real Preflight",
                            "l: Logs",
                            "x: Repair command",
                            "?: Help",
                            "q: Quit",
                            "",
                            "[b]Legacy[/b]",
                            "旧番号メニューは `mujina-assist menu --legacy` または `mujina-assist legacy-menu` で起動できます。",
                        ]
                    )
                ),
                classes="screen-body",
            )
            yield Footer()


    SCREEN_CLASSES = {
        "dashboard": DashboardScreen,
        "setup": SetupFlowScreen,
        "device": DeviceScreen,
        "can": CANScreen,
        "motor": MotorScreen,
        "zero": ZeroWizardScreen,
        "policy": PolicyScreen,
        "simulation": SimulationScreen,
        "real-preflight": RealPreflightScreen,
        "real-launch": RealLaunchScreen,
        "logs": LogScreen,
        "help": HelpScreen,
    }
else:
    SCREEN_CLASSES = {}
