"""Tests for the Briefe-Triage classifier + extractor + Widerspruch template."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from procurement_letters import (
    Letter,
    classify,
    dispatch_send_at,
    enrich,
    extract_fields,
    from_text,
    widerspruch_email,
)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("snippet, expected", [
        ("Mahnung ueber 250 EUR", "MAHNUNG"),
        ("Letzte Mahnung - Zahlungsfrist", "MAHNUNG"),
        ("Rechnung Nr. 123, faellig am 30.06.2026", "INVOICE"),
        ("Bitte beachten Sie die Widerspruchsfrist", "WIDERSPRUCH_FRIST"),
        ("Vertrag ueber Internetanschluss, Kuendigungsfrist 3 Monate", "VERTRAG"),
        ("Postkarte aus Italien", "SONSTIGES"),
    ])
    def test_keyword_matching(self, snippet, expected):
        assert classify(snippet) == expected

    def test_mahnung_wins_over_invoice(self):
        # A Mahnung typically also includes the word "Rechnung"; ensure the
        # mahnung match wins.
        text = "Mahnung zur Rechnung Nr. R-0042"
        assert classify(text) == "MAHNUNG"


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

class TestExtractFields:
    SAMPLE = (
        "Stadtwerke Berlin GmbH\n"
        "Musterstrasse 7, 10117 Berlin\n"
        "\n"
        "Rechnung Nr. R-2026-0042\n"
        "Rechnungsdatum: 12.04.2026\n"
        "Faellig bis: 30.06.2026\n"
        "Betrag: 1.234,56 EUR\n"
        "\n"
        "Kontakt: kontakt@stadtwerke-berlin.de\n"
    )

    def test_short_code_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["short_code"] == "R-2026-0042"

    def test_amount_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["amount_eur"] == pytest.approx(1234.56)

    def test_deadline_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["deadline_date"] == date(2026, 6, 30)

    def test_issue_date_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["issue_date"] == date(2026, 4, 12)

    def test_sender_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["sender"] == "Stadtwerke Berlin GmbH"

    def test_sender_email_extracted(self):
        fields = extract_fields(self.SAMPLE)
        assert fields["sender_email"] == "kontakt@stadtwerke-berlin.de"

    def test_fallback_short_code_is_deterministic(self):
        text = "Schreiben ohne Aktenzeichen"
        a = extract_fields(text, filename="brief.pdf")
        b = extract_fields(text, filename="brief.pdf")
        assert a["short_code"] == b["short_code"]
        assert a["short_code"].startswith("LET-")

    def test_amount_picks_largest(self):
        text = "Bearbeitungsgebuehr 5,00 EUR. Rechnungsbetrag 999,99 EUR."
        fields = extract_fields(text)
        assert fields["amount_eur"] == pytest.approx(999.99)

    def test_no_amount_returns_none(self):
        fields = extract_fields("Ein Brief ohne Geldbetraege")
        assert fields["amount_eur"] is None

    def test_no_dates_returns_none(self):
        fields = extract_fields("Ein Brief ohne Datum")
        assert fields["deadline_date"] is None
        assert fields["issue_date"] is None


# ---------------------------------------------------------------------------
# Enrich + from_text
# ---------------------------------------------------------------------------

class TestEnrich:
    def test_from_text_returns_complete_letter(self):
        text = TestExtractFields.SAMPLE
        letter = from_text(text, source="UPLOAD", filename="rechnung.pdf")
        assert isinstance(letter, Letter)
        assert letter.letter_type == "INVOICE"
        assert letter.amount_eur == pytest.approx(1234.56)
        assert letter.deadline_date == date(2026, 6, 30)
        assert letter.sender == "Stadtwerke Berlin GmbH"

    def test_enrich_updates_timestamp(self):
        letter = Letter(
            letter_id="x", source="UPLOAD",
            raw_text=TestExtractFields.SAMPLE,
        )
        before = letter.updated_at
        # ensure tick
        letter.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        enrich(letter)
        assert letter.updated_at > before
        assert letter.letter_type == "INVOICE"


# ---------------------------------------------------------------------------
# Widerspruch template
# ---------------------------------------------------------------------------

class TestWiderspruchEmail:
    def test_renders_subject_and_body(self):
        letter = from_text(
            TestExtractFields.SAMPLE, source="UPLOAD", filename="rechnung.pdf",
        )
        subject, body = widerspruch_email(letter, operator_name="Max Mustermann")
        assert "R-2026-0042" in subject
        assert "12.04.2026" in subject
        assert "Widerspruch" in subject

        assert "Sehr geehrte Damen und Herren" in body
        assert "R-2026-0042" in body
        assert "1.234,56 EUR" in body
        assert "Max Mustermann" in body

    def test_handles_missing_amount_and_date(self):
        letter = Letter(
            letter_id="x", source="UPLOAD", raw_text="(empty)",
            short_code=None, amount_eur=None,
            issue_date=None, deadline_date=None,
        )
        subject, body = widerspruch_email(letter)
        assert "ohne Aktenzeichen" in subject
        assert "Betrag unbekannt" in body


# ---------------------------------------------------------------------------
# dispatch_send_at
# ---------------------------------------------------------------------------

class TestDispatchSendAt:
    def test_four_days_before_deadline(self):
        letter = Letter(
            letter_id="x", source="UPLOAD", raw_text="",
            deadline_date=date(2026, 6, 30),
        )
        send_at = dispatch_send_at(letter, lead_days=4)
        assert send_at.date() == date(2026, 6, 26)

    def test_no_deadline_falls_back_to_plus_7d(self):
        letter = Letter(letter_id="x", source="UPLOAD", raw_text="")
        send_at = dispatch_send_at(letter)
        delta = send_at - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)
