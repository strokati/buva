"""Password hashing, server-side sessions, login rate limiting, same-origin checks."""
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from config import SESSION_TTL_DAYS

PBKDF2_ITERATIONS = 600_000  # OWASP recommendation for PBKDF2-HMAC-SHA256
SESSION_COOKIE = "gbv_session"


# --- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --- sessions ----------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, datetime('now', ?))",
        (_token_hash(token), user_id, f"+{SESSION_TTL_DAYS} days"),
    )
    # opportunistic cleanup of expired sessions
    conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
    conn.commit()
    return token


def destroy_session(conn, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()


def current_user(conn, request: Request):
    """Return the user row for a valid, unexpired session cookie, else None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return conn.execute(
        "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash = ? AND s.expires_at > datetime('now')",
        (_token_hash(token),),
    ).fetchone()


# --- abuse limits ------------------------------------------------------------

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LIMIT = 10       # attempts ...
_LOGIN_WINDOW = 300.0   # ... per 5 minutes, per (ip, username)


def login_allowed(key: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < _LOGIN_WINDOW]
    _LOGIN_ATTEMPTS[key] = recent
    return len(recent) < _LOGIN_LIMIT


def record_login_attempt(key: str, success: bool) -> None:
    if success:
        _LOGIN_ATTEMPTS.pop(key, None)
    else:
        _LOGIN_ATTEMPTS.setdefault(key, []).append(time.monotonic())


# --- CSRF --------------------------------------------------------------------

def require_same_origin(request: Request) -> None:
    """Mutating API calls must be same-origin (belt to SameSite=Lax suspenders)."""
    origin = request.headers.get("origin")
    if not origin:
        return  # non-browser client or same-origin fetch without Origin header
    host = request.headers.get("host", "")
    if urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")
