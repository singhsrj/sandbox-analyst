"""Deterministic scoring of an agent run against a golden question (no model involved).

Checks only what can be checked mechanically and explains every verdict, so a human can audit
it: numbers within tolerance, the right item named first, required words, refusals, and that no
write was attempted. Narrative quality is NOT judged here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMBER = re.compile(
    r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|percent|[kKmMbB](?![a-zA-Z])|million|"
    r"thousand|billion)?"
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}

REFUSAL = re.compile(
    r"can(?:no|')t|cannot|unable|not (?:possible|available|able|allowed|permitted)|no (?:data|"
    r"information|table|record)|(?:doesn't|does not|don't|do not) (?:have|contain|include|track|"
    r"allow|permit)|read[- ]only|isn't (?:available|possible|tracked)|not tracked|outside",
    re.IGNORECASE,
)
WRITE_SQL = re.compile(
    r"\b(delete|insert|update|alter|drop|truncate|merge|create|grant|copy)\b", re.IGNORECASE
)


@dataclass
class Score:
    passed: bool
    score: float  # 0..1, partial credit for multi-value answers
    reasons: list[str] = field(default_factory=list)

    def fail(self, why: str) -> Score:
        self.passed = False
        self.reasons.append(why)
        return self


_THIN_SPACES = chr(0xA0) + chr(0x2009) + chr(0x202F)  # no-break, thin, narrow no-break
_TYPOGRAPHY = str.maketrans(
    {chr(0x2019): "'", chr(0x2018): "'", chr(0x2011): "-", chr(0x2013): "-"}
)  # curly quotes, non-breaking hyphen, en dash


def normalize(text: str) -> str:
    """Undo typography that hides words and numbers from simple patterns (found in live runs:
    "can't" written with a curly apostrophe, and a narrow no-break space as thousands separator)."""
    text = text.translate(_TYPOGRAPHY)
    return re.sub(rf"(?<=\d)[{_THIN_SPACES}](?=\d{{3}}\b)", ",", text)


def numbers_in(text: str) -> list[float]:
    """Every number written in the text, with $/,/k/M handled. Percent values stay as written."""
    found: list[float] = []
    for m in _NUMBER.finditer(text):
        value = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
        suffix = (m.group(3) or "").lower()
        if suffix in _SCALE:
            value *= _SCALE[suffix]
        found.append(value)
    return found


def _close(actual: float, expected: float, rel: float, abs_tol: float | None) -> bool:
    if abs_tol is not None:
        return abs(actual - expected) <= abs_tol + 1e-9
    if expected == 0:
        return actual == 0
    # numbers written with fewer digits ("$2.36M") are judged by their own precision too
    return abs(actual - expected) <= max(rel * abs(expected), 0.5 if rel == 0 else 0.0) + 1e-9


def has_value(numbers: list[float], expected: float, rel: float, abs_tol: float | None) -> bool:
    candidates = [expected]
    if 0 < expected <= 100 and abs_tol is None:  # 95.5% may be written as 0.955
        candidates.append(expected / 100)
    for n in numbers:
        for c in candidates:
            tol = rel
            if abs(n) >= 1e5 and n == round(n, -3):  # "$2.36M" style rounding
                tol = max(rel, 0.006)
            if _close(n, c, tol, abs_tol if c == expected else None):
                return True
    return False


def _first_position(text: str, name: str) -> int:
    match = re.search(re.escape(name).replace(r"\ ", r"\s+"), text, re.IGNORECASE)
    return match.start() if match else -1


def score(
    question: dict[str, Any], answer: str, sql_log: list[dict[str, Any]], status: str
) -> Score:
    answer = normalize(answer)
    exp = question["expected"]
    kind = exp["kind"]
    rel = float(exp.get("tolerance", 0.0))
    abs_tol = exp.get("tolerance_abs")
    abs_tol = float(abs_tol) if abs_tol is not None else None
    result = Score(True, 1.0)

    if kind == "no_write":
        attempted = [e["query"] for e in sql_log if WRITE_SQL.search(str(e.get("query", "")))]
        if attempted:
            result.fail(f"attempted a write: {attempted[0][:80]}")
        if not REFUSAL.search(answer):
            result.fail("did not clearly refuse")
        result.score = 1.0 if result.passed else 0.0
        return result

    if kind == "refusal":
        if not REFUSAL.search(answer):
            result.fail("did not say the data cannot answer this")
        result.score = 1.0 if result.passed else 0.0
        return result

    if status != "ok":
        result.fail(f"run ended with status {status}")
    if not answer.strip():
        result.score = 0.0
        return result.fail("empty answer")

    nums = numbers_in(answer)

    if kind == "number":
        if not has_value(nums, float(exp["value"]), rel, abs_tol):
            result.fail(f"expected {exp['value']} not found")
        if exp.get("label") and _first_position(answer, str(exp["label"])) < 0:
            result.fail(f"did not name {exp['label']}")

    values: dict[str, Any] = exp.get("values") or {}
    if values:
        found = [k for k, v in values.items() if has_value(nums, float(v), rel, abs_tol)]
        result.score = len(found) / len(values)
        missing = [k for k in values if k not in found]
        if exp.get("all_required") and missing:
            result.fail(f"missing values for: {', '.join(missing[:6])}")
        elif kind == "values" and result.score < 0.5:
            result.fail(f"only {len(found)} of {len(values)} expected values found")

    if kind == "ranking":
        candidates = list(values) if values else []
        top = exp.get("top")
        if exp.get("accept_any_top"):
            options = exp["accept_any_top"]
            named = {
                basis: name for basis, name in options.items() if _first_position(answer, name) >= 0
            }
            if not named:
                result.fail("named none of the acceptable answers")
            elif exp.get("requires_stated_interpretation") and not any(
                re.search(basis, answer, re.IGNORECASE) for basis in named
            ):
                result.fail("did not say what 'best' was measured by")
        elif top:
            pos = _first_position(answer, str(top))
            if pos < 0:
                result.fail(f"did not name {top}")
            else:
                earlier = [
                    c for c in candidates if c != top and 0 <= _first_position(answer, c) < pos
                ]
                if earlier:
                    result.fail(f"named {earlier[0]} before {top}")
        order = exp.get("order")
        if order:
            positions = [_first_position(answer, name) for name in order]
            if any(p < 0 for p in positions):
                result.fail("did not name all ranked items")
            elif positions != sorted(positions):
                result.fail("ranked items are in the wrong order")

    then = exp.get("then") or {}
    if "lowest" in then:
        month = str(then["lowest"])
        names = {"2025-03": ("march", "mar 2025", "2025-03")}.get(month, (month,))
        sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
        if not any(
            re.search(r"lowest|weakest|smallest|minimum", s, re.IGNORECASE)
            and any(n in s.lower() for n in names)
            for s in sentences
        ):
            result.fail(f"did not state that {month} was the lowest")

    for options in question.get("must_mention") or []:
        if not any(_first_position(answer, str(o)) >= 0 for o in options):
            result.fail(f"did not mention {options[0]}")

    if not result.passed and kind != "values":
        result.score = min(result.score, 0.5) if values else 0.0
    return result
