from __future__ import annotations

import os

from dotenv import load_dotenv

_ENV_LOADED = False


def load_env() -> None:
    """Load `.env` once. Safe to call multiple times."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_dotenv()
    _ENV_LOADED = True


def require_env(name: str) -> str:
    """Return env var `name` or raise a RuntimeError with a clear hint."""
    load_env()
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your shell or in a local .env file."
        )
    return value


def optional_env(name: str, default: str | None = None) -> str | None:
    load_env()
    return os.environ.get(name, default)
