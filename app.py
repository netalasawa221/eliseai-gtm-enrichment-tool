"""Streamlit UI for the EliseAI Lead Enrichment Tool.

Wraps the existing pipeline (enricher → scorer → email_generator → email_sender)
with a web interface. No pipeline logic lives here — only UI orchestration.

Run with:
    streamlit run app.py
"""

import html as _html
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from clients.census_client import get_city_demographics
from clients.email_sender import send_email
from clients.hud_client import get_fair_market_rent
from clients.news_client import get_city_real_estate_news, get_company_news
from core.email_generator import generate_outreach_email
from core.icp_classifier import classify_icp
from core.scorer import score_lead, build_linkedin_urls

SAMPLE_CSV_PATH = Path("data/sample_leads.csv")
REQUIRED_COLUMNS = {"name", "email", "company", "property_address", "city", "state", "country"}

TIER_EMOJI = {"Hot": "🔥", "Warm": "🌤️", "Cold": "❄️"}
TIER_COLOR = {"Hot": "#FF4B4B", "Warm": "#FFA500", "Cold": "#4B9CD3"}

# ---------------------------------------------------------------------------
# CSS — using selectors confirmed to work in Streamlit
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* Force dark theme base */
.stApp { background-color: #0d1117 !important; }
section[data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d !important; }
section[data-testid="stSidebar"] * { color: #c9d1d9 !important; }

/* Main content area */
.main .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; max-width: 1050px !important; }

/* ALL text color */
.stMarkdown, .stText, p, span, label, div { color: #c9d1d9; }

/* Headers */
h1, h2, h3 { color: #f0f6fc !important; }

/* Buttons - primary */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #238636, #2ea043) !important;
    color: white !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
    font-size: 1rem !important; padding: 0.6rem 2rem !important;
    width: 100% !important; transition: all 0.2s !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #2ea043, #3fb950) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 15px rgba(46,160,67,0.4) !important;
}

/* Buttons - secondary */
.stButton > button[kind="secondary"] {
    background: #21262d !important; color: #c9d1d9 !important;
    border: 1px solid #30363d !important; border-radius: 6px !important;
}

/* Download button */
.stDownloadButton > button {
    background: linear-gradient(135deg, #1f6feb, #388bfd) !important;
    color: white !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
    width: 100% !important; padding: 0.6rem !important;
}

/* Dataframe */
.stDataFrame { border: 1px solid #30363d !important; border-radius: 8px !important; }

/* Expanders */
details { border: 1px solid #30363d !important; border-radius: 10px !important; margin-bottom: 0.5rem !important; background: #161b22 !important; }
details summary { padding: 0.8rem 1rem !important; font-weight: 500 !important; color: #f0f6fc !important; }
details[open] { border-color: #388bfd !important; }

/* Metrics */
[data-testid="stMetric"] { background: #161b22 !important; border: 1px solid #30363d !important; border-radius: 10px !important; padding: 1rem !important; }
[data-testid="stMetricValue"] { color: #f0f6fc !important; font-size: 1.8rem !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 0.8rem !important; }

/* File uploader */
[data-testid="stFileUploader"] { border: 2px dashed #30363d !important; border-radius: 10px !important; padding: 1rem !important; background: #161b22 !important; }

/* Success/Info/Warning/Error boxes */
.stSuccess { background: rgba(46,160,67,0.1) !important; border: 1px solid rgba(46,160,67,0.3) !important; border-radius: 8px !important; }
.stInfo    { background: rgba(56,139,253,0.1) !important; border: 1px solid rgba(56,139,253,0.3) !important; border-radius: 8px !important; }
.stWarning { background: rgba(210,153,34,0.1) !important; border: 1px solid rgba(210,153,34,0.3) !important; border-radius: 8px !important; }
.stError   { background: rgba(248,81,73,0.1)  !important; border: 1px solid rgba(248,81,73,0.3)  !important; border-radius: 8px !important; }

/* Slider */
.stSlider > div > div > div { background: #388bfd !important; }

/* Divider */
hr { border-color: #21262d !important; }

/* Code blocks */
code { background: #161b22 !important; border: 1px solid #30363d !important; border-radius: 4px !important; }

/* Progress bar */
.stProgress > div > div { background: linear-gradient(90deg, #1f6feb, #388bfd) !important; }

/* Text area */
textarea { background: #161b22 !important; color: #c9d1d9 !important; border: 1px solid #30363d !important; border-radius: 6px !important; font-family: 'Courier New', monospace !important; }
</style>
"""


# ---------------------------------------------------------------------------
# Step header helper — inline styles only, no CSS class dependency
# ---------------------------------------------------------------------------

def step_header(num: int, title: str, subtitle: str = "") -> None:
    sub_html = (
        f'<div style="font-size:0.82rem; color:#8b949e; margin-top:0.2rem;">{subtitle}</div>'
        if subtitle else ""
    )
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:0.8rem;
                    margin:2rem 0 1rem 0; padding-bottom:0.8rem;
                    border-bottom:1px solid #21262d;">
            <div style="background:#1f6feb; color:white; width:32px; height:32px;
                        border-radius:50%; display:flex; align-items:center;
                        justify-content:center; font-weight:700; font-size:0.9rem;
                        flex-shrink:0;">{num}</div>
            <div>
                <div style="font-size:1.15rem; font-weight:700; color:#f0f6fc;
                            line-height:1;">{title}</div>
                {sub_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_session_state() -> None:
    """Set default values for all session state keys on first load."""
    defaults = {
        "processed": False,
        "results": [],
        "input_df": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> tuple[bool, int]:
    """Render sidebar settings and API status check.

    Returns:
        (send_emails, limit) — settings chosen by the user.
    """
    with st.sidebar:
        st.markdown(
            """
            <div style="padding:0.5rem 0 1.5rem 0; border-bottom:1px solid #21262d;
                        margin-bottom:1.5rem;">
                <div style="font-size:1rem; font-weight:700; color:#f0f6fc;">⚙️ Settings</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # --- Email sending toggle ---
        send_emails = st.checkbox(
            "📧 Send demo emails",
            value=False,
            help="Route generated emails to DEMO_RECIPIENT_EMAIL. Never sends to real lead addresses.",
        )
        if send_emails:
            demo_addr = config.DEMO_RECIPIENT_EMAIL or "(not set)"
            st.warning(
                f"Emails route to **{demo_addr}** only — never real recipients.",
                icon="⚠️",
            )
            valid, err = config.validate_email_config()
            if not valid:
                st.error(f"Email config error: {err}", icon="🚫")
                send_emails = False

        st.markdown("---")

        # --- Lead limit slider ---
        # Read the uploaded DataFrame from session state (set by render_upload_section).
        # Because Streamlit reruns the full script on every interaction, this value
        # is always current by the time the sidebar re-renders after an upload.
        _uploaded_df = st.session_state.get("input_df")
        n_leads = len(_uploaded_df) if _uploaded_df is not None else 0

        if n_leads > 0:
            limit = st.slider(
                f"Leads to process (uploaded: {n_leads})",
                min_value=1,
                max_value=n_leads,
                value=n_leads,
                # Key includes n_leads so uploading a different-sized CSV resets the slider.
                key=f"lead_limit_{n_leads}",
                help="Lower to test on a subset. Leads are processed in CSV order.",
            )
            if limit == n_leads:
                st.caption(f"Processing all {n_leads} leads. Lower the slider to test on a subset.")
            else:
                st.caption(f"Processing {limit} of {n_leads} leads (subset mode).")
        else:
            st.slider(
                "Leads to process",
                min_value=1,
                max_value=50,
                value=5,
                disabled=True,
                help="Upload a CSV first to enable this slider.",
            )
            st.caption("Upload a CSV first to set the lead limit.")
            limit = 5  # fallback; not used since no CSV is loaded yet

        st.markdown("---")

        # --- API status ---
        with st.expander("🔌 API Status"):
            for api_name, key_exists, desc in [
                ("Census API", bool(config.CENSUS_API_KEY), "Demographics"),
                ("HUD API", bool(config.HUD_API_TOKEN), "Market rents"),
                ("NewsAPI", bool(config.NEWS_API_KEY), "Company news"),
                ("Claude API", bool(config.ANTHROPIC_API_KEY), "AI generation"),
                ("Gmail SMTP", bool(config.GMAIL_USER), "Email sending"),
            ]:
                icon = "🟢" if key_exists else "🔴"
                st.markdown(f"{icon} **{api_name}** — {desc}")

        st.markdown("---")
        st.caption("Powered by Census · HUD · NewsAPI · Claude")

    return send_emails, limit


# ---------------------------------------------------------------------------
# Upload section
# ---------------------------------------------------------------------------

def render_upload_section() -> pd.DataFrame | None:
    """File uploader with sample-data fallback.

    Returns:
        A validated DataFrame, or None if nothing is loaded yet.
    """
    step_header(1, "Load Leads", "Upload a CSV or use sample data")

    uploaded = st.file_uploader(
        "Upload a leads CSV",
        type=["csv"],
        help="Required columns: name, email, company, property_address, city, state, country",
    )

    df: pd.DataFrame | None = None

    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded)
        except Exception as exc:
            st.error(f"Could not parse CSV: {exc}")
            return None
    else:
        col_btn, col_msg = st.columns([1, 3])
        with col_btn:
            if st.button("📋 Use sample data", use_container_width=True):
                if SAMPLE_CSV_PATH.exists():
                    df = pd.read_csv(SAMPLE_CSV_PATH)
                    st.session_state.input_df = df
                else:
                    st.error(f"Sample file not found: {SAMPLE_CSV_PATH}")
                    return None
        with col_msg:
            st.markdown(
                "<small>Loads <code>data/sample_leads.csv</code> — 5 realistic leads "
                "across Austin, Newark, Miami, Boise, and Liberal KS.</small>",
                unsafe_allow_html=True,
            )
        if df is None and st.session_state.input_df is not None:
            df = st.session_state.input_df

    if df is None:
        st.info("Upload a CSV or click **Use sample data** to get started.", icon="👆")
        return None

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        st.error(f"CSV is missing required columns: {sorted(missing)}")
        return None

    st.session_state.input_df = df

    st.success(f"Loaded {len(df)} lead(s).")
    with st.expander("Preview uploaded data", expanded=True):
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)

    return df


# ---------------------------------------------------------------------------
# Processing (pipeline logic — UNCHANGED)
# ---------------------------------------------------------------------------

def _enrich_with_steps(lead: dict, step_fn) -> dict:
    """Run all enrichment steps sequentially, calling step_fn(label) before each.

    Mirrors core/enricher.py but accepts a callback so the Streamlit UI can
    update a status widget between each blocking API call.

    Args:
        lead:    Lead row dict.
        step_fn: Callable that accepts a string label and updates the UI.

    Returns:
        Enrichment dict identical in shape to enrich_lead() output.
    """
    company = lead.get("company", "Unknown")
    city = lead.get("city", "")
    state = lead.get("state", "")
    error_summary: list[str] = []

    step_fn(f"[1/6] Census demographics for {city}, {state}…")
    try:
        census = get_city_demographics(city, state)
    except Exception as exc:
        census = {"housing_units": None, "renter_percentage": None, "median_income": None,
                  "success": False, "error": str(exc)}
    if not census.get("success"):
        error_summary.append("Census")

    step_fn(f"[2/6] HUD Fair Market Rents for {city}, {state}…")
    try:
        hud = get_fair_market_rent(city, state)
    except Exception as exc:
        hud = {"fmr_1br": None, "fmr_2br": None, "fmr_3br": None,
               "metro_name": None, "success": False, "error": str(exc)}
    if not hud.get("success"):
        error_summary.append("HUD")

    step_fn(f"[3/6] Company news for {company}…")
    try:
        company_news = get_company_news(company)
    except Exception as exc:
        company_news = {"article_count": 0, "articles": [], "success": False, "error": str(exc)}
    if not company_news.get("success"):
        error_summary.append("Company News")

    step_fn(f"[4/6] Real estate news for {city}, {state}…")
    try:
        city_news = get_city_real_estate_news(city, state)
    except Exception as exc:
        city_news = {"article_count": 0, "articles": [], "success": False, "error": str(exc)}
    if not city_news.get("success"):
        error_summary.append("City News")

    headlines = [
        a.get("title", "")
        for a in (company_news.get("articles") or [])
        if a.get("title")
    ]
    step_fn(f"[5/6] ICP classification for {company}…")
    try:
        icp = classify_icp(company, headlines)
    except Exception as exc:
        icp = {"company": company, "icp_match": "UNCERTAIN", "company_size": "UNKNOWN",
               "description": "", "size_score_bonus": 0, "success": False, "error": str(exc)}
    if not icp.get("success"):
        error_summary.append("icp_classifier")

    return {
        "census": census,
        "hud": hud,
        "news": {"company_news": company_news, "city_news": city_news},
        "icp": icp,
        "any_errors": len(error_summary) > 0,
        "error_summary": error_summary,
    }


def process_leads_with_ui(df: pd.DataFrame, send_emails: bool, limit: int) -> None:
    """Run the enrichment pipeline with live Streamlit progress updates.

    Writes results to st.session_state.results and sets
    st.session_state.processed = True on completion.

    Args:
        df:          Input leads DataFrame (all rows; limit is applied here).
        send_emails: Whether to send demo emails after each lead is processed.
        limit:       Maximum number of leads to process.
    """
    df = df.head(limit).reset_index(drop=True)
    total = len(df)
    results: list[dict] = []

    st.divider()
    step_header(2, "Enrich & Score", "Calling Census, HUD, NewsAPI, and Claude for each lead")

    progress_bar = st.progress(0, text="Starting…")
    status_box = st.empty()
    log_container = st.container()

    for idx, row in df.iterrows():
        lead = row.to_dict()
        name = lead.get("name", "?")
        company = lead.get("company", "?")
        city = lead.get("city", "")
        state = lead.get("state", "")

        pct = int(idx / total * 100)
        progress_bar.progress(pct, text=f"Processing {idx + 1}/{total}: {name} @ {company}…")
        status_box.markdown(f"**Current:** {name} @ {company} ({city}, {state})")

        result = {
            "lead": lead,
            "enrichment": {},
            "scoring": {},
            "email": {},
            "email_sent": None,
            "email_error": None,
            "pipeline_error": None,
        }

        step_box = st.empty()
        lead_num = int(idx) + 1

        def _step(label: str) -> None:
            # Reformat "[N/6] description" → "Lead X/Y · Step N/6: description"
            # Labels without a bracket prefix (e.g. "Sending demo email…") get
            # "Lead X/Y · description" so context is always visible.
            if label.startswith("[") and "/6]" in label:
                bracket_end = label.index("]") + 1
                step_part = label[1:bracket_end - 1]   # e.g. "3/6"
                desc = label[bracket_end:].strip()
                formatted = f"Lead {lead_num}/{total} · Step {step_part}: {desc}"
            else:
                formatted = f"Lead {lead_num}/{total} · {label}"
            step_box.markdown(f"   ⏳ **{formatted}**")

        try:
            enrichment = _enrich_with_steps(lead, _step)
            icp_result = enrichment.get("icp")

            _step("[5/6] Scoring lead…")
            scoring = score_lead(enrichment, icp_result=icp_result)

            _step(f"[6/6] Generating outreach email for {name}…")
            email = generate_outreach_email(lead, enrichment, scoring)

            result["enrichment"] = enrichment
            result["scoring"] = scoring
            result["email"] = email

            if send_emails and config.DEMO_RECIPIENT_EMAIL:
                subject = email.get("subject", f"Reaching out about {company}")
                body = email.get("body", "")
                _step("Sending demo email…")
                send_result = send_email(
                    to_email=config.DEMO_RECIPIENT_EMAIL,
                    subject=subject,
                    body=body,
                    original_recipient=lead.get("email", ""),
                )
                time.sleep(2)
                result["email_sent"] = send_result["success"]
                result["email_error"] = send_result.get("error")

        except Exception as exc:
            result["pipeline_error"] = str(exc)

        step_box.empty()

        results.append(result)

        # Live log line
        tier = result["scoring"].get("tier", "?") if result["scoring"] else "error"
        score = result["scoring"].get("score", "—") if result["scoring"] else "—"
        emoji = TIER_EMOJI.get(tier, "⚠️")
        with log_container:
            st.markdown(f"{emoji} **{name}** — Score: {score} | Tier: {tier}")

    progress_bar.progress(100, text="Done!")
    status_box.empty()

    st.session_state.results = results
    st.session_state.processed = True
    st.success(f"✅ Processed {total} lead(s). Scroll down for results.")


# ---------------------------------------------------------------------------
# Results rendering
# ---------------------------------------------------------------------------

def render_results(results: list[dict], send_emails: bool) -> None:
    """Render summary metrics, sortable table, and per-lead expander cards."""
    st.divider()
    step_header(3, "Results", "Leads sorted by score — hottest first")

    # Compute tier counts from the nested scoring dict
    scored = [r for r in results if r.get("scoring")]
    hot  = sum(1 for r in scored if r["scoring"].get("tier") == "Hot")
    warm = sum(1 for r in scored if r["scoring"].get("tier") == "Warm")
    cold = sum(1 for r in scored if r["scoring"].get("tier") == "Cold")

    # --- Summary metrics (st.metric — always renders correctly) ---
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("📋 Total Leads", len(results))
    with col2: st.metric("🔥 Hot (70-100)", hot)
    with col3: st.metric("🌤 Warm (40-69)", warm)
    with col4: st.metric("❄️ Cold (0-39)", cold)

    st.divider()

    # --- Results table ---
    table_rows = []
    for r in results:
        lead    = r.get("lead", {})
        scoring = r.get("scoring", {})
        email   = r.get("email", {})
        table_rows.append({
            "Name":    lead.get("name", ""),
            "Company": lead.get("company", ""),
            "City":    lead.get("city", ""),
            "State":   lead.get("state", ""),
            "Score":   scoring.get("score", 0) if scoring else 0,
            "Tier":    scoring.get("tier", "—") if scoring else "error",
            "Subject": email.get("subject", "") if email else "",
        })

    table_df = pd.DataFrame(table_rows).sort_values("Score", ascending=False)
    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "Tier":    st.column_config.TextColumn("Tier"),
            "Subject": st.column_config.TextColumn("Subject", width="large"),
        },
    )

    st.divider()
    st.markdown("### 🔍 Lead Details")

    sorted_results = sorted(
        results,
        key=lambda r: r.get("scoring", {}).get("score", 0) if r.get("scoring") else 0,
        reverse=True,
    )

    for idx, r in enumerate(sorted_results):
        lead            = r.get("lead", {})
        scoring         = r.get("scoring", {})
        enrichment      = r.get("enrichment", {})
        email           = r.get("email", {})
        pipeline_error  = r.get("pipeline_error")

        name    = lead.get("name", "Unknown")
        company = lead.get("company", "Unknown")
        score   = scoring.get("score", 0) if scoring else 0
        tier    = scoring.get("tier", "Cold") if scoring else "Cold"

        # Tier colour palette — inline so no CSS class needed
        colors = {
            "Hot":  {"border": "#f85149", "bg": "rgba(248,81,73,0.08)",  "text": "#f85149"},
            "Warm": {"border": "#d29922", "bg": "rgba(210,153,34,0.08)", "text": "#d29922"},
            "Cold": {"border": "#388bfd", "bg": "rgba(56,139,253,0.08)", "text": "#388bfd"},
        }
        c = colors.get(tier, colors["Cold"])

        # ICP data
        icp_data    = enrichment.get("icp") or {}
        icp_match   = icp_data.get("icp_match", "UNCERTAIN")
        company_size = icp_data.get("company_size", "UNKNOWN")
        icp_desc    = icp_data.get("description", "")

        icp_styles = {
            "YES":       ("✓ ICP Match",    "#2ea043", "rgba(46,160,67,0.15)"),
            "NO":        ("✗ ICP Mismatch", "#f85149", "rgba(248,81,73,0.15)"),
            "UNCERTAIN": ("? Verify ICP",   "#d29922", "rgba(210,153,34,0.15)"),
        }
        icp_label, icp_color, icp_bg = icp_styles.get(icp_match, icp_styles["UNCERTAIN"])

        tier_emoji = "🔥" if tier == "Hot" else "🌤" if tier == "Warm" else "❄️"
        expander_label = f"{tier_emoji} {name} @ {company} — {score}/100 ({tier})"

        with st.expander(expander_label):

            if pipeline_error:
                st.error(f"Pipeline error: {pipeline_error}")
                continue

            census       = enrichment.get("census") or {}
            hud          = enrichment.get("hud") or {}
            news         = enrichment.get("news") or {}
            company_news = news.get("company_news") or {}

            # ── Card header (inline styles — no CSS class dependency) ──────
            desc_html = (
                f'<div style="margin-top:0.8rem; padding:0.7rem; background:rgba(0,0,0,0.2); '
                f'border-radius:6px; font-size:0.83rem; color:#8b949e; font-style:italic;">'
                f'{_html.escape(icp_desc)}</div>'
                if icp_desc else ""
            )
            st.markdown(
                f"""
                <div style="background:{c['bg']}; border:1px solid {c['border']};
                            border-left:4px solid {c['border']}; border-radius:10px;
                            padding:1.2rem; margin-bottom:1rem;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <div style="font-size:1rem; font-weight:700; color:#f0f6fc;">
                                {_html.escape(name)} &nbsp;·&nbsp; {_html.escape(company)}
                            </div>
                            <div style="font-size:0.83rem; color:#8b949e; margin-top:0.25rem;">
                                {_html.escape(lead.get('city',''))}, {_html.escape(lead.get('state',''))}
                                &nbsp;·&nbsp; {_html.escape(company_size.title())} operator
                            </div>
                            <div style="margin-top:0.5rem;">
                                <span style="background:{icp_bg}; color:{icp_color};
                                             border:1px solid {icp_color}; padding:0.15rem 0.6rem;
                                             border-radius:999px; font-size:0.72rem; font-weight:600;">
                                    {icp_label}
                                </span>
                            </div>
                        </div>
                        <div style="background:{c['bg']}; border:2px solid {c['border']};
                                    border-radius:50%; width:54px; height:54px;
                                    display:flex; align-items:center; justify-content:center;
                                    font-size:1.1rem; font-weight:800; color:{c['text']};
                                    flex-shrink:0;">
                            {score}
                        </div>
                    </div>
                    {desc_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── Market Signals (st.metric — always works) ──────────────────
            st.markdown("**📊 Market Signals**")
            m1, m2, m3, m4 = st.columns(4)
            units  = census.get("housing_units")
            renter = census.get("renter_percentage")
            fmr    = hud.get("fmr_2br")
            with m1:
                st.metric("Housing Units", f"{int(units):,}" if units else "N/A")
            with m2:
                st.metric("Renter %", f"{renter}%" if renter is not None else "N/A")
            with m3:
                st.metric("2BR FMR", f"${fmr:,}" if fmr else "N/A")
            with m4:
                st.metric("News Articles", company_news.get("article_count", 0))

            # ── Score Reasoning (st.info — always works) ───────────────────
            reasoning = scoring.get("reasoning", "") if scoring else ""
            if reasoning:
                st.markdown("**🎯 Score Reasoning**")
                st.info(reasoning)

            # ── Sales Insights (plain st.markdown bullets) ─────────────────
            insights_raw = scoring.get("sales_insights", []) if scoring else []
            if insights_raw:
                st.markdown("**💡 Sales Insights**")
                if isinstance(insights_raw, str):
                    insight_list = [i.strip().lstrip("•").strip() for i in insights_raw.split("|") if i.strip()]
                else:
                    insight_list = insights_raw
                for insight in insight_list:
                    if insight:
                        st.markdown(f"• {insight}")

            # ── Outreach Email (st.text_area — always works) ───────────────
            st.markdown("**✉️ Generated Outreach Email**")
            if email and email.get("success"):
                subject = email.get("subject", "")
                body    = email.get("body", "")
            else:
                first_name = name.split()[0]
                subject = f"Reaching out about {company}"
                body = (
                    f"Hi {first_name}, I'd love to connect about how EliseAI "
                    f"can help {company}. Worth a 15-min chat?"
                )
                err = email.get("error", "Unknown error") if email else "Email generation failed"
                st.warning(f"Email generation failed: {err}", icon="⚠️")

            st.markdown(f"**Subject:** `{subject}`")
            st.text_area(
                "Email body (click to select all, then copy):",
                value=body,
                height=220,
                key=f"email_{name.replace(' ', '_')}_{idx}",
                label_visibility="collapsed",
            )

            # ── Email send status ──────────────────────────────────────────
            if send_emails:
                email_sent = r.get("email_sent")
                if email_sent is True:
                    st.success("✉️ Demo email sent successfully")
                elif email_sent is False:
                    st.error(f"✗ Email send failed: {r.get('email_error')}")

            # ── Quick Actions — LinkedIn URLs ──────────────────────────────
            st.markdown("**🔗 Quick Actions**")
            linkedin = build_linkedin_urls(name, company)
            qa1, qa2, qa3 = st.columns(3)
            with qa1:
                st.link_button(
                    "👤 Find on LinkedIn",
                    url=linkedin["person_search"],
                    use_container_width=True,
                )
            with qa2:
                st.link_button(
                    "🏢 Company Page",
                    url=linkedin["company_page"],
                    use_container_width=True,
                )
            with qa3:
                st.link_button(
                    "🎯 Sales Navigator",
                    url=linkedin["sales_nav"],
                    use_container_width=True,
                )

    # Export section
    st.divider()
    _render_download_button(results)


# ---------------------------------------------------------------------------
# Download (data logic UNCHANGED)
# ---------------------------------------------------------------------------

def _render_download_button(results: list[dict]) -> None:
    """Build the enriched CSV and offer it as a download."""
    step_header(4, "Export", "Download enriched CSV for your CRM")

    st.markdown(
        "Download the fully enriched leads CSV with all scores, ICP classifications, "
        "market data, and generated emails."
    )

    rows = []
    for r in results:
        lead        = r.get("lead", {})
        scoring     = r.get("scoring", {}) or {}
        enrichment  = r.get("enrichment", {}) or {}
        email       = r.get("email", {}) or {}

        census       = enrichment.get("census") or {}
        hud          = enrichment.get("hud") or {}
        news         = enrichment.get("news") or {}
        company_news = news.get("company_news") or {}
        icp          = enrichment.get("icp") or {}

        if email.get("success"):
            subject = email.get("subject", "")
            body    = email.get("body", "")
        else:
            first_name = lead.get("name", "there").split()[0]
            company    = lead.get("company", "your company")
            subject    = f"Reaching out about {company}"
            body = (
                f"Hi {first_name}, I'd love to connect about how EliseAI can "
                f"help {company}. Worth a 15-min chat?"
            )

        linkedin = build_linkedin_urls(lead.get("name", ""), lead.get("company", ""))
        rows.append({
            **lead,
            "lead_score":              scoring.get("score", 0),
            "tier":                    scoring.get("tier", "Cold"),
            "score_reasoning":         scoring.get("reasoning", ""),
            "sales_insights":          " | ".join(scoring.get("sales_insights", [])),
            "outreach_subject":        subject,
            "outreach_email":          body,
            "housing_units":           census.get("housing_units"),
            "renter_percentage":       census.get("renter_percentage"),
            "median_income":           census.get("median_income"),
            "fmr_2br":                 hud.get("fmr_2br"),
            "metro_name":              hud.get("metro_name"),
            "company_news_count":      company_news.get("article_count", 0),
            "enrichment_errors":       ", ".join(enrichment.get("error_summary", [])),
            "icp_match":               icp.get("icp_match", ""),
            "company_size":            icp.get("company_size", ""),
            "company_description":     icp.get("description", ""),
            "email_sent":              r.get("email_sent"),
            "linkedin_person_search":  linkedin["person_search"],
            "linkedin_company_page":   linkedin["company_page"],
            "linkedin_sales_nav":      linkedin["sales_nav"],
        })

    out_df    = pd.DataFrame(rows).sort_values("lead_score", ascending=False)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"enriched_leads_{timestamp}.csv"

    st.download_button(
        label="📥 Download Enriched CSV",
        data=out_df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
        type="primary",
    )
    st.caption(f"Will download as: `{filename}`")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="EliseAI Lead Enrichment",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # CSS MUST BE FIRST — before any other st call
    st.markdown(_CSS, unsafe_allow_html=True)

    init_session_state()

    # Page header — all inline styles, zero CSS class dependency
    st.markdown(
        """
        <div style="margin-bottom:2rem; padding-bottom:1.5rem; border-bottom:1px solid #21262d;">
            <h1 style="font-size:2.2rem; font-weight:800; color:#f0f6fc;
                       margin:0 0 0.3rem 0; letter-spacing:-0.02em;">
                🏢 EliseAI Lead Enrichment
            </h1>
            <p style="color:#8b949e; font-size:0.95rem; margin:0;">
                AI-powered top-of-funnel automation — enrich, score, and personalize outreach for inbound leads
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ How it works", expanded=False):
        st.markdown("""
        1. **Upload** a CSV of inbound leads (name, company, city, state, etc.)
        2. **Enrich** — each lead is researched across four sources:
           - 🏛️ **US Census ACS** → total housing units, renter %, median income
           - 🏠 **HUD Fair Market Rents** → metro-level 2BR rental prices
           - 📰 **NewsAPI** → recent press about the company and local real estate market
           - 🤖 **Claude ICP Classifier** → is this company in EliseAI's ideal customer profile?
        3. **Score** — a 0–100 market quality score is calculated; ICP non-matches are gated to Cold
        4. **Email** — a personalized cold outreach email is generated by Claude (Anthropic)
        5. **Optionally send** — demo emails are routed to your inbox (never to real recipients)
        """)

    send_emails, limit = render_sidebar()
    df = render_upload_section()

    if df is not None:
        st.divider()
        if st.button(
            "🚀 Enrich & Score Leads",
            type="primary",
            use_container_width=True,
            help=f"Will process up to {limit} lead(s). Adjust in the sidebar.",
        ):
            st.session_state.processed = False
            st.session_state.results = []
            process_leads_with_ui(df, send_emails, limit)

    if st.session_state.get("processed") and st.session_state.get("results"):
        render_results(st.session_state.results, send_emails)

    st.divider()
    st.caption("EliseAI GTM Engineer Practical Assignment — Built with Streamlit")


if __name__ == "__main__":
    main()
