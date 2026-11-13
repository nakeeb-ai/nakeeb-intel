"""
Nakeeb AI - Deterministic Scoring Engine
100-point rubric with provenance tracking.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional
from pathlib import Path

import yaml

from .enrich import EnrichedDiscovery
from .errors import ScoringError, ConfigurationError


# Base rubric weights (sum = 100)
BASE_RUBRIC = {
    "practical_usefulness": 20,
    "technical_quality": 20,
    "free_access": 15,
    "documentation": 15,
    "maintenance": 10,
    "integration_potential": 10,
    "originality": 10,
}

TIER_THRESHOLDS = {
    "reject": 65,
    "standard": 79,
    "reverse_engineer": 100,
}


@dataclass
class ScoreBreakdown:
    """Detailed score for each criterion."""
    practical_usefulness: int = 0
    technical_quality: int = 0
    free_access: int = 0
    documentation: int = 0
    maintenance: int = 0
    integration_potential: int = 0
    originality: int = 0

    def total(self) -> int:
        return sum([
            self.practical_usefulness,
            self.technical_quality,
            self.free_access,
            self.documentation,
            self.maintenance,
            self.integration_potential,
            self.originality,
        ])

    def to_dict(self) -> dict[str, int]:
        return {
            "practical_usefulness": self.practical_usefulness,
            "technical_quality": self.technical_quality,
            "free_access": self.free_access,
            "documentation": self.documentation,
            "maintenance": self.maintenance,
            "integration_potential": self.integration_potential,
            "originality": self.originality,
            "total": self.total(),
        }


@dataclass
class ScoredDiscovery:
    """Discovery with deterministic score."""
    enriched: EnrichedDiscovery
    scores: ScoreBreakdown
    total: int
    tier: str  # reject, standard, reverse_engineer
    confidence: float
    reasoning: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    missing_info: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    config_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "stable_id": self.enriched.discovery.stable_id,
            "fingerprint": self.enriched.discovery.fingerprint,
            "scores": self.scores.to_dict(),
            "total": self.total,
            "tier": self.tier,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "provenance": self.provenance,
            "missing_info": self.missing_info,
            "flags": self.flags,
            "config_hash": self.config_hash,
        }


class Scorer:
    """Deterministic scoring engine."""

    def __init__(self, profile_path: Path, domain: str):
        self.profile_path = profile_path
        self.domain = domain
        self.profile = self._load_profile()
        self.weights = self._compute_weights()
        self.config_hash = self._hash_config()

    def _load_profile(self) -> dict:
        if not self.profile_path.exists():
            raise ConfigurationError(f"Profile not found: {self.profile_path}")
        with open(self.profile_path) as f:
            return yaml.safe_load(f)

    def _compute_weights(self) -> dict[str, float]:
        """Compute effective weights from base rubric * profile multipliers."""
        base = BASE_RUBRIC.copy()
        profile_weights = self.profile.get("scoring_weights", {})

        effective = {}
        for criterion, base_weight in base.items():
            multiplier = profile_weights.get(criterion, 1.0)
            effective[criterion] = base_weight * multiplier

        # Normalize to sum = 100
        total = sum(effective.values())
        if total > 0:
            effective = {k: v * 100 / total for k, v in effective.items()}

        return effective

    def _hash_config(self) -> str:
        """Hash the effective config for reproducibility."""
        config_str = json.dumps({
            "base_rubric": BASE_RUBRIC,
            "weights": self.weights,
            "thresholds": self.profile.get("thresholds", {}),
        }, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def score(self, enriched: EnrichedDiscovery) -> ScoredDiscovery:
        """Score an enriched discovery deterministically."""
        e = enriched
        d = e.discovery
        meta = e.__dict__  # Access enriched fields

        # --- Practical Usefulness (0-20) ---
        usefulness, u_reason, u_prov = self._score_usefulness(e)
        # --- Technical Quality (0-20) ---
        quality, q_reason, q_prov = self._score_quality(e)
        # --- Free Access (0-15) ---
        free_access, f_reason, f_prov = self._score_free_access(e)
        # --- Documentation (0-15) ---
        docs, d_reason, d_prov = self._score_documentation(e)
        # --- Maintenance (0-10) ---
        maint, m_reason, m_prov = self._score_maintenance(e)
        # --- Integration Potential (0-10) ---
        integ, i_reason, i_prov = self._score_integration(e)
        # --- Originality (0-10) ---
        orig, o_reason, o_prov = self._score_originality(e)

        scores = ScoreBreakdown(
            practical_usefulness=usefulness,
            technical_quality=quality,
            free_access=free_access,
            documentation=docs,
            maintenance=maint,
            integration_potential=integ,
            originality=orig,
        )

        total = scores.total()

        # Determine tier
        thresholds = self.profile.get("thresholds", {})
        if total < thresholds.get("min_score", 65):
            tier = "reject"
        elif total >= thresholds.get("reverse_engineering_threshold", 80):
            tier = "reverse_engineer"
        else:
            tier = "standard"

        # Confidence: based on missing info proportion
        total_fields = 7
        missing_count = len(e.missing_info) + len(e.enrichment_errors)
        confidence = max(0.0, 1.0 - (missing_count / (total_fields * 2)))

        # Aggregate provenance and reasoning
        provenance = {
            "practical_usefulness": u_prov,
            "technical_quality": q_prov,
            "free_access": f_prov,
            "documentation": d_prov,
            "maintenance": m_prov,
            "integration_potential": i_prov,
            "originality": o_prov,
        }

        reasoning = {
            "practical_usefulness": u_reason,
            "technical_quality": q_reason,
            "free_access": f_reason,
            "documentation": d_reason,
            "maintenance": m_reason,
            "integration_potential": i_reason,
            "originality": o_reason,
        }

        # Collect missing info and flags
        missing_info = list(e.missing_info)
        if e.enrichment_errors:
            missing_info.extend([f"enrichment_error: {err}" for err in e.enrichment_errors])

        flags = list(e.flags)
        if e.provenance.get("license") == "unknown":
            flags.append("license_unknown")
        if e.provenance.get("free_tier_compatibility") == "unknown":
            flags.append("free_tier_unknown")

        return ScoredDiscovery(
            enriched=enriched,
            scores=scores,
            total=total,
            tier=tier,
            confidence=round(confidence, 2),
            reasoning=reasoning,
            provenance=provenance,
            missing_info=missing_info,
            flags=flags,
            config_hash=self.config_hash,
        )

    # --- Scoring Methods ---

    def _score_usefulness(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score practical usefulness (0-20)."""
        desc = (e.description or "").lower()
        name = (e.name or "").lower()

        # Keywords indicating clear utility
        utility_keywords = [
            "tool", "library", "framework", "api", "cli", "sdk",
            "automation", "pipeline", "workflow", "agent", "orchestration",
            "inference", "training", "fine-tuning", "evaluation", "benchmark",
            "rag", "retrieval", "embedding", "vector", "search",
            "deploy", "production", "monitoring", "observability",
        ]

        # Keywords indicating niche/experimental
        experimental_keywords = [
            "experimental", "alpha", "beta", "prototype", "proof of concept",
            "poc", "research", "exploratory", "demo", "example",
        ]

        score = 10  # Base

        # Check for utility signals
        util_count = sum(1 for kw in utility_keywords if kw in desc or kw in name)
        score += min(util_count * 1.5, 8)

        # Penalize experimental
        exp_count = sum(1 for kw in experimental_keywords if kw in desc or kw in name)
        score -= min(exp_count * 2, 5)

        # Stars as proxy for community validation
        if e.stars > 1000:
            score += 2
        elif e.stars > 100:
            score += 1

        return max(0, min(20, int(score))), f"Utility keywords: {util_count}, stars: {e.stars}", "metadata"

    def _score_quality(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score technical quality (0-20)."""
        # Indicators: tests, CI, typing, docs, structure
        deps = e.dependencies
        readme = (e.install_requirements or "").lower()

        score = 10  # Base

        # Dependency quality signals
        quality_deps = ["pytest", "ruff", "mypy", "black", "pre-commit", "github actions", "ci"]
        for dep in deps:
            dep_lower = dep.lower()
            if any(q in dep_lower for q in quality_deps):
                score += 1

        # README quality signals
        if "test" in readme:
            score += 1
        if "example" in readme:
            score += 1
        if "install" in readme:
            score += 1

        # License clarity
        if e.license and e.license != "unknown":
            score += 1

        return max(0, min(20, int(score))), f"Quality deps: {sum(1 for d in deps if any(q in d.lower() for q in ['pytest','ruff','mypy','black']))}, README signals", "metadata"

    def _score_free_access(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score free/low-cost access (0-15)."""
        free_text = (e.free_tier_compatibility or "").lower()
        pricing = (e.api_pricing or "").lower()
        combined = f"{free_text} {pricing}"

        # Negative signals
        negative = [
            "enterprise only", "contact sales", "paid plan required",
            "credit card required", "trial only", "limited free tier",
            "no free tier", "pay per use", "billing", "invoice",
        ]

        # Positive signals
        positive = [
            "free tier", "free for personal", "open source", "community edition",
            "no credit card", "generous free tier", "self-hosted", "local-first",
            "runs locally", "mit license", "apache license", "bsd license",
        ]

        score = 7  # Base neutral

        for neg in negative:
            if neg in combined:
                score -= 3

        for pos in positive:
            if pos in combined:
                score += 1.5

        # License check
        preferred = self.profile.get("license", {}).get("preferred", [])
        if e.license in preferred:
            score += 2
        acceptable = self.profile.get("license", {}).get("acceptable", [])
        if e.license in acceptable:
            score += 1
        reject = self.profile.get("license", {}).get("reject", [])
        if e.license in reject:
            score -= 5

        return max(0, min(15, int(score))), f"Free signals: {sum(1 for p in positive if p in combined)}, license: {e.license}", "metadata"

    def _score_documentation(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score documentation (0-15)."""
        readme = (e.install_requirements or "").lower()
        desc_len = len(e.description or "")

        score = 5  # Base

        # Description quality
        if desc_len > 500:
            score += 3
        elif desc_len > 200:
            score += 2
        elif desc_len > 50:
            score += 1

        # README sections
        sections = ["install", "setup", "usage", "example", "api", "configuration", "deploy", "troubleshooting"]
        for sec in sections:
            if sec in readme:
                score += 0.5

        # Has releases
        if e.releases:
            score += 1

        return max(0, min(15, int(score))), f"Desc len: {desc_len}, README sections: {sum(1 for s in sections if s in readme)}", "metadata"

    def _score_maintenance(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score maintenance activity (0-10)."""
        from datetime import datetime, timezone

        score = 5  # Base

        # Last commit recency
        if e.last_commit:
            try:
                last = datetime.fromisoformat(e.last_commit.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days = (now - last).days
                if days < 30:
                    score += 3
                elif days < 90:
                    score += 2
                elif days < 180:
                    score += 1
                elif days > 365:
                    score -= 2
            except Exception:
                pass

        # Release frequency
        if len(e.releases) >= 3:
            score += 1
        elif len(e.releases) >= 1:
            score += 0.5

        # Dependencies freshness (rough)
        if e.dependencies:
            score += 0.5

        return max(0, min(10, int(score))), f"Last commit: {e.last_commit}, releases: {len(e.releases)}", "metadata"

    def _score_integration(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score integration potential (0-10)."""
        readme = (e.install_requirements or "").lower()
        deps = [d.lower() for d in e.dependencies]

        score = 3  # Base

        # API/interface signals
        api_signals = ["api", "rest", "graphql", "grpc", "websocket", "sdk", "client", "wrapper"]
        for sig in api_signals:
            if sig in readme:
                score += 1
                break

        # Standards compliance
        std_signals = ["openapi", "swagger", "mcp", "protocol", "standard", "spec"]
        for sig in std_signals:
            if sig in readme:
                score += 1
                break

        # Plugin/extensibility
        plugin_signals = ["plugin", "extension", "hook", "middleware", "custom", "adapter"]
        for sig in plugin_signals:
            if sig in readme:
                score += 1
                break

        # Language bindings
        lang_signals = ["python", "javascript", "typescript", "go", "rust", "java"]
        for lang in lang_signals:
            if any(lang in d for d in deps):
                score += 0.5

        return max(0, min(10, int(score))), f"API signals in README, dependencies", "metadata"

    def _score_originality(self, e: EnrichedDiscovery) -> tuple[int, str, str]:
        """Score originality/opportunity (0-10)."""
        desc = (e.description or "").lower()
        name = (e.name or "").lower()

        score = 5  # Base

        # Novelty keywords
        novel = [
            "novel", "new approach", "first", "unique", "innovative",
            "breakthrough", "paradigm", "unlike", "different from",
            "solves", "addresses", "improves upon", "outperforms",
        ]

        for n in novel:
            if n in desc:
                score += 1
                break

        # Derivative signals (penalize)
        derivative = [
            "fork of", "based on", "inspired by", "clone of",
            "alternative to", "replacement for", "wrapper for",
        ]

        for d in derivative:
            if d in desc:
                score -= 1
                break

        # Stars as market validation (but not too high = saturated)
        if 100 < e.stars < 5000:
            score += 1
        elif e.stars > 10000:
            score -= 1  # May be saturated

        return max(0, min(10, int(score))), f"Novelty signals in description, stars: {e.stars}", "metadata"


async def score_batch(
    enriched: list[EnrichedDiscovery],
    profile_path: Path,
    domain: str,
) -> list[ScoredDiscovery]:
    """Score a batch of enriched discoveries."""
    scorer = Scorer(profile_path, domain)
    return [scorer.score(e) for e in enriched]