from __future__ import annotations

import unittest
from unittest.mock import patch

from mujina_assist.services.live_health import collect_live_health


CAN_OK = {
    "present": True,
    "operstate": "up",
    "controller_state": "error-active",
    "bitrate": 1000000,
    "rx_errors": 0,
    "tx_errors": 0,
    "bus_errors": 0,
    "bus_off": 0,
    "ok": True,
    "warn": False,
}


class LiveHealthTest(unittest.TestCase):
    def test_collect_live_health_falls_back_when_ros2_is_missing(self) -> None:
        with patch(
            "mujina_assist.services.live_health.detect_real_devices",
            return_value={"/dev/rt_usb_imu": True, "/dev/input/js0": True},
        ), patch(
            "mujina_assist.services.live_health.inspect_can_status",
            return_value=CAN_OK,
        ), patch(
            "mujina_assist.services.live_health.shutil.which",
            return_value=None,
        ):
            health = collect_live_health()

        self.assertTrue(health.can_ok)
        self.assertTrue(health.imu_ok)
        self.assertTrue(health.joy_ok)
        self.assertFalse(health.ros_available)
        self.assertIn("ROS 2 is not available", "\n".join(health.warnings))


if __name__ == "__main__":
    unittest.main()
