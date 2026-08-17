"""
backend/llm.py
==============
The only place this project talks to a language model.

Kept deliberately small and in one file so swapping providers means editing
this file and nothing else. Nothing here computes a financial figure — the
model only ever writes English about numbers Python already verified.

    from backend.llm import GeminiClient
    client = GeminiClient()          # reads GEMINI_API_KEY from .env
    if client.enabled:
        reply = client.generate_json("...")
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_MODEL = "gemini-2.0-flash"
API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent")
TIMEOUT_SECONDS = 20

# 503 = model overloaded, 429 = rate limited, 5xx = transient server fault.
# All are common on the free tier and all clear on their own.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2

# Numbers shorter than this appear by chance in ordinary sentences ("in 3 of
# 5 years"), so guarding them would flag everything. We check the figures
# that matter: percentages, crore amounts, ratios.
MIN_CHECKED_NUMBER_LENGTH = 3


def _load_env() -> None:
    """Read .env if python-dotenv is installed. Optional, never fatal."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def extract_numbers(text: str) -> List[str]:
    """Pull every number-like token out of a string, ignoring separators."""
    return [t.replace(",", "")
            for t in re.findall(r"\d[\d,]*\.?\d*", text)
            if len(t.replace(",", "").replace(".", "")) >= MIN_CHECKED_NUMBER_LENGTH]


class GeminiClient:
    """Minimal Gemini REST client. One POST, no SDK."""

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None) -> None:
        _load_env()
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.api_key = self.api_key.strip()
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """
        Send a prompt, get parsed JSON back. Raises on any failure so the
        caller can fall back to its own text.

        Transient errors are retried briefly; everything else fails at once,
        because retrying a bad API key only makes the user wait longer for
        the same error.
        """
        last_error: Optional[Exception] = None

        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = httpx.post(
                    API_URL.format(model=self.model),
                    headers={"x-goog-api-key": self.api_key,
                             "Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            # JSON mode: the model must return valid JSON, so
                            # we parse a structure instead of scraping prose.
                            "response_mime_type": "application/json",
                            # Zero temperature: same numbers in, same words
                            # out. An audit workpaper that reworded itself on
                            # every run would not be defensible.
                            "temperature": 0,
                            "maxOutputTokens": 500,
                        },
                    },
                    timeout=TIMEOUT_SECONDS,
                )
            except Exception as exc:
                last_error = exc
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue

            if response.status_code in RETRYABLE_STATUS:
                last_error = RuntimeError(
                    f"HTTP {response.status_code} from {self.model}")
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue

            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(
                text.strip().removeprefix("```json").removesuffix("```"))

        raise last_error or RuntimeError("Gemini request failed")
