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
from datetime import date, datetime, timezone

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

-- Briefe-Triage feature ----------------------------------------------------

CREATE TABLE IF NOT EXISTS letters (
    letter_id      TEXT PRIMARY KEY,
    drive_file_id  TEXT UNIQUE,
    source         TEXT NOT NULL,           -- DRIVE | UPLOAD
    filename       TEXT,
    short_code     TEXT,
    sender         TEXT,
    sender_email   TEXT,
    letter_type    TEXT NOT NULL,
    amount_eur     REAL,
    issue_date     TEXT,
    deadline_date  TEXT,
    raw_text       TEXT,
    status         TEXT DEFAULT 'NEW',      -- NEW|KEPT|DISPUTED|LATER|IGNORED
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_letters_sender   ON letters(sender);
CREATE INDEX IF NOT EXISTS idx_letters_deadline ON letters(deadline_date);

CREATE TABLE IF NOT EXISTS letter_decisions (
    letter_id   TEXT PRIMARY KEY,
    verdict     TEXT NOT NULL,
    rationale   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_dispatches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    letter_id   TEXT NOT NULL,
    channel     TEXT NOT NULL,              -- EMAIL
    recipient   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    send_at     TEXT NOT NULL,
    status      TEXT DEFAULT 'DRAFT',       -- DRAFT|SENT|CANCELLED
    sent_at     TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (letter_id) REFERENCES letters(letter_id)
);
CREATE INDEX IF NOT EXISTS idx_dispatch_status ON pending_dispatches(status);
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


# ---------------------------------------------------------------------------
# Briefe-Triage: letters
# ---------------------------------------------------------------------------

_VALID_LETTER_STATUS = ("NEW", "KEPT", "DISPUTED", "LATER", "IGNORED")
_VALID_LETTER_VERDICT = ("KEPT", "DISPUTED", "LATER", "IGNORED")
_VALID_DISPATCH_STATUS = ("DRAFT", "SENT", "CANCELLED")


def _date_or_none(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _dt_or_none(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _serialise_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _serialise_dt(value) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def record_letter(letter) -> None:
    """Upsert a Letter (procurement_letters.Letter) into the store."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO letters
               (letter_id, drive_file_id, source, filename, short_code,
                sender, sender_email, letter_type, amount_eur,
                issue_date, deadline_date, raw_text, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(letter_id) DO UPDATE SET
                   drive_file_id=excluded.drive_file_id,
                   source=excluded.source,
                   filename=excluded.filename,
                   short_code=excluded.short_code,
                   sender=excluded.sender,
                   sender_email=excluded.sender_email,
                   letter_type=excluded.letter_type,
                   amount_eur=excluded.amount_eur,
                   issue_date=excluded.issue_date,
                   deadline_date=excluded.deadline_date,
                   raw_text=excluded.raw_text,
                   status=excluded.status,
                   updated_at=excluded.updated_at""",
            (
                letter.letter_id,
                letter.drive_file_id,
                letter.source,
                letter.filename,
                letter.short_code,
                letter.sender,
                letter.sender_email,
                letter.letter_type,
                letter.amount_eur,
                _serialise_date(letter.issue_date),
                _serialise_date(letter.deadline_date),
                letter.raw_text,
                letter.status,
                _serialise_dt(letter.created_at) or now_iso,
                now_iso,
            ),
        )


def _row_to_letter(row):
    # Lazy import to avoid a circular dependency at module load time.
    from procurement_letters import Letter
    return Letter(
        letter_id=row["letter_id"],
        drive_file_id=row["drive_file_id"],
        source=row["source"],
        filename=row["filename"],
        short_code=row["short_code"],
        sender=row["sender"],
        sender_email=row["sender_email"],
        letter_type=row["letter_type"],
        amount_eur=row["amount_eur"],
        issue_date=_date_or_none(row["issue_date"]),
        deadline_date=_date_or_none(row["deadline_date"]),
        raw_text=row["raw_text"] or "",
        status=row["status"] or "NEW",
        created_at=_dt_or_none(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_dt_or_none(row["updated_at"]) or datetime.now(timezone.utc),
    )


def get_letter(letter_id: str):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM letters WHERE letter_id = ?", (letter_id,)
        ).fetchone()
    return _row_to_letter(row) if row else None


def all_letters(status: str | None = None) -> list:
    sql = "SELECT * FROM letters"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY created_at DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_letter(r) for r in rows]


def letters_by_sender(sender: str) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM letters WHERE sender = ? ORDER BY created_at DESC",
            (sender,),
        ).fetchall()
    return [_row_to_letter(r) for r in rows]


def update_letter_status(letter_id: str, status: str) -> None:
    if status not in _VALID_LETTER_STATUS:
        raise ValueError(f"status must be one of {_VALID_LETTER_STATUS}, got {status!r}")
    with _connect() as conn:
        conn.execute(
            "UPDATE letters SET status = ?, updated_at = ? WHERE letter_id = ?",
            (status, datetime.now(timezone.utc).isoformat(), letter_id),
        )


def record_letter_decision(
    letter_id: str, verdict: str, *, rationale: str | None = None,
) -> None:
    if verdict not in _VALID_LETTER_VERDICT:
        raise ValueError(
            f"letter verdict must be one of {_VALID_LETTER_VERDICT}, got {verdict!r}"
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO letter_decisions (letter_id, verdict, rationale, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(letter_id) DO UPDATE SET
                   verdict=excluded.verdict,
                   rationale=excluded.rationale,
                   created_at=excluded.created_at""",
            (letter_id, verdict, rationale, now_iso),
        )
    # Mirror the verdict onto the letter row so a single query gives both.
    update_letter_status(letter_id, verdict)


def is_drive_file_seen(drive_file_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM letters WHERE drive_file_id = ? LIMIT 1",
            (drive_file_id,),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Briefe-Triage: pending dispatches
# ---------------------------------------------------------------------------

@dataclass
class PendingDispatch:
    id: int
    letter_id: str
    channel: str
    recipient: str
    subject: str
    body: str
    send_at: datetime
    status: str
    sent_at: datetime | None
    error: str | None
    created_at: datetime


def _row_to_dispatch(row) -> PendingDispatch:
    return PendingDispatch(
        id=row["id"],
        letter_id=row["letter_id"],
        channel=row["channel"],
        recipient=row["recipient"],
        subject=row["subject"],
        body=row["body"],
        send_at=_dt_or_none(row["send_at"]) or datetime.now(timezone.utc),
        status=row["status"] or "DRAFT",
        sent_at=_dt_or_none(row["sent_at"]),
        error=row["error"],
        created_at=_dt_or_none(row["created_at"]) or datetime.now(timezone.utc),
    )


def record_dispatch_draft(
    *,
    letter_id: str,
    channel: str,
    recipient: str,
    subject: str,
    body: str,
    send_at: datetime,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO pending_dispatches
               (letter_id, channel, recipient, subject, body, send_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?)""",
            (
                letter_id, channel, recipient, subject, body,
                _serialise_dt(send_at),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def pending_dispatches(status: str = "DRAFT") -> list[PendingDispatch]:
    if status not in _VALID_DISPATCH_STATUS:
        raise ValueError(f"status must be one of {_VALID_DISPATCH_STATUS}")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_dispatches WHERE status = ? ORDER BY send_at ASC",
            (status,),
        ).fetchall()
    return [_row_to_dispatch(r) for r in rows]


def get_dispatch(dispatch_id: int) -> PendingDispatch | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_dispatches WHERE id = ?", (dispatch_id,),
        ).fetchone()
    return _row_to_dispatch(row) if row else None


def mark_dispatch_sent(dispatch_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_dispatches SET status='SENT', sent_at=?, error=NULL "
            "WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), dispatch_id),
        )


def mark_dispatch_failed(dispatch_id: int, error: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_dispatches SET error=? WHERE id = ?",
            (error, dispatch_id),
        )


def mark_dispatch_cancelled(dispatch_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_dispatches SET status='CANCELLED' WHERE id = ?",
            (dispatch_id,),
        )
