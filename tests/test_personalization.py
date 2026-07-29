"""Tests for personalization v2: daily plan, profile, activity, permissions."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from healthbuddy import create_app
from healthbuddy.services import daily_plan, segmentation, notify


class PersonalizationTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True, "SECRET_KEY": "test"})
        self.client = self.app.test_client()
        self._seed_cards()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _seed_cards(self):
        import json
        from healthbuddy.db import execute
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with self.app.app_context():
            with open(os.path.join(base, "content", "cards.json")) as f:
                for c in json.load(f):
                    execute("INSERT INTO notification_cards (category, emoji, title, body, action_label, audience) "
                            "VALUES (?,?,?,?,?,?)",
                            (c["category"], c["emoji"], c["title"], c["body"],
                             c.get("action_label", "Done"), c.get("audience", "all")))

    def auth(self, email="p@example.com", gender="female", goals=None):
        res = self.client.post("/api/auth/register",
                               json={"email": email, "name": "Pri", "password": "password123"})
        tok = res.get_json()["token"]
        h = {"Authorization": "Bearer " + tok}
        self.client.post("/api/onboarding", headers=h,
                         json={"occupation": "student", "gender": gender,
                               "activity_level": "moderate",
                               "health_goals": goals or ["general"]})
        return h

    # ---------- daily plan ----------
    def test_daily_plan_stable_within_day_and_changes_next_day(self):
        h = self.auth()
        with self.app.app_context():
            a = daily_plan.build(1, "2026-07-20")
            b = daily_plan.build(1, "2026-07-20")
            c = daily_plan.build(1, "2026-07-21")
        self.assertEqual([t["id"] for t in a], [t["id"] for t in b])   # same day → identical
        self.assertNotEqual([t["id"] for t in a], [t["id"] for t in c])  # new day → new plan
        slots = [t["slot"] for t in a]
        self.assertEqual(slots, ["morning", "afternoon", "night"])
        self.assertEqual(len({t["category"] for t in a}), 3)           # varied categories

    def test_daily_plan_bonus_awarded_once(self):
        h = self.auth()
        plan = self.client.get("/api/daily-plan", headers=h).get_json()["plan"]
        total_xp = 0
        for i, t in enumerate(plan["tasks"]):
            res = self.client.post(f"/api/nudges/{t['id']}/interact", headers=h,
                                   json={"action": "acted"}).get_json()
            total_xp += res["xp_earned"]
            if i == 2:
                self.assertEqual(res.get("daily_plan_bonus"), 30)      # bonus on 3rd
        plan = self.client.get("/api/daily-plan", headers=h).get_json()["plan"]
        self.assertEqual(plan["completed"], 3)
        self.assertTrue(plan["bonus_earned"])
        # act on something else — bonus must not repeat
        res = self.client.get("/api/nudges/next", headers=h).get_json()["nudge"]
        again = self.client.post(f"/api/nudges/{res['id']}/interact", headers=h,
                                 json={"action": "acted"}).get_json()
        self.assertNotIn("daily_plan_bonus", again)

    # ---------- profile ----------
    def test_profile_get_and_patch_persists(self):
        h = self.auth()
        me = self.client.get("/api/profile", headers=h).get_json()["profile"]
        self.assertEqual(me["gender"], "female")
        res = self.client.patch("/api/profile", headers=h,
                                json={"name": "Priya", "avatar": "🦊", "step_goal": 6000,
                                      "health_goals": ["sleep", "stress"], "age_range": "18_24"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("✨", res.get_json()["message"])
        me = self.client.get("/api/profile", headers=h).get_json()["profile"]
        self.assertEqual((me["name"], me["avatar"], me["step_goal"]), ("Priya", "🦊", 6000))
        self.assertEqual(me["health_goals"], ["sleep", "stress"])
        bad = self.client.patch("/api/profile", headers=h, json={"step_goal": 999})
        self.assertEqual(bad.status_code, 400)

    def test_goal_change_shifts_personalization(self):
        h = self.auth(goals=["fitness"])
        self.client.patch("/api/profile", headers=h, json={"health_goals": ["sleep"]})
        t = self.client.get("/api/transparency", headers=h).get_json()["state"]
        top = t[0]["category"]
        self.assertIn(top, ("sleep", "mindfulness"))                   # priors re-seeded

    def test_multi_goal_segmentation_blends(self):
        with self.app.app_context():
            w = segmentation.compute_weights(["fitness", "sleep"], "student", "moderate")
            single_fit = segmentation.compute_weights("fitness", "student", "moderate")
        self.assertGreater(w["sleep"], single_fit["sleep"])            # sleep goal now matters
        self.assertLess(w["movement"], single_fit["movement"])         # blended, not stacked
        self.assertAlmostEqual(sum(w.values()), 1.0, places=5)

    # ---------- activity ----------
    def test_activity_honest_absence_then_manual(self):
        h = self.auth()
        res = self.client.get("/api/activity/today", headers=h).get_json()
        self.assertIsNone(res["activity"])                             # no fake zeros
        self.client.post("/api/activity/manual", headers=h, json={"steps": 6400})
        res = self.client.get("/api/activity/today", headers=h).get_json()
        self.assertEqual(res["activity"]["steps"], 6400)
        self.assertEqual(res["activity"]["source"], "manual")
        bad = self.client.post("/api/activity/manual", headers=h, json={"steps": -5})
        self.assertEqual(bad.status_code, 400)

    def test_step_goal_hit_suppresses_movement(self):
        h = self.auth()
        self.client.patch("/api/profile", headers=h, json={"step_goal": 5000})
        self.client.post("/api/activity/manual", headers=h, json={"steps": 9000})
        with self.app.app_context():
            from healthbuddy.services.nudges import _suppressed_categories
            self.assertIn("movement", _suppressed_categories(1))
            picks = notify.compose(1, now=datetime(2026, 7, 20, 15, 0))
            self.assertFalse(any(p["id"] in ("legs_texted", "plot_twist", "steps_quiet")
                                 for p in picks))
            self.assertTrue(any(p["id"] == "steps_hit" for p in picks))  # celebration instead

    def test_steps_near_goal_encouragement(self):
        h = self.auth()
        self.client.patch("/api/profile", headers=h, json={"step_goal": 8000})
        self.client.post("/api/activity/manual", headers=h, json={"steps": 7300})
        with self.app.app_context():
            picks = notify.compose(1, now=datetime(2026, 7, 20, 17, 0))
            self.assertTrue(any(p["id"] == "steps_close" for p in picks))

    # ---------- permissions ----------
    def test_permissions_center_and_revoke(self):
        h = self.auth()
        res = self.client.get("/api/permissions", headers=h).get_json()["integrations"]
        keys = {i["key"] for i in res}
        self.assertEqual(keys, {"activity", "screen_time", "notifications", "period_care"})
        self.client.patch("/api/permissions", headers=h,
                          json={"integration": "activity", "status": "connected"})
        # synced (non-manual) writes require connection; revoking blocks them
        ok = self.client.post("/api/activity/sync", headers=h,
                              json={"steps": 4000, "source": "health_connect"})
        self.assertEqual(ok.status_code, 200)
        self.client.patch("/api/permissions", headers=h,
                          json={"integration": "activity", "status": "revoked"})
        blocked = self.client.post("/api/activity/sync", headers=h,
                                   json={"steps": 4200, "source": "health_connect"})
        self.assertEqual(blocked.status_code, 403)
        # app keeps working after revoke
        self.assertEqual(self.client.get("/api/dashboard", headers=h).status_code, 200)

    def test_notifications_master_switch(self):
        h = self.auth()
        self.client.patch("/api/permissions", headers=h,
                          json={"integration": "notifications", "status": "disconnected"})
        with self.app.app_context():
            self.assertEqual(notify.compose(1, now=datetime(2026, 7, 20, 15, 0)), [])


if __name__ == "__main__":
    unittest.main()


class UndoLogTestCase(PersonalizationTestCase):
    def test_undo_log_removes_entry_and_xp(self):
        h = self.auth(email="undo@example.com")
        self.client.post("/api/logs", headers=h, json={"type": "water", "value": 1})
        xp_before = self.client.get("/api/gamification/profile", headers=h).get_json()["xp"]
        self.client.delete("/api/logs/water", headers=h)
        d = self.client.get("/api/dashboard", headers=h).get_json()
        self.assertEqual(d["score"]["today"]["water"]["total"], 0)
        xp_after = self.client.get("/api/gamification/profile", headers=h).get_json()["xp"]
        self.assertEqual(xp_before - xp_after, 5)
        self.assertEqual(self.client.delete("/api/logs/water", headers=h).status_code, 404)
        self.assertEqual(self.client.delete("/api/logs/chai", headers=h).status_code, 400)
