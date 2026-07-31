"""Password-reset AND registration-OTP email delivery.

No transactional email provider (SendGrid/SES/SMTP/etc) is configured yet,
so `send_password_reset` and `send_otp` currently just log server-side.
Swap the body of those two functions for a real provider call when you're
ready - nothing else in the app needs to change, since routes/api.py only
calls these two functions and never touches the token/code format directly.
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


def _hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()


def create_otp(user_id):
    """Issues a fresh 6-digit code, invalidating any earlier unused ones for
    this user first so only the latest code is ever valid."""
    execute("UPDATE email_otps SET used_at=datetime('now') WHERE user_id=? AND used_at IS NULL",
            (user_id,))
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["OTP_EXPIRY_MINUTES"])
    execute("INSERT INTO email_otps (user_id, code_hash, expires_at) VALUES (?,?,?)",
            (user_id, _hash_code(code), expires_at.isoformat()))
    return code


def verify_otp(user_id, code):
    """Returns 'ok' | 'invalid' | 'expired' | 'locked'. A wrong guess counts
    against OTP_MAX_ATTEMPTS on the current code before it's locked out,
    which the person can get past by requesting a fresh code (create_otp
    above invalidates the locked one)."""
    row = query("""SELECT * FROM email_otps WHERE user_id=? AND used_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""", (user_id,), one=True)
    if row is None:
        return "invalid"
    if row["attempts"] >= current_app.config["OTP_MAX_ATTEMPTS"]:
        return "locked"
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return "expired"
    if not code or _hash_code(code.strip()) != row["code_hash"]:
        execute("UPDATE email_otps SET attempts = attempts + 1 WHERE id=?", (row["id"],))
        return "invalid"
    execute("UPDATE email_otps SET used_at=datetime('now') WHERE id=?", (row["id"],))
    return "ok"


def send_otp(email_addr, code):
    """Stub delivery layer - logs the code instead of emailing it. Replace
    with a real provider call when one is available; keep the signature."""
    current_app.logger.info(
        "[email verification] %s -> code=%s (expires in %s min; no email "
        "provider configured - see services/email.py)",
        email_addr, code, current_app.config["OTP_EXPIRY_MINUTES"])
