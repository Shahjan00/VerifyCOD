"""VerifyCOD SQLite layer — one file, all SQL in one place.

SQLite for the demo; Postgres later. Keep it simple: sqlite3 stdlib, one
connection per call (the demo is single-user), JSON columns for address /
items / transcript. Every row is scoped by merchant_id. Swap this file's
SQL for Postgres later — the rest of the app only calls these functions.
"""
import json
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "verifycod.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    brand_name TEXT NOT NULL,
    plan TEXT DEFAULT 'demo',
    status TEXT DEFAULT 'active',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id INTEGER NOT NULL,
    external_order_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,          -- JSON
    items TEXT NOT NULL,            -- JSON
    amount INTEGER NOT NULL,
    currency TEXT DEFAULT 'INR',
    payment_mode TEXT DEFAULT 'COD',
    language_hint TEXT DEFAULT 'hi-en',
    metadata TEXT DEFAULT '{}',     -- JSON
    created_at REAL NOT NULL,
    UNIQUE (merchant_id, external_order_id)
);
CREATE TABLE IF NOT EXISTS verifications (
    id TEXT PRIMARY KEY,            -- ver_xxxx
    order_id INTEGER NOT NULL,
    merchant_id INTEGER NOT NULL,
    status TEXT NOT NULL,           -- queued, calling, completed, cancelled, needs_review
    outcome TEXT,                   -- CONFIRMED, ADDRESS_UPDATED, ...
    attempts INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    completed_at REAL
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL,
    attempt_no INTEGER DEFAULT 1,
    started_at REAL NOT NULL,
    ended_at REAL,
    duration_s REAL,
    status TEXT DEFAULT 'in_progress'
);
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL,
    speaker TEXT NOT NULL,          -- agent | customer
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL UNIQUE,
    outcome TEXT NOT NULL,
    confidence REAL NOT NULL,
    corrected_address TEXT,         -- JSON or NULL
    reschedule_for TEXT,
    cancel_reason TEXT,
    language_detected TEXT DEFAULT 'hi-en',
    raw_json TEXT NOT NULL
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)
        # One demo merchant — the store always posts as this merchant.
        row = conn.execute("SELECT id FROM merchants WHERE id = 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO merchants (id, name, brand_name, plan, status, created_at)"
                " VALUES (1, 'StyleKart', 'StyleKart', 'demo', 'active', ?)",
                (time.time(),),
            )


def _row_to_dict(row):
    return dict(row) if row else None


# --- orders ---------------------------------------------------------------
def create_order(merchant_id: int, payload: dict) -> dict:
    """Insert the order (idempotent on external_order_id) and return it."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE merchant_id = ? AND external_order_id = ?",
            (merchant_id, payload["external_order_id"]),
        ).fetchone()
        if row:
            return _row_to_dict(row)
        cur = conn.execute(
            "INSERT INTO orders (merchant_id, external_order_id, customer_name,"
            " phone, address, items, amount, currency, payment_mode,"
            " language_hint, metadata, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                merchant_id,
                payload["external_order_id"],
                payload["customer"]["name"],
                payload["customer"]["phone"],
                json.dumps(payload.get("address", {})),
                json.dumps(payload.get("items", [])),
                payload.get("amount", 0),
                payload.get("currency", "INR"),
                payload.get("payment_mode", "COD"),
                payload.get("customer", {}).get("language_hint", "hi-en"),
                json.dumps(payload.get("options", {}).get("metadata", {})),
                time.time(),
            ),
        )
        return _row_to_dict(
            conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
        )


def get_order(order_id: int) -> dict | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        )


def order_for_api(row: dict) -> dict:
    """DB row -> the order dict the dialog manager expects."""
    merchant = get_merchant(row["merchant_id"])
    return {
        "store": merchant["brand_name"] if merchant else "the store",
        "external_order_id": row["external_order_id"],
        "customer": {
            "name": row["customer_name"],
            "phone": row["phone"],
            "language_hint": row["language_hint"],
        },
        "address": json.loads(row["address"]),
        "items": json.loads(row["items"]),
        "amount": row["amount"],
        "currency": row["currency"],
        "payment_mode": row["payment_mode"],
    }


def get_merchant(merchant_id: int) -> dict | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,)).fetchone()
        )


# --- verifications --------------------------------------------------------
def create_verification(merchant_id: int, order_id: int) -> dict:
    vid = "ver_" + secrets.token_hex(4)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO verifications (id, order_id, merchant_id, status,"
            " attempts, created_at) VALUES (?, ?, ?, 'queued', 0, ?)",
            (vid, order_id, merchant_id, time.time()),
        )
        return _row_to_dict(
            conn.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone()
        )


def get_verification(verification_id: str) -> dict | None:
    with _connect() as conn:
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM verifications WHERE id = ?", (verification_id,)
            ).fetchone()
        )


def get_verification_for_order(merchant_id: int, external_order_id: str) -> dict | None:
    """The latest verification for an order (idempotency: same order, same ver)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT v.* FROM verifications v JOIN orders o ON o.id = v.order_id"
            " WHERE v.merchant_id = ? AND o.external_order_id = ?"
            " ORDER BY v.created_at DESC LIMIT 1",
            (merchant_id, external_order_id),
        ).fetchone()
        return _row_to_dict(row)


def list_verifications(merchant_id: int, status: str | None = None,
                       limit: int = 50) -> list[dict]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM verifications WHERE merchant_id = ? AND status = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (merchant_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM verifications WHERE merchant_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (merchant_id, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def set_verification_status(verification_id: str, status: str,
                            outcome: str | None = None):
    with _connect() as conn:
        if outcome is not None:
            conn.execute(
                "UPDATE verifications SET status = ?, outcome = ?,"
                " completed_at = ? WHERE id = ?",
                (status, outcome, time.time(), verification_id),
            )
        else:
            conn.execute(
                "UPDATE verifications SET status = ? WHERE id = ?",
                (status, verification_id),
            )


def bump_attempts(verification_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE verifications SET attempts = attempts + 1 WHERE id = ?",
            (verification_id,),
        )


# --- calls / transcripts / outcomes ---------------------------------------
def start_call(verification_id: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO calls (verification_id, attempt_no, started_at, status)"
            " VALUES (?, 1, ?, 'in_progress')",
            (verification_id, time.time()),
        )
        return cur.lastrowid


def end_call(call_id: int):
    with _connect() as conn:
        row = conn.execute(
            "SELECT started_at FROM calls WHERE id = ?", (call_id,)
        ).fetchone()
        started = row["started_at"] if row else time.time()
        conn.execute(
            "UPDATE calls SET ended_at = ?, duration_s = ?, status = 'completed'"
            " WHERE id = ?",
            (time.time(), time.time() - started, call_id),
        )


def add_turn(verification_id: str, speaker: str, text: str):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO transcripts (verification_id, speaker, text, created_at)"
            " VALUES (?, ?, ?, ?)",
            (verification_id, speaker, text, time.time()),
        )


def get_transcript(verification_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT speaker, text FROM transcripts WHERE verification_id = ?"
            " ORDER BY id",
            (verification_id,),
        ).fetchall()
        return [{"speaker": r["speaker"], "text": r["text"]} for r in rows]


def save_outcome(verification_id: str, outcome: dict):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO outcomes (verification_id, outcome, confidence,"
            " corrected_address, reschedule_for, cancel_reason,"
            " language_detected, raw_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                verification_id,
                outcome["outcome"],
                outcome["confidence"],
                json.dumps(outcome.get("corrected_address"))
                if outcome.get("corrected_address") else None,
                outcome.get("reschedule_for"),
                outcome.get("cancel_reason"),
                outcome.get("language_detected", "hi-en"),
                json.dumps(outcome),
            ),
        )


def get_outcome(verification_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM outcomes WHERE verification_id = ?",
            (verification_id,),
        ).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d["raw"] = json.loads(d["raw_json"])
        return d
