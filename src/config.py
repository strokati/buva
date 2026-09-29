"""Environment-driven configuration. Everything can be overridden via env vars / .env."""
import os
import secrets

DATA_DIR = os.environ.get("GBV_DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "gbv.sqlite3")

# Bootstrap user, created only when the users table is empty.
BOOTSTRAP_USERNAME = os.environ.get("GBV_USERNAME", "admin")
BOOTSTRAP_PASSWORD = os.environ.get("GBV_PASSWORD", "")

# Set GBV_COOKIE_SECURE=true when serving over HTTPS (directly or behind a reverse proxy).
COOKIE_SECURE = os.environ.get("GBV_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
SESSION_TTL_DAYS = int(os.environ.get("GBV_SESSION_TTL_DAYS", "30"))

MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB


def generated_password() -> str:
    """Fallback password, used only when GBV_PASSWORD is not set on first start."""
    return secrets.token_urlsafe(9)
