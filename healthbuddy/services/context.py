"""UserContext — the app's single source of truth for personalization.

Every feature that decides "what should this user see right now" reads from
here instead of querying tables directly. Nudge selection, the notification
engine, and the daily plan all consume the same context, which is what makes
HealthBuddy feel like one companion instead of five disconnected features.

Add a new signal in ONE place (here) and every consumer can use it.
All signals are optional: missing data means the key is None/absent, never a
fake value — consumers must handle absence gracefully.
"""
from datetime import date, datetime
from ..db import query
from . import cycle as cycle_svc


def build(user_id, now=None):
    now = now or datetime.now()
    today = date.today().isoformat()
    user = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user:
        return None

    ctx = {
        "user_id": user_id,
        "now": now,
        "hour": now.hour,
        "is_weekend": now.weekday() >= 5,
        "profile": {
            "name": user["name"], "gender": user["gender"],
            "occupation": user["occupation"], "activity_level": user["activity_level"],
            "health_goal": user["health_goal"],
            "health_goals": (user["health_goals"] or user["health_goal"] or "").split(",")
                            if (user["health_goals"] or user["health_goal"]) else [],
            "age_range": user["age_range"], "avatar": user["avatar"],
            "step_goal": user["step_goal"] or 8000,
            "notif_enabled": bool(user["notif_enabled"]),
            "quiet_start": user["quiet_start"], "quiet_end": user["quiet_end"],
        },
    }

    # --- today's habit logs ---
    logs = query("""SELECT type, COUNT(*) AS n, COALESCE(SUM(value),0) AS total
                    FROM habit_logs WHERE user_id=? AND logged_on=? GROUP BY type""",
                 (user_id, today))
    h = {r["type"]: r for r in logs}
    ctx["today"] = {
        "water_glasses": int(h["water"]["total"]) if "water" in h else 0,
        "meals": h["meal"]["n"] if "meal" in h else 0,
        "sleep_logged": "sleep" in h,
        "sleep_hours": h["sleep"]["total"] if "sleep" in h else None,
        "mood_logged": "mood" in h,
    }

    # --- activity (steps): None means "no data", never fake zero ---
    act = query("SELECT * FROM activity_daily WHERE user_id=? AND date=?",
                (user_id, today), one=True)
    ctx["steps"] = act["steps"] if act else None
    ctx["steps_source"] = act["source"] if act else None
    goal = ctx["profile"]["step_goal"]
    ctx["steps_pct"] = round(ctx["steps"] / goal * 100) if ctx["steps"] is not None and goal else None
    ctx["step_goal_hit"] = ctx["steps"] is not None and ctx["steps"] >= goal

    # --- screen time ---
    wb = query("SELECT * FROM device_wellbeing_daily WHERE user_id=? AND date=?",
               (user_id, today), one=True)
    ctx["screen_minutes"] = wb["screen_time_minutes"] if wb else None

    # --- nudge interaction patterns ---
    ctx["acted_today"] = query(
        """SELECT COUNT(*) AS n FROM interaction_logs
           WHERE user_id=? AND action='acted' AND date(created_at)=?""",
        (user_id, today), one=True)["n"]
    ctx["recent_api_hits"] = query(
        """SELECT COUNT(*) AS n FROM interaction_logs
           WHERE user_id=? AND created_at >= datetime('now','-45 minutes')""",
        (user_id,), one=True)["n"]
    # Categories the user keeps dismissing lately → consumers soft-suppress these.
    ctx["fatigued_categories"] = [r["category"] for r in query(
        """SELECT category FROM interaction_logs
           WHERE user_id=? AND action='dismissed'
             AND created_at >= datetime('now','-7 days')
           GROUP BY category HAVING COUNT(*) >= 3""", (user_id,))]

    # --- games ---
    ctx["daily_game_played"] = query(
        """SELECT 1 FROM game_scores WHERE user_id=? AND is_daily=1 AND played_on=?""",
        (user_id, today), one=True) is not None

    # --- cycle (only if Period Care enabled; absent otherwise) ---
    ctx["cycle"] = None
    try:
        ctx["cycle"] = cycle_svc.status(user_id)
    except LookupError:
        pass

    return ctx
