#!/usr/bin/env python3
"""Demo script: takes a screenshot on the target device and prints basic info."""

import sys
import subprocess

if len(sys.argv) < 2:
    print("Usage: python demo_screen.py <device_udid>")
    sys.exit(1)

udid = sys.argv[1]

print(f"Target device: {udid}")
print("Taking screenshot...")

result = subprocess.run(
    ["adb", "-s", udid, "exec-out", "screencap", "-p"],
    capture_output=True,
)
if result.returncode == 0:
    print(f"Screenshot captured: {len(result.stdout)} bytes")
else:
    print(f"Failed: {result.stderr.decode()}")
    sys.exit(1)
