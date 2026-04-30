from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mujina_assist.models import AppPaths
from mujina_assist.services.jobs import create_job, update_job
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
EXPECTED_KEYBINDS = {"d", "s", "p", "m", "z", "c", "i", "r", "l", "?", "q"}


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


if __name__ == "__main__":
    unittest.main()
