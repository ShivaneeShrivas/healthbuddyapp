"""Central configuration. Everything overridable via environment variables."""
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    # Identifies exactly which deploy is running - shown at GET /api/version and
    # used to cache-bust static assets (see templates/index.html), so "is my
    # latest code actually live?" always has a definitive answer instead of
    # guessing from browser behavior. Render sets RENDER_GIT_COMMIT automatically
    # on every deploy; falls back to process-start time so it still changes on
    # every restart even without that (e.g. running elsewhere, or locally).
    APP_VERSION = (os.environ.get("RENDER_GIT_COMMIT", "")[:8]
                   or os.environ.get("HB_APP_VERSION", "")
                   or str(int(time.time())))

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

    # Password reset codes (forgot-password flow). Short-lived, single-use,
    # 6-digit OTP style codes (not long tokens) so they're easy to type.
    RESET_TOKEN_EXPIRY_MINUTES = int(os.environ.get("HB_RESET_TOKEN_EXPIRY_MINUTES", "15"))
    RESET_CODE_MAX_ATTEMPTS = int(os.environ.get("HB_RESET_CODE_MAX_ATTEMPTS", "5"))
    # If a real SMTP server is configured below, the reset code is emailed
    # and never echoed back in the API response. If SMTP is NOT configured
    # (e.g. local dev), the code is returned in the response so the flow is
    # still testable end-to-end without an inbox - see routes/api.py.
    EXPOSE_RESET_TOKEN = os.environ.get("HB_EXPOSE_RESET_TOKEN", "1") == "1"

    # Email-verification-at-login: after a correct password, a 6-digit code
    # is emailed and must be entered before tokens are issued. Uses the same
    # SMTP settings below. Set HB_REQUIRE_LOGIN_OTP=0 to turn this step off
    # entirely (e.g. while SMTP isn't configured yet in dev).
    REQUIRE_LOGIN_OTP = os.environ.get("HB_REQUIRE_LOGIN_OTP", "1") == "1"
    LOGIN_OTP_EXPIRY_MINUTES = int(os.environ.get("HB_LOGIN_OTP_EXPIRY_MINUTES", "10"))
    LOGIN_OTP_MAX_ATTEMPTS = int(os.environ.get("HB_LOGIN_OTP_MAX_ATTEMPTS", "5"))
    # Same fallback as password reset: if SMTP isn't configured, the code is
    # returned in the response body instead of silently stranding the user.
    EXPOSE_LOGIN_OTP = os.environ.get("HB_EXPOSE_LOGIN_OTP", "1") == "1"

    # Outbound email (password reset codes, etc) via any SMTP+STARTTLS
    # provider - Gmail (App Password), SendGrid, Mailgun, SES, Postmark...
    # See services/mailer.py for exactly how these are used.
    SMTP_HOST = os.environ.get("HB_SMTP_HOST", "")
    SMTP_PORT = os.environ.get("HB_SMTP_PORT", "587")
    SMTP_USER = os.environ.get("HB_SMTP_USER", "")
    SMTP_PASS = os.environ.get("HB_SMTP_PASS", "")
    FROM_EMAIL = os.environ.get("HB_FROM_EMAIL", "")

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
