from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mujina_assist.models import AppPaths, DoctorReport, PolicyCandidate
from mujina_assist.services.checks import file_hash
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

    def test_tui_policy_switch_creates_job_and_resets_sim_state(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="old",
            active_policy_hash="old-sha256",
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            policy = Path(tmp) / "cached.onnx"
            policy.write_bytes(b"policy")
            app.state.last_sim_success = True
            app.state.last_sim_policy_hash = "old-sha256"
            app.save_runtime_state()
            candidate = PolicyCandidate(
                label="cache policy",
                path=policy,
                source_type="cache",
                description="cached",
                policy_hash="new-sha256",
            )

            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app.launch_job",
                return_value=SimpleNamespace(ok=True, mode="tmux", label="policy", pid=None, message="ok"),
            ):
                app.launch_policy_switch_from_tui(candidate)

            jobs = list_jobs(app.paths)
            state = load_runtime_state(app.paths.runtime_state_file)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].kind, "policy_switch")
        self.assertEqual(jobs[0].payload["label"], "cache policy")
        self.assertEqual(jobs[0].payload["policy_hash"], "new-sha256")
        self.assertFalse(state.last_sim_success)
        self.assertEqual(state.last_sim_policy_hash, "")

    def test_tui_policy_switch_blocks_manifestless_usb_policy(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="old",
            active_policy_hash="old-sha256",
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            policy = Path(tmp) / "usb.onnx"
            policy.write_bytes(b"policy")
            candidate = PolicyCandidate(label="USB: usb.onnx", path=policy, source_type="usb", policy_hash="new")

            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app.launch_job"
            ) as launch_mock:
                app.launch_policy_switch_from_tui(candidate)

            jobs = list_jobs(app.paths)

        self.assertEqual(jobs, [])
        launch_mock.assert_not_called()

    def test_tui_policy_switch_blocks_live_real_job(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="old",
            active_policy_hash="old-sha256",
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            policy = Path(tmp) / "cached.onnx"
            policy.write_bytes(b"policy")
            running = create_job(app.paths, kind="real_main", name="実機 mujina_main")
            update_job(running, status="running")
            candidate = PolicyCandidate(
                label="cache policy",
                path=policy,
                source_type="cache",
                description="cached",
                policy_hash="new-sha256",
            )

            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app.launch_job"
            ) as launch_mock:
                app.launch_policy_switch_from_tui(candidate)

            jobs = list_jobs(app.paths)

        self.assertEqual([job.kind for job in jobs], ["real_main"])
        launch_mock.assert_not_called()

    def test_tui_real_launch_locked_path_does_not_create_job(self) -> None:
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
            active_policy_hash="policy-sha256",
            sim_ready=False,
        )
        lock = SimpleNamespace(reasons=[SimpleNamespace(priority="P0", code="sim_unverified")])

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app._safety_state",
                return_value=lock,
            ), patch("mujina_assist.tui.app.launch_job") as launch_mock:
                app.launch_real_from_tui(can_mode="net", real_confirmation="REAL", checklist_complete=True)

            jobs = list_jobs(app.paths)

        self.assertEqual(jobs, [])
        launch_mock.assert_not_called()

    def test_tui_real_launch_blocks_live_policy_switch_job(self) -> None:
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
            active_policy_hash="policy-sha256",
            sim_ready=True,
        )
        unlocked = SimpleNamespace(reasons=[])

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            running = create_job(app.paths, kind="policy_switch", name="policy 切替")
            update_job(running, status="running")
            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app._safety_state",
                return_value=unlocked,
            ), patch("mujina_assist.tui.app.launch_job") as launch_mock:
                app.launch_real_from_tui(can_mode="net", real_confirmation="REAL", checklist_complete=True)

            jobs = list_jobs(app.paths)

        self.assertEqual([job.kind for job in jobs], ["policy_switch"])
        launch_mock.assert_not_called()

    def test_tui_real_launch_creates_confirmed_worker_job(self) -> None:
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
            active_policy_hash="policy-sha256",
            sim_ready=True,
        )
        unlocked = SimpleNamespace(reasons=[])

        with tempfile.TemporaryDirectory() as tmp:
            app = app_class(Path(tmp))
            with patch("mujina_assist.tui.app.build_doctor_report", return_value=report), patch(
                "mujina_assist.tui.app._safety_state",
                return_value=unlocked,
            ), patch(
                "mujina_assist.tui.app.launch_job",
                return_value=SimpleNamespace(ok=True, mode="tmux", label="real", pid=None, message="ok"),
            ):
                app.launch_real_from_tui(can_mode="serial", real_confirmation="REAL", checklist_complete=True)

            jobs = list_jobs(app.paths)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].kind, "real_launch")
        self.assertEqual(jobs[0].payload["can_mode"], "serial")
        self.assertTrue(jobs[0].payload["operator_checklist_complete"])
        self.assertEqual(jobs[0].payload["real_confirmation"], "REAL")

    def test_tui_real_launch_screen_accepts_real_enter(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        from textual.widgets import Input

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_hash="policy-sha256",
            sim_ready=False,
        )

        async def run_screen() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                app = app_class(Path(tmp))
                with patch("mujina_assist.tui.screens.build_doctor_report", return_value=report), patch.object(
                    app,
                    "launch_real_from_tui",
                ) as launch_mock:
                    async with app.run_test() as pilot:
                        await app.push_screen("real-launch")
                        await pilot.pause(0.2)
                        screen = app.screen
                        self.assertIsNotNone(screen.query_one("#real-confirm", Input))
                        await pilot.press("1", "2", "3")
                        screen.query_one("#real-confirm", Input).focus()
                        await pilot.press("R", "E", "A", "L", "enter")
                        await pilot.pause(0.2)

                    launch_mock.assert_called_once_with(
                        can_mode="net",
                        real_confirmation="REAL",
                        checklist_complete=True,
                    )

        asyncio.run(run_screen())

    def test_tui_policy_screen_does_not_arm_manifestless_usb_candidate(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        from textual.widgets import Static

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_hash="policy-sha256",
        )

        async def run_screen() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                app = app_class(Path(tmp))
                policy = Path(tmp) / "usb.onnx"
                policy.write_bytes(b"policy")
                candidate = PolicyCandidate(label="USB: usb.onnx", path=policy, source_type="usb", policy_hash="new")
                with patch("mujina_assist.tui.screens.build_doctor_report", return_value=report), patch.object(
                    app,
                    "policy_candidates",
                    return_value=[candidate],
                ), patch.object(app, "launch_policy_switch_from_tui") as launch_mock:
                    async with app.run_test() as pilot:
                        await app.push_screen("policy")
                        await pilot.pause(0.2)
                        await pilot.press("a", "w")
                        await pilot.pause(0.2)
                        warning = str(app.screen.query_one("#policy-warning", Static).renderable)

                    self.assertIn("manifest", warning)
                    launch_mock.assert_not_called()

        asyncio.run(run_screen())

    def test_tui_policy_screen_g_creates_manifest_template_for_usb_candidate(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        from textual.widgets import Static

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_hash="policy-sha256",
        )

        async def run_screen() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                app = app_class(Path(tmp))
                policy = Path(tmp) / "usb.onnx"
                policy.write_bytes(b"policy")
                candidate = PolicyCandidate(label="USB: usb.onnx", path=policy, source_type="usb", policy_hash="new")
                with patch("mujina_assist.tui.screens.build_doctor_report", return_value=report), patch.object(
                    app,
                    "policy_candidates",
                    return_value=[candidate],
                ):
                    async with app.run_test() as pilot:
                        await app.push_screen("policy")
                        await pilot.pause(0.2)
                        await pilot.press("g")
                        await pilot.pause(0.2)
                        warning = str(app.screen.query_one("#policy-warning", Static).renderable)

                manifest = policy.with_suffix(".manifest.json")
                data = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(data["hash"]["onnx_sha256"], file_hash(policy))
                self.assertIn("robot_revision", warning)

        asyncio.run(run_screen())

    def test_tui_policy_screen_does_not_arm_invalid_manifest_candidate(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        from textual.widgets import Static

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_hash="policy-sha256",
        )

        async def run_screen() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                app = app_class(Path(tmp))
                policy = Path(tmp) / "usb.onnx"
                manifest = policy.with_suffix(".manifest.json")
                policy.write_bytes(b"policy")
                manifest.write_text("{}", encoding="utf-8")
                candidate = PolicyCandidate(
                    label="USB: usb.onnx",
                    path=policy,
                    source_type="usb",
                    policy_hash="new",
                    manifest_path=manifest,
                )
                with patch("mujina_assist.tui.screens.build_doctor_report", return_value=report), patch.object(
                    app,
                    "policy_candidates",
                    return_value=[candidate],
                ), patch.object(app, "launch_policy_switch_from_tui") as launch_mock:
                    async with app.run_test() as pilot:
                        await app.push_screen("policy")
                        await pilot.pause(0.2)
                        await pilot.press("a", "w")
                        await pilot.pause(0.2)
                        warning = str(app.screen.query_one("#policy-warning", Static).renderable)

                    self.assertIn("manifestを修正", warning)
                    launch_mock.assert_not_called()

        asyncio.run(run_screen())

    def test_tui_real_launch_screen_shows_p1_p2_blocking_reasons(self) -> None:
        app_class = getattr(tui_app_module, "MujinaAssistTui", None)
        if app_class is None:
            self.skipTest(f"{REQUIRED_TUI_API} is not implemented yet")

        from textual.widgets import Static

        report = DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_hash="policy-sha256",
            sim_ready=True,
        )
        from mujina_assist.services.safety import LockReason, SafetyState

        safety = SafetyState(
            real_launch_locked=False,
            standup_locked=False,
            walk_locked=False,
            reasons=[
                LockReason(priority="P1", code="zero_profile_warning", message="zero warning"),
                LockReason(priority="P2", code="joy_missing", message="joy missing"),
            ],
        )

        async def run_screen() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                app = app_class(Path(tmp))
                with patch("mujina_assist.tui.screens.build_doctor_report", return_value=report), patch(
                    "mujina_assist.tui.screens._safety_state",
                    return_value=safety,
                ):
                    async with app.run_test() as pilot:
                        await app.push_screen("real-launch")
                        await pilot.pause(0.2)
                        note = str(app.screen.query_one("#real-launch-note", Static).renderable)

                    self.assertIn("起動不可", note)
                    self.assertIn("zero_profile_warning", note)

        asyncio.run(run_screen())


if __name__ == "__main__":
    unittest.main()
