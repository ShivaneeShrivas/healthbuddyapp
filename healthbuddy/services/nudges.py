"""Nudge pipeline: bandit picks the category, we pick a fresh card, every
interaction is logged (the log doubles as the bandit's reward signal), and the
dashboard health score is computed from the day's activity."""
from datetime import date
from ..db import query, execute
from ..config import Config, CATEGORY_META
from . import bandit, gamification


def _suppressed_categories(user_id):
    """Context-aware vetoes: don't push movement at someone who already smashed
    their step goal; ease off categories the user keeps dismissing."""
    from . import context as context_svc
    ctx = context_svc.build(user_id)
    if not ctx:
        return set()
    out = set(ctx["fatigued_categories"])
    if ctx["step_goal_hit"]:
        out.add("movement")
    return out


def next_nudge(user_id, gender=None):
    skip = _suppressed_categories(user_id)
    category = bandit.select_category(user_id)
    for _ in range(6):  # re-sample around vetoed categories (bandit still learns)
        if category not in skip or len(skip) >= 5:
            break
        category = bandit.select_category(user_id)
    recent = [r["card_id"] for r in query(
        "SELECT card_id FROM interaction_logs WHERE user_id=? AND action='sent' "
        "ORDER BY id DESC LIMIT ?", (user_id, Config.RECENT_CARD_WINDOW))]
    placeholders = ",".join("?" * len(recent)) or "0"
    audience = ("all", gender or "all")
    card = query(
        f"SELECT * FROM notification_cards WHERE category=? AND audience IN (?,?) "
        f"AND id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1",
        (category, *audience, *recent), one=True)
    if card is None:  # small bank fallback: allow repeats
        card = query("SELECT * FROM notification_cards WHERE category=? AND audience IN (?,?) "
                     "ORDER BY RANDOM() LIMIT 1", (category, *audience), one=True)
    if card is None:
        return None
    execute("INSERT INTO interaction_logs (user_id, card_id, category, action) VALUES (?,?,?,'sent')",
            (user_id, card["id"], card["category"]))
    return card_dict(card)


def card_dict(card):
    meta = CATEGORY_META[card["category"]]
    return {
        "id": card["id"], "category": card["category"],
        "category_label": meta["label"], "color": meta["color"],
        "emoji": card["emoji"], "title": card["title"], "body": card["body"],
        "action_label": card["action_label"], "deep_dive": card["deep_dive"],
    }


def interact(user_id, card_id, action):
    if action not in Config.REWARDS:
        raise ValueError("action must be one of: " + ", ".join(Config.REWARDS))
    card = query("SELECT * FROM notification_cards WHERE id=?", (card_id,), one=True)
    if card is None:
        raise LookupError("card not found")
    execute("INSERT INTO interaction_logs (user_id, card_id, category, action) VALUES (?,?,?,?)",
            (user_id, card_id, card["category"], action))
    bandit.update(user_id, card["category"], action)
    xp = 0
    if action == "acted":
        xp = gamification.award_xp(user_id, "nudge_acted")
    elif action == "opened":
        xp = gamification.award_xp(user_id, "nudge_opened")
    result = {"xp_earned": xp, "new_badges": gamification.check_and_award(user_id)}
    if action == "acted":
        from . import daily_plan
        bonus = daily_plan.maybe_award_bonus(user_id)
        if bonus:
            result["xp_earned"] += bonus["bonus_xp"]
            result["daily_plan_bonus"] = bonus["bonus_xp"]
    return result


def feed(user_id, limit=20):
    rows = query(
        "SELECT il.created_at, il.action, nc.* FROM interaction_logs il "
        "JOIN notification_cards nc ON nc.id = il.card_id "
        "WHERE il.user_id=? AND il.action='sent' ORDER BY il.id DESC LIMIT ?",
        (user_id, limit))
    return [{**card_dict(r), "sent_at": r["created_at"]} for r in rows]


def today_summary(user_id):
    today = date.today().isoformat()
    logs = query("SELECT type, COUNT(*) AS n, SUM(value) AS total FROM habit_logs "
                 "WHERE user_id=? AND logged_on=? GROUP BY type", (user_id, today))
    by_type = {r["type"]: {"count": r["n"], "total": r["total"]} for r in logs}
    acted_today = query(
        "SELECT COUNT(*) AS n FROM interaction_logs WHERE user_id=? AND action='acted' "
        "AND date(created_at)=?", (user_id, today), one=True)["n"]
    return by_type, acted_today


def health_score(user_id):
    """0–100 daily score. Transparent, additive components so the ring is
    explainable — no black box for something users see every day."""
    by_type, acted = today_summary(user_id)
    water = min(by_type.get("water", {}).get("total", 0) or 0, 8)
    meals = min(by_type.get("meal", {}).get("count", 0), 3)
    sleep_hours = by_type.get("sleep", {}).get("total")
    mood_logged = by_type.get("mood", {}).get("count", 0) > 0

    components = {
        "hydration": round(water / 8 * 25),
        "meals": round(meals / 3 * 15),
        "sleep": 20 if sleep_hours and 7 <= sleep_hours <= 9 else (10 if sleep_hours else 0),
        "mood": 10 if mood_logged else 0,
        "nudges": min(acted, 3) * 10,
    }
    return {"score": sum(components.values()), "components": components,
            "today": {t: by_type.get(t, {"count": 0, "total": 0}) for t in gamification.HABIT_TYPES},
            "nudges_acted_today": acted}
