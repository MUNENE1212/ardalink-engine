"""Azure OpenAI integration for heavy AI analytical tasks."""

from .azure_client import (
    AzureNotConfiguredError,
    AzureOpenAIError,
    environmental_summary,
    is_configured,
    synthesize,
)

__all__ = [
    "AzureNotConfiguredError",
    "AzureOpenAIError",
    "environmental_summary",
    "is_configured",
    "synthesize",
]
