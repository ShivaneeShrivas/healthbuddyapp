"""SQLite data layer.

Deliberately thin: raw SQL behind small helpers so the storage engine can be
swapped for Postgres (psycopg + the same queries) without touching services.
"""
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
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_subs_user ON push_subscriptions(user_id);
CREATE TABLE IF NOT EXISTS push_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    template_id TEXT NOT NULL,
    slot TEXT,
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_push_history_user ON push_history(user_id, sent_at);
CREATE TABLE IF NOT EXISTS push_snoozes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    template_id TEXT NOT NULL,
    remind_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_snoozes_user ON push_snoozes(user_id, remind_at);
CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT UNIQUE NOT NULL,   -- sha256 of the raw token; raw token never stored
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id);
CREATE TABLE IF NOT EXISTS email_otps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    code_hash TEXT NOT NULL,   -- sha256 of the 6-digit code; raw code never stored
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_otps_user ON email_otps(user_id, created_at);
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


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


MIGRATIONS = [
    # (table, column, ALTER statement) — applied only when the column is missing,
    # so existing production data is never touched or lost.
    ("users", "avatar",        "ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT '🙂'"),
    ("users", "age_range",     "ALTER TABLE users ADD COLUMN age_range TEXT"),
    ("users", "step_goal",     "ALTER TABLE users ADD COLUMN step_goal INTEGER NOT NULL DEFAULT 8000"),
    ("users", "health_goals",  "ALTER TABLE users ADD COLUMN health_goals TEXT"),
    ("users", "notif_enabled", "ALTER TABLE users ADD COLUMN notif_enabled INTEGER NOT NULL DEFAULT 1"),
    # DEFAULT 1 here on purpose: existing/seeded accounts stay usable as-is.
    # register() explicitly inserts 0 for brand-new signups so only THOSE
    # accounts are gated behind the OTP flow.
    ("users", "email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1"),
]


def init_db(app):
    """Create tables, then apply additive column migrations (safe on live DBs)."""
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        for table, col, stmt in MIGRATIONS:
            cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                db.execute(stmt)
        db.commit()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid
