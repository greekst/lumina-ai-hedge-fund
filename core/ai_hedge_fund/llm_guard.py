# -*- coding: utf-8 -*-
"""
llm_guard.py — enforces Hard rule 3: "Models reason, software calculates."

LLMs may only contribute *categorical* judgements (stance, verdict, risk level,
quarantine flag) and prose. Every number that reaches a score, signal, position
size, stop or report is produced here, deterministically, from those categories
or from data. Raw LLM numbers are kept only under `llm_raw_*` keys for audit and
must never be read by decision code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Deterministic ordinal mapping of analyst stances (documented, not learned).
STANCE_SCORE: Dict[str, int] = {
    "BULLISH": 80,
    "ACCUMULATE": 65,
    "NEUTRAL": 50,
    "CAUTION": 40,
    "BEARISH": 25,
}
VALID_STANCES = tuple(STANCE_SCORE)

FINAL_STANCES = ("STRONG_BUY", "BUY", "HOLD", "REDUCE", "STRONG_SELL")
CRO_VERDICTS = ("APPROVED", "REQUIRE_REDEBATE")
RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "EXTREME")


def _norm(value: Any, allowed: tuple, default: str) -> str:
    v = str(value or "").strip().upper()
    return v if v in allowed else default


def sanitize_agent_output(result: Dict[str, Any]) -> Dict[str, Any]:
    """Replace an LLM analyst's numeric score with the deterministic stance score."""
    out = dict(result or {})
    stance = _norm(out.get("stance"), VALID_STANCES, "NEUTRAL")
    if "score" in out:
        out["llm_raw_score"] = out.get("score")
    out["stance"] = stance
    out["score"] = STANCE_SCORE[stance]
    out["score_source"] = "llm_guard.STANCE_SCORE[stance]"
    return out


def sanitize_cro_verdict(llm: Optional[Dict[str, Any]], deterministic: Dict[str, Any]) -> Dict[str, Any]:
    """Keep LLM verdict/risk category + comment; numeric limits come from `deterministic`."""
    llm = llm or {}
    out = dict(deterministic)
    out["verdict"] = _norm(llm.get("verdict"), CRO_VERDICTS, deterministic.get("verdict", "APPROVED"))
    out["risk_level"] = _norm(llm.get("risk_level"), RISK_LEVELS, deterministic.get("risk_level", "MODERATE"))
    if llm.get("comment"):
        out["comment"] = str(llm["comment"])
    out["llm_raw_numbers"] = {k: llm.get(k) for k in ("max_position_size_pct", "stop_loss_pct") if k in llm}
    return out


def sanitize_cio_verdict(llm: Optional[Dict[str, Any]], deterministic: Dict[str, Any]) -> Dict[str, Any]:
    """Final numbers (conviction, allocation, stop) are always the deterministic ones.
    The LLM may only supply prose (`executive_summary`)."""
    llm = llm or {}
    out = dict(deterministic)
    if llm.get("executive_summary"):
        out["executive_summary"] = str(llm["executive_summary"])
    if llm.get("final_stance"):
        out["llm_suggested_stance"] = _norm(llm.get("final_stance"), FINAL_STANCES, "HOLD")
    out["llm_raw_numbers"] = {
        k: llm.get(k) for k in ("conviction_score", "target_allocation_pct", "stop_loss_pct") if k in llm
    }
    return out


def deterministic_debate_adjustment(bull_score: int, bear_score: int) -> int:
    """Rule replacing the LLM-chosen `adjusted_score` after a cross-debate:
    the bull score is pulled toward the bear by 10% of the spread, capped at 10 points."""
    spread = max(0, int(bull_score) - int(bear_score))
    return int(bull_score) - min(10, spread // 10)


def credibility_from_flag(is_quarantined: bool) -> int:
    """News credibility score derived from the categorical quarantine flag."""
    return 40 if is_quarantined else 80
