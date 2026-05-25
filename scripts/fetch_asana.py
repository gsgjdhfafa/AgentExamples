#!/usr/bin/env python3
"""Dump my open Asana tasks to data/asana_tasks.json.

Run on your own machine:

    export ASANA_PAT='2/.../...:...'
    python scripts/fetch_asana.py

Then either commit the JSON or paste it back into the dashboard sandbox.
The Heute-Tab picks it up automatically the next time it reloads.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import procurement_asana as pa  # noqa: E402

OUT = ROOT / "data" / "asana_tasks.json"


def main() -> int:
    client = pa.AsanaClient()
    if not client.is_configured():
        print(f"FAIL: {client.reason_unavailable()}", file=sys.stderr)
        return 1
    tasks = client.fetch_my_open_tasks(horizon_days=14)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": [
            {
                "gid": t.gid,
                "name": t.name,
                "due_on": t.due_on.isoformat() if t.due_on else None,
                "completed": t.completed,
                "project_names": t.project_names,
                "permalink_url": t.permalink_url,
                "assignee_status": t.assignee_status,
            }
            for t in tasks
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {len(tasks)} tasks to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
