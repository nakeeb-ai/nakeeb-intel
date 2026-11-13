"""
Nakeeb AI - Publishing
Telegram digest publishing with error handling.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .errors import PublishingError, ConfigurationError
from .index import DiscoveryIndex
from .score import ScoredDiscovery


@dataclass
class PublishResult:
    """Result of publishing attempt."""
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    chars_sent: int = 0


class TelegramPublisher:
    """Publishes digests to Telegram."""

    def __init__(self, bot_token: str, chat_id: int, max_chars: int = 3800):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.max_chars = max_chars
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> PublishResult:
        """Send a message to Telegram."""
        client = await self._get_client()

        # Truncate if needed
        if len(text) > self.max_chars:
            text = text[:self.max_chars - 50] + "\n\n... [truncated]"

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            response = await client.post(f"{self.base_url}/sendMessage", json=payload)
            data = response.json()

            if not data.get("ok"):
                error = data.get("description", "Unknown error")
                # Handle common errors
                if "chat not found" in error.lower():
                    raise PublishingError("telegram", f"Chat not found: {error}")
                if "blocked by user" in error.lower():
                    raise PublishingError("telegram", f"Bot blocked by user: {error}")
                raise PublishingError("telegram", f"Telegram API error: {error}")

            result = data.get("result", {})
            return PublishResult(
                success=True,
                message_id=result.get("message_id"),
                chars_sent=len(text),
            )

        except httpx.HTTPStatusError as e:
            raise PublishingError("telegram", f"HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise PublishingError("telegram", str(e))

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def build_digest(
    scored: list[ScoredDiscovery],
    run_metadata: dict,
    index: DiscoveryIndex,
    base_url: str = "https://raw.githubusercontent.com/nakeeb-ai/nakeeb-intel/main",
) -> str:
    """Build digest text from scored discoveries."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = run_metadata.get("run_id", "unknown")

    # Categorize
    reverse_engineered = [s for s in scored if s.tier == "reverse_engineer"]
    standard = [s for s in scored if s.tier == "standard"]

    lines = [
        f"🤖 Nakeeb AI Daily Radar — {date_str}",
        "",
        "📊 **Run Summary**",
        f"• Sources: {run_metadata.get('sources_success', 0)}/{run_metadata.get('sources_attempted', 0)} successful",
        f"• Discovered: {run_metadata.get('discoveries_new', 0)} new items",
        f"• Scored: {len(scored)} ({len(standard)} Standard, {len(reverse_engineered)} Reverse-Engineered)",
        f"• LLM Calls: {run_metadata.get('llm_calls', 0)} | Quota: {run_metadata.get('quota_status', 'OK')}",
        f"• Duration: {run_metadata.get('duration_seconds', 0)}s",
        "",
    ]

    # Top opportunities (reverse engineered)
    if reverse_engineered:
        lines.append("🏆 **Top Opportunities** (Score ≥ 80)")
        lines.append("")
        for s in reverse_engineered[:5]:
            title = s.enriched.discovery.original_title[:80]
            score = s.total
            url = s.enriched.discovery.original_url
            brief_link = f"{base_url}/reports/briefs/{s.enriched.discovery.stable_id[:16]}.md"
            reverse_link = f"{base_url}/reports/reverse/{s.enriched.discovery.stable_id[:16]}.md"
            lines.append(f"🔹 **{title}** ({score}/100)")
            lines.append(f"   {s.reasoning.get('practical_usefulness', 'High practical value')[:100]}")
            lines.append(f"   🔗 {url}")
            lines.append(f"   📋 [Brief]({brief_link}) | [Reverse]({reverse_link})")
            lines.append("")

    # Standard briefs
    if standard:
        lines.append("📋 **Standard Briefs** (Score 65–79)")
        lines.append("")
        for s in standard[:5]:
            title = s.enriched.discovery.original_title[:80]
            score = s.total
            url = s.enriched.discovery.original_url
            brief_link = f"{base_url}/reports/briefs/{s.enriched.discovery.stable_id[:16]}.md"
            lines.append(f"🔸 **{title}** ({score}/100)")
            lines.append(f"   {s.reasoning.get('practical_usefulness', 'Good utility')[:100]}")
            lines.append(f"   🔗 {url}")
            lines.append(f"   📋 [Brief]({brief_link})")
            lines.append("")

    # Trends (simplified)
    if scored:
        lines.append("📈 **Trends**")
        lines.append("")
        # Count by source
        from collections import Counter
        source_counts = Counter(s.enriched.discovery.source_id for s in scored)
        for src, count in source_counts.most_common(3):
            lines.append(f"• {src}: {count} items")
        lines.append("")

    # Flags
    quota_status = run_metadata.get("quota_status", "OK")
    if quota_status != "OK":
        lines.append("⚠️ **Flags**")
        lines.append(f"• {quota_status}")
        lines.append("")

    lines.append(f"🤖 *Nakeeb AI v2.1 | Run: {run_id}*")
    lines.append(f"*Next run: ~6 hours*")

    return "\n".join(lines)


def build_technical_only_digest(
    discoveries: list[dict],
    run_metadata: dict,
) -> str:
    """Build digest when LLM is unavailable (metadata-only)."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = run_metadata.get("run_id", "unknown")

    lines = [
        f"🤖 Nakeeb AI Daily Radar (TECHNICAL ONLY) — {date_str}",
        "",
        "📊 **Run Summary** (No LLM enrichment)",
        f"• Sources: {run_metadata.get('sources_success', 0)}/{run_metadata.get('sources_attempted', 0)} successful",
        f"• Discovered: {run_metadata.get('discoveries_new', 0)} items",
        f"• ⚠️ LLM unavailable — qualitative assessments incomplete",
        "",
        "📋 **Top by Metadata**",
        "",
    ]

    # Sort by stars, recency
    sorted_disc = sorted(
        discoveries,
        key=lambda d: (d.get("stars", 0), d.get("fetched_at", "")),
        reverse=True,
    )

    for d in sorted_disc[:10]:
        title = d.get("title", "Untitled")[:80]
        stars = d.get("stars", 0)
        url = d.get("url", "")
        lines.append(f"🔸 **{title}** ⭐{stars}")
        lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append(f"🤖 *Nakeeb AI v2.1 | Run: {run_id} | Mode: TECHNICAL_ONLY*")

    return "\n".join(lines)


async def publish_digest(
    scored: list[ScoredDiscovery],
    run_metadata: dict,
    index: DiscoveryIndex,
    bot_token: str,
    chat_id: int,
    base_url: str = "https://raw.githubusercontent.com/nakeeb-ai/nakeeb-intel/main",
) -> PublishResult:
    """Publish digest to Telegram."""
    if not scored:
        digest = build_technical_only_digest([], run_metadata)
    else:
        digest = build_digest(scored, run_metadata, index, base_url)

    publisher = TelegramPublisher(bot_token, chat_id)
    try:
        return await publisher.send_message(digest)
    finally:
        await publisher.close()