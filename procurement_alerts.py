"""Alert dispatchers - email (SMTP) and webhook (HTTPS POST).

Configured exclusively via environment variables so credentials never end up
in the repo or in the SQLite store::

    # Email (any SMTP server, e.g. Sendgrid, Postmark, M365, Gmail)
    PROCUREMENT_ALERT_SMTP_HOST=smtp.example.com
    PROCUREMENT_ALERT_SMTP_PORT=587
    PROCUREMENT_ALERT_SMTP_USER=alerts@example.com
    PROCUREMENT_ALERT_SMTP_PASSWORD=...
    PROCUREMENT_ALERT_FROM=alerts@example.com
    PROCUREMENT_ALERT_TO=operator@example.com,backup@example.com

    # Webhook (Slack incoming-webhook, Discord, Teams, custom)
    PROCUREMENT_ALERT_WEBHOOK=https://hooks.slack.com/services/...

Both dispatchers are no-ops when their env vars are unset; that keeps the
demo path safe.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import procurement_data as pdata

try:
    import httpx  # type: ignore
    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
    HTTPX_AVAILABLE = False

logger = logging.getLogger("procurement.alerts")


@dataclass
class DispatchReport:
    channel: str          # "email" | "webhook"
    target: str | None
    sent: bool
    error: str | None = None


def _format_text(opps: list[pdata.Opportunity]) -> str:
    lines = [
        f"{len(opps)} neue Procurement-Hot-Deal(s):\n",
    ]
    for o in opps:
        lines.append(
            f"• [{o.score}] {o.title_normalized}\n"
            f"   {o.source_platform} · {o.location.city}, {o.location.country}\n"
            f"   Gebot {o.financials.current_bid:.0f} EUR · "
            f"NAV {o.net_asset_value:.0f} EUR · "
            f"Bid-Limit {o.bid_ceiling:.0f} EUR\n"
            f"   {o.listing_url}\n"
        )
    return "\n".join(lines)


def _format_webhook_payload(opps: list[pdata.Opportunity]) -> dict:
    return {
        "type": "procurement.hot_deals",
        "count": len(opps),
        "opportunities": [
            {
                "asset_id": o.asset_id,
                "title": o.title_normalized,
                "score": o.score,
                "platform": o.source_platform,
                "country": o.location.country,
                "city": o.location.city,
                "current_bid_eur": o.financials.current_bid,
                "net_asset_value_eur": o.net_asset_value,
                "bid_ceiling_eur": o.bid_ceiling,
                "auction_end": o.auction_end.isoformat(),
                "url": o.listing_url,
            }
            for o in opps
        ],
    }


def send_email(opps: list[pdata.Opportunity]) -> DispatchReport:
    host = os.getenv("PROCUREMENT_ALERT_SMTP_HOST")
    if not host:
        return DispatchReport("email", None, sent=False,
                              error="SMTP host not configured")
    port = int(os.getenv("PROCUREMENT_ALERT_SMTP_PORT", "587"))
    user = os.getenv("PROCUREMENT_ALERT_SMTP_USER")
    pwd = os.getenv("PROCUREMENT_ALERT_SMTP_PASSWORD")
    sender = os.getenv("PROCUREMENT_ALERT_FROM") or user
    recipients_raw = os.getenv("PROCUREMENT_ALERT_TO", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not (sender and recipients):
        return DispatchReport("email", None, sent=False,
                              error="Sender / recipients not configured")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = (
        f"[Procurement] {len(opps)} Hot Deal(s) - höchster Score "
        f"{max(o.score for o in opps)}"
    )
    msg.set_content(_format_text(opps))

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            if user and pwd:
                s.login(user, pwd)
            s.send_message(msg)
        return DispatchReport("email", ", ".join(recipients), sent=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email dispatch failed: %s", exc)
        return DispatchReport("email", ", ".join(recipients),
                              sent=False, error=f"{type(exc).__name__}: {exc}")


def send_webhook(opps: list[pdata.Opportunity]) -> DispatchReport:
    url = os.getenv("PROCUREMENT_ALERT_WEBHOOK")
    if not url:
        return DispatchReport("webhook", None, sent=False,
                              error="Webhook URL not configured")
    if not HTTPX_AVAILABLE:
        return DispatchReport("webhook", url, sent=False,
                              error="httpx not installed")

    payload = _format_webhook_payload(opps)
    try:
        with httpx.Client(timeout=8) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        return DispatchReport("webhook", url, sent=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook dispatch failed: %s", exc)
        return DispatchReport("webhook", url, sent=False,
                              error=f"{type(exc).__name__}: {exc}")


def dispatch_alerts(opps: list[pdata.Opportunity]) -> list[DispatchReport]:
    """Send via every configured channel. Empty opps → no-op (no reports)."""
    if not opps:
        return []
    reports = [send_email(opps), send_webhook(opps)]
    return [r for r in reports if r.error != "SMTP host not configured"
            and r.error != "Webhook URL not configured"]
