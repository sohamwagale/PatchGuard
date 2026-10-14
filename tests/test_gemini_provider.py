"""Unit tests for Google Gemini LLM provider."""

import os
import pytest

from patchguard.llm import GeminiProvider, calculate_cost


def test_gemini_provider_init_with_key():
    provider = GeminiProvider(api_key="test_gemini_key_123", model="gemini-1.5-flash")
    assert provider.api_key == "test_gemini_key_123"
    assert provider.model == "gemini-1.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_gemini_provider_reads_env_vars(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env_gemini_key_456")
    provider = GeminiProvider()
    assert provider.api_key == "env_gemini_key_456"
    assert provider.model == "gemini-1.5-flash"


def test_gemini_provider_reads_google_api_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "env_google_key_789")
    provider = GeminiProvider()
    assert provider.api_key == "env_google_key_789"


def test_gemini_provider_missing_key_raises_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Missing Gemini API key"):
        GeminiProvider(api_key="")


def test_gemini_pricing_rates():
    # 1,000,000 prompt tokens + 1,000,000 completion tokens on gemini-1.5-flash
    cost = calculate_cost("gemini-1.5-flash", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert round(cost, 2) == round(0.075 + 0.30, 2)
