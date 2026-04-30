from __future__ import annotations

import importlib
import unittest


try:
    can_module = importlib.import_module("mujina_assist.services.can")
except ImportError:  # pragma: no cover - documents the expected CAN parser service while it is absent.
    can_module = None


REQUIRED_CAN_API = (
    "parse_ip_details_statistics",
)


IP_DETAILS_STATISTICS_SAMPLE = """\
4: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 qdisc pfifo_fast state UP mode DEFAULT group default qlen 10
    link/can  promiscuity 0 allmulti 0 minmtu 0 maxmtu 0
    can state ERROR-ACTIVE (berr-counter tx 0 rx 0) restart-ms 100
          bitrate 1000000 sample-point 0.750
          tq 12 prop-seg 29 phase-seg1 30 phase-seg2 20 sjw 1
    RX:  bytes packets errors dropped  missed   mcast
          4816     1204      0       0       0       0
    TX:  bytes packets errors dropped carrier collsns
          4808     1202      0       0       0       0
    bus-errors arbit-lost error-warn error-pass bus-off
             0          0          0          0       0
"""


@unittest.skipIf(
    can_module is None,
    "mujina_assist.services.can is not implemented yet. "
    f"Expected API: {', '.join(REQUIRED_CAN_API)}",
)
class CanParserTest(unittest.TestCase):
    def _api(self, name: str):
        value = getattr(can_module, name, None)
        if value is None:
            self.skipTest(f"mujina_assist.services.can.{name} is not implemented yet")
        return value

    def test_parse_ip_details_statistics_extracts_state_bitrate_restart_and_counters(self) -> None:
        status = self._api("parse_ip_details_statistics")(IP_DETAILS_STATISTICS_SAMPLE)

        self.assertEqual(status.interface, "can0")
        self.assertEqual(status.operstate, "up")
        self.assertEqual(status.controller_state, "error-active")
        self.assertEqual(status.bitrate, 1000000)
        self.assertEqual(status.restart_ms, 100)
        self.assertEqual(status.rx_packets, 1204)
        self.assertEqual(status.tx_packets, 1202)
        self.assertEqual(status.rx_errors, 0)
        self.assertEqual(status.tx_errors, 0)
        self.assertTrue(status.ok)

    def test_can_health_blocks_bus_off_and_error_passive(self) -> None:
        parse = self._api("parse_ip_details_statistics")
        bus_off = parse(IP_DETAILS_STATISTICS_SAMPLE.replace("ERROR-ACTIVE", "BUS-OFF"))
        error_passive = parse(IP_DETAILS_STATISTICS_SAMPLE.replace("ERROR-ACTIVE", "ERROR-PASSIVE"))

        self.assertFalse(bus_off.ok)
        self.assertFalse(error_passive.ok)
        self.assertTrue(bus_off.warn)
        self.assertTrue(error_passive.warn)
        self.assertEqual(bus_off.controller_state, "bus-off")
        self.assertEqual(error_passive.controller_state, "error-passive")

    def test_can_health_warns_when_errors_increase_even_if_interface_is_up(self) -> None:
        parse = self._api("parse_ip_details_statistics")
        with_errors = parse(IP_DETAILS_STATISTICS_SAMPLE.replace("1204      0", "1204      7").replace("1202      0", "1202      3"))

        self.assertTrue(with_errors.present)
        self.assertEqual(with_errors.rx_errors, 7)
        self.assertEqual(with_errors.tx_errors, 3)

    def test_expected_can_health_evaluator_reports_error_reasons(self) -> None:
        evaluate = self._api("evaluate_can_health")
        parse = self._api("parse_ip_details_statistics")
        with_errors = parse(IP_DETAILS_STATISTICS_SAMPLE.replace("1204      0", "1204      7").replace("1202      0", "1202      3"))

        result = evaluate(with_errors)

        self.assertTrue(result.present)
        self.assertTrue(result.warn)
        self.assertIn("errors", " ".join(result.reasons).lower())


if __name__ == "__main__":
    unittest.main()
