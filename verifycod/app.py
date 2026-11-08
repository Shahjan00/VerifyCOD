"""VerifyCOD API — Server 1 of the Gnani demo.

FastAPI + SQLite. No telephony: the "call" is simulated in the browser —
the demo store's customer-phone widget is the buyer's phone.

Flow:
  store --POST /v1/orders--> API --queued--> (3s) calling
  phone widget polls GET /v1/verifications/{id} --sees calling--> rings
  user answers --POST /api/start--> agent speaks the greeting (Timbre TTS)
  mic (WAV) --POST /api/voice--> Prisma STT -> dialog state machine
  -> Timbre TTS reply -> outcome JSON stored in SQLite.

Run:  uvicorn app:app --reload --port 8000   (from the verifycod/ folder)
       needs GNANI_API_KEY in ../../.env (copy ../../.env.example first)
"""
import base64
import json
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gnani.stt import GnaniSTTClient
from gnani.tts import GnaniTTSClient
from pydantic import BaseModel

import db
from dialog import advance, lines_for

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE = Path(__file__).resolve().parent

# Models named in the submission: Prisma v2.5 (STT) + Timbre v2.5 (TTS).
STT_MODEL = "prisma-v2.5"
TTS_MODEL = "timbre-v2.5"
TTS_VOICE = "Pranav"  # Timbre v2.5 voice; language hi-IN below

DEMO_MERCHANT_ID = 1
# Seconds after the order before the verification "call" starts ringing.
# In production the telephony provider dials; here the phone widget just
# sees "calling" and rings. Keep it short so the demo feels live.
RING_AFTER_SECONDS = 3

db.init_db()

app = FastAPI(title="VerifyCOD API")
# The demo store (port 8001) calls this API from the browser — allow it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def _clients():
    """Build Gnani clients from the .env key. Fails loudly if key is missing."""
    key = os.getenv("GNANI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GNANI_API_KEY missing — copy .env.example to .env and add your key."
        )
    return GnaniSTTClient(api_key=key), GnaniTTSClient(api_key=key)


def _speak(tts, text: str) -> str:
    """Timbre TTS -> base64 WAV for the browser <audio> player."""
    audio_bytes = tts.synthesize(text, voice=TTS_VOICE, model=TTS_MODEL, language="hi-IN")
    return base64.b64encode(audio_bytes).decode("ascii")


def _verification_payload(ver: dict) -> dict:
    """Full verification object for the phone widget + dashboard."""
    order = db.get_order(ver["order_id"])
    outcome = db.get_outcome(ver["id"])
    return {
        "verification_id": ver["id"],
        "status": ver["status"],
        "outcome": ver["outcome"],
        "attempts": ver["attempts"],
        "order": db.order_for_api(order) if order else None,
        "transcript": db.get_transcript(ver["id"]),
        "outcome_detail": outcome["raw"] if outcome else None,
        "created_at": ver["created_at"],
        "completed_at": ver.get("completed_at"),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return FileResponse(BASE / "static" / "dashboard.html")


# ---------------------------------------------------------------------------
# Orders / verifications — the public API (v1)
# ---------------------------------------------------------------------------
class CustomerIn(BaseModel):
    name: str
    phone: str
    language_hint: str = "hi-en"


class OrderIn(BaseModel):
    external_order_id: str
    customer: CustomerIn
    address: dict = {}
    items: list = []
    amount: int = 0
    currency: str = "INR"
    payment_mode: str = "COD"
    options: dict = {}


@app.post("/v1/orders", status_code=202)
def create_order(order: OrderIn):
    """Seller posts a COD order. Returns 202 with a verification_id.
    Idempotent: same external_order_id returns the same verification."""
    existing = db.get_verification_for_order(DEMO_MERCHANT_ID, order.external_order_id)
    if existing:
        return {
            "verification_id": existing["id"],
            "status": existing["status"],
            "estimated_call_at": existing["created_at"] + RING_AFTER_SECONDS,
        }
    row = db.create_order(DEMO_MERCHANT_ID, order.model_dump())
    ver = db.create_verification(DEMO_MERCHANT_ID, row["id"])
    return {
        "verification_id": ver["id"],
        "status": ver["status"],
        "estimated_call_at": ver["created_at"] + RING_AFTER_SECONDS,
    }


@app.get("/v1/verifications/{verification_id}")
def get_verification(verification_id: str):
    """The phone widget polls this. A queued verification flips to
    'calling' RING_AFTER_SECONDS after the order — that is the ring."""
    ver = db.get_verification(verification_id)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    if ver["status"] == "queued" and time.time() - ver["created_at"] >= RING_AFTER_SECONDS:
        db.set_verification_status(verification_id, "calling")
        db.bump_attempts(verification_id)
        ver = db.get_verification(verification_id)
    return _verification_payload(ver)


@app.get("/v1/verifications")
def list_verifications(status: str | None = None, limit: int = 50):
    """Dashboard list."""
    vers = db.list_verifications(DEMO_MERCHANT_ID, status=status, limit=limit)
    return [_verification_payload(v) for v in vers]


@app.post("/v1/verifications/{verification_id}/cancel")
def cancel_verification(verification_id: str):
    ver = db.get_verification(verification_id)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    db.set_verification_status(verification_id, "cancelled")
    return {"verification_id": verification_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Voice loop — the simulated call (browser mic, no telephony)
# ---------------------------------------------------------------------------
@app.post("/api/start")
async def start_call(verification_id: str = Form(...)):
    """Agent speaks first (like a real outbound call): the greeting.
    Also opens a call row and stores the greeting turn."""
    try:
        _, tts = _clients()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ver = db.get_verification(verification_id)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    order = db.order_for_api(db.get_order(ver["order_id"]))
    greeting = lines_for(order)["GREETING"]
    db.start_call(verification_id)
    db.add_turn(verification_id, "agent", greeting)
    return {
        "agent_reply_text": greeting,
        "audio_base64": _speak(tts, greeting),
        "next_state": "IDENTITY",
        "history": [{"speaker": "agent", "text": greeting}],
        "ctx": {},
        "done": False,
        "outcome": None,
    }


@app.post("/api/voice")
async def voice(
    audio: UploadFile = File(...),
    verification_id: str = Form(...),
    state: str = Form("IDENTITY"),
    history: str = Form("[]"),
    ctx: str = Form("{}"),
):
    """One customer turn: upload a .wav clip + verification + state + history.
    Returns transcript, agent reply (+ audio), next state, outcome if done.
    Turns + outcome are stored in SQLite for the dashboard + store."""
    try:
        stt, tts = _clients()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ver = db.get_verification(verification_id)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    order = db.order_for_api(db.get_order(ver["order_id"]))
    try:
        past = json.loads(history) if history else []
        context = json.loads(ctx) if ctx else {}
    except json.JSONDecodeError:
        past, context = [], {}
    if not isinstance(past, list):
        past = []
    if not isinstance(context, dict):
        context = {}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
    try:
        # 1. Listen — Prisma v2.5, Hinglish (hi-IN handles code-mixed speech).
        result = stt.transcribe(tmp_path, language_code="hi-IN", model=STT_MODEL)
        customer_text = (result.get("transcript") or "").strip()
    finally:
        os.unlink(tmp_path)
    past.append({"speaker": "customer", "text": customer_text})
    db.add_turn(verification_id, "customer", customer_text)

    # 2. Think — the state machine decides the next state + reply.
    step = advance(state, customer_text, past, context, order)
    past.append({"speaker": "agent", "text": step["reply"]})
    db.add_turn(verification_id, "agent", step["reply"])

    # 3. Speak — Timbre v2.5, Hinglish, returns WAV bytes.
    audio_b64 = _speak(tts, step["reply"])

    # 4. If done, store the outcome and close the verification.
    if step["done"]:
        db.save_outcome(verification_id, step["outcome"])
        outcome_name = step["outcome"]["outcome"]
        status = "needs_review" if outcome_name == "NEEDS_REVIEW" else "completed"
        db.set_verification_status(verification_id, status, outcome=outcome_name)
        calls = db._connect().execute(
            "SELECT id FROM calls WHERE verification_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (verification_id,),
        ).fetchone()
        if calls:
            db.end_call(calls["id"])

    return {
        "transcript": customer_text,
        "agent_reply_text": step["reply"],
        "audio_base64": audio_b64,
        "next_state": step["next_state"],
        "history": past,
        "ctx": step["ctx"],
        "done": step["done"],
        "outcome": step["outcome"],
    }
