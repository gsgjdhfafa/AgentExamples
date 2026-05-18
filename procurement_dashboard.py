"""EU Procurement Intelligence Dashboard.

Multi-tab Streamlit app for monitoring opportunities and the specialist
agents that surface them.

Tabs:

  1. **Hot Deals**     - one card per top recommendation across all specialist
                         agents. The operator decides JA / NEIN / SPAETER per
                         asset. Decisions are persisted to SQLite and feed the
                         bargain learner.
  2. **Pipeline**      - full filterable / sortable list with map, detail
                         drawer, CSV export and the bid-ceiling derivation.
  3. **Agent-Monitor** - live status of every specialist (last run, found,
                         hot count, top pick) + run history.
  4. **Lerner**        - what the bargain learner currently believes per
                         category, with sample counts.
  5. **Alerts**        - threshold settings, send-test-alert buttons and
                         dispatch reports per channel.
  6. **Chat**          - free-form chat with the DeepSeek-backed agent that
                         can hit all the procurement tools.

Launch with::

    streamlit run procurement_dashboard.py
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import procurement_agents as pagents
import procurement_alerts as palerts
import procurement_data as pdata
import procurement_drive as pdrive
import procurement_learner as plearner
import procurement_letters as pletters
import procurement_pdf as ppdf
import procurement_sources as psources
import procurement_store as pstore
import procurement_today as ptoday


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
    .agent-card {
        background: #f8f9fc; border:1px solid #e1e4eb; border-radius:8px;
        padding:14px; margin-bottom:14px;
    }
    .verdict-yes  { color:#0a7d33; font-weight:600; }
    .verdict-no   { color:#b00020; font-weight:600; }
    .verdict-later { color:#8a6d3b; font-weight:600; }
    .source-ok    { color:#0a7d33; font-weight:600; }
    .source-fail  { color:#b00020; font-weight:600; }
    /* Hotkey help overlay */
    #procurement-hotkey-overlay {
        position: fixed; inset: 0; background: rgba(8,12,24,0.78);
        display: none; align-items: center; justify-content: center;
        z-index: 9999;
    }
    #procurement-hotkey-overlay .panel {
        background: #1b2236; color: #f0f4fc;
        border: 1px solid #3a4666; border-radius: 12px;
        padding: 28px 36px; min-width: 480px; max-width: 640px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        font-family: ui-sans-serif, system-ui, sans-serif;
    }
    #procurement-hotkey-overlay h2 {
        margin: 0 0 14px 0; color: #5aa8ff; font-size: 1.4em;
    }
    #procurement-hotkey-overlay table { border-collapse: collapse; width: 100%; }
    #procurement-hotkey-overlay td { padding: 6px 8px; vertical-align: middle; }
    #procurement-hotkey-overlay kbd {
        display: inline-block; min-width: 38px; padding: 4px 10px;
        background: #28304c; border: 1px solid #6e82b4; border-radius: 6px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-weight: 700; text-align: center; color: #f0f4fc;
    }
    #procurement-hotkey-overlay .hint {
        margin-top: 14px; font-size: 0.85em; color: #a0aec8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# Hotkey bindings + help overlay. Injected once, guarded against re-runs.
st.markdown(
    """
<div id="procurement-hotkey-overlay">
  <div class="panel">
    <h2>⌨ Hotkeys</h2>
    <table>
      <tr><td><kbd>1</kbd>–<kbd>8</kbd></td><td>Tab wechseln (Heute · Hot Deals · Pipeline · Monitor · Lerner · Alerts · Chat · Briefe-Triage)</td></tr>
      <tr><td><kbd>J</kbd></td><td>Ja / ✅ Okay — auf Hot Deals: kaufen, auf Briefe: in Ordnung</td></tr>
      <tr><td><kbd>N</kbd></td><td>Nein / ❌ Widerspruch — verwerfen bzw. Entwurf erstellen</td></tr>
      <tr><td><kbd>L</kbd></td><td>Später — Watchlist / Wiedervorlage</td></tr>
      <tr><td><kbd>W</kbd></td><td>Top-Entwurf im Postausgang senden (nur Briefe-Triage)</td></tr>
      <tr><td><kbd>/</kbd></td><td>Stichwort-Filter fokussieren (Pipeline-Tab)</td></tr>
      <tr><td><kbd>S</kbd></td><td>Spezialisten neu scannen (Hot Deals)</td></tr>
      <tr><td><kbd>E</kbd></td><td>CSV exportieren</td></tr>
      <tr><td><kbd>R</kbd></td><td>Dashboard reloaden</td></tr>
      <tr><td><kbd>?</kbd> / <kbd>H</kbd></td><td>Diese Hilfe ein/aus</td></tr>
      <tr><td><kbd>Esc</kbd></td><td>Hilfe schliessen</td></tr>
    </table>
    <div class="hint">Hotkeys feuern nur, wenn kein Eingabefeld fokussiert ist.</div>
  </div>
</div>
<script>
(function () {
  const NS = "__procurement_hotkeys_v1__";
  if (window[NS]) return;
  window[NS] = true;

  const overlay = () => document.getElementById("procurement-hotkey-overlay");
  const showHelp = () => { const o = overlay(); if (o) o.style.display = "flex"; };
  const hideHelp = () => { const o = overlay(); if (o) o.style.display = "none"; };
  const helpVisible = () => {
    const o = overlay();
    return o && getComputedStyle(o).display !== "none";
  };

  // Click first <button> whose visible text matches the predicate. Returns true on hit.
  function clickButton(predicate) {
    const buttons = Array.from(document.querySelectorAll("button"));
    const hit = buttons.find(b => {
      // skip hidden buttons (e.g. inactive tabs keep content in DOM but hidden)
      if (b.offsetParent === null) return false;
      const text = (b.innerText || b.textContent || "").trim();
      return predicate(text);
    });
    if (hit) { hit.click(); return true; }
    return false;
  }

  function activeTabName() {
    const t = document.querySelector('button[role="tab"][aria-selected="true"]');
    return t ? (t.innerText || "").trim() : "";
  }

  function selectTab(index) {
    const tabs = Array.from(document.querySelectorAll('button[role="tab"]'));
    if (tabs.length >= index) tabs[index - 1].click();
  }

  document.addEventListener("keydown", function (ev) {
    // never hijack when typing
    const tag = (ev.target.tagName || "").toLowerCase();
    if (ev.isComposing || tag === "input" || tag === "textarea" ||
        ev.target.isContentEditable) {
      if (ev.key === "Escape" && helpVisible()) hideHelp();
      return;
    }

    const k = ev.key;

    // Help toggle / close (works everywhere)
    if (k === "?" || k === "h" || k === "H") {
      ev.preventDefault();
      helpVisible() ? hideHelp() : showHelp();
      return;
    }
    if (k === "Escape") { hideHelp(); return; }

    // Numeric tabs
    if (k >= "1" && k <= "8") {
      ev.preventDefault();
      selectTab(parseInt(k, 10));
      return;
    }

    // Ja / Nein / Spaeter — Hot Deals OR Briefe-Triage tab
    const tab = activeTabName();
    const onHotDeals = tab.includes("Hot Deals");
    const onBriefe = tab.includes("Briefe");
    const onCardTab = onHotDeals || onBriefe;

    if (k === "j" || k === "J") {
      if (onCardTab) { ev.preventDefault(); clickButton(t => t.startsWith("✅")); }
      return;
    }
    if (k === "n" || k === "N") {
      if (onCardTab) { ev.preventDefault(); clickButton(t => t.startsWith("❌")); }
      return;
    }
    if (k === "l" || k === "L") {
      if (onCardTab) { ev.preventDefault(); clickButton(t => t.startsWith("⏳")); }
      return;
    }
    if (k === "w" || k === "W") {
      if (onBriefe) {
        ev.preventDefault();
        clickButton(t => t.includes("Jetzt senden"));
      }
      return;
    }

    if (k === "s" || k === "S") {
      if (onHotDeals) {
        ev.preventDefault();
        clickButton(t => t.includes("Spezialisten jetzt scannen"));
      }
      return;
    }

    if (k === "e" || k === "E") {
      ev.preventDefault();
      clickButton(t => t.includes("CSV exportieren") ||
                       t.includes("Entscheidungen als CSV"));
      return;
    }

    if (k === "r" || k === "R") {
      ev.preventDefault();
      window.location.reload();
      return;
    }

    if (k === "/") {
      ev.preventDefault();
      const inp = document.querySelector('input[aria-label*="Stichwort"]');
      if (inp) inp.focus();
      return;
    }
  });

  // Click outside the help panel = close
  document.addEventListener("click", function (ev) {
    const o = overlay();
    if (!o || !helpVisible()) return;
    if (ev.target === o) hideHelp();
  });
})();
</script>
    """,
    unsafe_allow_html=True,
)

st.title("EU Procurement Intelligence Dashboard")
st.caption(
    "Akquise von Behörden-, Militär-, Feuerwehr-, Wasserbau- und "
    "Edelmetall-Beständen — Score-getriebene Übersicht aus VEBEG, "
    "Zoll-Auktion, Troostwijk, Domaine, AMW, TED, e-vergabe, NetBid, "
    "Surplex und Fornæs.   ⌨ Hotkeys: `?` für Hilfe, `1`–`6` für Tabs, "
    "`J/N/L` für Ja/Nein/Später."
)


# ---------------------------------------------------------------------------
# Sidebar - global settings (apply to every tab)
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
hot_score = st.sidebar.slider(
    "Hot-Deal-Schwelle (Score)", 50, 100, 80, 5,
    help="Score ab dem ein Asset im Hot-Deals Tab erscheint und Alerts auslöst.",
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
    if live:
        adapters = psources.default_adapters()
    else:
        adapters = [psources.MockAdapter()]
    opps, reports = psources.aggregate(adapters)
    for o in opps:
        o.logistics_cost_estimate = pdata.estimate_logistics_cost(o, eur_km)
        o.scrap_value_potential = pdata.estimate_scrap_value(o)
        # learner adjusts both market value (in place) and score
        o.score, o.score_breakdown = plearner.apply_learning(o)
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
now = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = set()


# ---------------------------------------------------------------------------
# Top KPI strip (always visible)
# ---------------------------------------------------------------------------

k1, k2, k3, k4, k5 = st.columns(5)
positive = [o for o in opps if o.type == "POSITIVE_ASSET"]
negative = [o for o in opps if o.type == "NEGATIVE_ASSET"]
hot = [o for o in opps if o.score >= hot_score and o.auction_end > now]

with k1: st.metric("Opportunities (Inventar)", len(opps))
with k2: st.metric("Hot Deals (Score ≥ %d)" % hot_score, len(hot))
with k3:
    st.metric("NAV Σ (Positive)",
              f"{sum(o.net_asset_value for o in positive):,.0f} €".replace(",", "."))
with k4:
    decisions = pstore.all_decisions()
    yes_n = sum(1 for d in decisions if d.verdict == "YES")
    st.metric("Bestätigte Käufe", yes_n)
with k5:
    runs = pstore.recent_runs(50)
    st.metric("Agent-Läufe gesamt", len(runs))

st.divider()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

(
    tab_today,
    tab_hot,
    tab_pipeline,
    tab_monitor,
    tab_learn,
    tab_alerts,
    tab_chat,
    tab_briefe,
) = st.tabs([
    "📅 Heute",
    "🔥 Hot Deals",
    "📋 Pipeline",
    "🤖 Agent-Monitor",
    "🧠 Lerner",
    "🔔 Alerts",
    "💬 Chat",
    "📨 Briefe-Triage",
])


# ---------------------------------------------------------------------------
# TAB 1 - Hot Deals: one card per agent recommendation, JA/NEIN/SPAETER
# ---------------------------------------------------------------------------

with tab_hot:
    st.markdown(
        "Jede Karte ist die Top-Empfehlung eines Spezialisten. "
        "Klicke **Ja** zum Kaufen-Markieren, **Nein** zum Verwerfen, "
        "**Später** für die Watchlist. Entscheidungen trainieren den Lerner."
    )

    if st.button("Spezialisten jetzt scannen", type="primary"):
        st.cache_data.clear()  # so the next render re-runs the load
        results_run = pagents.run_all(opps, record=True)
        st.session_state["agent_results"] = results_run
        st.success(f"{sum(len(r) for r in results_run.values())} "
                   "Empfehlungen aus 5 Spezialisten.")
    else:
        # Fresh run for the current opps (not recorded so no log spam)
        if "agent_results" not in st.session_state:
            st.session_state["agent_results"] = pagents.run_all(
                opps, record=False
            )

    results = st.session_state["agent_results"]

    # Render: one expander per agent with up to 3 cards
    for agent_name, recs in results.items():
        spec = next(s for s in pagents.ALL_SPECIALISTS if s.name == agent_name)
        with st.expander(
            f"**{agent_name}** — {spec.description}  "
            f"·  {len(recs)} Empfehlung(en)",
            expanded=(agent_name == "Generalist"),
        ):
            if not recs:
                st.info("Aktuell keine passenden Lots.")
                continue
            for rec in recs[:3]:
                o = rec.opportunity
                existing = pstore.get_decision(o.asset_id)
                with st.container(border=True):
                    a, b = st.columns([3, 1])
                    a.markdown(
                        f"#### {o.title_normalized}  "
                        f"<span class='score-pill'>Score {o.score}</span>",
                        unsafe_allow_html=True,
                    )
                    if existing:
                        cls = {"YES": "verdict-yes", "NO": "verdict-no",
                               "LATER": "verdict-later"}[existing.verdict]
                        b.markdown(
                            f"<span class='{cls}'>Entscheidung: "
                            f"{existing.verdict}</span>",
                            unsafe_allow_html=True,
                        )
                    a.write(f"**{o.source_platform}** · {o.category} · "
                            f"{o.location.city}, {o.location.country} · "
                            f"Auktion endet {o.auction_end:%d.%m.%Y %H:%M}")
                    a.write(f"_{rec.rationale}_")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Aktuelles Gebot",
                              f"{o.financials.current_bid:,.0f} €".replace(",", "."))
                    m2.metric("Bid-Limit",
                              f"{o.bid_ceiling:,.0f} €".replace(",", "."))
                    m3.metric("Net Asset Value",
                              f"{o.net_asset_value:,.0f} €".replace(",", "."))
                    m4.metric("Confidence", f"{rec.confidence}/100")

                    risks = pdata.detect_red_flags(o)
                    if risks or pdata.detect_dual_use(o):
                        flags = ", ".join(risks) or ""
                        if pdata.detect_dual_use(o):
                            flags = (flags + ", " if flags else "") + "Dual-Use"
                        st.markdown(f"<span class='red-flag'>⚠ {flags}</span>",
                                    unsafe_allow_html=True)

                    btn1, btn2, btn3, btn4 = st.columns(4)
                    if btn1.button("✅ Ja", key=f"yes_{agent_name}_{o.asset_id}"):
                        pstore.record_decision(
                            o.asset_id, "YES",
                            category=o.category, score=o.score,
                            net_value=o.net_asset_value,
                            rationale=rec.rationale,
                        )
                        st.rerun()
                    if btn2.button("❌ Nein", key=f"no_{agent_name}_{o.asset_id}"):
                        pstore.record_decision(
                            o.asset_id, "NO",
                            category=o.category, score=o.score,
                            net_value=o.net_asset_value,
                            rationale=rec.rationale,
                        )
                        st.rerun()
                    if btn3.button("⏳ Später",
                                   key=f"later_{agent_name}_{o.asset_id}"):
                        pstore.record_decision(
                            o.asset_id, "LATER",
                            category=o.category, score=o.score,
                            net_value=o.net_asset_value,
                            rationale=rec.rationale,
                        )
                        st.session_state["watchlist"].add(o.asset_id)
                        st.rerun()
                    btn4.link_button("🔗 Listing", o.listing_url)


# ---------------------------------------------------------------------------
# TAB 2 - Pipeline (sortable table + map + detail drawer + CSV export)
# ---------------------------------------------------------------------------

with tab_pipeline:
    st.subheader("Filter")
    fc1, fc2, fc3, fc4 = st.columns(4)
    countries = sorted({o.location.country for o in opps if o.location.country})
    categories = sorted({o.category for o in opps if o.category})
    platforms = sorted({o.source_platform for o in opps})
    asset_types = ["POSITIVE_ASSET", "NEGATIVE_ASSET"]

    flt_country = fc1.multiselect("Land", countries, default=countries)
    flt_category = fc2.multiselect("Kategorie", categories, default=categories)
    flt_platform = fc3.multiselect("Plattform", platforms, default=platforms)
    flt_type = fc4.multiselect(
        "Asset-Typ", asset_types,
        default=asset_types,
        format_func=lambda x: "Positiv" if x == "POSITIVE_ASSET" else "Negativ",
    )

    g1, g2, g3 = st.columns([2, 2, 1])
    flt_min_score = g1.slider("Mindest-Score", 0, 100, 0, 5)
    flt_keyword = g2.text_input("Stichwort (Titel/Beschreibung)", "")
    flt_only_watch = g3.toggle(
        f"Watchlist ({len(st.session_state['watchlist'])})", value=False,
    )

    def passes(o):
        if flt_country and o.location.country not in flt_country: return False
        if flt_category and o.category not in flt_category: return False
        if flt_platform and o.source_platform not in flt_platform: return False
        if flt_type and o.type not in flt_type: return False
        if o.score < flt_min_score: return False
        if flt_keyword:
            blob = (o.title_normalized + " " + o.description).lower()
            if flt_keyword.lower() not in blob: return False
        if flt_only_watch and o.asset_id not in st.session_state["watchlist"]:
            return False
        return True

    filtered = [o for o in opps if passes(o)]

    def opp_to_row(o):
        days_left = (o.auction_end - now).days
        return {
            "★": "★" if o.asset_id in st.session_state["watchlist"] else "☆",
            "asset_id": o.asset_id,
            "Score": o.score,
            "Titel": o.title_normalized,
            "Typ": "POS" if o.type == "POSITIVE_ASSET" else "NEG",
            "Kategorie": o.category,
            "Plattform": o.source_platform,
            "Land": o.location.country,
            "Stadt": o.location.city,
            "Gebot (€)": o.financials.current_bid,
            "NAV (€)": o.net_asset_value,
            "Bid-Limit (€)": o.bid_ceiling,
            "Tage": days_left,
            "Red Flags": ", ".join(pdata.detect_red_flags(o)),
        }

    df_filtered = (
        pd.DataFrame(opp_to_row(o) for o in filtered)
        .sort_values(by=["Score", "Tage"], ascending=[False, True])
        if filtered else pd.DataFrame()
    )

    if df_filtered.empty:
        st.info("Keine Opportunities im Filter.")
    else:
        st.dataframe(
            df_filtered.drop(columns=["asset_id"]),
            use_container_width=True, hide_index=True,
            column_config={
                "★": st.column_config.TextColumn(width="small"),
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"),
                "Gebot (€)": st.column_config.NumberColumn(format="€ %d"),
                "NAV (€)": st.column_config.NumberColumn(format="€ %d"),
                "Bid-Limit (€)": st.column_config.NumberColumn(format="€ %d"),
            },
        )
        cbuf = io.StringIO()
        df_filtered.drop(columns=["asset_id", "★"]).to_csv(
            cbuf, index=False, sep=";", decimal=",")
        st.download_button(
            "CSV exportieren",
            cbuf.getvalue().encode("utf-8-sig"),
            file_name=f"procurement_pipeline_{now:%Y%m%d_%H%M}.csv",
            mime="text/csv",
        )

        st.subheader("Standorte")
        map_df = pd.DataFrame({
            "lat": [o.location.lat for o in filtered if o.location.lat],
            "lon": [o.location.lon for o in filtered if o.location.lon],
        })
        if not map_df.empty:
            st.map(map_df, size=20, zoom=3)

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
        in_watch = choice in st.session_state["watchlist"]
        if watch_col.button(
            "★ Aus Watchlist" if in_watch else "☆ Zur Watchlist",
            use_container_width=True,
        ):
            wl = st.session_state["watchlist"]
            (wl.remove if in_watch else wl.add)(choice)
            st.rerun()

        o = pdata.get(choice)
        if o:
            st.markdown(f"### {o.title_normalized}")
            st.markdown(
                f"<span class='score-pill'>Score {o.score}</span> "
                f"&nbsp;·&nbsp; **{o.source_platform}** · {o.category} · "
                f"{o.location.city or '—'}, {o.location.country}",
                unsafe_allow_html=True,
            )
            st.markdown(f"[Listing öffnen]({o.listing_url})")
            st.write(o.description)
            if o.score_breakdown:
                st.bar_chart(pd.DataFrame({"Punkte": o.score_breakdown}))
            with st.expander("Bid-Limit Herleitung (Handbuch §9)"):
                if o.type == "POSITIVE_ASSET":
                    st.write({
                        "Marktwert (learner-korrigiert)":
                            o.financials.estimated_market_value,
                        "- Logistik": -o.logistics_cost_estimate,
                        "- Reparatur OPEX": -o.financials.repair_opex_estimate,
                        f"- Zielmarge ({target_margin*100:.0f}%)":
                            -target_margin * o.financials.estimated_market_value,
                        "+ Schrott-Credit": o.scrap_value_potential,
                        "= Bid-Limit": o.bid_ceiling,
                    })
                else:
                    st.write({
                        "Sanierungskosten": o.financials.remediation_cost_estimate,
                        "- Schrott-Credit": -o.scrap_value_potential,
                        f"+ Zielmarge ({target_margin*100:.0f}%)":
                            target_margin * o.financials.remediation_cost_estimate,
                        "= Mindestvergütung": o.bid_ceiling,
                    })
            with st.expander("Vollständiges JSON (Schema Handbuch §8.3)"):
                st.json(pdata.to_dict(o))


# ---------------------------------------------------------------------------
# TAB 3 - Agent-Monitor
# ---------------------------------------------------------------------------

with tab_monitor:
    st.subheader("Spezialisten-Status")
    last = pstore.last_run_per_agent()
    cols = st.columns(len(pagents.ALL_SPECIALISTS))
    for col, spec in zip(cols, pagents.ALL_SPECIALISTS):
        with col:
            run = last.get(spec.name)
            with st.container(border=True):
                st.markdown(f"**{spec.name}**")
                st.caption(spec.description)
                if run and run.finished_at:
                    delta = (now - run.finished_at).total_seconds()
                    when = (f"vor {int(delta)} s" if delta < 60 else
                            f"vor {int(delta/60)} min")
                    st.write(f"Letzter Lauf: {when}")
                    st.write(f"Gefunden: **{run.found_count}**, "
                             f"Hot: **{run.hot_count}**")
                    if run.top_asset_id:
                        st.write(f"Top: `{run.top_asset_id}` "
                                 f"(Score {run.top_score})")
                else:
                    st.write("Noch nicht ausgeführt.")

    st.divider()
    st.subheader("Lauf-Historie")
    runs = pstore.recent_runs(30)
    if runs:
        df_runs = pd.DataFrame([{
            "ID": r.id,
            "Agent": r.agent_name,
            "Start": r.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "Dauer (s)": ((r.finished_at - r.started_at).total_seconds()
                          if r.finished_at else None),
            "Gefunden": r.found_count,
            "Hot": r.hot_count,
            "Top-Asset": r.top_asset_id or "—",
            "Top-Score": r.top_score,
        } for r in runs])
        st.dataframe(df_runs, use_container_width=True, hide_index=True)
    else:
        st.info("Noch keine Läufe protokolliert.")

    st.subheader("Entscheidungs-Log")
    decisions = pstore.all_decisions()
    if decisions:
        df_dec = pd.DataFrame([{
            "Zeit": d.created_at.strftime("%Y-%m-%d %H:%M"),
            "Verdict": d.verdict,
            "Asset": d.asset_id,
            "Kategorie": d.category or "",
            "Score": d.score,
            "NAV": d.net_value,
            "Rationale": (d.rationale or "")[:80],
        } for d in decisions])
        st.dataframe(df_dec, use_container_width=True, hide_index=True)
        st.download_button(
            "Entscheidungen als CSV exportieren",
            pstore.export_decisions_csv().encode("utf-8-sig"),
            file_name=f"procurement_decisions_{now:%Y%m%d_%H%M}.csv",
            mime="text/csv",
        )
    else:
        st.info("Noch keine Entscheidungen aufgezeichnet.")


# ---------------------------------------------------------------------------
# TAB 4 - Lerner
# ---------------------------------------------------------------------------

with tab_learn:
    st.subheader("Was der Lerner aus den Entscheidungen gelernt hat")
    st.caption(
        "Fit-Bonus: bewegt den Score in Kategorien, die du oft annimmst, "
        "nach oben (max ±12 Punkte ab 3 Entscheidungen). "
        "Markt-Korrektur: korrigiert geschätzte Marktwerte anhand "
        "beobachteter Endpreise (ab 3 Beobachtungen, Bereich 0.5x – 1.5x)."
    )

    summary = plearner.summarise()
    if not summary:
        st.info("Noch keine Lern-Datenpunkte. Mach im **Hot Deals** Tab "
                "ein paar Ja/Nein-Entscheidungen oder zeichne via "
                "`procurement_store.record_observation()` beobachtete "
                "Endpreise auf.")
    else:
        df = pd.DataFrame([{
            "Kategorie": a.category,
            "Fit-Bonus": a.fit_bonus,
            "Markt-Korrektur": f"{a.market_multiplier:.2f}x",
            "Entscheidungen": a.decision_samples,
            "Beobachtungen": a.observation_samples,
        } for a in summary])
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Beobachtung manuell aufzeichnen")
    st.caption(
        "Wenn eine Auktion durchgelaufen ist, trage den finalen Zuschlagspreis "
        "ein. Der Lerner passt dann die Marktwertschätzung für die Kategorie an."
    )
    with st.form("obs_form"):
        obs_asset = st.text_input("Asset-ID (z.B. VEBEG-2026-0142)")
        obs_category = st.text_input("Kategorie")
        obs_est = st.number_input("Geschätzter Marktwert (EUR)",
                                  min_value=0.0, step=100.0)
        obs_final = st.number_input("Finaler Zuschlagspreis (EUR)",
                                    min_value=0.0, step=100.0)
        if st.form_submit_button("Aufzeichnen"):
            if obs_asset and obs_category and obs_final > 0:
                pstore.record_observation(
                    obs_asset, obs_category, obs_final,
                    estimated_market_value=obs_est or None,
                )
                st.cache_data.clear()
                st.success("Beobachtung aufgezeichnet.")
                st.rerun()
            else:
                st.error("Asset-ID, Kategorie und Zuschlagspreis sind Pflicht.")


# ---------------------------------------------------------------------------
# TAB 5 - Alerts
# ---------------------------------------------------------------------------

with tab_alerts:
    st.subheader("Alert-Konfiguration")
    st.caption(
        "Email- und Webhook-Versand werden ausschliesslich über "
        "Umgebungsvariablen konfiguriert (keine Keys in der DB)."
    )

    cfg = {
        "SMTP-Host": os.getenv("PROCUREMENT_ALERT_SMTP_HOST") or "—",
        "SMTP-User": os.getenv("PROCUREMENT_ALERT_SMTP_USER") or "—",
        "From":      os.getenv("PROCUREMENT_ALERT_FROM") or "—",
        "To":        os.getenv("PROCUREMENT_ALERT_TO") or "—",
        "Webhook":   "konfiguriert" if os.getenv("PROCUREMENT_ALERT_WEBHOOK")
                     else "—",
    }
    st.json(cfg)

    st.subheader(f"Hot Deals zum Versand ({len(hot)} aktuell)")
    if hot:
        for o in hot[:5]:
            st.markdown(
                f"- **{o.title_normalized}** · Score {o.score} · "
                f"NAV {o.net_asset_value:.0f} EUR · "
                f"endet {o.auction_end:%d.%m.%Y %H:%M}"
            )
        if len(hot) > 5:
            st.caption(f"… und {len(hot)-5} weitere.")
    else:
        st.info(f"Keine Assets über Score {hot_score}.")

    c1, c2 = st.columns(2)
    if c1.button("Test-Alerts jetzt senden", type="primary", disabled=not hot):
        reports = palerts.dispatch_alerts(hot)
        if not reports:
            st.warning("Kein Kanal konfiguriert.")
        for rep in reports:
            cls = "verdict-yes" if rep.sent else "verdict-no"
            st.markdown(
                f"<span class='{cls}'>{rep.channel} → "
                f"{rep.target or '(unset)'}: "
                f"{'OK' if rep.sent else (rep.error or 'failed')}</span>",
                unsafe_allow_html=True,
            )
    c2.write("")  # spacer


# ---------------------------------------------------------------------------
# TAB 6 - Chat
# ---------------------------------------------------------------------------

with tab_chat:
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
            "Free-Tier auf https://platform.deepseek.com."
        )
    elif st.session_state["agent"] is None:
        st.info("Agent nicht verfügbar.")
    else:
        for msg in st.session_state["chat_messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        if user_msg := st.chat_input("Frag z.B.: 'Top 3 Pumpen mit Score > 70'"):
            st.session_state["chat_messages"].append(
                {"role": "user", "content": user_msg})
            with st.chat_message("user"):
                st.markdown(user_msg)
            with st.chat_message("assistant"):
                with st.spinner("Agent denkt nach …"):
                    reply = st.session_state["agent"].chat(user_msg)
                st.markdown(reply)
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": reply})
        if st.button("Chat zurücksetzen"):
            st.session_state["agent"].clear_chat()
            st.session_state["chat_messages"] = []
            st.rerun()


# ---------------------------------------------------------------------------
# TAB 7 - Briefe-Triage (Rechnungen / Mahnungen, Drive + Upload)
# ---------------------------------------------------------------------------

with tab_briefe:
    st.markdown(
        "Eingehende Briefe (Rechnungen, Mahnungen, Widerspruchsfristen) per "
        "Tastendruck triagieren. Bei **Widerspruch** legt der Agent einen "
        "deutschen Entwurf in den Postausgang. Nichts geht ohne deinen "
        "expliziten Klick raus."
    )

    if not ppdf.is_available():
        st.error(
            "`pdftotext` (poppler-utils) ist nicht installiert. Auf Debian/"
            "Ubuntu: `sudo apt-get install poppler-utils`. Ohne pdftotext "
            "koennen wir keine PDFs einlesen."
        )

    # -- Input row -------------------------------------------------------
    drive_col, upload_col = st.columns([1, 2])

    with drive_col:
        st.markdown("**Google Drive**")
        drive_client = pdrive.DriveClient()
        if drive_client.is_configured():
            if st.button("Drive abfragen", type="primary",
                         use_container_width=True):
                added = 0
                fetched = pdrive.fetch_new_pdfs(
                    drive_client,
                    is_seen_fn=pstore.is_drive_file_seen,
                )
                for drive_file, local_path in fetched:
                    try:
                        text = ppdf.extract_text(local_path)
                    except Exception as exc:  # noqa: BLE001
                        st.warning(f"pdftotext-Fehler bei {drive_file.name}: {exc}")
                        continue
                    letter = pletters.from_text(
                        text,
                        source="DRIVE",
                        filename=drive_file.name,
                        drive_file_id=drive_file.file_id,
                    )
                    pstore.record_letter(letter)
                    added += 1
                st.success(f"{added} neue PDF(s) aus Drive eingelesen.")
                st.rerun()
        else:
            st.caption(
                f"Nicht konfiguriert: {drive_client.reason_unavailable()}. "
                "Setze `PROCUREMENT_DRIVE_CREDENTIALS` und "
                "`PROCUREMENT_DRIVE_FOLDER_ID`."
            )

    with upload_col:
        st.markdown("**PDF-Upload (Quick-and-Dirty)**")
        uploaded = st.file_uploader(
            "PDFs hier hochladen (Mehrfachauswahl moeglich)",
            type=["pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        # `st.file_uploader` keeps its value across Streamlit reruns, so
        # without a guard every triage button click would re-ingest every
        # previously selected file and insert duplicate `letters` rows. We
        # fingerprint each file (name + size) and remember in session state
        # which fingerprints we have already ingested this session.
        if "uploaded_fingerprints" not in st.session_state:
            st.session_state["uploaded_fingerprints"] = set()
        seen_fps: set[str] = st.session_state["uploaded_fingerprints"]

        if uploaded and ppdf.is_available():
            import tempfile
            ingested = 0
            for fileobj in uploaded:
                fingerprint = f"{fileobj.name}:{getattr(fileobj, 'size', 0)}"
                if fingerprint in seen_fps:
                    continue
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                ) as tmp:
                    tmp.write(fileobj.read())
                    tmp_path = tmp.name
                try:
                    text = ppdf.extract_text(tmp_path)
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"pdftotext-Fehler bei {fileobj.name}: {exc}")
                    seen_fps.add(fingerprint)  # do not retry on every rerun
                    continue
                letter = pletters.from_text(
                    text,
                    source="UPLOAD",
                    filename=fileobj.name,
                )
                pstore.record_letter(letter)
                seen_fps.add(fingerprint)
                ingested += 1
            if ingested:
                st.success(f"{ingested} neue PDF(s) eingelesen.")

    st.divider()

    # -- Triage-Kartenstapel --------------------------------------------
    letters = pstore.all_letters()
    new_letters = [l for l in letters if l.status == "NEW"]

    st.subheader(f"📥 Eingang ({len(new_letters)} neu / {len(letters)} insgesamt)")
    if not new_letters:
        st.info("Keine offenen Briefe. Lade PDFs hoch oder hole sie aus Drive.")
    operator_name = os.getenv("PROCUREMENT_OPERATOR_NAME", "Der Eigentuemer")

    for letter in new_letters[:10]:
        with st.container(border=True):
            head, badge = st.columns([4, 1])
            head.markdown(
                f"### {letter.short_code or '(ohne Aktenzeichen)'}  "
                f"&nbsp;<span class='score-pill'>{letter.letter_type}</span>",
                unsafe_allow_html=True,
            )
            type_class = "verdict-no" if letter.letter_type in (
                "MAHNUNG", "WIDERSPRUCH_FRIST"
            ) else "verdict-yes"
            badge.markdown(
                f"<span class='{type_class}'>{letter.letter_type}</span>",
                unsafe_allow_html=True,
            )
            head.write(
                f"**Absender:** {letter.sender or '(unbekannt)'}"
                + (f" · {letter.sender_email}" if letter.sender_email else "")
            )
            cols = st.columns(3)
            cols[0].metric(
                "Betrag",
                pletters.format_amount_de(letter.amount_eur) + " EUR"
                if letter.amount_eur is not None else "—",
            )
            cols[1].metric(
                "Brief-Datum",
                pletters.format_date_de(letter.issue_date),
            )
            cols[2].metric(
                "Frist",
                pletters.format_date_de(letter.deadline_date),
            )
            with st.expander("Volltext (extrahiert)"):
                st.text(letter.raw_text[:4000])

            b1, b2, b3 = st.columns(3)
            if b1.button("✅ Okay", key=f"letter_ok_{letter.letter_id}"):
                pstore.record_letter_decision(
                    letter.letter_id, "KEPT", rationale="okay markiert",
                )
                st.rerun()
            if b2.button("❌ Widerspruch", key=f"letter_no_{letter.letter_id}"):
                pstore.record_letter_decision(
                    letter.letter_id, "DISPUTED",
                    rationale="Widerspruch-Entwurf generiert",
                )
                subject, body = pletters.widerspruch_email(letter, operator_name)
                pstore.record_dispatch_draft(
                    letter_id=letter.letter_id,
                    channel="EMAIL",
                    recipient=letter.sender_email or "",
                    subject=subject,
                    body=body,
                    send_at=pletters.dispatch_send_at(letter),
                )
                st.rerun()
            if b3.button("⏳ Spaeter", key=f"letter_later_{letter.letter_id}"):
                pstore.record_letter_decision(
                    letter.letter_id, "LATER", rationale="auf spaeter geschoben",
                )
                st.rerun()

    st.divider()

    # -- Postausgang -----------------------------------------------------
    drafts = pstore.pending_dispatches("DRAFT")
    st.subheader(f"📤 Postausgang ({len(drafts)} Entwurf/Entwuerfe)")
    if not drafts:
        st.info("Aktuell keine Widerspruchs-Entwuerfe.")
    for d in drafts:
        with st.container(border=True):
            top1, top2 = st.columns([3, 1])
            top1.markdown(f"**{d.subject}**")
            days_left = (d.send_at - now).days
            colour = ("verdict-no" if days_left <= 2 else
                      "verdict-later" if days_left <= 5 else
                      "verdict-yes")
            top2.markdown(
                f"<span class='{colour}'>Senden geplant: "
                f"{d.send_at:%d.%m.%Y} · in {days_left} Tagen</span>",
                unsafe_allow_html=True,
            )
            recipient = d.recipient or "(kein Empfaenger erkannt)"
            st.caption(f"An: {recipient}")
            with st.expander("Entwurf anzeigen / bearbeiten"):
                new_recipient = st.text_input(
                    "Empfaenger", value=recipient,
                    key=f"dispatch_to_{d.id}",
                )
                new_subject = st.text_input(
                    "Betreff", value=d.subject,
                    key=f"dispatch_subject_{d.id}",
                )
                new_body = st.text_area(
                    "Text", value=d.body, height=240,
                    key=f"dispatch_body_{d.id}",
                )
                bb1, bb2, bb3 = st.columns(3)
                if bb1.button("✉ Jetzt senden", key=f"send_{d.id}",
                              type="primary",
                              disabled=not new_recipient):
                    sendable = pstore.PendingDispatch(
                        id=d.id, letter_id=d.letter_id, channel=d.channel,
                        recipient=new_recipient, subject=new_subject,
                        body=new_body, send_at=d.send_at, status="DRAFT",
                        sent_at=None, error=None, created_at=d.created_at,
                    )
                    report = palerts.send_letter_dispatch(sendable)
                    if report.sent:
                        pstore.mark_dispatch_sent(d.id)
                        st.success(f"Gesendet an {report.target}.")
                    else:
                        pstore.mark_dispatch_failed(d.id, report.error or "unbekannt")
                        st.error(f"Versand fehlgeschlagen: {report.error}")
                    st.rerun()
                if bb2.button("❌ Verwerfen", key=f"cancel_{d.id}"):
                    pstore.mark_dispatch_cancelled(d.id)
                    st.rerun()
                bb3.write("")  # spacer

    st.divider()

    # -- Per-Absender-Kontext -------------------------------------------
    senders = sorted({l.sender for l in letters if l.sender})
    if senders:
        st.subheader("📚 Kontext pro Absender")
        chosen = st.selectbox(
            "Absender", senders,
            key="briefe_sender_selector",
        )
        related = pstore.letters_by_sender(chosen)
        df_related = pd.DataFrame([{
            "Datum": l.created_at.strftime("%Y-%m-%d"),
            "Aktenzeichen": l.short_code or "",
            "Typ": l.letter_type,
            "Betrag (€)": l.amount_eur,
            "Frist": l.deadline_date.isoformat() if l.deadline_date else "",
            "Status": l.status,
        } for l in related])
        st.dataframe(df_related, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# TAB 1 - Heute (zentrale Tagesuebersicht, mirror of the Triton Pipeline app)
# ---------------------------------------------------------------------------

with tab_today:
    snapshot = ptoday.load_snapshot()
    if snapshot is None:
        st.warning(
            "Keine `data/today_snapshot.json` gefunden. Lass den Snapshot via "
            "Gmail-MCP erzeugen oder lege die Datei manuell an."
        )
    else:
        gen_age = ptoday.age_label(snapshot.generated_at, now)
        st.markdown(
            f"### 📅 Heute · {now.strftime('%A, %d.%m.%Y')}"
        )
        st.caption(
            f"Snapshot: {gen_age} · Quelle Gmail: `{snapshot.source_account}`"
        )

        # ---- Kopfzeile: Kalender + Mail-Konten -----------------------
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            if snapshot.calendar_ics_url:
                st.markdown("**⏰ Kalender**")
                st.markdown(f"[Heutige Termine öffnen]({snapshot.calendar_ics_url})")
            else:
                st.markdown("**⏰ Kalender**")
                st.info(
                    "Keine ICS-URL hinterlegt. Setze `calendar_ics_url` in "
                    "`data/today_snapshot.json` (oeffentlich geteilter Google-"
                    "Calendar-ICS-Link), dann erscheinen Termine hier."
                )
        with c2:
            st.metric("Gmail-Account", "1 / mehrere")
            st.caption(snapshot.source_account)
        with c3:
            st.metric("Verfahren-Labels", len(snapshot.open_verfahren_labels))
            st.caption("offene Aktenzeichen")

        if snapshot.second_inbox_status:
            with st.expander("⚠️ Hinweis Zweit-Account"):
                st.caption(snapshot.second_inbox_status)

        st.divider()

        # ---- 4 Sektionen aus PIPELINE.md -----------------------------
        for section in snapshot.sections:
            klass = ptoday.urgency_class(section.urgency)
            with st.container(border=True):
                head_l, head_r = st.columns([5, 1])
                head_l.markdown(
                    f"### {section.title}  "
                    f"<span class='{klass}'>{section.thread_count} Threads</span>",
                    unsafe_allow_html=True,
                )
                head_r.caption(section.source_path)
                st.write(f"_{section.subtitle}_")

                if section.threads:
                    for t in section.threads:
                        with st.container():
                            cols = st.columns([4, 1])
                            cols[0].markdown(f"**{t.subject}**")
                            cols[1].caption(ptoday.age_label(t.last_message_at, now))
                            if t.snippet:
                                st.caption(t.snippet)
                            meta_bits = [
                                f"_Von:_ {t.sender}" if t.sender else None,
                                f"_Status:_ {t.status}" if t.status else None,
                            ]
                            st.caption(" · ".join(b for b in meta_bits if b))
                            if t.gmail_url:
                                st.markdown(f"[In Gmail öffnen]({t.gmail_url})")
                else:
                    st.info("Keine aktiven Threads in den letzten 14 Tagen.")

                if section.chips:
                    chip_html = " ".join(
                        f"<span class='score-pill'>{c}</span>"
                        for c in section.chips
                    )
                    st.markdown(chip_html, unsafe_allow_html=True)

        # ---- Verfahren-Tracker (Labels) ------------------------------
        if snapshot.open_verfahren_labels:
            with st.expander(
                f"⚖️ {len(snapshot.open_verfahren_labels)} offene Verfahren-Labels"
            ):
                for label in snapshot.open_verfahren_labels:
                    st.markdown(f"- {label}")

        st.divider()
        st.caption(
            "Diese Sicht spiegelt deine Triton-Pipeline (PIPELINE.md). "
            "Daten kommen aus `data/today_snapshot.json`. Refresh: Snapshot via "
            "Gmail-MCP neu erzeugen."
        )


# ---------------------------------------------------------------------------
# Footer - data source health
# ---------------------------------------------------------------------------

st.divider()
st.caption("Datenquellen-Status")
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
