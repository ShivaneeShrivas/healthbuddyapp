"""Notification engine — composes personalized, situational, fun messages.

Architecture (three layers, only the last differs between now and production):
  1. CONTEXT  — what's true for this user right now (hydration gap, no sleep
                log, time of day, weekend, phase of cycle, game streak...).
  2. COMPOSE  — pick the highest-priority matching templates (this module).
  3. DELIVER  — today: the in-app bell feed (GET /api/notifications).
                production: a scheduler worker calls compose() every ~30 min
                per active user and hands results to FCM/APNs for real phone
                push. Same compose code, different transport.

Quiet hours are enforced HERE so no delivery layer can bypass them.
"""
from datetime import datetime, date
from ..db import query
from . import cycle as cycle_svc

# (id, condition_key, hour_range, weekend_only, emoji, title, body, priority)
# hour_range is inclusive start, exclusive end, 24h. None = any time.
TEMPLATES = [
    # --- screen/eyes/posture: fire on long-session context ---
    ("scroll_bread", "long_session", None, False, "🍞", "Blink break",
     "You've been scrolling long enough to bake bread. Look up for a sec.", 3),
    ("eye_complaint", "long_session", None, False, "👀", "Official complaint",
     "Your eyes have filed an official complaint. Please look at something farther than your phone for 20 seconds.", 3),
    ("spine_memo", "long_session", None, False, "🧍", "Memo from your spine",
     "Your spine would like to remind you that humans are designed to stand occasionally.", 3),
    ("thumb_marathon", "long_session", None, False, "👍", "Marathon update",
     "Congratulations. You've traveled 14 kilometers today... with your thumb.", 2),
    ("brain_buffer", "long_session", None, False, "🧠", "Brain status",
     "Input buffer full. A short walk is recommended.", 2),
    # --- sleep ---
    ("bed_jealous", "late_night", (22, 24), False, "🛏️", "Bed check",
     "Bed's getting jealous of your phone. Just saying.", 5),
    ("sleep_watching", "late_night", (23, 24), False, "😴", "Concerned party",
     "Your sleep schedule is watching this session with concern.", 5),
    ("no_sleep_log", "no_sleep_log", (9, 12), False, "🌙", "Last night?",
     "How'd you sleep? Ten seconds to log it, lifetime of smug streak stats.", 2),
    # --- movement ---
    ("legs_texted", "inactive", (10, 20), False, "🦵", "1 new message",
     "Your legs texted. They said 'we exist.' Please reply with a walk.", 3),
    ("plot_twist", "inactive", (15, 20), False, "🚶", "Plot twist",
     "The walk you don't feel like taking is the one that fixes the mood.", 3),
    # --- hydration ---
    ("water_low", "water_low", (11, 21), False, "💧", "Hydration check",
     "It's so hot today even your ice cream is sweating. Hydrate before you also start melting.", 4),
    # --- food / mess ---
    ("breakfast_intel", "any", (7, 10), False, "🍳", "Breakfast intel",
     "Breakfast: the one meeting you shouldn't skip. Go be a functional human and eat something.", 3),
    ("maggi_upgrade", "any", (19, 23), False, "🍜", "Chef's tip",
     "Maggi again? No shame — just throw an egg on it and call it a nutritional upgrade.", 1),
    # --- seasonal (rain-friendly; swap via weather API later) ---
    ("rain_chai", "any", (16, 19), False, "☕", "Weather report",
     "Rain outside. Chai inside. Sounds like a perfect plan.", 1),
    ("rain_alert", "any", (7, 11), False, "🌦️", "Rain alert",
     "The sky has started washing the city. Stay dry out there!", 1),
    # --- weekend ---
    ("weekend_morning", "any", (9, 12), True, "🥞", "No alarms today",
     "No alarms today, but the day's still yours. Maybe eat something before noon though.", 2),
    # --- steps (only fire when real step data exists — see _context) ---
    ("steps_quiet", "steps_low", (14, 19), False, "👀", "Quiet day for your feet",
     "Been a quiet day for your feet 👀 A 10-minute walk could be a nice little reset.", 4),
    ("steps_close", "steps_near_goal", (12, 21), False, "🚶", "So close!",
     "Only a short walk between you and your step goal. You've got this ✨", 4),
    ("steps_hit", "steps_goal_hit", (12, 22), False, "🔥", "Goal smashed",
     "Step goal reached! Your legs definitely showed up today.", 3),
    # --- screen time (manual or synced; never faked) ---
    ("screen_break", "screen_high", (10, 22), False, "😄", "Attention check",
     "Your screen has had enough attention for a bit 😄 Look away, stretch, and give your eyes a tiny break 👀", 4),
    ("screen_reset", "screen_high", (12, 21), False, "💧", "Quick reset?",
     "Put the phone down for 5 minutes, grab some water, and move around 💧🚶", 3),
    # --- games ---
    ("daily_brain", "daily_game_pending", (12, 22), False, "🧠", "Daily brain challenge",
     "Today's brain challenge is up. Two minutes, bragging rights included.", 2),
]


def _in_quiet_hours(user, now):
    start, end = user["quiet_start"], user["quiet_end"]
    hm = now.strftime("%H:%M")
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end  # window wraps midnight


def _context(user_id, now):
    """Condition flags derived from the central UserContext (services/context.py).
    Every flag is honest: step/screen flags exist only when real data does."""
    from . import context as context_svc
    ctx = context_svc.build(user_id, now)
    if ctx is None:
        return {}
    goal = ctx["profile"]["step_goal"]
    steps = ctx["steps"]  # None = no data → all step flags stay False
    flags = {
        "any": True,
        "water_low": ctx["today"]["water_glasses"] < 4 and now.hour >= 11,
        "no_sleep_log": not ctx["today"]["sleep_logged"],
        "late_night": True,
        "long_session": ctx["recent_api_hits"] >= 6,
        "inactive": ctx["acted_today"] == 0 and not ctx["step_goal_hit"],
        "daily_game_pending": not ctx["daily_game_played"],
        "steps_low": steps is not None and steps < goal * 0.4,
        "steps_near_goal": steps is not None and goal * 0.8 <= steps < goal,
        "steps_goal_hit": bool(ctx["step_goal_hit"]),
        "screen_high": ctx["screen_minutes"] is not None and ctx["screen_minutes"] >= 180,
    }
    # Suppression: if the step goal is hit, generic movement pokes make no sense.
    if ctx["step_goal_hit"]:
        flags["inactive"] = False
        flags["steps_low"] = False
    flags["_fatigued"] = set(ctx.get("fatigued_categories") or [])
    flags["_notif_enabled"] = ctx["profile"]["notif_enabled"]
    return flags


def compose(user_id, now=None, limit=3):
    """Highest-priority matching notifications for this user, right now."""
    now = now or datetime.now()
    user = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user or _in_quiet_hours(user, now):
        return []

    ctx = _context(user_id, now)
    if not ctx or not ctx.get("_notif_enabled", True):
        return []
    is_weekend = now.weekday() >= 5
    picks = []
    for tid, cond, hours, weekend_only, emoji, title, body, prio in TEMPLATES:
        if weekend_only and not is_weekend:
            continue
        if hours and not (hours[0] <= now.hour < hours[1]):
            continue
        if not ctx.get(cond):
            continue
        picks.append({"id": tid, "emoji": emoji, "title": title, "body": body,
                      "priority": prio, "kind": "fun"})

    # Period Care reminders ride the same pipeline (highest priority).
    try:
        st = cycle_svc.status(user_id)
        if st["remind"]:
            if st["checkin_due"]:
                picks.append({"id": "cycle_checkin", "emoji": "🌸",
                              "title": "Quick check-in",
                              "body": "Did your period start today?",
                              "priority": 10, "kind": "cycle_checkin"})
            elif 0 < st["days_left"] <= 3 or st["phase"] == "menstrual":
                n = cycle_svc.phase_nudge(user_id)
                picks.append({"id": "cycle_" + st["phase"], "emoji": n["emoji"],
                              "title": n["title"], "body": n["body"],
                              "priority": 8, "kind": "cycle"})
    except LookupError:
        pass

    picks.sort(key=lambda p: -p["priority"])
    return picks[:limit]
