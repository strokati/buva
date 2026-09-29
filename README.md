# Germany Business Validation Workspace

Rebuild of the single-file `Germany_Business_Validation_Workspace.html` as a small
multi-container-free web app: same workspace UI, but all data now lives in
**SQLite on the server** behind a **login**, ready to run on your own server with
**Docker Compose**.

- **Backend:** Python / FastAPI, SQLite (WAL) — no external database, one process
- **Frontend:** plain HTML/CSS/JS served by the same container — no build step
- **Auth:** session cookie (HttpOnly / SameSite=Lax), PBKDF2-hashed passwords,
  login rate limiting, same-origin checks, strict CSP
- **Data:** answers, sources, evidence, section takeaways and custom tasks per user;
  JSON export/import compatible with the old HTML version's export files

## Quick start

```bash
git clone git@github.com:strokati/buva.git
cd buva
cp .env.example .env
# edit .env: set GBV_USERNAME / GBV_PASSWORD (or leave the password empty and read it from the logs)
docker compose up -d --build
```

Open `http://<server-ip>:8080` and log in.

If `GBV_PASSWORD` was left empty, a random password is generated on first start:

```bash
docker compose logs gbv | grep -A1 "First start"
```

## Configuration (`.env`)

| Variable             | Default | Meaning                                                        |
|----------------------|---------|----------------------------------------------------------------|
| `GBV_USERNAME`       | `admin` | First user, created only when the database has no users yet    |
| `GBV_PASSWORD`       | —       | Password for that user; empty → random, printed in logs once   |
| `GBV_COOKIE_SECURE`  | `false` | Set `true` once the app is served over HTTPS                   |
| `GBV_SESSION_TTL_DAYS` | `30`  | Session lifetime in days                                       |

Notes:

- Credentials are read **only on first start** (while the users table is empty).
  Changing them in `.env` later has no effect — use "Змінити пароль" in the app menu.
  To re-bootstrap from scratch: stop the container, delete `data/gbv.sqlite3*`, start again.
- The database (including WAL files) lives in `app/data/` on the host — back up
  that folder (or copy `gbv.sqlite3` while the container is stopped).

## HTTPS behind a reverse proxy

The container listens on plain HTTP on port 8080. Put it behind your existing
reverse proxy (Caddy / Traefik / nginx) for TLS, then set `GBV_COOKIE_SECURE=true`.
Minimal Caddy example:

```
validator.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

nginx example:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Using the workspace

Everything from the original HTML file is kept:

- 22 sections / 238 tasks in 6 phases (Define → Market → Economics → Germany → Validation → Decision)
- per-task: answer, main source, extra evidence rows, status (Open/Doing/Done), confidence (A–D)
- per-section takeaway (key conclusion + key number), custom tasks, progress bar, search
- appendices: rules of work, calculation definitions, Germany starter sources

Server-side additions:

- **Export** (topbar) downloads a **PDF report** of the whole workspace: progress,
  all sections and tasks with your answers, sources, evidence and section takeaways,
  plus the calculation definitions and Germany starter sources as an appendix.
  Cyrillic-capable DejaVu fonts are bundled in `src/fonts/` (fpdf2, no system font needed).
- **Меню → Експорт JSON (бекап)** downloads a JSON of everything (same shape as the
  old file's export — you can import data exported from the old HTML workspace).
- **Import** replaces the current user's data with an uploaded JSON backup file.
- **Меню → Змінити пароль** changes the password; **Вийти** logs out.

## Local development (without Docker)

```bash
cd src
python3 -m venv .venv && . .venv/bin/activate
pip install -r ../requirements.txt
GBV_DATA_DIR=../data uvicorn main:app --reload --port 8000
```

## Project layout

```
.
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── src/
    ├── main.py        # FastAPI routes: auth, state, evidence, custom tasks, import/export, PDF
    ├── pdf.py         # PDF report generator (fpdf2 + bundled DejaVu fonts)
    ├── auth.py        # PBKDF2 hashing, sessions, rate limiting, origin checks
    ├── db.py          # SQLite schema + bootstrap
    ├── config.py      # env-driven settings
    ├── fonts/         # DejaVu Sans (regular/bold) for Cyrillic PDF output
    └── static/        # UI: pages, app.js, styles.css, content.json (questionnaire data)
```

This repository contains only the application. The original single-file HTML
muster (`Germany_Business_Validation_Workspace.html`) is not part of it.

The questionnaire content itself is static (see `src/static/content.js`,
extracted from the original HTML); user data is never stored there.
