"""Procurement dashboard for the EU public-sector / military / firefighter
surplus opportunity feed.

Run it with::

    streamlit run procurement_dashboard.py

Panels:
  * KPI strip            - portfolio totals (count, NAV, alert count)
  * Alert banner         - lists any Score > 80 opportunities w/ deadline
  * Settings sidebar     - home depot, target margin, EUR/km, live/offline
  * Filter sidebar       - country / category / type / platform / score
  * Opportunity table    - sortable, with star/watchlist toggle and CSV export
  * Detail drawer        - normalised JSON + score breakdown + map +
                           embedded chat with the procurement agent
  * Data sources strip   - per-adapter status (Zoll / TED / mock)
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import procurement_data as pdata
import procurement_sources as psources


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="EU Procurement Intelligence",
    page_icon="🛠️",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stAppDeployButton { visibility: hidden; }
    div[data-testid="metric-container"] {
        background: #f6f7fb; padding: 12px; border-radius: 8px;
        border: 1px solid #e1e4eb;
    }
    .red-flag  { color:#b00020; font-weight:600; }
    .score-pill {
        display:inline-block; padding:2px 8px; border-radius:12px;
        background:#1f6feb; color:white; font-weight:600; font-size:0.85em;
    }
    .neg-asset {
        display:inline-block; padding:2px 6px; border-radius:4px;
        background:#fff3cd; color:#664d03; font-size:0.8em;
    }
    .alert-strip {
        background:#fff3cd; border-left:4px solid #f59e0b;
        padding:8px 14px; border-radius:6px; margin-bottom:12px;
    }
    .source-ok    { color:#0a7d33; font-weight:600; }
    .source-fail  { color:#b00020; font-weight:600; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("EU Procurement Intelligence Dashboard")
st.caption(
    "Akquise von Behörden-, Militär-, Feuerwehr- und Wasserbauausrüstung — "
    "Score-getriebene Übersicht aus VEBEG, Zoll-Auktion, Troostwijk, "
    "Domaine, AMW, TED und e-vergabe."
)


# ---------------------------------------------------------------------------
# Persistent settings
# ---------------------------------------------------------------------------

st.sidebar.header("Einstellungen")
target_margin = st.sidebar.slider(
    "Zielmarge (für Bid-Limit)", 0.05, 0.50, 0.25, 0.05,
    help="Sicherheitsabschlag auf den Marktwert. Höher = vorsichtiger.",
)
eur_per_km = st.sidebar.slider(
    "Transportkosten (€/km)", 0.5, 5.0, 2.20, 0.10,
    help="Spezialtransport, Heavy-Haul. Über 5 t kommt +30 % Aufschlag drauf.",
)
live_mode = st.sidebar.toggle(
    "Live-Datenquellen abfragen",
    value=False,
    help="Schaltet Zoll-API + TED zu. Aus = nur die kuratierte Mock-Liste.",
)
st.sidebar.divider()


# ---------------------------------------------------------------------------
# Data load (cached, recomputed on setting changes)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)
def load_opportunities(live: bool, eur_km: float, margin: float):
    """Fetch from all enabled adapters, then re-enrich with current settings."""
    if live:
        adapters = psources.default_adapters()
    else:
        adapters = [psources.MockAdapter()]
    opps, reports = psources.aggregate(adapters)
    # Re-enrich with the user's current logistics + margin settings so the
    # bid-ceiling and NAV reflect the live sliders.
    for o in opps:
        o.logistics_cost_estimate = pdata.estimate_logistics_cost(o, eur_km)
        o.scrap_value_potential = pdata.estimate_scrap_value(o)
        o.score, o.score_breakdown = pdata.score_opportunity(o)
        o.bid_ceiling = pdata.compute_bid_ceiling(o, margin)
        if o.type == "POSITIVE_ASSET":
            o.net_asset_value = round(
                o.financials.estimated_market_value
                - o.financials.current_bid
                - o.logistics_cost_estimate
                - o.financials.repair_opex_estimate
                + o.scrap_value_potential,
                2,
            )
        else:
            o.net_asset_value = round(
                o.financials.current_bid
                - o.financials.remediation_cost_estimate
                + o.scrap_value_potential,
                2,
            )
    return opps, reports


opps, reports = load_opportunities(live_mode, eur_per_km, target_margin)

# ---------------------------------------------------------------------------
# Watchlist (per-session)
# ---------------------------------------------------------------------------

if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = set()


def toggle_watchlist(asset_id: str):
    wl = st.session_state["watchlist"]
    if asset_id in wl:
        wl.remove(asset_id)
    else:
        wl.add(asset_id)


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.header("Filter")

countries = sorted({o.location.country for o in opps if o.location.country})
categories = sorted({o.category for o in opps if o.category})
platforms = sorted({o.source_platform for o in opps})
asset_types = ["POSITIVE_ASSET", "NEGATIVE_ASSET"]

flt_country = st.sidebar.multiselect("Land", countries, default=countries)
flt_category = st.sidebar.multiselect("Kategorie", categories, default=categories)
flt_platform = st.sidebar.multiselect("Plattform", platforms, default=platforms)
flt_type = st.sidebar.multiselect(
    "Asset-Typ", asset_types,
    default=asset_types,
    format_func=lambda x: "Positiv (Erwerb)" if x == "POSITIVE_ASSET" else "Negativ (Mitgift)",
)
flt_min_score = st.sidebar.slider("Mindest-Score", 0, 100, 0, 5)
flt_keyword = st.sidebar.text_input("Stichwort (Titel/Beschreibung)", "")
flt_only_watch = st.sidebar.toggle(
    f"Nur Watchlist ({len(st.session_state['watchlist'])})",
    value=False,
)

st.sidebar.divider()
st.sidebar.subheader("Heimat-Depot")
st.sidebar.write(f"{pdata.HOME_DEPOT[0]}, {pdata.HOME_DEPOT[1]}")
st.sidebar.caption(
    f"Logistik wird ab hier mit {eur_per_km:.2f} €/km berechnet "
    "(+30 % über 5 t)."
)


def passes_filters(o: pdata.Opportunity) -> bool:
    if flt_country and o.location.country not in flt_country:
        return False
    if flt_category and o.category not in flt_category:
        return False
    if flt_platform and o.source_platform not in flt_platform:
        return False
    if flt_type and o.type not in flt_type:
        return False
    if o.score < flt_min_score:
        return False
    if flt_keyword:
        blob = (o.title_normalized + " " + o.description).lower()
        if flt_keyword.lower() not in blob:
            return False
    if flt_only_watch and o.asset_id not in st.session_state["watchlist"]:
        return False
    return True


filtered = [o for o in opps if passes_filters(o)]


# ---------------------------------------------------------------------------
# Alert banner (score > 80, deadline within 14 days)
# ---------------------------------------------------------------------------

now = datetime.now(timezone.utc)
alerts = [
    o for o in opps
    if o.score >= 80 and (o.auction_end - now).days <= 14 and o.auction_end > now
]
if alerts:
    lines = []
    for o in alerts[:5]:
        days_left = (o.auction_end - now).days
        nav = f"{o.net_asset_value:,.0f}".replace(",", ".")
        lines.append(
            f"<li><b>{o.title_normalized}</b> · Score {o.score} · "
            f"NAV {nav} € · noch <b>{days_left} Tage</b> · "
            f"<code>{o.asset_id}</code></li>"
        )
    extra = (f"<br><small>… und {len(alerts) - 5} weitere</small>"
             if len(alerts) > 5 else "")
    st.markdown(
        f"<div class='alert-strip'>"
        f"<b>🔔 {len(alerts)} Hot-Deal Alert(s)</b> — Score ≥ 80, "
        f"Auktion endet in ≤ 14 Tagen:<ul>{''.join(lines)}</ul>{extra}"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Build the dataframe
# ---------------------------------------------------------------------------

def opp_to_row(o: pdata.Opportunity) -> dict:
    days_left = (o.auction_end - now).days
    red_flags = pdata.detect_red_flags(o)
    star = "★" if o.asset_id in st.session_state["watchlist"] else "☆"
    return {
        "★": star,
        "asset_id": o.asset_id,
        "Score": o.score,
        "Titel": o.title_normalized,
        "Typ": "POS" if o.type == "POSITIVE_ASSET" else "NEG",
        "Kategorie": o.category,
        "Plattform": o.source_platform,
        "Land": o.location.country,
        "Stadt": o.location.city,
        "Aktuelles Gebot (EUR)": o.financials.current_bid,
        "NAV (EUR)": o.net_asset_value,
        "Bid-Limit (EUR)": o.bid_ceiling,
        "Tage übrig": days_left,
        "Red Flags": ", ".join(red_flags) if red_flags else "",
    }


df_filtered = (
    pd.DataFrame(opp_to_row(o) for o in filtered)
    .sort_values(by=["Score", "Tage übrig"], ascending=[False, True])
    if filtered else pd.DataFrame()
)


# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Opportunities (gefiltert)", len(filtered))
with col2:
    nav_total = sum(o.net_asset_value for o in filtered if o.type == "POSITIVE_ASSET")
    st.metric("NAV Σ (Positive)", f"{nav_total:,.0f} €".replace(",", "."))
with col3:
    neg_margin = sum(
        o.financials.current_bid - o.financials.remediation_cost_estimate
        for o in filtered if o.type == "NEGATIVE_ASSET"
    )
    st.metric("Marge Σ (Negative)", f"{neg_margin:,.0f} €".replace(",", "."))
with col4:
    st.metric("Hot Deals (Score ≥ 80)", sum(1 for o in filtered if o.score >= 80))

st.divider()

# ---------------------------------------------------------------------------
# Main two-column layout
# ---------------------------------------------------------------------------

left, right = st.columns([1.4, 1])

with left:
    header_col, export_col = st.columns([3, 1])
    header_col.subheader("Opportunity-Pipeline")
    if not df_filtered.empty:
        csv_buf = io.StringIO()
        df_filtered.drop(columns=["asset_id", "★"]).to_csv(
            csv_buf, index=False, sep=";", decimal=","
        )
        export_col.download_button(
            "CSV exportieren",
            csv_buf.getvalue().encode("utf-8-sig"),
            file_name=f"procurement_pipeline_{now:%Y%m%d_%H%M}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if df_filtered.empty:
        st.info("Keine Opportunities passen zum aktuellen Filter.")
    else:
        st.dataframe(
            df_filtered.drop(columns=["asset_id"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "★": st.column_config.TextColumn(width="small"),
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
                "Aktuelles Gebot (EUR)": st.column_config.NumberColumn(format="€ %d"),
                "NAV (EUR)": st.column_config.NumberColumn(format="€ %d"),
                "Bid-Limit (EUR)": st.column_config.NumberColumn(format="€ %d"),
            },
        )

        # Map
        st.subheader("Standorte")
        map_df = pd.DataFrame(
            {
                "lat": [o.location.lat for o in filtered if o.location.lat],
                "lon": [o.location.lon for o in filtered if o.location.lon],
            }
        )
        if not map_df.empty:
            st.map(map_df, size=20, zoom=3)

        # Detail selector + watchlist button
        st.subheader("Detailansicht")
        sel_col, watch_col = st.columns([4, 1])
        choice = sel_col.selectbox(
            "Asset auswählen",
            df_filtered["asset_id"].tolist(),
            format_func=lambda aid: (
                ("★ " if aid in st.session_state["watchlist"] else "")
                + f"{aid} — {pdata.get(aid).title_normalized if pdata.get(aid) else aid}"
            ),
        )
        st.session_state["selected_asset"] = choice
        in_watch = choice in st.session_state["watchlist"]
        if watch_col.button(
            "★ Watchlist entfernen" if in_watch else "☆ Watchlist hinzufügen",
            use_container_width=True,
        ):
            toggle_watchlist(choice)
            st.rerun()

with right:
    selected_id = st.session_state.get("selected_asset")
    o = pdata.get(selected_id) if selected_id else None
    if o is None and filtered:
        o = filtered[0]

    if o is None:
        st.info("Wähle links ein Asset, um Details zu sehen.")
    else:
        st.markdown(f"### {o.title_normalized}")
        type_chip = "<span class='neg-asset'>NEGATIVE ASSET</span>" \
            if o.type == "NEGATIVE_ASSET" else ""
        st.markdown(
            f"<span class='score-pill'>Score {o.score}</span> "
            f"&nbsp;·&nbsp; **{o.source_platform}** · {o.category} · "
            f"{o.location.city or '—'}, {o.location.country} {type_chip}",
            unsafe_allow_html=True,
        )
        st.markdown(f"[Listing öffnen]({o.listing_url})")

        cA, cB, cC = st.columns(3)
        cA.metric("Aktuelles Gebot",
                  f"{o.financials.current_bid:,.0f} €".replace(",", "."))
        if o.type == "POSITIVE_ASSET":
            cB.metric("Bid-Limit",
                      f"{o.bid_ceiling:,.0f} €".replace(",", "."))
            cC.metric("Net Asset Value",
                      f"{o.net_asset_value:,.0f} €".replace(",", "."))
        else:
            cB.metric("Vergütung (Auftraggeber)",
                      f"{o.financials.current_bid:,.0f} €".replace(",", "."))
            cC.metric("Geschätzte Sanierungskosten",
                      f"{o.financials.remediation_cost_estimate:,.0f} €".replace(",", "."))

        st.markdown("**Beschreibung**")
        st.write(o.description)

        # Score breakdown
        st.markdown("**Score-Breakdown**")
        bd = o.score_breakdown
        if bd:
            st.bar_chart(pd.DataFrame({"Punkte": bd}))
        else:
            st.write("(keine Daten)")

        # Risk badges
        red = pdata.detect_red_flags(o)
        dual = pdata.detect_dual_use(o)
        chips = []
        if red:
            chips.append(
                f"<span class='red-flag'>Red Flags: {', '.join(red)}</span>"
            )
        if dual:
            chips.append(
                "<span class='red-flag'>Dual-Use / BAFA-Pflicht prüfen</span>"
            )
        if o.risk_factors.pre_1990_vessel:
            chips.append(
                "<span class='red-flag'>Pre-1990-Schiff (Asbestrisiko)</span>"
            )
        if not chips:
            chips.append("Keine kritischen Risiken erkannt.")
        st.markdown("**Risiko**<br>" + "<br>".join(chips), unsafe_allow_html=True)

        # Bid-ceiling math (transparent)
        with st.expander("Bid-Limit Herleitung (Handbuch §9)"):
            if o.type == "POSITIVE_ASSET":
                st.write({
                    "Marktwert": o.financials.estimated_market_value,
                    "- Logistik": -o.logistics_cost_estimate,
                    "- Reparatur OPEX": -o.financials.repair_opex_estimate,
                    f"- Zielmarge ({target_margin*100:.0f}%)":
                        -target_margin * o.financials.estimated_market_value,
                    "+ Schrott-Credit": o.scrap_value_potential,
                    "= Bid-Limit": o.bid_ceiling,
                })
            else:
                st.write({
                    "Geschätzte Sanierungskosten": o.financials.remediation_cost_estimate,
                    "- Schrott-Credit": -o.scrap_value_potential,
                    f"+ Zielmarge ({target_margin*100:.0f}%)":
                        target_margin * o.financials.remediation_cost_estimate,
                    "= Angebotspreis (Mindestvergütung)": o.bid_ceiling,
                })

        with st.expander("Vollständiges JSON (Schema Handbuch §8.3)"):
            st.json(pdata.to_dict(o))

st.divider()


# ---------------------------------------------------------------------------
# Data sources status strip
# ---------------------------------------------------------------------------

st.subheader("Datenquellen")
src_cols = st.columns(len(reports) or 1)
for col, rep in zip(src_cols, reports):
    cls = "source-ok" if not rep.error else "source-fail"
    label = "OK" if not rep.error else "Fehler"
    detail = f"{rep.count} Treffer" if not rep.error else (rep.error[:80] + "…")
    col.markdown(
        f"**{rep.adapter_name}** ({rep.platform})  \n"
        f"<span class='{cls}'>{label}</span> — {detail}",
        unsafe_allow_html=True,
    )

st.divider()


# ---------------------------------------------------------------------------
# Embedded chat with the procurement agent (lazy-imported so the dashboard
# still works for users without a DEEPSEEK_API_KEY).
# ---------------------------------------------------------------------------

st.subheader("Chat mit dem Procurement Agent")

if "agent" not in st.session_state:
    try:
        from procurement_agent import Agent  # type: ignore
        st.session_state["agent"] = Agent()
        st.session_state["agent_error"] = None
    except Exception as exc:  # noqa: BLE001
        st.session_state["agent"] = None
        st.session_state["agent_error"] = str(exc)

if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []

if st.session_state.get("agent_error"):
    st.warning(
        "Procurement Agent konnte nicht geladen werden: "
        f"{st.session_state['agent_error']}\n\n"
        "Trage einen `DEEPSEEK_API_KEY` in `.env` ein und starte das "
        "Dashboard neu, um den Chat zu aktivieren. "
        "Key kostenlos unter https://platform.deepseek.com erhältlich."
    )
elif st.session_state["agent"] is None:
    st.info("Agent nicht verfügbar.")
else:
    for msg in st.session_state["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    placeholder = (
        f"Frag z.B.: 'Ist {st.session_state.get('selected_asset','VEBEG-2026-0142')} "
        "wirtschaftlich sinnvoll?'"
        if st.session_state.get("selected_asset")
        else "Frag z.B.: 'Zeig mir die Top-3 Pumpen mit Score > 70.'"
    )

    if user_msg := st.chat_input(placeholder):
        st.session_state["chat_messages"].append(
            {"role": "user", "content": user_msg}
        )
        with st.chat_message("user"):
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            with st.spinner("Agent denkt nach …"):
                reply = st.session_state["agent"].chat(user_msg)
            st.markdown(reply)
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": reply}
        )

    if st.button("Chat zurücksetzen"):
        st.session_state["agent"].clear_chat()
        st.session_state["chat_messages"] = []
        st.rerun()
