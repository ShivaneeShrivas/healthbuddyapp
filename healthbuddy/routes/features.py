"""Feature routes: Period Care, Mind Games, Weekly Wrapped, Notifications.

Kept in a separate blueprint so /routes/api.py (core MVP) stays readable.
"""
from flask import Blueprint, jsonify, request, g
from ..auth import require_auth
from ..services import cycle, games, wrapped, notify, gamification, daily_plan, providers, segmentation, bandit, context as context_svc

bp = Blueprint("features", __name__, url_prefix="/api")


def body():
    return request.get_json(silent=True) or {}


# ---------------- Period Care ----------------
@bp.post("/cycle/setup")
@require_auth
def cycle_setup():
    b = body()
    try:
        cycle.setup(g.user["id"],
                    last_period_start=b.get("last_period_start"),
                    avg_cycle_len=b.get("avg_cycle_len", 28),
                    avg_period_len=b.get("avg_period_len", 5),
                    remind=b.get("remind", True),
                    gcal_export=b.get("gcal_export", False))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    badges = gamification.award_badge(g.user["id"], "self_care")
    return jsonify(status=cycle.status(g.user["id"]), new_badges=badges)


@bp.get("/cycle/status")
@require_auth
def cycle_status():
    try:
        return jsonify(status=cycle.status(g.user["id"]))
    except LookupError:
        return jsonify(error="Period Care isn't enabled. Turn it on from your profile whenever you like."), 404


@bp.post("/cycle/checkin")
@require_auth
def cycle_checkin():
    b = body()
    try:
        if b.get("started"):
            avg = cycle.log_period_start(g.user["id"], b.get("date"))
            xp = gamification.award_xp(g.user["id"], "cycle_checkin")
            return jsonify(message="Logged. Predictions just got a little smarter. 💗",
                           avg_cycle_len=avg, xp_earned=xp,
                           status=cycle.status(g.user["id"]))
        return jsonify(message="No worries — I'll check in again tomorrow.",
                       status=cycle.status(g.user["id"]))
    except LookupError:
        return jsonify(error="Period Care isn't enabled."), 404
    except ValueError as e:
        return jsonify(error=str(e)), 400


@bp.get("/cycle/export")
@require_auth
def cycle_export():
    try:
        return jsonify(events=cycle.gcal_export_payload(g.user["id"]))
    except LookupError:
        return jsonify(error="Enable Google Calendar export in Period Care settings first — it's off by default for privacy."), 404


@bp.delete("/cycle")
@require_auth
def cycle_delete():
    cycle.delete_all(g.user["id"])
    return jsonify(message="All Period Care data deleted. Nothing kept, no questions asked.")


# ---------------- Mind Games ----------------
@bp.get("/games")
@require_auth
def games_home():
    return jsonify(**games.stats(g.user["id"]))


@bp.post("/games/score")
@require_auth
def games_score():
    b = body()
    try:
        result = games.submit(g.user["id"], b.get("game"), b.get("difficulty", "easy"),
                              b.get("score"), b.get("is_daily", False))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(**result)


# ---------------- Weekly Wrapped ----------------
@bp.get("/wrapped")
@require_auth
def wrapped_view():
    data = wrapped.build(g.user["id"])
    badges = gamification.award_badge(g.user["id"], "wrapped_fan")
    xp = gamification.award_xp(g.user["id"], "wrapped_viewed") if badges else 0
    return jsonify(wrapped=data, new_badges=badges, xp_earned=xp)


# ---------------- Daily Plan ----------------
@bp.get("/daily-plan")
@require_auth
def get_daily_plan():
    return jsonify(plan=daily_plan.with_completion(g.user["id"]))


# ---------------- Profile ----------------
EDITABLE = ("name", "avatar", "age_range", "gender", "activity_level",
            "occupation", "step_goal", "notif_enabled")
GENDERS = {"female", "male", "nonbinary", "prefer_not"}
GOALS = {"fitness", "stress", "sleep", "eat_better", "general"}
AGE_RANGES = {"under_18", "18_24", "25_34", "35_44", "45_54", "55_plus"}


@bp.get("/profile")
@require_auth
def get_profile():
    u = g.user
    return jsonify(profile={
        "name": u["name"], "email": u["email"], "avatar": u["avatar"],
        "age_range": u["age_range"], "gender": u["gender"],
        "occupation": u["occupation"], "activity_level": u["activity_level"],
        "health_goal": u["health_goal"],
        "health_goals": (u["health_goals"] or u["health_goal"] or "").split(",")
                        if (u["health_goals"] or u["health_goal"]) else [],
        "step_goal": u["step_goal"] or 8000,
        "notif_enabled": bool(u["notif_enabled"]),
        "buddy_code": u["buddy_code"],
    })


@bp.patch("/profile")
@require_auth
def patch_profile():
    from ..db import execute
    b = body()
    updates, params, problems = [], [], []

    if "name" in b:
        name = str(b["name"]).strip()
        if not (1 <= len(name) <= 60):
            problems.append("Name should be 1-60 characters.")
        else:
            updates.append("name=?"); params.append(name)
    if "avatar" in b:
        av = str(b["avatar"])[:8]
        updates.append("avatar=?"); params.append(av or "🙂")
    if "age_range" in b:
        if b["age_range"] and b["age_range"] not in AGE_RANGES:
            problems.append("age_range must be one of: " + ", ".join(sorted(AGE_RANGES)))
        else:
            updates.append("age_range=?"); params.append(b["age_range"] or None)
    if "gender" in b:
        if b["gender"] not in GENDERS:
            problems.append("gender must be one of: " + ", ".join(sorted(GENDERS)))
        else:
            updates.append("gender=?"); params.append(b["gender"])
    if "activity_level" in b:
        if b["activity_level"] not in {"active", "moderate", "inactive"}:
            problems.append("activity_level must be active, moderate, or inactive.")
        else:
            updates.append("activity_level=?"); params.append(b["activity_level"])
    if "occupation" in b:
        if b["occupation"] not in {"student", "professional", "other"}:
            problems.append("occupation must be student, professional, or other.")
        else:
            updates.append("occupation=?"); params.append(b["occupation"])
    if "step_goal" in b:
        try:
            sgoal = int(b["step_goal"])
            assert 1000 <= sgoal <= 50000
            updates.append("step_goal=?"); params.append(sgoal)
        except (ValueError, TypeError, AssertionError):
            problems.append("Step goal should be between 1,000 and 50,000.")
    if "notif_enabled" in b:
        updates.append("notif_enabled=?"); params.append(1 if b["notif_enabled"] else 0)
    goals_changed = False
    if "health_goals" in b or "health_goal" in b:
        goals = b.get("health_goals") or [b.get("health_goal")]
        goals = [str(x).strip() for x in goals if x]
        if not goals or any(x not in GOALS for x in goals):
            problems.append("health goals must be from: " + ", ".join(sorted(GOALS)))
        else:
            updates.append("health_goal=?"); params.append(goals[0])
            updates.append("health_goals=?"); params.append(",".join(goals))
            goals_changed = True

    if problems:
        return jsonify(error=" ".join(problems)), 400
    if not updates:
        return jsonify(error="Nothing to update."), 400
    params.append(g.user["id"])
    execute("UPDATE users SET " + ", ".join(updates) + " WHERE id=?", tuple(params))

    # Personalization refresh: goal/activity/occupation changes re-seed the
    # bandit's starting point (pref_multiplier — the user's manual tuning —
    # is preserved inside seed_priors' upsert per category).
    if goals_changed or "activity_level" in b or "occupation" in b:
        from ..db import query as q
        u = q("SELECT * FROM users WHERE id=?", (g.user["id"],), one=True)
        weights = segmentation.compute_weights(
            u["health_goals"] or u["health_goal"], u["occupation"],
            u["activity_level"], u["gender"])
        bandit.seed_priors(g.user["id"], weights)
    return jsonify(message="Profile updated successfully ✨")


# ---------------- Activity (steps) ----------------
@bp.get("/activity/today")
@require_auth
def activity_today():
    row = providers.today_activity(g.user["id"])
    u = g.user
    return jsonify(activity=({"steps": row["steps"], "active_minutes": row["active_minutes"],
                              "source": row["source"], "last_synced_at": row["last_synced_at"]}
                             if row else None),
                   step_goal=u["step_goal"] or 8000,
                   connected=providers.is_connected(g.user["id"], "activity"))


@bp.post("/activity/manual")
@require_auth
def activity_manual():
    b = body()
    try:
        providers.upsert_activity(g.user["id"], b.get("steps"), source="manual",
                                  active_minutes=b.get("active_minutes", 0))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e) or "Steps must be a number."), 400
    return jsonify(message="Steps saved 🚶", activity=dict(providers.today_activity(g.user["id"])))


@bp.post("/activity/sync")
@require_auth
def activity_sync():
    """Normalized sync endpoint for platform adapters (Health Connect / HealthKit)."""
    b = body()
    try:
        providers.upsert_activity(g.user["id"], b.get("steps"),
                                  source=b.get("source", "other"),
                                  day=b.get("date"),
                                  active_minutes=b.get("active_minutes", 0))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(message="Synced.")


# ---------------- Screen time ----------------
@bp.get("/wellbeing/today")
@require_auth
def wellbeing_today():
    row = providers.today_wellbeing(g.user["id"])
    return jsonify(wellbeing=({"screen_time_minutes": row["screen_time_minutes"],
                               "source": row["source"]} if row else None),
                   connected=providers.is_connected(g.user["id"], "screen_time"))


@bp.post("/wellbeing/sync")
@require_auth
def wellbeing_sync():
    """Normalized sync endpoint for platform adapters (Android UsageStats)."""
    b = body()
    try:
        providers.upsert_wellbeing(g.user["id"], b.get("screen_time_minutes"),
                                   source=b.get("source", "other"), day=b.get("date"))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(message="Synced.")


@bp.post("/wellbeing/manual")
@require_auth
def wellbeing_manual():
    b = body()
    try:
        providers.upsert_wellbeing(g.user["id"], b.get("screen_time_minutes"), source="manual")
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e) or "Minutes must be a number."), 400
    return jsonify(message="Screen time saved 📱")


# ---------------- Permissions & privacy center ----------------
@bp.get("/permissions")
@require_auth
def get_permissions():
    return jsonify(integrations=providers.statuses(g.user["id"]))


@bp.patch("/permissions")
@require_auth
def patch_permissions():
    from ..db import execute
    b = body()
    kind, status = b.get("integration"), b.get("status")
    if kind == "notifications":
        execute("UPDATE users SET notif_enabled=? WHERE id=?",
                (1 if status == "connected" else 0, g.user["id"]))
        return jsonify(integrations=providers.statuses(g.user["id"]))
    try:
        providers.set_status(g.user["id"], kind, status)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(integrations=providers.statuses(g.user["id"]))


# ---------------- Buddies ----------------
@bp.delete("/buddies/<int:buddy_id>")
@require_auth
def unlink_buddy(buddy_id):
    from ..services import social
    social.unlink_buddy(g.user["id"], buddy_id)
    return jsonify(message="Unlinked. No hard feelings 🐝")


# ---------------- Habit log undo ----------------
@bp.delete("/logs/<habit_type>")
@require_auth
def undo_log(habit_type):
    """Remove the newest log of this habit from today (mis-taps happen).
    Also walks back the +5 XP that log earned, so no farming by log/undo."""
    from ..db import query as q, execute
    if habit_type not in ("water", "meal", "sleep", "mood"):
        return jsonify(error="Unknown habit type."), 400
    row = q("""SELECT id FROM habit_logs WHERE user_id=? AND type=? AND logged_on=date('now')
               ORDER BY id DESC LIMIT 1""", (g.user["id"], habit_type), one=True)
    if not row:
        return jsonify(error="Nothing logged today to undo."), 404
    execute("DELETE FROM habit_logs WHERE id=?", (row["id"],))
    xp = q("""SELECT id FROM xp_events WHERE user_id=? AND reason='habit_log'
              AND date(created_at)=date('now') ORDER BY id DESC LIMIT 1""",
           (g.user["id"],), one=True)
    if xp:
        execute("DELETE FROM xp_events WHERE id=?", (xp["id"],))
    return jsonify(message="Undone — like it never happened ↩️")


# ---------------- Notifications ----------------
@bp.get("/notifications")
@require_auth
def notifications():
    return jsonify(notifications=notify.compose(g.user["id"]))
