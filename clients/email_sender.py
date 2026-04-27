"""Gmail SMTP email sender — DEMO MODE ONLY.

Safety contract enforced in code:
  - Every outgoing email goes to DEMO_RECIPIENT_EMAIL from config, never to the
    lead's real address. send_email() raises ValueError immediately if the caller
    tries to pass any other recipient.
  - The lead's original address appears only in the subject prefix:
    [DEMO → real@address.com] <actual subject>
  - A plaintext footer is appended to every body explaining this is a demo.

To use Gmail SMTP you need an App Password (not your login password):
  Google Account → Security → 2-Step Verification → App passwords
  Generate a 16-character password for "Mail" and set it as GMAIL_APP_PASSWORD.
"""

import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import config


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(
    to_email: str,
    subject: str,
    body: str,
    original_recipient: Optional[str] = None,
) -> dict:
    """Send an email via Gmail SMTP.

    SAFETY: to_email must always equal config.DEMO_RECIPIENT_EMAIL. This is
    enforced with a hard ValueError — no exceptions.

    Args:
        to_email:           Actual recipient. Must be config.DEMO_RECIPIENT_EMAIL.
        subject:            Email subject line (auto-prefixed with demo tag).
        body:               Plain-text email body.
        original_recipient: The lead's real email address — shown in the subject
                            prefix and footer, never used as an actual recipient.

    Returns:
        {"success": True,  "error": None,          "sent_to": "you@gmail.com"}
        {"success": False, "error": "description", "sent_to": None}

    Raises:
        ValueError: Immediately if to_email != DEMO_RECIPIENT_EMAIL. This is
                    intentional — a wrong recipient is a bug, not a runtime error.
    """
    # ------------------------------------------------------------------ #
    # SAFETY GUARD — must be the first thing that runs, before any I/O   #
    # ------------------------------------------------------------------ #
    if not config.DEMO_RECIPIENT_EMAIL:
        return {
            "success": False,
            "error": "DEMO_RECIPIENT_EMAIL is not set in .env — refusing to send",
            "sent_to": None,
        }

    if to_email != config.DEMO_RECIPIENT_EMAIL:
        raise ValueError(
            f"Safety violation: attempted to send to '{to_email}' but "
            f"DEMO_RECIPIENT_EMAIL is '{config.DEMO_RECIPIENT_EMAIL}'. "
            "send_email() must always be called with config.DEMO_RECIPIENT_EMAIL "
            "as the recipient — never with a lead's real address."
        )
    # ------------------------------------------------------------------ #

    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        return {
            "success": False,
            "error": "GMAIL_USER or GMAIL_APP_PASSWORD not set in .env",
            "sent_to": None,
        }

    # Build subject with demo prefix
    if original_recipient:
        full_subject = f"[DEMO → {original_recipient}] {subject}"
    else:
        full_subject = f"[DEMO] {subject}"

    # Build body with demo footer
    if original_recipient:
        footer = (
            "\n\n---\n"
            f"[This is a demo email. In production, this would have been sent to: {original_recipient}]"
        )
    else:
        footer = "\n\n---\n[This is a demo email.]"

    full_body = body + footer

    # Assemble MIME message
    msg = MIMEMultipart()
    msg["From"] = config.GMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = full_subject
    msg.attach(MIMEText(full_body, "plain"))

    # Send via STARTTLS
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_USER, to_email, msg.as_string())

        return {"success": True, "error": None, "sent_to": to_email}

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "Gmail authentication failed — check GMAIL_USER and GMAIL_APP_PASSWORD in .env",
            "sent_to": None,
        }
    except smtplib.SMTPRecipientsRefused:
        return {
            "success": False,
            "error": f"Recipient refused by Gmail: {to_email}",
            "sent_to": None,
        }
    except smtplib.SMTPException as exc:
        return {"success": False, "error": f"SMTP error: {exc}", "sent_to": None}
    except OSError as exc:
        return {"success": False, "error": f"Network error: {exc}", "sent_to": None}


if __name__ == "__main__":
    print("Testing email_sender.send_email()...")
    print(f"  Sending to: {config.DEMO_RECIPIENT_EMAIL}")

    result = send_email(
        to_email=config.DEMO_RECIPIENT_EMAIL,
        subject="EliseAI outreach — test send",
        body=(
            "Hi Jordan,\n\n"
            "Saw that Greystar recently expanded its Austin portfolio.\n\n"
            "With 449,452 housing units and 55% renters, Austin is one of the top "
            "multifamily markets in the US — EliseAI's leasing automation can help "
            "your team handle that volume without adding headcount.\n\n"
            "Worth a 15-min chat next week?"
        ),
        original_recipient="test@fakecompany.com",
    )

    if result["success"]:
        print(f"  ✓ Sent successfully to {result['sent_to']}")
        print("  Check your inbox — subject will show: [DEMO → test@fakecompany.com] EliseAI outreach — test send")
    else:
        print(f"  ✗ Send failed: {result['error']}")
