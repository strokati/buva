"""SQLite access: schema, connections, bootstrap. One connection per request, WAL mode."""
import sqlite3

from config import BOOTSTRAP_PASSWORD, BOOTSTRAP_USERNAME, DB_PATH, generated_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS task_state (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id    TEXT NOT NULL,
  answer     TEXT NOT NULL DEFAULT '',
  source     TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'Open',
  confidence TEXT NOT NULL DEFAULT 'D',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, task_id)
);
CREATE TABLE IF NOT EXISTS evidence (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id  TEXT NOT NULL,
  position INTEGER NOT NULL,
  value    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evidence_user_task ON evidence(user_id, task_id);
CREATE TABLE IF NOT EXISTS section_notes (
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  section_num INTEGER NOT NULL,
  note        TEXT NOT NULL DEFAULT '',
  key_number  TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, section_num)
);
CREATE TABLE IF NOT EXISTS custom_tasks (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  section_num INTEGER NOT NULL,
  title       TEXT NOT NULL,
  instruction TEXT NOT NULL DEFAULT '',
  example     TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_custom_user ON custom_tasks(user_id, section_num);
"""


def connect() -> sqlite3.Connection:
    # check_same_thread=False: the connection is request-scoped and used strictly
    # sequentially, but FastAPI may run sync dependencies and the endpoint on
    # different threadpool threads.
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create schema and bootstrap the first user. Prints a generated password if none was configured."""
    import os

    from auth import hash_password

    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            password = BOOTSTRAP_PASSWORD or generated_password()
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (BOOTSTRAP_USERNAME, hash_password(password)),
            )
            conn.commit()
            if not BOOTSTRAP_PASSWORD:
                print("=" * 62)
                print(f"First start: created user '{BOOTSTRAP_USERNAME}' with password:")
                print(f"    {password}")
                print("Set GBV_PASSWORD in .env to choose your own, then remove the")
                print("data directory once and restart to re-bootstrap.")
                print("=" * 62)
    finally:
        conn.close()
