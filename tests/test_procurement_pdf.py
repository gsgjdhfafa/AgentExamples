"""Tests for the pdftotext wrapper.

Generates a small PDF on the fly via reportlab so we have a known-content
source to round-trip through ``procurement_pdf.extract_text``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

procurement_pdf = pytest.importorskip("procurement_pdf")


def _make_pdf(path: Path, text: str) -> None:
    """Write a 1-page A4 PDF containing the given text."""
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(72, y, line)
        y -= 16
    c.showPage()
    c.save()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    if not procurement_pdf.is_available():
        pytest.skip("pdftotext binary not installed")
    target = tmp_path / "sample.pdf"
    _make_pdf(target, (
        "Rechnung Nr. R-2026-0042\n"
        "Betrag: 1.234,56 EUR\n"
        "Faellig bis: 30.06.2026\n"
        "Mit freundlichen Gruessen"
    ))
    return target


class TestIsAvailable:
    def test_returns_bool(self):
        result = procurement_pdf.is_available()
        assert isinstance(result, bool)


class TestExtractText:
    def test_round_trip(self, sample_pdf):
        text = procurement_pdf.extract_text(sample_pdf)
        assert "Rechnung Nr. R-2026-0042" in text
        assert "1.234,56" in text
        assert "30.06.2026" in text

    def test_missing_file(self, tmp_path):
        if not procurement_pdf.is_available():
            pytest.skip("pdftotext binary not installed")
        with pytest.raises(FileNotFoundError):
            procurement_pdf.extract_text(tmp_path / "does-not-exist.pdf")
