"""
Nakeeb AI - Enrichment
Public metadata enrichment from verified sources.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path

import httpx
import yaml

from .intake import Discovery
from .errors import NakeebError, SourceError


@dataclass
class EnrichedDiscovery:
    """Discovery with enriched metadata."""
    discovery: Discovery
    # Verified fields with provenance
    name: str = ""
    description: str = ""
    repo_url: str = ""
    owner: str = ""
    license: str = ""
    stars: int = 0
    forks: int = 0
    last_commit: str = ""
    releases: list[dict] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    install_requirements: str = ""
    api_pricing: str = ""
    hosting_requirements: str = ""
    hardware_requirements: str = ""
    free_tier_compatibility: str = ""
    security_notes: str = ""
    # Provenance mapping: field -> source
    provenance: dict[str, str] = field(default_factory=dict)
    # Confidence per field
    confidence: dict[str, float] = field(default_factory=dict)
    # Missing info flags
    missing_info: list[str] = field(default_factory=list)
    # Enrichment errors
    enrichment_errors: list[str] = field(default_factory=list)


class Enricher:
    """Enriches discoveries with public metadata from verified sources."""

    def __init__(self, github_token: str | None = None, hf_token: str | None = None):
        self.github_token = github_token
        self.hf_token = hf_token
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "NakeebAI/2.1"}
            if self.github_token:
                headers["Authorization"] = f"token {self.github_token}"
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=headers)
        return self._client

    async def enrich(self, discovery: Discovery) -> EnrichedDiscovery:
        """Enrich a single discovery based on its source."""
        enriched = EnrichedDiscovery(discovery=discovery)

        try:
            if discovery.source_id == "github_user_events" or discovery.source_id == "github_repo_releases":
                await self._enrich_from_github(enriched)
            elif discovery.source_id == "hackernews":
                await self._enrich_from_hn(enriched)
            elif discovery.source_id == "arxiv":
                await self._enrich_from_arxiv(enriched)
            elif discovery.source_id == "hf_hub":
                await self._enrich_from_hf_hub(enriched)
            elif discovery.source_id.startswith("rss_"):
                await self._enrich_from_rss(enriched)
            elif discovery.source_id == "horizon_rss":
                await self._enrich_from_horizon(enriched)
        except Exception as e:
            enriched.enrichment_errors.append(f"{type(e).__name__}: {e}")

        return enriched

    async def _enrich_from_github(self, enriched: EnrichedDiscovery):
        """Enrich from GitHub API."""
        client = await self._get_client()
        url = enriched.discovery.canonical_url

        # Extract owner/repo from URL
        # https://github.com/owner/repo
        path_parts = url.path.strip("/").split("/")
        if len(path_parts) >= 2:
            owner, repo = path_parts[0], path_parts[1]

            # Get repo details
            response = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            if response.status_code == 200:
                data = response.json()
                enriched.name = data.get("name", "")
                enriched.description = data.get("description", "") or ""
                enriched.repo_url = data.get("html_url", "")
                enriched.owner = data.get("owner", {}).get("login", "")
                enriched.license = data.get("license", {}).get("spdx_id", "") if data.get("license") else ""
                enriched.stars = data.get("stargazers_count", 0)
                enriched.forks = data.get("forks_count", 0)
                enriched.last_commit = data.get("pushed_at", "")
                enriched.provenance.update({
                    "name": "github_api.repo.name",
                    "description": "github_api.repo.description",
                    "repo_url": "github_api.repo.html_url",
                    "owner": "github_api.repo.owner.login",
                    "license": "github_api.repo.license.spdx_id",
                    "stars": "github_api.repo.stargazers_count",
                    "forks": "github_api.repo.forks_count",
                    "last_commit": "github_api.repo.pushed_at",
                })

            # Get releases
            releases_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/releases")
            if releases_resp.status_code == 200:
                releases = releases_resp.json()
                enriched.releases = [
                    {"tag": r.get("tag_name", ""), "date": r.get("published_at", ""), "prerelease": r.get("prerelease", False)}
                    for r in releases[:10]
                    if r.get("published_at")
                ]
                enriched.provenance["releases"] = "github_api.repo.releases"

            # Get dependencies (check common files)
            for dep_file in ["requirements.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]:
                dep_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{dep_file}")
                if dep_resp.status_code == 200:
                    dep_data = dep_resp.json()
                    if isinstance(dep_data, dict) and dep_data.get("content"):
                        import base64
                        content = base64.b64decode(dep_data["content"]).decode("utf-8", errors="ignore")
                        enriched.dependencies.extend(self._parse_dependencies(dep_file, content))
                elif dep_resp.status_code == 404:
                    continue

            # Get README for install requirements, pricing, etc.
            readme_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/readme")
            if readme_resp.status_code == 200:
                readme_data = readme_resp.json()
                import base64
                readme = base64.b64decode(readme_data["content"]).decode("utf-8", errors="ignore")
                enriched.install_requirements = self._extract_section(readme, ["install", "setup", "usage", "getting started"])
                enriched.api_pricing = self._extract_section(readme, ["pricing", "cost", "free tier", "billing"])
                enriched.hosting_requirements = self._extract_section(readme, ["hosting", "deploy", "docker", "kubernetes"])
                enriched.hardware_requirements = self._extract_section(readme, ["gpu", "memory", "cpu", "hardware", "requirements"])
                enriched.free_tier_compatibility = self._extract_section(readme, ["free", "community", "no credit card", "self-hosted"])
                enriched.security_notes = self._extract_section(readme, ["security", "vulnerability", "audit", "safe"])

    def _parse_dependencies(self, filename: str, content: str) -> list[str]:
        """Parse dependency file."""
        deps = []
        if filename == "requirements.txt":
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append(line.split("==")[0].split(">=")[0].split("<=")[0].strip())
        elif filename == "pyproject.toml":
            # Simple extraction
            for line in content.splitlines():
                if "=" in line and ("dependencies" in content[:content.index(line)] or "requirements" in line.lower()):
                    dep = line.split("=")[1].strip().strip('"').strip("'")
                    if dep:
                        deps.append(dep)
        elif filename == "package.json":
            import json
            try:
                data = json.loads(content)
                deps.extend(data.get("dependencies", {}).keys())
                deps.extend(data.get("devDependencies", {}).keys())
            except Exception:
                pass
        return deps

    def _extract_section(self, text: str, keywords: list[str]) -> str:
        """Extract relevant section from text based on keywords."""
        lines = text.splitlines()
        relevant = []
        in_section = False
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                in_section = True
                relevant.append(line)
            elif in_section and line.strip() and not line.startswith((" ", "\t", "#", "-", "*")):
                # End of section
                in_section = False
            elif in_section:
                relevant.append(line)
        return "\n".join(relevant[:20])  # Limit length

    async def _enrich_from_hn(self, enriched: EnrichedDiscovery):
        """Enrich from Hacker News (limited metadata)."""
        disc = enriched.discovery
        enriched.name = disc.original_title
        enriched.description = disc.metadata.get("content", "")[:500]
        enriched.provenance["name"] = "hn_api.title"
        enriched.provenance["description"] = "hn_api.text"

    async def _enrich_from_arxiv(self, enriched: EnrichedDiscovery):
        """Enrich from arXiv."""
        disc = enriched.discovery
        enriched.name = disc.original_title
        enriched.description = disc.metadata.get("summary", "")[:500]
        enriched.repo_url = disc.metadata.get("link", "")
        enriched.provenance["name"] = "arxiv_api.title"
        enriched.provenance["description"] = "arxiv_api.summary"

    async def _enrich_from_hf_hub(self, enriched: EnrichedDiscovery):
        """Enrich from Hugging Face Hub."""
        disc = enriched.discovery
        enriched.name = disc.metadata.get("modelId", disc.original_title)
        enriched.description = disc.metadata.get("description", "")[:500] if disc.metadata.get("description") else ""
        enriched.repo_url = f"https://huggingface.co/{disc.metadata.get('modelId', '')}"
        enriched.stars = disc.metadata.get("likes", 0)
        enriched.provenance["name"] = "hf_api.modelId"
        enriched.provenance["description"] = "hf_api.description"

    async def _enrich_from_rss(self, enriched: EnrichedDiscovery):
        """Enrich from RSS feed."""
        disc = enriched.discovery
        enriched.name = disc.original_title
        enriched.description = disc.metadata.get("content", "")[:500]
        enriched.provenance["name"] = "rss_feed.title"
        enriched.provenance["description"] = "rss_feed.content"

    async def _enrich_from_horizon(self, enriched: EnrichedDiscovery):
        """Enrich from Horizon output (already structured)."""
        disc = enriched.discovery
        # Horizon ContentItem already has structured metadata
        enriched.name = disc.original_title
        enriched.description = disc.metadata.get("content", "")[:500]
        enriched.provenance["name"] = "horizon.ContentItem.title"
        enriched.provenance["description"] = "horizon.ContentItem.content"

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


async def enrich_batch(
    discoveries: list[Discovery],
    github_token: str | None = None,
    hf_token: str | None = None,
    concurrency: int = 5,
) -> list[EnrichedDiscovery]:
    """Enrich a batch of discoveries with controlled concurrency."""
    enricher = Enricher(github_token, hf_token)
    semaphore = asyncio.Semaphore(concurrency)

    async def enrich_one(d: Discovery) -> EnrichedDiscovery:
        async with semaphore:
            return await enricher.enrich(d)

    try:
        results = await asyncio.gather(*[enrich_one(d) for d in discoveries])
        return list(results)
    finally:
        await enricher.close()