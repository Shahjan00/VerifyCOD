"""Groq LLM intent classification for the VerifyCOD voice agent.

The keyword matcher in dialog.py breaks on natural speech — Devanagari
script, code-mixed Hinglish, multi-intent lines ("haan, main Ramesh hoon,
order confirm kar do"). An LLM understands meaning regardless of script.

This module is the ONLY place that talks to Groq. It returns None whenever
it cannot classify (no key, network error, bad JSON) and the caller falls
back to the keyword matcher — the call never fails because the LLM did.

Model: openai/gpt-oss-20b on Groq (same model Zuno uses). Key in .env as
GROQ_API_KEY — never in chat, never in code.
"""
import json
import os

MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """You classify what a COD delivery customer just said on a phone call.
Reply with ONLY a JSON object: {"intent": "<one of the intents>", "confidence": <0.0-1.0>}.

Valid intents:
- yes: customer agrees / confirms / says the order, address or delivery is correct.
- no: customer says it is wrong / refuses / says no.
- wrong_person: this is not the customer, wrong number.
- cancel: customer wants to cancel the order / does not want it.
- reschedule: customer wants delivery later / another day.
- callback: customer wants a call back later (NOT a later delivery).
- address_change: customer wants to change the delivery address.
- unclear: greeting, test question ("can you hear me?"), noise, or anything that does not answer the question.

Rules:
- The customer speaks Hinglish — Hindi in Devanagari script, Roman Hindi, or English, often mixed. Judge meaning, not script or exact words.
- "haan, main Ramesh hoon, order confirm kar do" is yes (identity confirmed AND order confirmed in one breath).
- "baad mein call karo" is callback, NOT reschedule. "kal delivery karo" is reschedule.
- A question that does not answer the agent (like "can you hear my voice?") is unclear.
- "cancel" is ONLY when the customer explicitly wants to cancel the order / does not want it ("nahi chahiye", "cancel kar do", "mat bhejo"). A "no" answering a yes/no question is NEVER "cancel" — it means the thing asked about is wrong.
- In ADDRESS_CONFIRM, "nahi, yehi theek hai" / "no, this is fine" is yes — the "no" answers "do you want to change it?" and the address is correct. A bare "no" there means the address is wrong, so use "address_change", not "cancel".
"""

# What the agent just asked, per state — so the LLM reads the reply in context.
STATE_QUESTIONS = {
    "IDENTITY": "Am I speaking with the customer?",
    "ORDER_CONFIRM": "Is this order correct?",
    "ADDRESS_CONFIRM": "Is this delivery address correct, or do you want to change it?",
    "ADDRESS_RECONFIRM": "Is the new address correct?",
    "DELIVERY_INTENT": "Will you be available to accept the delivery and pay in cash?",
}


def classify_intent(state: str, transcript: str) -> str | None:
    """LLM intent classification. Returns an intent string or None.

    None means "could not classify" — the caller must fall back to the
    keyword matcher. Never raises for missing key / network / bad JSON.
    """
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key or not (transcript or "").strip():
        return None
    try:
        from groq import Groq
    except ImportError:
        return None
    question = STATE_QUESTIONS.get(state, "the agent's last question")
    try:
        client = Groq(api_key=key, timeout=10)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"The agent just asked: {question}\n"
                    f"The customer replied: {transcript.strip()}"
                )},
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        intent = (data.get("intent") or "").strip().lower()
        valid = {"yes", "no", "wrong_person", "cancel", "reschedule",
                 "callback", "address_change", "unclear"}
        return intent if intent in valid else None
    except Exception:
        return None
