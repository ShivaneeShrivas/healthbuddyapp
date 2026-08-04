"""REST API. All endpoints under /api. Errors are friendly, specific,
and actionable (what happened + how to fix)."""
import re
from datetime import date

from flask import Blueprint, g, jsonify, request

from ..auth import (device_label_from_request, hash_password, issue_refresh_token,
                    issue_token, new_buddy_code, require_auth, revoke_refresh_token,
                    rotate_refresh_token, verify_password, verify_refresh_token)
from ..config import CATEGORIES, CATEGORY_META
from ..db import execute, query
from ..services import bandit, gamification, nudges, segmentation, social

api = Blueprint("api", __name__, url_prefix="/api")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OCCUPATIONS = {"student", "professional", "other"}
GENDERS = {"female", "male", "nonbinary", "prefer_not"}
ACTIVITY = {"active", "moderate", "inactive"}
GOALS = {"fitness", "stress", "sleep", "eat_better", "general"}
HABITS = {"water", "meal", "sleep", "mood"}


def body():
    return request.get_json(silent=True) or {}


# ---------- Auth ----------

@api.post("/auth/register")
def register():
    data = body()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name:
        return jsonify(error="Add your name so we know what to call you."), 400
    if not EMAIL_RE.match(email):
        return jsonify(error="That email doesn't look right. Check it and try again."), 400
    if len(password) < 8:
        return jsonify(error="Password needs at least 8 characters."), 400
    if query("SELECT 1 FROM users WHERE email=?", (email,), one=True):
        return jsonify(error="That email already has an account. Try signing in instead."), 409
    user_id = execute(
        "INSERT INTO users (email, password_hash, name, buddy_code) VALUES (?,?,?,?)",
        (email, hash_password(password), name, new_buddy_code()))
    refresh_token = issue_refresh_token(user_id, device_label_from_request())
    return jsonify(token=issue_token(user_id), refresh_token=refresh_token,
                   user=_public_user(user_id)), 201


@api.post("/auth/login")
def login():
    data = body()
    user = query("SELECT * FROM users WHERE email=?",
                 ((data.get("email") or "").strip().lower(),), one=True)
    if user is None or not verify_password(data.get("password") or "", user["password_hash"]):
        return jsonify(error="Email and password don't match. Try again."), 401
    refresh_token = issue_refresh_token(user["id"], device_label_from_request())
    return jsonify(token=issue_token(user["id"]), refresh_token=refresh_token,
                   user=_public_user(user["id"]))


@api.post("/auth/refresh")
def refresh():
    """Trade a still-valid refresh token for a new access token, without the
    user re-entering a password. This is the call the client makes silently
    in the background — it's the whole mechanism behind staying logged in."""
    data = body()
    session = verify_refresh_token(data.get("refresh_token") or "")
    if session is None:
        return jsonify(error="Your session has expired. Sign in again."), 401
    new_refresh = rotate_refresh_token(session, device_label_from_request())
    return jsonify(token=issue_token(session["user_id"]), refresh_token=new_refresh,
                   user=_public_user(session["user_id"]))


@api.post("/auth/logout")
def logout():
    """Revoke this device's refresh token server-side. Safe to call even if
    the access token already expired (that's the whole point of logout)."""
    data = body()
    revoke_refresh_token(data.get("refresh_token") or "")
    return jsonify(ok=True)


def _public_user(user_id):
    u = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    return {"id": u["id"], "name": u["name"], "email": u["email"],
            "buddy_code": u["buddy_code"], "onboarded": bool(u["onboarded"]),
            "occupation": u["occupation"], "gender": u["gender"],
            "activity_level": u["activity_level"], "health_goal": u["health_goal"],
            "quiet_start": u["quiet_start"], "quiet_end": u["quiet_end"]}


@api.get("/me")
@require_auth
def me():
    return jsonify(user=_public_user(g.user["id"]))


# ---------- Onboarding → segmentation → bandit priors ----------

@api.post("/onboarding")
@require_auth
def onboarding():
    data = body()
    occupation, gender = data.get("occupation"), data.get("gender")
    activity = data.get("activity_level")
    goals = data.get("health_goals") or ([data.get("health_goal")] if data.get("health_goal") else [])
    goals = [str(x).strip() for x in goals if x]
    goal = goals[0] if goals else None
    problems = []
    if occupation not in OCCUPATIONS:
        problems.append("occupation must be one of: " + ", ".join(sorted(OCCUPATIONS)))
    if gender not in GENDERS:
        problems.append("gender must be one of: " + ", ".join(sorted(GENDERS)))
    if activity not in ACTIVITY:
        problems.append("activity_level must be one of: " + ", ".join(sorted(ACTIVITY)))
    if not goals or any(x not in GOALS for x in goals):
        problems.append("health_goal(s) must be from: " + ", ".join(sorted(GOALS)))
    if problems:
        return jsonify(error="; ".join(problems)), 400

    first_time = not g.user["onboarded"]
    execute("UPDATE users SET occupation=?, gender=?, activity_level=?, health_goal=?, health_goals=?, onboarded=1 WHERE id=?",
            (occupation, gender, activity, goal, ",".join(goals), g.user["id"]))
    weights = segmentation.compute_weights(goals, occupation, activity, gender)
    bandit.seed_priors(g.user["id"], weights)
    xp = gamification.award_xp(g.user["id"], "onboarding") if first_time else 0
    if first_time:
        execute("INSERT INTO user_badges (user_id, badge_code) VALUES (?, 'first_steps') "
                "ON CONFLICT (user_id, badge_code) DO NOTHING",
                (g.user["id"],))
    return jsonify(weights=weights, xp_earned=xp, user=_public_user(g.user["id"]))


# ---------- Nudges ----------

@api.get("/nudges/next")
@require_auth
def next_nudge():
    if not g.user["onboarded"]:
        return jsonify(error="Finish onboarding first so nudges can be tuned to you."), 409
    card = nudges.next_nudge(g.user["id"], g.user["gender"])
    if card is None:
        return jsonify(error="The content bank is empty. Run the seed script."), 503
    return jsonify(nudge=card)


@api.post("/nudges/<int:card_id>/interact")
@require_auth
def interact(card_id):
    action = body().get("action")
    try:
        result = nudges.interact(g.user["id"], card_id, action)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except LookupError:
        return jsonify(error="That nudge doesn't exist."), 404
    return jsonify(**result)


@api.get("/nudges/feed")
@require_auth
def feed():
    return jsonify(feed=nudges.feed(g.user["id"]))


# ---------- Tracking & dashboard ----------

@api.post("/logs")
@require_auth
def add_log():
    data = body()
    habit = data.get("type")
    if habit not in HABITS:
        return jsonify(error="type must be one of: " + ", ".join(sorted(HABITS))), 400
    try:
        value = float(data.get("value", 1))
    except (TypeError, ValueError):
        return jsonify(error="value must be a number."), 400
    if habit == "sleep" and not (0 < value <= 24):
        return jsonify(error="Sleep hours should be between 0 and 24."), 400
    if habit == "mood" and not (1 <= value <= 5):
        return jsonify(error="Mood is a 1–5 scale."), 400
    execute("INSERT INTO habit_logs (user_id, type, value, note) VALUES (?,?,?,?)",
            (g.user["id"], habit, value, (data.get("note") or "")[:280]))
    xp = gamification.award_xp(g.user["id"], "habit_log")
    new_badges = gamification.check_and_award(g.user["id"])
    return jsonify(xp_earned=xp, new_badges=new_badges,
                   streak=gamification.streak(g.user["id"], habit)), 201


@api.get("/dashboard")
@require_auth
def dashboard():
    score = nudges.health_score(g.user["id"])
    prof = gamification.profile(g.user["id"])
    return jsonify(greeting_name=g.user["name"].split()[0],
                   score=score, streaks=prof["streaks"],
                   level=prof["level"], xp=prof["xp"],
                   level_progress=prof["progress"], next_at=prof["next_at"])


@api.get("/history/<habit>")
@require_auth
def history(habit):
    if habit not in HABITS:
        return jsonify(error="Unknown habit type."), 400
    rows = query("SELECT logged_on, COUNT(*) AS count, SUM(value) AS total FROM habit_logs "
                 "WHERE user_id=? AND type=? GROUP BY logged_on ORDER BY logged_on DESC LIMIT 30",
                 (g.user["id"], habit))
    return jsonify(history=[dict(r) for r in rows])


# ---------- Knowledge hub ----------

@api.get("/cards")
@require_auth
def cards():
    category = request.args.get("category")
    if category and category not in CATEGORIES:
        return jsonify(error="Unknown category."), 400
    sql = "SELECT * FROM notification_cards WHERE audience IN ('all', ?)"
    args = [g.user["gender"] or "all"]
    if category:
        sql += " AND category=?"
        args.append(category)
    rows = query(sql + " ORDER BY category, id", args)
    return jsonify(cards=[nudges.card_dict(r) for r in rows],
                   categories=[{"key": c, **CATEGORY_META[c]} for c in CATEGORIES])


@api.get("/cards/daily")
@require_auth
def card_of_day():
    rows = query("SELECT * FROM notification_cards WHERE deep_dive IS NOT NULL ORDER BY id")
    if not rows:
        return jsonify(error="No content yet."), 503
    pick = rows[date.today().toordinal() % len(rows)]
    return jsonify(card=nudges.card_dict(pick))


# ---------- Gamification, transparency, preferences ----------

@api.get("/gamification/profile")
@require_auth
def gamification_profile():
    return jsonify(**gamification.profile(g.user["id"]))


@api.get("/transparency")
@require_auth
def transparency():
    return jsonify(
        explanation=("Your nudges are picked by a learning system. It started from your "
                     "onboarding answers and updates every time you act on, open, snooze, "
                     "or dismiss a nudge. Higher affinity means you'll see that category more."),
        state=[{**s, **{"label": CATEGORY_META[s["category"]]["label"],
                        "emoji": CATEGORY_META[s["category"]]["emoji"],
                        "color": CATEGORY_META[s["category"]]["color"]}}
               for s in bandit.get_state(g.user["id"])])


@api.patch("/preferences")
@require_auth
def preferences():
    data = body()
    for cat, mult in (data.get("category_weights") or {}).items():
        if cat in CATEGORIES:
            bandit.set_preference(g.user["id"], cat, mult)
    updates, args = [], []
    for field in ("quiet_start", "quiet_end"):
        if field in data and re.match(r"^\d{2}:\d{2}$", str(data[field])):
            updates.append(f"{field}=?")
            args.append(data[field])
    if updates:
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", (*args, g.user["id"]))
    return jsonify(ok=True, user=_public_user(g.user["id"]))


# ---------- Social ----------

@api.get("/challenges")
@require_auth
def challenges():
    return jsonify(challenges=social.list_challenges(g.user["id"]))


@api.post("/challenges/<int:challenge_id>/join")
@require_auth
def join_challenge(challenge_id):
    try:
        return jsonify(**social.join(g.user["id"], challenge_id))
    except LookupError:
        return jsonify(error="That challenge doesn't exist."), 404


@api.get("/challenges/<int:challenge_id>/leaderboard")
@require_auth
def challenge_leaderboard(challenge_id):
    try:
        return jsonify(**social.leaderboard(challenge_id))
    except LookupError:
        return jsonify(error="That challenge doesn't exist."), 404


@api.post("/buddies/link")
@require_auth
def link_buddy():
    try:
        return jsonify(**social.link_buddy(g.user["id"], body().get("code") or ""))
    except LookupError as e:
        return jsonify(error=str(e)), 404
    except ValueError as e:
        return jsonify(error=str(e)), 400


@api.get("/buddies")
@require_auth
def buddies():
    return jsonify(buddies=social.list_buddies(g.user["id"]), my_code=g.user["buddy_code"])
