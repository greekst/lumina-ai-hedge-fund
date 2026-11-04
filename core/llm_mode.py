# -*- coding: utf-8 -*-
"""
Central LLM access policy for Lumina.

LUMINA_LLM_MODE:
  live  - real Gemini calls (requires a key)
  mock  - deterministic, seeded, offline responses (tests, CI, backtests)
  off   - no LLM at all; callers take their deterministic fallback path
If unset: "live" when a key is configured, otherwise "off".

Hard rule 3 ("models reason, software calculates"): whatever an LLM returns,
numeric fields must pass through core.ai_hedge_fund.llm_guard before use.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Optional

MOCK_KEY = "mock-llm-key"
VALID_MODES = ("live", "mock", "off")


def _settings_key() -> str:
    try:
        from core.state_manager import load_app_settings
        cfg = load_app_settings() or {}
    except Exception:
        cfg = {}
    # Upstream bug: settings default wrote "gemini_api_key" but every caller read "google_api_key".
    return (cfg.get("google_api_key") or cfg.get("gemini_api_key") or "").strip()


def get_llm_mode() -> str:
    mode = os.getenv("LUMINA_LLM_MODE", "").strip().lower()
    if mode in VALID_MODES:
        return mode
    return "live" if (_settings_key() or os.getenv("GEMINI_API_KEY", "").strip()) else "off"


def get_llm_api_key() -> str:
    """Key for genai clients. Returns MOCK_KEY in mock mode and "" in off mode."""
    mode = get_llm_mode()
    if mode == "off":
        return ""
    if mode == "mock":
        return MOCK_KEY
    return _settings_key() or os.getenv("GEMINI_API_KEY", "").strip()


def is_mock() -> bool:
    return get_llm_mode() == "mock"


# ---------------------------------------------------------------------------
# Deterministic mock client (mirrors the subset of google.genai used here)
# ---------------------------------------------------------------------------

_CATEGORICAL_DEFAULTS = {
    "stance": "NEUTRAL",
    "final_stance": "HOLD",
    "verdict": "APPROVED",
    "risk_level": "MODERATE",
    "is_quarantined": False,
    "sentiment": "NEUTRAL",
}


def _seed(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def mock_response_text(prompt: str) -> str:
    """Deterministic response for a prompt. If the prompt contains a JSON template,
    returns JSON with the same keys; numeric slots get 0 (they are stripped by llm_guard)."""
    seed = _seed(prompt)
    keys = re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', prompt)
    if not keys:
        return f"[MOCK LLM {seed}] Deterministic placeholder text; no model was called."
    out: Dict[str, Any] = {}
    for k in dict.fromkeys(keys):  # ordered unique
        if k in _CATEGORICAL_DEFAULTS:
            out[k] = _CATEGORICAL_DEFAULTS[k]
        elif re.search(rf'"{k}"\s*:\s*[-0-9]', prompt) or re.search(rf'"{k}"\s*:\s*[^"\n]*(数値|整数|0から|0〜100)', prompt):
            out[k] = 0
        else:
            out[k] = f"[MOCK LLM {seed}] {k}"
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


class _MockResponse:
    def __init__(self, text: str):
        self.text = text


class _MockModels:
    def generate_content(self, model: str = "", contents: Any = "", config: Any = None, **_: Any) -> _MockResponse:
        prompt = contents if isinstance(contents, str) else json.dumps(contents, default=str, sort_keys=True)
        sys_inst = getattr(config, "system_instruction", None) or ""
        return _MockResponse(mock_response_text(f"{sys_inst}\n{prompt}"))


class MockGenAIClient:
    def __init__(self, *_: Any, **__: Any):
        self.models = _MockModels()


def make_genai_client(api_key: Optional[str] = None):
    """Factory replacing direct `genai.Client(api_key=...)` construction."""
    mode = get_llm_mode()
    if mode == "mock":
        return MockGenAIClient()
    if mode == "off" or not api_key:
        raise RuntimeError("LLM disabled (LUMINA_LLM_MODE=off or no key)")
    from google import genai
    return genai.Client(api_key=api_key)
