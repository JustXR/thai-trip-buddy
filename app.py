import functools
import json
import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import closing

import boto3
from flask import Flask, jsonify, request

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")

REGION = os.environ.get("AWS_REGION", "eu-north-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID")
MOCK = os.environ.get("MOCK_AI") == "1"  # test locally without AWS
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "trips.db"))
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
client = boto3.client("bedrock-runtime", region_name=REGION)

with open(os.path.join(BASE, "tips.json"), encoding="utf-8") as f:
    TIPS = json.load(f)
TIPS_TEXT = "\n".join(f"- [{t['category']}] {t['tip']}" for t in TIPS)
FORMAT = (
    " Format the answer in simple Markdown: a short title with #, a ## heading for each day or topic "
    "(you may start a heading with one fitting emoji), bullet lists, **bold** for place names, and "
    "prices written like '100 THB'. No tables. For very short answers, use just a few bullets or sentences."
)


# ---------- helpers ----------
hits = defaultdict(deque)


def client_ip():
    return request.headers.get("X-Real-IP", request.remote_addr)


def allowed(bucket, limit, window):
    now = time.time()
    q = hits[(bucket, client_ip())]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def clean(value, name, max_len=300):
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value[:max_len]


def limited(bucket, limit, window):
    """Rate limit + turn ValueError into a 400 response."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not allowed(bucket, limit, window):
                return jsonify(error="Too many requests. Please try again later."), 429
            try:
                return fn(*args, **kwargs)
            except ValueError as e:
                return jsonify(error=str(e)), 400
        return wrapper
    return deco


# ---------- database (SQLite) ----------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS trips(
                code TEXT PRIMARY KEY, name TEXT NOT NULL, people TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                descr TEXT NOT NULL, amount REAL NOT NULL, payer TEXT NOT NULL,
                created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_expenses_code ON expenses(code);
            """
        )
        c.commit()


init_db()


def normalize_code(code):
    return str(code or "").strip().upper()


def get_trip(code):
    code = normalize_code(code)
    with closing(db()) as c:
        row = c.execute("SELECT * FROM trips WHERE code=?", (code,)).fetchone()
        if not row:
            return None
        exps = c.execute(
            "SELECT id, descr, amount, payer FROM expenses WHERE code=? ORDER BY id", (code,)
        ).fetchall()
    return {
        "code": row["code"],
        "name": row["name"],
        "people": json.loads(row["people"]),
        "plan": row["plan"],
        "expenses": [
            {"id": e["id"], "desc": e["descr"], "amount": e["amount"], "payer": e["payer"]}
            for e in exps
        ],
    }


def not_found():
    return jsonify(error="Trip not found. Check the code."), 404


def parse_people(raw):
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        raise ValueError("Travelers must be a list of names.")
    people = []
    for p in raw:
        p = str(p).strip()[:30]
        if p and p not in people:
            people.append(p)
    if not 1 <= len(people) <= 12:
        raise ValueError("Add between 1 and 12 travelers.")
    return people


# ---------- trip endpoints ----------
@app.post("/api/trips")
@limited("create", 10, 3600)
def create_trip():
    data = request.get_json(silent=True) or {}
    name = clean(data.get("name"), "Trip name", 60)
    people = parse_people(data.get("people"))
    with closing(db()) as c:
        for _ in range(10):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            try:
                c.execute(
                    "INSERT INTO trips(code, name, people, created) VALUES(?,?,?,?)",
                    (code, name, json.dumps(people), time.time()),
                )
                c.commit()
                break
            except sqlite3.IntegrityError:
                continue
        else:
            return jsonify(error="Could not create a trip. Try again."), 500
    return jsonify(get_trip(code)), 201


@app.get("/api/trips/<code>")
@limited("read", 3000, 3600)
def read_trip(code):
    trip = get_trip(code)
    return jsonify(trip) if trip else not_found()


@app.post("/api/trips/<code>/expenses")
@limited("write", 200, 3600)
def add_expense(code):
    trip = get_trip(code)
    if not trip:
        return not_found()
    data = request.get_json(silent=True) or {}
    try:
        amount = round(float(data.get("amount")), 2)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number.")
    if not 0 < amount < 10_000_000:
        raise ValueError("Amount must be greater than 0.")
    payer = str(data.get("payer") or "")
    if payer not in trip["people"]:
        raise ValueError("Payer must be one of the travelers.")
    descr = str(data.get("desc") or "").strip()[:60] or "Expense"
    if len(trip["expenses"]) >= 500:
        raise ValueError("This trip has too many expenses.")
    with closing(db()) as c:
        c.execute(
            "INSERT INTO expenses(code, descr, amount, payer, created) VALUES(?,?,?,?,?)",
            (trip["code"], descr, amount, payer, time.time()),
        )
        c.commit()
    return jsonify(get_trip(code))


@app.delete("/api/trips/<code>/expenses/<int:expense_id>")
@limited("write", 200, 3600)
def delete_expense(code, expense_id):
    trip = get_trip(code)
    if not trip:
        return not_found()
    with closing(db()) as c:
        c.execute("DELETE FROM expenses WHERE id=? AND code=?", (expense_id, trip["code"]))
        c.commit()
    return jsonify(get_trip(code))


@app.put("/api/trips/<code>/people")
@limited("write", 200, 3600)
def update_people(code):
    trip = get_trip(code)
    if not trip:
        return not_found()
    people = parse_people((request.get_json(silent=True) or {}).get("people"))
    missing = {e["payer"] for e in trip["expenses"]} - set(people)
    if missing:
        raise ValueError("Can't remove travelers who paid expenses: " + ", ".join(sorted(missing)))
    with closing(db()) as c:
        c.execute("UPDATE trips SET people=? WHERE code=?", (json.dumps(people), trip["code"]))
        c.commit()
    return jsonify(get_trip(code))


@app.put("/api/trips/<code>/plan")
@limited("write", 200, 3600)
def save_plan(code):
    trip = get_trip(code)
    if not trip:
        return not_found()
    plan = str((request.get_json(silent=True) or {}).get("plan") or "")[:6000]
    with closing(db()) as c:
        c.execute("UPDATE trips SET plan=? WHERE code=?", (plan, trip["code"]))
        c.commit()
    return jsonify(get_trip(code))


# ---------- AI endpoints ----------
def ask_model(system, user, max_tokens=900):
    if MOCK:
        return (
            "# Sample answer (mock mode)\n"
            "This is a fake reply for local testing.\n\n"
            "## 🍜 Food\n- **Street stalls** - 40-80 THB per meal\n- **Small restaurants** - 100-200 THB\n\n"
            "## 🛕 Temples\n- **Wat Example** - 100 THB entry\n- Dress modestly, cover shoulders and knees\n\n"
            "You asked: " + user
        )
    resp = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.5},
    )
    return resp["output"]["message"]["content"][0]["text"]


def guarded(handler):
    def wrapper():
        if not MODEL_ID and not MOCK:
            return jsonify(error="BEDROCK_MODEL_ID is not set on the server."), 500
        if not allowed("ai", 20, 3600):
            return jsonify(error="Too many requests. Please try again later."), 429
        try:
            return jsonify(answer=handler(request.get_json(silent=True) or {}))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:  # log details on the server, keep the reply generic
            app.logger.exception("AI call failed: %s", e)
            return jsonify(error="The AI service is unavailable right now."), 502
    wrapper.__name__ = handler.__name__
    return wrapper


@app.post("/api/plan")
@guarded
def plan(data):
    days = clean(data.get("days"), "Days", 3)
    region = clean(data.get("region"), "Region", 60)
    budget = clean(data.get("budget"), "Budget", 40)
    interests = clean(data.get("interests"), "Interests", 200)
    system = (
        "You are a friendly Thai local helping foreign travelers plan trips in Thailand. "
        "Use the local tips below when relevant. Give a day-by-day plan with realistic "
        "prices in THB. Be concise and practical." + FORMAT + "\n\nLocal tips:\n" + TIPS_TEXT
    )
    user = f"Plan a {days}-day trip. Region: {region}. Budget: {budget}. Interests: {interests}."
    return ask_model(system, user, 1200)


@app.post("/api/ask")
@guarded
def ask(data):
    question = clean(data.get("question"), "Question", 500)
    system = (
        "You are a friendly Thai local answering travelers' questions about Thailand. "
        "Prefer the local tips below when relevant. If you are unsure, say so. "
        "Keep answers short and practical." + FORMAT + "\n\nLocal tips:\n" + TIPS_TEXT
    )
    return ask_model(system, question, 600)


@app.get("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
