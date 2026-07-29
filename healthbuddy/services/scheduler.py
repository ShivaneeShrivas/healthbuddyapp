"""Shared scheduling logic - one 'tick' that sends due slot notifications and
due snoozes. Called from two places:
  1. push_worker.py's loop, for local dev / any host with a real worker process.
  2. routes/api.py's /push/run-tick, for free hosting (Render free tier etc)
     where a paid background worker isn't worth it - an external free cron
     pinger (cron-job.org, GitHub Actions schedule, etc) hits that endpoint
     every ~15-20 min instead.
"""
from ..db import query
from . import notify, push


def _users_with_subscriptions():
    return query("""
        SELECT DISTINCT u.id, u.name FROM users u
        JOIN push_subscriptions ps ON ps.user_id = u.id
    """)


def _send(user, tmpl):
    sig = push.sign_action(user["id"], tmpl["id"])
    payload = {
        "title": f"{tmpl['emoji']} {tmpl['title']}",
        "body": tmpl["body"],
        "url": "/#nudges",
        "tag": tmpl["id"],
        "user_id": user["id"],
        "sig": sig,
    }
    return push.send_to_user(user["id"], payload)


def run_tick_once():
    """Must be called inside an active Flask app context. Returns a small
    summary dict, useful both for worker log lines and for the HTTP
    endpoint's response body."""
    sent_log = []
    for user in _users_with_subscriptions():
        for snz in notify.due_snoozes(user["id"]):
            tmpl = notify.find_template(snz["template_id"])
            if tmpl and _send(user, tmpl):
                notify.record_slot_sent(user["id"], tmpl["slot"], tmpl["id"])
                sent_log.append(f"SNOOZED '{tmpl['id']}' -> user {user['id']}")
            notify.clear_snooze(snz["id"])

        tmpl = notify.compose_slot(user["id"])
        if not tmpl:
            continue
        if _send(user, tmpl):
            notify.record_slot_sent(user["id"], tmpl["slot"], tmpl["id"])
            sent_log.append(f"'{tmpl['id']}' ({tmpl['slot']}) -> user {user['id']}")
    return {"sent": len(sent_log), "detail": sent_log}
