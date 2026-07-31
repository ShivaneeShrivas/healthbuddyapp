"""Actual email delivery via SMTP.

Configure with standard environment variables and it works with any
SMTP+STARTTLS provider - Gmail (with an App Password), SendGrid, Mailgun,
Amazon SES, Postmark, your own mail server, etc:

    HB_SMTP_HOST      e.g. smtp.gmail.com / smtp.sendgrid.net
    HB_SMTP_PORT      defaults to 587 (STARTTLS)
    HB_SMTP_USER      SMTP username (for SendGrid this is literally "apikey")
    HB_SMTP_PASS      SMTP password / API key
    HB_FROM_EMAIL     the "From" address shown to recipients (defaults to HB_SMTP_USER)

If these aren't set, send_email() safely no-ops and logs instead of
crashing, so local/dev use still works without a mail account.
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app


def is_configured():
    c = current_app.config
    return bool(c.get("SMTP_HOST") and c.get("SMTP_USER") and c.get("SMTP_PASS"))


def send_email(to_addr, subject, text_body, html_body=None):
    """Best-effort send. Returns True if handed off to the SMTP server
    successfully, False otherwise - callers decide how to degrade (e.g.
    falling back to a dev-mode on-screen code) rather than this raising
    and taking down the request."""
    c = current_app.config
    if not is_configured():
        current_app.logger.warning(
            "[mailer] SMTP not configured (set HB_SMTP_HOST / HB_SMTP_USER / "
            "HB_SMTP_PASS) - email to %s NOT sent: %r", to_addr, subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = c.get("FROM_EMAIL") or c["SMTP_USER"]
    msg["To"] = to_addr
    msg.attach(MIMEText(text_body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        port = int(c.get("SMTP_PORT") or 587)
        context = ssl.create_default_context()
        with smtplib.SMTP(c["SMTP_HOST"], port, timeout=10) as server:
            server.starttls(context=context)
            server.login(c["SMTP_USER"], c["SMTP_PASS"])
            server.sendmail(msg["From"], [to_addr], msg.as_string())
        return True
    except Exception:
        current_app.logger.exception("[mailer] failed to send email to %s", to_addr)
        return False
