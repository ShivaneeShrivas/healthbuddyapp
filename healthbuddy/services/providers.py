"""Providers — normalized storage for device data + integration permissions.

Cross-platform architecture (matches the client-side provider interfaces):

  CLIENT ADAPTERS (in static/providers.js)      SERVER (this file)
  ------------------------------------------    -------------------------------
  AndroidActivityProvider  (Health Connect) ┐
  IOSActivityProvider      (HealthKit)      ├─→  POST /api/activity/sync ─→ activity_daily
  WebActivityProvider      (unavailable)    │        (normalized: steps, source, date)
  ManualActivityProvider   (user types it)  ┘

The server never cares which OS sent the data — everything lands in one
normalized table with a `source` column ('health_connect', 'healthkit',
'manual', 'web'). Same pattern for screen time (DeviceWellbeingProvider).

Privacy rules enforced here:
- Nothing is stored unless the integration is 'connected' or the user
  submits manually (manual submission implies consent for that entry).
- Revoking sets status + keeps the audit timestamp; data can be wiped too.
- Steps/screen time are never exposed to buddies or leaderboards.
"""
from datetime import date
from ..db import query, execute

INTEGRATIONS = {
    "activity":   {"label": "Activity / Steps", "emoji": "🚶",
                   "why": "Step count lets HealthBuddy skip movement reminders you've already earned, and cheer at the right moments."},
    "screen_time": {"label": "Screen Time", "emoji": "📱",
                    "why": "Screen-time awareness powers gentle look-away and wind-down nudges. Never judgement, just nudges."},
    "notifications": {"label": "Notifications", "emoji": "🔔",
                      "why": "Lets HealthBuddy actually reach you with its (respectfully rationed) personality."},
    "period_care": {"label": "Period Care", "emoji": "🌸",
                    "why": "Cycle predictions and supportive phase-aware reminders. Private by default, deletable anytime."},
}
VALID_SOURCES = {"health_connect", "healthkit", "device_sensor", "android_usage", "manual", "web", "other"}


def statuses(user_id):
    """Current status of every integration for the permissions center."""
    rows = {r["integration_type"]: r for r in query(
        "SELECT * FROM integrations WHERE user_id=?", (user_id,))}
    user = query("SELECT notif_enabled FROM users WHERE id=?", (user_id,), one=True)
    cycle_on = query("SELECT enabled FROM cycle_settings WHERE user_id=?",
                     (user_id,), one=True)
    out = []
    for key, meta in INTEGRATIONS.items():
        if key == "notifications":
            status = "connected" if user and user["notif_enabled"] else "disconnected"
        elif key == "period_care":
            status = "connected" if cycle_on and cycle_on["enabled"] else "not_connected"
        else:
            r = rows.get(key)
            status = r["status"] if r else "not_connected"
        out.append({"key": key, **meta, "status": status})
    return out


def set_status(user_id, integration_type, status):
    if integration_type not in ("activity", "screen_time"):
        raise ValueError("Unknown integration.")
    if status not in ("connected", "revoked", "not_connected"):
        raise ValueError("Status must be connected, revoked, or not_connected.")
    ts_field = "granted_at" if status == "connected" else "revoked_at"
    execute(f"""INSERT INTO integrations (user_id, integration_type, status, {ts_field})
                VALUES (?,?,?,datetime('now'))
                ON CONFLICT(user_id, integration_type)
                DO UPDATE SET status=excluded.status, {ts_field}=datetime('now')""",
            (user_id, integration_type, status))


def is_connected(user_id, integration_type):
    r = query("SELECT status FROM integrations WHERE user_id=? AND integration_type=?",
              (user_id, integration_type), one=True)
    return bool(r and r["status"] == "connected")


def upsert_activity(user_id, steps, source="manual", day=None, active_minutes=0):
    """Normalized write for any platform adapter. Manual entries always allowed
    (typing a number IS consent); automatic sources require connected status."""
    if source not in VALID_SOURCES:
        raise ValueError("Unknown activity source.")
    if source not in ("manual",) and not is_connected(user_id, "activity"):
        raise PermissionError("Activity integration isn't connected.")
    steps = int(steps)
    if not (0 <= steps <= 200000):
        raise ValueError("That step count looks off.")
    day = day or date.today().isoformat()
    execute("""INSERT INTO activity_daily (user_id, date, steps, active_minutes, source, last_synced_at)
               VALUES (?,?,?,?,?,datetime('now'))
               ON CONFLICT(user_id, date) DO UPDATE SET
                 steps=excluded.steps, active_minutes=excluded.active_minutes,
                 source=excluded.source, last_synced_at=datetime('now')""",
            (user_id, day, steps, int(active_minutes or 0), source))


def upsert_wellbeing(user_id, screen_minutes, source="manual", day=None):
    if source not in VALID_SOURCES:
        raise ValueError("Unknown screen-time source.")
    if source not in ("manual",) and not is_connected(user_id, "screen_time"):
        raise PermissionError("Screen-time integration isn't connected.")
    mins = int(screen_minutes)
    if not (0 <= mins <= 1440):
        raise ValueError("Screen time must be between 0 and 1440 minutes.")
    day = day or date.today().isoformat()
    execute("""INSERT INTO device_wellbeing_daily (user_id, date, screen_time_minutes, source, last_synced_at)
               VALUES (?,?,?,?,datetime('now'))
               ON CONFLICT(user_id, date) DO UPDATE SET
                 screen_time_minutes=excluded.screen_time_minutes,
                 source=excluded.source, last_synced_at=datetime('now')""",
            (user_id, day, mins, source))


def today_activity(user_id):
    return query("SELECT * FROM activity_daily WHERE user_id=? AND date=?",
                 (user_id, date.today().isoformat()), one=True)


def today_wellbeing(user_id):
    return query("SELECT * FROM device_wellbeing_daily WHERE user_id=? AND date=?",
                 (user_id, date.today().isoformat()), one=True)
