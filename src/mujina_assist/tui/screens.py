from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table

from mujina_assist.services.checks import (
    build_doctor_report,
    detect_real_devices,
    inspect_can_status,
    list_serial_device_candidates,
)
from mujina_assist.services.jobs import active_jobs, list_jobs, recent_jobs, summarize_job

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
                    Vertical(Static(id="flow-list"), Static(id="detail-pane"), classes="pane", id="right-pane"),
                    id="dashboard-grid",
                ),
                classes="screen-body",
            )
            yield Footer()

        def on_mount(self) -> None:
            self._refresh()
            self.set_interval(2.0, self._refresh)

        def _flow_items(self, report: "DoctorReport") -> list[FlowItem]:
            return [
                FlowItem("setup", "Setup", "ok" if report.workspace_cloned else "warn", "workspace / upstream 準備"),
                FlowItem("device", "Device", "ok" if report.imu_port_label else "warn", "IMU / USB-CAN / joy"),
                FlowItem("can", "CAN", "ok" if report.real_devices.get("can0") else "warn", "SocketCAN / serial CAN"),
                FlowItem("motor", "Motor", "wait", "12軸の passive scan"),
                FlowItem("zero", "Zero", "lock", "zero profile / post verification"),
                FlowItem("policy", "Policy", "ok" if report.active_policy_hash else "warn", report.active_policy_label),
                FlowItem("simulation", "Simulation", "ok" if report.sim_ready else "warn", "policy変更後のSIM確認"),
                FlowItem("real-preflight", "Real Preflight", "lock" if not report.sim_ready else "warn", "P0/P1/P2確認"),
                FlowItem("real-launch", "Real Launch", "lock", "段階起動"),
                FlowItem("logs", "Logs", "wait", "job log tail"),
                FlowItem("help", "Help", "ok", "keybind一覧"),
            ]

        def _refresh(self) -> None:
            report = self.doctor_report()
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

            locks = ["[b]Launch Locks[/b]"]
            if not report.workspace_built:
                locks.append("- build が未完了")
            if not report.active_policy_hash:
                locks.append("- active policy が未設定")
            if not report.sim_ready:
                locks.append("- SIM確認が未完了")
            if not report.imu_port_label:
                locks.append("- IMU が未検出")
            if not (report.real_devices.get("can0") or report.real_devices.get("/dev/usb_can")):
                locks.append("- CAN が未検出")
            if len(locks) == 1:
                locks.append("[green]- P0 blockなし。Preflightへ進めます。[/]")
            self.query_one("#lock-summary", Static).update("\n".join(locks[:7]))

            jobs = active_jobs(self.paths)
            job_lines = ["[b]Running Jobs[/b]"]
            if jobs:
                job_lines.extend(f"- {job.name} ({job.kind})" for job in jobs[:6])
            else:
                job_lines.append("- 実行中ジョブなし")
            self.query_one("#job-summary", Static).update("\n".join(job_lines))

            flow_lines = ["[b]Flow[/b]"]
            for item in self._flow_items(report):
                flow_lines.append(f"{_badge(item.status)}  [b]{item.label:<15}[/b] [dim]{item.summary}[/dim]")
            self.query_one("#flow-list", Static).update("\n".join(flow_lines))

            details = ["[b]Doctor Checks[/b]"]
            details.extend(f"- {_badge(check.status)} [b]{check.label}[/b]: {check.summary}" for check in report.checks)
            if report.notes:
                details.append("\n[b]Notes[/b]")
                details.extend(f"- {note}" for note in report.notes[:5])
            self.query_one("#detail-pane", Static).update("\n".join(details))

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            key = getattr(event.item, "mujina_key", "")
            if key:
                self.app.open_screen(key)


    class SetupFlowScreen(MujinaBaseScreen):
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(
                self.header("Setup Flow", "初回セットアップからSIM準備までの流れ"),
                DataTable(id="setup-table"),
                Static("[dim]実行ボタンは後続実装で既存job systemに接続します。旧CLIの setup/build subcommand はそのまま利用できます。[/dim]"),
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
                ("patch適用状態確認", "wait", "assisted patch queue は未接続"),
                ("colcon build", "ok" if report.workspace_built else "warn", "完了" if report.workspace_built else "未実行"),
                ("udev / dialout", "warn", "実機用設定を確認"),
                ("device確認", "ok" if report.imu_port_label else "warn", report.imu_port_label or "IMU未検出"),
                ("SIM準備", "ok" if report.sim_ready else "warn", "確認済み" if report.sim_ready else "未確認"),
            ]
            _add_rows(table, rows)


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
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(self.header("CAN", "can0 / slcand / statistics"), DataTable(id="can-table"), Static(id="can-raw"), classes="screen-body")
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


    class MotorScreen(MujinaBaseScreen):
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
            yield Container(self.header("Motor", "12軸 passive scan の表示骨格"), DataTable(id="motor-table"), classes="screen-body")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#motor-table", DataTable)
            table.add_columns("Joint", "ID", "Resp", "Pos(rad)", "Vel(rad/s)", "Temp(C)", "Err", "Zero")
            for joint, motor_id in self.JOINTS:
                table.add_row(joint, str(motor_id), "WAIT", "-", "-", "-", "-", "unknown")


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
            self.query_one("#skeleton-note", Static).update("[dim]この画面は骨格です。実処理は既存service/job層へ段階的に接続します。[/dim]")


    class ZeroWizardScreen(SkeletonScreen):
        SCREEN_TITLE = "Zero Wizard"
        SCREEN_SUMMARY = "pre-scan / confirmation / upstream zero / post verification"
        ITEMS = [
            ("CAN状態確認", "wait", "can0 healthy required"),
            ("対象motor選択", "wait", "all / leg / single"),
            ("passive scan", "wait", "torqueを出さない診断"),
            ("operator checklist", "lock", "所定姿勢と停止手段"),
            ("upstream zero script", "lock", "motor_set_zero_position.py"),
            ("zero profile保存", "wait", "post-zero verification後に保存"),
        ]


    class PolicyScreen(SkeletonScreen):
        SCREEN_TITLE = "Policy"
        SCREEN_SUMMARY = "default / USB / cache / manifest / SIM verified"
        ITEMS = [
            ("policy一覧", "wait", "default, cache, USB候補"),
            ("ONNX shape check", "wait", "[1,45] -> [1,12]"),
            ("manifest validation", "lock", "external policyはmanifest必須"),
            ("switch rollback", "wait", "default backupから復旧"),
            ("SIM verified reset", "lock", "切替後は再確認"),
        ]


    class SimulationScreen(SkeletonScreen):
        SCREEN_TITLE = "Simulation"
        SCREEN_SUMMARY = "policy変更後の実機前確認"
        ITEMS = [
            ("SIM main", "wait", "mujina_main --sim"),
            ("joy node", "wait", "input応答確認"),
            ("topic watcher", "wait", "/robot_mode /motor_state /joint_states"),
            ("SIM verified", "lock", "live session確認後に付与"),
        ]


    class RealPreflightScreen(SkeletonScreen):
        SCREEN_TITLE = "Real Preflight"
        SCREEN_SUMMARY = "P0/P1/P2 lock reasons"
        ITEMS = [
            ("Build", "lock", "workspace build required"),
            ("Policy", "lock", "provenance / manifest / SIM verified"),
            ("CAN", "lock", "error-active required"),
            ("IMU", "lock", "fixed device and topic required"),
            ("Motors", "lock", "12/12 response required"),
            ("Zero profile", "lock", "verified profile required"),
            ("Operator", "lock", "REAL confirmation required"),
        ]


    class RealLaunchScreen(SkeletonScreen):
        SCREEN_TITLE = "Real Launch"
        SCREEN_SUMMARY = "段階起動"
        ITEMS = [
            ("CAN setup", "wait", "net / serial"),
            ("IMU node", "wait", "wait /imu/data"),
            ("passive motor scan", "lock", "main起動前"),
            ("mujina_main", "lock", "wait /robot_mode"),
            ("joy node", "lock", "wait /joy"),
            ("standup unlock", "lock", "operator確認後"),
        ]


    class LogScreen(MujinaBaseScreen):
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Container(self.header("Logs", "job履歴と最新ログ末尾"), DataTable(id="jobs-table"), Static(id="log-tail"), classes="screen-body")
            yield Footer()

        def on_mount(self) -> None:
            jobs = list_jobs(self.paths)
            table = self.query_one("#jobs-table", DataTable)
            table.add_columns("Job", "Status", "Log")
            for job in jobs[:12]:
                table.add_row(job.name, job.status, Path(job.log_path).name)
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
                            "Enter: flow項目を開く",
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
