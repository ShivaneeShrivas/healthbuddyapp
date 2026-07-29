"""HealthBuddy test suite (stdlib unittest; run: python -m unittest discover tests -v)."""
import os
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from healthbuddy import create_app
from healthbuddy.config import CATEGORIES
from healthbuddy.services.segmentation import compute_weights


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True, "SECRET_KEY": "test"})
        self.client = self.app.test_client()
        self._seed_content()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _seed_content(self):
        import json
        from healthbuddy.db import execute
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with self.app.app_context():
            with open(os.path.join(base, "content", "cards.json")) as f:
                for c in json.load(f):
                    execute("INSERT INTO notification_cards (category, emoji, title, body, action_label, audience, deep_dive) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (c["category"], c["emoji"], c["title"], c["body"],
                             c.get("action_label", "Done"), c.get("audience", "all"), c.get("deep_dive")))
            today = date.today().isoformat()
            end = (date.today() + timedelta(days=13)).isoformat()
            execute("INSERT INTO challenges (title, description, emoji, metric_type, target, starts_on, ends_on) "
                    "VALUES ('Hydration Week','desc','💧','water',7,?,?)", (today, end))

    def register(self, email="a@example.com", name="Asha", password="password123"):
        res = self.client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
        self.assertEqual(res.status_code, 201, res.get_json())
        return res.get_json()["token"]

    def auth(self, token):
        return {"Authorization": "Bearer " + token}

    def onboard(self, token, **kw):
        payload = dict(occupation="professional", gender="female", activity_level="inactive", health_goal="stress") | kw
        res = self.client.post("/api/onboarding", json=payload, headers=self.auth(token))
        self.assertEqual(res.status_code, 200, res.get_json())
        return res.get_json()


class TestSegmentation(unittest.TestCase):
    def test_weights_normalized(self):
        for goal in ("fitness", "stress", "sleep", "eat_better", "general"):
            w = compute_weights(goal, "student", "moderate")
            self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
            self.assertEqual(set(w), set(CATEGORIES))
            self.assertTrue(all(v > 0 for v in w.values()))

    def test_goal_dominates(self):
        w = compute_weights("fitness", "student", "moderate")
        self.assertEqual(max(w, key=w.get), "movement")
        w = compute_weights("stress", "student", "moderate")
        self.assertEqual(max(w, key=w.get), "mindfulness")

    def test_professional_boosts_mindfulness_and_sleep(self):
        professional = compute_weights("general", "professional", "moderate")
        student = compute_weights("general", "student", "moderate")
        self.assertGreater(professional["mindfulness"], student["mindfulness"])
        self.assertGreater(professional["sleep"], student["sleep"])

    def test_active_users_get_less_movement(self):
        active = compute_weights("general", "student", "active")
        inactive = compute_weights("general", "student", "inactive")
        self.assertLess(active["movement"], inactive["movement"])

    def test_gender_does_not_shift_category_weights(self):
        a = compute_weights("fitness", "student", "active", gender="female")
        b = compute_weights("fitness", "student", "active", gender="male")
        self.assertEqual(a, b)


class TestBandit(AppTestCase):
    def test_priors_match_segmentation(self):
        from healthbuddy.services import bandit
        token = self.register()
        self.onboard(token, health_goal="fitness")
        with self.app.app_context():
            from healthbuddy.db import query
            user_id = query("SELECT id FROM users", one=True)["id"]
            state = bandit.get_state(user_id)
        self.assertEqual(state[0]["category"], "movement")  # highest prior affinity

    def test_bandit_converges_to_rewarded_category(self):
        from healthbuddy.services import bandit
        token = self.register()
        self.onboard(token, health_goal="general")
        random.seed(42)
        with self.app.app_context():
            from healthbuddy.db import query
            user_id = query("SELECT id FROM users", one=True)["id"]
            # simulate: user loves hydration, ignores everything else
            for _ in range(300):
                cat = bandit.select_category(user_id)
                bandit.update(user_id, cat, "acted" if cat == "hydration" else "dismissed")
            picks = [bandit.select_category(user_id) for _ in range(100)]
        self.assertGreater(picks.count("hydration"), 80)

    def test_preference_multiplier_clamped(self):
        from healthbuddy.services import bandit
        token = self.register()
        self.onboard(token)
        with self.app.app_context():
            from healthbuddy.db import query
            user_id = query("SELECT id FROM users", one=True)["id"]
            bandit.set_preference(user_id, "sleep", 99)
            state = {s["category"]: s for s in bandit.get_state(user_id)}
        self.assertEqual(state["sleep"]["pref_multiplier"], 2.0)


class TestGamification(unittest.TestCase):
    def test_level_curve(self):
        from healthbuddy.services.gamification import level_for, xp_needed
        self.assertEqual(level_for(0), 1)
        self.assertEqual(level_for(59), 1)
        self.assertEqual(level_for(60), 2)
        self.assertEqual(level_for(240), 3)
        self.assertEqual(xp_needed(5), 960)


class TestAPIFlow(AppTestCase):
    """End-to-end: register → onboard → nudge → interact → log → dashboard → social."""

    def test_register_validation(self):
        res = self.client.post("/api/auth/register", json={"email": "bad", "name": "X", "password": "12345678"})
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/auth/register", json={"email": "x@y.com", "name": "X", "password": "short"})
        self.assertEqual(res.status_code, 400)

    def test_duplicate_email(self):
        self.register()
        res = self.client.post("/api/auth/register",
                               json={"email": "a@example.com", "name": "B", "password": "password123"})
        self.assertEqual(res.status_code, 409)

    def test_login_wrong_password(self):
        self.register()
        res = self.client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrongwrong"})
        self.assertEqual(res.status_code, 401)

    def test_nudge_requires_onboarding(self):
        token = self.register()
        res = self.client.get("/api/nudges/next", headers=self.auth(token))
        self.assertEqual(res.status_code, 409)

    def test_full_happy_path(self):
        token = self.register()
        data = self.onboard(token)
        self.assertAlmostEqual(sum(data["weights"].values()), 1.0, places=9)
        self.assertEqual(data["xp_earned"], 25)

        # get a nudge, act on it → XP + bandit update
        res = self.client.get("/api/nudges/next", headers=self.auth(token))
        self.assertEqual(res.status_code, 200)
        nudge = res.get_json()["nudge"]
        self.assertIn(nudge["category"], CATEGORIES)
        res = self.client.post(f"/api/nudges/{nudge['id']}/interact",
                               json={"action": "acted"}, headers=self.auth(token))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["xp_earned"], 10)

        # invalid interaction
        res = self.client.post(f"/api/nudges/{nudge['id']}/interact",
                               json={"action": "yeeted"}, headers=self.auth(token))
        self.assertEqual(res.status_code, 400)

        # log water → XP + first_sip badge
        res = self.client.post("/api/logs", json={"type": "water", "value": 1}, headers=self.auth(token))
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["xp_earned"], 5)
        self.assertIn("first_sip", [b["code"] for b in body["new_badges"]])
        self.assertEqual(body["streak"], 1)

        # invalid logs rejected
        self.assertEqual(self.client.post("/api/logs", json={"type": "mood", "value": 9},
                                          headers=self.auth(token)).status_code, 400)
        self.assertEqual(self.client.post("/api/logs", json={"type": "sleep", "value": 30},
                                          headers=self.auth(token)).status_code, 400)

        # dashboard reflects activity
        d = self.client.get("/api/dashboard", headers=self.auth(token)).get_json()
        self.assertGreater(d["score"]["score"], 0)
        self.assertEqual(d["streaks"]["water"], 1)
        self.assertGreaterEqual(d["xp"], 40)

        # feed and knowledge hub
        self.assertEqual(self.client.get("/api/nudges/feed", headers=self.auth(token)).status_code, 200)
        cards = self.client.get("/api/cards?category=hydration", headers=self.auth(token)).get_json()["cards"]
        self.assertTrue(all(c["category"] == "hydration" for c in cards))
        self.assertEqual(self.client.get("/api/cards/daily", headers=self.auth(token)).status_code, 200)

        # transparency
        t = self.client.get("/api/transparency", headers=self.auth(token)).get_json()
        self.assertEqual(len(t["state"]), 6)

        # challenges: join, progress, leaderboard
        ch = self.client.get("/api/challenges", headers=self.auth(token)).get_json()["challenges"][0]
        res = self.client.post(f"/api/challenges/{ch['id']}/join", headers=self.auth(token))
        self.assertEqual(res.get_json()["xp_earned"], 15)
        ch2 = self.client.get("/api/challenges", headers=self.auth(token)).get_json()["challenges"][0]
        self.assertTrue(ch2["joined"])
        self.assertEqual(ch2["progress"], 1)  # water logged today
        lb = self.client.get(f"/api/challenges/{ch['id']}/leaderboard", headers=self.auth(token)).get_json()
        self.assertEqual(lb["leaderboard"][0]["name"], "Asha")

    def test_buddy_flow(self):
        t1, t2 = self.register(), self.register(email="b@example.com", name="Bo")
        code2 = self.client.get("/api/buddies", headers=self.auth(t2)).get_json()["my_code"]
        # self-link rejected
        code1 = self.client.get("/api/buddies", headers=self.auth(t1)).get_json()["my_code"]
        self.assertEqual(self.client.post("/api/buddies/link", json={"code": code1},
                                          headers=self.auth(t1)).status_code, 400)
        # bad code
        self.assertEqual(self.client.post("/api/buddies/link", json={"code": "HB-NOPE99"},
                                          headers=self.auth(t1)).status_code, 404)
        # good link, reciprocal
        res = self.client.post("/api/buddies/link", json={"code": code2}, headers=self.auth(t1))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/api/buddies", headers=self.auth(t2)).get_json()["buddies"][0]["name"], "Asha")

    def test_preferences_update(self):
        token = self.register()
        self.onboard(token)
        res = self.client.patch("/api/preferences", headers=self.auth(token),
                                json={"category_weights": {"seasonal": 0.3}, "quiet_start": "22:30"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["user"]["quiet_start"], "22:30")

    def test_auth_required(self):
        for path in ("/api/dashboard", "/api/nudges/next", "/api/me"):
            self.assertEqual(self.client.get(path).status_code, 401)
        bad = self.client.get("/api/me", headers={"Authorization": "Bearer nonsense"})
        self.assertEqual(bad.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
