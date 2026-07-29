"""Seed the database with the content bank and starter challenges.

Usage:  python seed.py [--demo]
        --demo also creates a demo account (demo@healthbuddy.app / demopass123)
"""
import json
import os
import sys
from datetime import date, timedelta

from healthbuddy import create_app
from healthbuddy.db import execute, query

BASE = os.path.dirname(os.path.abspath(__file__))


def seed_cards():
    with open(os.path.join(BASE, "content", "cards.json")) as f:
        cards = json.load(f)
    existing = query("SELECT COUNT(*) AS n FROM notification_cards", one=True)["n"]
    if existing:
        print(f"Content bank already has {existing} cards — skipping.")
        return
    for c in cards:
        execute(
            "INSERT INTO notification_cards (category, tone, emoji, title, body, action_label, audience, deep_dive) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (c["category"], c.get("tone", "friendly"), c["emoji"], c["title"], c["body"],
             c.get("action_label", "Done"), c.get("audience", "all"), c.get("deep_dive")))
    print(f"Seeded {len(cards)} notification cards.")


def seed_challenges():
    if query("SELECT 1 FROM challenges", one=True):
        print("Challenges already seeded — skipping.")
        return
    today = date.today()
    end = today + timedelta(days=13)
    rows = [
        ("Hydration Week", "Log water on 7 different days in the next two weeks. Your kidneys are cheering.",
         "💧", "water", 7, today.isoformat(), end.isoformat()),
        ("Nudge Streak", "Act on 15 nudges before the challenge ends. Small actions, big momentum.",
         "⚡", "nudge_acted", 15, today.isoformat(), end.isoformat()),
        ("Sleep Squad", "Log your sleep on 5 different days. Consistency beats heroics.",
         "🌙", "sleep", 5, today.isoformat(), end.isoformat()),
    ]
    for r in rows:
        execute("INSERT INTO challenges (title, description, emoji, metric_type, target, starts_on, ends_on) "
                "VALUES (?,?,?,?,?,?,?)", r)
    print(f"Seeded {len(rows)} challenges.")


def seed_demo_user():
    from healthbuddy.auth import hash_password, new_buddy_code
    if query("SELECT 1 FROM users WHERE email='demo@healthbuddy.app'", one=True):
        print("Demo user exists — skipping.")
        return
    execute("INSERT INTO users (email, password_hash, name, buddy_code) VALUES (?,?,?,?)",
            ("demo@healthbuddy.app", hash_password("demopass123"), "Demo Buddy", new_buddy_code()))
    print("Demo user created: demo@healthbuddy.app / demopass123")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_cards()
        seed_challenges()
        if "--demo" in sys.argv:
            seed_demo_user()
    print("Seeding complete.")
