"""Asana integration for the Heute-Tab.

Same defensive pattern as ``procurement_drive``: read everything we need
from env vars; if anything is missing, ``is_configured()`` returns False
and the dashboard renders a setup hint instead of crashing.

Why not the official ``asana`` Python SDK? It pulls in a heavy dependency
tree (Swagger client, urllib3, six). We only need three GET endpoints
(/users/me, /workspaces, /tasks) so a thin httpx wrapper is enough and
keeps the requirements lean.

Auth: Asana Personal Access Token in env var ``ASANA_PAT``.
Create one at: https://app.asana.com/0/my-apps -> Create new token.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("procurement.asana")

ASANA_API = "https://app.asana.com/api/1.0"
_DEFAULT_FIELDS = (
    "name",
    "due_on",
    "due_at",
    "completed",
    "completed_at",
    "permalink_url",
    "projects.name",
    "assignee_status",
)


def _import_httpx():
    try:
        import httpx  # type: ignore
        return httpx
    except ImportError:
        return None


@dataclass
class AsanaTask:
    gid: str
    name: str
    due_on: date | None
    completed: bool
    project_names: list[str] = field(default_factory=list)
    permalink_url: str | None = None
    assignee_status: str | None = None  # "today" | "upcoming" | "later" | "new"

    @property
    def overdue(self) -> bool:
        return (
            not self.completed
            and self.due_on is not None
            and self.due_on < date.today()
        )

    @property
    def due_today(self) -> bool:
        return not self.completed and self.due_on == date.today()


class AsanaClient:
    """Thin Asana API client. Reads only - no writes from the dashboard."""

    def __init__(self) -> None:
        self.token = os.getenv("ASANA_PAT") or os.getenv("ASANA_PERSONAL_ACCESS_TOKEN")
        self.workspace_gid_override = os.getenv("ASANA_WORKSPACE_GID")
        self._workspace_gid: str | None = None
        self._user_gid: str | None = None

    @staticmethod
    def is_configured() -> bool:
        if not (os.getenv("ASANA_PAT") or os.getenv("ASANA_PERSONAL_ACCESS_TOKEN")):
            return False
        return _import_httpx() is not None

    def reason_unavailable(self) -> str | None:
        if not self.token:
            return "ASANA_PAT env var not set (create at https://app.asana.com/0/my-apps)"
        if _import_httpx() is None:
            return "httpx package not installed"
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        httpx = _import_httpx()
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                ASANA_API + path, headers=self._headers(), params=params or {},
            )
            resp.raise_for_status()
            return resp.json()

    def _ensure_workspace(self) -> str:
        if self._workspace_gid:
            return self._workspace_gid
        if self.workspace_gid_override:
            self._workspace_gid = self.workspace_gid_override
            return self._workspace_gid
        data = self._get("/workspaces", params={"limit": 1})
        items = data.get("data", [])
        if not items:
            raise RuntimeError("Asana account has no workspaces")
        self._workspace_gid = items[0]["gid"]
        return self._workspace_gid

    def fetch_my_open_tasks(self, *, horizon_days: int = 14) -> list[AsanaTask]:
        """Tasks assigned to ``me`` that are not completed, with a due date
        in the past or within the next ``horizon_days`` days. Tasks without
        a due date are excluded (they would otherwise drown the list).
        """
        if not self.is_configured():
            return []
        workspace_gid = self._ensure_workspace()
        data = self._get("/tasks", params={
            "assignee": "me",
            "workspace": workspace_gid,
            "completed_since": "now",  # = only incomplete
            "opt_fields": ",".join(_DEFAULT_FIELDS),
            "limit": 100,
        })
        out: list[AsanaTask] = []
        for row in data.get("data", []):
            due_on = _parse_date(row.get("due_on"))
            if due_on is None:
                continue
            if due_on > date.today().fromordinal(
                date.today().toordinal() + horizon_days
            ):
                continue
            out.append(AsanaTask(
                gid=row["gid"],
                name=row.get("name", "(ohne Titel)"),
                due_on=due_on,
                completed=bool(row.get("completed", False)),
                project_names=[
                    p.get("name", "") for p in row.get("projects", []) if p.get("name")
                ],
                permalink_url=row.get("permalink_url"),
                assignee_status=row.get("assignee_status"),
            ))
        # Overdue first, then due-today, then by due date ascending
        out.sort(key=lambda t: (
            0 if t.overdue else (1 if t.due_today else 2),
            t.due_on or date(9999, 12, 31),
        ))
        return out


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
