"""Tests for the Asana client gating logic. No network calls."""

from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest

import procurement_asana


@pytest.fixture
def fresh(monkeypatch):
    for name in (
        "ASANA_PAT",
        "ASANA_PERSONAL_ACCESS_TOKEN",
        "ASANA_WORKSPACE_GID",
    ):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(procurement_asana)
    return procurement_asana


class TestIsConfigured:
    def test_no_token_is_unconfigured(self, fresh):
        client = fresh.AsanaClient()
        assert client.is_configured() is False
        assert "ASANA_PAT" in client.reason_unavailable()

    def test_token_present_is_configured(self, fresh, monkeypatch):
        monkeypatch.setenv("ASANA_PAT", "1/123:abcdef")
        importlib.reload(fresh)
        client = fresh.AsanaClient()
        assert client.is_configured() is True
        assert client.reason_unavailable() is None

    def test_legacy_env_var_name_also_works(self, fresh, monkeypatch):
        monkeypatch.setenv("ASANA_PERSONAL_ACCESS_TOKEN", "1/123:abcdef")
        importlib.reload(fresh)
        client = fresh.AsanaClient()
        assert client.is_configured() is True

    def test_fetch_my_open_tasks_short_circuits_when_unconfigured(self, fresh):
        client = fresh.AsanaClient()
        assert client.fetch_my_open_tasks() == []


class TestAsanaTaskHelpers:
    def test_overdue_when_due_in_past(self):
        task = procurement_asana.AsanaTask(
            gid="x", name="t", due_on=date.today() - timedelta(days=2),
            completed=False,
        )
        assert task.overdue is True
        assert task.due_today is False

    def test_not_overdue_when_completed(self):
        task = procurement_asana.AsanaTask(
            gid="x", name="t", due_on=date.today() - timedelta(days=2),
            completed=True,
        )
        assert task.overdue is False

    def test_due_today(self):
        task = procurement_asana.AsanaTask(
            gid="x", name="t", due_on=date.today(), completed=False,
        )
        assert task.due_today is True
        assert task.overdue is False
