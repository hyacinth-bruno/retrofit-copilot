"""Read a building profile out of an energy certificate.

Text first, vision when needed:
- PDF with a text layer -> redact PII -> send text only (cheaper, faster, and we can check
  every quote against the source).
- Scanned PDF or photo -> send the file itself to Claude (multimodal). We cannot ground the
  quotes against text, so confidence is capped and review is more likely.
- No API key or both models fail -> regex baseline on the text layer, flagged for review.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
from collections import OrderedDict

from langchain_core.messages import HumanMessage, SystemMessage
from pypdf import PdfReader

from app.config import get_settings
from app.guardrails import checks
from app.llm import client
from app.observability.tracer import Run, callbacks_for
from app.schemas import BuildingProfile, ExtractionResult, FieldEvidence, Issue

MIN_TEXT_CHARS = 200
VISION_CONFIDENCE_CAP = 0.8

_cache: OrderedDict[str, ExtractionResult] = OrderedDict()
_CACHE_SIZE = 64


def pdf_text(data: bytes, max_pages: int) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    if pages > max_pages:
        raise checks.InputRejected(f"PDF has {pages} pages; the limit is {max_pages}.")
    return "\n".join((p.extract_text() or "") for p in reader.pages), pages


# ---------- regex baseline (no AI) ----------

HEATING_WORDS = {
    "erdgas": "gas",
    "gas": "gas",
    "heizöl": "oil",
    "öl": "oil",
    "fernwärme": "district_heating",
    "wärmepumpe": "heat_pump",
    "strom": "electric",
    "holz": "biomass",
    "pellets": "biomass",
}


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)


def regex_extract(text: str) -> BuildingProfile:
    p = BuildingProfile()
    ev: list[FieldEvidence] = []

    def grab(field, pattern, convert):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return
        try:
            setattr(p, field, convert(m.group(1).strip()))
            ev.append(FieldEvidence(field=field, quote=m.group(0).strip(), confidence=0.6))
        except ValueError:
            pass

    grab("address", r"Adresse\s*:?\s*(.+)", str)
    grab("year_built", r"Baujahr Gebäude\s*:?\s*(\d{4})", int)
    grab("dwelling_units", r"Anzahl (?:der )?Wohnungen\s*:?\s*(\d+)", int)
    grab("living_area_m2", r"(?:Gebäudenutzfläche \(AN\)|Wohnfläche)\s*:?\s*([\d.,]+)\s*m", _num)
    grab(
        "final_energy_kwh_m2a",
        r"Endenergie(?:bedarf|verbrauch) dieses Gebäudes\s*:?\s*([\d.,]+)",
        _num,
    )
    grab("energy_class", r"Energieeffizienzklasse\s*:?\s*(A\+|[A-H])\b", str.upper)
    m = re.search(r"Energieträger für Heizung\s*:?\s*([\wäöü]+)", text, re.IGNORECASE)
    if m:
        p.heating_type = HEATING_WORDS.get(m.group(1).lower(), "other")  # type: ignore[assignment]
        ev.append(FieldEvidence(field="heating_type", quote=m.group(0), confidence=0.6))
    if re.search(r"Mehrfamilienhaus", text):
        p.building_type = "multi_family"
    elif re.search(r"(Ein|Zwei)familienhaus", text):
        p.building_type = "single_family"
    if re.search(r"Bedarfsausweis|Endenergiebedarf dieses", text):
        p.certificate_type = "demand"
    elif re.search(r"Verbrauchsausweis|Endenergieverbrauch dieses", text):
        p.certificate_type = "consumption"
    p.evidence = ev
    return p


# ---------- main entry ----------


def extract(data: bytes, filename: str, run: Run) -> ExtractionResult:
    s = get_settings()
    digest = hashlib.sha256(data).hexdigest()
    if digest in _cache:
        cached = _cache[digest].model_copy(update={"run_id": run.id, "cached": True})
        run.event("cache_hit", kind="cache", sha256=digest[:12])
        run.needs_review = cached.needs_review
        return cached

    with run.span("input_guardrails", kind="guardrail") as sp:
        checks.check_size(data, s.max_upload_mb)
        mime = checks.sniff_type(data)
        text, pages = ("", 0)
        if mime == "application/pdf":
            text, pages = pdf_text(data, s.max_pdf_pages)
        redacted, pii = checks.redact(text)
        issues: list[Issue] = checks.injection_issues(text)
        sp.meta.update(mime=mime, pages=pages, text_chars=len(text), pii_redacted=pii)

    mode = "text" if len(text.strip()) >= MIN_TEXT_CHARS else "vision"
    profile: BuildingProfile | None = None
    model_used = None
    version, system = client.prompt("extraction")

    try:
        llm = client.structured(BuildingProfile, name="extract_profile")
        if mode == "text":
            content: list | str = (
                "Extract the building profile from this certificate.\n"
                f"<document>\n{redacted}\n</document>"
            )
        else:
            b64 = base64.b64encode(data).decode()
            block = (
                {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
                if mime == "application/pdf"
                else {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                }
            )
            content = [
                block,
                {"type": "text", "text": "Extract the building profile from this certificate."},
            ]
        with run.span("extract_llm", kind="step", mode=mode, prompt=version):
            profile = llm.invoke(
                [SystemMessage(system), HumanMessage(content=content)],
                config={"callbacks": callbacks_for(run), "metadata": {"prompt_version": version}},
            )
        model_used = next(
            (sp.model for sp in reversed(run.spans) if sp.kind == "llm" and sp.status == "ok"), None
        )
    except client.LLMUnavailable:
        run.event("llm_unavailable", kind="fallback")
    except Exception as exc:  # both models failed, timeout, budget
        run.event("llm_failed", kind="fallback", error=str(exc)[:200])

    if profile is None:
        run.fallback_used = True
        if text.strip():
            mode = "regex_fallback"
            profile = regex_extract(text)
            issues.append(
                Issue(
                    code="ai_fallback",
                    severity="warning",
                    message="AI extraction unavailable; used the rule-based reader. Please check the values.",
                )
            )
        else:
            mode = "none"
            profile = BuildingProfile()
            issues.append(
                Issue(
                    code="ai_unavailable",
                    severity="error",
                    message="This is a scan and AI extraction is unavailable. Please enter the values by hand.",
                )
            )

    with run.span("output_guardrails", kind="guardrail") as sp:
        issues += checks.sanity_issues(profile)
        if mode in ("text", "regex_fallback"):
            issues += checks.grounding_issues(profile, text)
            issues += checks.confidence_issues(profile, s.review_confidence_threshold)
        elif mode == "vision":
            issues += checks.grounding_issues(profile, None)
            issues += checks.confidence_issues(
                profile, s.review_confidence_threshold, cap=VISION_CONFIDENCE_CAP
            )
            issues.append(
                Issue(
                    code="vision_only",
                    severity="info",
                    message="Read from an image, so quotes could not be checked against text.",
                )
            )
        review = checks.needs_review(issues)
        sp.meta.update(issue_codes=[i.code for i in issues], needs_review=review)

    run.needs_review = review
    result = ExtractionResult(
        run_id=run.id,
        profile=profile,
        issues=issues,
        needs_review=review,
        mode=mode,
        model=model_used,
    )
    if mode in ("text", "vision"):
        _cache[digest] = result
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return result
