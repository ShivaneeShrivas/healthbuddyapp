"""Data layer — SQLite for local dev/tests, Postgres for production.

Deliberately thin: raw SQL behind small helpers. Which backend is active is
decided per-request from config:
  - HB_DATABASE_URL set (a Postgres connection string, e.g. from Neon/Supabase)
    -> Postgres, via psycopg. Data survives redeploys/restarts/spin-downs.
  - otherwise -> local SQLite file at HB_DATABASE. Zero setup, but on hosts
    with an ephemeral filesystem (e.g. Render's free tier) the file — and
    every account in it — is wiped on every restart. Fine for `python run.py`
    on your own laptop; NOT fine for a real deployment. Set HB_DATABASE_URL
    in production.

All call sites in services/routes write plain SQLite-flavoured SQL (`?`
placeholders, `datetime('now')`, `date('now')`, `date(col)`, `INSERT INTO
... ON CONFLICT (...) DO NOTHING/UPDATE`). When the Postgres backend is
active, `_translate()` rewrites that SQL on the fly, so business logic never
needs to know which database it's talking to.
"""
import re
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    buddy_code TEXT UNIQUE NOT NULL,
    occupation TEXT, gender TEXT, activity_level TEXT, health_goal TEXT,
    onboarded INTEGER NOT NULL DEFAULT 0,
    quiet_start TEXT NOT NULL DEFAULT '23:00',
    quiet_end TEXT NOT NULL DEFAULT '07:00',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notification_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    tone TEXT NOT NULL DEFAULT 'friendly',
    emoji TEXT NOT NULL DEFAULT '✨',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    action_label TEXT NOT NULL DEFAULT 'Done',
    audience TEXT NOT NULL DEFAULT 'all',
    deep_dive TEXT
);
CREATE TABLE IF NOT EXISTS bandit_states (
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta REAL NOT NULL,
    pref_multiplier REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (user_id, category)
);
CREATE TABLE IF NOT EXISTS interaction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id INTEGER NOT NULL REFERENCES notification_cards(id),
    category TEXT NOT NULL,
    action TEXT NOT NULL,            -- sent | opened | dismissed | acted | snoozed
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON interaction_logs(user_id, created_at);
CREATE TABLE IF NOT EXISTS habit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,              -- water | meal | sleep | mood
    value REAL NOT NULL DEFAULT 1,
    note TEXT,
    logged_on TEXT NOT NULL DEFAULT (date('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_habits_user_day ON habit_logs(user_id, type, logged_on);
CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS user_badges (
    user_id INTEGER NOT NULL REFERENCES users(id),
    badge_code TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, badge_code)
);
CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🏆',
    metric_type TEXT NOT NULL,       -- habit type or 'nudge_acted'
    target INTEGER NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenge_members (
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (challenge_id, user_id)
);
CREATE TABLE IF NOT EXISTS buddies (
    user_id INTEGER NOT NULL REFERENCES users(id),
    buddy_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, buddy_id)
);
CREATE TABLE IF NOT EXISTS cycle_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0,
    last_period_start TEXT,
    avg_cycle_len REAL NOT NULL DEFAULT 28,
    avg_period_len REAL NOT NULL DEFAULT 5,
    remind INTEGER NOT NULL DEFAULT 1,
    gcal_export INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cycle_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    start_date TEXT NOT NULL,
    UNIQUE (user_id, start_date)
);
CREATE TABLE IF NOT EXISTS activity_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    steps INTEGER NOT NULL DEFAULT 0,
    active_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS device_wellbeing_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    screen_time_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS integrations (
    user_id INTEGER NOT NULL REFERENCES users(id),
    integration_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_connected',
    granted_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (user_id, integration_type)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT UNIQUE NOT NULL,   -- sha256 of the refresh token; raw token never stored
    device_label TEXT,                 -- best-effort User-Agent snippet, for a future "manage devices" screen
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    game TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'easy',
    score REAL NOT NULL,
    is_daily INTEGER NOT NULL DEFAULT 0,
    played_on TEXT NOT NULL DEFAULT (date('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Same tables, Postgres-flavoured: SERIAL instead of AUTOINCREMENT, and
# NOW()/CURRENT_DATE (cast to text so they match the TEXT columns the app
# already expects everywhere) instead of SQLite's datetime('now')/date('now').
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    buddy_code TEXT UNIQUE NOT NULL,
    occupation TEXT, gender TEXT, activity_level TEXT, health_goal TEXT,
    onboarded INTEGER NOT NULL DEFAULT 0,
    quiet_start TEXT NOT NULL DEFAULT '23:00',
    quiet_end TEXT NOT NULL DEFAULT '07:00',
    created_at TEXT NOT NULL DEFAULT (NOW()::text)
);
CREATE TABLE IF NOT EXISTS notification_cards (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    tone TEXT NOT NULL DEFAULT 'friendly',
    emoji TEXT NOT NULL DEFAULT '✨',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    action_label TEXT NOT NULL DEFAULT 'Done',
    audience TEXT NOT NULL DEFAULT 'all',
    deep_dive TEXT
);
CREATE TABLE IF NOT EXISTS bandit_states (
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta REAL NOT NULL,
    pref_multiplier REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (user_id, category)
);
CREATE TABLE IF NOT EXISTS interaction_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id INTEGER NOT NULL REFERENCES notification_cards(id),
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (NOW()::text)
);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON interaction_logs(user_id, created_at);
CREATE TABLE IF NOT EXISTS habit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 1,
    note TEXT,
    logged_on TEXT NOT NULL DEFAULT (CURRENT_DATE::text),
    created_at TEXT NOT NULL DEFAULT (NOW()::text)
);
CREATE INDEX IF NOT EXISTS idx_habits_user_day ON habit_logs(user_id, type, logged_on);
CREATE TABLE IF NOT EXISTS xp_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (NOW()::text)
);
CREATE TABLE IF NOT EXISTS user_badges (
    user_id INTEGER NOT NULL REFERENCES users(id),
    badge_code TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (NOW()::text),
    PRIMARY KEY (user_id, badge_code)
);
CREATE TABLE IF NOT EXISTS challenges (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🏆',
    metric_type TEXT NOT NULL,
    target INTEGER NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenge_members (
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at TEXT NOT NULL DEFAULT (NOW()::text),
    PRIMARY KEY (challenge_id, user_id)
);
CREATE TABLE IF NOT EXISTS buddies (
    user_id INTEGER NOT NULL REFERENCES users(id),
    buddy_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (NOW()::text),
    PRIMARY KEY (user_id, buddy_id)
);
CREATE TABLE IF NOT EXISTS cycle_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0,
    last_period_start TEXT,
    avg_cycle_len REAL NOT NULL DEFAULT 28,
    avg_period_len REAL NOT NULL DEFAULT 5,
    remind INTEGER NOT NULL DEFAULT 1,
    gcal_export INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (NOW()::text)
);
CREATE TABLE IF NOT EXISTS cycle_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    start_date TEXT NOT NULL,
    UNIQUE (user_id, start_date)
);
CREATE TABLE IF NOT EXISTS activity_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    steps INTEGER NOT NULL DEFAULT 0,
    active_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (NOW()::text),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS device_wellbeing_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    screen_time_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (NOW()::text),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS integrations (
    user_id INTEGER NOT NULL REFERENCES users(id),
    integration_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_connected',
    granted_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (user_id, integration_type)
);
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT UNIQUE NOT NULL,
    device_label TEXT,
    created_at TEXT NOT NULL DEFAULT (NOW()::text),
    last_used_at TEXT NOT NULL DEFAULT (NOW()::text),
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS game_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    game TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'easy',
    score REAL NOT NULL,
    is_daily INTEGER NOT NULL DEFAULT 0,
    played_on TEXT NOT NULL DEFAULT (CURRENT_DATE::text),
    created_at TEXT NOT NULL DEFAULT (NOW()::text)
);
"""

MIGRATIONS = [
    # (table, column, ALTER statement) — applied only when the column is missing,
    # so existing production data is never touched or lost. Valid verbatim on
    # both SQLite and Postgres.
    ("users", "avatar",        "ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT '🙂'"),
    ("users", "age_range",     "ALTER TABLE users ADD COLUMN age_range TEXT"),
    ("users", "step_goal",     "ALTER TABLE users ADD COLUMN step_goal INTEGER NOT NULL DEFAULT 8000"),
    ("users", "health_goals",  "ALTER TABLE users ADD COLUMN health_goals TEXT"),
    ("users", "notif_enabled", "ALTER TABLE users ADD COLUMN notif_enabled INTEGER NOT NULL DEFAULT 1"),
]


def _backend():
    """'postgres' when HB_DATABASE_URL is configured, else local 'sqlite'."""
    return "postgres" if current_app.config.get("DATABASE_URL") else "sqlite"


def get_db():
    if "db" not in g:
        if _backend() == "postgres":
            import psycopg
            from psycopg.rows import dict_row
            g.db = psycopg.connect(current_app.config["DATABASE_URL"], row_factory=dict_row)
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --- SQLite -> Postgres SQL translation (only used on the postgres backend) --
# Every call site in services/routes is written once, in SQLite dialect; this
# rewrites it on the fly so business logic never needs an if/else per query.
_RE_DATETIME_OFFSET = re.compile(r"datetime\('now',\s*'-(\d+) (\w+)'\)")
_RE_DATE_COL = re.compile(r"\bdate\(([\w.]+)\)")
# Matches "INSERT INTO users" but not "INSERT INTO user_badges" etc. — word
# boundary after "users" so only that exact table qualifies.
_RE_INSERT_INTO_USERS = re.compile(r"^INSERT\s+INTO\s+users\b", re.IGNORECASE)


def _translate(sql):
    sql = _RE_DATETIME_OFFSET.sub(r"((NOW() - INTERVAL '\1 \2')::text)", sql)
    sql = sql.replace("datetime('now')", "(NOW()::text)")
    sql = sql.replace("date('now')", "(CURRENT_DATE::text)")
    sql = _RE_DATE_COL.sub(r"(\1)::date", sql)
    sql = sql.replace("?", "%s")
    return sql


def init_db(app):
    """Create tables, then apply additive column migrations (safe on live DBs)."""
    with app.app_context():
        db = get_db()
        if _backend() == "postgres":
            for stmt in POSTGRES_SCHEMA.strip().split(";\n"):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
            db.commit()
            for table, col, stmt in MIGRATIONS:
                cur = db.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
                    (table,))
                cols = {r["column_name"] for r in cur.fetchall()}
                if col not in cols:
                    db.execute(stmt)
            db.commit()
        else:
            db.executescript(SCHEMA)
            for table, col, stmt in MIGRATIONS:
                cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    db.execute(stmt)
            db.commit()


def query(sql, args=(), one=False):
    if _backend() == "postgres":
        sql = _translate(sql)
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    backend = _backend()
    if backend == "postgres":
        sql = _translate(sql)
        stripped = sql.strip().rstrip(";")
        # Only one caller (user registration) relies on the new row's id
        # (SQLite's cursor.lastrowid) — mirror that with RETURNING id.
        if _RE_INSERT_INTO_USERS.match(stripped) and "RETURNING" not in stripped.upper():
            sql = stripped + " RETURNING id"
    cur = db.execute(sql, args)
    db.commit()
    if backend == "postgres":
        if "RETURNING" in sql.upper():
            row = cur.fetchone()
            return row["id"] if row else None
        return None
    return cur.lastrowid
