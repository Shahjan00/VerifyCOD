"""VerifyCOD data layer — SQLAlchemy ORM.

SQLite for the demo; Postgres later by setting DATABASE_URL.
Every row is scoped by merchant_id. All SQL lives in the models below —
no hand-written SQL strings anywhere in the app.

Same function names + return shapes as before, so app.py barely changes:
functions return plain dicts (not ORM objects), so the API layer never
touches a session.
"""
import datetime
import hashlib
import hmac
import os
import secrets
import struct
import time
import wave
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{BASE_DIR / 'verifycod.db'}"
)

# SQLite needs check_same_thread=False for FastAPI's threaded use.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    brand_name: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="demo")
    status: Mapped[str] = mapped_column(String, default="active")
    credits: Mapped[float] = mapped_column(Float, default=100.0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("merchant_id", "external_order_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    external_order_id: Mapped[str] = mapped_column(String, nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String, default="INR")
    payment_mode: Mapped[str] = mapped_column(String, default="COD")
    language_hint: Mapped[str] = mapped_column(String, default="hi-en")
    # Attribute is metadata_ because `metadata` is reserved by DeclarativeBase;
    # the DB column is still named "metadata".
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ver_xxxx
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), nullable=False
    )
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)  # queued, calling, ...
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(
        String, ForeignKey("verifications.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="in_progress")
    recording_path: Mapped[str | None] = mapped_column(String, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(
        String, ForeignKey("verifications.id"), nullable=False
    )
    speaker: Mapped[str] = mapped_column(String, nullable=False)  # agent | customer
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(String, nullable=True)


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(
        String, ForeignKey("verifications.id"), nullable=False, unique=True
    )
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    corrected_address: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reschedule_for: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    language_detected: Mapped[str] = mapped_column(String, default="hi-en")
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)  # sha256, never the key
    prefix: Mapped[str] = mapped_column(String, nullable=False)  # e.g. vc_live_ab12
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_used_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | revoked


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secret_hash: Mapped[str] = mapped_column(String, nullable=False)  # sha256
    secret_prefix: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")  # active | disabled
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("webhook_endpoints.id"), nullable=False
    )
    event: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    response_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class MerchantSettings(Base):
    __tablename__ = "merchant_settings"

    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), primary_key=True
    )
    brand_name: Mapped[str] = mapped_column(String, default="StyleKart")
    support_number: Mapped[str] = mapped_column(String, default="")
    calling_hours_start: Mapped[str] = mapped_column(String, default="09:00")
    calling_hours_end: Mapped[str] = mapped_column(String, default="21:00")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    retry_gap_minutes: Mapped[int] = mapped_column(Integer, default=60)
    default_language: Mapped[str] = mapped_column(String, default="hi-en")
    allowed_languages: Mapped[list] = mapped_column(
        JSON, default=lambda: ["hi-en", "en"]
    )
    voice: Mapped[str] = mapped_column(String, default="Pranav")
    greeting: Mapped[str] = mapped_column(String, default="")
    return_policy: Mapped[str] = mapped_column(String, default="")
    delivery_time: Mapped[str] = mapped_column(String, default="2 to 3 days")
    risk_value_threshold: Mapped[int] = mapped_column(Integer, default=1000)
    risk_first_time_only: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_pincodes: Mapped[list] = mapped_column(JSON, default=list)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    do_not_call: Mapped[list] = mapped_column(JSON, default=list)


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # Owner/Admin/Ops/Developer/Viewer
    status: Mapped[str] = mapped_column(String, default="invited")  # invited | active
    invited_at: Mapped[float] = mapped_column(Float, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The raw token string (a random 64-hex secret); the API layer sends it
    # as "Authorization: Bearer <token>". No JWT, no extra dependencies.
    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


def _migrate_columns():
    """Add new columns to pre-existing demo DBs (fresh DBs get them from
    create_all). Detection uses SQLAlchemy's inspector (no SQL strings);
    the ALTER itself is DDL — SQLAlchemy has no native add-column API
    without Alembic, and this is the only raw DDL in the file. All CRUD
    stays ORM-only."""
    needed = [
        ("merchants", "credits", "FLOAT DEFAULT 100.0"),
        ("calls", "recording_path", "VARCHAR"),
        ("calls", "cost", "FLOAT DEFAULT 0.0"),
        ("transcripts", "audio_path", "VARCHAR"),
    ]
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, col, ddl in needed:
            try:
                cols = [c["name"] for c in insp.get_columns(table)]
            except Exception:
                continue
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def init_db():
    Base.metadata.create_all(engine)
    _migrate_columns()
    with SessionLocal() as session:
        # One demo merchant — the store always posts as this merchant.
        if session.get(Merchant, 1) is None:
            session.add(
                Merchant(
                    id=1, name="StyleKart", brand_name="StyleKart",
                    plan="demo", status="active", created_at=time.time(),
                    credits=100.0,
                )
            )
            session.commit()
    seed_demo_data()


def _merchant_dict(m: Merchant | None) -> dict | None:
    if not m:
        return None
    return {
        "id": m.id, "name": m.name, "brand_name": m.brand_name,
        "plan": m.plan, "status": m.status, "credits": m.credits,
        "created_at": m.created_at,
    }


def _order_dict(o: Order | None) -> dict | None:
    if not o:
        return None
    return {
        "id": o.id, "merchant_id": o.merchant_id,
        "external_order_id": o.external_order_id,
        "customer_name": o.customer_name, "phone": o.phone,
        "address": o.address, "items": o.items, "amount": o.amount,
        "currency": o.currency, "payment_mode": o.payment_mode,
        "language_hint": o.language_hint, "metadata": o.metadata_,
        "created_at": o.created_at,
    }


def _verification_dict(v: Verification | None) -> dict | None:
    if not v:
        return None
    return {
        "id": v.id, "order_id": v.order_id, "merchant_id": v.merchant_id,
        "status": v.status, "outcome": v.outcome, "attempts": v.attempts,
        "created_at": v.created_at, "completed_at": v.completed_at,
    }


def _outcome_dict(o: Outcome | None) -> dict | None:
    if not o:
        return None
    return {
        "id": o.id, "verification_id": o.verification_id,
        "outcome": o.outcome, "confidence": o.confidence,
        "corrected_address": o.corrected_address,
        "reschedule_for": o.reschedule_for,
        "cancel_reason": o.cancel_reason,
        "language_detected": o.language_detected,
        "raw_json": o.raw_json,
        "raw": o.raw_json,
    }


# --- orders ---------------------------------------------------------------
def create_order(merchant_id: int, payload: dict) -> dict:
    """Insert the order (idempotent on external_order_id) and return it."""
    with SessionLocal() as session:
        existing = session.query(Order).filter_by(
            merchant_id=merchant_id,
            external_order_id=payload["external_order_id"],
        ).first()
        if existing:
            return _order_dict(existing)
        order = Order(
            merchant_id=merchant_id,
            external_order_id=payload["external_order_id"],
            customer_name=payload["customer"]["name"],
            phone=payload["customer"]["phone"],
            address=payload.get("address", {}),
            items=payload.get("items", []),
            amount=payload.get("amount", 0),
            currency=payload.get("currency", "INR"),
            payment_mode=payload.get("payment_mode", "COD"),
            language_hint=payload.get("customer", {}).get("language_hint", "hi-en"),
            metadata_=payload.get("options", {}).get("metadata", {}),
            created_at=time.time(),
        )
        session.add(order)
        session.commit()
        return _order_dict(order)


def get_order(order_id: int) -> dict | None:
    with SessionLocal() as session:
        return _order_dict(session.get(Order, order_id))


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
        "address": row["address"],
        "items": row["items"],
        "amount": row["amount"],
        "currency": row["currency"],
        "payment_mode": row["payment_mode"],
    }


def get_merchant(merchant_id: int) -> dict | None:
    with SessionLocal() as session:
        return _merchant_dict(session.get(Merchant, merchant_id))


# --- verifications --------------------------------------------------------
def create_verification(merchant_id: int, order_id: int) -> dict:
    vid = "ver_" + secrets.token_hex(4)
    with SessionLocal() as session:
        ver = Verification(
            id=vid, order_id=order_id, merchant_id=merchant_id,
            status="queued", attempts=0, created_at=time.time(),
        )
        session.add(ver)
        session.commit()
        return _verification_dict(ver)


def get_verification(verification_id: str) -> dict | None:
    with SessionLocal() as session:
        return _verification_dict(session.get(Verification, verification_id))


def get_verification_for_order(merchant_id: int, external_order_id: str) -> dict | None:
    """The latest verification for an order (idempotency: same order, same ver)."""
    with SessionLocal() as session:
        ver = (
            session.query(Verification)
            .join(Order, Order.id == Verification.order_id)
            .filter(
                Verification.merchant_id == merchant_id,
                Order.external_order_id == external_order_id,
            )
            .order_by(Verification.created_at.desc())
            .first()
        )
        return _verification_dict(ver)


def list_verifications(merchant_id: int, status: str | None = None,
                       limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        q = session.query(Verification).filter_by(merchant_id=merchant_id)
        if status:
            q = q.filter_by(status=status)
        rows = q.order_by(Verification.created_at.desc()).limit(limit).all()
        return [_verification_dict(r) for r in rows]


def set_verification_status(verification_id: str, status: str,
                            outcome: str | None = None):
    with SessionLocal() as session:
        ver = session.get(Verification, verification_id)
        if not ver:
            return
        ver.status = status
        if outcome is not None:
            ver.outcome = outcome
            ver.completed_at = time.time()
        session.commit()


def bump_attempts(verification_id: str):
    with SessionLocal() as session:
        ver = session.get(Verification, verification_id)
        if ver:
            ver.attempts += 1
            session.commit()


# --- calls / transcripts / outcomes ---------------------------------------
def start_call(verification_id: str) -> int:
    with SessionLocal() as session:
        call = Call(
            verification_id=verification_id, attempt_no=1,
            started_at=time.time(), status="in_progress",
        )
        session.add(call)
        session.commit()
        return call.id


def get_latest_call_id(verification_id: str) -> int | None:
    """Newest call row for a verification (replaces the raw SQL in app.py)."""
    with SessionLocal() as session:
        call = (
            session.query(Call)
            .filter_by(verification_id=verification_id)
            .order_by(Call.id.desc())
            .first()
        )
        return call.id if call else None


def end_call(call_id: int):
    with SessionLocal() as session:
        call = session.get(Call, call_id)
        if not call:
            return
        now = time.time()
        call.ended_at = now
        call.duration_s = now - call.started_at
        call.status = "completed"
        session.commit()


def add_turn(verification_id: str, speaker: str, text: str,
             audio_path: str | None = None):
    with SessionLocal() as session:
        session.add(
            Transcript(
                verification_id=verification_id, speaker=speaker,
                text=text, created_at=time.time(), audio_path=audio_path,
            )
        )
        session.commit()


def get_transcript(verification_id: str) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(Transcript)
            .filter_by(verification_id=verification_id)
            .order_by(Transcript.id)
            .all()
        )
        return [{"speaker": r.speaker, "text": r.text} for r in rows]


def save_outcome(verification_id: str, outcome: dict):
    with SessionLocal() as session:
        existing = session.query(Outcome).filter_by(
            verification_id=verification_id
        ).first()
        if existing:
            session.delete(existing)
            # Flush the delete first: without this, the INSERT below can
            # hit the UNIQUE constraint on verification_id (override path).
            session.flush()
        session.add(
            Outcome(
                verification_id=verification_id,
                outcome=outcome["outcome"],
                confidence=outcome["confidence"],
                corrected_address=outcome.get("corrected_address"),
                reschedule_for=outcome.get("reschedule_for"),
                cancel_reason=outcome.get("cancel_reason"),
                language_detected=outcome.get("language_detected", "hi-en"),
                raw_json=outcome,
            )
        )
        session.commit()


def get_outcome(verification_id: str) -> dict | None:
    with SessionLocal() as session:
        row = session.query(Outcome).filter_by(
            verification_id=verification_id
        ).first()
        return _outcome_dict(row)


# --- API keys ---------------------------------------------------------------
def _api_key_dict(k: ApiKey | None) -> dict | None:
    if not k:
        return None
    return {
        "id": k.id, "merchant_id": k.merchant_id, "label": k.label,
        "prefix": k.prefix, "created_at": k.created_at,
        "last_used_at": k.last_used_at, "status": k.status,
    }


def create_api_key(merchant_id: int, label: str) -> tuple[dict, str]:
    """Create a key. Returns (key dict, plain key) — the plain key is shown
    once and never stored; only its sha256 hash is kept."""
    plain = "vc_live_" + secrets.token_hex(16)  # 32 hex chars
    key_hash = hashlib.sha256(plain.encode()).hexdigest()
    with SessionLocal() as session:
        row = ApiKey(
            merchant_id=merchant_id, label=label, key_hash=key_hash,
            prefix=plain[:12], created_at=time.time(), status="active",
        )
        session.add(row)
        session.commit()
        return _api_key_dict(row), plain


def list_api_keys(merchant_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(ApiKey)
            .filter_by(merchant_id=merchant_id)
            .order_by(ApiKey.created_at.desc())
            .all()
        )
        return [_api_key_dict(r) for r in rows]


def get_api_key(key_id: int) -> dict | None:
    with SessionLocal() as session:
        return _api_key_dict(session.get(ApiKey, key_id))


def revoke_api_key(key_id: int):
    with SessionLocal() as session:
        row = session.get(ApiKey, key_id)
        if row:
            row.status = "revoked"
            session.commit()


def touch_api_key(key_id: int):
    with SessionLocal() as session:
        row = session.get(ApiKey, key_id)
        if row:
            row.last_used_at = time.time()
            session.commit()


# --- webhooks ---------------------------------------------------------------
def _webhook_dict(w: WebhookEndpoint | None) -> dict | None:
    if not w:
        return None
    return {
        "id": w.id, "merchant_id": w.merchant_id, "url": w.url,
        "events": w.events, "secret_prefix": w.secret_prefix,
        "status": w.status, "created_at": w.created_at,
    }


def _delivery_dict(d: WebhookDelivery | None, webhook_url: str | None = None) -> dict | None:
    if not d:
        return None
    return {
        "id": d.id, "webhook_id": d.webhook_id, "webhook_url": webhook_url,
        "event": d.event, "payload": d.payload, "status_code": d.status_code,
        "attempts": d.attempts, "response_ms": d.response_ms,
        "created_at": d.created_at,
    }


def create_webhook(merchant_id: int, url: str, events: list) -> tuple[dict, str]:
    """Create an endpoint. Returns (endpoint dict, plain secret) — the
    secret is shown once; only its sha256 hash is stored."""
    secret = "whsec_" + secrets.token_hex(16)
    secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    with SessionLocal() as session:
        row = WebhookEndpoint(
            merchant_id=merchant_id, url=url, events=list(events or []),
            secret_hash=secret_hash, secret_prefix=secret[:10],
            status="active", created_at=time.time(),
        )
        session.add(row)
        session.commit()
        return _webhook_dict(row), secret


def get_webhook(webhook_id: int) -> dict | None:
    with SessionLocal() as session:
        return _webhook_dict(session.get(WebhookEndpoint, webhook_id))


def list_webhooks(merchant_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(WebhookEndpoint)
            .filter_by(merchant_id=merchant_id)
            .order_by(WebhookEndpoint.created_at.desc())
            .all()
        )
        return [_webhook_dict(r) for r in rows]


def delete_webhook(webhook_id: int):
    with SessionLocal() as session:
        row = session.get(WebhookEndpoint, webhook_id)
        if row:
            session.delete(row)
            session.commit()


def log_delivery(webhook_id: int, event: str, payload: dict,
                 status_code: int, attempts: int, response_ms: float) -> dict:
    with SessionLocal() as session:
        row = WebhookDelivery(
            webhook_id=webhook_id, event=event, payload=payload,
            status_code=status_code, attempts=attempts,
            response_ms=response_ms, created_at=time.time(),
        )
        session.add(row)
        session.commit()
        url = None
        wh = session.get(WebhookEndpoint, webhook_id)
        if wh:
            url = wh.url
        return _delivery_dict(row, url)


def list_deliveries(merchant_id: int, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(WebhookDelivery)
            .join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.webhook_id)
            .filter(WebhookEndpoint.merchant_id == merchant_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .all()
        )
        urls = {
            w.id: w.url
            for w in session.query(WebhookEndpoint)
            .filter_by(merchant_id=merchant_id)
            .all()
        }
        return [_delivery_dict(r, urls.get(r.webhook_id)) for r in rows]


def get_latest_delivery(webhook_id: int) -> dict | None:
    with SessionLocal() as session:
        row = (
            session.query(WebhookDelivery)
            .filter_by(webhook_id=webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .first()
        )
        if not row:
            return None
        wh = session.get(WebhookEndpoint, webhook_id)
        return _delivery_dict(row, wh.url if wh else None)


# --- settings ---------------------------------------------------------------
SETTINGS_FIELDS = {
    "brand_name", "support_number", "calling_hours_start", "calling_hours_end",
    "max_attempts", "retry_gap_minutes", "default_language",
    "allowed_languages", "voice", "greeting", "return_policy",
    "delivery_time", "risk_value_threshold", "risk_first_time_only",
    "risk_pincodes", "recording_enabled", "retention_days", "do_not_call",
}


def _settings_dict(s: MerchantSettings | None) -> dict | None:
    if not s:
        return None
    return {f: getattr(s, f) for f in ["merchant_id"] + sorted(SETTINGS_FIELDS)}


def get_settings(merchant_id: int) -> dict:
    with SessionLocal() as session:
        row = session.get(MerchantSettings, merchant_id)
        if row is None:
            # Default the settings brand to the merchant's own brand name,
            # so a signed-up store doesn't see "StyleKart" in Settings.
            merchant = session.get(Merchant, merchant_id)
            brand = merchant.brand_name if merchant else "StyleKart"
            row = MerchantSettings(merchant_id=merchant_id, brand_name=brand)
            session.add(row)
            session.commit()
        return _settings_dict(row)


def update_settings(merchant_id: int, patch: dict) -> dict:
    with SessionLocal() as session:
        row = session.get(MerchantSettings, merchant_id)
        if row is None:
            merchant = session.get(Merchant, merchant_id)
            brand = merchant.brand_name if merchant else "StyleKart"
            row = MerchantSettings(merchant_id=merchant_id, brand_name=brand)
            session.add(row)
        for k, v in (patch or {}).items():
            if k in SETTINGS_FIELDS:
                setattr(row, k, v)
        session.commit()
        return _settings_dict(row)


# --- credits ----------------------------------------------------------------
def get_credits(merchant_id: int) -> float:
    with SessionLocal() as session:
        m = session.get(Merchant, merchant_id)
        return float(m.credits or 0.0) if m else 0.0


def add_credits(merchant_id: int, amount: float) -> float:
    with SessionLocal() as session:
        m = session.get(Merchant, merchant_id)
        if not m:
            return 0.0
        m.credits = float(m.credits or 0.0) + float(amount)
        session.commit()
        return float(m.credits)


def deduct_credits(merchant_id: int, amount: float) -> float:
    with SessionLocal() as session:
        m = session.get(Merchant, merchant_id)
        if not m:
            return 0.0
        m.credits = max(0.0, float(m.credits or 0.0) - float(amount))
        session.commit()
        return float(m.credits)


# --- team -------------------------------------------------------------------
def _team_dict(t: TeamMember | None) -> dict | None:
    if not t:
        return None
    return {
        "id": t.id, "merchant_id": t.merchant_id, "email": t.email,
        "role": t.role, "status": t.status, "invited_at": t.invited_at,
    }


def list_team(merchant_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(TeamMember)
            .filter_by(merchant_id=merchant_id)
            .order_by(TeamMember.invited_at.desc())
            .all()
        )
        return [_team_dict(r) for r in rows]


def invite_member(merchant_id: int, email: str, role: str) -> dict:
    with SessionLocal() as session:
        row = TeamMember(
            merchant_id=merchant_id, email=email, role=role,
            status="invited", invited_at=time.time(),
        )
        session.add(row)
        session.commit()
        return _team_dict(row)


# --- auth: users + session tokens -------------------------------------------
# Passwords: pbkdf2-hmac-sha256, 100k iterations, fresh 16-byte salt per
# user, stored as "salt_hex$hash_hex". Tokens: random 64-hex strings,
# 48h expiry, stored server-side. No bcrypt, no JWT, no new dependencies.
SESSION_TTL_SECONDS = 48 * 3600  # 48 hours


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 100_000
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _user_dict(u: User | None, include_hash: bool = False) -> dict | None:
    if not u:
        return None
    d = {
        "id": u.id, "merchant_id": u.merchant_id, "name": u.name,
        "email": u.email, "created_at": u.created_at,
    }
    if include_hash:
        d["password_hash"] = u.password_hash
    return d


def create_user(merchant_id: int, name: str, email: str, password: str) -> dict:
    """Raises ValueError('email_taken') or ValueError('invalid')."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or "@" not in email or "." not in email or len(password or "") < 8:
        raise ValueError("invalid")
    with SessionLocal() as session:
        if session.query(User).filter_by(email=email).first():
            raise ValueError("email_taken")
        row = User(
            merchant_id=merchant_id, name=name, email=email,
            password_hash=hash_password(password), created_at=time.time(),
        )
        session.add(row)
        session.commit()
        return _user_dict(row)


def get_user_by_email(email: str) -> dict | None:
    """Includes password_hash — the API layer must never return it."""
    with SessionLocal() as session:
        row = (
            session.query(User)
            .filter_by(email=(email or "").strip().lower())
            .first()
        )
        return _user_dict(row, include_hash=True)


def create_merchant_for_signup(brand_name: str) -> dict:
    with SessionLocal() as session:
        row = Merchant(
            name=brand_name, brand_name=brand_name, plan="payg",
            status="active", credits=100.0, created_at=time.time(),
        )
        session.add(row)
        session.commit()
        return _merchant_dict(row)


def create_session(user_id: int) -> str:
    """New 64-hex token, 48h expiry. Expired tokens for this user are
    pruned first."""
    token = secrets.token_hex(32)
    now = time.time()
    with SessionLocal() as session:
        session.query(SessionToken).filter(
            SessionToken.user_id == user_id,
            SessionToken.expires_at < now,
        ).delete()
        session.add(SessionToken(
            token=token, user_id=user_id,
            created_at=now, expires_at=now + SESSION_TTL_SECONDS,
        ))
        session.commit()
    return token


def get_user_by_token(token: str) -> dict | None:
    """None when the token is missing, unknown, or expired. Never includes
    password_hash."""
    if not token:
        return None
    with SessionLocal() as session:
        row = session.query(SessionToken).filter_by(token=token).first()
        if not row or row.expires_at < time.time():
            return None
        return _user_dict(session.get(User, row.user_id))


def delete_session(token: str) -> bool:
    with SessionLocal() as session:
        row = session.query(SessionToken).filter_by(token=token).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True


# --- calls ------------------------------------------------------------------
def _mask_phone(phone: str) -> str:
    """+919876543210 -> +91 98765****0. Keeps country + first 5 + last 1."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) <= 6:
        return phone or ""
    number = digits[-10:]
    country = digits[:-10]
    masked = f"{number[:5]}{'*' * 4}{number[-1:]}"
    return f"+{country} {masked}" if country else masked


def _sentiment(outcome: str | None) -> str:
    if outcome in ("CONFIRMED", "ADDRESS_UPDATED"):
        return "positive"
    if outcome in ("CANCELLED_BY_CUSTOMER", "CANCELLED"):
        return "negative"
    return "neutral"


def list_calls(merchant_id: int, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(Call)
            .join(Verification, Verification.id == Call.verification_id)
            .filter(Verification.merchant_id == merchant_id)
            .order_by(Call.started_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for c in rows:
            ver = session.get(Verification, c.verification_id)
            order = session.get(Order, ver.order_id) if ver else None
            out.append({
                "call_id": c.id, "verification_id": c.verification_id,
                "customer_name": order.customer_name if order else "",
                "phone_masked": _mask_phone(order.phone) if order else "",
                "language": order.language_hint if order else "hi-en",
                "duration_s": c.duration_s or 0,
                "outcome": ver.outcome if ver else None,
                "sentiment": _sentiment(ver.outcome if ver else None),
                "cost": c.cost or 0.0,
                "created_at": c.started_at,
            })
        return out


def get_call(call_id: int) -> dict | None:
    with SessionLocal() as session:
        c = session.get(Call, call_id)
        if not c:
            return None
        ver = session.get(Verification, c.verification_id)
        order = session.get(Order, ver.order_id) if ver else None
        oc = (
            session.query(Outcome)
            .filter_by(verification_id=c.verification_id)
            .first()
        )
        turns = (
            session.query(Transcript)
            .filter_by(verification_id=c.verification_id)
            .order_by(Transcript.id)
            .all()
        )
        transcript = []
        for t in turns:
            audio_url = None
            if t.audio_path:
                audio_url = (
                    f"/v1/recordings/{c.verification_id}/"
                    f"{Path(t.audio_path).name}"
                )
            transcript.append({
                "speaker": t.speaker, "text": t.text,
                "created_at": t.created_at, "audio_url": audio_url,
            })
        return {
            "call": {
                "id": c.id, "verification_id": c.verification_id,
                "attempt_no": c.attempt_no, "started_at": c.started_at,
                "ended_at": c.ended_at, "duration_s": c.duration_s,
                "status": c.status, "recording_path": c.recording_path,
                "cost": c.cost or 0.0,
            },
            "verification_id": c.verification_id,
            "customer_name": order.customer_name if order else "",
            "transcript": transcript,
            "outcome": _outcome_dict(oc)["raw"] if oc else None,
        }


def set_call_recording(call_id: int, path: str | None, cost: float):
    with SessionLocal() as session:
        c = session.get(Call, call_id)
        if c:
            c.recording_path = path
            c.cost = float(cost)
            session.commit()


# --- retry / override -------------------------------------------------------
def retry_verification(verification_id: str) -> dict | None:
    with SessionLocal() as session:
        ver = session.get(Verification, verification_id)
        if not ver:
            return None
        ver.status = "queued"
        ver.outcome = None
        ver.completed_at = None
        ver.attempts = (ver.attempts or 0) + 1
        session.commit()
        return _verification_dict(ver)


def override_verification(verification_id: str, outcome: str) -> dict | None:
    with SessionLocal() as session:
        ver = session.get(Verification, verification_id)
        if not ver:
            return None
        ver.outcome = outcome
        ver.status = "completed"
        ver.completed_at = time.time()
        session.commit()
    save_outcome(verification_id, {
        "outcome": outcome, "confidence": 1.0, "corrected_address": None,
        "reschedule_for": None, "cancel_reason": None,
        "language_detected": "hi-en", "transcript": [],
    })
    with SessionLocal() as session:
        return _verification_dict(session.get(Verification, verification_id))


# --- analytics --------------------------------------------------------------
def analytics_summary(merchant_id: int) -> dict:
    now = time.time()
    day = 86400
    with SessionLocal() as session:
        orders = session.query(Order).filter_by(merchant_id=merchant_id).all()
        vers = session.query(Verification).filter_by(merchant_id=merchant_id).all()
        calls = (
            session.query(Call)
            .join(Verification, Verification.id == Call.verification_id)
            .filter(Verification.merchant_id == merchant_id)
            .all()
        )
        orders_count = len(orders)
        calls_count = len(calls)
        confirmed = sum(
            1 for v in vers if v.outcome in ("CONFIRMED", "ADDRESS_UPDATED")
        )
        cancellations = sum(
            1 for v in vers if v.outcome == "CANCELLED_BY_CUSTOMER"
        )
        addresses_fixed = sum(
            1 for v in vers if v.outcome == "ADDRESS_UPDATED"
        )
        attempted = [v for v in vers if (v.attempts or 0) > 0]
        confirmation_rate = (confirmed / len(attempted)) if attempted else 0.0
        avg_value = (
            sum(o.amount for o in orders) / orders_count
        ) if orders_count else 0
        money_saved = round(confirmed * avg_value * 0.25)
        credits_left = get_credits(merchant_id)

        # Outcomes by day, last 14 days (UTC dates).
        buckets: dict[str, dict] = {}
        for i in range(13, -1, -1):
            d = datetime.datetime.fromtimestamp(
                now - i * day, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d")
            buckets[d] = {"date": d, "confirmed": 0, "cancelled": 0,
                          "needs_review": 0, "total": 0}
        for v in vers:
            ts = v.completed_at or v.created_at
            d = datetime.datetime.fromtimestamp(
                ts, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d")
            if d not in buckets:
                continue
            buckets[d]["total"] += 1
            if v.outcome in ("CONFIRMED", "ADDRESS_UPDATED"):
                buckets[d]["confirmed"] += 1
            elif v.outcome == "CANCELLED_BY_CUSTOMER":
                buckets[d]["cancelled"] += 1
            elif v.outcome == "NEEDS_REVIEW":
                buckets[d]["needs_review"] += 1
        outcomes_by_day = [buckets[d] for d in sorted(buckets)]

        outcome_split: dict[str, int] = {}
        for v in vers:
            key = v.outcome or "PENDING"
            outcome_split[key] = outcome_split.get(key, 0) + 1

        languages: dict[str, int] = {}
        for o in orders:
            lang = o.language_hint or "hi-en"
            languages[lang] = languages.get(lang, 0) + 1

        durations = [c.duration_s for c in calls if c.duration_s]
        avg_call_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0
        # Verifications where the customer actually connected (at least one
        # call with real duration) / verifications attempted. Distinct
        # verification ids, so retries can't push this above 1.0.
        connected_ver_ids = {
            c.verification_id for c in calls if (c.duration_s or 0) > 0
        }
        connect_rate = (len(connected_ver_ids) / len(attempted)) if attempted else 0.0

        pin_stats: dict[str, dict] = {}
        ver_by_order = {v.order_id: v for v in vers}
        for o in orders:
            pin = (o.address or {}).get("pincode", "unknown")
            entry = pin_stats.setdefault(
                pin, {"pincode": pin, "orders": 0, "cancellations": 0}
            )
            entry["orders"] += 1
            v = ver_by_order.get(o.id)
            if v and v.outcome == "CANCELLED_BY_CUSTOMER":
                entry["cancellations"] += 1
        top_pincodes = sorted(
            pin_stats.values(), key=lambda e: e["orders"], reverse=True
        )[:5]

        activity = []
        for v in sorted(vers, key=lambda x: x.created_at, reverse=True)[:10]:
            order = next((o for o in orders if o.id == v.order_id), None)
            activity.append({
                "verification_id": v.id,
                "customer_name": order.customer_name if order else "",
                "outcome": v.outcome, "status": v.status,
                "created_at": v.created_at,
            })

        alerts: list[dict] = []
        if credits_left < 20:
            alerts.append({
                "type": "low_credits",
                "message": f"Credits running low — {credits_left:.2f} left. Add credits to keep calling.",
            })
        failing = (
            session.query(WebhookDelivery)
            .join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.webhook_id)
            .filter(
                WebhookEndpoint.merchant_id == merchant_id,
                WebhookDelivery.created_at >= now - day,
                WebhookDelivery.status_code >= 400,
            )
            .first()
        )
        if failing:
            alerts.append({
                "type": "webhook_failing",
                "message": f"Webhook deliveries failing (latest HTTP {failing.status_code}). Check your endpoint.",
            })

        return {
            "kpis": {
                "orders": orders_count, "calls": calls_count,
                "confirmation_rate": round(confirmation_rate, 3),
                "cancellations": cancellations,
                "addresses_fixed": addresses_fixed,
                "money_saved": money_saved, "credits_left": credits_left,
            },
            "outcomes_by_day": outcomes_by_day,
            "outcome_split": outcome_split,
            "languages": languages,
            "avg_call_seconds": avg_call_seconds,
            "connect_rate": round(connect_rate, 3),
            "top_pincodes": top_pincodes,
            "activity": activity,
            "alerts": alerts,
        }


# --- turn audio + call recordings -------------------------------------------
RECORDINGS_DIR = BASE_DIR / "recordings"


def save_turn_audio(verification_id: str, turn_index: int, speaker: str,
                    wav_bytes: bytes) -> str:
    """Write one turn's WAV. Returns the path relative to verifycod/."""
    rel = f"recordings/{verification_id}/turn_{turn_index:03d}_{speaker}.wav"
    path = BASE_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes)
    return rel


def _read_wav_mono_16k(path: Path) -> list[float]:
    """Read a WAV and return float samples resampled to 16kHz mono."""
    with wave.open(str(path), "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if sampwidth == 2:
        count = len(frames) // 2
        samples = [s / 32768.0 for s in struct.unpack(f"<{count}h", frames[:count * 2])]
    elif sampwidth == 1:
        samples = [(b - 128) / 128.0 for b in frames]
    elif sampwidth == 4:
        count = len(frames) // 4
        samples = [s / 2147483648.0 for s in struct.unpack(f"<{count}i", frames[:count * 4])]
    else:
        return []
    if n_channels > 1:
        samples = [
            sum(samples[i:i + n_channels]) / n_channels
            for i in range(0, len(samples) - n_channels + 1, n_channels)
        ]
    if framerate == 16000:
        return samples
    ratio = framerate / 16000
    out_len = int(len(samples) / ratio)
    out = []
    for i in range(out_len):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = samples[j]
        b = samples[j + 1] if j + 1 < len(samples) else a
        out.append(a + (b - a) * frac)
    return out


def build_call_recording(verification_id: str) -> str | None:
    """Concatenate all turn WAVs (resampled to 16kHz mono) into one
    recording.wav. Returns the relative path, or None if no turns exist."""
    vdir = RECORDINGS_DIR / verification_id
    if not vdir.is_dir():
        return None
    turn_files = sorted(vdir.glob("turn_*.wav"))
    if not turn_files:
        return None
    all_samples: list[float] = []
    for f in turn_files:
        all_samples.extend(_read_wav_mono_16k(f))
    if not all_samples:
        return None
    out_path = vdir / "recording.wav"
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = b"".join(
            struct.pack("<h", max(-32768, min(32767, int(s * 32767))))
            for s in all_samples
        )
        w.writeframes(frames)
    return f"recordings/{verification_id}/recording.wav"


# --- demo seed data ---------------------------------------------------------
def _seed_one(days_ago: float, external_order_id: str, name: str, phone: str,
              city: str, pincode: str, item: str, amount: int,
              outcome_name: str | None, confidence: float, duration_s: int,
              turns: list[tuple[str, str]], corrected_address: dict | None = None,
              cancel_reason: str | None = None):
    """One seeded order + verification (+ outcome/call/transcript when the
    call happened). outcome_name=None leaves it queued/calling."""
    order = create_order(1, {
        "external_order_id": external_order_id,
        "customer": {"name": name, "phone": phone, "language_hint": "hi-en"},
        "address": {"line1": "Seed address", "city": city, "pincode": pincode},
        "items": [{"name": item, "qty": 1, "price": amount}],
        "amount": amount, "currency": "INR", "payment_mode": "COD",
    })
    ver = create_verification(1, order["id"])
    if outcome_name is None:
        return ver
    for speaker, text in turns:
        add_turn(ver["id"], speaker, text)
    save_outcome(ver["id"], {
        "outcome": outcome_name, "confidence": confidence,
        "corrected_address": corrected_address,
        "reschedule_for": None, "cancel_reason": cancel_reason,
        "language_detected": "hi-en", "transcript": [],
    })
    status = "needs_review" if outcome_name == "NEEDS_REVIEW" else "completed"
    set_verification_status(ver["id"], status, outcome=outcome_name)
    # Backdate + a completed call row (no function exists for a seeded call,
    # so this is a direct ORM insert). attempts=1 so the analytics
    # confirmation/connect rates count these calls.
    created = time.time() - days_ago * 86400
    cost = round(2.0 + 0.5 * (duration_s / 60), 2)
    with SessionLocal() as session:
        o = session.get(Order, order["id"])
        if o:
            o.created_at = created
        v = session.get(Verification, ver["id"])
        if v:
            v.created_at = created
            v.completed_at = created + duration_s + 120
            v.attempts = 1
        session.add(Call(
            verification_id=ver["id"], attempt_no=1,
            started_at=created + 60, ended_at=created + 60 + duration_s,
            duration_s=float(duration_s), status="completed", cost=cost,
        ))
        session.commit()
    return ver


def seed_demo_data():
    """Seed merchant 1 (StyleKart) with ~6 demo orders so the dashboard is
    alive on first open: 2 CONFIRMED, 1 ADDRESS_UPDATED, 1
    CANCELLED_BY_CUSTOMER, 1 NEEDS_REVIEW, 1 still queued. Idempotent:
    no-op when merchant 1 already has orders."""
    with SessionLocal() as session:
        if session.query(Order).filter_by(merchant_id=1).count() > 0:
            return
    _seed_one(3, "SK-1001", "Ramesh Patel", "+919876543210",
              "Vadodara", "390001", "Phone Case", 499,
              "CONFIRMED", 0.95, 42, [
                  ("agent", "Namaste, main StyleKart se bol rahi hoon. Kya main Ramesh Patel se baat kar rahi hoon?"),
                  ("customer", "Haan, main Ramesh hoon."),
                  ("agent", "Aapka Phone Case ka order hai, ₹499, Cash on Delivery. Kya aap order confirm karna chahenge?"),
                  ("customer", "Haan, confirm kar do."),
                  ("agent", "Shukriya! Aapka order confirm ho gaya hai. 2 se 3 din mein delivery ho jayegi."),
              ])
    _seed_one(2, "SK-1002", "Meera Shah", "+919988776655",
              "Ahmedabad", "380001", "Cotton Kurta", 1299,
              "CONFIRMED", 0.93, 38, [
                  ("agent", "Namaste, main StyleKart se bol rahi hoon. Kya main Meera Shah se baat kar rahi hoon?"),
                  ("customer", "Haan, main Meera hoon."),
                  ("agent", "Aapka Cotton Kurta ka order hai, ₹1299, Cash on Delivery. Kya order confirm karna hai?"),
                  ("customer", "Haan, sahi hai, bhej do."),
                  ("agent", "Dhanyavaad! Aapka order confirm ho gaya hai."),
              ])
    _seed_one(2, "SK-1003", "Arjun Mehta", "+919123456789",
              "Surat", "395001", "Sneakers", 1999,
              "ADDRESS_UPDATED", 0.91, 55, [
                  ("agent", "Namaste, main StyleKart se bol raha hoon. Kya main Arjun Mehta se baat kar raha hoon?"),
                  ("customer", "Haan, main Arjun hoon."),
                  ("agent", "Aapka Sneakers ka order hai, ₹1999, Cash on Delivery. Kya aapka address sahi hai — Vesu, Surat?"),
                  ("customer", "Address badal gaya hai. Naya address hai B-402, Shanti Heights, Vesu, Surat, 395007."),
                  ("agent", "Samajh gaya — B-402, Shanti Heights, Vesu, Surat, 395007. Kya yahi address sahi hai?"),
                  ("customer", "Haan, wahi pe bhej do."),
                  ("agent", "Shukriya! Aapka order naye address par confirm ho gaya hai."),
              ],
              corrected_address={"line1": "B-402, Shanti Heights, Vesu",
                                 "city": "Surat", "pincode": "395007"})
    _seed_one(1, "SK-1004", "Priya Nair", "+919876512345",
              "Mumbai", "400001", "T-Shirt", 699,
              "CANCELLED_BY_CUSTOMER", 0.97, 28, [
                  ("agent", "Namaste, main StyleKart se bol rahi hoon. Kya main Priya Nair se baat kar rahi hoon?"),
                  ("customer", "Haan, main Priya hoon."),
                  ("agent", "Aapka T-Shirt ka order hai, ₹699, Cash on Delivery. Kya order confirm karna hai?"),
                  ("customer", "Nahi chahiye, cancel kar do. Maine galti se order kar diya tha."),
                  ("agent", "Theek hai, aapka order cancel kar diya gaya hai. Shukriya!"),
              ],
              cancel_reason="Customer cancelled — ordered by mistake")
    _seed_one(1, "SK-1005", "Vikram Singh", "+919999888777",
              "Delhi", "110001", "Phone Case", 499,
              "NEEDS_REVIEW", 0.62, 47, [
                  ("agent", "Namaste, main StyleKart se bol raha hoon. Kya main Vikram Singh se baat kar raha hoon?"),
                  ("customer", "Hello? Kaun bol raha hai?"),
                  ("agent", "Main StyleKart se bol raha hoon, aapke Phone Case ke order ke baare mein. Kya aap Vikram Singh hain?"),
                  ("customer", "Haan haan, theek hai... pata nahi, baad mein bataunga."),
                  ("agent", "Koi baat nahi, main aapko baad mein call kar loon?"),
                  ("customer", "Haan... theek hai."),
              ])
    # Still waiting for its call — no outcome, no call row.
    _seed_one(0.08, "SK-1006", "Sneha Iyer", "+919888777666",
              "Pune", "411001", "Cotton Kurta", 1299,
              None, 0.0, 0, [])
