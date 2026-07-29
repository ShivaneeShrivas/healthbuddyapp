"""Mind Games: scores, daily challenges, improvement tracking, brain score.

Games run fully client-side; the server records results, hands out XP and
badges, picks the daily challenge, and computes progress over time.
Score convention: HIGHER IS ALWAYS BETTER. The client normalizes (e.g.
reaction time is submitted as max(0, 1000 - ms)) so trends compare cleanly.
"""
from datetime import date, timedelta
from ..db import query, execute
from . import gamification

GAMES = {
    "memory":   {"emoji": "🃏", "label": "Memory Match",     "skill": "memory"},
    "pattern":  {"emoji": "🎨", "label": "Pattern Recall",   "skill": "focus"},
    "reaction": {"emoji": "⚡", "label": "Reaction Time",    "skill": "reaction"},
    "logic":    {"emoji": "🧩", "label": "Logic Sprint",     "skill": "logic"},
}
DIFFICULTIES = ("easy", "medium", "hard")
DAILY_BONUS_XP = "daily_challenge"


def daily_game(today=None):
    """Deterministic rotation so everyone gets the same daily challenge."""
    keys = sorted(GAMES)
    d = (today or date.today()).toordinal()
    return keys[d % len(keys)]


def submit(user_id, game, difficulty, score, is_daily=False):
    if game not in GAMES:
        raise ValueError("Unknown game.")
    if difficulty not in DIFFICULTIES:
        raise ValueError("Difficulty must be easy, medium, or hard.")
    try:
        score = float(score)
    except (TypeError, ValueError):
        raise ValueError("Score must be a number.")
    if score < 0 or score > 100000:
        raise ValueError("That score looks off.")
    is_daily = bool(is_daily) and game == daily_game()
    execute("""INSERT INTO game_scores (user_id, game, difficulty, score, is_daily)
               VALUES (?,?,?,?,?)""", (user_id, game, difficulty, score, int(is_daily)))

    xp = gamification.award_xp(user_id, "game_played")
    if is_daily and not _daily_already_counted(user_id):
        xp += gamification.award_xp(user_id, DAILY_BONUS_XP)

    badges = []
    total = query("SELECT COUNT(*) AS n FROM game_scores WHERE user_id = ?", (user_id,), one=True)["n"]
    if total == 1:
        badges += gamification.award_badge(user_id, "brain_spark")
    if game == "reaction" and score >= 700:  # 1000 - ms ≥ 700 → under 300 ms
        badges += gamification.award_badge(user_id, "quick_reflex")
    dailies = query("""SELECT COUNT(DISTINCT played_on) AS n FROM game_scores
                       WHERE user_id = ? AND is_daily = 1""", (user_id,), one=True)["n"]
    if dailies >= 5:
        badges += gamification.award_badge(user_id, "sharp_mind")
    return {"xp_earned": xp, "new_badges": badges, "is_daily": is_daily}


def _daily_already_counted(user_id):
    return query("""SELECT COUNT(*) AS n FROM game_scores
                    WHERE user_id = ? AND is_daily = 1 AND played_on = date('now')""",
                 (user_id,), one=True)["n"] > 1


def stats(user_id):
    """Per-game best / recent trend + play streak + overall brain score."""
    out = []
    for key, meta in GAMES.items():
        rows = query("""SELECT score, played_on FROM game_scores
                        WHERE user_id = ? AND game = ? ORDER BY created_at""", (user_id, key))
        scores = [r["score"] for r in rows]
        entry = {"game": key, **meta, "plays": len(scores),
                 "best": max(scores) if scores else None,
                 "trend_pct": None}
        if len(scores) >= 4:
            half = len(scores) // 2
            early, late = scores[:half], scores[half:]
            base = (sum(early) / len(early)) or 1
            entry["trend_pct"] = round((sum(late) / len(late) - base) / base * 100)
        out.append(entry)

    days = {r["played_on"] for r in query(
        "SELECT DISTINCT played_on FROM game_scores WHERE user_id = ?", (user_id,))}
    streak, d = 0, date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        streak += 1
        d -= timedelta(days=1)

    return {"games": out, "daily_game": daily_game(), "play_streak": streak,
            "brain_score": brain_score(user_id)}


def brain_score(user_id, since_days=7):
    """0-100 composite of recent play: activity (40) + skill coverage (30) +
    personal-best momentum (30). Simple and explainable on purpose."""
    since = (date.today() - timedelta(days=since_days)).isoformat()
    rows = query("""SELECT game, score, played_on FROM game_scores
                    WHERE user_id = ? AND played_on >= ?""", (user_id, since))
    if not rows:
        return 0
    days_played = len({r["played_on"] for r in rows})
    games_touched = len({r["game"] for r in rows})
    activity = min(days_played / 5, 1) * 40
    coverage = games_touched / len(GAMES) * 30
    momentum = 0
    for g in {r["game"] for r in rows}:
        all_best = query("""SELECT MAX(score) AS m FROM game_scores
                            WHERE user_id = ? AND game = ?""", (user_id, g), one=True)["m"]
        recent_best = max(r["score"] for r in rows if r["game"] == g)
        if all_best and recent_best >= all_best:
            momentum += 30 / games_touched
    return round(activity + coverage + momentum)
