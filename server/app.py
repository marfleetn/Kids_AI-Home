import json
import os
import re
import sqlite3

from contextlib import asynccontextmanager
from datetime import datetime, date
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-to-a-random-string")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
CONFIG_DIR = Path("/app/config")
DATA_DIR = Path("/app/data")
DB_PATH = DATA_DIR / "conversations.db"

serializer = URLSafeSerializer(SECRET_KEY)


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_children_config() -> dict:
    return load_json(CONFIG_DIR / "children.json")


def get_filter_config() -> dict:
    return load_json(CONFIG_DIR / "content_filter.json")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id TEXT NOT NULL,
            model TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            blocked INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            child_id TEXT NOT NULL,
            date TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            PRIMARY KEY (child_id, date)
        )
    """)
    conn.commit()
    conn.close()


def log_message(child_id: str, model: str, role: str, content: str, blocked: bool = False):
    conn = get_db()
    conn.execute(
        "INSERT INTO conversations (child_id, model, role, content, blocked) VALUES (?, ?, ?, ?, ?)",
        (child_id, model, role, content, int(blocked)),
    )
    conn.commit()
    conn.close()


def get_daily_count(child_id: str) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT message_count FROM daily_usage WHERE child_id = ? AND date = ?",
        (child_id, date.today().isoformat()),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def check_and_increment_daily(child_id: str, limit: int) -> tuple[bool, int]:
    """Atomically check daily limit and increment if under. Returns (allowed, current_count)."""
    conn = get_db()
    today = date.today().isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT message_count FROM daily_usage WHERE child_id = ? AND date = ?",
            (child_id, today),
        ).fetchone()
        count = row[0] if row else 0
        if count >= limit:
            conn.rollback()
            return False, count
        conn.execute(
            """INSERT INTO daily_usage (child_id, date, message_count)
               VALUES (?, ?, 1)
               ON CONFLICT(child_id, date)
               DO UPDATE SET message_count = message_count + 1""",
            (child_id, today),
        )
        conn.commit()
        return True, count + 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_conversation_history(child_id: str, limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT role, content FROM conversations
           WHERE child_id = ? AND blocked = 0
           ORDER BY id DESC LIMIT ?""",
        (child_id, limit),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def check_content_filter(text: str, patterns: list[str]) -> bool:
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def get_session_child(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token)
    except Exception:
        return None
    config = get_children_config()
    for child in config["children"]:
        if child["id"] == data.get("child_id"):
            return child
    return None


def get_admin_session(request: Request) -> bool:
    token = request.cookies.get("admin_session")
    if not token:
        return False
    try:
        data = serializer.loads(token)
        return data.get("admin") is True
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- Child-facing routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    child = get_session_child(request)
    if child:
        return RedirectResponse("/chat")
    config = get_children_config()
    return templates.TemplateResponse("login.html", {"request": request, "children": config["children"]})


@app.post("/login")
async def login(child_id: str = Form(...), pin: str = Form(...)):
    config = get_children_config()
    for child in config["children"]:
        if child["id"] == child_id and child["pin"] == pin:
            token = serializer.dumps({"child_id": child_id})
            response = RedirectResponse("/chat", status_code=303)
            response.set_cookie("session", token, httponly=True, max_age=3600)
            return response
    return RedirectResponse("/?error=wrong_pin", status_code=303)


@app.get("/logout")
async def logout():
    response = RedirectResponse("/")
    response.delete_cookie("session")
    return response


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    child = get_session_child(request)
    if not child:
        return RedirectResponse("/")
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "child": child,
        "daily_count": get_daily_count(child["id"]),
    })


@app.post("/api/chat")
async def chat_api(request: Request):
    child = get_session_child(request)
    if not child:
        raise HTTPException(status_code=401, detail="Not logged in")

    body = await request.json()
    message = body.get("message", "").strip()
    model = body.get("model", child["allowed_models"][0])

    if model not in child["allowed_models"]:
        raise HTTPException(status_code=403, detail="Model not allowed")

    if len(message) > child.get("max_message_length", 500):
        raise HTTPException(status_code=400, detail="Message too long")

    filter_config = get_filter_config()
    if check_content_filter(message, filter_config["blocked_input_patterns"]):
        log_message(child["id"], model, "user", message, blocked=True)
        return {"response": filter_config["blocked_response_message"], "blocked": True}

    max_daily = child.get("max_messages_per_day", 100)
    allowed, _count = check_and_increment_daily(child["id"], max_daily)
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily message limit reached. Try again tomorrow!")

    log_message(child["id"], model, "user", message)

    history = get_conversation_history(child["id"], limit=20)
    system_prompt = filter_config["system_safety_prompt"] + "\n\n" + child["personality"]

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)

    async def generate():
        full_response = ""
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = chunk.get("message", {}).get("content", "")
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

        if check_content_filter(full_response, filter_config["blocked_output_patterns"]):
            log_message(child["id"], model, "assistant", full_response, blocked=True)
            yield f"data: {json.dumps({'replace': filter_config['blocked_response_message']})}\n\n"
        else:
            log_message(child["id"], model, "assistant", full_response)

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# --- Admin routes ---


@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if get_admin_session(request):
        return RedirectResponse("/admin/dashboard")
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def admin_login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        token = serializer.dumps({"admin": True})
        response = RedirectResponse("/admin/dashboard", status_code=303)
        response.set_cookie("admin_session", token, httponly=True, max_age=7200)
        return response
    return RedirectResponse("/admin?error=wrong_password", status_code=303)


@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin")
    response.delete_cookie("admin_session")
    return response


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not get_admin_session(request):
        return RedirectResponse("/admin")

    config = get_children_config()
    children_stats = []
    conn = get_db()
    for child in config["children"]:
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE child_id = ?", (child["id"],)
        ).fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE child_id = ? AND blocked = 1", (child["id"],)
        ).fetchone()[0]
        today_count = get_daily_count(child["id"])
        children_stats.append({
            **child,
            "total_messages": total,
            "blocked_messages": blocked,
            "today_messages": today_count,
        })
    conn.close()

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "children": children_stats,
    })


@app.get("/admin/logs/{child_id}", response_class=HTMLResponse)
async def admin_logs(request: Request, child_id: str, page: int = 1):
    if not get_admin_session(request):
        return RedirectResponse("/admin")

    per_page = 50
    offset = (page - 1) * per_page
    conn = get_db()
    logs = conn.execute(
        """SELECT role, content, model, blocked, timestamp
           FROM conversations WHERE child_id = ?
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (child_id, per_page, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE child_id = ?", (child_id,)
    ).fetchone()[0]
    conn.close()

    config = get_children_config()
    child_name = child_id
    for c in config["children"]:
        if c["id"] == child_id:
            child_name = c["name"]
            break

    return templates.TemplateResponse("admin_logs.html", {
        "request": request,
        "logs": logs,
        "child_id": child_id,
        "child_name": child_name,
        "page": page,
        "total": total,
        "per_page": per_page,
    })


@app.get("/api/models")
async def list_models(request: Request):
    child = get_session_child(request)
    if not child:
        raise HTTPException(status_code=401)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{OLLAMA_URL}/api/tags")
        available = [m["name"] for m in resp.json().get("models", [])]
    return {"models": [m for m in child["allowed_models"] if m in available]}
