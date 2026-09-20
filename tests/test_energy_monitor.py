"""Check file import, statistics, alarm boundaries and CLI errors."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import energy_monitor as monitor


class EnergyMonitorTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "readings.txt"
            path.write_text(text, encoding="utf-8")
            return monitor.load_measurements(path)

    def test_examples_match_demo(self):
        root = Path(__file__).resolve().parents[1]
        expected = monitor.analyze_measurements(
            monitor.SAMPLE_MEASUREMENTS, monitor.SAMPLE_LIMITS
        )
        for extension in ("csv", "txt"):
            with self.subTest(extension=extension):
                data, limits = monitor.load_measurements(
                    root / "examples" / f"measurements.{extension}"
                )
                results = monitor.analyze_measurements(data, limits)
                self.assertEqual(results, expected)
                self.assertEqual(results["average_count"], 2)
                self.assertAlmostEqual(
                    dict(results["average_power"])["transformer_1"],
                    463.3333333333,
                )
                self.assertEqual(
                    results["alarms"],
                    [("08:30", "transformer_1", 510, 500)],
                )

    def test_decimal_comma_bom_and_blank_lines(self):
        data, limits = self.load_text(
            "\ufeff\nPOWER;DEVICE;TIME;LIMIT\n"
            "120,5;heater;08:00;150\n\n160,2;heater;08:15;150\n"
        )
        self.assertEqual(data[0], ("08:00", "heater", 120.5))
        self.assertEqual(limits, {"heater": 150})

    def test_quoted_names_and_tabs(self):
        for delimiter in (",", "\t"):
            with self.subTest(delimiter=delimiter):
                data, _ = self.load_text(
                    delimiter.join(["time", "device", "power"]) + "\n"
                    + delimiter.join(["08:00", '"room, heater"', "10"])
                )
                self.assertEqual(data[0][1], "room, heater")

    def test_equality_negative_values_and_later_limit(self):
        data, limits = self.load_text(
            "time,device,power,limit\n"
            "08:00,battery,-100,\n"
            "08:15,battery,100,100\n"
            "08:30,transformer_1,900,\n"
        )
        results = monitor.analyze_measurements(data, limits)
        self.assertEqual(results["alarms"], [("08:15", "battery", 100, 100)])
        self.assertEqual(results["without_limit"], ["transformer_1"])
        self.assertEqual(dict(results["average_power"])["battery"], 0)

    def test_no_limit_column(self):
        data, limits = self.load_text("time device power\n08:00 pump 10\n")
        self.assertEqual(limits, {})
        self.assertEqual(data, [("08:00", "pump", 10)])

    def test_reject_invalid_files(self):
        cases = [
            "", "time,device,power\n",
            "time,power\n08:00,10\n",
            "time,device,power,power\n08:00,pump,10,20\n",
            "time,device,power\n08:00,pump\n",
            "time,device,power\n08:00,pump,10,20\n",
            "time,device,power\n,pump,10\n",
            "time,device,power\n08:00,,10\n",
            "time,device,power\n08:00,pump,no\n",
            "time,device,power\n08:00,pump,nan\n",
            "time,device,power\n08:00,pump,inf\n",
            "time,device,power,limit\n08:00,pump,10,inf\n",
            "time,device,power,limit\n08:00,pump,10,5\n08:01,pump,20,6\n",
            'time,device,power\n08:00,"pump,10\n',
        ]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    self.load_text(content)

    def test_error_includes_line_number(self):
        with self.assertRaisesRegex(ValueError, "Line 3"):
            self.load_text("time,device,power\n\n08:00,pump,no\n")

    def test_cli_file_demo_and_missing_file(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(monitor.main(["--demo"]), 0)
        self.assertIn("463.33", output.getvalue())

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "readings with spaces.txt"
            path.write_text("time device power\n08:00 pump 10\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(monitor.main([str(path)]), 0)
                with patch("builtins.input", return_value=f'"{path}"'):
                    self.assertEqual(monitor.main([]), 0)
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(monitor.main([str(path) + ".missing"]), 1)
            self.assertIn("Error:", error.getvalue())


if __name__ == "__main__":
    unittest.main()
