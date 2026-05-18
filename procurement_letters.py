"""Letter triage: classify scanned/uploaded letters, extract the key fields,
and draft a German Widerspruch (objection) email if the operator decides to
contest the claim.

Public API:
  * ``Letter``                       - normalised letter record (mirrors the
                                       ``Opportunity`` dataclass shape).
  * ``classify(text) -> LetterType`` - keyword/regex letter-type classifier.
  * ``extract_fields(text, filename) -> dict`` - pull sender, amount, deadline,
                                       short-code, issue date out of OCR'd text.
  * ``enrich(letter) -> Letter``     - run extraction + classification, ready
                                       for persistence.
  * ``widerspruch_email(letter, operator_name) -> (subject, body)``
                                     - render a German objection template.
  * ``dispatch_send_at(letter, lead_days=4)``
                                     - planned send time for an auto-drafted
                                       Widerspruch (deadline - lead_days).

The classifier and extractors are intentionally regex-based, not ML-based:
they need to be auditable, deterministic, and easy to extend per-sender by
hand. For wildcards beyond the regex set, fall back to the chat agent.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

LetterType = Literal[
    "WIDERSPRUCH_FRIST",
    "MAHNUNG",
    "INVOICE",
    "VERTRAG",
    "SONSTIGES",
]

LetterStatus = Literal["NEW", "KEPT", "DISPUTED", "LATER", "IGNORED"]


@dataclass
class Letter:
    letter_id: str
    source: str                          # "DRIVE" | "UPLOAD"
    filename: str | None = None
    drive_file_id: str | None = None
    short_code: str | None = None
    sender: str | None = None
    sender_email: str | None = None
    letter_type: LetterType = "SONSTIGES"
    amount_eur: float | None = None
    issue_date: date | None = None
    deadline_date: date | None = None
    raw_text: str = ""
    status: LetterStatus = "NEW"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Order matters: earlier matches win over later ones.
_TYPE_PATTERNS: list[tuple[LetterType, tuple[str, ...]]] = [
    ("WIDERSPRUCH_FRIST", (
        "widerspruchsfrist", "klagefrist", "einspruchsfrist",
    )),
    ("MAHNUNG", (
        "mahnung", "letzte mahnung", "zahlungserinnerung",
        "zahlungsfrist", "saeumniszuschlag", "säumniszuschlag",
    )),
    ("INVOICE", (
        "rechnung", "rechnungs-nr", "rechnungsnummer",
        "rechnungsbetrag", "rechnungsdatum",
    )),
    ("VERTRAG", (
        "kuendigungsfrist", "kündigungsfrist", "vertragsbedingungen",
        "vereinbarung", "vertrag",
    )),
]


def classify(text: str) -> LetterType:
    lo = text.lower()
    for label, needles in _TYPE_PATTERNS:
        for n in needles:
            if n in lo:
                return label
    return "SONSTIGES"


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

_RE_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
_RE_AMOUNT = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,3}(?:[. ]\d{3})*(?:,\d{2}))"
    r"\s*(?:€|EUR\b)",
    re.IGNORECASE,
)
_RE_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_RE_SHORTCODE_LABELS = re.compile(
    r"(?:rechnung(?:s)?[-\s]?nr\.?|rechnungsnummer|aktenzeichen|az\.?|"
    r"vorgangs?nummer|kunden[-\s]?nr\.?|forderungs[-\s]?nr\.?)"
    r"\s*[:.]?\s*"
    r"([A-Z0-9][A-Z0-9\-/_.]{2,30})",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT_WORDS = (
    "faellig", "fällig", "bis", "frist", "widerspruch", "spaetestens",
    "spätestens", "zahlung", "einreichen",
)


def _parse_german_date(day: str, month: str, year: str) -> date | None:
    try:
        d = int(day)
        m = int(month)
        y = int(year)
        if y < 100:
            y += 2000 if y < 70 else 1900
        return date(y, m, d)
    except ValueError:
        return None


def _extract_amount(text: str) -> float | None:
    matches = _RE_AMOUNT.findall(text)
    if not matches:
        return None
    # Pick the largest amount in the document (heuristic: the headline amount
    # of an invoice/Mahnung is usually the biggest figure).
    best: float | None = None
    for raw in matches:
        normalised = raw.replace(".", "").replace(" ", "").replace(",", ".")
        try:
            value = float(normalised)
        except ValueError:
            continue
        if best is None or value > best:
            best = value
    return best


def _extract_dates(text: str) -> list[tuple[int, date]]:
    """Return [(offset_in_text, parsed_date)] sorted by offset."""
    out: list[tuple[int, date]] = []
    for m in _RE_DATE.finditer(text):
        parsed = _parse_german_date(m.group(1), m.group(2), m.group(3))
        if parsed is not None:
            out.append((m.start(), parsed))
    return out


def _extract_deadline(text: str, dates: list[tuple[int, date]]) -> date | None:
    """Heuristic: the latest date that occurs within 60 chars of a deadline
    context word wins. Falls back to the latest date in the document if no
    contextual match is found.
    """
    lo = text.lower()
    contextual: list[date] = []
    for offset, parsed in dates:
        window_start = max(0, offset - 60)
        window = lo[window_start:offset]
        if any(w in window for w in _DEADLINE_CONTEXT_WORDS):
            contextual.append(parsed)
    if contextual:
        return max(contextual)
    if dates:
        # Latest absolute date as fallback - issue date is usually first, the
        # deadline tends to be later in the document.
        return max(d for _, d in dates)
    return None


def _extract_issue_date(text: str, dates: list[tuple[int, date]]) -> date | None:
    """Heuristic: the earliest date in the first ~600 chars."""
    if not dates:
        return None
    head_dates = [d for offset, d in dates if offset < 600]
    return min(head_dates) if head_dates else min(d for _, d in dates)


def _extract_sender(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:12]:
        if line.startswith(("Sehr geehrte", "Liebe", "Hallo")):
            continue
        words = [w for w in line.split() if w]
        # at least two capitalised words, reasonable length
        if len(words) >= 2 and sum(
            1 for w in words if w[:1].isupper()
        ) >= 2 and 5 <= len(line) <= 90:
            return line
    return None


def _extract_short_code(text: str) -> str | None:
    m = _RE_SHORTCODE_LABELS.search(text)
    if m:
        return m.group(1).strip(" ,.;:")
    return None


def _generated_short_code(seed: str) -> str:
    """Deterministic 6-hex suffix so the same letter always gets the same
    short code even if the user re-uploads it."""
    digest = hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:6].upper()
    year = date.today().year
    return f"LET-{year}-{digest}"


def extract_fields(text: str, *, filename: str | None = None) -> dict:
    dates = _extract_dates(text)
    sender = _extract_sender(text)
    email_match = _RE_EMAIL.search(text)
    short_code = _extract_short_code(text)
    if short_code is None:
        seed = filename or text[:200]
        short_code = _generated_short_code(seed)
    return {
        "sender": sender,
        "sender_email": email_match.group(0) if email_match else None,
        "short_code": short_code,
        "amount_eur": _extract_amount(text),
        "issue_date": _extract_issue_date(text, dates),
        "deadline_date": _extract_deadline(text, dates),
    }


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich(letter: Letter) -> Letter:
    """Populate classification + extracted fields in-place. Returns the same
    instance for chaining."""
    fields = extract_fields(letter.raw_text, filename=letter.filename)
    letter.sender = fields["sender"]
    letter.sender_email = fields["sender_email"]
    letter.short_code = fields["short_code"]
    letter.amount_eur = fields["amount_eur"]
    letter.issue_date = fields["issue_date"]
    letter.deadline_date = fields["deadline_date"]
    letter.letter_type = classify(letter.raw_text)
    letter.updated_at = datetime.now(timezone.utc)
    return letter


def from_text(
    text: str,
    *,
    source: str,
    filename: str | None = None,
    drive_file_id: str | None = None,
) -> Letter:
    letter = Letter(
        letter_id=str(uuid.uuid4()),
        source=source,
        filename=filename,
        drive_file_id=drive_file_id,
        raw_text=text,
    )
    return enrich(letter)


# ---------------------------------------------------------------------------
# Widerspruch email template
# ---------------------------------------------------------------------------

_AMOUNT_FORMAT = "{:,.2f}"  # then swap . and , for German conventions


def format_amount_de(amount: float | None) -> str:
    if amount is None:
        return "(Betrag unbekannt)"
    raw = _AMOUNT_FORMAT.format(amount)
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def format_date_de(value: date | None) -> str:
    if value is None:
        return "(Datum unbekannt)"
    return value.strftime("%d.%m.%Y")


def widerspruch_email(
    letter: Letter, operator_name: str = "Der Eigentuemer"
) -> tuple[str, str]:
    """Return (subject, body) for the German objection email.

    The wording is deliberately neutral: it does not concede payment, does not
    admit to receipt, and explicitly asks for written confirmation.
    """
    short_code = letter.short_code or "(ohne Aktenzeichen)"
    issue = format_date_de(letter.issue_date)
    amount = format_amount_de(letter.amount_eur)

    subject = f"Widerspruch zu {short_code} vom {issue}"

    body = (
        "Sehr geehrte Damen und Herren,\n"
        "\n"
        f"hiermit lege ich gegen Ihre Forderung {short_code} vom {issue} "
        "fristgerecht Widerspruch ein.\n"
        "\n"
        f"Die Forderung ueber {amount} EUR wird in Hoehe und Grund "
        "bestritten. Bis zur Klaerung bitte ich um Aussetzung der "
        "Vollziehung sowie um schriftliche Bestaetigung des Eingangs dieses "
        "Widerspruchs.\n"
        "\n"
        "Mit freundlichen Gruessen\n"
        f"{operator_name}\n"
        "\n"
        f"(Bezug: {short_code} - Schreiben vom {issue})\n"
    )
    return subject, body


def dispatch_send_at(letter: Letter, lead_days: int = 4) -> datetime:
    """Planned send time: ``deadline - lead_days`` at 09:00 local-ish (UTC).

    If no deadline is known, default to *now + 7 days* so the draft does not
    immediately fire.
    """
    if letter.deadline_date is None:
        return datetime.now(timezone.utc) + timedelta(days=7)
    target = letter.deadline_date - timedelta(days=lead_days)
    return datetime(target.year, target.month, target.day, 9, 0, tzinfo=timezone.utc)
