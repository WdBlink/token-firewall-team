#!/usr/bin/env python3
"""Rebuild shadow records and reports from archived Jev responses without API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "skills/token-firewall-team/scripts/token_firewall_runtime"
sys.path.insert(0, str(RUNTIME))

from tools.token_firewall.routing_shadow import attach_typesafe_requests, write_shadow_artifacts  # noqa: E402


tasks = json.loads((Path(__file__).parent / "tasks.json").read_text(encoding="utf-8"))
out_dir = ROOT / "evidence/route-shadow/typesafe-jev-20-001"
records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
attach_typesafe_requests(tasks, records, model="jev-1.13.0")
write_shadow_artifacts(records, out_dir)
print(out_dir / "standard-experiment-report.md")
