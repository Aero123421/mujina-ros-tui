from __future__ import annotations

from pathlib import Path

from mujina_assist.models import AppPaths, RuntimeState
from mujina_assist.services.checks import build_doctor_report
from mujina_assist.services.checks import current_policy_label, write_config_file
from mujina_assist.services.jobs import active_jobs, recent_jobs
from mujina_assist.services.state import load_runtime_state
from mujina_assist.tui.screens import SCREEN_CLASSES, TEXTUAL_IMPORT_ERROR

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
            height: 7;
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
            ("p", "open_screen('policy')", "Policy"),
            ("m", "open_screen('motor')", "Motor"),
            ("z", "open_screen('zero')", "Zero"),
            ("c", "open_screen('can')", "CAN"),
            ("i", "open_screen('device')", "Device"),
            ("r", "open_screen('real-preflight')", "Real"),
            ("l", "open_screen('logs')", "Logs"),
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
            "jobs": {"running": 0, "recent": []},
        }

    runtime_state = state or load_runtime_state(paths.runtime_state_file)
    report = build_doctor_report(paths, runtime_state)
    running_jobs = active_jobs(paths)
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
        "zero": {"status": "lock", "summary": "zero profile validation は後続実装で接続"},
        "policy": {
            "status": "ok" if report.active_policy_hash else "warn",
            "label": report.active_policy_label,
            "sim_ready": report.sim_ready,
        },
        "jobs": {
            "running": len(running_jobs),
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
