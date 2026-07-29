"""Gamification engine: XP economy, level curve, streaks, badges."""
from datetime import date, timedelta
from ..db import query, execute
from ..config import Config

HABIT_TYPES = ["water", "meal", "sleep", "mood"]

BADGES = [
    {"code": "first_steps",   "emoji": "👟", "name": "First Steps",     "desc": "Completed onboarding. Your journey starts here!"},
    {"code": "first_sip",     "emoji": "💧", "name": "First Sip",       "desc": "Logged your first glass of water."},
    {"code": "nudge_ninja",   "emoji": "🥷", "name": "Nudge Ninja",     "desc": "Acted on 10 nudges."},
    {"code": "hydration_hero","emoji": "🌊", "name": "Hydration Hero",  "desc": "7-day water streak."},
    {"code": "dream_weaver",  "emoji": "🌙", "name": "Dream Weaver",    "desc": "Logged sleep 5 days in a row."},
    {"code": "mood_mapper",   "emoji": "🎨", "name": "Mood Mapper",     "desc": "Logged your mood 7 times."},
    {"code": "level_5",       "emoji": "⭐", "name": "Rising Star",     "desc": "Reached level 5."},
    {"code": "challenger",    "emoji": "🏆", "name": "Challenger",      "desc": "Joined your first challenge."},
    {"code": "social_bee",    "emoji": "🐝", "name": "Social Bee",      "desc": "Linked up with a buddy."},
    {"code": "week_one",      "emoji": "🔥", "name": "One Week Strong", "desc": "Kept any streak alive for 7 days."},
    {"code": "brain_spark",   "emoji": "🧠", "name": "Brain Spark",     "desc": "Played your first mind game."},
    {"code": "quick_reflex",  "emoji": "⚡", "name": "Quick Reflex",    "desc": "Reaction time under 300 ms."},
    {"code": "sharp_mind",    "emoji": "🎯", "name": "Sharp Mind",      "desc": "Completed 5 daily brain challenges."},
    {"code": "wrapped_fan",   "emoji": "🎁", "name": "Wrapped Fan",     "desc": "Checked out your first Weekly Wrapped."},
    {"code": "self_care",     "emoji": "🌸", "name": "Self Care",       "desc": "Set up Period Care — looking out for yourself."},
]


def award_xp(user_id, reason):
    amount = Config.XP.get(reason, 0)
    if amount:
        execute("INSERT INTO xp_events (user_id, amount, reason) VALUES (?,?,?)", (user_id, amount, reason))
    return amount


def total_xp(user_id):
    row = query("SELECT COALESCE(SUM(amount),0) AS xp FROM xp_events WHERE user_id = ?", (user_id,), one=True)
    return row["xp"]


def level_for(xp):
    """Gentle square-root curve: L1→0, L2→60, L3→240, L4→540, L5→960 XP."""
    level = 1
    while xp_needed(level + 1) <= xp:
        level += 1
    return level


def xp_needed(level):
    return 60 * (level - 1) ** 2


def level_progress(xp):
    lvl = level_for(xp)
    lo, hi = xp_needed(lvl), xp_needed(lvl + 1)
    return {"level": lvl, "xp": xp, "current_floor": lo, "next_at": hi,
            "progress": round((xp - lo) / (hi - lo), 3)}


def streak(user_id, habit_type):
    """Consecutive days (ending today or yesterday) with at least one log."""
    rows = query(
        "SELECT DISTINCT logged_on FROM habit_logs WHERE user_id = ? AND type = ? ORDER BY logged_on DESC",
        (user_id, habit_type),
    )
    days = {r["logged_on"] for r in rows}
    today = date.today()
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while cursor.isoformat() in days:
        n += 1
        cursor -= timedelta(days=1)
    return n


def all_streaks(user_id):
    return {t: streak(user_id, t) for t in HABIT_TYPES}


def _has_badge(user_id, code):
    return query("SELECT 1 FROM user_badges WHERE user_id=? AND badge_code=?", (user_id, code), one=True) is not None


def _grant(user_id, code):
    if not _has_badge(user_id, code):
        execute("INSERT INTO user_badges (user_id, badge_code) VALUES (?,?)", (user_id, code))
        return next(b for b in BADGES if b["code"] == code)
    return None


def award_badge(user_id, code):
    """Directly grant one badge (used by feature services). Returns [badge] or []."""
    b = _grant(user_id, code)
    return [b] if b else []


def check_and_award(user_id):
    """Evaluate badge predicates; return list of newly earned badges."""
    new = []
    counts = {r["type"]: r["n"] for r in query(
        "SELECT type, COUNT(*) AS n FROM habit_logs WHERE user_id=? GROUP BY type", (user_id,))}
    acted = query("SELECT COUNT(*) AS n FROM interaction_logs WHERE user_id=? AND action='acted'",
                  (user_id,), one=True)["n"]
    streaks = all_streaks(user_id)

    checks = [
        ("first_sip", counts.get("water", 0) >= 1),
        ("nudge_ninja", acted >= 10),
        ("hydration_hero", streaks["water"] >= 7),
        ("dream_weaver", streaks["sleep"] >= 5),
        ("mood_mapper", counts.get("mood", 0) >= 7),
        ("level_5", level_for(total_xp(user_id)) >= 5),
        ("week_one", max(streaks.values()) >= 7),
        ("challenger", query("SELECT 1 FROM challenge_members WHERE user_id=?", (user_id,), one=True) is not None),
        ("social_bee", query("SELECT 1 FROM buddies WHERE user_id=?", (user_id,), one=True) is not None),
    ]
    for code, ok in checks:
        if ok:
            b = _grant(user_id, code)
            if b:
                new.append(b)
    return new


def profile(user_id):
    earned = {r["badge_code"]: r["earned_at"] for r in
              query("SELECT badge_code, earned_at FROM user_badges WHERE user_id=?", (user_id,))}
    badges = [{**b, "earned": b["code"] in earned, "earned_at": earned.get(b["code"])} for b in BADGES]
    return {**level_progress(total_xp(user_id)), "badges": badges, "streaks": all_streaks(user_id)}
