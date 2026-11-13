"""
Nakeeb AI - LLM Provider Abstraction
Supports Gemini, OpenRouter, HF Inference with unified interface.
"""

from __future__ import annotations

import os
import time
import json
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from .errors import QuotaExhaustedError, AllProvidersUnavailableError, NakeebError
from .quota import QuotaManager, ProviderQuota


class LLMResponse(BaseModel):
    """Standardized LLM response."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    metadata: dict = Field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model identifier."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Make a completion request."""

    @abstractmethod
    async def verify_free_status(self, model: str) -> bool:
        """Verify model is still free (check pricing)."""

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token)."""
        return len(text) // 4


class GeminiProvider(LLMProvider):
    """Google Gemini API (AI Studio)."""

    def __init__(self, api_key: str, quota: ProviderQuota):
        self.api_key = api_key
        self.quota = quota
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return "gemini-decision-1"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                headers={"x-goog-api-key": self.api_key},
            )
        return self._client

    async def verify_free_status(self, model: str) -> bool:
        """Gemini free tier requires project verification; assume true if key works."""
        # In practice, would check API response for quota/billing errors
        return True

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = await self._get_client()
        model = model or self.default_model

        # Build request per Gemini API
        parts = []
        if system_prompt:
            parts.append({"text": system_prompt})
        parts.append({"text": prompt})

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        url = f"{self.base_url}/models/{model}:generateContent"
        start = time.perf_counter()

        try:
            response = await client.post(url, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code == 429:
                raise QuotaExhaustedError("gemini", "rate_limit")

            response.raise_for_status()
            data = response.json()

            # Extract content
            content = ""
            if "candidates" in data and data["candidates"]:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            content += part["text"]

            # Extract usage
            usage = data.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount", 0)
            output_tokens = usage.get("candidatesTokenCount", 0)

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                metadata={"usage": usage},
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise QuotaExhaustedError("gemini", "rate_limit")
            raise NakeebError(f"Gemini API error: {e.response.status_code} - {e.response.text}")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class OpenRouterProvider(LLMProvider):
    """OpenRouter API (free router)."""

    def __init__(self, api_key: str, quota: ProviderQuota):
        self.api_key = api_key
        self.quota = quota
        self.base_url = "https://openrouter.ai/api/v1"
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_id(self) -> str:
        return "openrouter"

    @property
    def default_model(self) -> str:
        return "openrouter/free"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/nakeeb-ai/nakeeb-intel",
                    "X-Title": "Nakeeb AI",
                },
            )
        return self._client

    async def verify_free_status(self, model: str) -> bool:
        """Check model pricing via OpenRouter API."""
        if not model.startswith("openrouter/"):
            return True  # Assume user knows what they're doing

        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/models/{model}")
            if response.status_code == 200:
                data = response.json()
                pricing = data.get("pricing", {})
                prompt_price = float(pricing.get("prompt", "0"))
                completion_price = float(pricing.get("completion", "0"))
                return prompt_price == 0 and completion_price == 0
        except Exception:
            pass
        return False  # Conservative: assume not free if can't verify

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = await self._get_client()
        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{self.base_url}/chat/completions"
        start = time.perf_counter()

        try:
            response = await client.post(url, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code == 429:
                raise QuotaExhaustedError("openrouter", "rate_limit")

            response.raise_for_status()
            data = response.json()

            content = ""
            if "choices" in data and data["choices"]:
                content = data["choices"][0].get("message", {}).get("content", "")

            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                metadata={"usage": usage, "model": data.get("model")},
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise QuotaExhaustedError("openrouter", "rate_limit")
            raise NakeebError(f"OpenRouter API error: {e.response.status_code} - {e.response.text}")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class HFInferenceProvider(LLMProvider):
    """Hugging Face Inference API (backup)."""

    def __init__(self, api_key: str, quota: ProviderQuota):
        self.api_key = api_key
        self.quota = quota
        self.base_url = "https://api-inference.huggingface.co"
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_id(self) -> str:
        return "hf_inference"

    @property
    def default_model(self) -> str:
        return "meta-llama/Llama-3.1-8B-Instruct"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    async def verify_free_status(self, model: str) -> bool:
        return True  # Community tier is free

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = await self._get_client()
        model = model or self.default_model

        # HF chat format
        inputs = prompt
        if system_prompt:
            inputs = f"<<SYS>>\n{system_prompt}\n<</SYS>>\n\n{prompt}"

        payload = {
            "inputs": inputs,
            "parameters": {
                "temperature": temperature,
                "max_new_tokens": max_tokens,
                "return_full_text": False,
            },
        }

        url = f"{self.base_url}/models/{model}"
        start = time.perf_counter()

        try:
            response = await client.post(url, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code == 429:
                raise QuotaExhaustedError("hf_inference", "rate_limit")

            response.raise_for_status()
            data = response.json()

            content = ""
            if isinstance(data, list) and data:
                content = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                content = data.get("generated_text", "")

            # HF doesn't always return token counts
            input_tokens = self.estimate_tokens(inputs)
            output_tokens = self.estimate_tokens(content)

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise QuotaExhaustedError("hf_inference", "rate_limit")
            raise NakeebError(f"HF Inference API error: {e.response.status_code} - {e.response.text}")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class LLMManager:
    """Manages multiple LLM providers with fallback logic."""

    def __init__(self, quota_manager: QuotaManager, env: dict[str, str]):
        self.quota = quota_manager
        self.providers: dict[str, LLMProvider] = {}
        self._initialize_providers(env)

    def _initialize_providers(self, env: dict[str, str]):
        """Create provider instances from environment."""
        # Gemini
        if gemini_key := env.get("GEMINI_API_KEY"):
            if "gemini" in self.quota.providers:
                self.providers["gemini"] = GeminiProvider(gemini_key, self.quota.providers["gemini"])

        # OpenRouter
        if or_key := env.get("OPENROUTER_API_KEY"):
            if "openrouter" in self.quota.providers:
                self.providers["openrouter"] = OpenRouterProvider(or_key, self.quota.providers["openrouter"])

        # HF Inference
        if hf_key := env.get("HF_API_KEY"):
            if "hf_inference" in self.quota.providers:
                self.providers["hf_inference"] = HFInferenceProvider(hf_key, self.quota.providers["hf_inference"])

    def get_available_providers(self, prefer: list[str] | None = None) -> list[str]:
        """Get available providers in priority order."""
        base_order = prefer or ["gemini", "openrouter", "hf_inference"]
        return [p for p in base_order if p in self.providers and p in self.quota.get_available_providers()]

    async def complete_with_fallback(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        provider_order: list[str] | None = None,
    ) -> LLMResponse:
        """Try providers in order until one succeeds."""
        available = self.get_available_providers(provider_order)

        if not available:
            raise AllProvidersUnavailableError(list(self.providers.keys()))

        last_error = None
        for provider_id in available:
            provider = self.providers[provider_id]
            quota = self.quota.providers[provider_id]

            # Reserve quota
            estimated_input = provider.estimate_tokens(prompt + (system_prompt or ""))
            try:
                self.quota.check_and_reserve(provider_id, estimated_input)
            except QuotaExhaustedError:
                continue

            # Verify free status if configured
            if quota.config.get("verify_free_before_call", False):
                model_to_check = model or provider.default_model
                if not await provider.verify_free_status(model_to_check):
                    continue

            try:
                response = await provider.complete(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self.quota.record_call(
                    provider_id,
                    response.input_tokens,
                    response.output_tokens,
                    True,
                )
                return response

            except QuotaExhaustedError as e:
                self.quota.record_call(provider_id, 0, 0, False)
                last_error = e
                continue

            except Exception as e:
                self.quota.record_call(provider_id, 0, 0, False)
                last_error = e
                continue

        raise AllProvidersUnavailableError(available) from last_error

    async def close_all(self):
        """Close all provider clients."""
        for provider in self.providers.values():
            await provider.close()

    def get_usage_summary(self) -> list[dict]:
        """Get usage for all providers."""
        return self.quota.get_all_usage()