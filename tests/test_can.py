from __future__ import annotations

import unittest
from unittest.mock import patch

from mujina_assist.services.can import detect_slcand_processes, parse_ip_details_statistics


IP_DETAILS = """2: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 qdisc pfifo_fast state UP mode DEFAULT group default qlen 10
    link/can  promiscuity 0 allmulti 0 minmtu 0 maxmtu 0
    can state ERROR-ACTIVE (berr-counter tx 1 rx 2) restart-ms 100
          bitrate 1000000 sample-point 0.750
    RX:  bytes packets errors dropped  missed   mcast
          1280      80      3       0       0       0
    TX:  bytes packets errors dropped carrier collsns
          1024      64      4       0       0       0
    bus-errors arbit-lost error-warn error-pass bus-off
             5          0          1          0       0
"""


class CanServiceTest(unittest.TestCase):
    def test_parse_ip_details_statistics_extracts_can_fields(self) -> None:
        status = parse_ip_details_statistics(IP_DETAILS, present=True)

        self.assertTrue(status.ok)
        self.assertEqual(status.operstate, "up")
        self.assertEqual(status.controller_state, "error-active")
        self.assertEqual(status.bitrate, 1000000)
        self.assertEqual(status.restart_ms, 100)
        self.assertEqual(status.txqueuelen, 10)
        self.assertEqual(status.rx_packets, 80)
        self.assertEqual(status.tx_packets, 64)
        self.assertEqual(status.rx_errors, 3)
        self.assertEqual(status.tx_errors, 4)
        self.assertEqual(status.bus_errors, 5)
        self.assertEqual(status.bus_off, 0)
        self.assertEqual(status.berr_tx, 1)
        self.assertEqual(status.berr_rx, 2)

    def test_parse_ip_details_statistics_warns_on_bus_off(self) -> None:
        raw = IP_DETAILS.replace("ERROR-ACTIVE", "BUS-OFF").replace("state UP", "state DOWN")
        status = parse_ip_details_statistics(raw, present=True)

        self.assertFalse(status.ok)
        self.assertTrue(status.warn)
        self.assertEqual(status.controller_state, "bus-off")

    def test_detect_slcand_processes_parses_device_and_interface(self) -> None:
        ps_output = """  101 /usr/bin/slcand -o -c -s8 /dev/usb_can can0
  202 /usr/bin/python something.py
  303 slcand -o -c -s6 /dev/ttyACM0 can1
"""
        completed = type("Completed", (), {"returncode": 0, "stdout": ps_output})()
        with patch("mujina_assist.services.can.command_exists", return_value=True), patch(
            "mujina_assist.services.can.subprocess.run",
            return_value=completed,
        ):
            processes = detect_slcand_processes(interface="can0", device="/dev/usb_can")

        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].pid, 101)
        self.assertEqual(processes[0].device, "/dev/usb_can")
        self.assertEqual(processes[0].interface, "can0")


if __name__ == "__main__":
    unittest.main()
