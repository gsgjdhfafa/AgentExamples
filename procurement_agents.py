"""Multi-agent registry for the Procurement dashboard.

Each "specialist" is a function that scans the current opportunity feed and
emits a small set of recommendations under its own lens:

* ``BargainHunter``         - cheapest assets vs. estimated market value,
                              tight deadline.
* ``ScrapMaximizer``        - assets whose scrap credit alone covers >= 60 %
                              of the current bid (downside-protected).
* ``PreciousMetalsHunter``  - coin scrap / precious metal lots with thick
                              melt-value margin.
* ``TritonMaritime``        - tug- and harbour-vessel relevant equipment
                              (winches, propellers, pumps) prioritised by
                              proximity to a maritime depot.
* ``Generalist``            - the original Procurement Agent's pick of the
                              top 3 by raw score.

Every specialist runs ``scan()``, records an ``agent_run`` row via
``procurement_store`` and returns its top opportunity. The dashboard renders
all specialists side-by-side in the "Agent Monitor" tab.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

import procurement_data as pdata
import procurement_learner as plearner
import procurement_store as pstore


@dataclass
class AgentRecommendation:
    agent_name: str
    opportunity: pdata.Opportunity
    rationale: str
    confidence: int  # 0-100


class Specialist(ABC):
    name: str
    description: str

    @abstractmethod
    def scan(self, opps: list[pdata.Opportunity]) -> list[AgentRecommendation]:
        ...

    def run(
        self, opps: list[pdata.Opportunity], record: bool = True
    ) -> list[AgentRecommendation]:
        run_id = pstore.start_agent_run(self.name) if record else None
        recs = self.scan(opps)
        if record and run_id is not None:
            top = recs[0] if recs else None
            pstore.finish_agent_run(
                run_id,
                found_count=len(recs),
                hot_count=sum(1 for r in recs if r.confidence >= 80),
                top_asset_id=top.opportunity.asset_id if top else None,
                top_score=top.opportunity.score if top else None,
                notes=(top.rationale[:240] if top else None),
            )
        return recs


# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------

class BargainHunter(Specialist):
    name = "Bargain-Hunter"
    description = ("Sucht die groessten Margen zwischen Marktwert und "
                   "aktuellem Gebot bei Restlaufzeit ≤ 21 Tagen.")

    def scan(self, opps):
        now = datetime.now(timezone.utc)
        candidates = [
            o for o in opps
            if o.type == "POSITIVE_ASSET"
            and o.financials.estimated_market_value > 0
            and (o.auction_end - now).days <= 21
            and o.auction_end > now
        ]
        candidates.sort(
            key=lambda o: -(o.financials.estimated_market_value - o.financials.current_bid)
                          / max(o.financials.estimated_market_value, 1),
        )
        out: list[AgentRecommendation] = []
        for o in candidates[:5]:
            margin_pct = (
                100 * (o.financials.estimated_market_value - o.financials.current_bid)
                / o.financials.estimated_market_value
            )
            out.append(AgentRecommendation(
                agent_name=self.name,
                opportunity=o,
                rationale=(f"Marge {margin_pct:.0f} % gegenueber Marktwert "
                           f"({o.financials.current_bid:.0f}/{o.financials.estimated_market_value:.0f} EUR). "
                           f"Auktionsende in {(o.auction_end - now).days} Tagen."),
                confidence=min(100, int(margin_pct + o.score / 2)),
            ))
        return out


class ScrapMaximizer(Specialist):
    name = "Scrap-Maximizer"
    description = ("Assets, deren reiner Schrottwert einen Grossteil des "
                   "Gebots deckt - kaum Downside.")

    def scan(self, opps):
        out: list[AgentRecommendation] = []
        for o in opps:
            if o.financials.current_bid <= 0:
                continue
            coverage = o.scrap_value_potential / o.financials.current_bid
            if coverage >= 0.6 and o.type == "POSITIVE_ASSET":
                out.append(AgentRecommendation(
                    agent_name=self.name,
                    opportunity=o,
                    rationale=(f"Schrottwert {o.scrap_value_potential:.0f} EUR deckt "
                               f"{coverage*100:.0f} % des aktuellen Gebots "
                               f"({o.financials.current_bid:.0f} EUR). "
                               f"Material: {o.financials.scrap_material}, "
                               f"{(o.financials.weight_kg or 0):.0f} kg."),
                    confidence=min(100, int(coverage * 80 + o.score / 3)),
                ))
        out.sort(key=lambda r: -r.confidence)
        return out[:5]


class PreciousMetalsHunter(Specialist):
    name = "Precious-Metals-Hunter"
    description = ("Muenzschrott und Edelmetall-Lots mit Schmelzwert deutlich "
                   "ueber Startgebot.")

    PRECIOUS = {
        "SILVER", "GOLD", "PLATINUM", "PALLADIUM",
        "COIN_SCRAP_MIXED", "COIN_SCRAP_SILVER",
    }

    def scan(self, opps):
        out: list[AgentRecommendation] = []
        for o in opps:
            mat = o.financials.scrap_material or ""
            if mat not in self.PRECIOUS:
                continue
            if o.financials.current_bid <= 0:
                continue
            melt_margin = o.scrap_value_potential - o.financials.current_bid
            if melt_margin <= 0:
                continue
            out.append(AgentRecommendation(
                agent_name=self.name,
                opportunity=o,
                rationale=(f"Schmelzwert {o.scrap_value_potential:.0f} EUR liegt "
                           f"{melt_margin:.0f} EUR ueber dem Gebot. "
                           f"Material: {mat}, {(o.financials.weight_kg or 0):.1f} kg."),
                confidence=min(100, int(melt_margin / max(o.financials.current_bid, 1) * 50 + 50)),
            ))
        out.sort(key=lambda r: -r.confidence)
        return out[:5]


class TritonMaritime(Specialist):
    name = "Triton-Maritime"
    description = ("Tug- und Hafentechnik (Winden, Propeller, Pumpen) - "
                   "priorisiert nach Naehe zu norddeutschen Haefen.")

    MARITIME_CATEGORIES = {
        "MARITIME_PUMP", "MARITIME_CRANE", "MARITIME_SPARE",
        "TUG_EQUIPMENT", "WATERWORKS",
    }
    MARITIME_KEYWORDS = {
        "schlepp", "ponton", "schottel", "ruderpropeller", "winde",
        "saugbagger", "polder", "hafen", "marine", "kran",
    }

    def scan(self, opps):
        now = datetime.now(timezone.utc)
        out: list[AgentRecommendation] = []
        for o in opps:
            text = (o.title_normalized + " " + o.description).lower()
            cat_hit = o.category in self.MARITIME_CATEGORIES
            kw_hit = any(k in text for k in self.MARITIME_KEYWORDS)
            if not (cat_hit or kw_hit):
                continue
            if o.type != "POSITIVE_ASSET":
                continue
            distance = pdata.haversine_km(
                o.location.lat, o.location.lon,
                pdata.HOME_DEPOT[2], pdata.HOME_DEPOT[3],
            )
            proximity_bonus = max(0, 30 - distance / 100)  # 30 pts at door, 0 at 3000km
            out.append(AgentRecommendation(
                agent_name=self.name,
                opportunity=o,
                rationale=(f"Maritime Kategorie {o.category}, Standort "
                           f"{o.location.city}, ca. {distance:.0f} km vom Heimathafen. "
                           f"Auktionsende in {(o.auction_end - now).days} Tagen."),
                confidence=min(100, int(o.score * 0.6 + proximity_bonus)),
            ))
        out.sort(key=lambda r: -r.confidence)
        return out[:5]


class Generalist(Specialist):
    name = "Generalist"
    description = "Top-3 nach Gesamt-Score (Handbuch §8.4)."

    def scan(self, opps):
        top = sorted(opps, key=lambda o: -o.score)[:3]
        return [
            AgentRecommendation(
                agent_name=self.name,
                opportunity=o,
                rationale=f"Score {o.score}/100 nach Handbuch-Rubrik.",
                confidence=o.score,
            )
            for o in top
        ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_SPECIALISTS: list[Specialist] = [
    Generalist(),
    BargainHunter(),
    ScrapMaximizer(),
    PreciousMetalsHunter(),
    TritonMaritime(),
]


def run_all(
    opps: list[pdata.Opportunity], record: bool = True
) -> dict[str, list[AgentRecommendation]]:
    """Run every specialist and return ``{agent_name: recommendations}``.

    Applies the bargain learner to each opportunity once at the beginning so
    every specialist sees the learner-corrected score / market value.
    """
    for o in opps:
        o.score, o.score_breakdown = plearner.apply_learning(o)
    return {spec.name: spec.run(opps, record=record) for spec in ALL_SPECIALISTS}
