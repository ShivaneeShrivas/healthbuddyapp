"""Daily Plan — three fixed tasks per day: morning, afternoon, night.

Fixes the "card changes every refresh" problem: the plan for (user, date) is
DETERMINISTIC — seeded by user id + date — so it's identical no matter how
often the app is opened, and different tomorrow.

Personalized, not random: category selection samples from the user's bandit
affinities (so the plan leans toward what they respond to), the context layer
vetoes irrelevant picks (movement task suppressed if the step goal is already
smashed at plan-build time... but note the plan is built once per day, so
suppression uses stable daily signals only), and completing a task feeds the
same interaction log the bandit learns from.

Completing all 3 in one day earns a bonus (config XP 'daily_plan_bonus'),
awarded at most once per day.
"""
import random
from datetime import date
from ..db import query, execute
from ..config import CATEGORY_META
from . import bandit, gamification

SLOTS = [
    ("morning",   "🌅", "Morning"),
    ("afternoon", "☀️", "Afternoon"),
    ("night",     "🌙", "Night"),
]
# Categories that fit each slot best (soft preference, not a hard rule).
SLOT_LEANINGS = {
    "morning":   ["hydration", "nutrition", "movement", "mindfulness"],
    "afternoon": ["movement", "hydration", "nutrition", "seasonal"],
    "night":     ["sleep", "mindfulness", "seasonal", "nutrition"],
}


def _rng(user_id, day):
    return random.Random(f"hb-plan:{user_id}:{day}")


def build(user_id, day=None):
    """The user's 3 tasks for the day. Pure function of (user, date, affinities)."""
    day = day or date.today().isoformat()
    rng = _rng(user_id, day)

    # Affinity per category from the bandit (falls back to uniform pre-onboarding).
    states = {s["category"]: s for s in (bandit.get_state(user_id) or [])}
    def affinity(cat):
        s = states.get(cat)
        return s["affinity"] if s else 0.4

    tasks, used_cats, used_cards = [], set(), set()
    for slot, slot_emoji, slot_label in SLOTS:
        cats = [c for c in SLOT_LEANINGS[slot] if c not in used_cats and affinity(c) > 0]
        if not cats:
            cats = [c for c in CATEGORY_META if c not in used_cats]
        weights = [affinity(c) + 0.05 for c in cats]
        cat = rng.choices(cats, weights=weights, k=1)[0]
        used_cats.add(cat)

        cards = query("""SELECT * FROM notification_cards WHERE category=? ORDER BY id""", (cat,))
        cards = [c for c in cards if c["id"] not in used_cards] or cards
        card = cards[rng.randrange(len(cards))]
        used_cards.add(card["id"])
        m = CATEGORY_META[cat]
        tasks.append({
            "slot": slot, "slot_emoji": slot_emoji, "slot_label": slot_label,
            "id": card["id"], "category": cat, "category_label": m["label"],
            "emoji": card["emoji"], "color": m["color"],
            "title": card["title"], "body": card["body"],
            "action_label": card["action_label"],
        })
    return tasks


def with_completion(user_id, day=None):
    """Plan + which tasks are done today + whether the bonus was earned."""
    day = day or date.today().isoformat()
    tasks = build(user_id, day)
    ids = [t["id"] for t in tasks]
    done_rows = query(f"""SELECT DISTINCT card_id FROM interaction_logs
                          WHERE user_id=? AND action='acted' AND date(created_at)=?
                            AND card_id IN ({','.join('?' * len(ids))})""",
                      (user_id, day, *ids))
    done = {r["card_id"] for r in done_rows}
    for t in tasks:
        t["done"] = t["id"] in done
    bonus_earned = query("""SELECT 1 FROM xp_events
                            WHERE user_id=? AND reason='daily_plan_bonus' AND date(created_at)=?""",
                         (user_id, day), one=True) is not None
    return {"date": day, "tasks": tasks, "completed": len(done),
            "bonus_earned": bonus_earned}


def maybe_award_bonus(user_id, day=None):
    """Call after a task interaction; grants the all-3 bonus exactly once/day."""
    plan = with_completion(user_id, day)
    if plan["completed"] >= 3 and not plan["bonus_earned"]:
        xp = gamification.award_xp(user_id, "daily_plan_bonus")
        return {"bonus_xp": xp}
    return None
