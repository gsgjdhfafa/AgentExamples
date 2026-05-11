"""Pytest suite for the procurement scoring & enrichment engine.

Run with: ``pytest tests/test_procurement_data.py -v``
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

import procurement_data as pdata
from procurement_data import (
    Financials,
    HOME_DEPOT,
    Location,
    Opportunity,
    RiskFactors,
    compute_bid_ceiling,
    detect_dual_use,
    detect_red_flags,
    enrich,
    estimate_logistics_cost,
    estimate_scrap_value,
    haversine_km,
    score_opportunity,
    search,
)


def _utc(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 12, tzinfo=timezone.utc)


def _make_positive(
    *,
    asset_id: str = "TEST-POS-1",
    bid: float = 1000.0,
    market: float = 4000.0,
    weight: float = 1000.0,
    lat: float = 53.5511,
    lon: float = 9.9937,
    brands: list[str] | None = None,
    notes: list[str] | None = None,
    year_built: int = 2018,
    hours: int | None = 50,
    repair: float = 0.0,
    export_control: bool = False,
    pre_1990: bool = False,
    description: str = "Standard description",
) -> Opportunity:
    return Opportunity(
        asset_id=asset_id,
        source_platform="VEBEG",
        listing_url="https://example/",
        type="POSITIVE_ASSET",
        category="MARITIME_PUMP",
        title_normalized="Test pump",
        description=description,
        location=Location("DE", "20457", "Hamburg", lat, lon),
        financials=Financials(
            current_bid=bid,
            bid_type="SEALED_BID",
            estimated_market_value=market,
            scrap_material="STEEL_ST37",
            weight_kg=weight,
            repair_opex_estimate=repair,
        ),
        risk_factors=RiskFactors(
            export_control=export_control,
            pre_1990_vessel=pre_1990,
            notes=notes or [],
        ),
        brands=brands or ["Börger"],
        operating_hours=hours,
        year_built=year_built,
        found_at=_utc(2026, 5, 1),
        auction_end=_utc(2026, 5, 30),
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_km(53.5511, 9.9937, 53.5511, 9.9937) == pytest.approx(0.0)

    def test_hamburg_to_toulon_about_1200km(self):
        # Hamburg (53.55, 9.99) -> Toulon (43.12, 5.93), great-circle ~1200 km
        d = haversine_km(53.5511, 9.9937, 43.1242, 5.9280)
        assert 1100 < d < 1300, f"Hamburg->Toulon should be ~1200km, got {d:.1f}"

    def test_symmetric(self):
        a = haversine_km(53.5511, 9.9937, 51.1079, 17.0385)
        b = haversine_km(51.1079, 17.0385, 53.5511, 9.9937)
        assert a == pytest.approx(b)


# ---------------------------------------------------------------------------
# Scrap value
# ---------------------------------------------------------------------------

class TestScrapValue:
    def test_steel_st37(self):
        opp = _make_positive(weight=1000)  # 1 tonne ST37 @ 320 EUR/t
        assert estimate_scrap_value(opp) == pytest.approx(320.0)

    def test_zero_weight_returns_zero(self):
        opp = _make_positive(weight=0)
        opp.financials.weight_kg = None
        assert estimate_scrap_value(opp) == 0.0

    def test_unknown_material_uses_fallback(self):
        opp = _make_positive(weight=1000)
        opp.financials.scrap_material = "UNOBTAINIUM"
        # falls back to 250 EUR/t per implementation
        assert estimate_scrap_value(opp) == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# Logistics
# ---------------------------------------------------------------------------

class TestLogistics:
    def test_at_home_depot_is_near_zero(self):
        opp = _make_positive(lat=HOME_DEPOT[2], lon=HOME_DEPOT[3], weight=500)
        assert estimate_logistics_cost(opp) < 5.0

    def test_heavy_load_gets_surcharge(self):
        light = _make_positive(weight=1000, lat=48.8775, lon=12.5764)  # Straubing
        heavy = _make_positive(weight=10000, lat=48.8775, lon=12.5764)
        assert estimate_logistics_cost(heavy) == pytest.approx(
            estimate_logistics_cost(light) * 1.30, rel=1e-3
        )

    def test_custom_rate(self):
        opp = _make_positive(weight=1000, lat=48.8775, lon=12.5764)  # ~640km
        cheap = estimate_logistics_cost(opp, eur_per_km=1.0)
        expensive = estimate_logistics_cost(opp, eur_per_km=3.0)
        assert expensive == pytest.approx(cheap * 3.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Red flags / dual use
# ---------------------------------------------------------------------------

class TestRiskDetection:
    def test_asbest_detected(self):
        opp = _make_positive(description="Schiff mit Asbest belastet")
        flags = detect_red_flags(opp)
        assert any("Asbest" in f for f in flags)

    def test_sammlerzwecke_detected(self):
        opp = _make_positive(notes=["Nur zu Sammlerzwecken"])
        assert "Nur zu Sammlerzwecken" in detect_red_flags(opp)

    def test_clean_listing_has_no_flags(self):
        opp = _make_positive(description="Gewartet, vollständige Dokumentation.")
        assert detect_red_flags(opp) == []

    def test_dual_use_via_keyword(self):
        opp = _make_positive(description="Unimog U1300L Bw aus Bundeswehrbeständen")
        assert detect_dual_use(opp) is True

    def test_dual_use_via_export_control_flag(self):
        opp = _make_positive(export_control=True)
        assert detect_dual_use(opp) is True

    def test_no_dual_use_on_civilian(self):
        opp = _make_positive(description="Ehemaliges Bauhof-Notstromaggregat")
        assert detect_dual_use(opp) is False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_score_in_bounds(self):
        opp = _make_positive()
        score, _ = score_opportunity(opp)
        assert 0 <= score <= 100

    def test_high_margin_scores_high(self):
        cheap = _make_positive(bid=500, market=5000)   # 90% margin
        scarce = _make_positive(bid=4800, market=5000) # 4% margin
        s_cheap, _ = score_opportunity(cheap)
        s_scarce, _ = score_opportunity(scarce)
        assert s_cheap > s_scarce

    def test_premium_brand_adds_points(self):
        with_brand = _make_positive(brands=["Liebherr"])
        without = _make_positive(brands=["NoName"])
        s1, _ = score_opportunity(with_brand)
        s2, _ = score_opportunity(without)
        assert s1 > s2

    def test_close_proximity_beats_far(self):
        close = _make_positive(lat=HOME_DEPOT[2], lon=HOME_DEPOT[3])
        far = _make_positive(lat=43.1242, lon=5.9280)  # Toulon
        s_close, _ = score_opportunity(close)
        s_far, _ = score_opportunity(far)
        assert s_close > s_far

    def test_pre_1990_vessel_penalised(self):
        clean = _make_positive()
        old = _make_positive(pre_1990=True)
        s1, _ = score_opportunity(clean)
        s2, _ = score_opportunity(old)
        assert s1 > s2

    def test_unflagged_dual_use_penalised(self):
        # Tight margin so the score does not saturate at 100. The description
        # contains an exact DUAL_USE term so detect_dual_use() fires for both
        # listings; only the export_control flag changes.
        flagged = _make_positive(
            bid=3800, market=4000,
            description="Unimog U1300L Bw ausgesondert",
            export_control=True,
        )
        unflagged = _make_positive(
            bid=3800, market=4000,
            description="Unimog U1300L Bw ausgesondert",
            export_control=False,
        )
        s_flagged, _ = score_opportunity(flagged)
        s_unflagged, _ = score_opportunity(unflagged)
        assert s_unflagged < s_flagged, (
            f"unflagged={s_unflagged} should be lower than flagged={s_flagged}"
        )


# ---------------------------------------------------------------------------
# Bid ceiling formula
# ---------------------------------------------------------------------------

class TestBidCeiling:
    def test_positive_asset_formula(self):
        opp = _make_positive(market=10000, repair=500, weight=1000)
        enrich(opp)  # sets scrap + logistics
        expected = (
            10000
            - opp.logistics_cost_estimate
            - 500
            - 0.25 * 10000
            + opp.scrap_value_potential
        )
        assert compute_bid_ceiling(opp) == pytest.approx(round(max(expected, 0), 2))

    def test_negative_asset_formula(self):
        opp = _make_positive()
        opp.type = "NEGATIVE_ASSET"
        opp.financials.remediation_cost_estimate = 100000
        opp.financials.estimated_market_value = 0
        enrich(opp)
        expected = 100000 - opp.scrap_value_potential + 0.25 * 100000
        assert compute_bid_ceiling(opp) == pytest.approx(round(max(expected, 0), 2))

    def test_ceiling_clamps_at_zero(self):
        opp = _make_positive(market=100, repair=10000, weight=0)
        opp.financials.weight_kg = None
        enrich(opp)
        assert compute_bid_ceiling(opp) >= 0


# ---------------------------------------------------------------------------
# Search & sort
# ---------------------------------------------------------------------------

class TestSearch:
    def test_unfiltered_returns_all(self):
        assert len(search()) == len(pdata.all_opportunities())

    def test_results_sorted_by_score_desc(self):
        results = search()
        scores = [o.score for o in results]
        assert scores == sorted(scores, reverse=True)

    def test_country_filter(self):
        de = search(country="DE")
        assert all(o.location.country == "DE" for o in de)
        assert len(de) > 0

    def test_min_score_filter(self):
        results = search(min_score=70)
        assert all(o.score >= 70 for o in results)

    def test_keyword_filter_in_description(self):
        results = search(keyword="Asbest")
        assert any("asbest" in (o.description + o.title_normalized).lower()
                   for o in results)

    def test_negative_assets_only(self):
        neg = search(type_="NEGATIVE_ASSET")
        assert all(o.type == "NEGATIVE_ASSET" for o in neg)
        assert len(neg) >= 1


# ---------------------------------------------------------------------------
# Net asset value
# ---------------------------------------------------------------------------

class TestNetAssetValue:
    def test_positive_nav_includes_scrap(self):
        opp = _make_positive(market=5000, bid=1000, weight=1000, repair=200)
        enrich(opp)
        expected = (
            5000 - 1000 - opp.logistics_cost_estimate - 200 + opp.scrap_value_potential
        )
        assert opp.net_asset_value == pytest.approx(round(expected, 2))

    def test_negative_nav_uses_remediation(self):
        opp = _make_positive()
        opp.type = "NEGATIVE_ASSET"
        opp.financials.current_bid = 150000
        opp.financials.remediation_cost_estimate = 100000
        opp.financials.estimated_market_value = 0
        enrich(opp)
        expected = 150000 - 100000 + opp.scrap_value_potential
        assert opp.net_asset_value == pytest.approx(round(expected, 2))
