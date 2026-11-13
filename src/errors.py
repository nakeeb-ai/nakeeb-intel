"""
Nakeeb AI - Core Exceptions
Custom exception hierarchy for the pipeline.
"""

from typing import Any, Optional


class NakeebError(Exception):
    """Base exception for all Nakeeb AI errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "NAKEEB_ERROR",
        details: Optional[dict[str, Any]] = None,
        recoverable: bool = True,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable


class ConfigurationError(NakeebError):
    """Invalid or missing configuration."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="CONFIG_ERROR", **kwargs)


class SourceError(NakeebError):
    """Source-specific error (non-fatal, isolated)."""

    def __init__(self, source_id: str, message: str, **kwargs):
        super().__init__(
            f"Source '{source_id}': {message}",
            code="SOURCE_ERROR",
            details={"source_id": source_id, **kwargs.get("details", {})},
            **kwargs,
        )
        self.source_id = source_id


class QuotaExhaustedError(NakeebError):
    """Provider quota exhausted."""

    def __init__(self, provider: str, limit_type: str, **kwargs):
        super().__init__(
            f"Quota exhausted for {provider} ({limit_type})",
            code="QUOTA_EXHAUSTED",
            details={"provider": provider, "limit_type": limit_type, **kwargs.get("details", {})},
            recoverable=False,
            **kwargs,
        )
        self.provider = provider
        self.limit_type = limit_type


class AllProvidersUnavailableError(NakeebError):
    """All LLM providers unavailable."""

    def __init__(self, providers: list[str], **kwargs):
        super().__init__(
            f"All LLM providers unavailable: {', '.join(providers)}",
            code="ALL_PROVIDERS_UNAVAILABLE",
            details={"providers": providers, **kwargs.get("details", {})},
            recoverable=True,
            **kwargs,
        )


class ValidationError(NakeebError):
    """Data validation failed."""

    def __init__(self, field: str, message: str, **kwargs):
        super().__init__(
            f"Validation failed for '{field}': {message}",
            code="VALIDATION_ERROR",
            details={"field": field, **kwargs.get("details", {})},
            **kwargs,
        )


class EventStoreError(NakeebError):
    """Event log operation failed."""

    def __init__(self, operation: str, message: str, **kwargs):
        super().__init__(
            f"Event store {operation} failed: {message}",
            code="EVENT_STORE_ERROR",
            details={"operation": operation, **kwargs.get("details", {})},
            **kwargs,
        )


class DeduplicationError(NakeebError):
    """Deduplication logic error."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="DEDUP_ERROR", **kwargs)


class ScoringError(NakeebError):
    """Scoring engine error."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SCORING_ERROR", **kwargs)


class PublishingError(NakeebError):
    """Publishing (Telegram, etc.) failed."""

    def __init__(self, target: str, message: str, **kwargs):
        super().__init__(
            f"Publishing to {target} failed: {message}",
            code="PUBLISHING_ERROR",
            details={"target": target, **kwargs.get("details", {})},
            recoverable=True,
            **kwargs,
        )


class ArchiveError(NakeebError):
    """Archive/backup operation failed."""

    def __init__(self, operation: str, message: str, **kwargs):
        super().__init__(
            f"Archive {operation} failed: {message}",
            code="ARCHIVE_ERROR",
            details={"operation": operation, **kwargs.get("details", {})},
            recoverable=True,
            **kwargs,
        )


class SecurityError(NakeebError):
    """Security violation (input validation, auth, etc.)."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            code="SECURITY_ERROR",
            recoverable=False,
            **kwargs,
        )


class ConcurrencyError(NakeebError):
    """Concurrency/locking error."""

    def __init__(self, resource: str, message: str, **kwargs):
        super().__init__(
            f"Concurrency error on {resource}: {message}",
            code="CONCURRENCY_ERROR",
            details={"resource": resource, **kwargs.get("details", {})},
            recoverable=True,
            **kwargs,
        )