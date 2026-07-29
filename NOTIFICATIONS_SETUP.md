# Push Notifications — Setup Guide

This adds the missing piece: real phone notifications that arrive even when
HealthBuddy is closed, plus the browser permission prompt that was never
being triggered before.

## What was missing (root cause)

1. Nothing ever called `Notification.requestPermission()` — so the browser
   never showed the "Allow notifications?" prompt at all.
2. There was no `PushManager.subscribe()` call and no backend table to store
   *where* to deliver a notification, even if permission had been granted.
3. `services/notify.py` could already **compose** a good nudge message, but
   nothing **sent** it anywhere except the in-app bell — there was no
   delivery layer.

This update fixes all three.

## What's new

| File | What it does |
|---|---|
| `healthbuddy/db.py` | new `push_subscriptions` table |
| `healthbuddy/config.py` | VAPID key config (env-driven) |
| `healthbuddy/services/push.py` | sends web push via VAPID, cleans up dead subscriptions |
| `healthbuddy/routes/api.py` | `GET /push/public-key`, `POST /push/subscribe`, `POST /push/unsubscribe`, `POST /push/test` |
| `healthbuddy/static/sw.js` | now handles `push` and `notificationclick` events |
| `healthbuddy/static/app.js` | requests permission, subscribes, shows status in Profile, prompts right after onboarding |
| `generate_vapid_keys.py` | one-time script to create your VAPID keypair |
| `push_worker.py` | background loop that pushes nudges to subscribed users on a schedule |

**Why Web Push (VAPID) instead of setting up a Firebase project**: your
Android install is a PWABuilder-wrapped Trusted Web Activity — it's Chrome
under the hood, so standard Web Push already routes through FCM
automatically. No `google-services.json`, no Firebase console project, no
native SDK. Same code serves desktop browsers, mobile Chrome, and the APK.

## 1. Generate your VAPID keypair (once, ever)

```bash
pip install -r requirements.txt
python generate_vapid_keys.py
```

Copy the two printed lines into your environment:

```bash
export HB_VAPID_PUBLIC_KEY="BOjt..."
export HB_VAPID_PRIVATE_KEY="wovO..."
export HB_VAPID_CLAIM_EMAIL="mailto:you@example.com"   # any contact email
```

On Render/Railway/Fly: add these as environment variables in the dashboard,
not in code — the private key must stay secret.

## 2. Run the app + the push worker (two processes)

```bash
# terminal 1
python run.py

# terminal 2 — this is what makes nudges arrive with the app closed
python push_worker.py
```

In production, run `push_worker.py` as a **separate worker process/service**
next to your gunicorn web process — never inside a request-handling web
dyno, since it's an infinite loop. On Render: add it as a second "Background
Worker" service pointed at the same repo, same env vars.

## 3. Test permission + delivery end-to-end

1. Open the app, register or log in, complete onboarding.
2. You'll now see a modal: **"Want nudges to actually reach you?"** — tap
   **Enable notifications**. Your browser/OS will show the real permission
   prompt (this only fires because it's tied to that button tap — browsers
   block permission prompts that aren't triggered by a direct click).
3. Go to **Profile** — you should see "✅ On — you'll get nudges even when
   the app's closed" plus a **Send me a test notification** button. Tap it.
4. **Close the app completely** (swipe it away, don't just background it)
   and wait — the test button sends instantly; the background worker sends
   on its normal ~20-minute cadence after that (`HB_PUSH_INTERVAL_MINUTES`).
5. A system notification should appear in your phone's notification tray.
   Tapping it opens the app straight to the Nudges screen.

If nothing arrives: check `push_worker.py`'s terminal output first — it
prints every send attempt and any errors.

## 4. Rebuilding the APK via PWABuilder

Because this is a PWA wrapped as a Trusted Web Activity, you do **not** need
to rebuild the APK just to get push working — service worker + push code is
fetched from your live site each time the app opens, same as any other web
asset. You only need to rebuild if you changed `manifest.json` (icons, name,
etc). If you do rebuild:

1. Deploy the updated backend + static files first (Render/wherever).
2. Go to [pwabuilder.com](https://www.pwabuilder.com), re-enter your site URL.
3. Regenerate the Android package — PWABuilder auto-detects the service
   worker and includes the notification permission
   (`android.permission.POST_NOTIFICATIONS`, required on Android 13+) in the
   generated manifest.
4. Reinstall the APK on your test device (uninstall the old one first to
   avoid a stale service worker being cached).

## 5. Tuning

In `config.py` / env vars:
- `HB_PUSH_INTERVAL_MINUTES` (default 20) — minimum gap between pushes to
  the same user.
- `HB_PUSH_DAILY_CAP` (default 4) — hard ceiling per user per day, so the
  worker can never spam even if something misbehaves.

Quiet hours are enforced inside `notify.py` itself (`_in_quiet_hours`), so
the worker will simply get an empty pick list during a user's quiet window
— nothing to fix there, it already works correctly once push is wired up.

## 6. Also worth fixing: the login bug you saw

Separately from notifications — if login says "invalid" even with the
correct email/password after some time has passed, this is almost certainly
**not** an auth bug but the database resetting. `HB_DATABASE` defaults to a
local SQLite file (`healthbuddy.db`) in the project folder. On a free-tier
host like Render, the filesystem is **ephemeral** — it gets wiped on every
redeploy and sometimes on a cold restart after the free instance sleeps.
That silently deletes every registered account, which is indistinguishable
from a "wrong password" error to a returning user.

**Fix options, in order of effort:**
1. **Quickest**: attach a persistent disk on Render and point
   `HB_DATABASE` at a path on it (e.g. `/var/data/healthbuddy.db`) — costs a
   small monthly fee on Render but keeps SQLite as-is.
2. **More robust for pilot scale**: move to a hosted Postgres (Render/Neon/
   Supabase all have free tiers) — bigger change since `db.py` currently
   uses raw `sqlite3`, but this was already the planned Phase-4 direction
   in your original spec anyway.
