"""
/agents/llm_client.py
=====================
Unified LLM text-generation client with provider switching + retry/backoff.

Why this exists:
    The pipeline's LLM narration (Stage 3 risk explanations, route rationale) was
    hard-wired to Google Gemini, whose free tier frequently returns transient
    503 UNAVAILABLE ("high demand") and 429 RESOURCE_EXHAUSTED (quota) errors.
    The old code made a SINGLE attempt and fell straight to a template on any
    error, so users saw fallback text far more often than necessary.

    This module:
      1. Lets you switch providers via the LLM_PROVIDER env var:
           "groq"   — Groq Cloud, FREE tier, fast, generous limits (DEFAULT)
           "gemini" — Google Gemini (kept as a fallback option)
           "grok"   — xAI Grok (PAID; supported but not default)
      2. Retries transient errors (503/429/5xx/timeouts) with exponential backoff
         before giving up, so a brief overload no longer forces a fallback.
      3. Raises LLMUnavailable on final failure — callers wrap in try/except and
         fall back to a deterministic template. The pipeline NEVER crashes on LLM
         failure (unchanged contract).

    NOTE: "Groq" (groq.com, free) is a DIFFERENT company from "Grok" (x.ai, paid).
    Groq is the default here precisely because it is free with high rate limits.

Provider config (all via .env):
    LLM_PROVIDER   = groq | gemini | grok          (default: groq)

    # Groq (free) — https://console.groq.com
    GROQ_API_KEY   = <your groq key>
    GROQ_MODEL     = llama-3.3-70b-versatile

    # Gemini — https://aistudio.google.com
    GEMINI_API_KEY = <your gemini key>
    GEMINI_MODEL   = gemini-3.5-flash

    # Grok / xAI (paid) — https://console.x.ai
    XAI_API_KEY    = <your xai key>
    GROK_MODEL     = grok-3-mini

Groq and Grok are both OpenAI-API-compatible, so we reuse the already-installed
`openai` package pointed at their base URLs — no new dependency.
"""

import os
import time
import logging
import pathlib

from dotenv import load_dotenv

# Load .env from repo root so keys are available at import time (idempotent).
load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIG — all overridable via .env
# =============================================================================

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").strip().lower()

# OpenAI-compatible providers (Groq free + Grok paid). Each is reached with the
# `openai` SDK pointed at its base_url. `key_env` names the .env variable holding
# the API key for that provider.
_OPENAI_PROVIDERS: dict[str, dict] = {
    "groq": {
        "base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "key_env": "GROQ_API_KEY",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    "grok": {
        "base_url": os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"),
        "key_env": "XAI_API_KEY",
        "model": os.getenv("GROK_MODEL", "grok-3-mini"),
    },
}

# Gemini (non-OpenAI SDK) config.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# --- Retry policy ---
MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
RETRY_BASE_DELAY_S: float = float(os.getenv("LLM_RETRY_BASE_DELAY_S", "2.0"))

# Substrings that mark an error as transient (worth retrying).
_TRANSIENT_MARKERS = (
    "503", "429", "500", "502", "504",
    "unavailable", "resource_exhausted", "overloaded",
    "timeout", "timed out", "rate limit", "try again",
)


class LLMUnavailable(Exception):
    """Raised when the LLM cannot produce text (missing key or retries exhausted)."""


# =============================================================================
# LAZY CLIENT SINGLETONS
# =============================================================================

_openai_clients: dict[str, object] = {}   # provider -> OpenAI client
_gemini_client = None


def _get_openai_client(provider: str):
    """Build/cache an OpenAI-compatible client for 'groq' or 'grok'."""
    if provider not in _openai_clients:
        cfg = _OPENAI_PROVIDERS[provider]
        api_key = os.getenv(cfg["key_env"], "").strip()
        if not api_key:
            raise LLMUnavailable(
                f"{cfg['key_env']} not set in .env (required for provider={provider})"
            )
        from openai import OpenAI  # already installed; imported lazily
        _openai_clients[provider] = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    return _openai_clients[provider]


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise LLMUnavailable("GEMINI_API_KEY not set in .env (required for provider=gemini)")
        from google import genai  # imported lazily
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


# =============================================================================
# PROVIDER CALLS
# =============================================================================

def _openai_generate(provider: str, prompt: str, max_tokens: int | None) -> str:
    client = _get_openai_client(provider)
    model = _OPENAI_PROVIDERS[provider]["model"]
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def _gemini_generate(prompt: str, max_tokens: int | None) -> str:
    client = _get_gemini_client()
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return (resp.text or "").strip()


def _model_label(provider: str) -> str:
    if provider in _OPENAI_PROVIDERS:
        return _OPENAI_PROVIDERS[provider]["model"]
    return GEMINI_MODEL


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(m in s for m in _TRANSIENT_MARKERS)


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_text(
    prompt: str,
    *,
    max_tokens: int | None = None,
    provider: str | None = None,
) -> str:
    """
    Generate text from the configured LLM provider, retrying transient errors.

    Args:
        prompt:     The full prompt string.
        max_tokens: Optional output cap. Left unset by default.
        provider:   Override LLM_PROVIDER for this call ("groq" | "gemini" | "grok").

    Returns:
        The model's text response (non-empty, stripped).

    Raises:
        LLMUnavailable: if the required key is missing, or all retries fail.
                        Callers should catch this and fall back to a template.
    """
    prov = (provider or LLM_PROVIDER).strip().lower()
    if prov in _OPENAI_PROVIDERS:
        def gen(p, mt): return _openai_generate(prov, p, mt)
    elif prov == "gemini":
        gen = _gemini_generate
    else:
        raise LLMUnavailable(
            f"Unknown LLM_PROVIDER '{prov}' (expected 'groq', 'gemini', or 'grok')"
        )

    model_label = _model_label(prov)
    last_exc: Exception | None = None
    attempt = 0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            text = gen(prompt, max_tokens)
            if not text:
                raise RuntimeError("empty completion returned")
            return text
        except LLMUnavailable:
            raise  # missing key — retrying won't help
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES and _is_transient(exc):
                delay = RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
                logger.warning(
                    "[LLM:%s/%s] attempt %d/%d failed (%s). Retrying in %.0fs.",
                    prov, model_label, attempt, MAX_RETRIES, str(exc)[:100], delay,
                )
                time.sleep(delay)
                continue
            break

    raise LLMUnavailable(
        f"{prov}/{model_label} failed after {attempt} attempt(s): {last_exc}"
    )


def llm_status() -> dict:
    """Return the active provider/model and whether its key is present (diagnostics)."""
    prov = LLM_PROVIDER
    if prov in _OPENAI_PROVIDERS:
        cfg = _OPENAI_PROVIDERS[prov]
        return {
            "provider": prov,
            "model": cfg["model"],
            "key_present": bool(os.getenv(cfg["key_env"], "").strip()),
        }
    return {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "key_present": bool(os.getenv("GEMINI_API_KEY", "").strip()),
    }
