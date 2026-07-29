"""Thompson Sampling contextual bandit over notification categories.

Each (user, category) holds a Beta(alpha, beta) posterior over "this category
lands with this user". Selection samples each posterior and picks the max;
interactions update the posterior with a soft reward. Priors are seeded from
segmentation weights so day-one picks are informed, and real engagement takes
over naturally as evidence accumulates.
"""
import random
from ..config import CATEGORIES, Config
from ..db import query, execute


def seed_priors(user_id, weights, prior_strength=None):
    """alpha = 1 + S*w, beta = 1 + S*(1-w)  →  posterior mean ≈ w."""
    s = prior_strength or Config.PRIOR_STRENGTH
    for cat in CATEGORIES:
        w = weights[cat]
        execute(
            """INSERT INTO bandit_states (user_id, category, alpha, beta) VALUES (?,?,?,?)
               ON CONFLICT(user_id, category) DO UPDATE SET
                 alpha=excluded.alpha, beta=excluded.beta""",  # pref_multiplier (user tuning) preserved
            (user_id, cat, 1.0 + s * w, 1.0 + s * (1.0 - w)),
        )


def select_category(user_id, rng=random):
    """Sample each posterior (scaled by user preference multiplier) and argmax."""
    rows = query("SELECT category, alpha, beta, pref_multiplier FROM bandit_states WHERE user_id = ?", (user_id,))
    if not rows:
        return rng.choice(CATEGORIES)
    best_cat, best_sample = None, -1.0
    for r in rows:
        sample = rng.betavariate(r["alpha"], r["beta"]) * r["pref_multiplier"]
        if sample > best_sample:
            best_cat, best_sample = r["category"], sample
    return best_cat


def update(user_id, category, action):
    """Fold an interaction back into the posterior as a soft Bernoulli reward."""
    reward = Config.REWARDS.get(action)
    if reward is None:  # 'sent' and unknown actions carry no signal
        return
    execute(
        "UPDATE bandit_states SET alpha = alpha + ?, beta = beta + ? WHERE user_id = ? AND category = ?",
        (reward, 1.0 - reward, user_id, category),
    )


def get_state(user_id):
    """Expose posterior means for the 'Why am I seeing this?' screen."""
    rows = query("SELECT category, alpha, beta, pref_multiplier FROM bandit_states WHERE user_id = ?", (user_id,))
    out = []
    for r in rows:
        mean = r["alpha"] / (r["alpha"] + r["beta"])
        out.append({
            "category": r["category"],
            "affinity": round(mean * r["pref_multiplier"], 4),
            "evidence": round(r["alpha"] + r["beta"] - 2, 1),
            "pref_multiplier": r["pref_multiplier"],
        })
    out.sort(key=lambda x: -x["affinity"])
    return out


def set_preference(user_id, category, multiplier):
    multiplier = min(max(float(multiplier), 0.0), 2.0)
    execute(
        "UPDATE bandit_states SET pref_multiplier = ? WHERE user_id = ? AND category = ?",
        (multiplier, user_id, category),
    )
