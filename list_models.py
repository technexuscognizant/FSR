"""
List the Gemini models your key can actually use, then try each one.

    python list_models.py

Model names change over time and vary by key, so rather than guessing,
this asks Google directly and then sends a one-word prompt to each
candidate to see which ones actually respond right now.
"""

import os

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    raise SystemExit("pip install python-dotenv")

KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not KEY:
    raise SystemExit("GEMINI_API_KEY not found in .env")

BASE = "https://generativelanguage.googleapis.com/v1beta"
HEADERS = {"x-goog-api-key": KEY}

# ── what can this key see? ───────────────────────────────────────────────────
response = httpx.get(f"{BASE}/models", headers=HEADERS, timeout=30)
if response.status_code != 200:
    raise SystemExit(f"HTTP {response.status_code}\n{response.text[:400]}")

usable = []
for model in response.json().get("models", []):
    if "generateContent" not in model.get("supportedGenerationMethods", []):
        continue
    name = model["name"].removeprefix("models/")
    usable.append(name)

print(f"\n{len(usable)} model(s) support generateContent:\n")
for name in usable:
    print(f"   {name}")

# ── which ones respond right now? ────────────────────────────────────────────
# Prefer smaller/faster models: they are cheaper on the free tier and are
# far less likely to return 503 when demand spikes.
def rank(name: str) -> tuple:
    return (
        0 if "flash-lite" in name else 1 if "flash" in name else 2,
        0 if "preview" not in name and "exp" not in name else 1,
        name,
    )


print("\nTesting the most promising ones...\n")
working = []
for name in sorted(usable, key=rank)[:6]:
    try:
        reply = httpx.post(
            f"{BASE}/models/{name}:generateContent",
            headers=HEADERS,
            json={"contents": [{"parts": [{"text": "Reply with one word: ok"}]}],
                  "generationConfig": {"maxOutputTokens": 10}},
            timeout=25,
        )
        if reply.status_code == 200:
            print(f"   WORKS      {name}")
            working.append(name)
        else:
            reason = reply.json().get("error", {}).get("status", reply.status_code)
            print(f"   {str(reason):<10} {name}")
    except Exception as exc:
        print(f"   {type(exc).__name__:<10} {name}")

if working:
    print(f"\nPut this in your .env:\n\n    GEMINI_MODEL={working[0]}\n")
else:
    print("\nNothing responded. Google may be busy — wait a few minutes and "
          "retry.\nThe project still runs without a key; narrative sections "
          "fall back to\nengine-written text.\n")