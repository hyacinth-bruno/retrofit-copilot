"""Guardrails around the model: what goes in, and what we let out.

Input:  file type and size, page limit, PII redaction, prompt-injection detection.
Output: schema (enforced by structured output), sanity rules, cross-field consistency,
        grounding of every extracted value in the source text, confidence thresholds.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from difflib import SequenceMatcher

from app.domain.calculators import energy_class_for
from app.schemas import CRITICAL_FIELDS, BuildingProfile, Issue

ALLOWED_TYPES = {
    b"%PDF": "application/pdf",
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"RIFF": "image/webp",
}


class InputRejected(ValueError):
    pass


def sniff_type(data: bytes) -> str:
    """Detect the real file type from its first bytes, not from the filename."""
    for magic, mime in ALLOWED_TYPES.items():
        if data.startswith(magic):
            return mime
    raise InputRejected("Unsupported file. Upload a PDF, PNG, JPEG or WebP.")


def check_size(data: bytes, max_mb: int) -> None:
    if len(data) > max_mb * 1024 * 1024:
        raise InputRejected(f"File is larger than {max_mb} MB.")
    if len(data) < 100:
        raise InputRejected("File is empty or too small to be a certificate.")


# ---------- PII ----------

PII_PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("iban", re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b")),
    ("phone", re.compile(r"(?:\+49|0)\s?\d{2,5}[\s/-]?\d{3,}[\s-]?\d{0,6}")),
    ("owner", re.compile(r"(?im)^(Eigentümer(?:in)?|Aussteller(?:in)?)\s*:?\s*(.+)$")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Remove personal data before text leaves our system. Returns (text, kinds found)."""
    found: list[str] = []
    for kind, pattern in PII_PATTERNS:
        if kind == "owner":
            text, n = pattern.subn(lambda m: f"{m.group(1)}: [REDACTED]", text)
        else:
            text, n = pattern.subn(f"[{kind.upper()}]", text)
        if n:
            found.append(kind)
    return text, found


# ---------- Prompt injection ----------

INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous |prior |above )?(instructions|rules)|disregard (the )?(above|previous)"
    r"|you are now|system prompt|ignoriere (alle|die) (anweisungen|regeln))",
    re.IGNORECASE,
)


def injection_issues(text: str) -> list[Issue]:
    if INJECTION.search(text):
        return [
            Issue(
                code="prompt_injection_suspected",
                severity="warning",
                message="The document contains text that looks like instructions to the AI. "
                "It was treated as data only; please review the result.",
            )
        ]
    return []


# ---------- Output checks ----------


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def quote_in_source(quote: str, source: str, threshold: float = 0.85) -> bool:
    """True if `quote` appears in `source`, allowing small OCR and spacing differences."""
    q, src = _norm(quote), _norm(source)
    if not q:
        return False
    if q in src:
        return True
    window = len(q)
    step = max(1, window // 4)
    best = 0.0
    for i in range(0, max(1, len(src) - window + 1), step):
        best = max(best, SequenceMatcher(None, q, src[i : i + window]).ratio())
        if best >= threshold:
            return True
    return False


def sanity_issues(p: BuildingProfile) -> list[Issue]:
    issues: list[Issue] = []
    year = dt.date.today().year

    def err(code, msg, field):
        issues.append(Issue(code=code, severity="error", message=msg, field=field))

    if p.year_built is not None and not (1800 <= p.year_built <= year):
        err("implausible_year", f"Year built {p.year_built} is not plausible.", "year_built")
    if p.living_area_m2 is not None and not (20 <= p.living_area_m2 <= 100_000):
        err("implausible_area", f"Area {p.living_area_m2} m² is not plausible.", "living_area_m2")
    if p.final_energy_kwh_m2a is not None and not (0 < p.final_energy_kwh_m2a <= 1000):
        err(
            "implausible_energy",
            f"Final energy {p.final_energy_kwh_m2a} kWh/m²a is not plausible.",
            "final_energy_kwh_m2a",
        )
    if p.dwelling_units is not None and not (1 <= p.dwelling_units <= 1000):
        err(
            "implausible_units",
            f"{p.dwelling_units} dwelling units is not plausible.",
            "dwelling_units",
        )

    if p.energy_class and p.final_energy_kwh_m2a:
        expected = energy_class_for(p.final_energy_kwh_m2a)
        if expected != p.energy_class:
            issues.append(
                Issue(
                    code="class_mismatch",
                    severity="warning",
                    message=f"Class {p.energy_class} does not match {p.final_energy_kwh_m2a} "
                    f"kWh/m²a (expected {expected}). One of the two may be misread.",
                    field="energy_class",
                )
            )
    if p.building_type == "single_family" and p.dwelling_units is not None and p.dwelling_units > 2:
        issues.append(
            Issue(
                code="type_units_mismatch",
                severity="warning",
                message="Single-family type but more than two dwelling units.",
                field="building_type",
            )
        )
    for f in CRITICAL_FIELDS:
        v = getattr(p, f)
        if v is None or v == "unknown":
            issues.append(
                Issue(
                    code="missing_field", severity="warning", message=f"{f} was not found.", field=f
                )
            )
    return issues


def grounding_issues(p: BuildingProfile, source_text: str | None) -> list[Issue]:
    """Every filled field needs evidence, and the evidence must exist in the document."""
    issues: list[Issue] = []
    by_field = {e.field: e for e in p.evidence}
    for f in (
        "year_built",
        "living_area_m2",
        "final_energy_kwh_m2a",
        "energy_class",
        "dwelling_units",
    ):
        if getattr(p, f) is None:
            continue
        ev = by_field.get(f)
        if ev is None:
            issues.append(
                Issue(
                    code="no_evidence",
                    severity="warning",
                    message=f"No evidence given for {f}.",
                    field=f,
                )
            )
        elif source_text and not quote_in_source(ev.quote, source_text):
            issues.append(
                Issue(
                    code="ungrounded",
                    severity="error",
                    message=f"The quote for {f} ('{ev.quote[:60]}') is not in the document.",
                    field=f,
                )
            )
    return issues


def confidence_issues(
    p: BuildingProfile, threshold: float, cap: float | None = None
) -> list[Issue]:
    issues = []
    for e in p.evidence:
        conf = min(e.confidence, cap) if cap is not None else e.confidence
        if e.field in CRITICAL_FIELDS and conf < threshold:
            issues.append(
                Issue(
                    code="low_confidence",
                    severity="warning",
                    message=f"Low confidence ({conf:.2f}) for {e.field}.",
                    field=e.field,
                )
            )
    return issues


def needs_review(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues) or any(
        i.code in {"low_confidence", "missing_field", "prompt_injection_suspected", "ungrounded"}
        for i in issues
    )
