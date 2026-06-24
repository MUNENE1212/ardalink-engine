"""Azure OpenAI client using lightweight native HTTP requests.

All heavy text synthesis, context tagging, and secondary predictive analysis are
routed to the organisation's hosted Azure GPT-4o deployment to leverage Azure
credits and keep server compute costs near zero. Configuration is read from
standard environment variables (see :mod:`src.config`).
"""

from __future__ import annotations

import json
from typing import Any

import requests

from ..config import settings
from ..logging_config import get_logger

logger = get_logger("ardalink.ai.azure")


class AzureNotConfiguredError(RuntimeError):
    """Raised when Azure OpenAI is requested but credentials are missing."""


class AzureOpenAIError(RuntimeError):
    """Raised when the Azure OpenAI request fails."""


def is_configured() -> bool:
    """True when both Azure endpoint and key are present in the environment."""
    return settings.azure_configured


def _chat_completions_url() -> str:
    endpoint = (settings.AZURE_OPENAI_ENDPOINT or "").rstrip("/")
    return (
        f"{endpoint}/openai/deployments/{settings.AZURE_OPENAI_DEPLOYMENT}"
        f"/chat/completions?api-version={settings.AZURE_OPENAI_API_VERSION}"
    )


def synthesize(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.2,
) -> str:
    """Send a chat completion request to Azure GPT-4o and return the text.

    Raises :class:`AzureNotConfiguredError` if credentials are missing, or
    :class:`AzureOpenAIError` if the request fails — never silently degrades.
    """
    if not is_configured():
        raise AzureNotConfiguredError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_KEY to enable AI synthesis."
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        response = requests.post(
            _chat_completions_url(),
            headers={
                "api-key": settings.AZURE_OPENAI_KEY or "",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=settings.AZURE_OPENAI_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AzureOpenAIError(f"Azure OpenAI request failed: {exc}") from exc

    if response.status_code >= 400:
        raise AzureOpenAIError(
            f"Azure OpenAI returned HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise AzureOpenAIError("Unexpected Azure OpenAI response shape.") from exc


def environmental_summary(context: dict[str, Any]) -> str:
    """Produce a concise pastoral/environmental briefing from an assessment payload."""
    system = (
        "You are a rangeland and pastoral systems analyst for Isiolo County, Kenya. "
        "Given a structured biophysical assessment, write a concise, factual briefing "
        "(3-4 sentences) for field officers. Reference energy cost, feed needs, water "
        "access, and herd condition. Do not invent figures beyond the provided data."
    )
    prompt = (
        "Summarise the following spatial-biophysical assessment as an operational "
        "briefing:\n\n" + json.dumps(context, indent=2, default=str)
    )
    return synthesize(prompt, system=system, max_tokens=350)
