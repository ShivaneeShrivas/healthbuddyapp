"""Sends real phone/browser push notifications via the standard Web Push
protocol (VAPID). This is the actual "phone buzzes while the app is closed"
delivery layer that DEPLOYMENT.md Phase 2 calls for.

Why Web Push instead of a native Firebase SDK integration: the Android app
is a PWABuilder-wrapped Trusted Web Activity (basically Chrome), so it
already speaks standard Web Push - Chrome relays it through FCM under the
hood automatically. No separate Firebase console project, google-services.json,
or native SDK needed. Same code path serves desktop browsers, mobile browser
installs, and the APK.
"""
import hashlib
import hmac
import json

from flask import current_app
from pywebpush import WebPushException, webpush

from ..db import execute, query


def sign_action(user_id, template_id):
    """A short HMAC so the 'Remind'/'Done' buttons on a system notification
    (fired from the service worker, with no login token available) can prove
    the request is legitimate without needing a full auth flow."""
    secret = current_app.config["SECRET_KEY"].encode()
    msg = f"{user_id}:{template_id}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:24]


def verify_action(user_id, template_id, sig):
    if not user_id or not template_id or not sig:
        return False
    expected = sign_action(user_id, template_id)
    return hmac.compare_digest(expected, sig)


def save_subscription(user_id, subscription, user_agent=None):
    """Upsert a subscription. endpoint is unique per browser+device install,
    so re-subscribing (e.g. after reinstall) just refreshes the row."""
    existing = query("SELECT id FROM push_subscriptions WHERE endpoint=?",
                      (subscription["endpoint"],), one=True)
    keys = subscription.get("keys", {})
    if existing:
        execute("""UPDATE push_subscriptions
                   SET user_id=?, p256dh=?, auth=?, user_agent=?
                   WHERE endpoint=?""",
                (user_id, keys.get("p256dh"), keys.get("auth"), user_agent,
                 subscription["endpoint"]))
        return existing["id"]
    return execute("""INSERT INTO push_subscriptions
                      (user_id, endpoint, p256dh, auth, user_agent)
                      VALUES (?,?,?,?,?)""",
                   (user_id, subscription["endpoint"], keys.get("p256dh"),
                    keys.get("auth"), user_agent))


def remove_subscription(endpoint):
    execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))


def subscriptions_for_user(user_id):
    return query("SELECT * FROM push_subscriptions WHERE user_id=?", (user_id,))


def send_to_subscription(sub_row, payload: dict):
    """Send one push. Returns True on success, False if the subscription is
    dead and was cleaned up (browser unsubscribed, uninstalled, etc)."""
    vapid_private = current_app.config["VAPID_PRIVATE_KEY"]
    vapid_claims = {"sub": current_app.config["VAPID_CLAIM_EMAIL"]}

    if not vapid_private:
        raise RuntimeError(
            "HB_VAPID_PRIVATE_KEY is not set - run generate_vapid_keys.py "
            "and set the env vars before sending push notifications."
        )

    subscription_info = {
        "endpoint": sub_row["endpoint"],
        "keys": {"p256dh": sub_row["p256dh"], "auth": sub_row["auth"]},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_private,
            vapid_claims=dict(vapid_claims),
        )
        execute("UPDATE push_subscriptions SET last_sent_at=datetime('now') WHERE id=?",
                (sub_row["id"],))
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):  # gone / expired - browser unsubscribed
            remove_subscription(sub_row["endpoint"])
        return False


def send_to_user(user_id, payload: dict):
    """Send to every device the user has subscribed on. Returns count sent."""
    sent = 0
    for sub in subscriptions_for_user(user_id):
        if send_to_subscription(sub, payload):
            sent += 1
    return sent
