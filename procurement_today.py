"""Loader + renderer helpers for the "Heute" tab.

This module is the central daily-status surface that mirrors the four
sections from the user's Triton Pipeline desktop app:

  1. Pitch-Paket (KI4KI)
  2. Bewerbungen Projekte/Programme
  3. Insolvenz / Schreiben eingegangen
  4. Betreuungsverfahren

Live data comes from `data/today_snapshot.json`, which is currently produced
manually via the Gmail MCP outside the Streamlit process. A future iteration
will read Gmail directly via in-app OAuth (see procurement_drive.py for the
pattern); for now the JSON is the contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "today_snapshot.json"


@dataclass
class ThreadRef:
    subject: str
    snippet: str
    sender: str
    last_message_at: datetime | None
    thread_id: str | None
    status: str

    @property
    def gmail_url(self) -> str | None:
        if not self.thread_id:
            return None
        return f"https://mail.google.com/mail/u/0/#inbox/{self.thread_id}"


@dataclass
class Section:
    id: str
    title: str
    subtitle: str
    source_path: str
    urgency: str  # "red" | "blue" | "yellow" | "green"
    threads: list[ThreadRef] = field(default_factory=list)
    chips: list[str] = field(default_factory=list)

    @property
    def thread_count(self) -> int:
        return sum(1 for t in self.threads if t.thread_id is not None)


@dataclass
class TodaySnapshot:
    generated_at: datetime
    source_account: str
    sections: list[Section]
    second_inbox_status: str | None
    calendar_ics_url: str | None
    tasks_source: str | None
    open_verfahren_labels: list[str]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_snapshot(path: Path = SNAPSHOT_PATH) -> TodaySnapshot | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))

    sections: list[Section] = []
    for s in raw.get("sections", []):
        threads = [
            ThreadRef(
                subject=t.get("subject", ""),
                snippet=t.get("snippet", ""),
                sender=t.get("from", ""),
                last_message_at=_parse_dt(t.get("last_message_at")),
                thread_id=t.get("thread_id"),
                status=t.get("status", ""),
            )
            for t in s.get("active_threads", [])
        ]
        sections.append(Section(
            id=s.get("id", ""),
            title=s.get("title", ""),
            subtitle=s.get("subtitle", ""),
            source_path=s.get("source_path", ""),
            urgency=s.get("urgency", "blue"),
            threads=threads,
            chips=list(s.get("chips", [])),
        ))

    return TodaySnapshot(
        generated_at=_parse_dt(raw.get("generated_at")) or datetime.now(timezone.utc),
        source_account=raw.get("source_account", ""),
        sections=sections,
        second_inbox_status=raw.get("second_inbox_status"),
        calendar_ics_url=raw.get("calendar_ics_url"),
        tasks_source=raw.get("tasks_source"),
        open_verfahren_labels=list(
            raw.get("extra_summary", {}).get("open_verfahren_labels", [])
        ),
    )


def urgency_class(urgency: str) -> str:
    """Map urgency tag to one of the existing dashboard CSS classes."""
    return {
        "red": "verdict-no",
        "yellow": "verdict-later",
        "blue": "verdict-yes",
        "green": "verdict-yes",
    }.get(urgency, "verdict-yes")


def age_label(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "(kein Datum)"
    now = now or datetime.now(timezone.utc)
    delta = now - when
    if delta.days >= 1:
        return f"vor {delta.days} Tagen"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"vor {hours} h"
    minutes = max(1, delta.seconds // 60)
    return f"vor {minutes} min"
