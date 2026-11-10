# VerifyCOD — Gnani.ai Great Indian AI Internship Challenge

**Deadline: Tue 10 Nov 2026, 11:59 PM IST. No extensions.**
Models used: **Prisma v2.5** (speech-to-text) + **Timbre v2.5** (text-to-speech).
Target award: **Mixed Vibes** (best Hinglish code-mixed build) — also fits Solo Ninja.
Submission needs: working demo + 60-sec demo post on LinkedIn/X with
`#GreatIndianAIInternshipChallenge #GnaniAI` + the submission form in your email.

## The problem (one line)

COD orders in India get returned ~20–30% of the time — the buyer never
ordered, changed their mind, or the address is wrong. Sellers pay shipping
both ways. VerifyCOD calls the buyer in their own language and confirms
the order before the seller ships.

## The demo (no telephony)

Two servers, both local. No real phone calls — the "call" is a simulated
customer phone inside the demo store:

```
Demo Store (port 8001)                      VerifyCOD API (port 8000)
  buy a Kurta, COD checkout
    -- POST /v1/orders ----------------->  validates, SQLite, verification
                                             status: queued -> calling (3s)
  customer-phone widget polls
    -- GET /v1/verifications/{id} ------>  sees "calling" -> phone rings
  you answer, speak into the mic
    -- POST /api/voice (WAV) ----------->  Prisma STT -> dialog state
                                             machine -> Timbre TTS reply
                                             -> outcome JSON in SQLite
  store shows the result                    dashboard shows the same
```

**Why not Telegram calls:** Telegram bots cannot do live voice calls — the
Bot API only sends/receives voice messages (audio files), not real-time
calls. The phone widget in the store is the right stand-in: a real-time
voice loop in the browser, no telephony provider needed. Real telephony
(Exotel/Twilio) is the next step after the challenge.

## The website (landing → sign-in → dashboard)

Open http://127.0.0.1:8000 — a full website, not just a dashboard:

- **Landing page** (`/`) — hero with a live animated demo call, the RTO
  math, how it works, features, pricing, FAQ, and sign-up / sign-in
  modals. A "Try the live demo" button drops you straight into a seeded
  dashboard with 6 realistic orders — no account needed.
- **Sign-up / sign-in** — create a merchant account (name, store, email,
  password ≥ 8 chars, hashed with PBKDF2). Each account gets its own
  merchant, its own data, and ₹100 starting credits. Sessions last 48h.
- **Dashboard** (`/dashboard`) — requires a session token; without one
  it bounces you back to the landing page. Signing out clears the
  session server-side too. Merchants can never see each other's data
  (cross-merchant access returns 404).

## The dashboard (merchant console)

Open http://127.0.0.1:8000/dashboard after signing in — a full merchant dashboard, no build step
(plain HTML + vanilla JS, hash-routed SPA, near-black + lime theme):

- **Dashboard** — KPIs (orders, calls, confirmation rate, money saved),
  outcomes line chart + donut, live activity feed, alerts, quick actions.
- **Orders** — filters, search, bulk retry/cancel, CSV export, and a row
  drawer with timeline, address (original vs corrected), transcript,
  and manual override.
- **Conversations** — call list + detail view with a real waveform player
  (draws the actual recording), per-turn audio playback, extracted JSON,
  and Mark correct / Flag as wrong (feeds the eval data).
- **Review queue** — every NEEDS_REVIEW call, approve / edit outcome /
  call back.
- **Analytics** — connect rate, avg call length, cost per verified order,
  language split, top failing pincodes, RTO impact, CSV export.
- **Integrations** — working CSV import wizard (map columns → preview →
  bulk import), Shopify / Sheets / WooCommerce cards, send test order.
- **API Keys** — create (shown once, `vc_live_…`), revoke, curl snippet.
- **Webhooks** — endpoints, HMAC signing secret (`whsec_…`), delivery log,
  test + replay.
- **Billing** — credit balance (starts at ₹100), add credits, usage, plans.
- **Settings** — brand, calling hours, languages & voice, script & FAQs,
  risk rules, privacy (retention, do-not-call).
- **Team** — invite with roles Owner / Admin / Ops / Developer / Viewer.
- **Cmd+K** — global search across orders by id, name, or phone.
  Test/Live toggle in the top bar (sandbox never mixes with live).

Every call is recorded: turn-by-turn WAVs + one merged `recording.wav`
per call, stored under `verifycod/recordings/` (gitignored). Cost is
₹2 + ₹0.50/min, deducted from credits automatically.

## Folder layout

```
gnani-voice-buddy/
  README.md, requirements.txt, .env.example, test_api.py
  verifycod/          Server 1 — the API (port 8000)
    app.py            FastAPI + SQLAlchemy, /v1/orders, /v1/verifications, /api/voice
    dialog.py         state machine + intent matching + outcome extraction
    llm.py            Groq LLM intent classification (gpt-oss-20b), keyword fallback
    db.py             SQLAlchemy ORM models (SQLite now, Postgres via DATABASE_URL)
    static/landing.html     landing page + sign-up/sign-in (served at /)
    static/dashboard.html   merchant dashboard (12 pages, vanilla JS SPA)
    recordings/           per-call WAVs (gitignored, created on first call)
    verifycod.db      created on first run (gitignored)
  store/              Server 2 — the demo store (port 8001)
    app.py            serves the storefront
    static/index.html storefront + cart + COD checkout + customer phone widget
  app.py, static/     OLD single-page demo — superseded, kept for reference
```

## How it works (explain it across a table)

1. **Seller posts an order** — `POST /v1/orders` with customer, address,
   items, amount, payment_mode=COD. Idempotent on `external_order_id`.
   The API stores it in SQLite and creates a verification (`ver_xxxx`).
   **API keys:** send your merchant key as an `X-API-Key` header and the
   order is filed under YOUR merchant — it shows in your dashboard. Without
   a key the order goes to the demo merchant (1). The demo store ships
   with the demo key (`vc_live_demo_stylekart_...`, order-creation only,
   public by design) so its orders land in the demo dashboard. To point a
   store at your own merchant: dashboard → API Keys → Create → copy the
   `vc_live_...` value (shown once) → paste it into the store's `API_KEY`.
   Cancel also accepts the key (`POST /v1/verifications/{id}/cancel`).
2. **The call is placed** — after 3 seconds the verification flips to
   `calling`. In production a telephony provider dials; here the phone
   widget just sees the status change and rings.
3. **The voice loop** — you answer on the phone widget and speak. The mic
   audio is encoded as WAV in the browser (Gnani STT takes WAV, not webm).
   Prisma v2.5 transcribes it (hi-IN handles Hinglish). A Groq LLM
   (gpt-oss-20b) classifies what you meant — it understands Devanagari,
   Roman Hinglish, and multi-intent lines ("haan, available hoon, address
   bhi sahi hai") — with the keyword matcher as fallback if the LLM is
   down. A state machine decides the next agent line — greeting →
   availability → address → closing, three turns by design — and Timbre
   v2.5 speaks it back (voice Pranav). **The phone is always listening: no button to
   tap.** A volume monitor (AnalyserNode) detects when you start speaking,
   records until 1.5s of silence, sends the clip, and goes back to listening
   when the agent finishes. **Barge-in:** if you speak while the agent is
   still talking, the audio stops mid-sentence and it listens to you.
   (Echo guard: browser echo cancellation + a higher volume bar for
   interrupting; headphones make it bulletproof.) Guardrails are hardcoded
   (never asks for OTP/PIN, discloses it is automated, ends politely on
   anger/human requests).
4. **The outcome** — when the call ends, the transcript is turned into a
   strict JSON outcome (Pydantic): CONFIRMED / ADDRESS_UPDATED /
   CANCELLED_BY_CUSTOMER / RESCHEDULED / WRONG_PERSON / CALLBACK_REQUESTED /
   NEEDS_REVIEW, with confidence, corrected address (pincode by regex,
   landmark from "near …"), and the full transcript. Stored in SQLite,
   shown on the dashboard and on the store order page.

## Tonight — first call (~30 min, Sun 8 Nov)

1. Go to **app.gnani.ai → API Keys → generate a key**. (Console already
   live, 5,000/5,000 credits confirmed 6 Nov. Don't paste the key in chat.)
2. Go to **console.groq.com → API Keys → generate a key** (free tier).
   This powers the intent understanding — without it the keyword matcher
   still works, but Devanagari + natural speech is much weaker.
3. `cp .env.example .env` and paste both keys in `.env`. Never commit `.env`.
3. `pip install -r requirements.txt`
4. `python test_api.py` — TTS writes `test_reply.wav`. Play it: if you hear
   Hinglish, the key works. Then record a `sample.wav` on your phone, drop it
   here, re-run: STT prints the transcript. Both green = the app will work.
5. Run both servers (two terminals, from the project root):
   ```bash
   cd verifycod && uvicorn app:app --reload --port 8000
   cd store && uvicorn app:app --reload --port 8001
   ```
6. Open http://127.0.0.1:8001 — add the Kurta to the cart, place the COD
   order, answer the phone when it rings, and just speak — no button to
   tap, the phone is always listening. Interrupt the agent mid-sentence
   to test barge-in.

## Tomorrow — test the 5 paths (Mon 9 Nov, ~3h)

In the store, place an order and try each path on the phone:
1. **Confirm** — answer "haan, sahi hai" all the way → CONFIRMED, 0.95.
2. **Correct the address** — "address badlo", then speak a new address
   with a pincode → ADDRESS_UPDATED, pincode + landmark parsed.
3. **Cancel** — "nahi chahiye" → CANCELLED_BY_CUSTOMER.
4. **Reschedule** — "kal bhej do" → RESCHEDULED. (And "baad mein call
   karo" → CALLBACK_REQUESTED, not reschedule — that was a real bug,
   fixed by checking callback phrases first.)
5. **Wrong person** — "main Ramesh nahi" → WRONG_PERSON.
Then: push to GitHub (repo: github.com/Shahjan00/VerifyCOD, short human
commit messages, `.env` stays out — `.gitignore` already covers it).

## Tuesday — demo + submit (Tue 10 Nov)

1. Morning: record the 60-sec demo — buy the Kurta, answer the phone,
   confirm the order, show the outcome JSON.
2. Post it on LinkedIn/X from your phone with
   `#GreatIndianAIInternshipChallenge #GnaniAI` (no bought engagement —
   it disqualifies).
3. Submit via the form in your email by **11:59 PM IST**.

## Tech stack

- **Backend:** FastAPI (Python), SQLAlchemy ORM (SQLite now, Postgres via `DATABASE_URL`)
- **STT:** Gnani Prisma v2.5 — `gnani-vachana` SDK 0.9.0
- **TTS:** Gnani Timbre v2.5 — same SDK, voice Pranav, language hi-IN
- **Frontend:** plain HTML + vanilla JS, mic encoded as WAV in the browser
- **Dialog:** Python state machine + Groq LLM intent (gpt-oss-20b, JSON mode) with keyword fallback
- **Outcome:** Pydantic strict JSON

## What is NOT in this demo (next steps)

Real telephony (Exotel/Twilio), Postgres, Shopify adapter, risk
scoring model. The API shape (`POST /v1/orders`, webhooks, outcomes) is
designed so those slot in without changing the voice loop. Billing,
bulk orders, API keys, webhooks, and the dashboard are in as demo-grade
versions of the full spec.
