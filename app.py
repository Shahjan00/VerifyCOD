"""VerifyCOD — slim browser demo for the Gnani.ai Great Indian AI Internship Challenge.

No telephony. The user plays the COD customer, the app plays the verification
agent. One simulated phone call in the browser:

  mic (you, the customer) -> Prisma v2.5 STT -> dialog state machine
  -> Timbre v2.5 TTS (agent speaks) -> outcome JSON on the end screen.

Sample order (hardcoded): StyleKart, Ramesh Patel, 1x Cotton Kurta, Rs 1299,
COD, Flat 302 Shanti Nagar, near Hanuman mandir, Vadodara 390001.

Dialog: GREETING -> IDENTITY -> ORDER_CONFIRM -> ADDRESS_CONFIRM
       -> DELIVERY_INTENT -> CLOSING. Side exits: WRONG_PERSON,
       CUSTOMER_REFUSES, CALLBACK_REQUESTED, RESCHEDULED, NEEDS_REVIEW.
Intent matching is keyword-based on the transcript (Hinglish-tolerant),
no LLM — keyword matching is more reliable for a 2-day demo.

Run:  pip install -r requirements.txt
       copy .env.example to .env and put your Gnani API key in it
       uvicorn app:app --reload
       open http://127.0.0.1:8000
"""
import base64
import json
import os
import re
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gnani.stt import GnaniSTTClient
from gnani.tts import GnaniTTSClient
from pydantic import BaseModel
from typing import Literal

load_dotenv()

# Models named in the submission: Prisma v2.5 (STT) + Timbre v2.5 (TTS).
STT_MODEL = "prisma-v2.5"
TTS_MODEL = "timbre-v2.5"
TTS_VOICE = "Pranav"  # Timbre v2.5 voice; language hi-IN below

# ---------------------------------------------------------------------------
# Sample order (the demo scenario — hardcoded, no database for the demo)
# ---------------------------------------------------------------------------
ORDER = {
    "store": "StyleKart",
    "external_order_id": "SK-1042",
    "customer": {"name": "Ramesh Patel", "phone": "+919876543210", "language_hint": "hi-en"},
    "address": {
        "line1": "Flat 302, Shanti Nagar",
        "landmark": "near Hanuman mandir",
        "city": "Vadodara",
        "state": "Gujarat",
        "pincode": "390001",
    },
    "items": [{"name": "Cotton Kurta", "qty": 1, "price": 1299}],
    "amount": 1299,
    "currency": "INR",
    "payment_mode": "COD",
}

# ---------------------------------------------------------------------------
# Agent lines (Timbre TTS, Hinglish, voice Pranav)
# ---------------------------------------------------------------------------
LINES = {
    "GREETING": (
        "Namaste, I'm calling from StyleKart about your order of a Cotton Kurta, "
        "worth 1299 rupees. Am I speaking with Ramesh Patel?"
    ),
    "ORDER_CONFIRM": (
        "Great. You ordered one Cotton Kurta for 1299 rupees, cash on delivery. "
        "Is that correct?"
    ),
    "ADDRESS_CONFIRM": (
        "Your delivery address is Flat 302, Shanti Nagar, near Hanuman mandir, "
        "Vadodara, 390001. Is this correct, or do you want to change it?"
    ),
    "ADDRESS_CAPTURE": "Theek hai, apna naya address boliye.",
    "DELIVERY_INTENT": (
        "Perfect. Will you be available to accept the delivery and pay "
        "1299 rupees in cash?"
    ),
    "CLOSING_CONFIRMED": (
        "Thank you, your order is confirmed. You will receive it in 2 to 3 days."
    ),
    "CLOSING_ADDRESS_UPDATED": (
        "Thank you, your new address is saved and your order is confirmed. "
        "You will receive it in 2 to 3 days."
    ),
    "CLOSING_CANCELLED": (
        "Theek hai, aapka order cancel kar diya gaya hai. Dhanyavaad."
    ),
    "CLOSING_WRONG_PERSON": (
        "Maaf kijiye, lagta hai galat number hai. Dhanyavaad, goodbye."
    ),
    "CLOSING_CALLBACK": (
        "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad."
    ),
    "CLOSING_NEEDS_REVIEW": (
        "Maaf kijiye, main aapki baat samajh nahi paya. Hamari team aapko "
        "WhatsApp par message karegi. Dhanyavaad."
    ),
}

# ---------------------------------------------------------------------------
# Outcome schema (strict JSON shown on the end screen)
# ---------------------------------------------------------------------------
class Turn(BaseModel):
    speaker: Literal["agent", "customer"]
    text: str


class AddressOut(BaseModel):
    line1: str | None = None
    landmark: str | None = None
    pincode: str | None = None


class Outcome(BaseModel):
    outcome: Literal[
        "CONFIRMED",
        "ADDRESS_UPDATED",
        "CANCELLED_BY_CUSTOMER",
        "RESCHEDULED",
        "WRONG_PERSON",
        "CALLBACK_REQUESTED",
        "NEEDS_REVIEW",
    ]
    confidence: float
    corrected_address: AddressOut | None = None
    reschedule_for: str | None = None
    cancel_reason: str | None = None
    language_detected: str = "hi-en"
    transcript: list[Turn] = []


# ---------------------------------------------------------------------------
# Intent matching — keyword-based on the Prisma transcript, Hinglish-tolerant.
# Order matters: specific phrases first, plain "nahi"/"haan" last, because
# "sahi nahi hai" contains both a yes-word and a no-word.
# ---------------------------------------------------------------------------
def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _has_phrase(text: str, phrases: list[str]) -> bool:
    low = text.lower()
    return any(p in low for p in phrases)


def detect_intent(text: str) -> str:
    """One of: wrong_person, cancel, reschedule, callback, address_change,
    no, yes, unclear. Pure function — easy to unit test."""
    low = (text or "").lower().strip()
    words = _words(low)
    if not low:
        return "unclear"
    if _has_phrase(low, ["galat number", "wrong person", "main ramesh nahi",
                         "ramesh nahi", "main ramesh nahin"]):
        return "wrong_person"
    if _has_phrase(low, ["nahi chahiye", "cancel", "mat bhejo", "nahi lena",
                         "order cancel", "nahi mangwana"]):
        return "cancel"
    # Callback before reschedule: "baad mein call karo" means call me later,
    # not "deliver later". Callback phrases are more specific, so check first.
    if _has_phrase(low, ["wapas call", "callback", "call back", "phir call",
                         "dobara call", "call karo"]):
        return "callback"
    if _has_phrase(low, ["baad mein", "reschedule", "kal", "parson", "later",
                         "agle hafte", "next week"]):
        return "reschedule"
    if _has_phrase(low, ["badlo", "change", "naya address", "address galat",
                         "galat address", "address badlo"]):
        return "address_change"
    if words & {"nahi", "nahin", "no", "na"}:
        return "no"
    if words & {"haan", "han", "yes", "sahi", "correct", "theek", "thik",
                "ok", "okay", "bilkul", "ji"}:
        return "yes"
    return "unclear"


def parse_address(text: str) -> AddressOut:
    """Pull a pincode and a landmark out of a spoken address. Best effort —
    the raw text is kept as line1, so nothing is lost if parsing misses."""
    pin = re.search(r"\b(\d{6})\b", text)
    landmark = None
    m = re.search(r"near\s+([^,;.]+)", text, re.IGNORECASE)
    if m:
        landmark = "near " + m.group(1).strip()
    return AddressOut(
        line1=text.strip(),
        landmark=landmark,
        pincode=pin.group(1) if pin else None,
    )


# ---------------------------------------------------------------------------
# Dialog state machine — pure function, no audio, no network.
# advance(state, user_text, history, ctx) -> result dict.
# ctx carries: corrected_address (dict|None), unclear_count (int),
#              clarified (bool), address_attempts (int).
# ---------------------------------------------------------------------------
def _finish(outcome: str, confidence: float, history: list[dict],
            ctx: dict, **extra) -> dict:
    oc = Outcome(
        outcome=outcome,
        confidence=confidence,
        corrected_address=ctx.get("corrected_address"),
        language_detected="hi-en",
        transcript=[Turn(**t) for t in history],
        **extra,
    )
    return {"done": True, "outcome": oc.model_dump()}


def advance(state: str, user_text: str, history: list[dict], ctx: dict) -> dict:
    """One customer turn -> next state + agent reply (+ outcome if done)."""
    ctx = dict(ctx or {})
    ctx.setdefault("unclear_count", 0)
    ctx.setdefault("address_attempts", 0)
    ctx.setdefault("clarified", False)
    intent = detect_intent(user_text)

    def unclear_again(repeat_line: str) -> dict:
        """First unclear: repeat the question. Second unclear: give up to a human."""
        ctx["unclear_count"] = ctx.get("unclear_count", 0) + 1
        if ctx["unclear_count"] >= 2:
            return {
                "next_state": "CLOSING",
                "reply": LINES["CLOSING_NEEDS_REVIEW"],
                "ctx": ctx,
                **_finish("NEEDS_REVIEW", 0.5, history, ctx),
            }
        return {"next_state": state, "reply": repeat_line, "ctx": ctx,
                "done": False, "outcome": None}

    # --- IDENTITY -------------------------------------------------------
    if state == "IDENTITY":
        if intent == "yes":
            ctx["unclear_count"] = 0
            return {"next_state": "ORDER_CONFIRM", "reply": LINES["ORDER_CONFIRM"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent == "wrong_person":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_WRONG_PERSON"],
                    "ctx": ctx,
                    **_finish("WRONG_PERSON", 0.95, history, ctx)}
        if intent == "cancel":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.95, history, ctx,
                              cancel_reason="refused at identity check")}
        return unclear_again(
            "Maaf kijiye, samajh nahi aaya. Kya main Ramesh Patel se baat kar raha hoon?")

    # --- ORDER_CONFIRM --------------------------------------------------
    if state == "ORDER_CONFIRM":
        if intent == "yes":
            ctx["unclear_count"] = 0
            return {"next_state": "ADDRESS_CONFIRM", "reply": LINES["ADDRESS_CONFIRM"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent in ("no", "cancel"):
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.95, history, ctx,
                              cancel_reason="customer said the order is wrong / refused")}
        if intent == "reschedule":
            return {"next_state": "CLOSING",
                    "reply": "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad.",
                    "ctx": ctx,
                    **_finish("RESCHEDULED", 0.7, history, ctx,
                              reschedule_for=user_text.strip())}
        if intent == "callback":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CALLBACK"],
                    "ctx": ctx,
                    **_finish("CALLBACK_REQUESTED", 0.95, history, ctx)}
        return unclear_again(
            "Maaf kijiye, samajh nahi aaya. Aapne ek Cotton Kurta, 1299 rupees, "
            "cash on delivery order kiya tha — kya ye sahi hai?")

    # --- ADDRESS_CONFIRM ------------------------------------------------
    if state == "ADDRESS_CONFIRM":
        if intent == "yes":
            ctx["unclear_count"] = 0
            return {"next_state": "DELIVERY_INTENT", "reply": LINES["DELIVERY_INTENT"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent == "address_change":
            ctx["unclear_count"] = 0
            ctx["address_attempts"] = ctx.get("address_attempts", 0) + 1
            return {"next_state": "ADDRESS_CAPTURE", "reply": LINES["ADDRESS_CAPTURE"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent in ("no", "cancel"):
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.95, history, ctx,
                              cancel_reason="refused at address confirmation")}
        if intent == "reschedule":
            return {"next_state": "CLOSING",
                    "reply": "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad.",
                    "ctx": ctx,
                    **_finish("RESCHEDULED", 0.7, history, ctx,
                              reschedule_for=user_text.strip())}
        return unclear_again(
            "Maaf kijiye, samajh nahi aaya. Address hai Flat 302, Shanti Nagar, "
            "near Hanuman mandir, Vadodara, 390001 — kya ye sahi hai, ya badalna hai?")

    # --- ADDRESS_CAPTURE (raw spoken address, no keyword check) ---------
    if state == "ADDRESS_CAPTURE":
        if user_text.strip():
            ctx["corrected_address"] = parse_address(user_text.strip()).model_dump()
            ctx["unclear_count"] = 0
            addr = user_text.strip()
            return {"next_state": "ADDRESS_RECONFIRM",
                    "reply": f"Aapka naya address hai: {addr}. Kya ye sahi hai?",
                    "ctx": ctx, "done": False, "outcome": None}
        return unclear_again("Maaf kijiye, address sunaai nahi diya. Apna naya address phir se boliye.")

    # --- ADDRESS_RECONFIRM ----------------------------------------------
    if state == "ADDRESS_RECONFIRM":
        if intent == "yes":
            ctx["unclear_count"] = 0
            return {"next_state": "DELIVERY_INTENT", "reply": LINES["DELIVERY_INTENT"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent in ("no", "address_change"):
            if ctx.get("address_attempts", 0) >= 2:
                return {"next_state": "CLOSING",
                        "reply": LINES["CLOSING_NEEDS_REVIEW"], "ctx": ctx,
                        **_finish("NEEDS_REVIEW", 0.5, history, ctx)}
            ctx["address_attempts"] = ctx.get("address_attempts", 0) + 1
            return {"next_state": "ADDRESS_CAPTURE", "reply": LINES["ADDRESS_CAPTURE"],
                    "ctx": ctx, "done": False, "outcome": None}
        return unclear_again("Maaf kijiye, samajh nahi aaya. Naya address sahi hai ya nahi?")

    # --- DELIVERY_INTENT -------------------------------------------------
    if state == "DELIVERY_INTENT":
        if intent == "yes":
            ctx["unclear_count"] = 0
            changed = bool(ctx.get("corrected_address"))
            outcome = "ADDRESS_UPDATED" if changed else "CONFIRMED"
            line = LINES["CLOSING_ADDRESS_UPDATED"] if changed else LINES["CLOSING_CONFIRMED"]
            return {"next_state": "CLOSING", "reply": line, "ctx": ctx,
                    **_finish(outcome, 0.95, history, ctx)}
        if intent == "reschedule":
            return {"next_state": "CLOSING",
                    "reply": "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad.",
                    "ctx": ctx,
                    **_finish("RESCHEDULED", 0.7, history, ctx,
                              reschedule_for=user_text.strip())}
        if intent == "callback":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CALLBACK"],
                    "ctx": ctx,
                    **_finish("CALLBACK_REQUESTED", 0.95, history, ctx)}
        if intent in ("no", "cancel"):
            if not ctx.get("clarified"):
                ctx["clarified"] = True
                return {"next_state": "DELIVERY_INTENT",
                        "reply": "Kya aap order cancel karna chahte hain, "
                                 "ya delivery baad mein chahiye?",
                        "ctx": ctx, "done": False, "outcome": None}
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.7, history, ctx,
                              cancel_reason="not available for delivery, refused")}
        return unclear_again(
            "Maaf kijiye, samajh nahi aaya. Kya aap delivery lene ke liye "
            "uplabdh rahenge aur 1299 rupees cash denge?")

    # Unknown state — should not happen; fail safe to a human review.
    return {"next_state": "CLOSING", "reply": LINES["CLOSING_NEEDS_REVIEW"],
            "ctx": ctx, **_finish("NEEDS_REVIEW", 0.5, history, ctx)}


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="VerifyCOD — COD Verification Demo")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _clients():
    """Build Gnani clients from the .env key. Fails loudly if key is missing."""
    key = os.getenv("GNANI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GNANI_API_KEY missing — copy .env.example to .env and add your key.")
    return GnaniSTTClient(api_key=key), GnaniTTSClient(api_key=key)


def _speak(tts, text: str) -> str:
    """Timbre TTS -> base64 WAV for the browser <audio> player."""
    audio_bytes = tts.synthesize(text, voice=TTS_VOICE, model=TTS_MODEL, language="hi-IN")
    return base64.b64encode(audio_bytes).decode("ascii")


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/api/order")
def get_order():
    """The sample order the demo call is verifying."""
    return ORDER


@app.post("/api/start")
async def start_call():
    """Agent speaks first (like a real outbound call): the greeting."""
    try:
        _, tts = _clients()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    greeting = LINES["GREETING"]
    history = [{"speaker": "agent", "text": greeting}]
    return {
        "agent_reply_text": greeting,
        "audio_base64": _speak(tts, greeting),
        "next_state": "IDENTITY",
        "history": history,
        "ctx": {},
        "done": False,
        "outcome": None,
    }


@app.post("/api/voice")
async def voice(
    audio: UploadFile = File(...),
    state: str = Form("IDENTITY"),
    history: str = Form("[]"),
    ctx: str = Form("{}"),
):
    """One customer turn: upload a .wav clip + current state + history.
    Returns transcript, agent reply (+ audio), next state, outcome if done."""
    try:
        stt, tts = _clients()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
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

    # 2. Think — the state machine decides the next state + reply.
    step = advance(state, customer_text, past, context)
    past.append({"speaker": "agent", "text": step["reply"]})

    # 3. Speak — Timbre v2.5, Hinglish, returns WAV bytes.
    audio_b64 = _speak(tts, step["reply"])
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
