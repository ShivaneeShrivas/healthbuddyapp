"""Tests for Period Care, Mind Games, Weekly Wrapped, and notifications."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from healthbuddy import create_app
from healthbuddy.services import cycle, games, notify


class FeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True, "SECRET_KEY": "test"})
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def auth(self):
        res = self.client.post("/api/auth/register",
                               json={"email": "f@example.com", "name": "Fatima", "password": "password123"})
        tok = res.get_json()["token"]
        self.client.post("/api/onboarding", headers={"Authorization": "Bearer " + tok},
                         json={"occupation": "student", "gender": "female",
                               "activity_level": "moderate", "health_goal": "general"})
        return {"Authorization": "Bearer " + tok}

    # ---------------- Period Care ----------------
    def test_cycle_setup_predicts_and_learns(self):
        h = self.auth()
        start = (date.today() - timedelta(days=10)).isoformat()
        res = self.client.post("/api/cycle/setup", headers=h,
                               json={"last_period_start": start, "avg_cycle_len": 28, "avg_period_len": 5})
        self.assertEqual(res.status_code, 200, res.get_json())
        st = res.get_json()["status"]
        self.assertEqual(st["cycle_day"], 11)          # day 10 since start → cycle day 11
        self.assertEqual(st["days_left"], 18)          # 28 - 10
        self.assertEqual(st["phase"], "follicular")    # past period, before ovulation (day 14)
        self.assertTrue(any(b["code"] == "self_care" for b in res.get_json()["new_badges"]))

        # Log two real starts with 30- and 32-day gaps → avg learned = 31, not 28.
        with self.app.app_context():
            uid = 1
            base = date.today() - timedelta(days=72)
            cycle.delete_all(uid)
            cycle.setup(uid, base.isoformat())
            cycle.log_period_start(uid, (base + timedelta(days=30)).isoformat())
            avg = cycle.log_period_start(uid, (base + timedelta(days=62)).isoformat())
            self.assertEqual(avg, 31.0)
            st = cycle.status(uid, today=base + timedelta(days=70))
            self.assertEqual(st["days_left"], 23)      # next = day 62+31=93; 93-70
            self.assertEqual(st["cycles_recorded"], 3)

    def test_cycle_phases_and_checkin_due(self):
        with self.app.app_context():
            self.auth()
            uid = 1
            start = date(2026, 6, 1)
            cycle.setup(uid, start.isoformat(), avg_cycle_len=28, avg_period_len=5)
            self.assertEqual(cycle.status(uid, today=date(2026, 6, 3))["phase"], "menstrual")
            self.assertEqual(cycle.status(uid, today=date(2026, 6, 14))["phase"], "ovulation")
            self.assertEqual(cycle.status(uid, today=date(2026, 6, 22))["phase"], "luteal")
            self.assertTrue(cycle.status(uid, today=date(2026, 6, 30))["checkin_due"])
            self.assertFalse(cycle.status(uid, today=date(2026, 6, 20))["checkin_due"])

    def test_cycle_gated_and_deletable(self):
        h = self.auth()
        self.assertEqual(self.client.get("/api/cycle/status", headers=h).status_code, 404)
        self.client.post("/api/cycle/setup", headers=h,
                         json={"last_period_start": date.today().isoformat()})
        self.assertEqual(self.client.get("/api/cycle/status", headers=h).status_code, 200)
        # gcal export is off by default → 404 until explicitly enabled
        self.assertEqual(self.client.get("/api/cycle/export", headers=h).status_code, 404)
        self.client.delete("/api/cycle", headers=h)
        self.assertEqual(self.client.get("/api/cycle/status", headers=h).status_code, 404)

    def test_cycle_rejects_bad_input(self):
        h = self.auth()
        bad = self.client.post("/api/cycle/setup", headers=h,
                               json={"last_period_start": "not-a-date"})
        self.assertEqual(bad.status_code, 400)
        future = self.client.post("/api/cycle/setup", headers=h,
                                  json={"last_period_start": (date.today() + timedelta(days=3)).isoformat()})
        self.assertEqual(future.status_code, 400)

    # ---------------- Mind Games ----------------
    def test_game_score_xp_and_badges(self):
        h = self.auth()
        res = self.client.post("/api/games/score", headers=h,
                               json={"game": "memory", "difficulty": "easy", "score": 120})
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(data["xp_earned"], 5)
        self.assertTrue(any(b["code"] == "brain_spark" for b in data["new_badges"]))
        # reaction under 300 ms → score ≥ 700 → quick_reflex
        res = self.client.post("/api/games/score", headers=h,
                               json={"game": "reaction", "difficulty": "easy", "score": 760})
        self.assertTrue(any(b["code"] == "quick_reflex" for b in res.get_json()["new_badges"]))
        bad = self.client.post("/api/games/score", headers=h,
                               json={"game": "chess", "score": 1})
        self.assertEqual(bad.status_code, 400)

    def test_daily_challenge_deterministic_and_stats(self):
        self.assertEqual(games.daily_game(date(2026, 7, 10)), games.daily_game(date(2026, 7, 10)))
        self.assertNotEqual(games.daily_game(date(2026, 7, 10)), games.daily_game(date(2026, 7, 11)))
        h = self.auth()
        with self.app.app_context():
            today_game = games.daily_game()
        for s in (50, 60, 70, 90):
            self.client.post("/api/games/score", headers=h,
                             json={"game": today_game, "difficulty": "easy",
                                   "score": s, "is_daily": True})
        stats = self.client.get("/api/games", headers=h).get_json()
        g = next(x for x in stats["games"] if x["game"] == today_game)
        self.assertEqual(g["plays"], 4)
        self.assertGreater(g["trend_pct"], 0)          # later scores higher → improving
        self.assertEqual(stats["play_streak"], 1)
        self.assertGreater(stats["brain_score"], 0)

    # ---------------- Weekly Wrapped ----------------
    def test_wrapped_aggregates_week(self):
        h = self.auth()
        for _ in range(6):
            self.client.post("/api/logs", headers=h, json={"type": "water", "value": 1})
        self.client.post("/api/logs", headers=h, json={"type": "sleep", "value": 8})
        self.client.post("/api/games/score", headers=h,
                         json={"game": "logic", "difficulty": "easy", "score": 80})
        res = self.client.get("/api/wrapped", headers=h)
        w = res.get_json()["wrapped"]
        self.assertEqual(w["hydration"]["glasses"], 6)
        self.assertEqual(w["sleep"]["avg_hours"], 8)
        self.assertGreater(w["health_score"], 0)
        self.assertTrue(w["insights"])
        self.assertTrue(2 <= len(w["goals"]) <= 4)
        self.assertTrue(any(b["code"] == "wrapped_fan" for b in res.get_json()["new_badges"]))

    # ---------------- Notifications ----------------
    def test_notifications_context_and_quiet_hours(self):
        h = self.auth()
        with self.app.app_context():
            uid = 1
            # 3 pm, weekday, no water logged → hydration + movement style messages
            picks = notify.compose(uid, now=datetime(2026, 7, 8, 15, 0))
            self.assertTrue(picks)
            self.assertTrue(any(p["id"] in ("water_low", "legs_texted", "plot_twist") for p in picks))
            # quiet hours (default 23:00-07:00) → nothing at 2 am
            self.assertEqual(notify.compose(uid, now=datetime(2026, 7, 8, 2, 0)), [])
            # period check-in outranks everything on the predicted date
            cycle.setup(uid, (date.today() - timedelta(days=29)).isoformat(), avg_cycle_len=28)
            picks = notify.compose(uid, now=datetime.now().replace(hour=15))
            self.assertEqual(picks[0]["kind"], "cycle_checkin")
            self.assertIn("Did your period start today?", picks[0]["body"])


if __name__ == "__main__":
    unittest.main()
