# EliseAI GTM Enrichment Tool

Automates inbound lead enrichment, scoring, and personalized outreach email generation for EliseAI's sales team.

🚀 **Live demo:** https://app-slideshow-jndy5ejfrhhgipxdxotomc.streamlit.app/

📂 **Project plan:** [PROJECT_PLAN.md](PROJECT_PLAN.md)

## What it does

For each inbound lead (name, email, company, city), the tool:
1. Fetches city demographics from the US Census API
2. Fetches fair market rents from the HUD API
3. Searches for recent company and city real estate news via NewsAPI
4. Scores the lead 0–100 based on market quality signals
5. Assigns a tier (Hot / Warm / Cold)
6. Generates a personalized outreach email via Claude

## Sample output

A pre-run enriched CSV is included at [`data/sample_output.csv`](data/sample_output.csv) — 5 realistic leads across Austin TX, Newark NJ, Miami FL, Boise ID, and Liberal KS. Open it to see exactly what the tool produces without running anything.

## Non-US leads

The Census and HUD APIs are US-only. If a lead has `country` set to anything other than `US` / `USA`, the tool skips those two data sources and logs a clear warning instead of silently returning zeros. NewsAPI and the Claude ICP classifier still run normally, so non-US leads get a score based on company profile and news coverage only.

## Setup

### 1. Clone and enter the project
```bash
git clone <repo-url>
cd eliseai_tool
```

### 2. Activate the virtual environment
```bash
source eliseai_tool/bin/activate   # macOS/Linux
eliseai_tool\Scripts\activate      # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure API keys
```bash
cp .env.example .env
```
Edit `.env` and fill in your keys:

| Key | Where to get it |
|-----|-----------------|
| `CENSUS_API_KEY` | https://api.census.gov/data/key_signup.html (free) |
| `NEWS_API_KEY` | https://newsapi.org/register (free tier available) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| `HUD_API_KEY` | Not required for public HUD endpoints |

## Usage

### One-off run
```bash
python main.py --input data/sample_leads.csv --output results/enriched.csv
```

### Dry run (print to stdout, no file written)
```bash
python main.py --input data/sample_leads.csv --output /dev/null --dry-run
```

### Scheduled runs
```bash
python scheduler.py --input data/sample_leads.csv --output results/enriched.csv --interval 60
```

## Output columns

| Column | Description |
|--------|-------------|
| `lead_score` | 0–100 market quality score |
| `tier` | Hot (70–100) / Warm (40–69) / Cold (0–39) |
| `score_reasoning` | Why the score is what it is |
| `sales_insights` | Key talking points for the SDR |
| `outreach_email` | Personalized email draft |

## Scoring logic

Scores are **tiered within each signal** (not binary) to create spread between mid-market and top-market leads. The base signals sum to a maximum of 90; an ICP size bonus adds up to 10 more, capped at 100.

### ICP gate
If Claude classifies the company as **outside EliseAI's ICP** (e.g. industrial REIT, single-family only), all signals are skipped and the lead is hard-set to **score 15 / tier Cold**.

### Base signals (max 90 pts)

| Signal | Tiers | Max pts |
|--------|-------|---------|
| Housing units in city | ≥ 300k → 25 · ≥ 100k → 18 · ≥ 50k → 10 · < 50k → 4 | 25 |
| Renter-occupied % | > 50% → 20 · ≥ 40% → 12 · < 40% → 5 | 20 |
| Median household income | > $75k → 10 · ≥ $60k → 7 · < $60k → 3 | 10 |
| 2BR Fair Market Rent | > $1,800 → 20 · ≥ $1,400 → 12 · < $1,400 → 5 · no data → 0 | 20 |
| Company news articles | ≥ 3 → 10 · ≥ 1 → 5 · 0 → −5 | 10 |
| City real estate news | ≥ 1 article → 5 · none → 0 | 5 |

### ICP size bonus (max +10 pts)

| Company size (Claude classification) | Bonus |
|--------------------------------------|-------|
| LARGE (10,000+ units / NMHC top 50) | +10 |
| MEDIUM (500–9,999 units) | +6 |
| SMALL (< 500 units) | +2 |
| UNKNOWN | +0 |

### Tier cutoffs

| Tier | Score range |
|------|-------------|
| 🔥 Hot | 70–100 |
| 🌤 Warm | 40–69 |
| ❄️ Cold | 0–39 |

### Assumptions documented
- **FMR missing = 0 pts** (not 5): absence of HUD metro coverage is itself a negative signal — likely a rural/non-MSA market.
- **No company news = −5 pts**: a property manager with zero press coverage is less likely to be actively growing.
- **ICP classification** uses Claude with company name + recent news headlines as context.
