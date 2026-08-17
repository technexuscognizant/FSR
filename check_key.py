"""Run this to confirm your Gemini key is wired up: python check_key.py"""
import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    raise SystemExit("python-dotenv is missing.  pip install python-dotenv")

key = os.getenv("GEMINI_API_KEY", "").strip()
if not key or key == "your_key_here":
    raise SystemExit("GEMINI_API_KEY not found. Is the file named exactly .env "
                     "and in the project root (next to requirements.txt)?")
print(f"Key found: {key[:6]}...{key[-4:]}  (model {os.getenv('GEMINI_MODEL','gemini-2.0-flash')})")

import httpx
r = httpx.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{os.getenv('GEMINI_MODEL','gemini-2.0-flash')}:generateContent",
    headers={"x-goog-api-key": key},
    json={"contents": [{"parts": [{"text": "Reply with the single word: working"}]}]},
    timeout=20,
)
print("HTTP", r.status_code)
print(r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
      if r.status_code == 200 else r.text[:400])