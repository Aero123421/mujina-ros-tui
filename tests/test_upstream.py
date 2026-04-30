from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mujina_assist.models import AppPaths, RuntimeState

try:
    from mujina_assist.services import upstream
except ImportError:  # pragma: no cover - documents the expected Phase 0 API while it is absent.
    upstream = None


REQUIRED_API_NAMES = (
    "vendored_upstream_path",
    "patches_path",
    "upstream_metadata_path",
    "write_upstream_metadata",
    "read_upstream_metadata",
    "patch_set_hash",
    "build_workspace_signature",
    "prepare_workspace_from_vendored_upstream",
    "verify_assisted_patchset",
    "sync_runtime_workspace_state",
    "workspace_dirty",
)


class MujinaRosPatchQueueTest(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_mujina_ros_patch_queue_applies_to_clean_vendored_copy(self) -> None:
        repo_root = self._repo_root()
        source = repo_root / "third_party" / "mujina_ros"
        patches = sorted((repo_root / "patches" / "mujina_ros").glob("*.patch"))

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "mujina_ros"
            shutil.copytree(source, work)

            for patch in patches:
                result = subprocess.run(
                    ["git", "apply", str(patch)],
                    cwd=work,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{patch.name} failed to apply\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
                )

    def test_imu_patch_documents_supported_baud_rates_and_seven_value_frames(self) -> None:
        patch = (self._repo_root() / "patches" / "mujina_ros" / "0002-harden-imu-driver.patch").read_text(
            encoding="utf-8"
        )

        self.assertIn('declare_parameter("baud_rate", 2000000)', patch)
        self.assertIn("case 38400:", patch)
        self.assertIn("case 921600:", patch)
        self.assertIn("case 2000000:", patch)
        self.assertIn("Unsupported IMU baud_rate", patch)
        self.assertIn("values.size() == 7", patch)
        self.assertIn("msg.orientation.x = latest_data[0];", patch)
        self.assertIn("msg.angular_velocity.z = latest_data[6];", patch)
        self.assertNotIn("+        msg.angular_velocity.z = latest_data[7];", patch)
        self.assertNotIn("B921600 : B38400", patch)

    def test_motor_patch_validates_expected_response_and_error_categories(self) -> None:
        patch = (self._repo_root() / "patches" / "mujina_ros" / "0003-harden-motor-lib-response.patch").read_text(
            encoding="utf-8"
        )

        self.assertIn("class CanMotorTimeoutError", patch)
        self.assertIn("class UnexpectedCanIdError", patch)
        self.assertIn("class CanDlcError", patch)
        self.assertIn("class MotorError", patch)
        self.assertIn("def _response_matches_motor_id", patch)
        self.assertIn("def _recv_expected_motor_frame", patch)
        self.assertIn("unexpected frames", patch)
        self.assertIn("self._recv_expected_motor_frame()", patch)


@unittest.skipIf(
    upstream is None,
    "mujina_assist.services.upstream is not implemented yet. "
    f"Expected API: {', '.join(REQUIRED_API_NAMES)}",
)
class UpstreamTest(unittest.TestCase):
    def _api(self, name: str):
        value = getattr(upstream, name, None)
        if value is None:
            self.fail(f"mujina_assist.services.upstream.{name} is required for vendored upstream Phase 0")
        return value

    def _write_required_assisted_patches(self, patches: Path) -> None:
        patches.mkdir(parents=True, exist_ok=True)
        (patches / "0002-harden-imu-driver.patch").write_text(
            "\n".join(
                [
                    "diff --git a/rt_usb_imu_driver/src/parser.cpp b/rt_usb_imu_driver/src/parser.cpp",
                    "new file mode 100644",
                    "index 0000000..1111111",
                    "--- /dev/null",
                    "+++ b/rt_usb_imu_driver/src/parser.cpp",
                    "@@ -0,0 +1,2 @@",
                    "+if (!has_nonfinite && values.size() == 7) {}",
                    "+// Ignore malformed frames; live health checks catch stale data.",
                    "diff --git a/rt_usb_imu_driver/src/rt_usb_imu_driver.cpp b/rt_usb_imu_driver/src/rt_usb_imu_driver.cpp",
                    "new file mode 100644",
                    "index 0000000..1111111",
                    "--- /dev/null",
                    "+++ b/rt_usb_imu_driver/src/rt_usb_imu_driver.cpp",
                    "@@ -0,0 +1,6 @@",
                    '+this->declare_parameter("baud_rate", 2000000);',
                    "+bool baudRateToSpeed(int baud_rate, speed_t &speed) {",
                    "+case 38400: case 921600: case 2000000:",
                    "+Unsupported IMU baud_rate",
                    "+speed = B2000000; return true; }",
                    "+int port_fd_ = -1;",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (patches / "0003-harden-motor-lib-response.patch").write_text(
            "\n".join(
                [
                    "diff --git a/mujina_control/mujina_control/motor_lib/motor_lib.py b/mujina_control/mujina_control/motor_lib/motor_lib.py",
                    "new file mode 100644",
                    "index 0000000..1111111",
                    "--- /dev/null",
                    "+++ b/mujina_control/mujina_control/motor_lib/motor_lib.py",
                    "@@ -0,0 +1,8 @@",
                    "+class CanMotorTimeoutError(TimeoutError): pass",
                    "+class UnexpectedCanIdError(RuntimeError): pass",
                    "+class CanDlcError(RuntimeError): pass",
                    "+class MotorError(RuntimeError): pass",
                    "+def _response_matches_motor_id(self): pass",
                    "+def _recv_expected_motor_frame(self): pass",
                    "+unexpected frames",
                    "+raise CanResponseError('Unable to receive CAN frame')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (patches / "0004-harden-mujina-main-safety.patch").write_text(
            "\n".join(
                [
                    "diff --git a/mujina_control/mujina_control/mujina_main.py b/mujina_control/mujina_control/mujina_main.py",
                    "new file mode 100644",
                    "index 0000000..1111111",
                    "--- /dev/null",
                    "+++ b/mujina_control/mujina_control/mujina_main.py",
                    "@@ -0,0 +1,3 @@",
                    "+self.robot_state.velocity = [0.0] * len(P.STANDBY_ANGLE)",
                    "+Ignoring joy message with insufficient axes/buttons",
                    "+requested_mode = RobotModeCommand(msg.mode)",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_vendored_upstream_path_is_inside_third_party(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))

            vendored_path = self._api("vendored_upstream_path")(paths)
            patches_path = self._api("patches_path")(paths)

            self.assertEqual(vendored_path, Path(tmp) / "third_party" / "mujina_ros")
            self.assertEqual(patches_path, Path(tmp) / "patches" / "mujina_ros")
            self.assertNotEqual(vendored_path, paths.upstream_dir)
            self.assertNotIn("workspace", vendored_path.parts)

    def test_metadata_round_trips_commit_and_patch_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            metadata_path = self._api("upstream_metadata_path")(paths)
            metadata = {
                "repo_url": "https://github.com/MujinaRobotics/mujina_ros.git",
                "upstream_commit": "38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
                "patch_set_hash": "patches-abc",
                "mode": "assisted",
                "dirty": False,
            }

            self._api("write_upstream_metadata")(metadata_path, metadata)
            loaded = self._api("read_upstream_metadata")(metadata_path)

            self.assertEqual(loaded["repo_url"], metadata["repo_url"])
            self.assertEqual(loaded["upstream_commit"], metadata["upstream_commit"])
            self.assertEqual(loaded["patch_set_hash"], metadata["patch_set_hash"])
            self.assertEqual(loaded["mode"], "assisted")
            self.assertFalse(loaded["dirty"])
            self.assertFalse(metadata_path.with_suffix(f"{metadata_path.suffix}.tmp").exists())

    def test_patch_set_hash_is_stable_across_file_creation_order(self) -> None:
        patch_set_hash = self._api("patch_set_hash")
        with tempfile.TemporaryDirectory() as left_tmp, tempfile.TemporaryDirectory() as right_tmp:
            left = Path(left_tmp)
            right = Path(right_tmp)
            (left / "010-can.patch").write_text("can hardening\n", encoding="utf-8")
            (left / "020-imu.patch").write_text("imu fix\n", encoding="utf-8")
            (right / "020-imu.patch").write_text("imu fix\n", encoding="utf-8")
            (right / "010-can.patch").write_text("can hardening\n", encoding="utf-8")

            self.assertEqual(patch_set_hash(left), patch_set_hash(right))

            (right / "020-imu.patch").write_text("imu fix changed\n", encoding="utf-8")
            self.assertNotEqual(patch_set_hash(left), patch_set_hash(right))

    def test_workspace_signature_reflects_patch_hash_and_dirty_state(self) -> None:
        build_workspace_signature = self._api("build_workspace_signature")

        clean = build_workspace_signature(
            upstream_commit="38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
            patch_set_hash="patches-abc",
            dirty=False,
            workspace_tree_hash="tree-abc",
        )
        other_patch = build_workspace_signature(
            upstream_commit="38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
            patch_set_hash="patches-def",
            dirty=False,
            workspace_tree_hash="tree-abc",
        )
        dirty = build_workspace_signature(
            upstream_commit="38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
            patch_set_hash="patches-abc",
            dirty=True,
            workspace_tree_hash="tree-abc",
        )
        other_tree = build_workspace_signature(
            upstream_commit="38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
            patch_set_hash="patches-abc",
            dirty=False,
            workspace_tree_hash="tree-def",
        )

        self.assertNotEqual(clean, other_patch)
        self.assertNotEqual(clean, dirty)
        self.assertNotEqual(clean, other_tree)
        self.assertIn("38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d", clean)
        self.assertIn("patches-abc", clean)
        self.assertIn("tree=tree-abc", clean)
        self.assertIn("dirty", dirty)

    def test_prepare_workspace_can_keep_vanilla_or_apply_assisted_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            vendored = self._api("vendored_upstream_path")(paths)
            patches = self._api("patches_path")(paths)
            prepare_workspace = self._api("prepare_workspace_from_vendored_upstream")

            (vendored / "mujina_control").mkdir(parents=True)
            (vendored / "README.md").write_text("official upstream\n", encoding="utf-8")
            (vendored / "mujina_control" / "can_setup.sh").write_text("ip link set can0 up\n", encoding="utf-8")
            patches.mkdir(parents=True)
            (patches / "0001-can-setup-harden.patch").write_text(
                "\n".join(
                    [
                        "--- a/mujina_control/can_setup.sh",
                        "+++ b/mujina_control/can_setup.sh",
                        "@@ -1 +1 @@",
                        "-ip link set can0 up",
                        "+ip link set can0 type can bitrate 1000000 restart-ms 100",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            self._write_required_assisted_patches(patches)

            vanilla = prepare_workspace(paths, mode="vanilla")
            self.assertEqual((paths.upstream_dir / "mujina_control" / "can_setup.sh").read_text(encoding="utf-8"), "ip link set can0 up\n")
            self.assertFalse(vanilla.patched)

            assisted = prepare_workspace(paths, mode="assisted")
            self.assertIn(
                "restart-ms 100",
                (paths.upstream_dir / "mujina_control" / "can_setup.sh").read_text(encoding="utf-8"),
            )
            self.assertTrue(assisted.patched)
            self.assertEqual(assisted.patch_count, 4)

            diagnostic = prepare_workspace(paths, mode="diagnostic")
            self.assertEqual(diagnostic.returncode, 0, diagnostic.stderr)
            self.assertFalse(diagnostic.patched)
            self.assertIn("+diagnostic+", diagnostic.workspace_signature)

    def test_assisted_mode_warns_when_patch_queue_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            vendored = self._api("vendored_upstream_path")(paths)
            prepare_workspace = self._api("prepare_workspace_from_vendored_upstream")

            (vendored / ".mujina-upstream.json").parent.mkdir(parents=True)
            (vendored / ".mujina-upstream.json").write_text('{"upstream_commit":"commit-a"}\n', encoding="utf-8")
            (vendored / "README.md").write_text("official upstream\n", encoding="utf-8")

            assisted = prepare_workspace(paths, mode="assisted")

            self.assertEqual(assisted.returncode, 0, assisted.stderr)
            self.assertFalse(assisted.patched)
            self.assertIn("patch queue is empty", assisted.stdout)

    def test_workspace_dirty_invalidates_sim_verified_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            paths.ensure_directories()
            vendored = self._api("vendored_upstream_path")(paths)
            prepare_workspace = self._api("prepare_workspace_from_vendored_upstream")
            sync_runtime_workspace_state = self._api("sync_runtime_workspace_state")
            workspace_dirty = self._api("workspace_dirty")

            (vendored / ".mujina-upstream.json").write_text('{"upstream_commit":"commit-a"}\n', encoding="utf-8")
            (vendored / "README.md").write_text("official upstream\n", encoding="utf-8")

            prepared = prepare_workspace(paths, mode="vanilla")
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            state = RuntimeState(
                workspace_signature=prepared.workspace_signature,
                last_sim_success=True,
                last_sim_verified_workspace_signature=prepared.workspace_signature,
                last_sim_verified_at="2026-04-30T12:00:00+09:00",
            )

            (paths.upstream_dir / "README.md").write_text("local workspace edit\n", encoding="utf-8")
            sync_runtime_workspace_state(paths, state)

            self.assertTrue(workspace_dirty(paths))
            self.assertTrue(state.workspace_dirty)
            self.assertFalse(state.last_sim_success)
            self.assertEqual(state.last_sim_verified_workspace_signature, "")

    def test_prepare_workspace_fails_when_required_assisted_patches_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_repo_root(Path(tmp))
            vendored = self._api("vendored_upstream_path")(paths)
            patches = self._api("patches_path")(paths)
            prepare_workspace = self._api("prepare_workspace_from_vendored_upstream")

            (vendored / "README.md").parent.mkdir(parents=True)
            (vendored / "README.md").write_text("official upstream\n", encoding="utf-8")
            patches.mkdir(parents=True)
            (patches / "0001-readme.patch").write_text(
                "\n".join(
                    [
                        "diff --git a/README.md b/README.md",
                        "index 1111111..2222222 100644",
                        "--- a/README.md",
                        "+++ b/README.md",
                        "@@ -1 +1 @@",
                        "-official upstream",
                        "+assisted upstream",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            assisted = prepare_workspace(paths, mode="assisted")

            self.assertEqual(assisted.returncode, 1)
            self.assertIn("missing required patches: 0002, 0003, 0004", assisted.stderr)
            self.assertFalse(paths.upstream_dir.exists())

    def test_git_format_patch_applies_inside_workspace_under_parent_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            paths = AppPaths.from_repo_root(repo_root)
            vendored = self._api("vendored_upstream_path")(paths)
            patches = self._api("patches_path")(paths)
            prepare_workspace = self._api("prepare_workspace_from_vendored_upstream")

            (repo_root / "README.md").write_text("parent repo file\n", encoding="utf-8")
            (vendored / "mujina_control").mkdir(parents=True)
            (vendored / "README.md").write_text("official upstream\n", encoding="utf-8")
            (vendored / "mujina_control" / "can_setup.sh").write_text("ip link set can0 up\n", encoding="utf-8")
            patches.mkdir(parents=True)
            (patches / "0001-can-setup-harden.patch").write_text(
                "\n".join(
                    [
                        "diff --git a/mujina_control/can_setup.sh b/mujina_control/can_setup.sh",
                        "index 1111111..2222222 100644",
                        "--- a/mujina_control/can_setup.sh",
                        "+++ b/mujina_control/can_setup.sh",
                        "@@ -1 +1 @@",
                        "-ip link set can0 up",
                        "+ip link set can0 type can bitrate 1000000 restart-ms 100",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            self._write_required_assisted_patches(patches)

            assisted = prepare_workspace(paths, mode="assisted")

            self.assertEqual(assisted.returncode, 0, assisted.stderr)
            self.assertIn(
                "restart-ms 100",
                (paths.upstream_dir / "mujina_control" / "can_setup.sh").read_text(encoding="utf-8"),
            )
            self.assertEqual((repo_root / "README.md").read_text(encoding="utf-8"), "parent repo file\n")


if __name__ == "__main__":
    unittest.main()
