"""Thin wrapper around ``pdftotext`` (poppler-utils) for the Briefe-Triage
feature.

We deliberately shell out to the binary instead of relying on a Python PDF
library: the dashboard already needs poppler-utils for the PDF *display* tool
the user uploaded earlier, and the binary handles a much wider range of
encodings (incl. scanned-with-OCR-layer documents) than pure-Python parsers.

Public API:
  * ``is_available() -> bool`` - True iff the ``pdftotext`` binary is on PATH.
  * ``extract_text(path) -> str`` - returns plain text. Raises
    ``PdfToolMissing`` if ``pdftotext`` is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfToolMissing(RuntimeError):
    """Raised when ``pdftotext`` is not on PATH."""


def is_available() -> bool:
    return shutil.which("pdftotext") is not None


def extract_text(path: str | Path, *, layout: bool = True, timeout: float = 20.0) -> str:
    """Run ``pdftotext`` and return the extracted text.

    ``layout=True`` preserves the visual column layout, which matters for
    invoices where amounts and dates are right-aligned in their own columns.
    """
    if not is_available():
        raise PdfToolMissing(
            "pdftotext is not installed. On Debian/Ubuntu: "
            "`apt-get install poppler-utils`."
        )
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    args = ["pdftotext"]
    if layout:
        args.append("-layout")
    args.extend([str(pdf_path), "-"])  # "-" -> stdout

    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pdftotext timed out after {timeout} s") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"pdftotext exited with {exc.returncode}: "
            f"{exc.stderr.decode('utf-8', 'replace')[:200]}"
        ) from exc

    return proc.stdout.decode("utf-8", errors="replace")
