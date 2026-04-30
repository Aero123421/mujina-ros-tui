from __future__ import annotations

import unittest

from mujina_assist.models import DoctorCheck, DoctorReport, RuntimeState
from mujina_assist.services.safety import evaluate_real_preflight, p0_reasons
from mujina_assist.services.zero import new_zero_profile, validate_zero_profile


def _ready_report() -> DoctorReport:
    return DoctorReport(
        os_label="Ubuntu 24.04",
        ubuntu_24_04=True,
        ros_installed=True,
        workspace_cloned=True,
        workspace_built=True,
        active_policy_label="公式デフォルト",
        active_policy_hash="abc",
        sim_ready=True,
        real_devices={
            "/dev/rt_usb_imu": True,
            "/dev/usb_can": False,
            "/dev/input/js0": True,
            "can0": True,
        },
        imu_port_label="/dev/rt_usb_imu",
        checks=[DoctorCheck("can", "CAN", "ok", "can0 ok")],
    )


class SafetyTest(unittest.TestCase):
    def test_real_preflight_unlocks_when_p0_conditions_are_clear(self) -> None:
        zero = validate_zero_profile(
            new_zero_profile(result="verified", operator_confirmed=True, post_zero_max_abs_position_rad=0.01)
        )

        safety = evaluate_real_preflight(
            _ready_report(),
            RuntimeState(),
            zero_profile=zero,
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        self.assertFalse(safety.real_launch_locked)
        self.assertEqual(p0_reasons(safety), [])

    def test_real_preflight_blocks_missing_zero_and_confirmation(self) -> None:
        safety = evaluate_real_preflight(_ready_report(), RuntimeState())

        codes = {reason.code for reason in p0_reasons(safety)}
        self.assertTrue(safety.real_launch_locked)
        self.assertIn("zero_profile_missing", codes)
        self.assertIn("operator_checklist", codes)
        self.assertIn("real_confirmation", codes)

    def test_real_preflight_blocks_external_policy_without_manifest(self) -> None:
        report = _ready_report()
        report.active_policy_label = "USB: custom.onnx"
        report.active_policy_source = "/tmp/custom.onnx"
        zero = validate_zero_profile(
            new_zero_profile(result="verified", operator_confirmed=True, post_zero_max_abs_position_rad=0.01)
        )

        safety = evaluate_real_preflight(
            report,
            RuntimeState(),
            zero_profile=zero,
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        self.assertIn("policy_manifest_missing", {reason.code for reason in p0_reasons(safety)})

    def test_real_preflight_blocks_imu_fallback_without_fixed_name(self) -> None:
        report = _ready_report()
        report.real_devices["/dev/rt_usb_imu"] = False
        report.imu_port_label = "/dev/ttyACM0"
        report.imu_port_fallback = True
        zero = validate_zero_profile(new_zero_profile(post_zero_max_abs_position_rad=0.01))

        safety = evaluate_real_preflight(
            report,
            RuntimeState(),
            zero_profile=zero,
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        self.assertIn("imu_missing", {reason.code for reason in p0_reasons(safety)})

    def test_serial_can_requires_slcand_can0_and_ok_can_check(self) -> None:
        report = _ready_report()
        report.real_devices["/dev/usb_can"] = True
        report.real_devices["can0"] = False
        report.tool_status["slcand"] = False
        report.checks = [DoctorCheck("can", "CAN", "warn", "/dev/usb_can only")]
        zero = validate_zero_profile(
            new_zero_profile(result="verified", operator_confirmed=True, post_zero_max_abs_position_rad=0.01)
        )

        safety = evaluate_real_preflight(
            report,
            RuntimeState(),
            zero_profile=zero,
            can_mode="serial",
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        codes = {reason.code for reason in p0_reasons(safety)}
        self.assertIn("serial_can0_missing", codes)
        self.assertIn("slcand_missing", codes)
        self.assertIn("can_unhealthy", codes)


if __name__ == "__main__":
    unittest.main()
