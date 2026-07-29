"""Authentication: scrypt password hashing (stdlib) + JWT bearer tokens."""
import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from .db import execute, query

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return secrets.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_buddy_code():
    alphabet = string.ascii_uppercase + string.digits
    return "HB-" + "".join(secrets.choice(alphabet) for _ in range(6))


def issue_token(user_id):
    """Short-lived access token, sent as a Bearer header on every API call."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=current_app.config["ACCESS_TOKEN_EXPIRY_MINUTES"]),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"],
                      algorithm=current_app.config["JWT_ALGORITHM"])


def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_refresh_token(user_id, device_label=None):
    """Long-lived opaque token, stored (hashed) server-side so it can be
    looked up, rotated, and revoked. This is what keeps the user signed in
    across app restarts without re-entering their password — the client
    trades it in at /auth/refresh whenever the access token has expired."""
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=current_app.config["REFRESH_TOKEN_EXPIRY_DAYS"])
    execute(
        "INSERT INTO sessions (user_id, token_hash, device_label, expires_at) VALUES (?,?,?,?)",
        (user_id, _hash_token(raw), device_label, expires_at.isoformat()))
    return raw


def verify_refresh_token(raw):
    """Return the matching, still-valid session row, or None."""
    if not raw:
        return None
    session = query("SELECT * FROM sessions WHERE token_hash=?", (_hash_token(raw),), one=True)
    if session is None or session["revoked_at"] is not None:
        return None
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return session


def rotate_refresh_token(session, device_label=None):
    """Issue a fresh refresh token for the same session and invalidate the
    old one (rotation). Also slides the expiry forward, so an actively used
    app effectively never signs the user out."""
    execute("UPDATE sessions SET revoked_at=datetime('now') WHERE id=?", (session["id"],))
    return issue_refresh_token(session["user_id"], device_label or session["device_label"])


def revoke_refresh_token(raw):
    """Used on explicit logout — deletes the ability to refresh from this device."""
    session = verify_refresh_token(raw)
    if session is not None:
        execute("UPDATE sessions SET revoked_at=datetime('now') WHERE id=?", (session["id"],))
    return session is not None


def device_label_from_request():
    ua = request.headers.get("User-Agent", "")
    return ua[:120] if ua else None


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Sign in to continue."), 401
        try:
            payload = jwt.decode(header[7:], current_app.config["SECRET_KEY"],
                                 algorithms=[current_app.config["JWT_ALGORITHM"]])
        except jwt.ExpiredSignatureError:
            return jsonify(error="Your session expired. Sign in again to pick up where you left off."), 401
        except jwt.InvalidTokenError:
            return jsonify(error="Sign in to continue."), 401
        user = query("SELECT * FROM users WHERE id=?", (int(payload["sub"]),), one=True)
        if user is None:
            return jsonify(error="Account not found."), 401
        g.user = user
        return f(*args, **kwargs)
    return wrapper
