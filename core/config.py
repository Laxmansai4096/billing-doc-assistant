"""Configuration helpers and environment validation for production readiness."""
import os
from typing import Optional


def get_api_key() -> Optional[str]:
    return os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")


def get_model_name() -> str:
    return os.getenv("CHAT_MODEL", "gpt-4o-mini")


def get_ocr_dpi() -> int:
    try:
        return int(os.getenv("OCR_DPI", "150"))
    except ValueError:
        return 150


def get_ocr_retries() -> int:
    try:
        return int(os.getenv("OCR_RETRY_COUNT", "2"))
    except ValueError:
        return 2


def get_log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO")


def validate_env(raise_on_missing: bool = True) -> bool:
    """Validate required environment variables for LLM access.

    Returns True if valid (API key present). If raise_on_missing is True,
    raises RuntimeError when missing.
    """
    api = get_api_key()
    if not api:
        if raise_on_missing:
            raise RuntimeError("No API key found. Set AZURE_OPENAI_API_KEY or OPENAI_API_KEY in environment or .env file.")
        return False
    return True
