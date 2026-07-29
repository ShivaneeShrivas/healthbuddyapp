"""Cold-start segmentation (IIT Kanpur v1).

Converts onboarding answers into a normalized probability distribution over
notification categories, used to seed the Thompson Sampling priors so the very
first nudge is already an informed guess.

Per spec: health goal is the dominant signal; occupation is a routine/stress proxy;
activity level shifts movement vs. recovery content; gender is deliberately NOT
used at category level (only for card selection within a category).
"""
from ..config import CATEGORIES

BASE_WEIGHT = 1.0

GOAL_BOOSTS = {
    "fitness":         {"movement": 2.0, "nutrition": 0.75, "hydration": 0.5},
    "stress":          {"mindfulness": 2.0, "sleep": 0.75},
    "sleep":           {"sleep": 2.0, "mindfulness": 0.75},
    "eat_better":      {"nutrition": 2.0, "hydration": 0.5},
    "general":         {c: 0.4 for c in CATEGORIES},
}

OCCUPATION_BOOSTS = {
    # Students: irregular meals + deadline crunches
    "student":      {"movement": 0.3, "nutrition": 0.2},
    # Working professionals: desk hours, work stress, shorter nights
    "professional": {"mindfulness": 0.6, "sleep": 0.5, "movement": 0.3},
    # Other / prefer to skip: stay neutral, let the bandit learn
    "other":        {},
}

ACTIVITY_BOOSTS = {
    "active":   {"movement": -0.5, "nutrition": 0.4, "sleep": 0.3},   # recovery focus
    "moderate": {"movement": 0.2},
    "inactive": {"movement": 0.8, "hydration": 0.2},
}

MIN_WEIGHT = 0.25  # every category keeps a floor so the bandit can still explore


def _goal_boosts(health_goal):
    """Accepts a single goal or several ('fitness,sleep' or a list): multiple
    goals contribute the AVERAGE of their boost tables, so picking everything
    doesn't inflate weights — it genuinely blends interests."""
    goals = health_goal if isinstance(health_goal, (list, tuple)) else str(health_goal or "").split(",")
    goals = [g.strip() for g in goals if g.strip() in GOAL_BOOSTS] or ["general"]
    blended = {}
    for g in goals:
        for cat, delta in GOAL_BOOSTS[g].items():
            blended[cat] = blended.get(cat, 0) + delta / len(goals)
    return blended


def compute_weights(health_goal, occupation, activity_level, gender=None):
    """Return {category: weight} summing to 1.0. `gender` accepted but unused
    at this level by design — it only filters card audiences downstream."""
    weights = {c: BASE_WEIGHT for c in CATEGORIES}
    for boosts in (
        _goal_boosts(health_goal),
        OCCUPATION_BOOSTS.get(occupation, {}),
        ACTIVITY_BOOSTS.get(activity_level, {}),
    ):
        for cat, delta in boosts.items():
            weights[cat] += delta
    for c in CATEGORIES:
        weights[c] = max(weights[c], MIN_WEIGHT)
    total = sum(weights.values())
    return {c: w / total for c, w in weights.items()}
