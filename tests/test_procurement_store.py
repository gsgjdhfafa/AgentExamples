"""Tests for the SQLite persistence layer and the bargain learner."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    """Each test gets a fresh SQLite file. The store module reads
    ``PROCUREMENT_DB`` at import time, so we have to reimport after setting it.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    monkeypatch.setenv("PROCUREMENT_DB", path)
    import importlib
    import procurement_store
    importlib.reload(procurement_store)
    yield procurement_store
    try:
        os.unlink(path)
    except OSError:
        pass


class TestDecisions:
    def test_record_and_get(self, temp_db):
        temp_db.record_decision(
            "VEBEG-1", "YES",
            category="MARITIME_PUMP", score=88, net_value=4200.0,
            rationale="cheap",
        )
        got = temp_db.get_decision("VEBEG-1")
        assert got is not None
        assert got.verdict == "YES"
        assert got.category == "MARITIME_PUMP"
        assert got.score == 88

    def test_overwrite_on_repeat(self, temp_db):
        temp_db.record_decision("ID", "LATER", category="X")
        temp_db.record_decision("ID", "YES", category="X")
        assert temp_db.get_decision("ID").verdict == "YES"

    def test_invalid_verdict_rejected(self, temp_db):
        with pytest.raises(ValueError):
            temp_db.record_decision("ID", "MAYBE")

    def test_category_yes_rate_neutral_prior(self, temp_db):
        # No data -> neutral 0.5
        assert temp_db.category_yes_rate("NEVER_SEEN") == 0.5

    def test_category_yes_rate_with_data(self, temp_db):
        for i, verdict in enumerate(["YES", "YES", "NO", "YES"]):
            temp_db.record_decision(f"X{i}", verdict, category="MARITIME_PUMP")
        assert temp_db.category_yes_rate("MARITIME_PUMP") == 0.75


class TestObservations:
    def test_observed_ratio_no_data(self, temp_db):
        ratio, n = temp_db.observed_ratio("FIRE_TRUCK")
        assert ratio == 1.0 and n == 0

    def test_observed_ratio_mean(self, temp_db):
        # Final price was 0.5x estimate, then 1.0x, then 0.75x => mean 0.75
        temp_db.record_observation("A", "FIRE_TRUCK", 5000, estimated_market_value=10000)
        temp_db.record_observation("B", "FIRE_TRUCK", 9000, estimated_market_value=9000)
        temp_db.record_observation("C", "FIRE_TRUCK", 7500, estimated_market_value=10000)
        ratio, n = temp_db.observed_ratio("FIRE_TRUCK")
        assert n == 3
        assert ratio == pytest.approx((0.5 + 1.0 + 0.75) / 3)


class TestAgentRuns:
    def test_start_and_finish(self, temp_db):
        rid = temp_db.start_agent_run("Bargain-Hunter")
        temp_db.finish_agent_run(
            rid, found_count=5, hot_count=2,
            top_asset_id="X-1", top_score=88, notes="ok",
        )
        runs = temp_db.recent_runs()
        assert len(runs) == 1
        assert runs[0].agent_name == "Bargain-Hunter"
        assert runs[0].found_count == 5
        assert runs[0].finished_at is not None

    def test_last_run_per_agent(self, temp_db):
        for i in range(3):
            rid = temp_db.start_agent_run("A")
            temp_db.finish_agent_run(rid, found_count=i, hot_count=0,
                                     top_asset_id=None, top_score=None)
        last = temp_db.last_run_per_agent()
        assert last["A"].found_count == 2  # the last one


class TestLearner:
    def test_neutral_when_no_data(self, temp_db):
        import importlib
        import procurement_learner
        importlib.reload(procurement_learner)
        adj = procurement_learner.adjustment_for("ANY_CATEGORY")
        assert adj.fit_bonus == 0
        assert adj.market_multiplier == 1.0

    def test_positive_bias_after_yes(self, temp_db):
        for i in range(5):
            temp_db.record_decision(f"X{i}", "YES", category="MARITIME_PUMP")
        import importlib
        import procurement_learner
        importlib.reload(procurement_learner)
        adj = procurement_learner.adjustment_for("MARITIME_PUMP")
        assert adj.fit_bonus > 0
        assert adj.decision_samples == 5

    def test_negative_bias_after_no(self, temp_db):
        for i in range(5):
            temp_db.record_decision(f"X{i}", "NO", category="PSA")
        import importlib
        import procurement_learner
        importlib.reload(procurement_learner)
        adj = procurement_learner.adjustment_for("PSA")
        assert adj.fit_bonus < 0

    def test_market_correction_clamped(self, temp_db):
        # Extreme drop: observations say things sell at 5 % of estimate
        for i in range(5):
            temp_db.record_observation(
                f"O{i}", "TUG", 50, estimated_market_value=10000,
            )
        import importlib
        import procurement_learner
        importlib.reload(procurement_learner)
        adj = procurement_learner.adjustment_for("TUG")
        # clamped at MARKET_CORRECTION_FLOOR (0.5)
        assert adj.market_multiplier == pytest.approx(
            procurement_learner.MARKET_CORRECTION_FLOOR
        )
