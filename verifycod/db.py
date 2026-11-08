"""VerifyCOD data layer — SQLAlchemy ORM.

SQLite for the demo; Postgres later by setting DATABASE_URL.
Every row is scoped by merchant_id. All SQL lives in the models below —
no hand-written SQL strings anywhere in the app.

Same function names + return shapes as before, so app.py barely changes:
functions return plain dicts (not ORM objects), so the API layer never
touches a session.
"""
import os
import secrets
import time
from pathlib import Path

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
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


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(
        String, ForeignKey("verifications.id"), nullable=False
    )
    speaker: Mapped[str] = mapped_column(String, nullable=False)  # agent | customer
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


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


def init_db():
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        # One demo merchant — the store always posts as this merchant.
        if session.get(Merchant, 1) is None:
            session.add(
                Merchant(
                    id=1, name="StyleKart", brand_name="StyleKart",
                    plan="demo", status="active", created_at=time.time(),
                )
            )
            session.commit()


def _merchant_dict(m: Merchant | None) -> dict | None:
    if not m:
        return None
    return {
        "id": m.id, "name": m.name, "brand_name": m.brand_name,
        "plan": m.plan, "status": m.status, "created_at": m.created_at,
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


def add_turn(verification_id: str, speaker: str, text: str):
    with SessionLocal() as session:
        session.add(
            Transcript(
                verification_id=verification_id, speaker=speaker,
                text=text, created_at=time.time(),
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
