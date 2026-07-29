"""Challenges, leaderboards, and the buddy system."""
from datetime import date
from ..db import query, execute
from . import gamification


def _progress(user_id, ch):
    if ch["metric_type"] == "nudge_acted":
        row = query("SELECT COUNT(*) AS n FROM interaction_logs WHERE user_id=? AND action='acted' "
                    "AND date(created_at) BETWEEN ? AND ?",
                    (user_id, ch["starts_on"], ch["ends_on"]), one=True)
    else:
        row = query("SELECT COUNT(DISTINCT logged_on) AS n FROM habit_logs WHERE user_id=? AND type=? "
                    "AND logged_on BETWEEN ? AND ?",
                    (user_id, ch["metric_type"], ch["starts_on"], ch["ends_on"]), one=True)
    return min(row["n"], ch["target"])


def list_challenges(user_id):
    today = date.today().isoformat()
    rows = query("SELECT * FROM challenges WHERE ends_on >= ? ORDER BY starts_on", (today,))
    joined = {r["challenge_id"] for r in
              query("SELECT challenge_id FROM challenge_members WHERE user_id=?", (user_id,))}
    out = []
    for ch in rows:
        members = query("SELECT COUNT(*) AS n FROM challenge_members WHERE challenge_id=?",
                        (ch["id"],), one=True)["n"]
        item = dict(ch) | {"members": members, "joined": ch["id"] in joined}
        if item["joined"]:
            item["progress"] = _progress(user_id, ch)
        out.append(item)
    return out


def join(user_id, challenge_id):
    ch = query("SELECT * FROM challenges WHERE id=?", (challenge_id,), one=True)
    if ch is None:
        raise LookupError("challenge not found")
    already = query("SELECT 1 FROM challenge_members WHERE challenge_id=? AND user_id=?",
                    (challenge_id, user_id), one=True)
    if already:
        return {"xp_earned": 0, "new_badges": []}
    execute("INSERT INTO challenge_members (challenge_id, user_id) VALUES (?,?)", (challenge_id, user_id))
    xp = gamification.award_xp(user_id, "challenge_join")
    return {"xp_earned": xp, "new_badges": gamification.check_and_award(user_id)}


def leaderboard(challenge_id, limit=20):
    ch = query("SELECT * FROM challenges WHERE id=?", (challenge_id,), one=True)
    if ch is None:
        raise LookupError("challenge not found")
    members = query("SELECT u.id, u.name FROM challenge_members cm JOIN users u ON u.id=cm.user_id "
                    "WHERE cm.challenge_id=?", (challenge_id,))
    board = sorted(
        ({"user_id": m["id"], "name": m["name"], "progress": _progress(m["id"], ch)} for m in members),
        key=lambda x: -x["progress"])[:limit]
    for i, row in enumerate(board, 1):
        row["rank"] = i
    return {"challenge": dict(ch), "leaderboard": board}


def link_buddy(user_id, buddy_code):
    buddy = query("SELECT id, name FROM users WHERE buddy_code=?", (buddy_code.strip().upper(),), one=True)
    if buddy is None:
        raise LookupError("No one has that buddy code. Double-check it with your friend.")
    if buddy["id"] == user_id:
        raise ValueError("That's your own code! Share it with a friend instead.")
    for a, b in ((user_id, buddy["id"]), (buddy["id"], user_id)):
        if not query("SELECT 1 FROM buddies WHERE user_id=? AND buddy_id=?", (a, b), one=True):
            execute("INSERT INTO buddies (user_id, buddy_id) VALUES (?,?)", (a, b))
    gamification.check_and_award(user_id)
    gamification.check_and_award(buddy["id"])
    return {"buddy": {"id": buddy["id"], "name": buddy["name"]}}


def list_buddies(user_id):
    rows = query("SELECT u.id, u.name FROM buddies b JOIN users u ON u.id=b.buddy_id WHERE b.user_id=?",
                 (user_id,))
    return [{"id": r["id"], "name": r["name"], "streaks": gamification.all_streaks(r["id"])} for r in rows]


def unlink_buddy(user_id, buddy_id):
    """Remove the link both ways. Quiet and drama-free."""
    execute("DELETE FROM buddies WHERE user_id=? AND buddy_id=?", (user_id, buddy_id))
    execute("DELETE FROM buddies WHERE user_id=? AND buddy_id=?", (buddy_id, user_id))
