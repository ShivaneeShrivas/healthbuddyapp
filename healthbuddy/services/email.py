"""Password-reset flow: 6-digit OTP codes, actually emailed.

A code is short-lived, single-use, and scoped to one user (looked up by
email) so a 6-digit space can't be brute-forced across the whole user
base - see RESET_CODE_MAX_ATTEMPTS in config.py for the per-code guess
limit. Delivery goes through services/mailer.py (real SMTP); if no SMTP
provider is configured, routes/api.py falls back to returning the code
directly in the response so local/dev testing still works end-to-end.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..db import execute, query
from . import mailer


def _hash_code(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_reset_code(user_id):
    """Issues a fresh 6-digit code, invalidating any earlier unused codes
    for this user first so only the latest one is ever valid."""
    execute("UPDATE password_resets SET used_at=datetime('now') "
            "WHERE user_id=? AND used_at IS NULL", (user_id,))
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["RESET_TOKEN_EXPIRY_MINUTES"])
    execute(
        "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?,?,?)",
        (user_id, _hash_code(code), expires_at.isoformat()))
    return code


def verify_reset_code(user_id, code):
    """Validates a code for a specific user. Returns (ok, error_message).
    Wrong guesses are counted per-code; too many locks that code out early
    (the user just has to request a fresh one) so 6 digits can't be
    brute-forced by spamming this endpoint."""
    row = query(
        "SELECT * FROM password_resets WHERE user_id=? AND used_at IS NULL "
        "ORDER BY id DESC LIMIT 1", (user_id,), one=True)
    max_attempts = current_app.config["RESET_CODE_MAX_ATTEMPTS"]
    if row is None:
        return False, "That code is invalid or has expired. Request a new one."
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return False, "That code has expired. Request a new one."
    if row["attempts"] >= max_attempts:
        return False, "Too many incorrect attempts. Request a new code."
    if not secrets.compare_digest(row["token_hash"], _hash_code(code)):
        execute("UPDATE password_resets SET attempts=attempts+1 WHERE id=?", (row["id"],))
        left = max_attempts - (row["attempts"] + 1)
        if left <= 0:
            return False, "Too many incorrect attempts. Request a new code."
        return False, f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left."
    execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (row["id"],))
    return True, None


def send_password_reset(email_addr, code):
    """Emails the OTP code. Returns True if it was actually sent via a
    configured SMTP provider, False if not (caller decides whether to fall
    back to exposing the code directly, e.g. in local dev)."""
    subject = "Your HealthBuddy password reset code"
    text_body = (
        f"Your HealthBuddy password reset code is: {code}\n\n"
        f"This code expires in {current_app.config['RESET_TOKEN_EXPIRY_MINUTES']} minutes "
        "and can only be used once.\n\n"
        "If you didn't request this, you can safely ignore this email - "
        "your password won't be changed."
    )
    html_body = f"""
    <div style="font-family:sans-serif;max-width:420px;margin:auto">
      <h2 style="color:#FF5C8A">HealthBuddy</h2>
      <p>Your password reset code is:</p>
      <p style="font-size:32px;font-weight:800;letter-spacing:6px;
                background:#f4f4f8;padding:16px 20px;border-radius:12px;
                text-align:center;color:#1C1526">{code}</p>
      <p style="color:#666">This code expires in
        {current_app.config['RESET_TOKEN_EXPIRY_MINUTES']} minutes and can only be used once.</p>
      <p style="color:#999;font-size:13px">Didn't request this? You can safely ignore this
        email — your password won't be changed.</p>
    </div>"""
    sent = mailer.send_email(email_addr, subject, text_body, html_body)
    if not sent:
        current_app.logger.info("[password reset] %s -> code=%s (not emailed - see services/mailer.py)",
                                 email_addr, code)
    return sent
