import os
import pytest
from pydantic import ValidationError

from src.config.settings import Settings


def _base_env(**overrides):
    env = {
        "GEMINI_API_KEY": "fake",
        "SERPAPI_API_KEY": "fake",
    }
    env.update(overrides)
    return env


class TestJwtSecretValidation:
    def test_rejects_a_short_key(self, monkeypatch):
        for k, v in _base_env(JWT_SECRET_KEY="short_key").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings()

    def test_rejects_known_placeholder_values(self, monkeypatch):
        for k, v in _base_env(JWT_SECRET_KEY="generate_a_long_random_secret_here").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValidationError, match="placeholder"):
            Settings()

    def test_rejects_placeholder_regardless_of_case_or_surrounding_whitespace(self, monkeypatch):
        for k, v in _base_env(JWT_SECRET_KEY="  CHANGEME  ").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValidationError, match="placeholder"):
            Settings()

    def test_accepts_a_strong_random_key(self, monkeypatch):
        strong_key = "a" * 40
        for k, v in _base_env(JWT_SECRET_KEY=strong_key).items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert settings.jwt_secret_key == strong_key

    def test_accepts_a_key_exactly_at_the_32_character_minimum(self, monkeypatch):
        key = "b" * 32
        for k, v in _base_env(JWT_SECRET_KEY=key).items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert settings.jwt_secret_key == key

    def test_rejects_a_key_one_character_under_the_minimum(self, monkeypatch):
        for k, v in _base_env(JWT_SECRET_KEY="c" * 31).items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings()
