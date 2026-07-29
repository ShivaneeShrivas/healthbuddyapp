"""Period Care: cycle tracking, adaptive prediction, phase-aware nudges.

Privacy notes
-------------
- Data lives only in our DB; nothing leaves unless the user turns on the
  optional Google Calendar export (which shares predicted dates only).
- The feature is invisible unless enabled: every endpoint 404s for users who
  haven't opted in, and delete_all() wipes everything on request.
- Predictions learn from the user's own history (rolling average of the last
  6 recorded cycles) instead of assuming a fixed 28-day cycle.
"""
from datetime import date, timedelta
from ..db import query, execute

MAX_HISTORY = 6          # cycles used in the rolling average
CYCLE_BOUNDS = (15, 60)  # sanity range for a plausible cycle length, days
PERIOD_BOUNDS = (1, 12)

PHASES = {
    "menstrual":  {"emoji": "🌸", "label": "Menstrual",  "color": "#FF5C8A"},
    "follicular": {"emoji": "🌱", "label": "Follicular", "color": "#7ED957"},
    "ovulation":  {"emoji": "🌼", "label": "Ovulation",  "color": "#FFD166"},
    "luteal":     {"emoji": "🌙", "label": "Luteal",     "color": "#B39DFF"},
}

# Cute, supportive, deliberately non-medical copy — keyed by phase.
PHASE_NUDGES = {
    "pre": [  # 2-3 days before predicted start
        ("🛍️", "Stock-up run?", "Your period's likely in the next couple of days. Grab pads/tampons and maybe that dark chocolate now — future you says thanks."),
        ("🧺", "Comfy prep", "Period's probably around the corner. Cozy clothes washed? Hot water bag findable? Small prep, big comfort."),
    ],
    "menstrual": [
        ("🍫", "Chocolate is self-care", "Dark chocolate day. It's basically medicinal right now. Enjoy a square (or three)."),
        ("🥬", "Iron things out", "Your body's working hard — spinach, dal, or jaggery today helps top up iron. Mess salad counter has your back."),
        ("💧", "Extra hydration", "Cramps hate water. Sip a little more than usual today — warm water counts double for comfort."),
        ("🧘", "Gentle mode: ON", "Rest is productive today. A slow stretch or a nap beats pushing through. Be soft with yourself."),
    ],
    "follicular": [
        ("⚡", "Energy window", "Energy tends to climb in this phase — great week to start something new or take that longer walk."),
    ],
    "ovulation": [
        ("🌼", "Peak power days", "Many people feel their strongest around now. Good day for that workout you've been postponing."),
    ],
    "luteal": [
        ("🍵", "Wind-down week", "PMS can sneak in around now. Warm drinks, lighter evenings, and early sleep are your friends."),
        ("🧂", "Snack smart", "Cravings hitting? Salty + sweet is the classic combo — pair it with fruit or nuts so energy stays steady."),
    ],
}


def _settings(user_id):
    return query("SELECT * FROM cycle_settings WHERE user_id = ?", (user_id,), one=True)


def is_enabled(user_id):
    s = _settings(user_id)
    return bool(s and s["enabled"])


def setup(user_id, last_period_start, avg_cycle_len=28, avg_period_len=5,
          remind=True, gcal_export=False):
    """Enable Period Care. Validates inputs; idempotent upsert."""
    try:
        start = date.fromisoformat(str(last_period_start))
    except (TypeError, ValueError):
        raise ValueError("That date doesn't look right — use YYYY-MM-DD.")
    if start > date.today():
        raise ValueError("Last period start can't be in the future.")
    cycle = float(avg_cycle_len or 28)
    period = float(avg_period_len or 5)
    if not (CYCLE_BOUNDS[0] <= cycle <= CYCLE_BOUNDS[1]):
        raise ValueError(f"Cycle length should be between {CYCLE_BOUNDS[0]} and {CYCLE_BOUNDS[1]} days.")
    if not (PERIOD_BOUNDS[0] <= period <= PERIOD_BOUNDS[1]):
        raise ValueError(f"Period length should be between {PERIOD_BOUNDS[0]} and {PERIOD_BOUNDS[1]} days.")
    execute("""INSERT INTO cycle_settings
                 (user_id, enabled, last_period_start, avg_cycle_len, avg_period_len, remind, gcal_export)
               VALUES (?,1,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET enabled=1, last_period_start=excluded.last_period_start,
                 avg_cycle_len=excluded.avg_cycle_len, avg_period_len=excluded.avg_period_len,
                 remind=excluded.remind, gcal_export=excluded.gcal_export,
                 updated_at=datetime('now')""",
            (user_id, start.isoformat(), cycle, period, int(bool(remind)), int(bool(gcal_export))))
    execute("INSERT OR IGNORE INTO cycle_history (user_id, start_date) VALUES (?,?)",
            (user_id, start.isoformat()))


def log_period_start(user_id, start_date=None):
    """Record an actual period start and re-learn the average cycle length."""
    s = _settings(user_id)
    if not s or not s["enabled"]:
        raise LookupError
    start = date.fromisoformat(str(start_date)) if start_date else date.today()
    if start > date.today():
        raise ValueError("That start date is in the future.")
    execute("INSERT OR IGNORE INTO cycle_history (user_id, start_date) VALUES (?,?)",
            (user_id, start.isoformat()))
    # Rolling average over the gaps between the last MAX_HISTORY+1 starts.
    rows = query("""SELECT start_date FROM cycle_history WHERE user_id = ?
                    ORDER BY start_date DESC LIMIT ?""", (user_id, MAX_HISTORY + 1))
    dates = sorted(date.fromisoformat(r["start_date"]) for r in rows)
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])
            if CYCLE_BOUNDS[0] <= (b - a).days <= CYCLE_BOUNDS[1]]
    avg_cycle = round(sum(gaps) / len(gaps), 1) if gaps else s["avg_cycle_len"]
    execute("""UPDATE cycle_settings SET last_period_start = ?, avg_cycle_len = ?,
               updated_at = datetime('now') WHERE user_id = ?""",
            (max(dates).isoformat(), avg_cycle, user_id))
    return avg_cycle


def status(user_id, today=None):
    """Everything the dashboard card + check-in needs."""
    s = _settings(user_id)
    if not s or not s["enabled"]:
        raise LookupError
    today = today or date.today()
    last = date.fromisoformat(s["last_period_start"])
    cycle_len = max(s["avg_cycle_len"], 1)
    period_len = s["avg_period_len"]

    days_since = (today - last).days
    cycle_day = days_since % round(cycle_len) + 1 if days_since >= 0 else 1
    next_period = last
    while next_period <= today:
        next_period += timedelta(days=round(cycle_len))
    days_left = (next_period - today).days

    # Phase from cycle_day: menstrual → follicular → ovulation window → luteal
    ovu_day = round(cycle_len) - 14
    if cycle_day <= period_len:
        phase = "menstrual"
    elif abs(cycle_day - ovu_day) <= 1:
        phase = "ovulation"
    elif cycle_day < ovu_day:
        phase = "follicular"
    else:
        phase = "luteal"

    checkin_due = days_since >= round(cycle_len)  # predicted date reached, no new log yet
    history_n = query("SELECT COUNT(*) AS n FROM cycle_history WHERE user_id = ?",
                      (user_id,), one=True)["n"]
    return {
        "phase": phase, "phase_meta": PHASES[phase],
        "cycle_day": cycle_day,
        "next_period": next_period.isoformat(),
        "days_left": days_left,
        "avg_cycle_len": s["avg_cycle_len"],
        "avg_period_len": period_len,
        "remind": bool(s["remind"]),
        "gcal_export": bool(s["gcal_export"]),
        "checkin_due": checkin_due,
        "cycles_recorded": history_n,
        "prediction_note": ("Learning from your last %d cycles." % history_n) if history_n > 1
                           else "Predictions sharpen after your next check-in.",
    }


def phase_nudge(user_id):
    """A supportive nudge for the current phase (or the pre-period window)."""
    st = status(user_id)
    key = "pre" if 0 < st["days_left"] <= 3 else st["phase"]
    pool = PHASE_NUDGES.get(key) or PHASE_NUDGES[st["phase"]]
    emoji, title, body = pool[date.today().toordinal() % len(pool)]
    return {"emoji": emoji, "title": title, "body": body,
            "category": "period_care", "category_label": "Period Care",
            "color": "#FF5C8A", "action_label": "Noted 💗"}


def gcal_export_payload(user_id, months=3):
    """Predicted period start dates for the next few cycles — only ever built
    when the user has explicitly enabled export. Returned to the client, which
    performs the Google Calendar OAuth flow; the server never talks to Google."""
    s = _settings(user_id)
    if not s or not s["enabled"] or not s["gcal_export"]:
        raise LookupError
    st = status(user_id)
    cycle = round(max(s["avg_cycle_len"], 1))
    first = date.fromisoformat(st["next_period"])
    events = []
    for i in range((months * 31) // cycle + 1):
        d = first + timedelta(days=cycle * i)
        events.append({"title": "Period (predicted) 🌸", "start": d.isoformat(),
                       "end": (d + timedelta(days=round(s["avg_period_len"]))).isoformat()})
    return events


def delete_all(user_id):
    """Privacy: wipe every trace of cycle data on request."""
    execute("DELETE FROM cycle_history WHERE user_id = ?", (user_id,))
    execute("DELETE FROM cycle_settings WHERE user_id = ?", (user_id,))
