"""
Nakeeb AI - Quota Manager
Internal safety caps for provider usage. NOT provider guarantees.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import yaml

from .errors import QuotaExhaustedError, AllProvidersUnavailableError, ConfigurationError


@dataclass
class ProviderQuota:
    """Runtime quota state for a provider."""
    provider: str
    model: str
    per_run_cap: int
    daily_cap: int
    rpm_limit: int
    tpm_limit: int
    max_input_tokens: int
    max_output_tokens: int
    cost_per_1k_input: float
    cost_per_1k_output: float

    # Runtime counters
    calls_this_run: int = 0
    input_tokens_this_run: int = 0
    output_tokens_this_run: int = 0
    calls_today: int = 0
    input_tokens_today: int = 0
    output_tokens_today: int = 0
    last_reset_day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))
    consecutive_failures: int = 0
    circuit_open: bool = False

    def reset_daily_if_needed(self):
        """Reset daily counters if day changed."""
        today = time.strftime("%Y-%m-%d")
        if today != self.last_reset_day:
            self.calls_today = 0
            self.input_tokens_today = 0
            self.output_tokens_today = 0
            self.last_reset_day = today
            self.consecutive_failures = 0
            self.circuit_open = False

    def reset_run(self):
        """Reset per-run counters."""
        self.calls_this_run = 0
        self.input_tokens_this_run = 0
        self.output_tokens_this_run = 0

    def can_make_call(self, estimated_input_tokens: int = 0) -> tuple[bool, Optional[str]]:
        """Check if a call can be made. Returns (allowed, reason_if_denied)."""
        self.reset_daily_if_needed()

        if self.circuit_open:
            return False, f"Circuit breaker open for {self.provider}"

        # Check if consecutive failures should open circuit
        if self.consecutive_failures >= 5:
            self.circuit_open = True
            return False, f"Circuit breaker open for {self.provider} (5 consecutive failures)"

        if self.calls_this_run >= self.per_run_cap:
            return False, f"Per-run cap reached ({self.per_run_cap})"

        if self.calls_today >= self.daily_cap:
            return False, f"Daily cap reached ({self.daily_cap})"

        if estimated_input_tokens > self.max_input_tokens:
            return False, f"Input tokens ({estimated_input_tokens}) exceed max ({self.max_input_tokens})"

        return True, None

    def record_call(self, input_tokens: int, output_tokens: int, success: bool):
        """Record a completed call."""
        self.calls_this_run += 1
        self.calls_today += 1
        self.input_tokens_this_run += input_tokens
        self.input_tokens_today += input_tokens
        self.output_tokens_this_run += output_tokens
        self.output_tokens_today += output_tokens

        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= 5:
                self.circuit_open = True

    def get_usage_summary(self) -> dict[str, Any]:
        """Get current usage for logging."""
        return {
            "provider": self.provider,
            "model": self.model,
            "run": {
                "calls": self.calls_this_run,
                "input_tokens": self.input_tokens_this_run,
                "output_tokens": self.output_tokens_this_run,
            },
            "daily": {
                "calls": self.calls_today,
                "input_tokens": self.input_tokens_today,
                "output_tokens": self.output_tokens_today,
            },
            "limits": {
                "per_run_cap": self.per_run_cap,
                "daily_cap": self.daily_cap,
                "rpm_limit": self.rpm_limit,
                "tpm_limit": self.tpm_limit,
            },
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
        }


class QuotaManager:
    """Manages quota enforcement across all providers."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = self._load_config()
        self.providers: dict[str, ProviderQuota] = {}
        self._lock = threading.RLock()
        self._initialize_providers()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise ConfigurationError(f"Quota config not found: {self.config_path}")
        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def _initialize_providers(self):
        """Create ProviderQuota objects from config."""
        global_cfg = self.config.get("global", {})
        providers_cfg = self.config.get("providers", {})

        for provider_id, cfg in providers_cfg.items():
            if not cfg.get("enabled", True):
                continue

            self.providers[provider_id] = ProviderQuota(
                provider=provider_id,
                model=cfg.get("model", "unknown"),
                per_run_cap=cfg.get("per_run_cap", global_cfg.get("max_llm_calls_per_run", 20)),
                daily_cap=cfg.get("daily_cap", 1000),
                rpm_limit=cfg.get("rpm_limit", 100),
                tpm_limit=cfg.get("tpm_limit", 10000),
                max_input_tokens=cfg.get("max_input_tokens_per_call", 32000),
                max_output_tokens=cfg.get("max_output_tokens_per_call", 8192),
                cost_per_1k_input=cfg.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=cfg.get("cost_per_1k_output", 0.0),
            )

    def check_and_reserve(
        self,
        provider: str,
        estimated_input_tokens: int = 0,
    ) -> ProviderQuota:
        """Check quota and reserve a call slot. Returns the provider quota."""
        with self._lock:
            if provider not in self.providers:
                raise ConfigurationError(f"Unknown provider: {provider}")

            quota = self.providers[provider]
            allowed, reason = quota.can_make_call(estimated_input_tokens)

            if not allowed:
                raise QuotaExhaustedError(provider, reason)

            return quota

    def record_call(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        success: bool,
    ):
        """Record a completed call."""
        with self._lock:
            if provider in self.providers:
                self.providers[provider].record_call(input_tokens, output_tokens, success)

    def get_available_providers(self, prefer: list[str] | None = None) -> list[str]:
        """Get list of providers that can accept calls, in priority order."""
        with self._lock:
            order = prefer or list(self.providers.keys())
            available = []
            for p in order:
                if p in self.providers:
                    quota = self.providers[p]
                    quota.reset_daily_if_needed()
                    if not quota.circuit_open and quota.calls_this_run < quota.per_run_cap:
                        available.append(p)
            return available

    def all_unavailable(self) -> bool:
        """Check if all providers are exhausted."""
        return len(self.get_available_providers()) == 0

    def get_all_usage(self) -> list[dict]:
        """Get usage summary for all providers."""
        with self._lock:
            return [q.get_usage_summary() for q in self.providers.values()]

    def reset_run(self):
        """Reset per-run counters for all providers."""
        with self._lock:
            for q in self.providers.values():
                q.reset_run()

    def get_telegram_quota(self) -> dict[str, Any]:
        """Get Telegram quota config."""
        return self.config.get("telegram", {})

    def get_github_actions_quota(self) -> dict[str, Any]:
        """Get GitHub Actions quota config."""
        return self.config.get("github_actions", {})