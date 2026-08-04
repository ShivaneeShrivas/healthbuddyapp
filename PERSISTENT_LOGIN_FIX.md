# Why you were getting signed out (and why re-logging-in failed too)

**It wasn't a login bug.** The app-side code for "stay signed in like Instagram"
was already correct — short-lived access token + long-lived refresh token,
stored securely, silently renewed. That part didn't need fixing.

The real problem: your database is a single SQLite file (`healthbuddy.db`),
and Render's **free** web service plan has an *ephemeral filesystem*. Render's
own docs say it plainly — any local file changes are lost every time the
service redeploys, restarts, **or spins down** (which free instances do after
~15 idle minutes). So every time that happened, your whole `users` table —
every account, not just yours — was wiped. Re-entering the same email and
password failed because, as far as the server was concerned, that account had
never existed.

## The fix

The app now supports Postgres as well as SQLite. Point it at a **free,
persistent** Postgres database and the wipe problem goes away completely —
nothing else about how login works needs to change.

- Set the environment variable `HB_DATABASE_URL` → the app uses Postgres.
- Leave it unset → the app falls back to the local SQLite file, exactly as
  before (still handy for `python run.py` on your own laptop).

## Get a free Postgres database (5 minutes)

Either of these work well and don't expire from inactivity:

**Option 1 — Neon** (https://neon.tech)
1. Sign up free, create a project.
2. Copy the connection string it gives you (starts with `postgresql://...`,
   ends with `?sslmode=require`).

**Option 2 — Supabase** (https://supabase.com)
1. Sign up free, create a project.
2. Project Settings → Database → copy the "Connection string" (URI format,
   use the **pooled/transaction** connection string on port 6543 if offered).

## Wire it into Render

1. Render dashboard → your `healthbuddy` service → **Environment**.
2. Add a variable:
   - Key: `HB_DATABASE_URL`
   - Value: the connection string from Neon/Supabase above.
3. Save → Render redeploys automatically.
4. That's it. `db.py` detects `HB_DATABASE_URL` and switches to Postgres,
   creating all tables on first boot (same `init_db()` step as before).

## Verifying it worked

After the redeploy:
1. Register a **new** test account on your live link.
2. In the Render dashboard, trigger a **manual redeploy** (or just wait for
   the free tier to spin down after ~15 idle minutes, then visit the link
   again to wake it back up).
3. Log in again with that same test account.

Before this fix, step 3 would fail. Now it should just work — because the
account lives in Postgres, not on the app's local disk.

## What changed in the code

- `healthbuddy/config.py` — added `DATABASE_URL` (from `HB_DATABASE_URL`).
- `healthbuddy/db.py` — now supports both backends. All existing SQL in
  `services/`, `routes/`, `auth.py`, `seed.py` is untouched; `db.py`
  translates it on the fly when running against Postgres (`?` → `%s`,
  `datetime('now')` → `NOW()`, etc.), so nothing else in the codebase needed
  to change.
- `healthbuddy/routes/api.py`, `healthbuddy/services/cycle.py` — two
  `INSERT OR IGNORE` statements (SQLite-only syntax) were rewritten as
  `INSERT ... ON CONFLICT (...) DO NOTHING`, which is standard SQL and works
  identically on SQLite and Postgres.
- `requirements.txt` — added `psycopg[binary]` (the Postgres driver; only
  used when `HB_DATABASE_URL` is set).
- `tests/*.py` — test setup now explicitly forces the isolated SQLite path
  (`"DATABASE_URL": None`) so `python -m unittest discover tests` can never
  accidentally run against a real Postgres database, even if
  `HB_DATABASE_URL` happens to be set in your shell.

All 46 existing tests still pass unmodified. This was also tested end-to-end
against a real local Postgres instance: register → simulate a full process
restart (the exact failure mode you hit) → log in again → still works.
