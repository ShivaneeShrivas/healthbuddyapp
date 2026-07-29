"""Central configuration. Everything overridable via environment variables."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SECRET_KEY = os.environ.get("HB_SECRET_KEY", "dev-only-change-me")
    DATABASE = os.environ.get("HB_DATABASE", os.path.join(BASE_DIR, "healthbuddy.db"))
    JWT_ALGORITHM = "HS256"
    # Short-lived access token (sent on every request). Kept small on purpose —
    # if one leaks it's only useful for a short window.
    ACCESS_TOKEN_EXPIRY_MINUTES = int(os.environ.get("HB_ACCESS_TOKEN_EXPIRY_MINUTES", "60"))
    # Long-lived refresh token (used only to mint new access tokens). This is
    # what keeps a user signed in "like Instagram" — as long as they open the
    # app at least once within this window, they're never asked to log in
    # again. Sliding: every refresh pushes the expiry back out by this many days.
    REFRESH_TOKEN_EXPIRY_DAYS = int(os.environ.get("HB_REFRESH_TOKEN_EXPIRY_DAYS", "60"))

    # Web Push (VAPID). Generate with: python generate_vapid_keys.py
    # Works for browsers AND for the PWABuilder-wrapped Android APK, since
    # that's a Trusted Web Activity running on Chrome's push stack — no
    # separate Firebase console project is required.
    VAPID_PUBLIC_KEY = os.environ.get("HB_VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("HB_VAPID_PRIVATE_KEY", "")
    VAPID_CLAIM_EMAIL = os.environ.get("HB_VAPID_CLAIM_EMAIL", "mailto:admin@example.com")
    # Shared secret for POST /api/push/run-tick - lets a free external cron
    # pinger drive notifications on free hosting without a paid background
    # worker. Leave unset to disable the endpoint entirely.
    TICK_SECRET = os.environ.get("HB_TICK_SECRET", "")
    # The 4 daily push slots (morning/afternoon/evening/night) and their hour
    # windows live in services/notify.py (SLOTS) since they're content-adjacent.

    # Password reset tokens (forgot-password flow). Short-lived and single-use.
    RESET_TOKEN_EXPIRY_MINUTES = int(os.environ.get("HB_RESET_TOKEN_EXPIRY_MINUTES", "30"))
    # No email provider is wired up yet, so the reset link is logged server-side
    # (see services/email.py). Keep this on for local/dev/demo use so the flow
    # is testable end-to-end; turn OFF once real email sending is configured,
    # since exposing the token in the API response is not safe for production.
    EXPOSE_RESET_TOKEN = os.environ.get("HB_EXPOSE_RESET_TOKEN", "1") == "1"

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
