"""Live data source adapters for the Procurement Agent.

This module abstracts away the heterogeneous European auction / tender feeds
listed in handbook section 8.1 and converts them to the shared
``procurement_data.Opportunity`` schema (handbook section 8.3).

Adapters currently implemented (all read-only):
  * ``ZollAuktionAdapter``   - native JSON API at zoll.api.bund.dev
  * ``TedTendersAdapter``    - EU Tenders Electronic Daily, public search API
  * ``MockAdapter``          - the curated demo inventory bundled with the
                              repository (no network).

Every adapter has a uniform interface::

    adapter.fetch(limit: int = 50, timeout: float = 6.0) -> list[Opportunity]

and is *defensive*: any network / parsing failure is caught and the adapter
returns an empty list together with ``adapter.last_error``. Callers can
therefore aggregate adapters with ``aggregate(...)`` without worrying about
partial outages bringing the dashboard down.

The Zoll-Auktion endpoint, document layouts and CPV codes referenced here are
those documented in the strategic handbook §2.2.1 and §8.

Note: ``httpx`` is optional. If it is not installed, the live adapters become
no-ops and ``aggregate()`` quietly degrades to mock-only mode. This keeps the
zero-dependency demo path working out of the box.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from procurement_data import (
    Financials,
    Location,
    Opportunity,
    RiskFactors,
    all_opportunities,
    enrich,
)

try:  # httpx is optional - keep the demo path zero-dependency
    import httpx  # type: ignore
    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when httpx absent
    httpx = None  # type: ignore
    HTTPX_AVAILABLE = False

logger = logging.getLogger("procurement.sources")


# ---------------------------------------------------------------------------
# Cheap geocoder for German ZIP codes (centroid coordinates of the first two
# digits = "Postleitzahlenregion"). Keeps the live adapter fully offline-
# compatible. Replace with Nominatim/Photon for production use.
# ---------------------------------------------------------------------------

_PLZ_REGION_CENTROIDS: dict[str, tuple[float, float]] = {
    "01": (51.0504, 13.7373),  # Dresden
    "02": (51.1789, 14.4346),  # Bautzen
    "04": (51.3397, 12.3731),  # Leipzig
    "06": (51.4825, 11.9698),  # Halle
    "07": (50.7274, 11.5810),  # Gera
    "08": (50.7167, 12.4933),  # Zwickau
    "09": (50.8278, 12.9214),  # Chemnitz
    "10": (52.5200, 13.4050),  # Berlin
    "12": (52.4675, 13.5180),  # Berlin SO
    "14": (52.4006, 13.0590),  # Potsdam
    "17": (53.4324, 13.0760),  # Neubrandenburg
    "18": (54.0924, 12.0991),  # Rostock
    "19": (53.6355, 11.4011),  # Schwerin
    "20": (53.5511, 9.9937),   # Hamburg
    "22": (53.6500, 10.0500),  # Hamburg-Nord
    "24": (54.3233, 10.1228),  # Kiel
    "26": (53.1435, 8.2146),   # Oldenburg
    "28": (53.0793, 8.8017),   # Bremen
    "30": (52.3759, 9.7320),   # Hannover
    "32": (52.0302, 8.5325),   # Bielefeld
    "34": (51.3127, 9.4797),   # Kassel
    "36": (50.5559, 9.6808),   # Fulda
    "38": (52.2625, 10.5211),  # Braunschweig
    "40": (51.2277, 6.7735),   # Düsseldorf
    "44": (51.5135, 7.4653),   # Dortmund
    "45": (51.4556, 7.0116),   # Essen
    "46": (51.5078, 6.5645),   # Oberhausen
    "48": (51.9607, 7.6261),   # Münster
    "50": (50.9375, 6.9603),   # Köln
    "53": (50.7374, 7.0982),   # Bonn
    "55": (49.9929, 8.2473),   # Mainz
    "60": (50.1109, 8.6821),   # Frankfurt
    "63": (50.0993, 8.7616),   # Offenbach
    "65": (50.0826, 8.2400),   # Wiesbaden
    "67": (49.4401, 7.7491),   # Kaiserslautern
    "70": (48.7758, 9.1829),   # Stuttgart
    "72": (48.5216, 9.0576),   # Tübingen
    "74": (49.0735, 9.1486),   # Heilbronn
    "76": (49.0069, 8.4037),   # Karlsruhe
    "78": (47.6919, 9.1869),   # Konstanz
    "80": (48.1351, 11.5820),  # München
    "85": (48.5667, 11.4333),  # Ingolstadt
    "86": (48.3705, 10.8978),  # Augsburg
    "88": (47.6500, 9.4767),   # Friedrichshafen
    "90": (49.4521, 11.0767),  # Nürnberg
    "94": (48.8775, 12.5764),  # Straubing
    "97": (49.7913, 9.9534),   # Würzburg
    "99": (50.9787, 11.0328),  # Erfurt
}


def _zip_to_latlon(zip_code: str, country: str = "DE") -> tuple[float, float]:
    """Cheap PLZ → lat/lon lookup. Returns (0, 0) if unknown."""
    if country != "DE" or not zip_code:
        return (0.0, 0.0)
    return _PLZ_REGION_CENTROIDS.get(zip_code[:2], (51.1657, 10.4515))  # DE centroid


# ---------------------------------------------------------------------------
# Adapter base class
# ---------------------------------------------------------------------------

@dataclass
class Adapter:
    name: str
    platform: str
    last_error: str | None = field(default=None)
    last_fetched_count: int = 0

    def fetch(self, limit: int = 50, timeout: float = 6.0) -> list[Opportunity]:
        """Override in subclasses. Must NEVER raise — set ``last_error`` instead."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Zoll-Auktion (zoll.api.bund.dev)
# ---------------------------------------------------------------------------

@dataclass
class ZollAuktionAdapter(Adapter):
    base_url: str = "https://zoll.api.bund.dev"
    name: str = "Zoll-Auktion (Live)"
    platform: str = "ZOLL"
    category_filter: list[str] | None = None  # e.g. ["Feuerwehr", "Wasserbau"]

    def fetch(self, limit: int = 50, timeout: float = 6.0) -> list[Opportunity]:
        self.last_error = None
        self.last_fetched_count = 0
        if not HTTPX_AVAILABLE:
            self.last_error = "httpx not installed"
            return []
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(f"{self.base_url}/produkte")
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001 - we want to swallow everything
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Zoll-API fetch failed: %s", self.last_error)
            return []

        items = payload if isinstance(payload, list) else payload.get("data", [])
        out: list[Opportunity] = []
        for raw in items[: limit * 3]:  # over-fetch then filter
            opp = self._normalize(raw)
            if not opp:
                continue
            if self.category_filter and not any(
                cat.lower() in opp.title_normalized.lower()
                or cat.lower() in opp.description.lower()
                for cat in self.category_filter
            ):
                continue
            out.append(enrich(opp))
            if len(out) >= limit:
                break
        self.last_fetched_count = len(out)
        return out

    @staticmethod
    def _parse_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                # accept both 'Z' suffix and offset
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _normalize(self, raw: dict) -> Opportunity | None:
        """Map a raw Zoll-API product to our normalized schema.

        The Zoll OpenAPI document is moderately stable but field names have
        changed before. We look up keys in order of likelihood and bail out
        if none are present, returning ``None`` for the caller to skip.
        """
        try:
            asset_id = str(raw.get("id") or raw.get("artikelnummer")
                           or raw.get("auktionId") or raw.get("nummer") or "")
            if not asset_id:
                return None
            title = (raw.get("bezeichnung") or raw.get("titel")
                     or raw.get("name") or "").strip()
            description = (raw.get("beschreibung") or raw.get("info") or "").strip()
            current_bid = float(raw.get("aktuellesGebot") or raw.get("startpreis")
                                or raw.get("preis") or 0.0)
            zip_code = str(raw.get("plz") or raw.get("standortPlz") or "")
            city = (raw.get("ort") or raw.get("standortOrt") or "")
            country = raw.get("land") or "DE"
            lat, lon = _zip_to_latlon(zip_code, country)
            auction_end = self._parse_dt(raw.get("auktionsende") or raw.get("ende"))
            category = (raw.get("kategorie") or raw.get("category") or "")\
                .upper().replace(" ", "_")[:40] or "MISC"
            url = (raw.get("url")
                   or f"https://www.zoll-auktion.de/auktion/details.php?ID={asset_id}")

            return Opportunity(
                asset_id=f"ZOLL-LIVE-{asset_id}",
                source_platform="ZOLL",
                listing_url=url,
                type="POSITIVE_ASSET",
                category=category or "MISC",
                title_normalized=title or f"Zoll-Lot {asset_id}",
                description=description,
                location=Location(country, zip_code, city, lat, lon),
                financials=Financials(
                    current_bid=current_bid,
                    bid_type="ENGLISH",
                    estimated_market_value=current_bid * 1.5,  # heuristic
                ),
                risk_factors=RiskFactors(),
                brands=[],
                operating_hours=None,
                year_built=None,
                found_at=datetime.now(timezone.utc),
                auction_end=auction_end,
            )
        except (ValueError, TypeError) as exc:
            logger.debug("Zoll record skipped (%s): %s", exc, raw.get("id"))
            return None


# ---------------------------------------------------------------------------
# TED (EU Tenders Electronic Daily) - public search API
# ---------------------------------------------------------------------------

@dataclass
class TedTendersAdapter(Adapter):
    base_url: str = "https://ted.europa.eu/api/v3.0/notices/search"
    name: str = "TED EU Tenders (Live)"
    platform: str = "TED"
    cpv_codes: tuple[str, ...] = (
        "45110000",  # demolition
        "90520000",  # hazardous waste services
        "60651400",  # anti-pollution vessels
        "90722200",  # industrial decontamination
    )

    def fetch(self, limit: int = 50, timeout: float = 6.0) -> list[Opportunity]:
        self.last_error = None
        self.last_fetched_count = 0
        if not HTTPX_AVAILABLE:
            self.last_error = "httpx not installed"
            return []
        query = " OR ".join(f"cpv-classification=*{c}*" for c in self.cpv_codes)
        body = {
            "query": query,
            "limit": limit,
            "fields": [
                "publication-number", "title-text", "buyer-name",
                "buyer-country", "deadline-receipt-tender-date",
                "estimated-total-value-amount", "links",
            ],
        }
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.post(self.base_url, json=body)
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("TED fetch failed: %s", self.last_error)
            return []

        notices = payload.get("notices") if isinstance(payload, dict) else payload
        if not isinstance(notices, list):
            return []
        out: list[Opportunity] = []
        for raw in notices[:limit]:
            opp = self._normalize(raw)
            if opp:
                out.append(enrich(opp))
        self.last_fetched_count = len(out)
        return out

    @staticmethod
    def _first(obj, *keys):
        for k in keys:
            v = obj.get(k) if isinstance(obj, dict) else None
            if v not in (None, "", []):
                return v
        return None

    def _normalize(self, raw: dict) -> Opportunity | None:
        try:
            pub = self._first(raw, "publication-number", "publicationNumber")
            if not pub:
                return None
            title = self._first(raw, "title-text", "title") or f"TED notice {pub}"
            if isinstance(title, dict):
                title = next(iter(title.values()), "")
            if isinstance(title, list) and title:
                title = title[0]
            country = self._first(raw, "buyer-country", "country") or "EU"
            deadline_raw = self._first(
                raw, "deadline-receipt-tender-date", "deadline",
            )
            value = self._first(raw, "estimated-total-value-amount") or 0.0
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = 0.0
            url = (self._first(raw, "links") or {}).get("html") if isinstance(
                self._first(raw, "links"), dict
            ) else (f"https://ted.europa.eu/udl?uri=TED:NOTICE:{pub}")

            return Opportunity(
                asset_id=f"TED-{pub}",
                source_platform="TED",
                listing_url=url or f"https://ted.europa.eu/notice/-/detail/{pub}",
                type="NEGATIVE_ASSET",  # all CPVs above are paid-disposal tenders
                category="WRECK_REMOVAL",
                title_normalized=str(title)[:200],
                description=str(title),
                location=Location(country, "", "", 50.0, 10.0),
                financials=Financials(
                    current_bid=value,
                    bid_type="TENDER",
                    estimated_market_value=0.0,
                    remediation_cost_estimate=value * 0.75 if value else 0.0,
                ),
                risk_factors=RiskFactors(),
                brands=[],
                found_at=datetime.now(timezone.utc),
                auction_end=ZollAuktionAdapter._parse_dt(deadline_raw),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("TED record skipped: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Mock adapter (zero-dependency, always succeeds)
# ---------------------------------------------------------------------------

@dataclass
class MockAdapter(Adapter):
    name: str = "Curated mock inventory"
    platform: str = "MOCK"

    def fetch(self, limit: int = 50, timeout: float = 6.0) -> list[Opportunity]:
        self.last_error = None
        opps = all_opportunities()
        self.last_fetched_count = len(opps)
        return opps[:limit]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

@dataclass
class FetchReport:
    """Per-source diagnostics for the dashboard status bar."""
    adapter_name: str
    platform: str
    count: int
    error: str | None


def aggregate(
    adapters: list[Adapter],
    limit_per_source: int = 50,
    timeout: float = 6.0,
) -> tuple[list[Opportunity], list[FetchReport]]:
    """Run all adapters, merge results, deduplicate by ``asset_id``."""
    merged: dict[str, Opportunity] = {}
    reports: list[FetchReport] = []
    for adapter in adapters:
        items = adapter.fetch(limit=limit_per_source, timeout=timeout)
        for opp in items:
            merged.setdefault(opp.asset_id, opp)
        reports.append(FetchReport(
            adapter_name=adapter.name,
            platform=adapter.platform,
            count=adapter.last_fetched_count,
            error=adapter.last_error,
        ))
    return list(merged.values()), reports


def default_adapters() -> list[Adapter]:
    """Adapters used when the dashboard is launched without a custom config.

    Live adapters can be disabled by setting ``PROCUREMENT_OFFLINE=1`` in the
    environment - useful in CI or behind restrictive corporate proxies.
    """
    offline = os.getenv("PROCUREMENT_OFFLINE", "").lower() in ("1", "true", "yes")
    adapters: list[Adapter] = [MockAdapter()]
    if not offline:
        adapters.append(ZollAuktionAdapter(
            category_filter=["Feuerwehr", "Wasserbau", "Pumpe", "Aggregat"],
        ))
        adapters.append(TedTendersAdapter())
    return adapters
