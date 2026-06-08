# -*- coding: utf-8 -*-
"""Fabric L1 Support Bot - Dashboard (Terminal Dark Style)."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

# India Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

st.set_page_config(
    page_title="Fabric Pipeline Failure Agent",
    page_icon=":wrench:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;600;700;800&display=swap');

* { box-sizing: border-box; }

.stApp {
    background: #0d1117;
    font-family: 'Inter', sans-serif;
}

/* Hide streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
[data-testid="stSidebar"] * { color: #8b949e !important; }
.block-container { padding: 2rem 2rem 2rem 2rem !important; max-width: 1400px; }

/* Agent header */
.agent-header {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.agent-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 26px;
    font-weight: 800;
    color: #f0f6fc;
    margin: 0;
}
.agent-subtitle {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #8b949e;
    margin-top: 4px;
}
.agent-status-running {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #0d2818;
    border: 1px solid #238636;
    border-radius: 20px;
    padding: 6px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 700;
    color: #3fb950;
    letter-spacing: 1.5px;
}
.dot-pulse {
    width: 8px; height: 8px;
    background: #3fb950;
    border-radius: 50%;
    display: inline-block;
    animation: pulse 1.5s infinite;
}
@keyframes pulse {
    0%,100% { opacity: 1; }
    50% { opacity: 0.3; }
}
.last-scan {
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: #8b949e;
    margin-left: 16px;
}

/* KPI Cards */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
}
.kpi-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 22px 24px;
    position: relative;
    overflow: hidden;
}
.kpi-card::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 3px;
}
.kpi-red::after    { background: #f85149; }
.kpi-green::after  { background: #3fb950; }
.kpi-yellow::after { background: #d29922; }
.kpi-blue::after   { background: #388bfd; }
.kpi-teal::after   { background: #2dd4bf; }
.kpi-purple::after { background: #8957e5; }

.kpi-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #8b949e;
    margin-bottom: 10px;
}
.kpi-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 48px;
    font-weight: 800;
    line-height: 1;
    margin-bottom: 8px;
}
.kpi-red    .kpi-value { color: #f85149; }
.kpi-green  .kpi-value { color: #3fb950; }
.kpi-yellow .kpi-value { color: #d29922; }
.kpi-blue   .kpi-value { color: #388bfd; }
.kpi-teal   .kpi-value { color: #2dd4bf; }
.kpi-purple .kpi-value { color: #8957e5; }
.kpi-sub {
    font-size: 12px;
    color: #8b949e;
    font-family: 'JetBrains Mono', monospace;
}

/* Section headers */
.sec-header {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2.5px;
    color: #8b949e;
    text-transform: uppercase;
    margin: 28px 0 16px 0;
    display: flex;
    align-items: center;
    gap: 10px;
}
.sec-header::before { content: '//'; color: #388bfd; }
.sec-badge {
    background: #f8514922;
    border: 1px solid #f85149;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 11px;
    color: #f85149;
    letter-spacing: 1px;
}

/* Incident Cards */
.incident-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 12px;
    border-left: 3px solid #f85149;
    transition: border-color 0.2s;
}
.incident-card:hover { border-left-color: #388bfd; }
.incident-card.fixed { border-left-color: #3fb950; }
.incident-card.escalated { border-left-color: #d29922; }
.incident-card.maxretry { border-left-color: #8957e5; }

.incident-name {
    font-size: 15px;
    font-weight: 700;
    color: #f0f6fc;
    margin-bottom: 10px;
    font-family: 'JetBrains Mono', monospace;
}
.badge-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    font-family: 'JetBrains Mono', monospace;
}
.badge-critical  { background: #f8514922; color: #f85149; border: 1px solid #f85149; }
.badge-fixed     { background: #3fb95022; color: #3fb950; border: 1px solid #3fb950; }
.badge-escalated { background: #d2992222; color: #d29922; border: 1px solid #d29922; }
.badge-maxretry  { background: #8957e522; color: #8957e5; border: 1px solid #8957e5; }
.badge-category  { background: #388bfd22; color: #388bfd; border: 1px solid #388bfd; }
.badge-info      { background: #21262d;   color: #8b949e; border: 1px solid #30363d; }

.incident-meta {
    font-size: 12px;
    color: #8b949e;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 6px;
}
.incident-cause {
    font-size: 12px;
    color: #8b949e;
    margin-top: 6px;
    padding: 8px 12px;
    background: #0d1117;
    border-radius: 6px;
    border-left: 2px solid #30363d;
    font-family: 'Inter', sans-serif;
}

/* Chart containers */
.chart-box {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 20px;
}

/* Daily summary table */
.summary-table {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    overflow: hidden;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    width: 100%;
}
.summary-table th {
    background: #0d1117;
    color: #8b949e;
    padding: 10px 16px;
    text-align: left;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border-bottom: 1px solid #21262d;
}
.summary-table td {
    padding: 10px 16px;
    color: #f0f6fc;
    border-bottom: 1px solid #21262d;
}
.summary-table tr:last-child td { border-bottom: none; }
.summary-table tr:hover td { background: #21262d33; }

/* Sidebar button */
.stButton > button {
    background: #21262d;
    color: #f0f6fc;
    border: 1px solid #30363d;
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    width: 100%;
    padding: 10px;
    transition: all 0.2s;
}
.stButton > button:hover {
    background: #388bfd22;
    border-color: #388bfd;
    color: #388bfd;
}

/* Selectbox */
[data-testid="stSelectbox"] label { color: #8b949e !important; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
</style>
""", unsafe_allow_html=True)

# ── Config ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent.parent
load_dotenv(_HERE / ".env")  # make Fabric credentials available to the dashboard
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG_PATH", str(_HERE / "logs" / "audit.jsonl")))
FABRIC_WORKSPACE_ID = os.environ.get("FABRIC_WORKSPACE_IDS", "a078c6ff-84af-4f0e-b177-381e4bba48ee").split(",")[0]
FABRIC_URL = f"https://app.fabric.microsoft.com/groups/{FABRIC_WORKSPACE_ID}/list?experience=fabric-developer"


@st.cache_data(ttl=300, show_spinner=False)
def get_workspace_pipeline_count(workspace_id: str):
    """Live count of all DataPipelines in the Fabric workspace.

    Returns an int, or None if credentials are missing or the API call fails
    (so the dashboard degrades gracefully instead of erroring).
    """
    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    if not all([tenant, client, secret]):
        return None
    try:
        token_resp = httpx.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client,
                "client_secret": secret,
                "scope": "https://api.fabric.microsoft.com/.default",
            },
            timeout=15.0,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]
        items_resp = httpx.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        items_resp.raise_for_status()
        return sum(
            1 for it in items_resp.json().get("value", [])
            if it.get("type") == "DataPipeline"
        )
    except Exception:
        return None

PLOTLY_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#8b949e", family="JetBrains Mono, monospace", size=11),
    margin=dict(t=10, b=30, l=10, r=10),
)

CAT_COLOR = {
    "transient":     "#3fb950",
    "auth":          "#d29922",
    "infra":         "#388bfd",
    "schema":        "#f85149",
    "permission":    "#f85149",
    "data_quality":  "#8957e5",
    "source_missing":"#d29922",
    "unknown":       "#8b949e",
}
ACT_COLOR = {
    "auto_rerun":           "#3fb950",
    "alert_sent":           "#d29922",
    "max_retries_exceeded": "#f85149",
    "investigating":        "#388bfd",
}
ACT_LABEL = {
    "auto_rerun":           "AUTO-FIXED",
    "alert_sent":           "ESCALATED",
    "max_retries_exceeded": "MAX RETRIES",
    "investigating":        "INVESTIGATING",
}
ACT_BADGE = {
    "auto_rerun":           "badge-fixed",
    "alert_sent":           "badge-escalated",
    "max_retries_exceeded": "badge-maxretry",
    "investigating":        "badge-category",
}
CARD_CLASS = {
    "auto_rerun":           "fixed",
    "alert_sent":           "escalated",
    "max_retries_exceeded": "maxretry",
}

# ── Data ──────────────────────────────────────────────────────────────────────
def _load_sample_records() -> list:
    """Fallback demo data when no real audit log exists (e.g. public showcase)."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from generate_sample_data import build_sample_records
        return build_sample_records()
    except Exception:
        return []

@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    records = []
    if AUDIT_LOG.exists():
        with open(AUDIT_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except:
                        pass
    if not records:
        records = _load_sample_records()
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    uuid_p = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    df["pipeline_name"] = df.apply(
        lambda r: r.get("pipeline_id","Unknown")
        if uuid_p.match(str(r.get("pipeline_name",""))) else r.get("pipeline_name","Unknown"), axis=1
    )
    df["date"]    = df["timestamp"].dt.date
    df["hour"]    = df["timestamp"].dt.hour
    df["weekday"] = df["timestamp"].dt.strftime("%a")
    return df

def filter_days(df, days):
    if df.empty: return df
    return df[df["timestamp"] >= pd.Timestamp.utcnow() - timedelta(days=days)]

# ── Load ──────────────────────────────────────────────────────────────────────
df_all = load_data()
if df_all.empty:
    st.error("No audit data found. Run: `python main.py`")
    st.stop()

DEMO_MODE = not AUDIT_LOG.exists()
if DEMO_MODE:
    st.info("🟢 **Live demo** — showing sample data to showcase the Fabric L1 Support Agent. "
            "In production this is populated by real pipeline runs.")

# IST date bounds for the date picker
_ist_dates = df_all["timestamp"].dt.tz_convert(IST).dt.date
_min_date, _max_date = _ist_dates.min(), _ist_dates.max()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Fabric L1 Bot**")
    st.markdown(f"[Open Workspace]({FABRIC_URL})")
    st.markdown("---")
    filter_mode = st.radio("Filter by", ["Date range", "Specific date"], index=0)
    if filter_mode == "Date range":
        date_range = st.selectbox(
            "Date Range",
            [1, 7, 14, 30],
            format_func=lambda x: f"Last {x} day{'s' if x>1 else ''}",
            index=3,
        )
        selected_date = None
    else:
        selected_date = st.date_input(
            "Pick a date (IST)",
            value=_max_date,
            min_value=_min_date,
            max_value=_max_date,
        )
        date_range = None
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Auto-refreshes every 60s")

# ── Apply filter ──────────────────────────────────────────────────────────────
if selected_date is not None:
    df = df_all[df_all["timestamp"].dt.tz_convert(IST).dt.date == selected_date]
    period_label = selected_date.strftime("%d %b %Y")
    empty_msg = f"No data for {period_label} (IST)."
else:
    df = filter_days(df_all, date_range)
    period_label = f"LAST {date_range} DAYS"
    empty_msg = f"No data in last {date_range} days."

if df.empty:
    st.warning(empty_msg)
    st.stop()

now_str = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")
total     = len(df)
fixed     = int((df["action_taken"] == "auto_rerun").sum())
escalated = int((df["action_taken"] == "alert_sent").sum())
maxretry  = int((df["action_taken"] == "max_retries_exceeded").sum())
fix_rate  = round(fixed/total*100, 1) if total else 0
avg_conf  = round(df["confidence_score"].mean()*100, 1) if "confidence_score" in df.columns else 0

today_df = filter_days(df, 1)
today_count = len(today_df)

total_pipelines = get_workspace_pipeline_count(FABRIC_WORKSPACE_ID)
total_pipelines_display = total_pipelines if total_pipelines is not None else "—"
with_failures = df["pipeline_name"].nunique()

# Reruns that were VERIFIED to succeed (genuine recoveries), not just triggered
recovered = int((df["rerun_succeeded"] == True).sum()) if "rerun_succeeded" in df.columns else 0
recover_rate = round(recovered / fixed * 100, 1) if fixed else 0

# ── Agent Header ──────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="agent-header">
  <div>
    <div class="agent-title">Fabric Pipeline Failure Agent</div>
    <div class="agent-subtitle">
      Workspace: {FABRIC_WORKSPACE_ID[:8]}...{FABRIC_WORKSPACE_ID[-4:]} &nbsp;|&nbsp;
      Scan interval: 2 min &nbsp;|&nbsp;
      Monitoring: {len(df['pipeline_name'].unique())} pipelines
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px;">
    <div class="agent-status-running">
      <span class="dot-pulse"></span>
      AGENT RUNNING
    </div>
    <span class="last-scan">Last scan: {now_str}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── KPI Cards ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="kpi-grid">
  <div class="kpi-card kpi-blue">
    <div class="kpi-label">Total Pipelines</div>
    <div class="kpi-value">{total_pipelines_display}</div>
    <div class="kpi-sub">in workspace &nbsp;({with_failures} with failures)</div>
  </div>
  <div class="kpi-card kpi-red">
    <div class="kpi-label">Failed Pipelines</div>
    <div class="kpi-value">{total}</div>
    <div class="kpi-sub">+{today_count} since yesterday</div>
  </div>
  <div class="kpi-card kpi-green">
    <div class="kpi-label">Auto-Fixed</div>
    <div class="kpi-value">{fixed}</div>
    <div class="kpi-sub">reruns triggered &nbsp;({fix_rate}%)</div>
  </div>
  <div class="kpi-card kpi-teal">
    <div class="kpi-label">Recovered</div>
    <div class="kpi-value">{recovered}</div>
    <div class="kpi-sub">verified success after rerun &nbsp;({recover_rate}%)</div>
  </div>
  <div class="kpi-card kpi-yellow">
    <div class="kpi-label">Escalated</div>
    <div class="kpi-value">{escalated}</div>
    <div class="kpi-sub">Teams alert sent</div>
  </div>
  <div class="kpi-card kpi-purple">
    <div class="kpi-label">Max Retries Hit</div>
    <div class="kpi-value">{maxretry}</div>
    <div class="kpi-sub">L2 intervention needed</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Detected Failures Today ───────────────────────────────────────────────────
st.markdown(f"""
<div class="sec-header">
  DETECTED FAILURES &mdash; {period_label}
  <span class="sec-badge">{total} failures</span>
</div>
""", unsafe_allow_html=True)

# Show each incident as a card
recent = df.sort_values("timestamp", ascending=False).head(10)
for _, row in recent.iterrows():
    action  = row.get("action_taken", "unknown")
    cat     = row.get("error_category", "unknown")
    name    = row.get("pipeline_name", "Unknown Pipeline")
    cause   = row.get("root_cause", "")
    err_msg = str(row.get("error_message", "") or "")
    ts_val  = row["timestamp"]
    if hasattr(ts_val, "tz_convert"):        # tz-aware (UTC) pandas Timestamp -> IST
        ts = ts_val.tz_convert(IST).strftime("%d %b %Y, %I:%M:%S %p IST")
    elif hasattr(ts_val, "strftime"):
        ts = ts_val.strftime("%d %b %Y, %I:%M:%S %p IST")
    else:
        ts = str(ts_val)
    conf    = row.get("confidence_score", 0)
    retries = int(row.get("retry_count", 0))
    card_cls = CARD_CLASS.get(action, "")
    act_badge = ACT_BADGE.get(action, "badge-info")
    act_label = ACT_LABEL.get(action, action.upper())
    cat_color = CAT_COLOR.get(cat, "#8b949e")
    severity  = "CRITICAL" if cat in ["schema","permission","source_missing"] else "WARNING" if cat in ["data_quality"] else "INFO"
    sev_badge = "badge-critical" if severity == "CRITICAL" else "badge-escalated" if severity == "WARNING" else "badge-info"

    st.markdown(f"""
<div class="incident-card {card_cls}">
  <div class="incident-name">&#128233; {name}</div>
  <div class="badge-row">
    <span class="badge {sev_badge}">{severity}</span>
    <span class="badge badge-category" style="border-color:{cat_color};color:{cat_color};background:{cat_color}22;">{cat.replace('_',' ').upper()}</span>
    <span class="badge {act_badge}">{act_label}</span>
    {"<span class='badge badge-info'>Retries: " + str(retries) + "/3</span>" if retries > 0 else ""}
    {"<span class='badge badge-info'>Confidence: " + str(int(conf*100)) + "%</span>" if conf else ""}
  </div>
  {"<div class='incident-cause' style='color:#f0883e;'><b>Error:</b> " + err_msg[:240] + ("..." if len(err_msg) > 240 else "") + "</div>" if err_msg else ""}
  {"<div class='incident-cause'><b>Root cause:</b> " + str(cause)[:200] + ("..." if len(str(cause)) > 200 else "") + "</div>" if cause else ""}
  <div class="incident-meta">{ts}</div>
</div>
""", unsafe_allow_html=True)

# ── Charts Row ────────────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">TREND ANALYSIS</div>', unsafe_allow_html=True)
cc1, cc2 = st.columns([2, 1])

with cc1:
    daily = (
        df.groupby("date")
        .agg(
            total=("run_id","count"),
            fixed=("action_taken", lambda x: (x=="auto_rerun").sum()),
            escalated=("action_taken", lambda x: (x=="alert_sent").sum()),
            maxr=("action_taken", lambda x: (x=="max_retries_exceeded").sum()),
        ).reset_index()
    )
    fig = go.Figure()
    fig.add_bar(x=daily["date"], y=daily["total"],    name="Total",       marker_color="#388bfd", opacity=0.4)
    fig.add_bar(x=daily["date"], y=daily["fixed"],    name="Auto-Fixed",  marker_color="#3fb950")
    fig.add_bar(x=daily["date"], y=daily["escalated"],name="Escalated",   marker_color="#d29922")
    fig.add_bar(x=daily["date"], y=daily["maxr"],     name="Max Retries", marker_color="#f85149")
    fig.update_layout(
        **PLOTLY_BASE, barmode="overlay", height=280,
        legend=dict(orientation="h", y=-0.3, font=dict(color="#8b949e")),
        xaxis=dict(gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(gridcolor="#21262d", color="#8b949e"),
    )
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with cc2:
    cat_df = df["error_category"].value_counts().reset_index()
    cat_df.columns = ["cat","count"]
    colors = [CAT_COLOR.get(c,"#8b949e") for c in cat_df["cat"]]
    fig2 = go.Figure(go.Pie(
        labels=cat_df["cat"], values=cat_df["count"],
        hole=0.6,
        marker=dict(colors=colors, line=dict(color="#0d1117", width=2)),
        textinfo="percent",
        textfont=dict(size=11, color="#f0f6fc"),
        hovertemplate="<b>%{label}</b><br>%{value} incidents<br>%{percent}<extra></extra>",
    ))
    fig2.add_annotation(
        text=f"<b>{total}</b><br>total",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16, color="#f0f6fc", family="JetBrains Mono"),
    )
    fig2.update_layout(**PLOTLY_BASE, height=280, showlegend=True,
        legend=dict(orientation="v", x=1, font=dict(color="#8b949e", size=10)))
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.plotly_chart(fig2, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── Daily Summary Table ────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">DAILY SUMMARY</div>', unsafe_allow_html=True)

summary = (
    df.groupby("date")
    .agg(
        total=("run_id","count"),
        fixed=("action_taken", lambda x: (x=="auto_rerun").sum()),
        escalated=("action_taken", lambda x: (x=="alert_sent").sum()),
        maxr=("action_taken", lambda x: (x=="max_retries_exceeded").sum()),
        pipelines=("pipeline_name","nunique"),
        conf=("confidence_score", lambda x: f"{x.mean():.0%}"),
    ).reset_index().sort_values("date", ascending=False)
)
summary["fix_rate"] = (summary["fixed"] / summary["total"] * 100).round(1).astype(str) + "%"

rows_html = ""
for _, r in summary.iterrows():
    fix_color = "#3fb950" if float(r["fix_rate"].replace("%","")) > 50 else "#f85149"
    rows_html += f"""
    <tr>
      <td>{r['date']}</td>
      <td style="color:#f85149;font-weight:700;">{r['total']}</td>
      <td style="color:#3fb950;font-weight:700;">{r['fixed']}</td>
      <td style="color:#d29922;">{r['escalated']}</td>
      <td style="color:#f85149;">{r['maxr']}</td>
      <td style="color:#8b949e;">{r['pipelines']}</td>
      <td style="color:{fix_color};font-weight:700;">{r['fix_rate']}</td>
      <td style="color:#8957e5;">{r['conf']}</td>
    </tr>"""

st.markdown(f"""
<table class="summary-table">
  <thead>
    <tr>
      <th>Date</th>
      <th>Total</th>
      <th>Auto-Fixed</th>
      <th>Escalated</th>
      <th>Max Retries</th>
      <th>Pipelines</th>
      <th>Fix Rate</th>
      <th>Avg Confidence</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
""", unsafe_allow_html=True)

# ── Export ────────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
cols_exp = [c for c in ["timestamp","pipeline_name","error_category","action_taken",
                         "success","retry_count","confidence_score","root_cause"] if c in df.columns]
csv = df[cols_exp].sort_values("timestamp", ascending=False).to_csv(index=False).encode("utf-8")
st.download_button(
    "Export Incidents CSV",
    csv,
    f"fabric_l1_{datetime.utcnow().strftime('%Y%m%d')}.csv",
    "text/csv",
)
