#!/usr/bin/env python3
"""Smoke checks for the card generator:  python3 scripts/cards/test_build.py"""
import build

# fonts embed without a timestamp, so an unchanged card is byte-identical and the daily job commits nothing
assert build.stat("dark", "665", "x", 0) == build.stat("dark", "665", "x", 0)

# with reduced motion (animations off) the digit rolls rest on the real value, not on 0
assert "transform:translateY(-%dpx)" % ((10 + 6) * 44) in build.stat("dark", "6", "x", 0)

assert build.fmt_contributions(10688) == "10,500+"
assert build.fmt_contributions(42) == "42"
assert build.fmt_thousands(17593) == "17K+"
assert build.fmt_thousands(999) == "999"
print("ok")
