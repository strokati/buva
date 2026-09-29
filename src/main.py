"""Business Validation Workspace — FastAPI backend + static frontend.

Single-container app: serves the UI, session-cookie auth, all user data in SQLite.
"""
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import auth
import db
import pdf
from auth import SESSION_COOKIE
from config import COOKIE_SECURE, MAX_IMPORT_BYTES, SESSION_TTL_DAYS  # noqa: F401

STATIC_DIR = Path(__file__).resolve().parent / "static"
VALID_STATUSES = ("Open", "In progress", "Done")
VALID_CONFIDENCE = ("A", "B", "C", "D")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Business Validation Workspace", lifespan=lifespan, docs_url=None, redoc_url=None)


# --- helpers -----------------------------------------------------------------

def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_user(request: Request, conn=Depends(get_conn)):
    user = auth.current_user(conn, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, media_type="text/html")


def require_same_origin(request: Request) -> None:
    auth.require_same_origin(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;"
        " connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
    )
    return response


# --- auth pages --------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, conn=Depends(get_conn)):
    if auth.current_user(conn, request) is None:
        return RedirectResponse("/login", status_code=303)
    return page("index.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, conn=Depends(get_conn)):
    if auth.current_user(conn, request) is not None:
        return RedirectResponse("/", status_code=303)
    return page("login.html")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), conn=Depends(get_conn)):
    key = f"{request.client.host if request.client else '?'}:{username.strip().lower()}"
    if not auth.login_allowed(key):
        return RedirectResponse("/login?error=rate", status_code=303)
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username.strip(),)
    ).fetchone()
    if row is None or not auth.verify_password(password, row["password_hash"]):
        auth.record_login_attempt(key, success=False)
        return RedirectResponse("/login?error=1", status_code=303)
    auth.record_login_attempt(key, success=True)
    token = auth.create_session(conn, row["id"])
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return response


@app.post("/logout")
def logout(request: Request, conn=Depends(get_conn)):
    auth.destroy_session(conn, request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# --- state -------------------------------------------------------------------

def _state_payload(conn, user_id: int) -> dict:
    tasks: dict = {}
    for row in conn.execute("SELECT * FROM task_state WHERE user_id = ?", (user_id,)):
        tasks[row["task_id"]] = {
            "answer": row["answer"],
            "source": row["source"],
            "status": row["status"],
            "confidence": row["confidence"],
            "evidence": [],
        }
    for row in conn.execute(
        "SELECT id, task_id, value FROM evidence WHERE user_id = ? ORDER BY task_id, position, id",
        (user_id,),
    ):
        if row["task_id"] in tasks:
            tasks[row["task_id"]]["evidence"].append({"id": row["id"], "value": row["value"]})
    sections = {
        str(row["section_num"]): {"note": row["note"], "key_number": row["key_number"]}
        for row in conn.execute("SELECT * FROM section_notes WHERE user_id = ?", (user_id,))
    }
    custom = [
        {
            "id": row["id"],
            "key": f"CUSTOM-{row['id']}",
            "section": row["section_num"],
            "title": row["title"],
            "instruction": row["instruction"],
            "example": row["example"],
        }
        for row in conn.execute(
            "SELECT * FROM custom_tasks WHERE user_id = ? ORDER BY id", (user_id,)
        )
    ]
    return {"tasks": tasks, "sections": sections, "customTasks": custom}


@app.get("/api/state")
def api_state(user=Depends(get_user), conn=Depends(get_conn)):
    return {**_state_payload(conn, user["id"]), "username": user["username"]}


# --- task answers ------------------------------------------------------------

class TaskPatch(BaseModel):
    answer: str | None = None
    source: str | None = None
    status: str | None = None
    confidence: str | None = None


@app.patch("/api/tasks/{task_id}")
def api_patch_task(task_id: str, body: TaskPatch, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    if not TASK_ID_RE.match(task_id):
        raise HTTPException(status_code=422, detail="Invalid task id")
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    if body.confidence is not None and body.confidence not in VALID_CONFIDENCE:
        raise HTTPException(status_code=422, detail="Invalid confidence")
    row = conn.execute(
        "SELECT * FROM task_state WHERE user_id = ? AND task_id = ?", (user["id"], task_id)
    ).fetchone()
    current = row or {
        "answer": "", "source": "", "status": "Open", "confidence": "D",
    }
    answer = body.answer if body.answer is not None else current["answer"]
    source = body.source if body.source is not None else current["source"]
    status = body.status if body.status is not None else current["status"]
    confidence = body.confidence if body.confidence is not None else current["confidence"]
    conn.execute(
        """INSERT INTO task_state (user_id, task_id, answer, source, status, confidence)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, task_id) DO UPDATE SET
             answer = excluded.answer, source = excluded.source, status = excluded.status,
             confidence = excluded.confidence, updated_at = datetime('now')""",
        (user["id"], task_id, answer, source, status, confidence),
    )
    conn.commit()
    return {"ok": True}


# --- evidence ----------------------------------------------------------------

class EvidenceCreate(BaseModel):
    value: str = ""


class EvidencePatch(BaseModel):
    value: str


@app.post("/api/tasks/{task_id}/evidence", status_code=201)
def api_add_evidence(task_id: str, body: EvidenceCreate, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    if not TASK_ID_RE.match(task_id):
        raise HTTPException(status_code=422, detail="Invalid task id")
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM evidence WHERE user_id = ? AND task_id = ?",
        (user["id"], task_id),
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO evidence (user_id, task_id, position, value) VALUES (?, ?, ?, ?)",
        (user["id"], task_id, pos, body.value),
    )
    conn.commit()
    return {"id": cur.lastrowid, "value": body.value}


def _owned_evidence(conn, user_id: int, evidence_id: int):
    row = conn.execute(
        "SELECT id, task_id FROM evidence WHERE id = ? AND user_id = ?", (evidence_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return row


@app.patch("/api/evidence/{evidence_id}")
def api_patch_evidence(evidence_id: int, body: EvidencePatch, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    _owned_evidence(conn, user["id"], evidence_id)
    conn.execute("UPDATE evidence SET value = ? WHERE id = ?", (body.value, evidence_id))
    conn.commit()
    return {"ok": True}


@app.delete("/api/evidence/{evidence_id}")
def api_delete_evidence(evidence_id: int, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    _owned_evidence(conn, user["id"], evidence_id)
    conn.execute("DELETE FROM evidence WHERE id = ?", (evidence_id,))
    conn.commit()
    return {"ok": True}


# --- section takeaways ---------------------------------------------------------

class SectionPatch(BaseModel):
    note: str | None = None
    key_number: str | None = None


@app.patch("/api/sections/{section_num}")
def api_patch_section(section_num: int, body: SectionPatch, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    row = conn.execute(
        "SELECT * FROM section_notes WHERE user_id = ? AND section_num = ?",
        (user["id"], section_num),
    ).fetchone()
    note = body.note if body.note is not None else (row["note"] if row else "")
    key_number = body.key_number if body.key_number is not None else (row["key_number"] if row else "")
    conn.execute(
        """INSERT INTO section_notes (user_id, section_num, note, key_number) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, section_num) DO UPDATE SET
             note = excluded.note, key_number = excluded.key_number""",
        (user["id"], section_num, note, key_number),
    )
    conn.commit()
    return {"ok": True}


# --- custom tasks --------------------------------------------------------------

class CustomTaskCreate(BaseModel):
    section: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=300)
    instruction: str = Field(default="", max_length=2000)
    example: str = Field(default="", max_length=4000)


@app.post("/api/custom-tasks", status_code=201)
def api_create_custom_task(body: CustomTaskCreate, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    cur = conn.execute(
        "INSERT INTO custom_tasks (user_id, section_num, title, instruction, example) VALUES (?, ?, ?, ?, ?)",
        (user["id"], body.section, body.title.strip(), body.instruction.strip(), body.example.strip()),
    )
    conn.commit()
    task_id = f"CUSTOM-{cur.lastrowid}"
    conn.execute(
        "INSERT OR IGNORE INTO task_state (user_id, task_id) VALUES (?, ?)", (user["id"], task_id)
    )
    conn.commit()
    return {"id": cur.lastrowid, "key": task_id}


@app.delete("/api/custom-tasks/{task_num}")
def api_delete_custom_task(task_num: int, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    row = conn.execute(
        "SELECT id FROM custom_tasks WHERE id = ? AND user_id = ?", (task_num, user["id"])
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom task not found")
    key = f"CUSTOM-{task_num}"
    conn.execute("DELETE FROM evidence WHERE user_id = ? AND task_id = ?", (user["id"], key))
    conn.execute("DELETE FROM task_state WHERE user_id = ? AND task_id = ?", (user["id"], key))
    conn.execute("DELETE FROM custom_tasks WHERE id = ?", (task_num,))
    conn.commit()
    return {"ok": True}


# --- export / import / reset ---------------------------------------------------

@app.get("/api/export")
def api_export(user=Depends(get_user), conn=Depends(get_conn)):
    state = _state_payload(conn, user["id"])
    for task in state["tasks"].values():
        task["evidence"] = [e["value"] for e in task["evidence"]]
    payload = {
        "app": "gbv",
        "version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **state,
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="germany-business-validation-data.json"'},
    )


@app.get("/api/export/pdf")
def api_export_pdf(user=Depends(get_user), conn=Depends(get_conn)):
    state = _state_payload(conn, user["id"])
    data = pdf.build_pdf(state, user["username"])
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="germany-business-validation-report.pdf"'},
    )


def _normalize_import(data: dict) -> tuple[dict, dict, list]:
    """Accept both the current export format and the legacy single-file HTML format."""
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
        raise HTTPException(status_code=422, detail="Unexpected file format: 'tasks' missing")

    tasks: dict[str, dict] = {}
    for task_id, raw in data["tasks"].items():
        if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id) or not isinstance(raw, dict):
            continue
        evidence = raw.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        values = [e if isinstance(e, str) else str(e.get("value") or "") for e in evidence if e]
        status = str(raw.get("status") or "Open")
        confidence = str(raw.get("confidence") or "D").upper()
        tasks[task_id] = {
            "answer": str(raw.get("answer") or ""),
            "source": str(raw.get("source") or ""),
            "status": status if status in VALID_STATUSES else "Open",
            "confidence": confidence if confidence in VALID_CONFIDENCE else "D",
            "evidence": values,
        }

    sections: dict[int, dict] = {}
    raw_sections = data.get("sections") or {}
    if isinstance(raw_sections, dict):
        for num, raw in raw_sections.items():
            if not isinstance(raw, dict):
                continue
            try:
                sections[int(num)] = {
                    "note": str(raw.get("note") or ""),
                    "key_number": str(raw.get("key_number") or raw.get("number") or ""),
                }
            except (TypeError, ValueError):
                continue

    custom: list[dict] = []
    raw_custom = data.get("customTasks") or []
    if isinstance(raw_custom, list):
        for raw in raw_custom:
            if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
                continue
            try:
                section = int(raw.get("section"))
            except (TypeError, ValueError):
                continue
            custom.append({
                "section": section,
                "title": str(raw["title"]).strip()[:300],
                "instruction": str(raw.get("instruction") or "")[:2000],
                "example": str(raw.get("example") or "")[:4000],
            })
    return tasks, sections, custom


@app.post("/api/import")
def api_import(request: Request, file: UploadFile = File(...), user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    raw = file.file.read()  # sync endpoint: the request-scoped connection must stay in this thread
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Not a valid JSON file")
    tasks, sections, custom = _normalize_import(data)

    try:
        conn.execute("BEGIN")
        for table in ("task_state", "evidence", "section_notes", "custom_tasks"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user["id"],))
        for task_id, t in tasks.items():
            conn.execute(
                "INSERT INTO task_state (user_id, task_id, answer, source, status, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], task_id, t["answer"], t["source"], t["status"], t["confidence"]),
            )
            for pos, value in enumerate(t["evidence"], start=1):
                conn.execute(
                    "INSERT INTO evidence (user_id, task_id, position, value) VALUES (?, ?, ?, ?)",
                    (user["id"], task_id, pos, value),
                )
        for num, s in sections.items():
            conn.execute(
                "INSERT INTO section_notes (user_id, section_num, note, key_number) VALUES (?, ?, ?, ?)",
                (user["id"], num, s["note"], s["key_number"]),
            )
        for c in custom:
            conn.execute(
                "INSERT INTO custom_tasks (user_id, section_num, title, instruction, example) VALUES (?, ?, ?, ?, ?)",
                (user["id"], c["section"], c["title"], c["instruction"], c["example"]),
            )
        # legacy imports re-number custom tasks; drop their orphaned CUSTOM-* states
        conn.execute(
            "DELETE FROM task_state WHERE user_id = ? AND task_id LIKE 'CUSTOM-%'"
            " AND task_id NOT IN (SELECT 'CUSTOM-' || id FROM custom_tasks WHERE user_id = ?)",
            (user["id"], user["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _state_payload(conn, user["id"])


@app.post("/api/reset")
def api_reset(request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    for table in ("task_state", "evidence", "section_notes", "custom_tasks"):
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user["id"],))
    conn.commit()
    return {"ok": True}


# --- password -------------------------------------------------------------------

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


@app.post("/api/password")
def api_password(body: PasswordChange, request: Request, user=Depends(get_user), conn=Depends(get_conn)):
    require_same_origin(request)
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not auth.verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Поточний пароль невірний")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (auth.hash_password(body.new_password), user["id"]),
    )
    # keep the current session, drop all others
    token = request.cookies.get(SESSION_COOKIE, "")
    conn.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
        (user["id"], auth._token_hash(token)),
    )
    conn.commit()
    return {"ok": True}


# --- static ---------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
