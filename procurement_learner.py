"""Bargain learner - turns operator decisions and observed auction outcomes
into per-category corrections that feed back into the scoring engine.

Two effects:

1. **Category fit**: if the operator consistently says YES to maritime tug
   equipment but NO to PSA, future maritime-tug listings get a category
   bonus and PSA listings get a penalty in the score.

2. **Market-value recalibration**: if observed final auction prices for a
   category are consistently *lower* than our ``estimated_market_value``,
   we are over-optimistic. Apply a multiplicative correction so the Net
   Asset Value, bid ceiling and score stop quoting fantasy margins.

Both effects are intentionally conservative (small bonuses, neutral prior of
1.0) so a handful of decisions do not destabilise the score.
"""

from __future__ import annotations

from dataclasses import dataclass

import procurement_data as pdata
import procurement_store as pstore


# Hyperparameters - all small on purpose so the learner stays gentle.
CATEGORY_FIT_MAX_BONUS = 12     # +/- points added to the score
CATEGORY_FIT_MIN_SAMPLES = 3
MARKET_CORRECTION_FLOOR = 0.5   # never trust an extreme correction
MARKET_CORRECTION_CEIL = 1.5
MARKET_CORRECTION_MIN_SAMPLES = 3


@dataclass
class LearnedAdjustment:
    category: str
    fit_bonus: int                 # -12 .. +12
    market_multiplier: float       # 0.5 .. 1.5
    decision_samples: int
    observation_samples: int


def _yes_rate_to_bonus(rate: float, samples: int) -> int:
    if samples < CATEGORY_FIT_MIN_SAMPLES:
        return 0
    # 0.5 (neutral) -> 0 bonus; 1.0 (always yes) -> +CATEGORY_FIT_MAX_BONUS;
    # 0.0 (always no) -> -CATEGORY_FIT_MAX_BONUS
    centred = (rate - 0.5) * 2  # -1..+1
    return int(round(centred * CATEGORY_FIT_MAX_BONUS))


def adjustment_for(category: str) -> LearnedAdjustment:
    yes_rate = pstore.category_yes_rate(category)
    decisions = sum(
        1 for d in pstore.all_decisions() if d.category == category
    )
    market_ratio, obs_n = pstore.observed_ratio(category)
    if obs_n < MARKET_CORRECTION_MIN_SAMPLES:
        market_multiplier = 1.0
    else:
        market_multiplier = max(
            MARKET_CORRECTION_FLOOR,
            min(MARKET_CORRECTION_CEIL, market_ratio),
        )
    return LearnedAdjustment(
        category=category,
        fit_bonus=_yes_rate_to_bonus(yes_rate, decisions),
        market_multiplier=market_multiplier,
        decision_samples=decisions,
        observation_samples=obs_n,
    )


def apply_learning(opp: pdata.Opportunity) -> tuple[int, dict[str, int]]:
    """Return (adjusted_score, breakdown) for the opportunity, augmenting the
    handbook rubric with the learner's category fit + market correction.

    Idempotent: callers can run this every render without state leakage.
    """
    adj = adjustment_for(opp.category)

    # Apply market multiplier in-place so the operator-facing NAV / bid
    # ceiling reflect the learned correction.
    if adj.market_multiplier != 1.0 and opp.financials.estimated_market_value:
        corrected = round(
            opp.financials.estimated_market_value * adj.market_multiplier, 2
        )
        opp.financials.estimated_market_value = corrected

    # Recompute base score with the corrected market value.
    base_score, breakdown = pdata.score_opportunity(opp)
    breakdown["learned_fit"] = adj.fit_bonus
    adjusted = max(0, min(100, base_score + adj.fit_bonus))
    return adjusted, breakdown


def summarise() -> list[LearnedAdjustment]:
    """One ``LearnedAdjustment`` per category for which we have any data.

    Used in the dashboard's "Agent Monitor" tab to show what the learner
    currently believes.
    """
    categories: set[str] = set()
    for d in pstore.all_decisions():
        if d.category:
            categories.add(d.category)
    # plus categories with observations
    import sqlite3
    with sqlite3.connect(pstore.DB_PATH) as conn:
        for (cat,) in conn.execute(
            "SELECT DISTINCT category FROM observations"
        ):
            categories.add(cat)
    return [adjustment_for(c) for c in sorted(categories)]
