#!/usr/bin/env python3
"""Přehled překladu – launcher (kept under the old name so shortcuts and the build keep working).

Run `py progress.py` for the window; command line options are listed in README.md.
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from prehled.cli import run  # noqa: E402

if __name__ == "__main__":
    run()
