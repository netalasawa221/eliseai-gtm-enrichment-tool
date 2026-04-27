"""EliseAI GTM Lead Enrichment Tool — CLI entry point.

Reads a CSV of inbound leads, enriches each one with market data and news,
scores them 0–100, generates a personalized outreach email via Claude, and
writes the results to an output CSV sorted by score (hottest leads first).

Example usage:
    # Full run
    python main.py --input data/sample_leads.csv --output data/enriched_leads.csv

    # Dry run (no file written, full pipeline still executes)
    python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --dry-run

    # Process only the first 3 leads (quick testing)
    python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --limit 3

    # Send demo emails (routed to DEMO_RECIPIENT_EMAIL, never to real lead addresses)
    python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --send-emails

    # Send emails, limit to 1 lead for testing
    python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --send-emails --limit 1

Input CSV required columns:
    name, email, company, property_address, city, state, country

Output CSV adds:
    lead_score, tier, score_reasoning, sales_insights, outreach_subject,
    outreach_email, housing_units, renter_percentage, median_income,
    fmr_2br, metro_name, company_news_count, enrichment_errors,
    icp_match, company_size, company_description, email_sent
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd

import config
from clients.email_sender import send_email
from core.enricher import enrich_lead
from core.scorer import score_lead, build_linkedin_urls
from core.email_generator import generate_outreach_email

REQUIRED_COLUMNS = {"name", "email", "company", "property_address", "city", "state", "country"}
DIVIDER = "=" * 60


# ---------------------------------------------------------------------------
# Public pipeline function
# ---------------------------------------------------------------------------

def process_leads(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    limit: Optional[int] = None,
    send_emails: bool = False,
) -> dict:
    """Read leads from CSV, run the full enrichment pipeline, write output CSV.

    Args:
        input_path:   Path to the input CSV file.
        output_path:  Path to write the enriched output CSV.
        dry_run:      If True, skip writing the output file (pipeline still runs).
                      Also suppresses email sending even if send_emails=True.
        limit:        If set, process only the first N leads.
        send_emails:  If True, send each generated email via Gmail SMTP to
                      DEMO_RECIPIENT_EMAIL. Requires GMAIL_USER, GMAIL_APP_PASSWORD,
                      and DEMO_RECIPIENT_EMAIL in .env. Ignored when dry_run=True.

    Returns:
        Summary dict with keys: total, processed, hot, warm, cold,
        leads_with_errors, emails_sent, emails_failed, output_path, dry_run.

    Exits with code 1 if the input file is missing, has wrong columns, or
    email sending is requested but email config vars are not set.
    """
    # --- Load input ---
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(input_path)

    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        print(
            f"Error: input CSV is missing required columns: {sorted(missing_cols)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if limit is not None:
        df = df.head(limit)

    total = len(df)

    # --- Validate email config before touching any leads ---
    will_send = send_emails and not dry_run
    if will_send:
        valid, err = config.validate_email_config()
        if not valid:
            print(f"Error: cannot send emails — {err}", file=sys.stderr)
            sys.exit(1)

    # --- Print header ---
    print(f"\n{DIVIDER}")
    print("  EliseAI Lead Enrichment Tool")
    print(DIVIDER)
    print(f"  Input:  {input_path}")
    print(f"  Output: {'(dry run — no file written)' if dry_run else output_path}")
    print(f"  Leads:  {total}")
    print(DIVIDER)

    if will_send:
        print(f"\n  ⚠  EMAIL SENDING IS ENABLED")
        print(f"  All emails will be routed to: {config.DEMO_RECIPIENT_EMAIL}")
        print(f"  Original recipients appear in subject as [DEMO → email]")
        print(f"  Sleeping 2s between sends to avoid rate limits.")
        print(DIVIDER)

    # --- Process leads ---
    rows: list[dict] = []
    leads_with_errors = 0
    emails_sent = 0
    emails_failed = 0

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        lead = row.to_dict()

        # Validate this row has the critical lookup fields
        if not lead.get("city") or not lead.get("state") or not lead.get("company"):
            print(
                f"\n[{idx}/{total}] SKIPPED: {lead.get('name', '?')} — "
                "missing city, state, or company",
                file=sys.stderr,
            )
            continue

        name = lead.get("name", "Unknown")
        company = lead.get("company", "Unknown")
        city = lead.get("city", "")
        state = lead.get("state", "")

        print(f"\n[{idx}/{total}] Processing: {name} @ {company} ({city}, {state})")

        try:
            enrichment = enrich_lead(lead)
            icp_result = enrichment.get("icp")
            scoring = score_lead(enrichment, icp_result=icp_result)
            email = generate_outreach_email(lead, enrichment, scoring)
        except Exception as exc:
            print(f"  ✗ Pipeline error for {name}: {exc}", file=sys.stderr)
            leads_with_errors += 1
            continue

        if enrichment.get("any_errors"):
            leads_with_errors += 1

        output_row = _build_output_row(lead, enrichment, scoring, email)

        # --- Optionally send email ---
        if will_send:
            lead_email = lead.get("email", "")
            subject = output_row.get("outreach_subject", "")
            body = output_row.get("outreach_email", "")

            send_result = send_email(
                to_email=config.DEMO_RECIPIENT_EMAIL,
                subject=subject,
                body=body,
                original_recipient=lead_email,
            )

            if send_result["success"]:
                emails_sent += 1
                output_row["email_sent"] = True
                print(
                    f"  ✉ Email sent to {config.DEMO_RECIPIENT_EMAIL} "
                    f"(re: {lead_email})"
                )
            else:
                emails_failed += 1
                output_row["email_sent"] = False
                print(f"  ✗ Email send FAILED: {send_result['error']}")

            time.sleep(2)

        rows.append(output_row)

        # Progress summary line
        subject = output_row.get("outreach_subject") or ""
        subject_preview = (subject[:60] + "...") if len(subject) > 60 else subject
        print(
            f"  → Score: {output_row['lead_score']} | "
            f"Tier: {output_row['tier']} | "
            f'"{subject_preview}"'
        )

    # --- Sort and write ---
    if not rows:
        print("\nNo leads were successfully processed.", file=sys.stderr)
        sys.exit(1)

    output_df = pd.DataFrame(rows).sort_values("lead_score", ascending=False)

    if not dry_run:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_df.to_csv(output_path, index=False)

    # --- Summary ---
    _print_summary(
        rows=rows,
        output_path=output_path,
        dry_run=dry_run,
        leads_with_errors=leads_with_errors,
        send_emails=will_send,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
    )

    return {
        "total": total,
        "processed": len(rows),
        "hot": sum(1 for r in rows if r["tier"] == "Hot"),
        "warm": sum(1 for r in rows if r["tier"] == "Warm"),
        "cold": sum(1 for r in rows if r["tier"] == "Cold"),
        "leads_with_errors": leads_with_errors,
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "output_path": output_path,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def _build_output_row(
    lead: dict,
    enrichment: dict,
    scoring: dict,
    email: dict,
) -> dict:
    """Flatten lead + enrichment + scoring + email into a single CSV-ready dict.

    email_sent is initialised to None here. process_leads() updates it to
    True/False after the send attempt (only when --send-emails is active).

    Args:
        lead:       Original lead row dict.
        enrichment: Output of enrich_lead().
        scoring:    Output of score_lead().
        email:      Output of generate_outreach_email().

    Returns:
        Flat dict with all input columns plus all enriched output columns.
    """
    census = enrichment.get("census") or {}
    hud = enrichment.get("hud") or {}
    news = enrichment.get("news") or {}
    company_news = news.get("company_news") or {}
    icp_result = enrichment.get("icp") or {}
    linkedin = build_linkedin_urls(lead.get("name", ""), lead.get("company", ""))

    if email.get("success"):
        outreach_subject = email.get("subject", "")
        outreach_body = email.get("body", "")
    else:
        # Fallback when Claude API is unavailable
        first_name = (lead.get("name") or "there").split()[0]
        company = lead.get("company") or "your company"
        outreach_subject = f"Reaching out about {company}"
        outreach_body = (
            f"Hi {first_name}, I'd love to connect about how EliseAI can help "
            f"{company}. Worth a 15-min chat?"
        )

    return {
        # Original lead columns
        **lead,
        # Scoring
        "lead_score": scoring.get("score", 0),
        "tier": scoring.get("tier", "Cold"),
        "score_reasoning": scoring.get("reasoning", ""),
        "sales_insights": " | ".join(scoring.get("sales_insights", [])),
        # Email
        "outreach_subject": outreach_subject,
        "outreach_email": outreach_body,
        # Flat market data (for CSV readability)
        "housing_units": census.get("housing_units"),
        "renter_percentage": census.get("renter_percentage"),
        "median_income": census.get("median_income"),
        "fmr_2br": hud.get("fmr_2br"),
        "metro_name": hud.get("metro_name"),
        "company_news_count": company_news.get("article_count", 0),
        "enrichment_errors": ", ".join(enrichment.get("error_summary", [])),
        # ICP classification
        "icp_match": icp_result.get("icp_match", ""),
        "company_size": icp_result.get("company_size", ""),
        "company_description": icp_result.get("description", ""),
        # Email send status — updated post-send by process_leads()
        "email_sent": None,
        # LinkedIn quick-access URLs
        "linkedin_person_search": linkedin["person_search"],
        "linkedin_company_page": linkedin["company_page"],
        "linkedin_sales_nav": linkedin["sales_nav"],
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(
    rows: list[dict],
    output_path: str,
    dry_run: bool,
    leads_with_errors: int,
    send_emails: bool = False,
    emails_sent: int = 0,
    emails_failed: int = 0,
) -> None:
    """Print the final summary block after all leads are processed."""
    hot = sum(1 for r in rows if r["tier"] == "Hot")
    warm = sum(1 for r in rows if r["tier"] == "Warm")
    cold = sum(1 for r in rows if r["tier"] == "Cold")

    print(f"\n{DIVIDER}")
    print("  Summary")
    print(DIVIDER)
    print(f"  Total leads processed:  {len(rows)}")
    print(f"  Hot  (70-100):          {hot}")
    print(f"  Warm (40-69):           {warm}")
    print(f"  Cold  (0-39):           {cold}")

    if leads_with_errors:
        print(f"\n  Enrichment errors:      {leads_with_errors} lead(s) had partial API failures")
    else:
        print("\n  Enrichment errors:      none")

    if send_emails:
        print(f"\n  Emails sent:            {emails_sent}")
        print(f"  Emails failed:          {emails_failed}")
    else:
        print(f"\n  Emails skipped:         {len(rows)} (--send-emails not used)")

    if dry_run:
        print("\n  Output:                 dry run — no file written")
    else:
        print(f"\n  Output written to:      {output_path}")

    print(DIVIDER)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "EliseAI GTM Lead Enrichment Tool — enriches inbound leads with "
            "market data, scores them, and generates personalized outreach emails."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --input data/sample_leads.csv --output data/enriched_leads.csv\n"
            "  python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --dry-run\n"
            "  python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --limit 3\n"
            "  python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --send-emails\n"
            "  python main.py --input data/sample_leads.csv --output data/enriched_leads.csv --send-emails --limit 1"
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="PATH",
        help="Path to input CSV (required columns: name, email, company, property_address, city, state, country)",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Path to write enriched output CSV (sorted by score, hottest first)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip writing the output file and suppress email sending",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N leads (useful for quick testing)",
    )
    parser.add_argument(
        "--send-emails",
        action="store_true",
        help=(
            "Send each generated email via Gmail SMTP. "
            "ALL emails are routed to DEMO_RECIPIENT_EMAIL — never to real lead addresses. "
            "Requires GMAIL_USER, GMAIL_APP_PASSWORD, and DEMO_RECIPIENT_EMAIL in .env."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    process_leads(
        input_path=args.input,
        output_path=args.output,
        dry_run=args.dry_run,
        limit=args.limit,
        send_emails=args.send_emails,
    )


if __name__ == "__main__":
    main()
