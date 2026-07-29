# Deployment runbook — HealthBuddy pilot

## Target setup (simplest thing that works)
One small VM (or a free-tier host like Railway/Render/Fly.io), gunicorn behind
nginx or the platform's built-in TLS. SQLite on a persistent disk is fine for a
few hundred pilot users.

```bash
export HB_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export HB_DATABASE=/var/lib/healthbuddy/healthbuddy.db
pip install -r requirements.txt
python seed.py
gunicorn -w 2 -b 0.0.0.0:8000 "healthbuddy:create_app()"
```

## Deploy checklist

### Pre-deploy
- [ ] `python -m unittest discover tests` — all 17 green
- [ ] `HB_SECRET_KEY` set to a random 64-hex value (NEVER the dev default)
- [ ] `HB_DATABASE` points at a persistent, backed-up path
- [ ] TLS in front (JWTs travel as bearer headers — HTTPS is mandatory)
- [ ] `debug=True` only in run.py (dev entrypoint); production uses gunicorn — verified
- [ ] Seed script run once (idempotent — safe to re-run)
- [ ] Rollback plan: previous release tag + copy of the .db file before deploy

### Deploy
- [ ] Deploy, then smoke test: `GET /health` → `{"status":"ok"}`
- [ ] Register a throwaway account, complete onboarding, pull a nudge, act on it
- [ ] Check the transparency screen shows 6 categories with sane affinities
- [ ] Watch logs for 15 minutes

### Post-deploy
- [ ] Nightly `sqlite3 healthbuddy.db ".backup backup-$(date +%F).db"` cron
- [ ] Dogfood with the small friend group before wider general soft launch (per spec)
- [ ] Track weekly: DAU, nudge act-rate by category, D7 retention

### Rollback triggers
- /health failing or 5xx rate above 2%
- Login or onboarding flow broken
- Bandit selecting only one category for all users (check /transparency across accounts)

## Phase 2 — real phone push notifications (deploy AFTER the core app is live)

The brains already exist: `services/notify.py` composes personalized messages
(quiet hours enforced inside it). Today they're delivered via the in-app bell
(`GET /api/notifications`). Real pop-up-on-the-phone push adds a delivery layer:

1. Create a Firebase project → enables FCM (free; covers Android + web push;
   APNs for iOS routes through FCM too). Put the service-account JSON path in
   env var `HB_FCM_CREDENTIALS`.
2. Add a `device_tokens` table (user_id, token, platform) and a
   `POST /api/devices` endpoint — the app registers its token after the user
   grants notification permission.
3. Run a scheduler worker as a SECOND process next to gunicorn:
   `python push_worker.py` (cron-style loop, every 15–30 min:
   for each active user → `notify.compose(user)` → send top pick via FCM).
   On a platform host this is a "background worker" dyno; on a VM, a
   systemd service or cron job.
4. Web/PWA users additionally need a service worker + VAPID keys (HTTPS only).
5. Note: screen-time triggers ("scrolling long enough to bake bread") can't be
   seen by the server — those fire as LOCAL notifications inside the phone app
   using on-device usage APIs, reusing the same template copy.

Checklist additions for this phase:
- [ ] `HB_FCM_CREDENTIALS` set; worker process running and logged
- [ ] Token cleanup on FCM "unregistered" errors
- [ ] Verify quiet hours: send a test at 23:30 → nothing should arrive
- [ ] Per-user daily cap (e.g. max 4 pushes/day) before wide rollout

## Security notes (reviewed)
- Passwords: scrypt (n=2^14) with per-user salt, constant-time compare
- SQL: 100% parameterized queries (the one f-string builds only `?` placeholders)
- XSS: all dynamic strings HTML-escaped client-side (`esc()`)
- Before public launch add: rate limiting on /auth/*, email verification, CORS policy
  if the API is ever served on a different origin than the app
