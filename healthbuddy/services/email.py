"""Password-reset email delivery.

No transactional email provider (SendGrid/SES/SMTP/etc) is configured yet,
so `send_password_reset` currently just logs the link server-side. Swap the
body of that one function for a real provider call when you're ready -
nothing else in the app needs to change, since routes/api.py only calls
`send_password_reset` and never touches the token format directly.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..db import execute, query


def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_reset_token(user_id):
    """Issues a single-use, short-lived token. Only its hash is stored, same
    pattern as refresh tokens in auth.py, so a leaked DB row alone can't be
    used to reset anyone's password."""
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["RESET_TOKEN_EXPIRY_MINUTES"])
    execute(
        "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?,?,?)",
        (user_id, _hash_token(raw), expires_at.isoformat()))
    return raw


def consume_reset_token(raw):
    """Validates and immediately marks the token used. Returns the user_id on
    success, or None if the token is missing, unknown, already used, or expired."""
    if not raw:
        return None
    row = query("SELECT * FROM password_resets WHERE token_hash=?", (_hash_token(raw),), one=True)
    if row is None or row["used_at"] is not None:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (row["id"],))
    return row["user_id"]


def send_password_reset(email_addr, token):
    """Stub delivery layer - logs the reset link instead of emailing it.
    Replace this body with a real provider call (SendGrid, SES, SMTP, etc)
    when one is available; keep the function signature the same."""
    link = f"(configure HB_APP_URL) /#reset-password?token={token}"
    current_app.logger.info(
        "[password reset] %s -> token=%s link=%s "
        "(no email provider configured - see services/email.py)",
        email_addr, token, link)
