"""Tests for the Drive client's ``is_configured`` / ``reason_unavailable``
contract.

We only test the gating logic — not the actual Drive API — so the tests run
fully offline.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import procurement_drive


@pytest.fixture
def fresh_client(monkeypatch):
    """Wipe all PROCUREMENT_DRIVE_* env vars, then reload the module so the
    class picks up a clean state for each test.
    """
    for name in (
        "PROCUREMENT_DRIVE_CREDENTIALS",
        "PROCUREMENT_DRIVE_FOLDER_ID",
        "PROCUREMENT_DRIVE_TOKEN_CACHE",
    ):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(procurement_drive)
    return procurement_drive


class TestIsConfigured:
    def test_no_env_vars_is_unconfigured(self, fresh_client):
        client = fresh_client.DriveClient()
        assert client.is_configured() is False
        assert "PROCUREMENT_DRIVE_CREDENTIALS" in client.reason_unavailable()

    def test_credentials_file_missing(self, fresh_client, tmp_path, monkeypatch):
        # env var set but the file does not exist on disk
        bogus = tmp_path / "nonexistent.json"
        monkeypatch.setenv("PROCUREMENT_DRIVE_CREDENTIALS", str(bogus))
        monkeypatch.setenv("PROCUREMENT_DRIVE_FOLDER_ID", "abc123")
        importlib.reload(fresh_client)
        client = fresh_client.DriveClient()
        assert client.is_configured() is False
        reason = client.reason_unavailable()
        assert "not found" in reason
        assert str(bogus) in reason

    def test_folder_id_missing(self, fresh_client, tmp_path, monkeypatch):
        creds = tmp_path / "credentials.json"
        creds.write_text("{}")  # content doesn't matter for this gate
        monkeypatch.setenv("PROCUREMENT_DRIVE_CREDENTIALS", str(creds))
        importlib.reload(fresh_client)
        client = fresh_client.DriveClient()
        assert client.is_configured() is False
        assert "PROCUREMENT_DRIVE_FOLDER_ID" in client.reason_unavailable()

    def test_fetch_new_pdfs_short_circuits_when_unconfigured(self, fresh_client):
        assert fresh_client.fetch_new_pdfs() == []
