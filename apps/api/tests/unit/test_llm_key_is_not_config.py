"""The LLM key is entered in the app, not baked into the cluster.

It is registered in settings_spec, so an operator types it once into
Settings and it lands as a database override — rotatable without a redeploy
and without anyone holding a kubeconfig. That only works if the app STARTS
without it, which it previously could not: the field was required, so a
fresh install crash-looped until the secret was already in place.
"""

from __future__ import annotations

import pytest
from app.services.llm import LLMNotConfiguredError
from app.settings import SPECS, Settings

_BASE = {
    "database_url": "postgresql+asyncpg://a:b@h/d",
    "postgres_password": "x",
    "app_db_password": "y",
}


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer shell almost certainly exports LLM_API_KEY.

    Settings reads real environment variables, so without this the
    "unconfigured" cases silently test a configured one.
    """
    for var in ("LLM_API_KEY", "LLM_EMBEDDING_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_the_app_starts_with_no_llm_key() -> None:
    s = Settings(_env_file=None, **_BASE)
    assert s.llm_api_key.get_secret_value() == ""
    assert s.llm_is_configured() is False


def test_a_key_that_is_present_reads_as_configured() -> None:
    s = Settings(_env_file=None, llm_api_key="sk-real", **_BASE)
    assert s.llm_is_configured() is True


@pytest.mark.parametrize("blank", ["", "   "])
def test_whitespace_is_not_a_key(blank: str) -> None:
    """Clearing the field in the UI stores "", which must read as unset."""
    s = Settings(_env_file=None, llm_api_key=blank, **_BASE)
    assert s.llm_is_configured() is False


def test_the_placeholder_is_still_rejected() -> None:
    """Empty means "not yet". 'changeme' means someone thought they were
    done, and fails later and further from the cause."""
    with pytest.raises(ValueError, match="changeme"):
        Settings(_env_file=None, llm_api_key="changeme", **_BASE)


def test_the_key_is_enterable_from_the_settings_ui() -> None:
    """If it leaves SPECS, "enter it after deployment" stops being true."""
    names = {s.name for s in SPECS}
    assert "llm_api_key" in names
    spec = next(s for s in SPECS if s.name == "llm_api_key")
    assert spec.kind == "secret", "must be masked in the UI"


def test_calling_the_model_unconfigured_says_so() -> None:
    """Not an upstream 401, which reads as an outage rather than setup."""
    assert issubclass(LLMNotConfiguredError, RuntimeError)
