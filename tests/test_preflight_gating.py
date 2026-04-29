from __future__ import annotations

import unittest

from mujina_assist.models import DoctorCheck, DoctorReport, RuntimeState
from mujina_assist.services.policy_manifest import PolicyManifestValidation
from mujina_assist.services.safety import evaluate_real_preflight, p0_reasons
from mujina_assist.services.zero import ZeroProfileValidation


class PreflightGatingTest(unittest.TestCase):
    def _ready_report(self) -> DoctorReport:
        return DoctorReport(
            os_label="Ubuntu 24.04",
            ubuntu_24_04=True,
            ros_installed=True,
            workspace_cloned=True,
            workspace_built=True,
            active_policy_label="公式デフォルト",
            active_policy_source="cache/default_policy.onnx",
            active_policy_hash="policy-sha256",
            sim_ready=True,
            real_devices={
                "/dev/rt_usb_imu": True,
                "/dev/usb_can": True,
                "/dev/input/js0": True,
                "can0": True,
            },
            imu_port_label="/dev/rt_usb_imu",
            imu_port_fallback=False,
            checks=[DoctorCheck("can", "CAN", "ok", "can0 ERROR-ACTIVE")],
        )

    def _ready_state(self) -> RuntimeState:
        return RuntimeState(
            active_policy_hash="policy-sha256",
            last_sim_success=True,
            last_sim_policy_hash="policy-sha256",
            last_sim_verified_workspace_signature="38ff97f+patches-abc",
        )

    def test_all_clear_preflight_allows_real_launch(self) -> None:
        safety = evaluate_real_preflight(
            self._ready_report(),
            self._ready_state(),
            policy_manifest=PolicyManifestValidation(ok=True),
            zero_profile=ZeroProfileValidation(ok=True),
            can_mode="net",
            active_job_kinds=set(),
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        self.assertFalse(safety.real_launch_locked)
        self.assertEqual(p0_reasons(safety), [])

    def test_workspace_or_policy_signature_mismatch_blocks_as_sim_unverified(self) -> None:
        report = self._ready_report()
        report.sim_ready = False

        safety = evaluate_real_preflight(
            report,
            self._ready_state(),
            policy_manifest=PolicyManifestValidation(ok=True),
            zero_profile=ZeroProfileValidation(ok=True),
            can_mode="net",
            active_job_kinds=set(),
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        hard_block_codes = [reason.code for reason in p0_reasons(safety)]
        self.assertTrue(safety.real_launch_locked)
        self.assertIn("sim_unverified", hard_block_codes)

    def test_external_policy_without_manifest_blocks_real_launch(self) -> None:
        report = self._ready_report()
        report.active_policy_label = "USB: policy-a.onnx"
        report.active_policy_source = "/media/user/policy-a.onnx"

        safety = evaluate_real_preflight(
            report,
            self._ready_state(),
            policy_manifest=None,
            zero_profile=ZeroProfileValidation(ok=True),
            can_mode="net",
            active_job_kinds=set(),
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        hard_block_codes = [reason.code for reason in p0_reasons(safety)]
        self.assertTrue(safety.real_launch_locked)
        self.assertIn("policy_manifest_missing", hard_block_codes)

    def test_unhealthy_can_and_missing_zero_profile_are_hard_blocks(self) -> None:
        report = self._ready_report()
        report.checks = [DoctorCheck("can", "CAN", "ng", "can0 BUS-OFF")]

        safety = evaluate_real_preflight(
            report,
            self._ready_state(),
            policy_manifest=PolicyManifestValidation(ok=True),
            zero_profile=None,
            can_mode="net",
            active_job_kinds=set(),
            operator_checklist_complete=True,
            real_confirmation="REAL",
        )

        hard_block_codes = [reason.code for reason in p0_reasons(safety)]
        self.assertTrue(safety.real_launch_locked)
        self.assertIn("can_unhealthy", hard_block_codes)
        self.assertIn("zero_profile_missing", hard_block_codes)


if __name__ == "__main__":
    unittest.main()
