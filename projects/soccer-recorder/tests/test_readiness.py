import unittest

from soccer_recorder.readiness import (
    MacReadiness,
    parse_lid_open,
    parse_power_connected,
    parse_sleep_prevention,
)


class ReadinessTests(unittest.TestCase):
    def test_parses_soccer_recorder_caffeinate_assertion(self) -> None:
        output = """
Assertion status system-wide:
   PreventUserIdleSystemSleep     1
   pid 20011(caffeinate): caffeinate command-line tool
   Details: caffeinate asserting on behalf of '/Applications/Soccer Recorder.app/Contents/MacOS/Soccer Recorder'
"""
        self.assertTrue(parse_sleep_prevention(output))
        self.assertFalse(parse_sleep_prevention("PreventUserIdleSystemSleep 1\npid 1(powerd)"))

    def test_parses_power_and_lid(self) -> None:
        self.assertTrue(parse_power_connected("Now drawing from 'AC Power'"))
        self.assertFalse(parse_power_connected("Now drawing from 'Battery Power'"))
        self.assertTrue(parse_lid_open('"AppleClamshellState" = No'))
        self.assertFalse(parse_lid_open('"AppleClamshellState" = Yes'))

    def test_readiness_explains_failures(self) -> None:
        report = MacReadiness(True, True, False, True)
        self.assertFalse(report.ready)
        self.assertIn("power adapter", report.details())
        self.assertTrue(MacReadiness(True, True, True, True).ready)


if __name__ == "__main__":
    unittest.main()
