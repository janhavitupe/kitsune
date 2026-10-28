from functools import lru_cache

from openai import OpenAI

from app.config import settings


class AIUnavailable(RuntimeError):
    pass


@lru_cache
def model_api() -> OpenAI:
    """Client for the Meta Model API. The SDK doesn't read MODEL_API_KEY itself, so pass it explicitly."""
    if not settings.model_api_key:
        raise AIUnavailable("MODEL_API_KEY is not set")
    return OpenAI(base_url=settings.model_api_base_url, api_key=settings.model_api_key, timeout=60, max_retries=1)


@lru_cache
def openweights() -> OpenAI:
    """Client for the self-hosted open-weights endpoint (Baseten, or Fireworks as fallback)."""
    if not (settings.openweights_base_url and settings.openweights_api_key):
        raise AIUnavailable("OPENWEIGHTS_BASE_URL / OPENWEIGHTS_API_KEY are not set")
    return OpenAI(
        base_url=settings.openweights_base_url, api_key=settings.openweights_api_key, timeout=60, max_retries=1
    )
