"""Procurement Intelligence Agent (Anthropic Claude).

Implements the autonomous "Procurement Agent" described in the strategic
handbook on the acquisition of military / firefighter / waterworks equipment
in Europe (sections 8.3, 8.4 and 9 of the source document).

The agent re-uses the common interface from this repository
(`Agent.name`, `Agent.chat`, `Agent.clear_chat`) so it plugs into the
shared Streamlit chat UI as well as the dedicated procurement dashboard.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

import anthropic
from dotenv import load_dotenv

from procurement_prompts import role, goal, instructions, knowledge
import procurement_data as pdata

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEFAULT_MODEL = os.getenv("PROCUREMENT_MODEL", "claude-opus-4-7")


class Agent:
    """A Claude-driven procurement agent specialised in EU public-sector
    surplus equipment auctions and paid-disposal tenders."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.name = "Procurement Agent (DE/EU)"
        self.model = model
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.messages: list[dict] = []
        self.system_prompt = "\n".join([role, goal, instructions, knowledge])

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_current_date() -> str:
        return date.today().strftime("%Y-%m-%d")

    @staticmethod
    def _tool_list_opportunities(
        category: str | None = None,
        country: str | None = None,
        type_: str | None = None,
        platform: str | None = None,
        min_score: int | None = None,
        keyword: str | None = None,
        limit: int = 10,
    ) -> str:
        hits = pdata.search(
            category=category,
            country=country,
            type_=type_,
            platform=platform,
            min_score=min_score,
            keyword=keyword,
        )[:limit]
        return json.dumps(
            [
                {
                    "asset_id": o.asset_id,
                    "title": o.title_normalized,
                    "platform": o.source_platform,
                    "country": o.location.country,
                    "city": o.location.city,
                    "type": o.type,
                    "category": o.category,
                    "current_bid": o.financials.current_bid,
                    "estimated_market_value": o.financials.estimated_market_value,
                    "score": o.score,
                    "net_asset_value": o.net_asset_value,
                    "auction_end": o.auction_end.isoformat(),
                }
                for o in hits
            ],
            ensure_ascii=False,
        )

    @staticmethod
    def _tool_get_opportunity(asset_id: str) -> str:
        opp = pdata.get(asset_id)
        if not opp:
            return json.dumps({"error": f"asset_id {asset_id} not found"})
        return json.dumps(pdata.to_dict(opp), ensure_ascii=False)

    @staticmethod
    def _tool_score_opportunity(asset_id: str) -> str:
        opp = pdata.get(asset_id)
        if not opp:
            return json.dumps({"error": f"asset_id {asset_id} not found"})
        # re-run on current state (handy after the user tweaks bid in tests)
        score, breakdown = pdata.score_opportunity(opp)
        return json.dumps(
            {
                "asset_id": asset_id,
                "score": score,
                "breakdown": breakdown,
                "bid_ceiling_eur": opp.bid_ceiling,
                "net_asset_value_eur": opp.net_asset_value,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _tool_scrap_value(asset_id: str) -> str:
        opp = pdata.get(asset_id)
        if not opp:
            return json.dumps({"error": f"asset_id {asset_id} not found"})
        return json.dumps(
            {
                "asset_id": asset_id,
                "scrap_material": opp.financials.scrap_material,
                "weight_kg": opp.financials.weight_kg,
                "eur_per_tonne": pdata.SCRAP_PRICES_EUR_PER_TONNE.get(
                    opp.financials.scrap_material or "", None
                ),
                "scrap_value_eur": opp.scrap_value_potential,
            }
        )

    @staticmethod
    def _tool_logistics_estimate(asset_id: str) -> str:
        opp = pdata.get(asset_id)
        if not opp:
            return json.dumps({"error": f"asset_id {asset_id} not found"})
        distance_km = pdata.haversine_km(
            opp.location.lat, opp.location.lon,
            pdata.HOME_DEPOT[2], pdata.HOME_DEPOT[3],
        )
        return json.dumps(
            {
                "asset_id": asset_id,
                "from": f"{opp.location.city}, {opp.location.country}",
                "to": f"{pdata.HOME_DEPOT[0]}, {pdata.HOME_DEPOT[1]}",
                "distance_km": round(distance_km, 1),
                "logistics_cost_eur": opp.logistics_cost_estimate,
            }
        )

    @staticmethod
    def _tool_dual_use_check(asset_id: str) -> str:
        opp = pdata.get(asset_id)
        if not opp:
            return json.dumps({"error": f"asset_id {asset_id} not found"})
        suspected = pdata.detect_dual_use(opp)
        red_flags = pdata.detect_red_flags(opp)
        return json.dumps(
            {
                "asset_id": asset_id,
                "dual_use_suspected": suspected,
                "export_control_flagged_in_listing": opp.risk_factors.export_control,
                "red_flags": red_flags,
                "guidance": (
                    "Sale to non-EU buyers requires BAFA approval per "
                    "Außenwirtschaftsgesetz. Domestic sale is unrestricted "
                    "but advise buyer of dual-use status."
                    if suspected else
                    "No dual-use indicators detected. Standard EU sale."
                ),
            },
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Tool plumbing for the Anthropic Messages API
    # ------------------------------------------------------------------

    def _tool_specs(self) -> list[dict]:
        return [
            {
                "name": "current_date",
                "description": "Get today's date (UTC). Use it to compute days "
                               "until an auction deadline.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "list_opportunities",
                "description": "Search the procurement opportunity database. "
                               "All filters are optional. Returns the top "
                               "matches sorted by attractiveness score "
                               "(descending) then earliest auction end.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "e.g. MARITIME_PUMP, MILITARY_TRUCK, "
                                           "FIRE_TRUCK, WATERWORKS, "
                                           "MARITIME_CRANE, GENERATOR, PSA, "
                                           "WRECK_REMOVAL, "
                                           "WATERWORKS_DECONSTRUCTION",
                        },
                        "country": {
                            "type": "string",
                            "description": "ISO-2 country code (DE, FR, NL, PL, ...)",
                        },
                        "type_": {
                            "type": "string",
                            "enum": ["POSITIVE_ASSET", "NEGATIVE_ASSET"],
                        },
                        "platform": {
                            "type": "string",
                            "description": "VEBEG, ZOLL, TROOSTWIJK, DOMAINE, "
                                           "AMW, E-VERGABE",
                        },
                        "min_score": {
                            "type": "integer",
                            "description": "Only return opportunities with score >= this",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "Free-text search inside title and description",
                        },
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                },
            },
            {
                "name": "get_opportunity",
                "description": "Fetch the full normalised JSON record for a "
                               "single opportunity (handbook section 8.3 "
                               "schema).",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                },
            },
            {
                "name": "score_opportunity",
                "description": "Re-run the 0-100 attractiveness scorer for an "
                               "opportunity and return the per-factor "
                               "breakdown plus the recommended bid ceiling.",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                },
            },
            {
                "name": "scrap_value",
                "description": "Compute the LME-based scrap credit (EUR) for "
                               "an opportunity's metal content.",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                },
            },
            {
                "name": "logistics_estimate",
                "description": "Distance- and weight-aware heavy-haul "
                               "transport cost estimate from the asset's "
                               "pickup location to the home depot.",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                },
            },
            {
                "name": "dual_use_check",
                "description": "Flag potential BAFA / EU dual-use export "
                               "control risk for the asset and suggest the "
                               "compliant sale path.",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                },
            },
        ]

    def _dispatch(self, name: str, args: dict) -> str:
        try:
            if name == "current_date":
                return self._tool_current_date()
            if name == "list_opportunities":
                return self._tool_list_opportunities(**args)
            if name == "get_opportunity":
                return self._tool_get_opportunity(**args)
            if name == "score_opportunity":
                return self._tool_score_opportunity(**args)
            if name == "scrap_value":
                return self._tool_scrap_value(**args)
            if name == "logistics_estimate":
                return self._tool_logistics_estimate(**args)
            if name == "dual_use_check":
                return self._tool_dual_use_check(**args)
            return json.dumps({"error": f"unknown tool {name}"})
        except TypeError as exc:
            return json.dumps({"error": f"bad arguments: {exc}"})

    # ------------------------------------------------------------------
    # Public chat interface
    # ------------------------------------------------------------------

    def chat(self, message: str) -> str:
        self.messages.append({"role": "user", "content": message})
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=self._tool_specs(),
                messages=self.messages,
            )

            while response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._dispatch(block.name, block.input or {})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                self.messages.append({"role": "assistant", "content": response.content})
                self.messages.append({"role": "user", "content": tool_results})

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=self._tool_specs(),
                    messages=self.messages,
                )

            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            answer = "\n".join(text_blocks).strip() or "(keine Antwort)"
            self.messages.append({"role": "assistant", "content": answer})
            return answer

        except anthropic.APIError as exc:
            return f"Anthropic API-Fehler: {exc}"
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            return f"Fehler im Procurement Agent: {exc}"

    def clear_chat(self) -> bool:
        self.messages = []
        return True


def main() -> None:
    agent = Agent()
    print(f"{agent.name} bereit. 'exit' zum Beenden.\n")
    while True:
        query = input("Sie: ").strip()
        if not query or query.lower() == "exit":
            break
        print(f"Agent: {agent.chat(query)}\n")


if __name__ == "__main__":
    main()
