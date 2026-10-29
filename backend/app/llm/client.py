"""One shared LLM client for every feature.

Every squad gets the same behaviour for free: retries with backoff, a timeout, a fallback
model, structured output, prompt versioning, and telemetry through callbacks.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from app.config import get_settings

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


# Errors that should switch to the fallback model. BudgetExceeded is deliberately not here.
FALLBACK_ON = (anthropic.APIError, OutputParserException, ValidationError)


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured. Callers switch to their non-AI fallback."""


def _model(name: str) -> ChatAnthropic:
    s = get_settings()
    return ChatAnthropic(
        model=name,
        api_key=s.anthropic_api_key,
        max_tokens=4096,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,  # exponential backoff on 429/5xx inside the SDK
    )


def _require_key() -> None:
    if not get_settings().llm_enabled:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")


def structured(schema: type, *, name: str) -> Runnable:
    """Primary model -> fallback model, both forced to return `schema`."""
    _require_key()
    s = get_settings()
    primary = (
        _model(s.primary_model)
        .with_structured_output(schema, method="json_schema")
        .with_config(run_name=name)
    )
    backup = (
        _model(s.fallback_model)
        .with_structured_output(schema, method="json_schema")
        .with_config(run_name=f"{name}:fallback")
    )
    return primary.with_fallbacks([backup], exceptions_to_handle=FALLBACK_ON)


def with_tools(tools: list, *, name: str) -> Runnable:
    _require_key()
    s = get_settings()
    primary = _model(s.primary_model).bind_tools(tools).with_config(run_name=name)
    backup = _model(s.fallback_model).bind_tools(tools).with_config(run_name=f"{name}:fallback")
    return primary.with_fallbacks([backup], exceptions_to_handle=FALLBACK_ON)


@lru_cache
def prompt(name: str) -> tuple[str, str]:
    """Load a versioned prompt file. Returns (version, text).

    Files look like `extraction.md` with a first line `version: 3`.
    The version is attached to every trace, so a quality change can be tied to a prompt change.
    """
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = text.partition("\n")
    version = first.split(":", 1)[1].strip() if first.startswith("version:") else "0"
    return f"{name}@{version}", body.strip()
