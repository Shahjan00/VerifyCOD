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
import secrets
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gnani.stt import GnaniSTTClient
from gnani.tts import GnaniTTSClient
from pydantic import BaseModel

import db
from dialog import advance, lines_for

# Groq LLM intent — optional. If llm.py is missing, the keyword matcher
# in dialog.py handles intent on its own.
try:
    from llm import classify_intent
except ImportError:  # pragma: no cover
    classify_intent = None

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


def _speak_bytes(tts, text: str) -> bytes:
    """Timbre TTS -> raw WAV bytes."""
    return tts.synthesize(text, voice=TTS_VOICE, model=TTS_MODEL, language="hi-IN")


def _speak(tts, text: str) -> str:
    """Timbre TTS -> base64 WAV for the browser <audio> player."""
    return base64.b64encode(_speak_bytes(tts, text)).decode("ascii")


def _save_turn_audio_safe(verification_id: str, turn_index: int,
                          speaker: str, wav_bytes: bytes) -> str | None:
    """Save a turn WAV; never let a recording failure break the call."""
    try:
        return db.save_turn_audio(verification_id, turn_index, speaker, wav_bytes)
    except Exception:
        return None


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
# Auth dependencies — defined up here because the /v1/verifications routes
# below use them as defaults (evaluated at definition time). The auth
# ENDPOINTS live further down, in their own section.
# Tokens are random 64-hex strings stored server-side (SessionToken table),
# 48h expiry. The dashboard sends them as "Authorization: Bearer <token>".
# No JWT, no extra dependencies.
# ---------------------------------------------------------------------------
def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
        return token or None
    return None


def get_current_user(request: Request) -> dict:
    """FastAPI dependency: the signed-in user, or 401."""
    user = db.get_user_by_token(_bearer_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def _merchant_from_api_key(request: Request) -> int | None:
    """Merchant id from the X-API-Key header, or None if no key was sent.
    A key that IS sent but invalid raises 401. This is how a store
    checkout authenticates: it posts orders as the merchant who owns
    the key, so those orders show up in that merchant's dashboard."""
    key = request.headers.get("X-API-Key", "").strip()
    if not key:
        return None
    merchant_id = db.get_merchant_id_by_api_key(key)
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return merchant_id


def get_current_merchant(request: Request) -> int:
    """FastAPI dependency: the merchant id the token is scoped to."""
    return get_current_user(request)["merchant_id"]


# ---------------------------------------------------------------------------
# Landing + dashboard pages
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    """The public site: landing page when it exists, dashboard as fallback
    (so the site never breaks while the landing page is being written)."""
    landing = BASE / "static" / "landing.html"
    if landing.is_file():
        return FileResponse(landing)
    return FileResponse(BASE / "static" / "dashboard.html")


@app.get("/dashboard")
def dashboard():
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
def create_order(order: OrderIn, request: Request):
    """Seller posts a COD order. Returns 202 with a verification_id.
    Idempotent: same external_order_id returns the same verification.
    Auth: send your merchant API key as X-API-Key and the order is filed
    under YOUR merchant (so it shows in your dashboard). Without a key
    the order goes to the demo merchant (1) — that is how the demo store
    worked before keys existed, and it still works that way."""
    merchant_id = _merchant_from_api_key(request) or DEMO_MERCHANT_ID
    existing = db.get_verification_for_order(merchant_id, order.external_order_id)
    if existing:
        return {
            "verification_id": existing["id"],
            "status": existing["status"],
            "estimated_call_at": existing["created_at"] + RING_AFTER_SECONDS,
        }
    row = db.create_order(merchant_id, order.model_dump())
    ver = db.create_verification(merchant_id, row["id"])
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
def list_verifications(status: str | None = None, limit: int = 50,
                       merchant_id: int = Depends(get_current_merchant)):
    """Dashboard list (authed merchant only)."""
    vers = db.list_verifications(merchant_id, status=status, limit=limit)
    return [_verification_payload(v) for v in vers]


@app.post("/v1/verifications/{verification_id}/cancel")
def cancel_verification(verification_id: str, request: Request):
    """Cancel a verification. Accepts either a dashboard session token
    (Authorization: Bearer) or the merchant API key (X-API-Key) — the
    store cancels with its API key. Either way the verification must
    belong to that merchant, else 404."""
    merchant_id = _merchant_from_api_key(request)
    if merchant_id is None:
        merchant_id = get_current_merchant(request)  # 401 if no token
    ver = db.get_verification(verification_id)
    if not ver or ver["merchant_id"] != merchant_id:
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
    audio_bytes = _speak_bytes(tts, greeting)
    audio_path = _save_turn_audio_safe(verification_id, 0, "agent", audio_bytes)
    db.start_call(verification_id)
    db.add_turn(verification_id, "agent", greeting, audio_path=audio_path)
    return {
        "agent_reply_text": greeting,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
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

    wav_bytes = await audio.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name
    try:
        # 1. Listen — Prisma v2.5, Hinglish (hi-IN handles code-mixed speech).
        result = stt.transcribe(tmp_path, language_code="hi-IN", model=STT_MODEL)
        customer_text = (result.get("transcript") or "").strip()
    finally:
        os.unlink(tmp_path)
    turn_index = len(past)  # transcript length before this turn
    past.append({"speaker": "customer", "text": customer_text})
    cust_path = _save_turn_audio_safe(
        verification_id, turn_index, "customer", wav_bytes
    )
    db.add_turn(verification_id, "customer", customer_text, audio_path=cust_path)

    # 2. Think — Groq LLM classifies the intent (Devanagari / code-mixed
    #    safe); falls back to the keyword matcher when it returns None.
    #    The state machine then decides the next state + reply.
    intent = classify_intent(state, customer_text) if classify_intent else None
    step = advance(state, customer_text, past, context, order, intent=intent)
    past.append({"speaker": "agent", "text": step["reply"]})
    reply_bytes = _speak_bytes(tts, step["reply"])
    agent_path = _save_turn_audio_safe(
        verification_id, turn_index + 1, "agent", reply_bytes
    )
    db.add_turn(verification_id, "agent", step["reply"], audio_path=agent_path)
    audio_b64 = base64.b64encode(reply_bytes).decode("ascii")

    # 4. If done, store the outcome and close the verification.
    if step["done"]:
        db.save_outcome(verification_id, step["outcome"])
        outcome_name = step["outcome"]["outcome"]
        status = "needs_review" if outcome_name == "NEEDS_REVIEW" else "completed"
        db.set_verification_status(verification_id, status, outcome=outcome_name)
        call_id = db.get_latest_call_id(verification_id)
        if call_id:
            db.end_call(call_id)
            recording_path = db.build_call_recording(verification_id)
            call_info = db.get_call(call_id)
            duration_s = 0.0
            if call_info and call_info.get("call"):
                duration_s = call_info["call"].get("duration_s") or 0.0
            cost = round(2.0 + 0.5 * (duration_s / 60), 2)
            db.set_call_recording(call_id, recording_path, cost)
            # Charge the verification's own merchant (not the demo one —
            # bulk orders from signed-up merchants live under them).
            db.deduct_credits(ver["merchant_id"], cost)

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


# ---------------------------------------------------------------------------
# Auth — signup / signin / demo. (Dependencies live above, near the top,
# because earlier routes reference them.)
# ---------------------------------------------------------------------------
def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


def _public_merchant(m: dict) -> dict:
    return {"id": m["id"], "name": m["name"], "brand_name": m["brand_name"]}


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    brand_name: str | None = None


class SigninIn(BaseModel):
    email: str
    password: str


@app.post("/v1/auth/signup", status_code=201)
def signup(body: SignupIn):
    """Create a merchant + the first user + a session. 201 on success."""
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not name or "@" not in email or "." not in email or len(password) < 8:
        raise HTTPException(status_code=400, detail="invalid")
    if db.get_user_by_email(email):
        raise HTTPException(status_code=400, detail="email_taken")
    brand_name = (body.brand_name or "").strip() or f"{name}'s Store"
    merchant = db.create_merchant_for_signup(brand_name)
    try:
        user = db.create_user(merchant["id"], name, email, password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    token = db.create_session(user["id"])
    return {
        "token": token,
        "user": _public_user(user),
        "merchant": _public_merchant(merchant),
    }


@app.post("/v1/auth/signin")
def signin(body: SigninIn):
    """Same 401 message for unknown email and wrong password — never leak
    which one failed."""
    user = db.get_user_by_email(body.email)
    if not user or not db.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    token = db.create_session(user["id"])
    merchant = db.get_merchant(user["merchant_id"])
    return {
        "token": token,
        "user": _public_user(user),
        "merchant": _public_merchant(merchant),
    }


@app.post("/v1/auth/signout")
def signout(request: Request, user: dict = Depends(get_current_user)):
    token = _bearer_token(request)
    if token:
        db.delete_session(token)
    return {"ok": True}


@app.get("/v1/auth/me")
def me(user: dict = Depends(get_current_user)):
    merchant = db.get_merchant(user["merchant_id"])
    return {
        "user": _public_user(user),
        "merchant": {
            "id": merchant["id"], "name": merchant["name"],
            "brand_name": merchant["brand_name"], "credits": merchant["credits"],
        },
    }


@app.post("/v1/auth/demo")
def demo_login():
    """No body needed. Returns a session scoped to merchant 1 (StyleKart),
    the seeded demo merchant — powers the landing page's 'Try the live
    demo' button. The demo user is created on first use with a random
    unguessable password, so it can never be signed in as."""
    demo_email = "demo@verifycod.in"
    user = db.get_user_by_email(demo_email)
    if not user:
        try:
            user = db.create_user(1, "Demo Merchant", demo_email, secrets.token_hex(16))
        except ValueError:
            user = db.get_user_by_email(demo_email)
    token = db.create_session(user["id"])
    merchant = db.get_merchant(1)
    return {
        "token": token,
        "user": {"id": user["id"], "name": "Demo Merchant", "email": demo_email},
        "merchant": _public_merchant(merchant),
    }


# ---------------------------------------------------------------------------
# Dashboard backend — analytics, calls, review actions, developers, billing
# All scoped to the AUTHENTICATED merchant (get_current_merchant).
# ---------------------------------------------------------------------------
VALID_OUTCOMES = {
    "CONFIRMED", "ADDRESS_UPDATED", "CANCELLED_BY_CUSTOMER", "RESCHEDULED",
    "WRONG_PERSON", "CALLBACK_REQUESTED", "NEEDS_REVIEW",
}
TEAM_ROLES = {"Owner", "Admin", "Ops", "Developer", "Viewer"}


# --- Analytics ---
@app.get("/v1/analytics/summary")
def analytics_summary(merchant_id: int = Depends(get_current_merchant)):
    return db.analytics_summary(merchant_id)


# --- Calls ---
@app.get("/v1/calls")
def list_calls(limit: int = 50,
               merchant_id: int = Depends(get_current_merchant)):
    return db.list_calls(merchant_id, limit=limit)


@app.get("/v1/calls/{call_id}")
def get_call_endpoint(call_id: int,
                      merchant_id: int = Depends(get_current_merchant)):
    c = db.get_call(call_id)
    if not c:
        raise HTTPException(status_code=404, detail="call not found")
    ver = db.get_verification(c["verification_id"])
    if not ver or ver["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="call not found")
    return c


@app.get("/v1/calls/{call_id}/recording")
def get_call_recording(call_id: int,
                       merchant_id: int = Depends(get_current_merchant)):
    c = db.get_call(call_id)
    if not c or not c["call"].get("recording_path"):
        raise HTTPException(status_code=404, detail="recording not found")
    ver = db.get_verification(c["verification_id"])
    if not ver or ver["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="recording not found")
    path = BASE / c["call"]["recording_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="recording not found")
    return FileResponse(path, media_type="audio/wav", filename="recording.wav")


@app.get("/v1/recordings/{verification_id}/{filename}")
def get_recording_file(verification_id: str, filename: str,
                       merchant_id: int = Depends(get_current_merchant)):
    # The verification must belong to the authed merchant — otherwise 404
    # (never leak another merchant's recordings, or their existence).
    ver = db.get_verification(verification_id)
    if not ver or ver["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="file not found")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    recordings_root = (BASE / "recordings").resolve()
    path = (recordings_root / verification_id / filename).resolve()
    try:
        path.relative_to(recordings_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="audio/wav", filename=filename)


# --- Review actions ---
@app.post("/v1/verifications/{verification_id}/retry")
def retry_verification_endpoint(
        verification_id: str,
        merchant_id: int = Depends(get_current_merchant)):
    ver = db.get_verification(verification_id)
    if not ver or ver["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="verification not found")
    ver = db.retry_verification(verification_id)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    return _verification_payload(ver)


class OverrideIn(BaseModel):
    outcome: str


@app.post("/v1/verifications/{verification_id}/override")
def override_verification_endpoint(
        verification_id: str, body: OverrideIn,
        merchant_id: int = Depends(get_current_merchant)):
    if body.outcome not in VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail="invalid outcome")
    ver = db.get_verification(verification_id)
    if not ver or ver["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="verification not found")
    ver = db.override_verification(verification_id, body.outcome)
    if not ver:
        raise HTTPException(status_code=404, detail="verification not found")
    return _verification_payload(ver)


# --- API keys ---
class ApiKeyIn(BaseModel):
    label: str


@app.get("/v1/api-keys")
def list_api_keys_endpoint(merchant_id: int = Depends(get_current_merchant)):
    return db.list_api_keys(merchant_id)


@app.post("/v1/api-keys", status_code=201)
def create_api_key_endpoint(body: ApiKeyIn,
                            merchant_id: int = Depends(get_current_merchant)):
    key_dict, plain = db.create_api_key(merchant_id, body.label)
    return {**key_dict, "key": plain}


@app.delete("/v1/api-keys/{key_id}")
def delete_api_key_endpoint(key_id: int,
                            merchant_id: int = Depends(get_current_merchant)):
    key = db.get_api_key(key_id)
    if not key or key["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="api key not found")
    db.revoke_api_key(key_id)
    return {"ok": True, "key_id": key_id, "status": "revoked"}


# --- Webhooks ---
class WebhookIn(BaseModel):
    url: str
    events: list = []


@app.get("/v1/webhooks")
def list_webhooks_endpoint(merchant_id: int = Depends(get_current_merchant)):
    return db.list_webhooks(merchant_id)


@app.post("/v1/webhooks", status_code=201)
def create_webhook_endpoint(body: WebhookIn,
                            merchant_id: int = Depends(get_current_merchant)):
    wh, secret = db.create_webhook(merchant_id, body.url, body.events)
    return {**wh, "secret": secret}


@app.delete("/v1/webhooks/{webhook_id}")
def delete_webhook_endpoint(webhook_id: int,
                            merchant_id: int = Depends(get_current_merchant)):
    wh = db.get_webhook(webhook_id)
    if not wh or wh["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="webhook not found")
    db.delete_webhook(webhook_id)
    return {"ok": True, "webhook_id": webhook_id}


@app.get("/v1/webhooks/deliveries")
def list_deliveries_endpoint(limit: int = 50,
                             merchant_id: int = Depends(get_current_merchant)):
    return db.list_deliveries(merchant_id, limit=limit)


@app.post("/v1/webhooks/{webhook_id}/test")
def test_webhook_endpoint(webhook_id: int,
                          merchant_id: int = Depends(get_current_merchant)):
    wh = db.get_webhook(webhook_id)
    if not wh or wh["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="webhook not found")
    payload = {
        "event": "verification.completed",
        "verification_id": "ver_test",
        "outcome": "CONFIRMED",
    }
    return db.log_delivery(
        webhook_id, "verification.completed", payload, 200, 1, 12.5
    )


@app.post("/v1/webhooks/{webhook_id}/replay")
def replay_webhook_endpoint(webhook_id: int,
                            merchant_id: int = Depends(get_current_merchant)):
    wh = db.get_webhook(webhook_id)
    if not wh or wh["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="webhook not found")
    latest = db.get_latest_delivery(webhook_id)
    if not latest:
        raise HTTPException(status_code=404, detail="no delivery to replay")
    return db.log_delivery(
        webhook_id, latest["event"], latest["payload"], 200, 1, 12.5
    )


# --- Settings ---
@app.get("/v1/settings")
def get_settings_endpoint(merchant_id: int = Depends(get_current_merchant)):
    return db.get_settings(merchant_id)


@app.put("/v1/settings")
def update_settings_endpoint(patch: dict,
                             merchant_id: int = Depends(get_current_merchant)):
    return db.update_settings(merchant_id, patch)


# --- Billing ---
@app.get("/v1/billing")
def billing(merchant_id: int = Depends(get_current_merchant)):
    credits_left = db.get_credits(merchant_id)
    calls = db.list_calls(merchant_id, limit=1000)
    calls_this_month = len(calls)
    connected = sum(1 for c in calls if (c["duration_s"] or 0) > 0)
    unanswered = calls_this_month - connected
    return {
        "credits_left": credits_left,
        "credits_used_this_month": max(0.0, 100.0 - credits_left),
        "calls_this_month": calls_this_month,
        "connected": connected,
        "unanswered": unanswered,
        "cost_breakdown": [
            {
                "label": "Connected calls",
                "amount": round(
                    sum(c["cost"] for c in calls if (c["duration_s"] or 0) > 0), 2
                ),
            },
            {
                "label": "Unanswered calls",
                "amount": round(
                    sum(c["cost"] for c in calls if (c["duration_s"] or 0) == 0), 2
                ),
            },
        ],
        "invoices": [],
    }


class AddCreditsIn(BaseModel):
    amount: float


@app.post("/v1/billing/add-credits")
def add_credits_endpoint(body: AddCreditsIn,
                         merchant_id: int = Depends(get_current_merchant)):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    balance = db.add_credits(merchant_id, body.amount)
    return {"credits_left": balance}


# --- Bulk orders ---
class BulkOrdersIn(BaseModel):
    orders: list[OrderIn]


@app.post("/v1/orders/bulk", status_code=202)
def bulk_orders(body: BulkOrdersIn,
                merchant_id: int = Depends(get_current_merchant)):
    out = []
    for order in body.orders:
        existing = db.get_verification_for_order(
            merchant_id, order.external_order_id
        )
        if existing:
            out.append({
                "external_order_id": order.external_order_id,
                "verification_id": existing["id"],
                "status": existing["status"],
            })
            continue
        row = db.create_order(merchant_id, order.model_dump())
        ver = db.create_verification(merchant_id, row["id"])
        out.append({
            "external_order_id": order.external_order_id,
            "verification_id": ver["id"],
            "status": ver["status"],
        })
    return out


# --- Team ---
class InviteIn(BaseModel):
    email: str
    role: str


@app.get("/v1/team")
def list_team_endpoint(merchant_id: int = Depends(get_current_merchant)):
    return db.list_team(merchant_id)


@app.post("/v1/team/invite", status_code=201)
def invite_team_endpoint(body: InviteIn,
                         merchant_id: int = Depends(get_current_merchant)):
    if body.role not in TEAM_ROLES:
        raise HTTPException(status_code=400, detail="invalid role")
    return db.invite_member(merchant_id, body.email, body.role)
