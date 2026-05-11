"""SQLite persistence layer for the Procurement Agent.

Three tables:

* ``decisions``       - operator's yes/no/later verdict per asset_id.
                        Feeds the bargain learner (which categories the user
                        actually wants) and the alert filter.
* ``observations``    - historical final auction prices once an auction has
                        ended. Feeds the bargain learner's market-value
                        recalibration per category.
* ``agent_runs``      - log of every specialist agent run: which agent, when,
                        how many opportunities it surfaced, top recommendation.
                        Shown in the dashboard's "Agent Monitor" tab.

Uses the stdlib ``sqlite3`` module - no SQLAlchemy or migrations system. The
DB file path defaults to ``procurement.db`` in the project root but can be
overridden via the ``PROCUREMENT_DB`` env var (useful in tests).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

DB_PATH = os.getenv("PROCUREMENT_DB", "procurement.db")

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    asset_id     TEXT PRIMARY KEY,
    verdict      TEXT NOT NULL CHECK (verdict IN ('YES','NO','LATER')),
    category     TEXT,
    score        INTEGER,
    net_value    REAL,
    rationale    TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    asset_id              TEXT PRIMARY KEY,
    category              TEXT NOT NULL,
    estimated_market_value REAL,
    final_price           REAL NOT NULL,
    closed_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obs_category ON observations(category);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name        TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    found_count       INTEGER DEFAULT 0,
    hot_count         INTEGER DEFAULT 0,
    top_asset_id      TEXT,
    top_score         INTEGER,
    notes             TEXT
);
"""


@contextmanager
def _connect():
    with _lock:
        conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


# Auto-init on import so dashboard code does not need to remember.
init_db()


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    asset_id: str
    verdict: str            # YES | NO | LATER
    category: str | None
    score: int | None
    net_value: float | None
    rationale: str | None
    created_at: datetime


def record_decision(
    asset_id: str,
    verdict: str,
    *,
    category: str | None = None,
    score: int | None = None,
    net_value: float | None = None,
    rationale: str | None = None,
) -> None:
    if verdict not in ("YES", "NO", "LATER"):
        raise ValueError(f"verdict must be YES/NO/LATER, got {verdict!r}")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO decisions
               (asset_id, verdict, category, score, net_value, rationale, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET
                   verdict=excluded.verdict,
                   category=excluded.category,
                   score=excluded.score,
                   net_value=excluded.net_value,
                   rationale=excluded.rationale,
                   created_at=excluded.created_at""",
            (asset_id, verdict, category, score, net_value, rationale,
             datetime.now(timezone.utc).isoformat()),
        )


def get_decision(asset_id: str) -> Decision | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM decisions WHERE asset_id = ?", (asset_id,)
        ).fetchone()
    if not row:
        return None
    return Decision(
        asset_id=row["asset_id"],
        verdict=row["verdict"],
        category=row["category"],
        score=row["score"],
        net_value=row["net_value"],
        rationale=row["rationale"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def all_decisions() -> list[Decision]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC"
        ).fetchall()
    return [
        Decision(
            asset_id=r["asset_id"],
            verdict=r["verdict"],
            category=r["category"],
            score=r["score"],
            net_value=r["net_value"],
            rationale=r["rationale"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


def category_yes_rate(category: str) -> float:
    """Fraction of decisions in the given category that were YES.

    Returns 0.5 if no data yet (neutral prior so the learner does not
    over-react to a single decision).
    """
    with _connect() as conn:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN verdict='YES' THEN 1 ELSE 0 END) AS yes_n,
                 COUNT(*) AS total_n
               FROM decisions WHERE category = ?""",
            (category,),
        ).fetchone()
    total = row["total_n"] or 0
    if total == 0:
        return 0.5
    return (row["yes_n"] or 0) / total


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

def record_observation(
    asset_id: str,
    category: str,
    final_price: float,
    estimated_market_value: float | None = None,
    closed_at: datetime | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO observations
               (asset_id, category, estimated_market_value, final_price, closed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET
                   final_price=excluded.final_price,
                   estimated_market_value=excluded.estimated_market_value""",
            (asset_id, category, estimated_market_value, final_price,
             (closed_at or datetime.now(timezone.utc)).isoformat()),
        )


def observed_ratio(category: str) -> tuple[float, int]:
    """Return (mean final/estimated price ratio, sample size) for category.

    Used by the learner to correct overestimated market values.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT estimated_market_value, final_price
               FROM observations
               WHERE category = ? AND estimated_market_value IS NOT NULL
                 AND estimated_market_value > 0""",
            (category,),
        ).fetchall()
    if not rows:
        return 1.0, 0
    ratios = [r["final_price"] / r["estimated_market_value"] for r in rows]
    return sum(ratios) / len(ratios), len(ratios)


# ---------------------------------------------------------------------------
# Agent runs
# ---------------------------------------------------------------------------

@dataclass
class AgentRun:
    id: int
    agent_name: str
    started_at: datetime
    finished_at: datetime | None
    found_count: int
    hot_count: int
    top_asset_id: str | None
    top_score: int | None
    notes: str | None


def start_agent_run(agent_name: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO agent_runs (agent_name, started_at) VALUES (?, ?)",
            (agent_name, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def finish_agent_run(
    run_id: int,
    *,
    found_count: int,
    hot_count: int,
    top_asset_id: str | None,
    top_score: int | None,
    notes: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE agent_runs SET
                 finished_at=?, found_count=?, hot_count=?,
                 top_asset_id=?, top_score=?, notes=?
               WHERE id=?""",
            (datetime.now(timezone.utc).isoformat(), found_count, hot_count,
             top_asset_id, top_score, notes, run_id),
        )


def recent_runs(limit: int = 20) -> list[AgentRun]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [
        AgentRun(
            id=r["id"],
            agent_name=r["agent_name"],
            started_at=datetime.fromisoformat(r["started_at"]),
            finished_at=(
                datetime.fromisoformat(r["finished_at"])
                if r["finished_at"] else None
            ),
            found_count=r["found_count"] or 0,
            hot_count=r["hot_count"] or 0,
            top_asset_id=r["top_asset_id"],
            top_score=r["top_score"],
            notes=r["notes"],
        )
        for r in rows
    ]


def last_run_per_agent() -> dict[str, AgentRun]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM agent_runs r1
               WHERE id = (
                   SELECT MAX(id) FROM agent_runs r2 WHERE r2.agent_name = r1.agent_name
               )"""
        ).fetchall()
    return {
        r["agent_name"]: AgentRun(
            id=r["id"],
            agent_name=r["agent_name"],
            started_at=datetime.fromisoformat(r["started_at"]),
            finished_at=(
                datetime.fromisoformat(r["finished_at"])
                if r["finished_at"] else None
            ),
            found_count=r["found_count"] or 0,
            hot_count=r["hot_count"] or 0,
            top_asset_id=r["top_asset_id"],
            top_score=r["top_score"],
            notes=r["notes"],
        )
        for r in rows
    }


def export_decisions_csv() -> str:
    """Return a CSV of all decisions (semicolon-separated, German conventions)."""
    decisions = all_decisions()
    lines = ["asset_id;verdict;category;score;net_value;rationale;created_at"]
    for d in decisions:
        lines.append(
            f"{d.asset_id};{d.verdict};{d.category or ''};"
            f"{d.score if d.score is not None else ''};"
            f"{(f'{d.net_value:.2f}'.replace('.', ',')) if d.net_value is not None else ''};"
            f"{(d.rationale or '').replace(chr(10), ' ').replace(';', ',')};"
            f"{d.created_at.isoformat()}"
        )
    return "\n".join(lines)
