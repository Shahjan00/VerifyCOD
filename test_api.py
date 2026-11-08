"""First Gnani API call — run this before the app, it proves the key works.

    python test_api.py

1. TTS: synthesises the VerifyCOD agent greeting with Timbre v2.5
   -> test_reply.wav (no audio file needed, so this always runs first).
2. STT: if a file called sample.wav is in this folder, transcribes it
   with Prisma v2.5. Record one on your phone, save as sample.wav, re-run.

Needs GNANI_API_KEY in .env (copy .env.example to .env first).
Never paste the key in chat, and never commit .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("GNANI_API_KEY", "").strip()
if not KEY:
    raise SystemExit("GNANI_API_KEY missing — copy .env.example to .env and add your key.")

from gnani.stt import GnaniSTTClient  # noqa: E402
from gnani.tts import GnaniTTSClient  # noqa: E402

tts = GnaniTTSClient(api_key=KEY)
audio = tts.synthesize(
    "Namaste, I'm calling from StyleKart about your order of a Cotton Kurta, "
    "worth 1299 rupees. Am I speaking with Ramesh Patel?",
    voice="Pranav",
    model="timbre-v2.5",
    language="hi-IN",
)
Path("test_reply.wav").write_bytes(audio)
print(f"TTS OK — Timbre v2.5, {len(audio)} bytes -> test_reply.wav (play it)")

sample = Path("sample.wav")
if sample.exists():
    stt = GnaniSTTClient(api_key=KEY)
    result = stt.transcribe(str(sample), language_code="hi-IN", model="prisma-v2.5")
    print("STT OK — Prisma v2.5 transcript:", result.get("transcript"))
else:
    print("STT skipped — no sample.wav here. Record one, save as sample.wav, re-run.")
print("Both calls use the same key. If this passes, the app will work.")
