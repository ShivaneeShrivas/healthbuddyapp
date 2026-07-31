"""Weekly Health Wrapped — Spotify-Wrapped-style weekly recap.

Aggregates the last 7 days into a sequence of story "cards" the frontend
animates. Insight strings are template-based today; swap generate_insights()
for an LLM call later without touching anything else.
"""
from datetime import date, timedelta
from ..db import query
from ..config import CATEGORY_META
from . import gamification, games as games_svc


def _week_range(today=None):
    end = today or date.today()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _daily_breakdown(user_id, start, end):
    """Per-day 0-100 scores across the week, for the mini bar chart on the
    first Wrapped slide — same weighting as the home-screen ring, just
    grouped by day instead of only "today"."""
    rows = query(
        """SELECT logged_on, type, COUNT(*) AS n, COALESCE(SUM(value),0) AS total
           FROM habit_logs WHERE user_id=? AND logged_on BETWEEN ? AND ?
           GROUP BY logged_on, type""", (user_id, start, end))
    by_day = {}
    for r in rows:
        by_day.setdefault(r["logged_on"], {})[r["type"]] = {"n": r["n"], "total": r["total"]}

    start_d = date.fromisoformat(start)
    out = []
    for i in range(7):
        d = start_d + timedelta(days=i)
        iso = d.isoformat()
        day = by_day.get(iso, {})
        water = min(day.get("water", {}).get("total", 0) or 0, 8)
        meals = min(day.get("meal", {}).get("n", 0), 3)
        sleep_hours = day.get("sleep", {}).get("total")
        mood_logged = day.get("mood", {}).get("n", 0) > 0
        score = round(water / 8 * 25) + round(meals / 3 * 15) \
            + (20 if sleep_hours and 7 <= sleep_hours <= 9 else (10 if sleep_hours else 0)) \
            + (10 if mood_logged else 0)
        out.append({"date": iso, "weekday": d.strftime("%a")[0], "score": min(score, 100),
                    "logged": bool(day)})
    return out


def build(user_id):
    start, end = _week_range()

    logs = query("""SELECT type, COUNT(*) AS n, COALESCE(SUM(value),0) AS total,
                           COUNT(DISTINCT logged_on) AS days
                    FROM habit_logs WHERE user_id=? AND logged_on BETWEEN ? AND ?
                    GROUP BY type""", (user_id, start, end))
    h = {r["type"]: r for r in logs}
    water_glasses = int(h.get("water", {"total": 0})["total"] or 0)
    meals = h.get("meal", {"n": 0})["n"]
    sleep_rows = query("""SELECT value FROM habit_logs
                          WHERE user_id=? AND type='sleep' AND logged_on BETWEEN ? AND ?""",
                       (user_id, start, end))
    sleep_vals = [r["value"] for r in sleep_rows if r["value"]]
    avg_sleep = round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else 0
    mood_rows = query("""SELECT value FROM habit_logs
                         WHERE user_id=? AND type='mood' AND logged_on BETWEEN ? AND ?""",
                      (user_id, start, end))
    mood_vals = [r["value"] for r in mood_rows if r["value"]]
    avg_mood = round(sum(mood_vals) / len(mood_vals), 1) if mood_vals else 0

    inter = query("""SELECT action, COUNT(*) AS n FROM interaction_logs
                     WHERE user_id=? AND date(created_at) BETWEEN ? AND ? GROUP BY action""",
                  (user_id, start, end))
    acts = {r["action"]: r["n"] for r in inter}
    acted = acts.get("acted", 0)

    top_cat = query("""SELECT c.category, COUNT(*) AS n
                       FROM interaction_logs il JOIN notification_cards c ON c.id = il.card_id
                       WHERE il.user_id=? AND il.action='acted' AND date(il.created_at) BETWEEN ? AND ?
                       GROUP BY c.category ORDER BY n DESC LIMIT 1""",
                    (user_id, start, end), one=True)

    xp_week = query("""SELECT COALESCE(SUM(amount),0) AS xp FROM xp_events
                       WHERE user_id=? AND date(created_at) BETWEEN ? AND ?""",
                    (user_id, start, end), one=True)["xp"]
    badges_week = query("""SELECT b.badge_code FROM user_badges b
                           WHERE b.user_id=? AND date(b.earned_at) BETWEEN ? AND ?""",
                        (user_id, start, end))
    badge_codes = [r["badge_code"] for r in badges_week]
    badge_meta = [b for b in gamification.BADGES if b["code"] in badge_codes]

    gstats = games_svc.stats(user_id)
    brain = gstats["brain_score"]
    streaks = gamification.all_streaks(user_id)

    # Rough weekly health score: same weights as the daily score, on averages.
    health = round(min(water_glasses / (7 * 8), 1) * 25 + min(meals / (7 * 3), 1) * 15
                   + (20 if 7 <= avg_sleep <= 9 else 10 if avg_sleep else 0)
                   + (avg_mood / 5) * 10 + min(acted / 7, 3) * 10)

    daily = _daily_breakdown(user_id, start, end)
    best_day = max(daily, key=lambda d: d["score"]) if daily else None
    active_days = sum(1 for d in daily if d["logged"])

    return {
        "range": {"start": start, "end": end},
        "health_score": health,
        "daily": daily,
        "best_day": best_day,
        "active_days": active_days,
        "brain_score": brain,
        "hydration": {"glasses": water_glasses, "days": h.get("water", {"days": 0})["days"]},
        "nutrition": {"meals": meals},
        "sleep": {"avg_hours": avg_sleep, "nights": len(sleep_vals)},
        "mood": {"avg": avg_mood, "checkins": len(mood_vals)},
        "movement_note": "Step tracking arrives with the phone app — for now Movement nudges carry the flag.",
        "nudges": {"acted": acted, "opened": acts.get("opened", 0),
                   "top_category": (top_cat and {
                       "key": top_cat["category"], **CATEGORY_META[top_cat["category"]],
                       "count": top_cat["n"]}) or None},
        "games": {"plays": sum(g["plays"] for g in gstats["games"]),
                  "best_skill": max(gstats["games"], key=lambda g: g["plays"])["skill"]
                                if any(g["plays"] for g in gstats["games"]) else None,
                  "trends": [{"label": g["label"], "emoji": g["emoji"], "trend_pct": g["trend_pct"]}
                             for g in gstats["games"] if g["trend_pct"] is not None]},
        "xp": xp_week,
        "badges": badge_meta,
        "streaks": streaks,
        "insights": generate_insights(water_glasses, avg_sleep, acted, brain, streaks),
        "goals": generate_goals(water_glasses, avg_sleep, meals, brain),
    }


def generate_insights(water, sleep, acted, brain, streaks):
    ins = []
    if water >= 40:
        ins.append("Certified hydration icon — %d glasses this week. Your skin noticed." % water)
    elif water:
        ins.append("%d glasses of water logged. Next week, let's sneak in a few more." % water)
    if sleep >= 7:
        ins.append("Averaging %.1f h of sleep — your brain's night shift thanks you." % sleep)
    elif sleep:
        ins.append("Sleep averaged %.1f h. One earlier night this week could change everything." % sleep)
    if acted >= 5:
        ins.append("You acted on %d nudges. That's momentum, not luck." % acted)
    if brain >= 60:
        ins.append("Brain score %d — the mind games are clearly rated E for Effective." % brain)
    best = max(streaks, key=streaks.get)
    if streaks[best] >= 3:
        ins.append("Longest streak: %d days of %s. Keep the chain alive!" % (streaks[best], best))
    return ins[:4] or ["Quiet week — and that's okay. Wrapped looks better with data; log a little and see."]


def generate_goals(water, sleep, meals, brain):
    goals = []
    goals.append({"emoji": "💧", "text": "Hit %d glasses of water" % min(max(water + 5, 20), 56)})
    if sleep < 7:
        goals.append({"emoji": "😴", "text": "Two nights of 7+ hours"})
    else:
        goals.append({"emoji": "😴", "text": "Keep that sleep rhythm going"})
    if meals < 15:
        goals.append({"emoji": "🍽️", "text": "Log 2 meals a day"})
    goals.append({"emoji": "🧠", "text": "Beat one personal best in Mind Games"
                  if brain else "Try your first Mind Game"})
    return goals[:4]
