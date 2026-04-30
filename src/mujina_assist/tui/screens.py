from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table

from mujina_assist.models import DEFAULT_MOTOR_IDS
from mujina_assist.services.checks import (
    build_doctor_report,
    detect_real_devices,
    inspect_can_status,
    list_serial_device_candidates,
)
from mujina_assist.services.jobs import active_jobs, list_jobs, recent_jobs, stale_jobs, summarize_job
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
    from textual.widgets import DataTable, Footer, Header, Label, ListItem, ListView, Static
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


def _safety_state(paths: "AppPaths", state: "RuntimeState", report: "DoctorReport") -> SafetyState:
    manifest = _active_policy_manifest_validation(report)
    zero_profile = validate_zero_profile(paths.active_zero_profile_file) if paths.active_zero_profile_file.exists() else None
    return evaluate_real_preflight(
        report,
        state,
        policy_manifest=manifest,
        zero_profile=zero_profile,
        can_mode="net",
        active_job_kinds={job.kind for job in active_jobs(paths)},
        operator_checklist_complete=False,
        real_confirmation="",
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
            ("p", "app.open_screen('policy')", "Policy"),
            ("m", "app.open_screen('motor')", "Motor"),
            ("z", "app.open_screen('zero')", "Zero"),
            ("c", "app.open_screen('can')", "CAN"),
            ("i", "app.open_screen('device')", "Device"),
            ("r", "app.open_screen('real-preflight')", "Real"),
            ("l", "app.open_screen('logs')", "Logs"),
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
            zero_status = _status_from_reasons(
                safety,
                {"zero_profile_missing", "zero_profile_invalid", "zero_profile_warning"},
                default="ok",
            )
            preflight_status = "lock" if safety.real_launch_locked else ("warn" if safety.standup_locked else "ok")
            return [
                FlowItem("setup", "Setup", "ok" if report.workspace_cloned else "warn", "workspace / upstream 準備"),
                FlowItem("device", "Device", imu_status, "IMU / USB-CAN / joy"),
                FlowItem("can", "CAN", can_status, "SocketCAN / serial CAN"),
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
                f"[dim]workspace={'ready' if report.workspace_cloned else 'missing'}  "
                f"build={'ready' if report.workspace_built else 'pending'}  "
                f"policy={report.active_policy_label}  "
                f"sim={'verified' if report.sim_ready else 'not verified'}[/dim]"
            )

            status_lines = [
                "[b]System[/b]",
                f"Workspace  {_badge('ok' if report.workspace_cloned else 'warn')}  {'ready' if report.workspace_cloned else 'missing'}",
                f"Build      {_badge('ok' if report.workspace_built else 'warn')}  {'complete' if report.workspace_built else 'pending'}",
                f"Policy     {_badge('ok' if report.active_policy_hash else 'warn')}  {report.active_policy_label}",
                f"SIM        {_badge('ok' if report.sim_ready else 'lock')}  {report.sim_verified_at or 'not verified'}",
                "",
                "[b]Devices[/b]",
                f"IMU        {_badge('ok' if report.imu_port_label and not report.imu_port_fallback else 'warn')}  {report.imu_port_label or 'missing'}",
                f"CAN        {_badge('ok' if report.real_devices.get('can0') or report.real_devices.get('/dev/usb_can') else 'warn')}  can0={_yn(report.real_devices.get('can0', False))} / usb={_yn(report.real_devices.get('/dev/usb_can', False))}",
                f"Joy        {_badge('ok' if report.real_devices.get('/dev/input/js0') else 'warn')}  {_yn(report.real_devices.get('/dev/input/js0', False))}",
            ]
            if report.recommendation:
                status_lines.extend(["", f"[b]Next[/b]  {report.recommendation}"])
            self.query_one("#status-summary", Static).update("\n".join(status_lines))

            locks = ["[b]Launch Locks[/b]  [dim]evaluate_real_preflight[/dim]"]
            if safety.manual_recovery_required:
                locks.append(f"{_badge('lock')} P0 manual recovery: {safety.manual_recovery_summary or '未解決'}")
            for reason in safety.reasons:
                locks.append(f"{_badge(_reason_status(reason.priority))} {reason.priority} {reason.code}: {reason.message}")
            if len(locks) == 1:
                locks.append("[green]- P0 blockなし。Preflightへ進めます。[/]")
            self.query_one("#lock-summary", Static).update("\n".join(locks[:7]))

            jobs = active_jobs(self.paths)
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
                row = ListItem(Label(f"{_status_icon(item.status):<4} {item.label:<15} {item.summary}"))
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


    class PolicyScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("t", "policy_test", "ONNX test"),
            ("w", "policy_switch", "Switch CLI"),
        ]
        SCREEN_TITLE = "Policy"
        SCREEN_SUMMARY = "default / USB / cache / manifest / SIM verified"
        ITEMS = [
            ("policy一覧", "wait", "default, cache, USB候補"),
            ("ONNX shape check", "wait", "[1,45] -> [1,12]"),
            ("manifest validation", "lock", "external policyはmanifest必須"),
            ("switch rollback", "wait", "default backupから復旧"),
            ("SIM verified reset", "lock", "切替後は再確認"),
        ]

        def action_policy_test(self) -> None:
            self.app.launch_tui_job(kind="policy_test", name="ONNX 読み込みテスト")

        def action_policy_switch(self) -> None:
            self.app.show_cli_required("./start.sh policy", "policy切替は候補選択とmanifest確認が必要です")


    class SimulationScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("x", "sim_cli", "SIM CLI"),
            ("v", "sim_verified_cli", "Verified CLI"),
        ]
        SCREEN_TITLE = "Simulation"
        SCREEN_SUMMARY = "policy変更後の実機前確認"
        ITEMS = [
            ("SIM main", "wait", "mujina_main --sim"),
            ("joy node", "wait", "input応答確認"),
            ("topic watcher", "wait", "/robot_mode /motor_state /joint_states"),
            ("SIM verified", "lock", "live session確認後に付与"),
        ]

        def action_sim_cli(self) -> None:
            self.app.show_cli_required("./start.sh sim", "SIMはmain/joyのペア起動と別ターミナル確認が必要です")

        def action_sim_verified_cli(self) -> None:
            self.app.show_cli_required("./start.sh sim-verified", "SIM確認済み付与はlive session確認後にCLIで実行します")


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


    class RealLaunchScreen(SkeletonScreen):
        BINDINGS = MujinaBaseScreen.BINDINGS + [
            ("f", "open_preflight", "Preflight"),
            ("x", "robot_cli", "Robot CLI"),
        ]
        SCREEN_TITLE = "Real Launch"
        SCREEN_SUMMARY = "段階起動"
        ITEMS = [
            ("CAN setup", "wait", "net / serial"),
            ("IMU node", "wait", "wait /imu/data"),
            ("zero-gain motor query", "lock", "main起動前"),
            ("mujina_main", "lock", "wait /robot_mode"),
            ("joy node", "lock", "wait /joy"),
            ("standup unlock", "lock", "operator確認後"),
        ]

        def action_open_preflight(self) -> None:
            self.app.action_open_screen("real-preflight")

        def action_robot_cli(self) -> None:
            self.app.show_cli_required("./start.sh robot", "実機起動はP0/P1/P2、operator checklist、REAL入力をCLIで通します")


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
                            "p: Policy",
                            "m: Motor",
                            "z: Zero Wizard",
                            "c: CAN",
                            "i: Device",
                            "r: Real Preflight",
                            "l: Logs",
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
