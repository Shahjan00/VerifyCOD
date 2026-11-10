"""VerifyCOD dialog manager — pure Python, no audio, no network.

State machine: GREETING -> AVAILABILITY -> ADDRESS_CONFIRM -> CLOSING.
Side exits: WRONG_PERSON, CUSTOMER_REFUSES, CALLBACK_REQUESTED,
RESCHEDULED, NEEDS_REVIEW (after 2 unclear answers). One extra state,
ADDRESS_CAPTURE / ADDRESS_RECONFIRM, for address changes.

The call is THREE agent turns by design (10 Nov): availability, address,
closing. No identity check, no separate order confirm — the product is
named in the first line. A 90-second call loses customers.

Intent matching is keyword-based on the Prisma transcript (Hinglish-tolerant),
no LLM — keyword matching is more reliable for a 2-day demo.

The agent lines are built from the order, so the same code works for any
store / item / customer — the demo order is just one order in the DB.
"""
import re
import time
from datetime import datetime, timedelta

from pydantic import BaseModel
from typing import Literal

# ---------------------------------------------------------------------------
# Outcome schema (strict JSON shown on the dashboard + store order page)
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
# Agent lines — built from the order, so any store/item/customer works.
# Timbre TTS, Hinglish, voice Pranav. The call is THREE turns by design:
# availability -> address -> closing. Opening line names the store and the
# product and asks about the delivery day. Never asks for OTPs, card
# details or UPI PINs. Ever.
# ---------------------------------------------------------------------------
def _delivery_date(order: dict) -> str:
    """Delivery day the agent asks about: order date + 2 days (the
    '2 to 3 days' promise). E.g. '12 November' -> 'kya aap 12 November
    ko available rahenge?'"""
    ts = order.get("created_at") or time.time()
    try:
        day = datetime.fromtimestamp(float(ts) + 2 * 86400)
    except (TypeError, ValueError, OSError):
        day = datetime.now() + timedelta(days=2)
    return day.strftime("%d %B").lstrip("0")


def lines_for(order: dict) -> dict:
    store = order.get("store", "the store")
    items = order.get("items") or [{"name": "your order", "qty": 1, "price": 0}]
    item = items[0]
    amount = order.get("amount", item.get("price", 0))
    addr = order.get("address") or {}
    addr_str = ", ".join(
        p for p in [
            addr.get("line1", ""),
            addr.get("landmark", ""),
            addr.get("city", ""),
            addr.get("state", ""),
            addr.get("pincode", ""),
        ]
        if p
    )
    delivery = _delivery_date(order)
    return {
        "GREETING": (
            f"Main {store} se AI agent bol raha hoon, aapka "
            f"{item['name']} confirm karne ke liye. Kya aap {delivery} ko "
            f"available rahenge?"
        ),
        "ADDRESS_CONFIRM": (
            f"Okay, to aapka address {addr_str} ye hai. Kya ye sahi hai "
            f"ya ise update karna hai?"
        ),
        "ADDRESS_CAPTURE": "Theek hai, apna naya address boliye.",
        "CLOSING_CONFIRMED": (
            "Shukriya, aapka order jaldi aapke paas pahunch jayega."
        ),
        "CLOSING_ADDRESS_UPDATED": (
            "Shukriya, aapka naya address save ho gaya hai. Aapka order "
            "jaldi aapke paas pahunch jayega."
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
# Intent matching — keyword-based on the Prisma transcript, Hinglish-tolerant.
# Order matters: specific phrases first, plain "nahi"/"haan" last, because
# "sahi nahi hai" contains both a yes-word and a no-word.
# ---------------------------------------------------------------------------
def _words(text: str) -> set[str]:
    # a-z for Roman Hinglish + Devanagari range for Hindi script.
    # Prisma transcribes Hindi speech in Devanagari, so [a-z] alone drops it.
    return set(re.findall(r"[a-z\u0900-\u097F]+", text.lower()))


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
                         "ramesh nahi", "main ramesh nahin",
                         "गलत नंबर", "गलत आदमी", "मैं रमेश नहीं",
                         "रमेश नहीं"]):
        return "wrong_person"
    if _has_phrase(low, ["nahi chahiye", "cancel", "mat bhejo", "nahi lena",
                         "order cancel", "nahi mangwana",
                         "नहीं चाहिए", "कैंसल", "रद्द", "मत भेजो",
                         "नहीं लेना", "ऑर्डर कैंसल", "नहीं मंगवाना"]):
        return "cancel"
    # Callback before reschedule: "baad mein call karo" means call me later,
    # not "deliver later". Callback phrases are more specific, so check first.
    if _has_phrase(low, ["wapas call", "callback", "call back", "phir call",
                         "dobara call", "call karo",
                         "वापस कॉल", "फिर कॉल", "दोबारा कॉल", "कॉल करो"]):
        return "callback"
    if _has_phrase(low, ["baad mein", "reschedule", "kal", "parson", "later",
                         "agle hafte", "next week",
                         "बाद में", "कल", "परसों", "अगले हफ्ते"]):
        return "reschedule"
    if _has_phrase(low, ["badlo", "change", "naya address", "address galat",
                         "galat address", "address badlo",
                         "बदलो", "नया पता", "पता गलत", "गलत पता", "पता बदलो"]):
        return "address_change"
    if words & {"nahi", "nahin", "nhi", "no", "na", "नहीं", "नही", "ना"}:
        return "no"
    if words & {"haan", "han", "yes", "sahi", "correct", "theek", "thik",
                "ok", "okay", "bilkul", "ji",
                "हाँ", "हां", "जी", "सही", "ठीक", "बिल्कुल", "ओके"}:
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
# advance(state, user_text, history, ctx, order) -> result dict.
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


def advance(state: str, user_text: str, history: list[dict], ctx: dict,
            order: dict, intent: str | None = None) -> dict:
    """One customer turn -> next state + agent reply (+ outcome if done).

    `intent` is the LLM-classified intent (from verifycod/llm.py, Groq).
    When it is None — no key, LLM failed, or the caller did not classify —
    the keyword matcher below decides. The state machine never depends on
    the LLM being up.
    """
    LINES = lines_for(order)
    ctx = dict(ctx or {})
    ctx.setdefault("unclear_count", 0)
    ctx.setdefault("address_attempts", 0)
    ctx.setdefault("clarified", False)
    if intent is None:
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

    # --- AVAILABILITY (first + only opening question) -------------------
    if state == "AVAILABILITY":
        if intent == "yes":
            ctx["unclear_count"] = 0
            # Multi-intent: "haan, available hoon, address bhi sahi hai" —
            # the customer confirmed availability AND the address in one
            # breath. Skip the address step and close.
            _w = _words(user_text or "")
            if ("address" in _w or "एड्रेस" in _w) and _w & {
                    "sahi", "theek", "shi", "correct", "सही", "ठीक"}:
                return {"next_state": "CLOSING", "reply": LINES["CLOSING_CONFIRMED"],
                        "ctx": ctx, **_finish("CONFIRMED", 0.95, history, ctx)}
            return {"next_state": "ADDRESS_CONFIRM", "reply": LINES["ADDRESS_CONFIRM"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent == "wrong_person":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_WRONG_PERSON"],
                    "ctx": ctx,
                    **_finish("WRONG_PERSON", 0.95, history, ctx)}
        if intent == "cancel":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.95, history, ctx,
                              cancel_reason="refused at availability check")}
        if intent == "no":
            # "No" to "are you free on the delivery day?" = not free that
            # day, not a refusal of the order. Reschedule, don't cancel.
            return {"next_state": "CLOSING",
                    "reply": "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad.",
                    "ctx": ctx,
                    **_finish("RESCHEDULED", 0.7, history, ctx,
                              reschedule_for=user_text.strip())}
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
            "Maaf kijiye, samajh nahi aaya. Kya aap "
            f"{_delivery_date(order)} ko available rahenge?")

    # --- ADDRESS_CONFIRM ------------------------------------------------
    if state == "ADDRESS_CONFIRM":
        if intent == "yes":
            ctx["unclear_count"] = 0
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CONFIRMED"],
                    "ctx": ctx, **_finish("CONFIRMED", 0.95, history, ctx)}
        if intent == "address_change":
            ctx["unclear_count"] = 0
            ctx["address_attempts"] = ctx.get("address_attempts", 0) + 1
            return {"next_state": "ADDRESS_CAPTURE", "reply": LINES["ADDRESS_CAPTURE"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent == "cancel":
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_CANCELLED"],
                    "ctx": ctx,
                    **_finish("CANCELLED_BY_CUSTOMER", 0.95, history, ctx,
                              cancel_reason="refused at address confirmation")}
        if intent == "no":
            # "No" NEVER cancels here. The question is "is this address
            # correct?" — a "no" means the address is wrong, not that the
            # order is refused. Two cases:
            #  - "Nhi, yhi theek h" / "No, this is fine": the "no" answers
            #    "do you want to change it?" and the address is fine —
            #    keep it and move on. (This was the live bug: it cancelled.)
            #  - A bare "no": the address is wrong — ask for the new one.
            low = (user_text or "").lower()
            if _has_phrase(low, ["yhi theek", "yehi theek", "yahi theek",
                                 "yehi sahi", "yahi sahi", "theek hai",
                                 "theek h", "sahi hai", "sahi h",
                                 "this is fine", "it's fine", "fine hai",
                                 "yehi rakh", "yahi rakh", "yehi rakho",
                                 "यही ठीक", "यही सही", "ठीक है", "सही है"]):
                ctx["unclear_count"] = 0
                return {"next_state": "CLOSING", "reply": LINES["CLOSING_CONFIRMED"],
                        "ctx": ctx, **_finish("CONFIRMED", 0.95, history, ctx)}
            ctx["unclear_count"] = 0
            ctx["address_attempts"] = ctx.get("address_attempts", 0) + 1
            return {"next_state": "ADDRESS_CAPTURE", "reply": LINES["ADDRESS_CAPTURE"],
                    "ctx": ctx, "done": False, "outcome": None}
        if intent == "reschedule":
            return {"next_state": "CLOSING",
                    "reply": "Theek hai, hum aapko baad mein phir call karenge. Dhanyavaad.",
                    "ctx": ctx,
                    **_finish("RESCHEDULED", 0.7, history, ctx,
                              reschedule_for=user_text.strip())}
        addr = order.get("address") or {}
        addr_str = ", ".join(p for p in [
            addr.get("line1", ""), addr.get("landmark", ""),
            addr.get("city", ""), addr.get("state", ""), addr.get("pincode", ""),
        ] if p)
        return unclear_again(
            "Maaf kijiye, samajh nahi aaya. Address hai "
            f"{addr_str} — kya ye sahi hai?")

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
            return {"next_state": "CLOSING", "reply": LINES["CLOSING_ADDRESS_UPDATED"],
                    "ctx": ctx, **_finish("ADDRESS_UPDATED", 0.95, history, ctx)}
        if intent in ("no", "address_change"):
            if ctx.get("address_attempts", 0) >= 2:
                return {"next_state": "CLOSING",
                        "reply": LINES["CLOSING_NEEDS_REVIEW"], "ctx": ctx,
                        **_finish("NEEDS_REVIEW", 0.5, history, ctx)}
            ctx["address_attempts"] = ctx.get("address_attempts", 0) + 1
            return {"next_state": "ADDRESS_CAPTURE", "reply": LINES["ADDRESS_CAPTURE"],
                    "ctx": ctx, "done": False, "outcome": None}
        return unclear_again("Maaf kijiye, samajh nahi aaya. Naya address sahi hai ya nahi?")

    # Unknown state — should not happen; fail safe to a human review.
    return {"next_state": "CLOSING", "reply": LINES["CLOSING_NEEDS_REVIEW"],
            "ctx": ctx, **_finish("NEEDS_REVIEW", 0.5, history, ctx)}
