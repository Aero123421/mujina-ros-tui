from __future__ import annotations

import importlib
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mujina_assist.models import AppPaths, DoctorReport
from mujina_assist.services.jobs import create_job, list_jobs, update_job
from mujina_assist.services.state import load_runtime_state


try:
    tui_app_module = importlib.import_module("mujina_assist.tui.app")
except ImportError:  # pragma: no cover - documents the expected Textual entry point while it is absent.
    tui_app_module = None


REQUIRED_TUI_API = "mujina_assist.tui.app.MujinaAssistTui"
EXPECTED_SCREENS = {
    "dashboard",
    "setup",
    "device",
    "can",
    "motor",
    "zero",
    "policy",
    "simulation",
    "real-preflight",
    "real-launch",
    "logs",
    "help",
}
EXPECTED_KEYBINDS = {"d", "s", "p", "m", "z", "c", "i", "r", "l", "x", "?", "q"}


@unittest.skipIf(tui_app_module is None, f"{REQUIRED_TUI_API} is not implemented yet")
class TextualTuiSmokeTest(unittest.TestCase):
    def test_app_exposes_expected_screen_registry_and_keybinds(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            screen_registry = set(getattr(tui_app_module, "SCREEN_CLASSES", {}).keys())
            bindings = getattr(app, "BINDINGS", [])
            bound_keys = {binding[0] if isinstance(binding, tuple) else getattr(binding, "key", "") for binding in bindings}

        self.assertTrue(EXPECTED_SCREENS.issubset(screen_registry))
        self.assertTrue(EXPECTED_KEYBINDS.issubset(bound_keys))
        self.assertIn("y", bound_keys)

    def test_dashboard_model_contains_workspace_devices_can_zero_policy_and_jobs(self) -> None:
        build_dashboard_model = getattr(tui_app_module, "build_dashboard_model", None)
        if build_dashboard_model is None:
            self.skipTest("mujina_assist.tui.app.build_dashboard_model(paths, state) is not implemented yet")

        model = build_dashboard_model(paths=None, state=None)

        for key in ("workspace", "devices", "can", "zero", "policy", "safety", "jobs"):
            self.assertIn(key, model)

        self.assertTrue(model["safety"]["real_launch_locked"])

    def test_dashboard_model_reports_stale_jobs(self) -> None:
        build_dashboard_model = getattr(tui_app_module, "build_dashboard_model", None)
        if build_dashboard_model is None:
            self.skipTest("mujina_assist.tui.app.build_dashboard_model(paths, state) is not implemented yet")

        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            state = load_runtime_state(paths.runtime_state_file)
            job = create_job(paths, kind="setup", name="initial setup")
            update_job(job, terminal_mode="terminal", terminal_pid=999999)

            with patch("mujina_assist.services.jobs._pid_alive", return_value=False):
                model = build_dashboard_model(paths=paths, state=state)

        self.assertEqual(model["jobs"]["stale"], 1)

    def test_tui_sim_launch_creates_paired_jobs_with_policy_payload(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_source="/tmp/policy.onnx",
            active_policy_hash="policy-sha256",
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            launches = [
                SimpleNamespace(ok=True, mode="terminal", label="gnome-terminal", pid=111, message="ok"),
                SimpleNamespace(ok=True, mode="terminal", label="gnome-terminal", pid=222, message="ok"),
            ]
            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app.workspace_signature", return_value="workspace-sha256"
            ), patch("mujina_assist.tui.app.launch_job", side_effect=launches):
                app.launch_sim_from_tui()

            jobs = list_jobs(app.paths)

        self.assertEqual({job.kind for job in jobs}, {"sim_main", "sim_joy"})
        self.assertEqual({job.group_id for job in jobs}, {jobs[0].group_id})
        for job in jobs:
            self.assertEqual(job.payload["policy_hash"], "policy-sha256")
            self.assertEqual(job.payload["workspace_signature"], "workspace-sha256")

    def test_tui_sim_verified_requires_live_paired_sim_jobs(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_source="/tmp/policy.onnx",
            active_policy_hash="policy-sha256",
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            group_id = "sim-test"
            payload = {
                "policy_hash": "policy-sha256",
                "policy_label": "公式デフォルト",
                "workspace_signature": "workspace-sha256",
            }
            sim_main = create_job(app.paths, kind="sim_main", name="SIM 本体", payload=payload, group_id=group_id)
            sim_joy = create_job(app.paths, kind="sim_joy", name="SIM joy ノード", payload=payload, group_id=group_id)
            update_job(sim_main, status="running", started_at="2026-06-04T10:00:00+09:00")
            update_job(sim_joy, status="running", started_at="2026-06-04T10:00:00+09:00")

            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app.workspace_signature", return_value="workspace-sha256"
            ):
                app.mark_sim_verified_from_tui()

            state = load_runtime_state(app.paths.runtime_state_file)

        self.assertTrue(state.last_sim_success)
        self.assertEqual(state.last_sim_policy_hash, "policy-sha256")
        self.assertEqual(state.last_sim_verified_workspace_signature, "workspace-sha256")


if __name__ == "__main__":
    unittest.main()
