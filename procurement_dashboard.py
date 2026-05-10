"""Procurement dashboard for the EU public-sector / military / firefighter
surplus opportunity feed.

Run it with:

    streamlit run procurement_dashboard.py

The dashboard has four panels:

  * KPI strip            - portfolio totals (count, est. NAV, # red flags)
  * Filter sidebar       - country / category / type / platform / score
  * Opportunity table    - sortable, click a row to load the detail view
  * Detail drawer        - normalised JSON + score breakdown + map +
                           an embedded chat with the procurement agent
                           pre-loaded with that asset_id.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import procurement_data as pdata


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
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("EU Procurement Intelligence Dashboard")
st.caption(
    "Akquise von Behörden-, Militär-, Feuerwehr- und Wasserbauausrüstung — "
    "Score-getriebene Übersicht aus VEBEG, Zoll-Auktion, Troostwijk, "
    "Domaine, AMW und e-vergabe."
)


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------

opps = pdata.all_opportunities()


def opp_to_row(o: pdata.Opportunity) -> dict:
    days_left = (o.auction_end - datetime.now(timezone.utc)).days
    red_flags = pdata.detect_red_flags(o)
    return {
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


df = pd.DataFrame(opp_to_row(o) for o in opps)


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.header("Filter")

countries = sorted({o.location.country for o in opps})
categories = sorted({o.category for o in opps})
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

st.sidebar.divider()
st.sidebar.subheader("Heimat-Depot")
st.sidebar.write(f"{pdata.HOME_DEPOT[0]}, {pdata.HOME_DEPOT[1]}")
st.sidebar.caption("Logistikkosten werden ab hier berechnet (ca. 2,20 €/km).")


def passes_filters(o: pdata.Opportunity) -> bool:
    if o.location.country not in flt_country:
        return False
    if o.category not in flt_category:
        return False
    if o.source_platform not in flt_platform:
        return False
    if o.type not in flt_type:
        return False
    if o.score < flt_min_score:
        return False
    if flt_keyword:
        blob = (o.title_normalized + " " + o.description).lower()
        if flt_keyword.lower() not in blob:
            return False
    return True


filtered = [o for o in opps if passes_filters(o)]
filtered_ids = [o.asset_id for o in filtered]
df_filtered = df[df["asset_id"].isin(filtered_ids)].sort_values(
    by=["Score", "Tage übrig"], ascending=[False, True]
)


# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Opportunities (gefiltert)", len(filtered))
with col2:
    nav_total = sum(o.net_asset_value for o in filtered if o.type == "POSITIVE_ASSET")
    st.metric("NAV Summe (Positive)", f"{nav_total:,.0f} €".replace(",", "."))
with col3:
    neg_value = sum(
        o.financials.current_bid - o.financials.remediation_cost_estimate
        for o in filtered if o.type == "NEGATIVE_ASSET"
    )
    st.metric("Marge Negative Assets", f"{neg_value:,.0f} €".replace(",", "."))
with col4:
    rf_count = sum(1 for o in filtered if pdata.detect_red_flags(o))
    st.metric("Red-Flag Listings", rf_count)

st.divider()

# ---------------------------------------------------------------------------
# Main two-column layout: list + detail
# ---------------------------------------------------------------------------

left, right = st.columns([1.4, 1])

with left:
    st.subheader("Opportunity-Pipeline")
    if df_filtered.empty:
        st.info("Keine Opportunities passen zum aktuellen Filter.")
    else:
        st.dataframe(
            df_filtered.drop(columns=["asset_id"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
                "Aktuelles Gebot (EUR)": st.column_config.NumberColumn(format="€ %d"),
                "NAV (EUR)": st.column_config.NumberColumn(format="€ %d"),
                "Bid-Limit (EUR)": st.column_config.NumberColumn(format="€ %d"),
            },
        )

        # Map over filtered locations
        st.subheader("Standorte")
        map_df = pd.DataFrame(
            {
                "lat": [o.location.lat for o in filtered],
                "lon": [o.location.lon for o in filtered],
            }
        )
        st.map(map_df, size=20, zoom=3)

        # Selector for the right-hand drawer
        st.subheader("Detailansicht")
        choice = st.selectbox(
            "Asset auswählen",
            df_filtered["asset_id"].tolist(),
            format_func=lambda aid: f"{aid} — {pdata.get(aid).title_normalized}",
        )
        st.session_state["selected_asset"] = choice

with right:
    selected_id = st.session_state.get("selected_asset") or (
        filtered_ids[0] if filtered_ids else None
    )

    if not selected_id:
        st.info("Wähle links ein Asset, um Details zu sehen.")
    else:
        o = pdata.get(selected_id)
        st.markdown(f"### {o.title_normalized}")
        type_chip = "<span class='neg-asset'>NEGATIVE ASSET</span>" \
            if o.type == "NEGATIVE_ASSET" else ""
        st.markdown(
            f"<span class='score-pill'>Score {o.score}</span> "
            f"&nbsp;·&nbsp; **{o.source_platform}** · {o.category} · "
            f"{o.location.city}, {o.location.country} {type_chip}",
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
            cB.metric("Vergütung (WSV)",
                      f"{o.financials.current_bid:,.0f} €".replace(",", "."))
            cC.metric("Geschätzte Sanierungskosten",
                      f"{o.financials.remediation_cost_estimate:,.0f} €".replace(",", "."))

        st.markdown("**Beschreibung**")
        st.write(o.description)

        # Score breakdown bar chart
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

        with st.expander("Vollständiges JSON (Schema Handbuch §8.3)"):
            st.json(pdata.to_dict(o))

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
