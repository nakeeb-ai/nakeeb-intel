#!/usr/bin/env python3
"""
Nakeeb AI - Main CLI
Orchestrates the full pipeline: collect → dedup → enrich → score → brief → publish
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from .errors import NakeebError, ConfigurationError
from .quota import QuotaManager
from .intake import Discovery, process_source_batch, Deduplicator, canonicalize_url
from .enrich import enrich_batch
from .score import score_batch
from .index import EventStore, DiscoveryIndex, Event, DiscoveryIndex
from .publish import publish_digest, build_technical_only_digest
from .llm import LLMManager
from .rebuild_db import main as rebuild_main


# Load environment
REPO_ROOT = Path(__file__).parent.parent
load_dotenv(REPO_ROOT / ".env")


def get_env(key: str, default: str = "") -> str:
    """Get env var with fallback to .env."""
    return os.environ.get(key, default)


async def run_pipeline(
    dry_run: bool = False,
    since_hours: int = 24,
    profile: str = "both",
    max_items: int = 100,
) -> dict[str, Any]:
    """Run the full collection pipeline."""
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"🚀 Starting run: {run_id}")

    # Initialize components
    quota_path = REPO_ROOT / "config" / "quotas.yaml"
    quota = QuotaManager(quota_path)
    quota.reset_run()

    events_path = REPO_ROOT / "index" / "events.jsonl"
    event_store = EventStore(events_path)
    index = DiscoveryIndex(REPO_ROOT / "index" / "discoveries.db")

    # Load deduplicator with existing discoveries
    dedup = Deduplicator()
    existing = list(index.query_discoveries(limit=10000))
    dedup.load_existing([
        Discovery(
            stable_id=d["stable_id"],
            fingerprint=d["fingerprint"],
            canonical_url=canonicalize_url(d["canonical_url"]),
            original_url=d["original_url"],
            original_title=d["original_title"],
            normalized_title=d["normalized_title"],
            source_id=d["source_id"],
            source_url=d["source_url"],
        )
        for d in existing
    ])

    # Load LLM manager
    env = dict(os.environ)
    llm = LLMManager(quota, env)

    # Run started event
    run_started = Event(
        discovery_id="",
        event_type="run_started",
        source_run_id=run_id,
        payload={
            "run_id": run_id,
            "started_at": started_at,
            "since_hours": since_hours,
            "profile": profile,
        },
    )
    event_store.append(run_started)

    # Track metrics
    metrics = {
        "run_id": run_id,
        "started_at": started_at,
        "sources_attempted": 0,
        "sources_succeeded": 0,
        "discoveries_new": 0,
        "discoveries_dup": 0,
        "enriched_count": 0,
        "scored_count": 0,
        "llm_calls": 0,
        "quota_status": "OK",
        "errors": [],
    }

    # === SOURCE COLLECTION (simplified - Phase 2 will implement adapters) ===
    # For now, create mock discoveries for testing
    print("📡 Collecting from sources...")

    # Mock source data for testing
    mock_sources = [
        {
            "id": "github_user_events",
            "items": [
                {
                    "url": "https://github.com/pydantic/pydantic",
                    "title": "Pydantic v2.10 released with performance improvements",
                    "source_url": "https://api.github.com/repos/pydantic/pydantic/releases",
                    "metadata": {"event_type": "ReleaseEvent", "repo": "pydantic/pydantic"},
                },
            ],
        },
        {
            "id": "hackernews",
            "items": [
                {
                    "url": "https://news.ycombinator.com/item?id=50472038",
                    "title": "Rust 1.100 released",
                    "source_url": "https://hacker-news.firebaseio.com/v0/item/50472038.json",
                    "metadata": {"score": 419, "by": "rust_user"},
                },
            ],
        },
        {
            "id": "rss_simon_willison",
            "items": [
                {
                    "url": "https://simonwillison.net/2026/Nov/12/llm-gemini/",
                    "title": "llm-gemini 0.37 released",
                    "source_url": "https://simonwillison.net/atom/everything/",
                    "metadata": {"category": "ai-tools", "feed_name": "Simon Willison"},
                },
            ],
        },
    ]

    metrics["sources_attempted"] = len(mock_sources)

    all_new_discoveries = []
    all_duplicate_info = []

    for source in mock_sources:
        try:
            metrics["sources_succeeded"] += 1
            new_discs, dup_info = await process_source_batch(
                source["items"], source["id"], dedup
            )
            all_new_discoveries.extend(new_discs)
            all_duplicate_info.extend(dup_info)
        except Exception as e:
            metrics["errors"].append(f"Source {source['id']}: {e}")
            # Record source_error event
            event_store.append(Event(
                discovery_id="",
                event_type="source_error",
                source_run_id=run_id,
                payload={"source_id": source["id"], "error": str(e)},
            ))

    metrics["discoveries_new"] = len(all_new_discoveries)
    metrics["discoveries_dup"] = len(all_duplicate_info)

    # Record discovery_created events
    discovery_events = []
    for disc in all_new_discoveries:
        discovery_events.append(Event(
            discovery_id=disc.stable_id,
            event_type="discovery_created",
            source_run_id=run_id,
            payload=disc.to_dict(),
        ))
    event_store.append_batch(discovery_events)

    # === ENRICHMENT ===
    print(f"🔍 Enriching {len(all_new_discoveries)} discoveries...")
    github_token = get_env("GH_PAT_DISPATCH")  # Reuse for API calls
    hf_token = get_env("HF_API_KEY")

    if all_new_discoveries:
        enriched = await enrich_batch(all_new_discoveries, github_token, hf_token)
        metrics["enriched_count"] = len(enriched)

        # Record enriched events
        enriched_events = []
        for e in enriched:
            enriched_events.append(Event(
                discovery_id=e.discovery.stable_id,
                event_type="enriched",
                source_run_id=run_id,
                payload={
                    "name": e.name,
                    "description": e.description,
                    "repo_url": e.repo_url,
                    "owner": e.owner,
                    "license": e.license,
                    "stars": e.stars,
                    "forks": e.forks,
                    "last_commit": e.last_commit,
                    "releases": e.releases,
                    "dependencies": e.dependencies,
                    "install_requirements": e.install_requirements,
                    "api_pricing": e.api_pricing,
                    "hosting_requirements": e.hosting_requirements,
                    "hardware_requirements": e.hardware_requirements,
                    "free_tier_compatibility": e.free_tier_compatibility,
                    "security_notes": e.security_notes,
                    "provenance": e.provenance,
                    "confidence": e.confidence,
                    "missing_info": e.missing_info,
                    "enrichment_errors": e.enrichment_errors,
                },
            ))
        event_store.append_batch(enriched_events)

        # === SCORING ===
        print(f"📊 Scoring {len(enriched)} discoveries...")
        profile_path = REPO_ROOT / "config" / "profiles" / f"{profile}.yaml"
        if not profile_path.exists():
            profile_path = REPO_ROOT / "config" / "profiles" / "ai-tools.yaml"

        scored = await score_batch(enriched, profile_path, profile)
        metrics["scored_count"] = len(scored)

        # Record scored events
        scored_events = []
        for s in scored:
            scored_events.append(Event(
                discovery_id=s.enriched.discovery.stable_id,
                event_type="scored",
                source_run_id=run_id,
                payload=s.to_dict(),
            ))
        event_store.append_batch(scored_events)

        # === BRIEF GENERATION (simplified - Phase 3) ===
        # For now, just mark as standard/reverse_engineer

        # === PUBLISHING ===
        bot_token = get_env("BOT_TOKEN")
        chat_id_str = get_env("ADMIN_USER_ID")
        if bot_token and chat_id_str and not dry_run:
            print("📤 Publishing digest...")
            chat_id = int(chat_id_str)
            try:
                result = await publish_digest(scored, metrics, index, bot_token, chat_id)
                if result.success:
                    print(f"✅ Digest published (message_id: {result.message_id})")
                else:
                    print(f"❌ Publish failed: {result.error}")
                    event_store.append(Event(
                        discovery_id="",
                        event_type="publish_error",
                        source_run_id=run_id,
                        payload={"error": result.error},
                    ))
            except Exception as e:
                print(f"❌ Publish error: {e}")
                event_store.append(Event(
                    discovery_id="",
                    event_type="publish_error",
                    source_run_id=run_id,
                    payload={"error": str(e)},
                ))
        else:
            print("⏭️  Skipping publish (no bot config or dry_run)")

    # === FINALIZE ===
    completed_at = datetime.now(timezone.utc).isoformat()
    duration = (datetime.fromisoformat(completed_at.replace("Z", "+00:00")) -
                datetime.fromisoformat(started_at.replace("Z", "+00:00"))).total_seconds()

    metrics.update({
        "completed_at": completed_at,
        "duration_seconds": duration,
        "status": "completed" if not metrics["errors"] else "completed_with_errors",
        "quota_usage": quota.get_all_usage(),
    })

    # Record run_completed
    event_store.append(Event(
        discovery_id="",
        event_type="run_completed",
        source_run_id=run_id,
        payload=metrics,
    ))

    # Close
    await llm.close_all()
    index.close()

    print(f"\n✅ Run {run_id} completed in {duration:.1f}s")
    print(f"   New: {metrics['discoveries_new']}, Dup: {metrics['discoveries_dup']}")
    print(f"   Scored: {metrics['scored_count']}")
    print(f"   LLM calls: {metrics['llm_calls']}")

    return metrics


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Nakeeb AI Opportunity Intelligence v2.1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    run_parser = subparsers.add_parser("run", help="Run collection pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="Skip publishing")
    run_parser.add_argument("--since-hours", type=int, default=24, help="Collection window")
    run_parser.add_argument("--profile", choices=["ai-tools", "agent-engineering", "both"], default="both")
    run_parser.add_argument("--max-items", type=int, default=100, help="Max items per source")

    # rebuild command
    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild SQLite from events")

    # test command
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument("--coverage", action="store_true", help="Run with coverage")

    args = parser.parse_args()

    if args.command == "run":
        try:
            asyncio.run(run_pipeline(
                dry_run=args.dry_run,
                since_hours=args.since_hours,
                profile=args.profile,
                max_items=args.max_items,
            ))
        except NakeebError as e:
            print(f"❌ Pipeline error: {e.message}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted")
            sys.exit(130)
        except Exception as e:
            print(f"❌ Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "rebuild":
        rebuild_main()

    elif args.command == "test":
        import subprocess
        cmd = ["python", "-m", "pytest", "tests/", "-v"]
        if args.coverage:
            cmd.extend(["--cov=src", "--cov-report=term-missing"])
        subprocess.run(cmd, cwd=REPO_ROOT)


if __name__ == "__main__":
    main()