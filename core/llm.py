"""Groq client wrapper with exponential backoff and structured JSON output."""
from __future__ import annotations

import json
import os
import time

from groq import Groq
from groq import RateLimitError, APIStatusError

_RETRYABLE = (RateLimitError,)
_MAX_RETRIES = 5
_BASE_DELAY = 2.0  # seconds
# Model choice: llama-3.3-70b-versatile (default)
# This model produces the best synthesis and citation quality on Groq's free tier.
# If you hit rate limits (429s) during eval runs, switch to llama-3.1-8b-instant —
# it runs on a separate rate-limit pool and is practical for batch runs at the cost
# of weaker reasoning. mixtral-8x7b-32768 was a prior option but has been
# decommissioned by Groq.
_MODEL = "llama-3.3-70b-versatile"


def _get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key "
            "(free tier at console.groq.com)."
        )
    return Groq(api_key=api_key)


def _call_with_retry(client: Groq, messages: list[dict], json_mode: bool = False) -> str:
    """Call the Groq API with exponential backoff on rate-limit errors."""
    kwargs = {
        "model": _MODEL,
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except _RETRYABLE as exc:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _BASE_DELAY * (2 ** attempt)
            print(f"  [llm] rate limited, retrying in {wait:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(wait)
        except APIStatusError as exc:
            if exc.status_code == 503 and attempt < _MAX_RETRIES - 1:
                wait = _BASE_DELAY * (2 ** attempt)
                print(f"  [llm] service unavailable, retrying in {wait:.1f}s")
                time.sleep(wait)
            else:
                raise


class LLMClient:
    def __init__(self, model_name: str = _MODEL):
        self._client = _get_client()
        self._model = model_name

    def generate(self, prompt: str) -> str:
        """Free-form text generation."""
        messages = [{"role": "user", "content": prompt}]
        return _call_with_retry(self._client, messages, json_mode=False)

    def generate_json(self, prompt: str) -> dict:
        """Generate and parse a JSON response."""
        messages = [{"role": "user", "content": prompt}]
        raw = _call_with_retry(self._client, messages, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(cleaned)
