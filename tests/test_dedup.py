#!/usr/bin/env python3
"""
Nakeeb AI - Test Suite
Tests for deduplication, scoring, quota, event sourcing, and security.
"""

import pytest
import tempfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from src.intake import (
    canonicalize_url,
    normalize_title,
    generate_fingerprint,
    generate_stable_id,
    Discovery,
    Deduplicator,
)
from src.enrich import EnrichedDiscovery
from src.score import Scorer, ScoreBreakdown, BASE_RUBRIC, TIER_THRESHOLDS
from src.index import EventStore, DiscoveryIndex, Event, SCHEMA_SQL
from src.quota import QuotaManager, ProviderQuota
from src.errors import (
    NakeebError,
    ConfigurationError,
    SourceError,
    QuotaExhaustedError,
    AllProvidersUnavailableError,
    ValidationError,
    EventStoreError,
    DeduplicationError,
    ScoringError,
    PublishingError,
    ArchiveError,
    SecurityError,
    ConcurrencyError,
)


# === FIXTURES ===

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_discovery():
    return Discovery.from_source(
        url="https://github.com/pydantic/pydantic",
        title="Pydantic v2.10 Released",
        source_id="github_repo_releases",
        source_url="https://api.github.com/repos/pydantic/pydantic/releases",
        metadata={"repo": "pydantic/pydantic", "tag": "v2.10.0"},
    )


@pytest.fixture
def profile_path(temp_dir):
    """Create a minimal test profile."""
    profile = temp_dir / "test-profile.yaml"
    profile.write_text("""
id: test
name: Test Profile
scoring_weights:
  practical_usefulness: 1.0
  technical_quality: 1.0
  free_access: 1.0
  documentation: 1.0
  maintenance: 1.0
  integration_potential: 1.0
  originality: 1.0
thresholds:
  min_score: 65
  reverse_engineering_threshold: 80
license:
  preferred: [MIT, Apache-2.0]
  acceptable: [BSD-3-Clause]
  reject: [GPL-3.0]
free_tier:
  required: true
  acceptable_patterns: ["free tier", "open source"]
  reject_patterns: ["enterprise only"]
""")
    return profile


# === INTAKE TESTS ===

class TestCanonicalizeURL:
    def test_basic_canonicalization(self):
        url = "https://GitHub.com/USER/Repo/?utm_source=test&fbclid=123"
        canon = canonicalize_url(url)
        assert canon.scheme == "https"
        assert canon.host == "github.com"
        assert canon.path == "/user/repo"
        assert "utm_source" not in canon.query
        assert "fbclid" not in canon.query

    def test_default_ports_removed(self):
        url1 = "http://example.com:80/path"
        url2 = "https://example.com:443/path"
        canon1 = canonicalize_url(url1)
        canon2 = canonicalize_url(url2)
        assert canon1.port is None
        assert canon2.port is None

    def test_non_default_ports_preserved(self):
        url = "https://example.com:8443/path"
        canon = canonicalize_url(url)
        assert canon.port == 8443

    def test_path_normalization(self):
        url = "https://example.com/path//to///resource/"
        canon = canonicalize_url(url)
        assert canon.path == "/path/to/resource"

    def test_query_sorting(self):
        url = "https://example.com?b=2&a=1&c=3"
        canon = canonicalize_url(url)
        assert canon.query == "a=1&b=2&c=3"


class TestNormalizeTitle:
    def test_basic_normalization(self):
        title = "  Hello   WORLD!  "
        assert normalize_title(title) == "hello world"

    def test_punctuation_removed(self):
        title = "Test: API (v2.0) - Awesome!"
        assert normalize_title(title) == "test api v20 awesome"

    def test_unicode_handling(self):
        title = "Café résumé"
        normalized = normalize_title(title)
        assert "caf" in normalized
        assert "resum" in normalized


class TestFingerprint:
    def test_deterministic(self):
        url = canonicalize_url("https://github.com/test/repo")
        title = normalize_title("Test Repo")

        fp1 = generate_fingerprint(url, title)
        fp2 = generate_fingerprint(url, title)
        assert fp1 == fp2

    def test_different_url_different_fp(self):
        url1 = canonicalize_url("https://github.com/test/repo1")
        url2 = canonicalize_url("https://github.com/test/repo2")
        title = normalize_title("Test")

        fp1 = generate_fingerprint(url1, title)
        fp2 = generate_fingerprint(url2, title)
        assert fp1 != fp2

    def test_different_title_different_fp(self):
        url = canonicalize_url("https://github.com/test/repo")
        fp1 = generate_fingerprint(url, normalize_title("Title A"))
        fp2 = generate_fingerprint(url, normalize_title("Title B"))
        assert fp1 != fp2


class TestStableID:
    def test_deterministic(self):
        url = canonicalize_url("https://github.com/test/repo")
        id1 = generate_stable_id(url)
        id2 = generate_stable_id(url)
        assert id1 == id2

    def test_same_for_same_canonical(self):
        url1 = canonicalize_url("https://github.com/test/repo?utm_source=x")
        url2 = canonicalize_url("https://github.com/test/repo?fbclid=y")
        id1 = generate_stable_id(url1)
        id2 = generate_stable_id(url2)
        assert id1 == id2


class TestDiscovery:
    def test_from_source(self, sample_discovery):
        assert sample_discovery.stable_id
        assert sample_discovery.fingerprint
        assert sample_discovery.source_id == "github_repo_releases"
        assert "pydantic" in sample_discovery.original_url

    def test_to_dict(self, sample_discovery):
        d = sample_discovery.to_dict()
        assert d["stable_id"] == sample_discovery.stable_id
        assert d["source_id"] == "github_repo_releases"


class TestDeduplicator:
    def test_exact_duplicate(self, sample_discovery):
        dedup = Deduplicator()
        dedup.add(sample_discovery)

        # Same discovery should be detected as duplicate
        result = dedup.check(sample_discovery)
        assert result.is_duplicate
        assert result.action == "exact_duplicate"

    def test_different_not_duplicate(self):
        dedup = Deduplicator()
        d1 = Discovery.from_source(
            url="https://github.com/a/b",
            title="Repo A",
            source_id="github",
            source_url="https://api.github.com",
        )
        d2 = Discovery.from_source(
            url="https://github.com/c/d",
            title="Repo B",
            source_id="github",
            source_url="https://api.github.com",
        )
        dedup.add(d1)
        result = dedup.check(d2)
        assert not result.is_duplicate

    def test_load_existing(self, sample_discovery):
        dedup = Deduplicator()
        dedup.load_existing([sample_discovery])
        result = dedup.check(sample_discovery)
        assert result.is_duplicate


# === SCORING TESTS ===

class TestScorer:
    def test_scorer_initialization(self, profile_path):
        scorer = Scorer(profile_path, "test")
        assert scorer.weights
        assert scorer.config_hash

    def test_weights_normalized(self, profile_path):
        scorer = Scorer(profile_path, "test")
        total = sum(scorer.weights.values())
        assert abs(total - 100) < 0.01

    def test_score_enriched(self, profile_path):
        scorer = Scorer(profile_path, "test")

        # Create minimal enriched discovery
        from src.intake import Discovery, canonicalize_url, normalize_title
        disc = Discovery.from_source(
            url="https://github.com/test/repo",
            title="Test Repo",
            source_id="github",
            source_url="https://api.github.com",
        )
        enriched = EnrichedDiscovery(discovery=disc)
        enriched.name = "Test Repo"
        enriched.description = "A useful tool for testing with great documentation and examples."
        enriched.repo_url = "https://github.com/test/repo"
        enriched.owner = "test"
        enriched.license = "MIT"
        enriched.stars = 500
        enriched.forks = 50
        enriched.last_commit = datetime.now(timezone.utc).isoformat()
        enriched.releases = [{"tag": "v1.0", "date": "2026-01-01"}]
        enriched.dependencies = ["pytest", "requests"]
        enriched.install_requirements = "pip install test-repo\n# Examples in docs"
        enriched.api_pricing = "Free tier available, no credit card required"
        enriched.hosting_requirements = "Docker supported"
        enriched.hardware_requirements = "Runs on CPU"
        enriched.free_tier_compatibility = "Free tier with generous limits, open source"
        enriched.security_notes = "No known vulnerabilities"

        result = scorer.score(enriched)
        assert isinstance(result.total, int)
        assert 0 <= result.total <= 100
        assert result.tier in ["reject", "standard", "reverse_engineer"]
        assert 0 <= result.confidence <= 1.0
        assert result.config_hash == scorer.config_hash

    def test_tier_thresholds(self, profile_path):
        scorer = Scorer(profile_path, "test")

        # Low score -> reject
        from src.intake import Discovery
        disc = Discovery.from_source("https://x.com", "X", "x", "x")
        enriched = EnrichedDiscovery(discovery=disc)
        enriched.description = "x"
        result = scorer.score(enriched)
        assert result.tier == "reject"

    def test_deterministic(self, profile_path):
        """Same input + config = same score."""
        scorer = Scorer(profile_path, "test")
        from src.intake import Discovery
        disc = Discovery.from_source("https://github.com/test/repo", "Test", "github", "https://api.github.com")
        enriched = EnrichedDiscovery(discovery=disc)
        enriched.name = "Test"
        enriched.description = "A test library"
        enriched.license = "MIT"
        enriched.stars = 100

        r1 = scorer.score(enriched)
        r2 = scorer.score(enriched)
        assert r1.total == r2.total
        assert r1.scores.to_dict() == r2.scores.to_dict()


# === QUOTA TESTS ===

class TestQuotaManager:
    def test_provider_quota_can_make_call(self):
        quota = ProviderQuota(
            provider="test",
            model="test-model",
            per_run_cap=10,
            daily_cap=100,
            rpm_limit=60,
            tpm_limit=10000,
            max_input_tokens=4000,
            max_output_tokens=1000,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
        )
        allowed, reason = quota.can_make_call(1000)
        assert allowed
        assert reason is None

    def test_per_run_cap(self):
        quota = ProviderQuota(
            provider="test", model="test", per_run_cap=2, daily_cap=100,
            rpm_limit=60, tpm_limit=10000, max_input_tokens=4000,
            max_output_tokens=1000, cost_per_1k_input=0.0, cost_per_1k_output=0.0,
        )
        quota.calls_this_run = 2
        allowed, reason = quota.can_make_call()
        assert not allowed
        assert "Per-run cap" in reason

    def test_daily_cap(self):
        quota = ProviderQuota(
            provider="test", model="test", per_run_cap=10, daily_cap=2,
            rpm_limit=60, tpm_limit=10000, max_input_tokens=4000,
            max_output_tokens=1000, cost_per_1k_input=0.0, cost_per_1k_output=0.0,
        )
        quota.calls_today = 2
        allowed, reason = quota.can_make_call()
        assert not allowed
        assert "Daily cap" in reason

    def test_circuit_breaker(self):
        quota = ProviderQuota(
            provider="test", model="test", per_run_cap=10, daily_cap=100,
            rpm_limit=60, tpm_limit=10000, max_input_tokens=4000,
            max_output_tokens=1000, cost_per_1k_input=0.0, cost_per_1k_output=0.0,
        )
        quota.consecutive_failures = 5
        allowed, reason = quota.can_make_call()
        assert not allowed
        assert "Circuit breaker" in reason

    def test_record_call(self):
        quota = ProviderQuota(
            provider="test", model="test", per_run_cap=10, daily_cap=100,
            rpm_limit=60, tpm_limit=10000, max_input_tokens=4000,
            max_output_tokens=1000, cost_per_1k_input=0.0, cost_per_1k_output=0.0,
        )
        quota.record_call(100, 50, True)
        assert quota.calls_this_run == 1
        assert quota.input_tokens_this_run == 100
        assert quota.output_tokens_this_run == 50
        assert quota.consecutive_failures == 0

        quota.record_call(50, 25, False)
        assert quota.consecutive_failures == 1


class TestQuotaManagerIntegration:
    def test_check_and_reserve(self, temp_dir):
        # Create minimal quota config
        config = temp_dir / "quotas.yaml"
        config.write_text("""
global:
  max_llm_calls_per_run: 20
providers:
  gemini:
    enabled: true
    model: gemini-decision-1
    per_run_cap: 5
    daily_cap: 100
    rpm_limit: 100
    tpm_limit: 20000
    max_input_tokens_per_call: 32000
    max_output_tokens_per_call: 8192
    cost_per_1k_input: 0.0
    cost_per_1k_output: 0.0
""")
        qm = QuotaManager(config)
        quota = qm.check_and_reserve("gemini", 1000)
        assert quota.provider == "gemini"

    def test_quota_exhausted_raises(self, temp_dir):
        config = temp_dir / "quotas.yaml"
        config.write_text("""
global:
  max_llm_calls_per_run: 1
providers:
  gemini:
    enabled: true
    model: gemini-decision-1
    per_run_cap: 1
    daily_cap: 1
    rpm_limit: 100
    tpm_limit: 20000
    max_input_tokens_per_call: 32000
    max_output_tokens_per_call: 8192
    cost_per_1k_input: 0.0
    cost_per_1k_output: 0.0
""")
        qm = QuotaManager(config)
        qm.check_and_reserve("gemini")
        with pytest.raises(QuotaExhaustedError):
            qm.check_and_reserve("gemini")

    def test_all_unavailable(self, temp_dir):
        config = temp_dir / "quotas.yaml"
        config.write_text("""
global:
  max_llm_calls_per_run: 0
providers:
  gemini:
    enabled: true
    model: gemini-decision-1
    per_run_cap: 0
    daily_cap: 0
    rpm_limit: 100
    tpm_limit: 20000
    max_input_tokens_per_call: 32000
    max_output_tokens_per_call: 8192
    cost_per_1k_input: 0.0
    cost_per_1k_output: 0.0
""")
        qm = QuotaManager(config)
        assert qm.all_unavailable()


# === EVENT STORE TESTS ===

class TestEventStore:
    def test_append_and_read(self, temp_dir):
        events_path = temp_dir / "events.jsonl"
        store = EventStore(events_path)

        event = Event(
            discovery_id="test-123",
            event_type="discovery_created",
            source_run_id="run-1",
            payload={"title": "Test"},
        )
        store.append(event)

        events = list(store.read_all())
        assert len(events) == 1
        assert events[0].discovery_id == "test-123"
        assert events[0].event_type == "discovery_created"

    def test_append_batch(self, temp_dir):
        events_path = temp_dir / "events.jsonl"
        store = EventStore(events_path)

        events = [
            Event(discovery_id="1", event_type="discovery_created", source_run_id="run-1", payload={}),
            Event(discovery_id="2", event_type="enriched", source_run_id="run-1", payload={}),
        ]
        store.append_batch(events)

        read = list(store.read_all())
        assert len(read) == 2

    def test_integrity_verification(self, temp_dir):
        events_path = temp_dir / "events.jsonl"
        store = EventStore(events_path)

        event = Event(discovery_id="1", event_type="discovery_created", source_run_id="run-1", payload={})
        store.append(event)

        valid, errors = store.verify_integrity()
        assert valid
        assert errors == []

    def test_unknown_event_type_rejected(self):
        with pytest.raises(ValueError):
            Event(discovery_id="1", event_type="invalid_type", source_run_id="run-1", payload={})


class TestDiscoveryIndex:
    def test_rebuild_from_events(self, temp_dir):
        events_path = temp_dir / "events.jsonl"
        db_path = temp_dir / "index.db"

        store = EventStore(events_path)
        index = DiscoveryIndex(db_path)

        # Add events
        event1 = Event(
            discovery_id="disc-1",
            event_type="discovery_created",
            source_run_id="run-1",
            payload={
                "stable_id": "disc-1", "fingerprint": "fp-1",
                "canonical_url": "https://github.com/test/repo",
                "original_url": "https://github.com/test/repo",
                "original_title": "Test Repo",
                "normalized_title": "test repo",
                "source_id": "github", "source_url": "https://api.github.com",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        store.append(event1)

        counts = index.rebuild_from_events(store)
        assert counts["discoveries"] == 1
        assert counts["events"] == 1

        index.close()

    def test_query_discoveries(self, temp_dir):
        events_path = temp_dir / "events.jsonl"
        db_path = temp_dir / "index.db"

        store = EventStore(events_path)
        index = DiscoveryIndex(db_path)

        event = Event(
            discovery_id="disc-1",
            event_type="discovery_created",
            source_run_id="run-1",
            payload={
                "stable_id": "disc-1", "fingerprint": "fp-1",
                "canonical_url": "https://github.com/test/repo",
                "original_url": "https://github.com/test/repo",
                "original_title": "Test Repo",
                "normalized_title": "test repo",
                "source_id": "github", "source_url": "https://api.github.com",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        store.append(event)
        index.rebuild_from_events(store)

        # Add score event
        score_event = Event(
            discovery_id="disc-1",
            event_type="scored",
            source_run_id="run-1",
            payload={"total": 85, "tier": "reverse_engineer", "confidence": 0.9},
        )
        store.append(score_event)
        index.rebuild_from_events(store)

        results = index.query_discoveries(min_score=80)
        assert len(results) == 1
        assert results[0]["total_score"] == 85

        index.close()


# === ERROR TESTS ===

class TestErrors:
    def test_nakeeb_error_base(self):
        err = NakeebError("Test error", code="TEST", details={"key": "value"})
        assert str(err) == "Test error"
        assert err.code == "TEST"
        assert err.details["key"] == "value"
        assert err.recoverable is True

    def test_quota_exhausted(self):
        err = QuotaExhaustedError("gemini", "rate_limit")
        assert "gemini" in str(err)
        assert err.details["provider"] == "gemini"
        assert err.details["limit_type"] == "rate_limit"
        assert err.recoverable is False

    def test_all_providers_unavailable(self):
        err = AllProvidersUnavailableError(["gemini", "openrouter"])
        assert "gemini" in str(err)
        assert "openrouter" in str(err)
        assert err.details["providers"] == ["gemini", "openrouter"]

    def test_security_error_non_recoverable(self):
        err = SecurityError("Invalid input")
        assert err.recoverable is False

    def test_concurrency_error(self):
        err = ConcurrencyError("events.jsonl", "Lock timeout")
        assert "events.jsonl" in str(err)
        assert err.details["resource"] == "events.jsonl"


# === SECURITY TESTS ===

class TestSecurity:
    def test_no_secrets_in_errors(self):
        """Ensure error messages don't leak secrets."""
        err = QuotaExhaustedError("gemini", "rate_limit")
        error_str = str(err)
        assert "api_key" not in error_str.lower()
        assert "token" not in error_str.lower()
        assert "secret" not in error_str.lower()
        assert "password" not in error_str.lower()

    def test_input_validation(self):
        """Test that validation errors don't expose internals."""
        err = ValidationError("api_key", "Invalid format")
        assert "api_key" in str(err)
        assert err.details["field"] == "api_key"


# === INTEGRATION TESTS ===

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_mock(self, temp_dir, profile_path):
        """Test the full pipeline with mock data."""
        from src.intake import Discovery, process_source_batch, Deduplicator
        from src.enrich import enrich_batch
        from src.score import score_batch

        # Mock source data
        mock_items = [
            {"url": "https://github.com/test/repo1", "title": "Repo 1", "source_url": "https://api.github.com", "metadata": {}},
            {"url": "https://github.com/test/repo2", "title": "Repo 2", "source_url": "https://api.github.com", "metadata": {}},
        ]

        dedup = Deduplicator()
        new_discs, dup_info = await process_source_batch(mock_items, "github_test", dedup)

        assert len(new_discs) == 2
        assert len(dup_info) == 0

        # Enrich (mock - no actual API calls)
        # In real test, would mock httpx responses

        # Score
        scored = await score_batch([
            EnrichedDiscovery(
                discovery=d,
                name=d.original_title,
                description="A test repository with good documentation.",
                license="MIT",
                stars=100,
                last_commit=datetime.now(timezone.utc).isoformat(),
            ) for d in new_discs
        ], profile_path, "test")

        assert len(scored) == 2
        for s in scored:
            assert 0 <= s.total <= 100
            assert s.tier in ["reject", "standard", "reverse_engineer"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])