#!/usr/bin/env python3
"""Simple test script."""

import sys

if len(sys.argv) < 2:
    print("Usage: python hello.py <device_udid>")
    sys.exit(1)

udid = sys.argv[1]
print(f"Hello from device: {udid}")
