# HealthBuddy 🌱

A warm, friendly health-nudge companion for the IIT Kanpur pilot. Onboarding seeds a
Thompson Sampling bandit; every nudge interaction teaches it what actually works for you.
Quick-logs, streaks, XP, badges, challenges, buddies, and a "why am I seeing this?"
transparency screen — all in a mobile-first web app with zero build step.

## Quick start (under 2 minutes)

```bash
pip install -r requirements.txt      # Flask + PyJWT (+ gunicorn for prod)
python seed.py --demo                # content bank, challenges, demo account
python run.py                        # http://localhost:8000
```

Sign in as `demo@healthbuddy.app` / `demopass123`, or register fresh and walk the
4-step onboarding.

Run tests: `python -m unittest discover tests -v` (17 tests: segmentation,
bandit convergence, gamification curve, full API integration).

## Architecture

```
Browser (SPA, /static/app.js)                 Mobile-first, PWA-ready
        │  JSON + JWT bearer
        ▼
Flask app factory (healthbuddy/__init__.py)
        │
routes/api.py            thin HTTP layer: validation + friendly errors
        │
services/                framework-agnostic business logic (ports to FastAPI as-is)
  segmentation.py        onboarding answers → normalized category weights
  bandit.py              Thompson Sampling: seed priors, select, update, explain
  nudges.py              card selection, interaction logging, health score
  gamification.py        XP economy, level curve, streaks, badge predicates
  social.py              challenges, leaderboards, buddy links
        │
db.py                    thin SQLite layer (Postgres swap = change this file)
```

**The learning loop** (the product's differentiator, live from v1):

1. Onboarding → `segmentation.compute_weights()` → weights `w` per category
2. `bandit.seed_priors()` sets Beta(1 + 20·w, 1 + 20·(1−w)) — the first nudge is already an informed guess
3. `GET /api/nudges/next` samples each posterior, picks the max, logs `sent`
4. Every interact (`acted`=1.0, `opened`=0.6, `snoozed`=0.2, `dismissed`=0) updates the posterior
5. The interaction log doubles as the training data for future richer models (Phase 4)

## API reference

All endpoints under `/api`; authenticated routes need `Authorization: Bearer <token>`.

| Method | Path | Purpose |
|---|---|---|
| POST | /auth/register | `{name,email,password}` → token (201) |
| POST | /auth/login | `{email,password}` → `{otp_required, email}` (sends emailed code) or token if `HB_REQUIRE_LOGIN_OTP=0` |
| POST | /auth/login/verify-otp | `{email,code}` → token (step 2 of sign-in) |
| POST | /auth/login/resend-otp | `{email}` → sends a fresh sign-in code |
| GET | /me | current user |
| POST | /onboarding | `{degree,gender,activity_level,health_goal}` → weights, seeds bandit |
| GET | /nudges/next | bandit-selected nudge card |
| POST | /nudges/:id/interact | `{action: acted\|opened\|snoozed\|dismissed}` → XP, badges |
| GET | /nudges/feed | recent nudges |
| POST | /logs | `{type: water\|meal\|sleep\|mood, value}` → XP, streak |
| GET | /dashboard | health score + components, streaks, level |
| GET | /history/:habit | 30-day trend data |
| GET | /cards, /cards/daily | knowledge hub + card of the day |
| GET | /gamification/profile | XP, level, badge wall, streaks |
| GET | /transparency | bandit affinities ("why am I seeing this?") |
| PATCH | /preferences | category multipliers, quiet hours |
| GET/POST | /challenges, /challenges/:id/join, /challenges/:id/leaderboard | challenges |
| GET/POST | /buddies, /buddies/link | buddy system |

Errors are always `{"error": "<what happened + how to fix>"}` with a proper status code.

## Design system

Bright "sunrise citrus" light theme. Tokens live at the top of `static/styles.css`:
background `#FFF8F0`, brand gradient `#FF8A5C → #FF5C8A`, one vivid color per
nudge category (mirrored in `config.CATEGORY_META` so backend and frontend agree).
Type: Fredoka (display) + Nunito Sans (body). Accessibility: 44px+ touch targets,
visible focus rings, ARIA roles on progress/dialogs, `aria-live` toasts,
`prefers-reduced-motion` respected.

## Email delivery (password reset + login verification)

Two flows send a 6-digit code by email, both single-use and scoped to the account:

- **Forgot password** (`/api/auth/forgot-password` → `/api/auth/reset-password`)
- **Sign-in verification** — after a correct password, `/api/auth/login` no
  longer returns tokens directly. It emails a code and responds
  `{ otp_required: true }`; the client then calls
  `/api/auth/login/verify-otp` with that code to actually get tokens. Set
  `HB_REQUIRE_LOGIN_OTP=0` to turn this step off (e.g. before SMTP is set up).

Both go through SMTP. Without SMTP configured, the code is returned directly in
the API response instead (dev-only fallback, `HB_EXPOSE_RESET_TOKEN` /
`HB_EXPOSE_LOGIN_OTP`, both on by default) so either flow still works without
an inbox — set these to send real email:

```bash
HB_SMTP_HOST=smtp.gmail.com     # or your provider's SMTP relay
HB_SMTP_PORT=587
HB_SMTP_USER=you@gmail.com      # for SendGrid this is literally "apikey"
HB_SMTP_PASS=your-app-password  # Gmail: generate an "App Password", not your login password
HB_FROM_EMAIL=you@gmail.com     # optional, defaults to HB_SMTP_USER

# optional tuning for the login-verification step
HB_REQUIRE_LOGIN_OTP=1          # set to 0 to skip email verification at login
HB_LOGIN_OTP_EXPIRY_MINUTES=10
HB_LOGIN_OTP_MAX_ATTEMPTS=5
```

Any STARTTLS-speaking provider works: Gmail, SendGrid, Mailgun, SES, Postmark,
your own mail server. Set these as environment variables on Render (or
wherever you deploy) — never commit real credentials to the repo.

## Known limits & next steps (in order)

1. **Push delivery**: nudges are pulled in-app today. Wire Firebase Cloud Messaging:
   store FCM device tokens per user, add a scheduler (cron/APScheduler) that respects
   `quiet_start/quiet_end`, and call `nudges.next_nudge()` server-side per user.
2. **Postgres**: swap `db.py` for psycopg when the pilot outgrows SQLite; move
   `create_all`-style schema to Alembic migrations.
3. **Rate limiting** on auth endpoints before opening beyond the friend group (signup/
   login/forgot-password aren't throttled per-IP yet). Sign-up email is validated
   (format + live MX/DNS lookup, see `services/email_validate.py`) and password-reset
   codes are emailed for real via SMTP (`services/mailer.py`) — still open: a
   sign-up confirmation email to verify the person actually owns the mailbox.
4. **Native app**: the API is client-agnostic — point a Flutter/React Native app at it.
5. Leaderboard computes progress per member per request — fine for a pilot, cache it
   at a few hundred concurrent users.
