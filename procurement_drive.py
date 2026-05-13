"""Google Drive integration for the Briefe-Triage feature.

We use the Drive v3 REST API via the official google-api-python-client.
Configuration is entirely environment-driven (no secrets in the repo or DB):

    PROCUREMENT_DRIVE_CREDENTIALS=/path/to/oauth_client.json
    PROCUREMENT_DRIVE_FOLDER_ID=<google drive folder id>
    PROCUREMENT_DRIVE_TOKEN_CACHE=/path/to/token_cache.json  # auto-created

OAuth flow: first run shows a clickable URL; after the user pastes the auth
code back, the token is cached so subsequent runs are fully unattended.

If any env var is missing or the Google libraries are not installed,
``DriveClient`` becomes a no-op (``is_configured()`` returns False) and the
dashboard falls back to the manual file uploader. This keeps the test path
network-free.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("procurement.drive")


# ---------------------------------------------------------------------------
# Optional Google deps - imported lazily so the dashboard still works without
# them installed.
# ---------------------------------------------------------------------------

def _import_google():
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore
        return {
            "Request": Request,
            "Credentials": Credentials,
            "InstalledAppFlow": InstalledAppFlow,
            "build": build,
            "MediaIoBaseDownload": MediaIoBaseDownload,
        }
    except ImportError:
        return None


@dataclass
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    modified_time: str


class DriveClient:
    """Thin wrapper around the Drive v3 REST API.

    Scope is read-only - we only list and download PDFs. Reads / writes outside
    that scope are intentionally not exposed.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self) -> None:
        self.credentials_path = os.getenv("PROCUREMENT_DRIVE_CREDENTIALS")
        self.folder_id = os.getenv("PROCUREMENT_DRIVE_FOLDER_ID")
        self.token_path = os.getenv(
            "PROCUREMENT_DRIVE_TOKEN_CACHE",
            os.path.expanduser("~/.procurement/drive_token.json"),
        )
        self.cache_dir = Path(os.path.expanduser("~/.procurement/letters"))
        self._service = None

    def is_configured(self) -> bool:
        """True iff env vars are set, the credentials file actually exists
        on disk, AND the google libs are installed. Routes through
        :meth:`reason_unavailable` so the two never disagree.
        """
        return self.reason_unavailable() is None

    def reason_unavailable(self) -> str | None:
        if not self.credentials_path:
            return "PROCUREMENT_DRIVE_CREDENTIALS env var not set"
        if not Path(self.credentials_path).exists():
            return f"credentials file not found at {self.credentials_path}"
        if not self.folder_id:
            return "PROCUREMENT_DRIVE_FOLDER_ID env var not set"
        if _import_google() is None:
            return (
                "google-api-python-client + google-auth-oauthlib not installed "
                "(see requirements.txt)"
            )
        return None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _load_credentials(self):
        google = _import_google()
        if google is None:
            raise RuntimeError("Google libraries not installed")
        Credentials = google["Credentials"]
        Request = google["Request"]
        InstalledAppFlow = google["InstalledAppFlow"]

        token_path = Path(self.token_path)
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path), self.SCOPES
            )
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
            return creds

        flow = InstalledAppFlow.from_client_secrets_file(
            self.credentials_path, self.SCOPES
        )
        # Console flow keeps things working over SSH / headless. The dashboard
        # surfaces the auth URL via the exception's message if necessary.
        creds = flow.run_local_server(port=0, open_browser=False)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        return creds

    def _get_service(self):
        if self._service is None:
            google = _import_google()
            self._service = google["build"](
                "drive", "v3",
                credentials=self._load_credentials(),
                cache_discovery=False,
            )
        return self._service

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def list_pdfs(self, *, page_size: int = 50) -> list[DriveFile]:
        if not self.is_configured():
            return []
        service = self._get_service()
        q = (
            f"'{self.folder_id}' in parents "
            "and mimeType='application/pdf' "
            "and trashed=false"
        )
        result = service.files().list(
            q=q,
            pageSize=page_size,
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc",
        ).execute()
        return [
            DriveFile(
                file_id=f["id"],
                name=f["name"],
                mime_type=f.get("mimeType", "application/pdf"),
                modified_time=f.get("modifiedTime", ""),
            )
            for f in result.get("files", [])
        ]

    def download(self, file: DriveFile) -> Path:
        """Idempotent: returns the local cache path; only downloads if missing."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / f"{file.file_id}.pdf"
        if target.exists() and target.stat().st_size > 0:
            return target
        service = self._get_service()
        google = _import_google()
        MediaIoBaseDownload = google["MediaIoBaseDownload"]

        request = service.files().get_media(fileId=file.file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        target.write_bytes(buffer.getvalue())
        return target


def fetch_new_pdfs(
    client: DriveClient | None = None,
    *,
    is_seen_fn=None,
) -> list[tuple[DriveFile, Path]]:
    """High-level helper: list folder, skip already-seen file IDs, download.

    ``is_seen_fn`` is injected so this stays decoupled from
    ``procurement_store``; callers pass ``procurement_store.is_drive_file_seen``.
    """
    client = client or DriveClient()
    if not client.is_configured():
        return []
    out: list[tuple[DriveFile, Path]] = []
    for drive_file in client.list_pdfs():
        if is_seen_fn is not None and is_seen_fn(drive_file.file_id):
            continue
        try:
            local = client.download(drive_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drive download failed for %s: %s", drive_file.file_id, exc)
            continue
        out.append((drive_file, local))
    return out
