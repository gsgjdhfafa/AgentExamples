"""Mock data store, scoring engine and enrichment helpers for the
Procurement Agent.

The opportunity records mirror the JSON schema from the source handbook,
section 8.3 ("Datenmodell für das Opportunity Matching").

In a production deployment this module would be backed by:
  - the Zoll-Auktion REST API  (zoll.api.bund.dev)
  - a VEBEG HTML scraper
  - the Troostwijk / TBAuctions Atlas API
  - Domaines (FR), Domeinen RZ (NL), AMW (PL) crawlers
  - LME ferrous scrap price feed
  - OSRM / Google Maps for haversine logistics distance

For the dashboard demo it ships with a curated, deterministic sample so the
scoring logic is fully exercised end-to-end without external network calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Approx LME-derived spot prices in EUR / tonne (handbook section 6.2).
# Treated as constants here; in production these would be fetched daily.
SCRAP_PRICES_EUR_PER_TONNE = {
    "STEEL_HMS_1_2": 350.0,
    "STEEL_ST37": 320.0,
    "MIXED_FERROUS": 290.0,
    "COPPER": 7800.0,
    "ALUMINIUM": 1900.0,
    "STAINLESS_304": 1200.0,
}

# Premium brands that get a positive score nudge (handbook section 8.4).
PREMIUM_BRANDS = {
    "Liebherr", "Börger", "Boerger", "Mercedes", "MAN", "Schottel",
    "Unimog", "Volvo Penta", "Caterpillar", "Wacker", "Atlas Copco",
    "Rosenbauer", "Magirus", "Ziegler",
}

# Risk vocabulary ("red flags") - handbook sections 5.2, 6.2, 9.
RED_FLAG_TERMS = {
    "Asbest", "PCB", "Altlast", "Bodenkontamination",
    "Nur zu Sammlerzwecken", "Nicht für den Einsatz zugelassen",
    "Attest abgelaufen", "Klasse abgelaufen", "Ausschlachtware",
    "Ersatzteilspender", "Zustand unbekannt",
}

# Dual-use trigger terms (Anhang I EU Dual-Use VO; handbook section 9.1).
DUAL_USE_TERMS = {
    "ABC-Schutz", "ABC Schutz", "Spürpanzer", "Funkgerät SEM",
    "Nachtsicht", "geländegängig 6x6", "Unimog U1300L Bw",
    "Schutzmaske", "Filterabdichtung",
}

# Home depot used for the logistics distance bonus.
HOME_DEPOT = ("Hamburg", "DE", 53.5511, 9.9937)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Location:
    country: str
    zip: str
    city: str
    lat: float
    lon: float
    pickup_restrictions: list[str] = field(default_factory=list)


@dataclass
class Financials:
    currency: str = "EUR"
    current_bid: float = 0.0
    bid_type: str = "ENGLISH"  # SEALED_BID | ENGLISH | FIXED_PRICE | TENDER
    estimated_market_value: float = 0.0
    scrap_material: str | None = None
    weight_kg: float | None = None
    repair_opex_estimate: float = 0.0
    remediation_cost_estimate: float = 0.0  # for negative assets


@dataclass
class RiskFactors:
    export_control: bool = False
    hazardous_materials: bool = False
    repair_needed: bool = False
    missing_parts: list[str] = field(default_factory=list)
    pre_1990_vessel: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Opportunity:
    asset_id: str
    source_platform: str        # VEBEG | ZOLL | TROOSTWIJK | DOMAINE | AMW | TED
    listing_url: str
    type: str                   # POSITIVE_ASSET | NEGATIVE_ASSET
    category: str
    title_normalized: str
    description: str
    location: Location
    financials: Financials
    risk_factors: RiskFactors
    found_at: datetime
    auction_end: datetime
    brands: list[str] = field(default_factory=list)
    operating_hours: int | None = None
    year_built: int | None = None

    # populated by enrichment pass
    scrap_value_potential: float = 0.0
    logistics_cost_estimate: float = 0.0
    net_asset_value: float = 0.0
    score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    bid_ceiling: float = 0.0


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_logistics_cost(opp: Opportunity, eur_per_km: float = 2.20) -> float:
    """Rough heavy-haul transport cost from the opportunity location to the
    home depot. 2,20 EUR/km is the typical low-loader rate cited in the
    handbook (Spezialtransport Überbreite)."""
    distance = haversine_km(
        opp.location.lat, opp.location.lon, HOME_DEPOT[2], HOME_DEPOT[3]
    )
    base = distance * eur_per_km
    # Heavy items (> 5 t) add a 30 % surcharge for permits / escort vehicles.
    if (opp.financials.weight_kg or 0) > 5000:
        base *= 1.30
    return round(base, 2)


def estimate_scrap_value(opp: Opportunity) -> float:
    """Scrap credit in EUR based on the LME-style ferrous price."""
    mat = opp.financials.scrap_material
    weight = opp.financials.weight_kg
    if not mat or not weight:
        return 0.0
    eur_per_t = SCRAP_PRICES_EUR_PER_TONNE.get(mat, 250.0)
    return round((weight / 1000.0) * eur_per_t, 2)


def detect_red_flags(opp: Opportunity) -> list[str]:
    text = " ".join([opp.title_normalized, opp.description] + opp.risk_factors.notes)
    return sorted({term for term in RED_FLAG_TERMS if term.lower() in text.lower()})


def detect_dual_use(opp: Opportunity) -> bool:
    text = " ".join([opp.title_normalized, opp.description])
    return any(term.lower() in text.lower() for term in DUAL_USE_TERMS) \
        or opp.risk_factors.export_control


def score_opportunity(opp: Opportunity) -> tuple[int, dict[str, int]]:
    """Return (score 0-100, breakdown).

    Implements the rubric from handbook section 8.4:
      + niedriges Startgebot vs. Marktwert (highest weight)
      + Markenhersteller
      + Standortnähe
      + Doku / niedrige Betriebsstunden trotz hohem Baujahr
      - red flags / Dual-Use ohne Klärung
      - Logistik > 25 % vom Schätzwert
      - Pre-1990 Schiff
    """
    breakdown: dict[str, int] = {}

    # Margin component (-30 .. +40)
    market = opp.financials.estimated_market_value
    bid = opp.financials.current_bid
    if opp.type == "POSITIVE_ASSET" and market > 0:
        margin_ratio = (market - bid) / market  # 0..1 typical
        margin_pts = int(round(max(min(margin_ratio * 60, 40), -30)))
    elif opp.type == "NEGATIVE_ASSET":
        # For paid-disposal mandates: the higher the contract value vs. our
        # estimated cost, the better the margin.
        cost = opp.financials.remediation_cost_estimate or 1
        margin_pts = int(round(max(min((bid - cost) / cost * 60, 40), -30)))
    else:
        margin_pts = 0
    breakdown["margin"] = margin_pts

    # Brand bonus (0 .. +10)
    brand_pts = 10 if any(b in PREMIUM_BRANDS for b in opp.brands) else 0
    breakdown["brand"] = brand_pts

    # Distance bonus (-10 .. +10)
    distance = haversine_km(
        opp.location.lat, opp.location.lon, HOME_DEPOT[2], HOME_DEPOT[3]
    )
    if distance < 300:
        distance_pts = 10
    elif distance < 700:
        distance_pts = 3
    elif distance < 1500:
        distance_pts = -3
    else:
        distance_pts = -10
    breakdown["proximity"] = distance_pts

    # Documentation / hours bonus (0 .. +15)
    doc_pts = 0
    if opp.operating_hours is not None and opp.operating_hours < 200:
        doc_pts += 10
    if opp.year_built and opp.year_built >= 2005:
        doc_pts += 5
    breakdown["condition"] = doc_pts

    # Logistics penalty: > 25 % of estimated value is a drag
    log_pts = 0
    if market > 0 and opp.logistics_cost_estimate / market > 0.25:
        log_pts = -15
    breakdown["logistics"] = log_pts

    # Risk penalties
    risk_pts = 0
    red_flags = detect_red_flags(opp)
    risk_pts -= 8 * len(red_flags)
    if opp.risk_factors.pre_1990_vessel:
        risk_pts -= 12
    if detect_dual_use(opp) and not opp.risk_factors.export_control:
        # Plausibly dual-use but unflagged -> hidden BAFA risk
        risk_pts -= 8
    breakdown["risk"] = risk_pts

    raw = 30 + sum(breakdown.values())  # baseline 30
    score = max(0, min(100, raw))
    return score, breakdown


def compute_bid_ceiling(opp: Opportunity, target_margin: float = 0.25) -> float:
    """Bid ceiling formula from handbook section 9.

    Positive asset:  market - logistics - repair - margin + scrap_credit
    Negative asset:  remediation - scrap_credit + margin
    """
    if opp.type == "POSITIVE_ASSET":
        ceiling = (
            opp.financials.estimated_market_value
            - opp.logistics_cost_estimate
            - opp.financials.repair_opex_estimate
            - target_margin * opp.financials.estimated_market_value
            + opp.scrap_value_potential
        )
    else:
        ceiling = (
            opp.financials.remediation_cost_estimate
            - opp.scrap_value_potential
            + target_margin * opp.financials.remediation_cost_estimate
        )
    return round(max(ceiling, 0), 2)


def enrich(opp: Opportunity) -> Opportunity:
    opp.scrap_value_potential = estimate_scrap_value(opp)
    opp.logistics_cost_estimate = estimate_logistics_cost(opp)
    opp.score, opp.score_breakdown = score_opportunity(opp)
    opp.bid_ceiling = compute_bid_ceiling(opp)
    if opp.type == "POSITIVE_ASSET":
        opp.net_asset_value = round(
            opp.financials.estimated_market_value
            - opp.financials.current_bid
            - opp.logistics_cost_estimate
            - opp.financials.repair_opex_estimate
            + opp.scrap_value_potential,
            2,
        )
    else:
        opp.net_asset_value = round(
            opp.financials.current_bid
            - opp.financials.remediation_cost_estimate
            + opp.scrap_value_potential,
            2,
        )
    return opp


# ---------------------------------------------------------------------------
# Sample inventory (mirrors realistic VEBEG / Zoll-Auktion / Troostwijk lots)
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


_SAMPLE: list[Opportunity] = [
    Opportunity(
        asset_id="VEBEG-2026-0142",
        source_platform="VEBEG",
        listing_url="https://www.vebeg.de/de/verkauf/details.htm?ID=2026-0142",
        type="POSITIVE_ASSET",
        category="MARITIME_PUMP",
        title_normalized="Drehkolbenpumpe Börger FL1036 (THW)",
        description=(
            "Drehkolbenpumpe Hersteller Börger, Typ FL1036, Baujahr 2018, "
            "ausgesondert vom Technischen Hilfswerk. Wenige Betriebsstunden, "
            "Gehäuse i.O., Dichtungssatz neu. Standort: Hamburg, "
            "Selbstabholung."
        ),
        location=Location("DE", "20457", "Hamburg", 53.5413, 9.9849),
        financials=Financials(
            current_bid=1500.0,
            bid_type="SEALED_BID",
            estimated_market_value=4500.0,
            scrap_material="STEEL_ST37",
            weight_kg=1200,
            repair_opex_estimate=300.0,
        ),
        risk_factors=RiskFactors(repair_needed=False),
        brands=["Börger"],
        operating_hours=120,
        year_built=2018,
        found_at=_utc(2026, 5, 1),
        auction_end=_utc(2026, 5, 28),
    ),
    Opportunity(
        asset_id="VEBEG-2026-0188",
        source_platform="VEBEG",
        listing_url="https://www.vebeg.de/de/verkauf/details.htm?ID=2026-0188",
        type="POSITIVE_ASSET",
        category="MILITARY_TRUCK",
        title_normalized="Unimog U1300L Bw, geländegängig",
        description=(
            "Unimog U1300L aus Bundeswehrbeständen, Bj. 1989, Diesel, 4x4. "
            "Ausfuhrgenehmigungspflichtig. Steuerung ohne Funktion, "
            "Gebrauchsspuren am Aufbau."
        ),
        location=Location("DE", "94315", "Straubing", 48.8775, 12.5764,
                          pickup_restrictions=["BAFA"]),
        financials=Financials(
            current_bid=12000.0,
            bid_type="SEALED_BID",
            estimated_market_value=22000.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=7200,
            repair_opex_estimate=2500.0,
        ),
        risk_factors=RiskFactors(
            export_control=True,
            repair_needed=True,
            notes=["Ausfuhrgenehmigungspflichtig"],
        ),
        brands=["Mercedes", "Unimog"],
        operating_hours=None,
        year_built=1989,
        found_at=_utc(2026, 4, 22),
        auction_end=_utc(2026, 5, 20),
    ),
    Opportunity(
        asset_id="ZOLL-2026-77321",
        source_platform="ZOLL",
        listing_url="https://www.zoll-auktion.de/auktion/details.php?ID=77321",
        type="POSITIVE_ASSET",
        category="FIRE_TRUCK",
        title_normalized="LF 16/12 MAN, Feuerwehr Gemeinde Bordesholm",
        description=(
            "Löschgruppenfahrzeug MAN, Aufbau Ziegler, Bj. 2002, ca. 38.000 km, "
            "regelmäßig gewartet. Inkl. Beladung (Schläuche, Tragkraftspritze "
            "TS 8/8). Verkauf wegen Ersatzbeschaffung."
        ),
        location=Location("DE", "24582", "Bordesholm", 54.1763, 10.0339),
        financials=Financials(
            current_bid=8500.0,
            bid_type="ENGLISH",
            estimated_market_value=18500.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=9500,
            repair_opex_estimate=800.0,
        ),
        risk_factors=RiskFactors(),
        brands=["MAN", "Ziegler"],
        operating_hours=None,
        year_built=2002,
        found_at=_utc(2026, 5, 4),
        auction_end=_utc(2026, 5, 14, 18),
    ),
    Opportunity(
        asset_id="TROOSTWIJK-NL-55102",
        source_platform="TROOSTWIJK",
        listing_url="https://www.troostwijkauctions.com/de/a/lot-55102",
        type="POSITIVE_ASSET",
        category="WATERWORKS",
        title_normalized="Saugbagger-Hochleistungspumpen 2x (Rijksoverheid)",
        description=(
            "Zwei Hochleistungspumpen für Polderentwässerung, ehem. "
            "Rijksoverheid (Defensie), 2014, jeweils 75 kW Diesel. "
            "Kavitationsschäden möglich, Laufrad geprüft."
        ),
        location=Location("NL", "3011", "Rotterdam", 51.9244, 4.4777),
        financials=Financials(
            current_bid=4200.0,
            bid_type="ENGLISH",
            estimated_market_value=11000.0,
            scrap_material="STEEL_HMS_1_2",
            weight_kg=2800,
            repair_opex_estimate=1500.0,
        ),
        risk_factors=RiskFactors(repair_needed=True,
                                 notes=["Kavitationsschäden möglich"]),
        brands=["Börger"],
        operating_hours=410,
        year_built=2014,
        found_at=_utc(2026, 4, 30),
        auction_end=_utc(2026, 5, 18),
    ),
    Opportunity(
        asset_id="DOMAINE-FR-LYON-009",
        source_platform="DOMAINE",
        listing_url="https://encheres-domaine.gouv.fr/vente/lyon-2026-009",
        type="POSITIVE_ASSET",
        category="MARITIME_CRANE",
        title_normalized="Hafenkran Liebherr LHM 320, Marine Toulon",
        description=(
            "Mobile harbour crane Liebherr LHM 320, ex-Marine Toulon, "
            "Bj. 2001. Moteur principal i.O., grue de manutention "
            "fonctionnelle. Documents complets."
        ),
        location=Location("FR", "83000", "Toulon", 43.1242, 5.9280),
        financials=Financials(
            current_bid=180000.0,
            bid_type="SEALED_BID",
            estimated_market_value=420000.0,
            scrap_material="STEEL_HMS_1_2",
            weight_kg=320000,
            repair_opex_estimate=12000.0,
        ),
        risk_factors=RiskFactors(),
        brands=["Liebherr"],
        operating_hours=None,
        year_built=2001,
        found_at=_utc(2026, 4, 10),
        auction_end=_utc(2026, 6, 5),
    ),
    Opportunity(
        asset_id="EVERGABE-2026-WSV-WRACK-088",
        source_platform="E-VERGABE",
        listing_url="https://www.evergabe.de/auftraege/2026-wsv-wrack-088",
        type="NEGATIVE_ASSET",
        category="WRECK_REMOVAL",
        title_normalized="Wrackbeseitigung Schubleichter, Mittellandkanal",
        description=(
            "Ausschreibung WSV: Beseitigung gesunkener Schubleichter, "
            "Bj. 1978, ca. 320 t Stahl. Verwertungserlös ist anzurechnen. "
            "Asbestbelastung nicht ausgeschlossen. CPV 60651400-9."
        ),
        location=Location("DE", "31226", "Peine", 52.3194, 10.2341),
        financials=Financials(
            current_bid=145000.0,  # contract value the WSV will pay
            bid_type="TENDER",
            estimated_market_value=0.0,
            scrap_material="STEEL_HMS_1_2",
            weight_kg=320000,
            remediation_cost_estimate=110000.0,
        ),
        risk_factors=RiskFactors(
            hazardous_materials=True,
            pre_1990_vessel=True,
            notes=["Asbest", "Pre-1990 Schiff"],
        ),
        brands=[],
        operating_hours=None,
        year_built=1978,
        found_at=_utc(2026, 5, 2),
        auction_end=_utc(2026, 6, 2, 10),
    ),
    Opportunity(
        asset_id="AMW-PL-OR-WROC-441",
        source_platform="AMW",
        listing_url="https://amw.com.pl/przetarg/2026-wroc-441",
        type="POSITIVE_ASSET",
        category="MILITARY_TRUCK",
        title_normalized="Star 266 6x6, AMW Wrocław",
        description=(
            "Star 266 6x6, ex-Wojsko Polskie, Bj. 1986. Robust, mechanisch, "
            "kein ABC-Schutz. Geeignet für Tiefbau / Forst. "
            "Selbstabholung Wrocław."
        ),
        location=Location("PL", "50-001", "Wrocław", 51.1079, 17.0385),
        financials=Financials(
            current_bid=4500.0,
            bid_type="SEALED_BID",
            estimated_market_value=9500.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=6800,
            repair_opex_estimate=1200.0,
        ),
        risk_factors=RiskFactors(repair_needed=True),
        brands=[],
        operating_hours=None,
        year_built=1986,
        found_at=_utc(2026, 4, 28),
        auction_end=_utc(2026, 5, 25),
    ),
    Opportunity(
        asset_id="VEBEG-2026-0211",
        source_platform="VEBEG",
        listing_url="https://www.vebeg.de/de/verkauf/details.htm?ID=2026-0211",
        type="POSITIVE_ASSET",
        category="GENERATOR",
        title_normalized="Notstromaggregat 80 kVA, Zivilschutz",
        description=(
            "Notstromaggregat 80 kVA, Zivilschutz-Reserve, kalendarisch "
            "ausgesondert. Nur 84 Betriebsstunden, voll dokumentiert."
        ),
        location=Location("DE", "30159", "Hannover", 52.3759, 9.7320),
        financials=Financials(
            current_bid=2200.0,
            bid_type="SEALED_BID",
            estimated_market_value=8500.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=950,
            repair_opex_estimate=0.0,
        ),
        risk_factors=RiskFactors(),
        brands=["MAN"],
        operating_hours=84,
        year_built=2011,
        found_at=_utc(2026, 5, 6),
        auction_end=_utc(2026, 5, 30),
    ),
    Opportunity(
        asset_id="EVERGABE-2026-WEHR-RUECKBAU-014",
        source_platform="E-VERGABE",
        listing_url="https://www.evergabe.de/auftraege/2026-wehr-rueckbau-014",
        type="NEGATIVE_ASSET",
        category="WATERWORKS_DECONSTRUCTION",
        title_normalized="Rückbau Wehr Lauffen am Neckar (WSV)",
        description=(
            "Rückbau Stauwehr nach EU-Wasserrahmenrichtlinie. "
            "Geschätzt 220 t Stahl (Schütze, Antriebe), 8 t Kupfer "
            "(Kabelagen, Motoren). CPV 45110000-1. "
            "Verwertungserlös ist anzurechnen."
        ),
        location=Location("DE", "74348", "Lauffen", 49.0735, 9.1486),
        financials=Financials(
            current_bid=380000.0,
            bid_type="TENDER",
            estimated_market_value=0.0,
            scrap_material="STEEL_HMS_1_2",
            weight_kg=220000,
            remediation_cost_estimate=290000.0,
        ),
        risk_factors=RiskFactors(),
        brands=[],
        operating_hours=None,
        year_built=1962,
        found_at=_utc(2026, 4, 18),
        auction_end=_utc(2026, 6, 12),
    ),
    Opportunity(
        asset_id="ZOLL-2026-77890",
        source_platform="ZOLL",
        listing_url="https://www.zoll-auktion.de/auktion/details.php?ID=77890",
        type="POSITIVE_ASSET",
        category="PSA",
        title_normalized="Atemschutzgeräte Konvolut (32 Stk.) - Sammlerzwecke",
        description=(
            "32 Atemschutzgeräte ehem. Feuerwehr, Druckbehälterprüfung "
            "abgelaufen. Nur zu Sammlerzwecken. Nicht für den Einsatz "
            "zugelassen."
        ),
        location=Location("DE", "04109", "Leipzig", 51.3397, 12.3731),
        financials=Financials(
            current_bid=190.0,
            bid_type="ENGLISH",
            estimated_market_value=400.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=160,
            repair_opex_estimate=0.0,
        ),
        risk_factors=RiskFactors(notes=["Nur zu Sammlerzwecken",
                                        "Attest abgelaufen"]),
        brands=["Dräger"],
        operating_hours=None,
        year_built=2003,
        found_at=_utc(2026, 5, 3),
        auction_end=_utc(2026, 5, 12, 19),
    ),
    Opportunity(
        asset_id="EVERGABE-2026-BROWNFIELD-077",
        source_platform="E-VERGABE",
        listing_url="https://www.evergabe.de/auftraege/2026-brownfield-077",
        type="NEGATIVE_ASSET",
        category="BROWNFIELD",
        title_normalized="Altlastenflaeche ehem. Kupferhuette Helbra",
        description=(
            "Industriebrache mit Bodenkontamination (Schwermetalle, "
            "Mineraloelkohlenwasserstoffe). 4,2 ha. Symbolischer Kaufpreis "
            "1 EUR plus Sanierungszuschuss vom Land. CPV 90722200-6. "
            "Altlastenverdachtsflaeche im Boden- und Altlastenkataster."
        ),
        location=Location("DE", "06311", "Helbra", 51.5468, 11.4965),
        financials=Financials(
            current_bid=850000.0,  # subsidy paid to whoever takes the land
            bid_type="TENDER",
            estimated_market_value=0.0,
            scrap_material=None,
            weight_kg=None,
            remediation_cost_estimate=620000.0,
        ),
        risk_factors=RiskFactors(
            hazardous_materials=True,
            notes=["Altlast", "Bodenkontamination"],
        ),
        brands=[],
        operating_hours=None,
        year_built=None,
        found_at=_utc(2026, 4, 12),
        auction_end=_utc(2026, 6, 20),
    ),
    Opportunity(
        asset_id="NETBID-INSO-2026-3318",
        source_platform="NETBID",
        listing_url="https://www.netbid.com/de/auction/insolvenz-3318",
        type="POSITIVE_ASSET",
        category="WATERWORKS",
        title_normalized="Hochleistungspumpe Boerger AL75, Mittelstandsinsolvenz",
        description=(
            "Drehkolbenpumpe Boerger AL75, Bj. 2020, ca. 380 Betriebsstunden. "
            "Aus Insolvenzverfahren eines Spezialtiefbauunternehmens. "
            "Komplett mit Frequenzumrichter und Steuerung. Besichtigung "
            "nach Termin. Gekauft wie gesehen."
        ),
        location=Location("DE", "44135", "Dortmund", 51.5135, 7.4653),
        financials=Financials(
            current_bid=6500.0,
            bid_type="ENGLISH",
            estimated_market_value=14500.0,
            scrap_material="STEEL_ST37",
            weight_kg=900,
            repair_opex_estimate=400.0,
        ),
        risk_factors=RiskFactors(),
        brands=["Börger"],
        operating_hours=380,
        year_built=2020,
        found_at=_utc(2026, 5, 5),
        auction_end=_utc(2026, 5, 22, 16),
    ),
    Opportunity(
        asset_id="FORNAES-DK-2026-0042",
        source_platform="FORNAES",
        listing_url="https://www.fornaes.com/parts/2026-0042",
        type="POSITIVE_ASSET",
        category="MARITIME_SPARE",
        title_normalized="Schottel SRP 1212 Ruderpropeller (refurbished)",
        description=(
            "Ausgebauter Schottel-Ruderpropeller SRP 1212 vom Verschrottungs- "
            "schiff M/V Nordkap (Bj. 1998). Hauptlager geprueft, Hydraulik "
            "ueberholt. Ideal als Ersatz fuer aeltere Hafenschlepper "
            "(End of Life beim Hersteller). Standort Grenaa, DK."
        ),
        location=Location("DK", "8500", "Grenaa", 56.4143, 10.8807),
        financials=Financials(
            current_bid=42000.0,
            bid_type="FIXED_PRICE",
            estimated_market_value=95000.0,
            scrap_material="STEEL_HMS_1_2",
            weight_kg=3200,
            repair_opex_estimate=4500.0,
        ),
        risk_factors=RiskFactors(repair_needed=False),
        brands=["Schottel"],
        operating_hours=None,
        year_built=1998,
        found_at=_utc(2026, 4, 25),
        auction_end=_utc(2026, 6, 1),
    ),
    Opportunity(
        asset_id="DOMAINE-FR-BREST-0034",
        source_platform="DOMAINE",
        listing_url="https://encheres-domaine.gouv.fr/vente/brest-2026-0034",
        type="POSITIVE_ASSET",
        category="GENERATOR",
        title_normalized="Dieselgenerator Volvo Penta 250 kVA, Marine Brest",
        description=(
            "Groupe electrogene marine, Volvo Penta TAD1242GE, 250 kVA, "
            "Bj. 2010, ca. 1100 Betriebsstunden. Reservequelle Marine "
            "Nationale, Selbstabholung Brest, Frankreich. Documents complets."
        ),
        location=Location("FR", "29200", "Brest", 48.3905, -4.4860),
        financials=Financials(
            current_bid=9800.0,
            bid_type="SEALED_BID",
            estimated_market_value=28500.0,
            scrap_material="MIXED_FERROUS",
            weight_kg=2400,
            repair_opex_estimate=600.0,
        ),
        risk_factors=RiskFactors(),
        brands=["Volvo Penta"],
        operating_hours=1100,
        year_built=2010,
        found_at=_utc(2026, 4, 28),
        auction_end=_utc(2026, 5, 26),
    ),
]

_DB: dict[str, Opportunity] = {opp.asset_id: enrich(opp) for opp in _SAMPLE}


# ---------------------------------------------------------------------------
# Public query API (used by the dashboard AND by the agent's tools)
# ---------------------------------------------------------------------------

def all_opportunities() -> list[Opportunity]:
    return list(_DB.values())


def get(asset_id: str) -> Opportunity | None:
    return _DB.get(asset_id)


def search(
    *,
    category: str | None = None,
    country: str | None = None,
    type_: str | None = None,
    platform: str | None = None,
    min_score: int | None = None,
    keyword: str | None = None,
) -> list[Opportunity]:
    result: Iterable[Opportunity] = _DB.values()

    def matches(o: Opportunity) -> bool:
        if category and o.category != category:
            return False
        if country and o.location.country != country:
            return False
        if type_ and o.type != type_:
            return False
        if platform and o.source_platform != platform:
            return False
        if min_score is not None and o.score < min_score:
            return False
        if keyword:
            blob = " ".join([o.title_normalized, o.description]).lower()
            if keyword.lower() not in blob:
                return False
        return True

    return sorted(
        (o for o in result if matches(o)),
        key=lambda o: (-o.score, o.auction_end),
    )


def to_dict(opp: Opportunity) -> dict:
    """Render an opportunity as the canonical JSON-style dict from the
    handbook section 8.3 (used both for the agent's tool output and the
    dashboard JSON drawer)."""
    return {
        "asset_id": opp.asset_id,
        "source_platform": opp.source_platform,
        "listing_url": opp.listing_url,
        "type": opp.type,
        "category": opp.category,
        "title_normalized": opp.title_normalized,
        "description": opp.description,
        "location": {
            "country": opp.location.country,
            "zip": opp.location.zip,
            "city": opp.location.city,
            "lat": opp.location.lat,
            "lon": opp.location.lon,
            "pickup_restrictions": opp.location.pickup_restrictions,
        },
        "financials": {
            "currency": opp.financials.currency,
            "current_bid": opp.financials.current_bid,
            "bid_type": opp.financials.bid_type,
            "estimated_market_value": opp.financials.estimated_market_value,
            "scrap_material": opp.financials.scrap_material,
            "weight_kg": opp.financials.weight_kg,
            "scrap_value_potential": opp.scrap_value_potential,
            "logistics_cost_estimate": opp.logistics_cost_estimate,
            "repair_opex_estimate": opp.financials.repair_opex_estimate,
            "remediation_cost_estimate": opp.financials.remediation_cost_estimate,
            "net_asset_value": opp.net_asset_value,
            "bid_ceiling": opp.bid_ceiling,
        },
        "risk_factors": {
            "export_control": opp.risk_factors.export_control,
            "hazardous_materials": opp.risk_factors.hazardous_materials,
            "repair_needed": opp.risk_factors.repair_needed,
            "missing_parts": opp.risk_factors.missing_parts,
            "pre_1990_vessel": opp.risk_factors.pre_1990_vessel,
            "red_flags": detect_red_flags(opp),
            "dual_use_suspected": detect_dual_use(opp),
            "notes": opp.risk_factors.notes,
        },
        "scoring": {
            "score": opp.score,
            "breakdown": opp.score_breakdown,
        },
        "timestamps": {
            "found_at": opp.found_at.isoformat(),
            "auction_end": opp.auction_end.isoformat(),
        },
        "brands": opp.brands,
        "operating_hours": opp.operating_hours,
        "year_built": opp.year_built,
    }
