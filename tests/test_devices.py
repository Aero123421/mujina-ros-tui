from __future__ import annotations

import unittest
from unittest.mock import patch

from mujina_assist.services.devices import SerialCandidate, list_serial_device_candidates, resolve_imu_port


class DevicesServiceTest(unittest.TestCase):
    def test_serial_candidate_summary_includes_usb_identity_and_by_id(self) -> None:
        candidate = SerialCandidate(
            path="/dev/ttyACM0",
            kind="ttyACM",
            by_id=["/dev/serial/by-id/usb-CANable_123"],
            vendor_id="1d50",
            product_id="606f",
            product="candleLight",
        )

        summary = candidate.summary()

        self.assertIn("/dev/ttyACM0", summary)
        self.assertIn("vid:pid=1d50:606f", summary)
        self.assertIn("candleLight", summary)
        self.assertIn("/dev/serial/by-id/usb-CANable_123", summary)

    def test_list_serial_device_candidates_keeps_legacy_string_api(self) -> None:
        candidates = [
            SerialCandidate(path="/dev/ttyUSB0", kind="ttyUSB"),
            SerialCandidate(path="/dev/ttyACM0", kind="ttyACM"),
        ]
        with patch("mujina_assist.services.devices.list_serial_candidate_details", return_value=candidates):
            self.assertEqual(list_serial_device_candidates(), ["/dev/ttyUSB0", "/dev/ttyACM0"])

    def test_resolve_imu_port_requires_fixed_name_or_single_fallback(self) -> None:
        with patch("mujina_assist.services.devices.Path.exists", return_value=False), patch(
            "mujina_assist.services.devices.list_serial_device_candidates",
            return_value=["/dev/ttyUSB0", "/dev/ttyACM0"],
        ):
            port, fallback, candidates = resolve_imu_port()

        self.assertIsNone(port)
        self.assertFalse(fallback)
        self.assertEqual(candidates, ["/dev/ttyUSB0", "/dev/ttyACM0"])


if __name__ == "__main__":
    unittest.main()
