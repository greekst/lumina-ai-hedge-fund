# -*- coding: utf-8 -*-
"""
backtest/llm_client.py — budgeted, cached Gemini calls for the Session 2 live-council test.

  * Cache key = sha256(model, system instruction, prompt, generation config). Responses are
    stored as JSON under backtest/llm_cache/ (committed: reruns are deterministic and free).
  * Hard budget: every request *sent* to the API (including retries and rate-limit errors) is
    counted in backtest/llm_cache/budget.json; a request that would exceed the cap raises.
  * Only categorical fields from responses are used downstream (hard rule 3, llm_guard).
  * Live calls require LUMINA_LLM_MODE=live and GEMINI_API_KEY; cache hits work offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "llm_cache")
BUDGET_FILE = os.path.join(CACHE_DIR, "budget.json")
CAP = 1500
MODEL = "gemini-3-flash-preview"
# Documented knowledge cutoff of MODEL: "January 2025" — Google Cloud Vertex AI model page
# https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-flash (version
# gemini-3-flash-preview). gemini-2.5-flash (same cutoff) answered 404 "no longer available to new
# users"; gemini-3.5-flash is documented as deprecated and auto-routed to a newer model, so it was
# not used. Every response's model_version is recorded and checked (no silent re-routing).
MODEL_KNOWLEDGE_CUTOFF = "2025-01-31"
EXPECTED_VERSION_PREFIX = "gemini-3-flash-preview"
MIN_INTERVAL_S = float(os.getenv("LUMINA_GEMINI_MIN_INTERVAL", "1.0"))


class BudgetExceeded(RuntimeError):
    pass


def _key(model: str, system: str, prompt: str, cfg: Dict[str, Any]) -> str:
    blob = json.dumps({"m": model, "s": system, "p": prompt, "c": cfg}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def budget() -> Dict[str, Any]:
    if os.path.exists(BUDGET_FILE):
        with open(BUDGET_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"cap": CAP, "requests_sent": 0, "ok": 0, "errors": 0, "by_purpose": {}}


def _save_budget(b: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(BUDGET_FILE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(b, fh, indent=1, sort_keys=True)


class GeminiCached:
    _last = 0.0

    def __init__(self, model: str = MODEL, temperature: float = 1.0, allow_live: Optional[bool] = None):
        self.model = model
        # Google recommends the default temperature (1.0) for Gemini 3; determinism comes from the cache.
        self.cfg = {"temperature": temperature, "response_mime_type": "application/json", "thinking_level": "low"}
        self.allow_live = (os.getenv("LUMINA_LLM_MODE") == "live") if allow_live is None else allow_live
        self._client = None
        self.hits = 0
        self.live = 0

    def _path(self, key: str) -> str:
        return os.path.join(CACHE_DIR, key[:2], key + ".json")

    def cached(self, system: str, prompt: str) -> Optional[Dict[str, Any]]:
        p = self._path(_key(self.model, system, prompt, self.cfg))
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        return None

    def generate(self, system: str, prompt: str, purpose: str) -> Dict[str, Any]:
        """Returns {"text": str, "json": dict|None, "key": str, "cached": bool}."""
        key = _key(self.model, system, prompt, self.cfg)
        p = self._path(key)
        if os.path.exists(p):
            self.hits += 1
            with open(p, encoding="utf-8") as fh:
                rec = json.load(fh)
            return dict(rec, cached=True)
        if not self.allow_live:
            raise RuntimeError("LLM response not cached and live calls not allowed (set LUMINA_LLM_MODE=live)")
        text, version = self._call(system, prompt, purpose)
        rec = {"key": key, "model": self.model, "model_version": version, "config": self.cfg, "purpose": purpose,
               "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "text": text,
               "json": _parse(text)}
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rec, fh, indent=1, sort_keys=True, ensure_ascii=False)
        return dict(rec, cached=False)

    def _call(self, system: str, prompt: str, purpose: str):
        from google import genai
        from google.genai import types
        if self._client is None:
            key = os.getenv("GEMINI_API_KEY", "")
            if not key:
                raise RuntimeError("GEMINI_API_KEY not set")
            # SDK-internal retries are disabled so that every request sent is counted here.
            self._client = genai.Client(api_key=key, http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)))
        conf = types.GenerateContentConfig(
            system_instruction=system or None, temperature=self.cfg["temperature"],
            response_mime_type=self.cfg["response_mime_type"],
            thinking_config=types.ThinkingConfig(thinking_level=self.cfg["thinking_level"]))
        last_err = None
        for attempt in range(6):
            b = budget()
            if b["requests_sent"] >= b["cap"]:
                raise BudgetExceeded(f"Gemini budget exhausted ({b['requests_sent']}/{b['cap']})")
            wait = MIN_INTERVAL_S - (time.monotonic() - GeminiCached._last)
            if wait > 0:
                time.sleep(wait)
            GeminiCached._last = time.monotonic()
            b["requests_sent"] += 1
            b["by_purpose"][purpose] = b["by_purpose"].get(purpose, 0) + 1
            _save_budget(b)
            self.live += 1
            try:
                res = self._client.models.generate_content(model=self.model, contents=prompt, config=conf)
                b = budget()
                b["ok"] += 1
                _save_budget(b)
                version = str(getattr(res, "model_version", "") or "")
                if version and not version.startswith(EXPECTED_VERSION_PREFIX):
                    raise RuntimeError(f"served model_version {version!r} != requested {self.model!r} (re-routed)")
                return (res.text or "").strip(), version
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                b = budget()
                b["errors"] += 1
                _save_budget(b)
                last_err = e
                msg = str(e)
                m = re.search(r"retry in ([0-9.]+)s|'retryDelay': '([0-9]+)s'", msg)
                delay = float(next(g for g in m.groups() if g)) if m else 5.0 * (attempt + 1)
                if any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "DEADLINE")):
                    if "PerDay" in msg or "per day" in msg.lower():
                        raise RuntimeError(f"Gemini daily quota exhausted: {msg[:300]}") from e
                    time.sleep(min(90.0, delay + 1.0))
                    continue
                raise
        raise RuntimeError(f"Gemini call failed after retries: {str(last_err)[:300]}")


def _parse(text: str) -> Optional[Dict[str, Any]]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None
