from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mujina_assist.models import AppPaths, RuntimeState
from mujina_assist.services.checks import build_doctor_report
from mujina_assist.services.checks import current_policy_label, workspace_signature, write_config_file
from mujina_assist.services.jobs import (
    active_jobs,
    create_job,
    live_jobs,
    mark_job_finished,
    mark_job_stopped,
    recent_jobs,
    stale_jobs,
    update_job,
)
from mujina_assist.services.state import load_runtime_state, save_runtime_state
from mujina_assist.services.terminals import launch_job, stop_job_launch
from mujina_assist.tui.screens import SCREEN_CLASSES, TEXTUAL_IMPORT_ERROR
from mujina_assist.tui.screens import _safety_state, _status_from_reasons

if TEXTUAL_IMPORT_ERROR is None:
    from textual.app import App


if TEXTUAL_IMPORT_ERROR is None:

    class MujinaAssistTui(App):
        SCREENS = {
            **SCREEN_CLASSES,
            "devices": SCREEN_CLASSES["device"],
            "motors": SCREEN_CLASSES["motor"],
            "real_preflight": SCREEN_CLASSES["real-preflight"],
            "real_launch": SCREEN_CLASSES["real-launch"],
        }

        CSS = """
        Screen {
            background: #101418;
            color: #dce3e8;
        }

        .screen-body {
            height: 100%;
            padding: 1;
        }

        .screen-heading {
            margin-bottom: 1;
            padding: 0 1;
            height: 3;
            border: round #5fa8d3;
            background: #17212b;
        }

        #dashboard-grid {
            height: 1fr;
        }

        .pane {
            width: 1fr;
            height: 100%;
            padding: 0 1;
        }

        #left-pane {
            width: 43%;
        }

        #right-pane {
            width: 57%;
        }

        Static {
            margin-bottom: 1;
        }

        DataTable {
            height: 1fr;
        }

        #flow-list {
            height: 13;
            border: round #30404f;
        }

        #status-summary, #lock-summary, #detail-pane, #job-summary, #serial-list, #can-raw, #log-tail, #skeleton-note {
            border: round #30404f;
            padding: 1;
        }

        #status-summary {
            height: 13;
        }

        #lock-summary {
            height: 8;
        }

        #job-summary {
            height: 9;
        }

        #detail-pane {
            height: 1fr;
        }
        """

        BINDINGS = [
            ("ctrl+c", "request_quit", "終了"),
            ("q", "request_quit", "終了"),
            ("d", "open_screen('dashboard')", "Doctor"),
            ("s", "open_screen('setup')", "Setup"),
            ("y", "open_screen('simulation')", "SIM"),
            ("p", "open_screen('policy')", "Policy"),
            ("m", "open_screen('motor')", "Motor"),
            ("z", "open_screen('zero')", "Zero"),
            ("c", "open_screen('can')", "CAN"),
            ("i", "open_screen('device')", "Device"),
            ("r", "open_screen('real-preflight')", "Real"),
            ("l", "open_screen('logs')", "Logs"),
            ("x", "show_repair_command", "Repair"),
            ("?", "open_screen('help')", "Help"),
        ]

        def __init__(self, repo_root: Path | None = None) -> None:
            super().__init__()
            self.paths = AppPaths.from_repo_root(repo_root or Path.cwd())
            self.paths.ensure_directories()
            write_config_file(self.paths)
            self.state = load_runtime_state(self.paths.runtime_state_file)
            if not self.state.active_policy_label:
                self.state.active_policy_label = current_policy_label(self.paths, self.state)

        def on_mount(self) -> None:
            self.push_screen("dashboard")

        def refresh_runtime_state(self) -> None:
            self.state = load_runtime_state(self.paths.runtime_state_file)
            if not self.state.active_policy_label:
                self.state.active_policy_label = current_policy_label(self.paths, self.state)

        def save_runtime_state(self) -> None:
            save_runtime_state(self.paths.runtime_state_file, self.state)

        def action_open_screen(self, name: str) -> None:
            route = {
                "devices": "device",
                "motors": "motor",
                "real_preflight": "real-preflight",
                "real_launch": "real-launch",
            }.get(name, name)
            if route not in self.SCREENS:
                self.notify(f"未知の画面です: {name}", severity="warning")
                return
            if self.screen.name == route:
                if hasattr(self.screen, "_refresh"):
                    self.screen._refresh()
                return
            self.push_screen(route)

        def action_request_quit(self) -> None:
            self.exit()

        def launch_tui_job(self, *, kind: str, name: str, payload: dict | None = None) -> None:
            conflicts = [job for job in live_jobs(self.paths) if job.kind == kind]
            if conflicts:
                existing = conflicts[0]
                self.notify(
                    f"{existing.name} が {existing.status} です。Logsで状態を確認してから再実行してください。",
                    severity="warning",
                    timeout=8,
                )
                return
            job = create_job(self.paths, kind=kind, name=name, payload=payload or {})
            launch = launch_job(self.paths, job)
            if not launch.ok:
                mark_job_finished(job, returncode=1, message=launch.message)
                self.notify(f"起動できません: {launch.message}", severity="error", timeout=8)
                return
            update_job(job, terminal_mode=launch.mode, terminal_label=launch.label, terminal_pid=launch.pid)
            self.notify(f"{name} を起動しました。ログ: {Path(job.log_path).name}", severity="information", timeout=8)
            self.refresh_runtime_state()

        def launch_sim_from_tui(self) -> None:
            report = build_doctor_report(self.paths, self.state)
            if not report.workspace_cloned:
                self.notify("workspace が未作成です。Setup画面で u を押して初回セットアップを開始してください。", severity="warning", timeout=10)
                return
            if not report.workspace_built:
                self.notify("workspace が未ビルドです。Setup画面で b を押すか、初回セットアップを完了してください。", severity="warning", timeout=10)
                return
            if not report.active_policy_hash:
                self.notify("policy hash を取得できません。Setup/Build後に再実行してください。", severity="warning", timeout=10)
                return

            conflicts = [job for job in live_jobs(self.paths) if job.kind in {"sim_main", "sim_joy"}]
            if conflicts:
                self.notify(
                    f"{conflicts[0].name} が {conflicts[0].status} です。Logsで状態を確認してください。",
                    severity="warning",
                    timeout=8,
                )
                return

            current_signature = workspace_signature(self.paths)
            self.state.active_policy_hash = report.active_policy_hash
            self.state.active_policy_label = report.active_policy_label
            self.state.active_policy_source = report.active_policy_source
            self.state.workspace_signature = current_signature
            self.state.last_action = "sim_launch"
            self.state.last_sim_success = False
            self.state.last_sim_policy_hash = ""
            self.save_runtime_state()

            group_id = f"sim-{uuid4().hex[:8]}"
            payload = {
                "policy_hash": report.active_policy_hash,
                "policy_label": report.active_policy_label,
                "workspace_signature": current_signature,
            }
            jobs = [
                create_job(self.paths, kind="sim_main", name="SIM 本体", payload=dict(payload), group_id=group_id),
                create_job(self.paths, kind="sim_joy", name="SIM joy ノード", payload=dict(payload), group_id=group_id),
            ]
            launches = []
            for job in jobs:
                launch = launch_job(self.paths, job)
                if not launch.ok:
                    mark_job_finished(job, returncode=1, message=launch.message)
                    for launched_job, mode, label, pid in launches:
                        stop_error = stop_job_launch(mode=mode, label=label, pid=pid)
                        if stop_error:
                            update_job(launched_job, message=f"SIMペア起動失敗。停止確認できませんでした: {stop_error}")
                        else:
                            mark_job_stopped(launched_job, message="SIMペア起動失敗のため停止しました。")
                    self.notify(f"SIMを起動できません: {launch.message}", severity="error", timeout=10)
                    return
                update_job(job, terminal_mode=launch.mode, terminal_label=launch.label, terminal_pid=launch.pid)
                launches.append((job, launch.mode, launch.label, launch.pid))

            self.notify("SIM 本体と joy ノードを起動しました。MuJoCo画面と入力応答を確認してください。", severity="information", timeout=10)
            self.refresh_runtime_state()

        def mark_sim_verified_from_tui(self) -> None:
            report = build_doctor_report(self.paths, self.state)
            if not report.workspace_built:
                self.notify("workspace が未ビルドです。先にSetup/Buildを完了してください。", severity="warning", timeout=10)
                return
            current_signature = workspace_signature(self.paths)
            groups: dict[str, set[str]] = {}
            for job in live_jobs(self.paths):
                if job.kind not in {"sim_main", "sim_joy"}:
                    continue
                if str(job.payload.get("policy_hash", "")) != report.active_policy_hash:
                    continue
                if str(job.payload.get("workspace_signature", "")) != current_signature:
                    continue
                if not job.group_id or not job.started_at:
                    continue
                groups.setdefault(job.group_id, set()).add(job.kind)
            if not any(kinds == {"sim_main", "sim_joy"} for kinds in groups.values()):
                self.notify("同じpolicy/workspaceで実行中のSIMペアを確認できません。先に o でSIMを起動してください。", severity="warning", timeout=10)
                return

            self.state.active_policy_hash = report.active_policy_hash
            self.state.active_policy_label = report.active_policy_label
            self.state.active_policy_source = report.active_policy_source
            self.state.workspace_signature = current_signature
            self.state.last_action = "sim_verified"
            self.state.last_sim_success = True
            self.state.last_sim_policy_hash = report.active_policy_hash
            self.state.last_sim_verified_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self.state.last_sim_verified_label = report.active_policy_label
            self.state.last_sim_verified_source = report.active_policy_source
            self.state.last_sim_verified_workspace_signature = current_signature
            self.save_runtime_state()
            self.notify("現在のpolicy/workspaceをSIM確認済みとして記録しました。", severity="information", timeout=10)
            self.refresh_runtime_state()

        def show_cli_required(self, command: str, reason: str) -> None:
            self.notify(f"{reason}: {command}", severity="warning", timeout=10)

        def action_show_repair_command(self) -> None:
            self.notify("stale job や壊れた状態の整理: ./start.sh repair", severity="warning", timeout=10)


    MujinaAssistTuiApp = MujinaAssistTui


def build_dashboard_model(paths: AppPaths | None, state: RuntimeState | None) -> dict[str, object]:
    """Return a small, testable model for the dashboard surface."""

    if paths is None:
        return {
            "workspace": {"status": "unknown", "summary": "workspace未確認"},
            "devices": {"status": "unknown", "summary": "device未確認"},
            "can": {"status": "unknown", "summary": "CAN未確認"},
            "zero": {"status": "lock", "summary": "zero profile未確認"},
            "policy": {"status": "unknown", "summary": "policy未確認"},
            "safety": {"real_launch_locked": True, "manual_recovery_required": False, "reasons": []},
            "jobs": {"running": 0, "recent": []},
        }

    runtime_state = state or load_runtime_state(paths.runtime_state_file)
    report = build_doctor_report(paths, runtime_state)
    safety = _safety_state(paths, runtime_state, report)
    zero_status = _status_from_reasons(safety, {"zero_profile_missing", "zero_profile_invalid", "zero_profile_warning"})
    running_jobs = active_jobs(paths)
    stale_job_records = stale_jobs(paths)
    latest_jobs = recent_jobs(paths, limit=5)
    return {
        "workspace": {
            "status": "ok" if report.workspace_cloned else "warn",
            "built": report.workspace_built,
            "summary": "build済み" if report.workspace_built else "build未完了",
        },
        "devices": {
            "status": "ok" if report.imu_port_label and (report.real_devices.get("can0") or report.real_devices.get("/dev/usb_can")) else "warn",
            "imu": report.imu_port_label,
            "joy": report.real_devices.get("/dev/input/js0", False),
            "summary": f"IMU={report.imu_port_label or 'missing'}",
        },
        "can": {
            "status": "ok" if report.real_devices.get("can0") or report.real_devices.get("/dev/usb_can") else "warn",
            "can0": report.real_devices.get("can0", False),
            "serial": report.real_devices.get("/dev/usb_can", False),
        },
        "zero": {
            "status": zero_status,
            "summary": "verified zero profile" if zero_status == "ok" else "zero profile未確認",
        },
        "policy": {
            "status": _status_from_reasons(
                safety,
                {"policy_unknown", "policy_manifest_missing", "policy_manifest_invalid", "policy_manifest_warning", "sim_unverified"},
                default="ok" if report.active_policy_hash else "warn",
            ),
            "label": report.active_policy_label,
            "sim_ready": report.sim_ready,
        },
        "safety": {
            "real_launch_locked": safety.real_launch_locked,
            "manual_recovery_required": safety.manual_recovery_required,
            "reasons": [{"priority": reason.priority, "code": reason.code, "message": reason.message} for reason in safety.reasons],
        },
        "jobs": {
            "running": len(running_jobs),
            "stale": len(stale_job_records),
            "recent": [job.name for job in latest_jobs],
        },
    }


def run_tui(repo_root: Path) -> int:
    if TEXTUAL_IMPORT_ERROR is not None:
        print("Textual が import できませんでした。`pip install -e .` で依存を入れてから再実行してください。")
        print(f"詳細: {TEXTUAL_IMPORT_ERROR}")
        return 1
    MujinaAssistTui(repo_root).run()
    return 0
