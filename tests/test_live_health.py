from __future__ import annotations

import unittest
from unittest.mock import patch

from mujina_assist.services.live_health import collect_live_health, inspect_imu_topic, inspect_joy_topic, wait_for_topic_health


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

    def test_imu_topic_health_parses_hz_quaternion_and_gyro(self) -> None:
        echo = """header:
  stamp:
    sec: 1893456000
    nanosec: 0
orientation:
  x: 0.0
  y: 0.0
  z: 0.0
  w: 1.0
angular_velocity:
  x: 0.1
  y: 0.2
  z: 0.3
"""
        with patch("mujina_assist.services.live_health._ros_topic_list", return_value={"/imu/data"}), patch(
            "mujina_assist.services.live_health._topic_hz",
            return_value=198.4,
        ), patch("mujina_assist.services.live_health._topic_echo_once", return_value=echo), patch(
            "mujina_assist.services.live_health.time.time",
            return_value=1893456000.01,
        ):
            sample = inspect_imu_topic()

        self.assertTrue(sample.exists)
        self.assertEqual(sample.hz, 198.4)
        self.assertAlmostEqual(sample.quaternion_norm or 0.0, 1.0)
        self.assertTrue(sample.gyro_finite)
        self.assertLess(sample.last_age_s or 1.0, 0.2)

    def test_joy_topic_health_parses_axes_and_buttons(self) -> None:
        echo = """header:
  stamp:
    sec: 1893456000
    nanosec: 0
axes: [0.0, 0.1, 0.2, 0.3]
buttons: [0, 1, 0]
"""
        with patch("mujina_assist.services.live_health._ros_topic_list", return_value={"/joy"}), patch(
            "mujina_assist.services.live_health._topic_echo_once",
            return_value=echo,
        ), patch("mujina_assist.services.live_health.time.time", return_value=1893456000.01):
            sample = inspect_joy_topic()

        self.assertTrue(sample.exists)
        self.assertEqual(sample.axes_count, 4)
        self.assertEqual(sample.buttons_count, 3)

    def test_wait_for_topic_health_uses_topic_specific_checks(self) -> None:
        with patch("mujina_assist.services.live_health.inspect_joy_topic") as joy_mock:
            joy_mock.return_value.exists = True
            joy_mock.return_value.axes_count = 4
            joy_mock.return_value.buttons_count = 3
            joy_mock.return_value.last_age_s = 0.01

            self.assertTrue(wait_for_topic_health("/joy", timeout_s=0.1))

    def test_wait_for_topic_health_requires_echo_for_generic_topics(self) -> None:
        with patch("mujina_assist.services.live_health._ros_topic_list", return_value={"/robot_mode"}), patch(
            "mujina_assist.services.live_health._topic_echo_once",
            return_value="",
        ), patch("mujina_assist.services.live_health._topic_hz", return_value=10.0), patch(
            "mujina_assist.services.live_health.time.sleep",
            return_value=None,
        ):
            self.assertFalse(wait_for_topic_health("/robot_mode", timeout_s=0.01))

        with patch("mujina_assist.services.live_health._ros_topic_list", return_value={"/robot_mode"}), patch(
            "mujina_assist.services.live_health._topic_echo_once",
            return_value="data: 1\n",
        ), patch("mujina_assist.services.live_health._topic_hz", return_value=10.0):
            self.assertTrue(wait_for_topic_health("/robot_mode", timeout_s=0.1))

    def test_imu_parser_does_not_confuse_nested_orientation_keys(self) -> None:
        echo = """header:
  stamp:
    sec: 1893456000
    nanosec: 0
orientation_covariance:
  x: 9.0
orientation:
  x: 0.0
  y: 0.0
  z: 0.0
  w: 1.0
angular_velocity:
  x: 0.1
  y: 0.2
  z: 0.3
"""
        with patch("mujina_assist.services.live_health._ros_topic_list", return_value={"/imu/data"}), patch(
            "mujina_assist.services.live_health._topic_hz",
            return_value=198.4,
        ), patch("mujina_assist.services.live_health._topic_echo_once", return_value=echo), patch(
            "mujina_assist.services.live_health.time.time",
            return_value=1893456000.01,
        ):
            sample = inspect_imu_topic()

        self.assertAlmostEqual(sample.quaternion_norm or 0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
