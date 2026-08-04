"""Central configuration. Everything overridable via environment variables."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SECRET_KEY = os.environ.get("HB_SECRET_KEY", "dev-only-change-me")
    # Local SQLite file — used automatically when HB_DATABASE_URL isn't set.
    # Fine for `python run.py` on your own laptop. On a host with an
    # ephemeral filesystem (e.g. Render's free tier) this file — and every
    # account in it — gets wiped on every restart/redeploy/spin-down, so
    # don't rely on it in production.
    DATABASE = os.environ.get("HB_DATABASE", os.path.join(BASE_DIR, "healthbuddy.db"))
    # Postgres connection string (e.g. from Neon or Supabase's free tier).
    # When set, the app uses Postgres instead of SQLite and data survives
    # restarts/redeploys — set this in production. Example:
    # postgresql://user:password@host/dbname?sslmode=require
    DATABASE_URL = os.environ.get("HB_DATABASE_URL")
    JWT_ALGORITHM = "HS256"
    # Short-lived access token (sent on every request). Kept small on purpose —
    # if one leaks it's only useful for a short window.
    ACCESS_TOKEN_EXPIRY_MINUTES = int(os.environ.get("HB_ACCESS_TOKEN_EXPIRY_MINUTES", "60"))
    # Long-lived refresh token (used only to mint new access tokens). This is
    # what keeps a user signed in "like Instagram" — as long as they open the
    # app at least once within this window, they're never asked to log in
    # again. Sliding: every refresh pushes the expiry back out by this many days.
    REFRESH_TOKEN_EXPIRY_DAYS = int(os.environ.get("HB_REFRESH_TOKEN_EXPIRY_DAYS", "60"))

    # Bandit tuning
    PRIOR_STRENGTH = 20          # pseudo-observations encoded from onboarding
    RECENT_CARD_WINDOW = 10      # avoid repeating the last N cards

    # Reward mapping: interaction -> reward signal for Thompson Sampling
    REWARDS = {"acted": 1.0, "opened": 0.6, "snoozed": 0.2, "dismissed": 0.0}

    # XP economy
    XP = {
        "nudge_acted": 10,
        "nudge_opened": 2,
        "habit_log": 5,
        "challenge_join": 15,
        "streak_bonus": 20,      # every 7-day streak milestone
        "onboarding": 25,
        "game_played": 5,
        "daily_challenge": 15,
        "cycle_checkin": 5,
        "wrapped_viewed": 10,
        "daily_plan_bonus": 30,
    }


CATEGORIES = ["nutrition", "hydration", "movement", "sleep", "mindfulness", "seasonal"]

CATEGORY_META = {
    "nutrition":   {"emoji": "🥗", "label": "Nutrition",   "color": "#FF8A5C"},
    "hydration":   {"emoji": "💧", "label": "Hydration",   "color": "#4FC3F7"},
    "movement":    {"emoji": "🏃", "label": "Movement",    "color": "#7ED957"},
    "sleep":       {"emoji": "😴", "label": "Sleep",       "color": "#B39DFF"},
    "mindfulness": {"emoji": "🧘", "label": "Mindfulness", "color": "#F7A8C4"},
    "seasonal":    {"emoji": "🌦️", "label": "Seasonal",   "color": "#FFD166"},
}
