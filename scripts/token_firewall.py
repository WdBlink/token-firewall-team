#!/usr/bin/env python3
"""Installed entry point for the bundled Token Firewall Runtime."""

from __future__ import annotations

import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent / "token_firewall_runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

from tools.token_firewall.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
