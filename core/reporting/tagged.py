# -*- coding: utf-8 -*-
"""
Tagged values — Hard rule 5: every number in a report carries `source` and `as_of`,
and is explicitly a SOURCED FACT or a MODEL ASSUMPTION.

    Tagged(24.1, source="yfinance", as_of="2026-11-03", label="P/E")
      -> "P/E 24.1 [SOURCED FACT · yfinance, 2026-11-03]"
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional

SOURCED_FACT = "SOURCED FACT"
MODEL_ASSUMPTION = "MODEL ASSUMPTION"
KINDS = (SOURCED_FACT, MODEL_ASSUMPTION)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Tagged:
    value: Optional[float]
    source: str
    as_of: str
    kind: str = SOURCED_FACT
    label: str = ""
    unit: str = ""
    decimals: int = 2

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not self.source or not str(self.source).strip():
            raise ValueError(f"{self.label or 'value'}: missing source")
        if not self.as_of or not _DATE.match(str(self.as_of)):
            raise ValueError(f"{self.label or 'value'}: as_of must start with YYYY-MM-DD, got {self.as_of!r}")
        if self.value is not None and not isinstance(self.value, (int, float)):
            raise TypeError(f"{self.label}: value must be numeric or None")

    @property
    def tag(self) -> str:
        return f"[{self.kind} · {self.source}, {str(self.as_of)[:10]}]"

    def fmt_value(self) -> str:
        if self.value is None or (isinstance(self.value, float) and not math.isfinite(self.value)):
            return "n/a"
        return f"{self.value:,.{self.decimals}f}{self.unit}"

    def render(self, with_label: bool = True) -> str:
        body = f"{self.fmt_value()} {self.tag}"
        return f"{self.label} {body}" if (with_label and self.label) else body


def fact(value: Any, source: str, as_of: str, label: str = "", unit: str = "", decimals: int = 2) -> Tagged:
    return Tagged(_num(value), source, as_of, SOURCED_FACT, label, unit, decimals)


def assumption(value: Any, source: str, as_of: str, label: str = "", unit: str = "", decimals: int = 2) -> Tagged:
    return Tagged(_num(value), source, as_of, MODEL_ASSUMPTION, label, unit, decimals)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# Validation of rendered text
# ---------------------------------------------------------------------------
_TAG = r"\[(?:SOURCED FACT|MODEL ASSUMPTION) · [^\]]+?, \d{4}-\d{2}-\d{2}\]"
_VALUE = r"(?:n/a|[-+]?\d[\d,]*(?:\.\d+)?)[^\s\[\]|]{0,3}"
_TAGGED_VALUE = re.compile(_VALUE + r" " + _TAG)
_TAG_ONLY = re.compile(_TAG)
_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")


def untagged_numbers(text: str) -> list:
    """(line_no, token) for every number in a report data line that is not part of a
    `value [KIND · source, YYYY-MM-DD]` pair. Headings, fenced code, the label (first) cell
    of table rows and lines carrying `<!-- text-only -->` are skipped. Digits inside
    identifiers (e.g. ROC20) are not numbers."""
    bad = []
    in_code = False
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        nxt = lines[i].strip() if i < len(lines) else ""
        if s.startswith("|") and re.match(r"^\|\s*:?-{3,}", nxt):
            continue  # table header row (column labels)
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or s.startswith("#") or "<!-- text-only -->" in s:
            continue
        if s.startswith("|"):
            # first table cell is the code-defined label (e.g. "RSI 14", "52w high"), not data
            cells = s.strip("|").split("|")
            line = "|".join(cells[1:])
        rest = _TAG_ONLY.sub(" ", _TAGGED_VALUE.sub(" ", line))
        bad += [(i, m.group(0)) for m in _NUM.finditer(rest)]
    return bad
