"""
Nakeeb AI - Intake & Normalization
URL canonicalization, title normalization, fingerprinting.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode


# Tracking parameters to strip (per Horizon + common)
TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "ttclid", "twclid",
    "li_fat_id", "mc_cid", "mc_eid", "_ga", "_gac", "vero_id", "igshid",
    "ref", "referrer", "source", "medium", "campaign",
})


@dataclass
class CanonicalURL:
    """Canonicalized URL with components."""
    scheme: str
    host: str
    port: Optional[int]
    path: str
    query: str  # Already sorted, tracking params removed

    def __str__(self) -> str:
        netloc = self.host
        if self.port and not ((self.scheme == "http" and self.port == 80) or
                               (self.scheme == "https" and self.port == 443)):
            netloc += f":{self.port}"
        query_part = f"?{self.query}" if self.query else ""
        return f"{self.scheme}://{netloc}{self.path}{query_part}"

    def __hash__(self) -> int:
        return hash(str(self))

    def __eq__(self, other) -> bool:
        if not isinstance(other, CanonicalURL):
            return False
        return str(self) == str(other)


def canonicalize_url(url: str) -> CanonicalURL:
    """
    Canonicalize URL per Horizon's _deduplication_url_key:
    - Lowercase scheme and host
    - Remove default ports (80/443)
    - Normalize path (remove trailing slash except root, lowercase)
    - Strip tracking query parameters
    - Sort remaining query parameters
    """
    parsed = urlparse(url.strip())

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port

    # Remove default ports
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    # Normalize path (lowercase, collapse multiple slashes)
    path = parsed.path
    path = re.sub(r"/+", "/", path)
    path = path.rstrip("/") or "/"
    path = path.lower()

    # Process query parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {}
    for key, values in query_params.items():
        key_lower = key.lower()
        if key_lower.startswith("utm_") or key_lower in TRACKING_PARAMS:
            continue
        filtered[key] = values[0] if values else ""

    # Sort for consistency
    query = urlencode(sorted(filtered.items()), doseq=True)

    return CanonicalURL(scheme, host, port, path, query)


def normalize_title(title: str) -> str:
    """Normalize title for fingerprinting."""
    # Lowercase, strip, collapse whitespace
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    # Remove common punctuation that doesn't affect meaning (keep alphanumeric and spaces)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    # Collapse multiple spaces
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def generate_fingerprint(canonical_url: CanonicalURL, normalized_title: str) -> str:
    """Generate SHA256 fingerprint: sha256(canonical_url + "|" + normalized_title)."""
    combined = f"{canonical_url}|{normalized_title}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def generate_stable_id(canonical_url: CanonicalURL) -> str:
    """Generate stable ID: sha256(canonical_url)."""
    return hashlib.sha256(str(canonical_url).encode("utf-8")).hexdigest()


@dataclass
class Discovery:
    """Normalized discovery record."""
    stable_id: str
    fingerprint: str
    canonical_url: CanonicalURL
    original_url: str
    original_title: str
    normalized_title: str
    source_id: str
    source_url: str
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stable_id": self.stable_id,
            "fingerprint": self.fingerprint,
            "canonical_url": str(self.canonical_url),
            "original_url": self.original_url,
            "original_title": self.original_title,
            "normalized_title": self.normalized_title,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_source(
        cls,
        url: str,
        title: str,
        source_id: str,
        source_url: str,
        metadata: dict | None = None,
    ) -> "Discovery":
        """Create discovery from raw source data."""
        canonical = canonicalize_url(url)
        norm_title = normalize_title(title)
        fingerprint = generate_fingerprint(canonical, norm_title)
        stable_id = generate_stable_id(canonical)

        return cls(
            stable_id=stable_id,
            fingerprint=fingerprint,
            canonical_url=canonical,
            original_url=url,
            original_title=title,
            normalized_title=norm_title,
            source_id=source_id,
            source_url=source_url,
            metadata=metadata or {},
        )
