"""Summarize power measurements from TXT/CSV files or sample data.

Program flow:
    main() selects the input file or demonstration data.
    load_measurements() reads and validates imported rows.
    analyze_measurements() calculates statistics and threshold alarms.
    report() prints the results in the terminal.

Each measurement is a (time, device, power) tuple. Alarm limits are stored
separately as a dictionary mapping device names to numeric thresholds.
"""

import argparse
import csv
import math
import sys
from pathlib import Path


# Invented readings used when the user selects the demonstration.
# Power values and alarm limits must use the same unit throughout the data.
SAMPLE_MEASUREMENTS = [
    ("08:00", "solar_inverter", 180),
    ("08:00", "transformer_1", 420),
    ("08:15", "transformer_1", 460),
    ("08:15", "solar_inverter", 210),
    ("08:30", "transformer_1", 510),
    ("08:30", "battery", -80),
]

# These thresholds apply only to the demonstration, not imported files.
SAMPLE_LIMITS = {
    "transformer_1": 500,
    "solar_inverter": 250,
    "battery": 100,
}


def parse_number(value, field, line_number):
    """Read a finite number, accepting a decimal point or decimal comma."""
    try:
        # Normalize the decimal separator before converting text to a float.
        number = float(value.replace(",", "."))
    except ValueError:
        raise ValueError(
            f"Line {line_number}: {field} must be a number."
        ) from None  # Hide the original conversion error for a clear message.

    # float() accepts NaN and infinity, but they are invalid measurements here.
    if not math.isfinite(number):
        raise ValueError(
            f"Line {line_number}: {field} must be finite."
        )
    return number


def load_measurements(path):
    """Read a UTF-8 file with time, device, power and optional limit columns.

    Detect comma, semicolon or tab delimiters from the header. Plain TXT
    files may also use spaces. A device has one limit throughout the file.
    Imported data never inherits the demonstration alarm limits.

    Returns a list of (time, device, power) tuples and a device-limit dict.
    Invalid input raises an error instead of returning a partial dataset.
    """
    # utf-8-sig also accepts files with a UTF-8 byte-order mark (BOM).
    # newline="" lets the CSV reader handle the file's line endings.
    # The with block closes the file automatically, even if reading fails.
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        lines = source.readlines()

    # Use the first non-empty line as the header. next() returns its default
    # (an empty string) if the file has no non-empty lines.
    header = next((line for line in lines if line.strip()), "")
    # Look for an explicit separator; otherwise, split on whitespace.
    delimiter = next(
        (symbol for symbol in (";", "\t", ",") if symbol in header),
        None,
    )
    if delimiter is None:
        # enumerate() retains line numbers for helpful validation errors.
        rows = enumerate((line.split() for line in lines), start=1)
    else:
        # csv.reader handles quoted fields containing the separator.
        # For a multiline quoted record, line_num is its ending line number.
        reader = csv.reader(lines, delimiter=delimiter, strict=True)
        rows = ((reader.line_num, row) for row in reader)

    columns = None
    measurements = []
    limits = {}

    try:
        for line_number, row in rows:
            # Ignore blank rows, including rows containing only separators.
            if not row or not any(value.strip() for value in row):
                continue

            values = [value.strip() for value in row]

            if columns is None:
                # Read the header once; normalize names to ignore their case.
                columns = [value.lower() for value in values]
                required = {"time", "device", "power"}
                # Set union adds the optional limit column to allowed names.
                allowed = required | {"limit"}
                # Reject duplicate names, missing fields and unknown columns.
                if (
                    len(set(columns)) != len(columns)
                    or not required.issubset(columns)
                    or not set(columns).issubset(allowed)
                ):
                    raise ValueError(
                        "Header must contain time, device and power; "
                        "an optional limit column is allowed."
                    )
                continue  # The header is not a measurement.

            # Check row width before pairing column names with their values.
            if len(values) != len(columns):
                raise ValueError(
                    f"Line {line_number}: expected {len(columns)} "
                    f"columns, found {len(values)}."
                )

            # zip() pairs headers with values, allowing any column order.
            record = dict(zip(columns, values))
            # Keep time as a text label; no date parsing or sorting is done.
            time = record["time"]
            device = record["device"]
            if not time or not device:
                raise ValueError(
                    f"Line {line_number}: time and device cannot be empty."
                )

            power = parse_number(record["power"], "power", line_number)
            # get() returns an empty string when the optional column is absent.
            limit_text = record.get("limit", "")
            if limit_text:
                limit = parse_number(limit_text, "limit", line_number)
                # A device must have one consistent threshold across the file.
                if device in limits and limits[device] != limit:
                    raise ValueError(
                        f"Line {line_number}: conflicting limits "
                        f"for {device!r}. Use one limit per device."
                    )
                limits[device] = limit

            # Store a row only after all of its fields have passed validation.
            measurements.append((time, device, power))
    except csv.Error as error:
        raise ValueError(f"Invalid delimited file: {error}") from None

    if not measurements:
        raise ValueError("The file contains no measurements.")

    # All limits are collected before analysis, so a threshold supplied later
    # in the file also applies to earlier readings from the same device.
    return measurements, limits


def analyze_measurements(measurements, limits):
    """Return counts, arithmetic mean power and signed threshold alarms.

    Counts and means are sorted from highest to lowest. Alarm entries keep
    input order and contain (time, device, power, limit). Devices without a
    threshold are listed separately so missing checks are visible.
    """
    device_counts = {}
    total_power = {}
    alarms = []

    for time, device, power in measurements:
        # get(..., 0) starts the count or sum when a device first appears.
        device_counts[device] = device_counts.get(device, 0) + 1
        # This sum is used for a mean; it is not energy consumption in kWh.
        total_power[device] = total_power.get(device, 0.0) + power

        # Equality triggers an alarm; negative values keep their sign.
        if device in limits and power >= limits[device]:
            alarms.append((time, device, power, limits[device]))

    # Dictionary comprehension calculates one arithmetic mean per device.
    # Measurement spacing is not used to weight the readings.
    average_power = {
        device: total_power[device] / count
        for device, count in device_counts.items()
    }
    # Each sorted item is a (device, value) pair. item[1] selects the value;
    # reverse=True places the largest counts or means first.
    return {
        "device_counts": sorted(
            device_counts.items(), key=lambda item: item[1], reverse=True
        ),
        "average_count": (
            # Avoid division by zero if this function receives an empty list.
            len(measurements) / len(device_counts) if device_counts else 0.0
        ),
        "average_power": sorted(
            average_power.items(), key=lambda item: item[1], reverse=True
        ),
        "alarms": alarms,
        # Missing limits do not stop statistics, but prevent alarm checks.
        "without_limit": [
            device for device in device_counts if device not in limits
        ],
    }


def report(results):
    """Display results in the same power unit as the input data."""
    # Formatting is kept separate from the calculations for easier reuse.
    print("=" * 40)
    print(" ENERGY MONITORING REPORT")
    print("=" * 40)
    print("\nMeasurement counts by device:")
    for device, count in results["device_counts"]:
        print(f"{device}: {count}")

    # :.2f displays averages with two digits after the decimal point.
    print(
        "\nAverage number of measurements per device: "
        f"{results['average_count']:.2f}"
    )
    print("\nSorted average power (input units):")
    for device, average in results["average_power"]:
        print(f"{device}: {average:.2f}")

    print("\nThreshold alarms:")
    if not results["alarms"]:
        print("No alarms for devices with configured limits.")
    for time, device, power, limit in results["alarms"]:
        # :g uses compact numeric formatting, e.g. 500 instead of 500.0.
        print(
            f"Alarm: {device} at {time}: "
            f"{power:g} >= limit {limit:g}"
        )

    # Distinguish a missing threshold from a device that passed its check.
    if results["without_limit"]:
        print(
            "\nNo alarm limit configured for: "
            + ", ".join(results["without_limit"])
        )


def main(argv=None):
    """Coordinate input, analysis and output; return an exit status.

    Return 0 on success or 1 on a file/data error or user cancellation.
    argparse handles invalid command-line usage separately with status 2.
    argv=None reads terminal arguments; tests can supply a list instead.
    """
    # argparse provides command-line options and automatic --help output.
    parser = argparse.ArgumentParser(
        description="Analyze power measurements from a TXT or CSV file."
    )
    # nargs="?" makes the path optional, allowing an interactive prompt.
    parser.add_argument("file", nargs="?", help="Path to a UTF-8 TXT/CSV file")
    # store_true turns the presence of --demo into a Boolean True value.
    parser.add_argument(
        "--demo", action="store_true", help="Use built-in sample readings"
    )
    args = parser.parse_args(argv)
    # The user must select one data source, not a file and the demo together.
    if args.file and args.demo:
        parser.error("Choose either a file or --demo, not both.")

    file_path = args.file
    try:
        if not file_path and not args.demo:
            # Remove outer spaces and quotes from a pasted Windows file path.
            file_path = input(
                "TXT/CSV file path (press Enter for sample data): "
            ).strip().strip("\"'")

        if file_path:
            # expanduser() resolves a leading ~ to the user's home directory.
            measurements, limits = load_measurements(
                Path(file_path).expanduser()
            )
            print(f"Loaded {len(measurements)} measurements from {file_path}")
        else:
            # --demo or an empty interactive answer selects sample readings.
            measurements = SAMPLE_MEASUREMENTS
            limits = SAMPLE_LIMITS
            print("Using built-in sample data.")

        # Pass the calculated result dictionary straight to the report printer.
        report(analyze_measurements(measurements, limits))
    except (OSError, UnicodeError, ValueError) as error:
        # Send file, encoding and data errors to the terminal's error stream.
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        # Handle closed input or Ctrl+C without displaying a traceback.
        print("\nCancelled.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Run only when launched directly, not when imported by another script.
    # main() returns the exit status; SystemExit passes it to the terminal.
    raise SystemExit(main())
