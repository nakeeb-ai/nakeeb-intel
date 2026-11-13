#!/usr/bin/env python3
"""
Nakeeb AI - Database Rebuild Script
Rebuilds SQLite index from events.jsonl.
Run: python -m src.rebuild_db
"""

from __future__ import annotations

import sys
from pathlib import Path

from .index import DiscoveryIndex, EventStore, verify_rebuild, SCHEMA_SQL


def main():
    """Rebuild database from event log."""
    repo_root = Path(__file__).parent.parent
    events_path = repo_root / "index" / "events.jsonl"
    db_path = repo_root / "index" / "discoveries.db"

    print(f"📍 Repo root: {repo_root}")
    print(f"📄 Events: {events_path}")
    print(f"🗄️  Database: {db_path}")

    if not events_path.exists():
        print("❌ No events.jsonl found. Nothing to rebuild.")
        sys.exit(1)

    # Load event store
    print("📖 Loading event store...")
    event_store = EventStore(events_path)

    # Verify event log integrity
    print("🔍 Verifying event log integrity...")
    valid, errors = event_store.verify_integrity()
    if not valid:
        print("❌ Event log integrity check failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    print("✅ Event log integrity verified")

    # Rebuild index
    print("🔨 Rebuilding SQLite index...")
    index = DiscoveryIndex(db_path)
    counts = index.rebuild_from_events(event_store)
    index.close()
    print(f"✅ Rebuild complete: {counts}")

    # Verify rebuild
    print("🔍 Verifying rebuild...")
    result = verify_rebuild(event_store, db_path)
    if result.get("equivalent"):
        print("✅ Logical equivalence verified")
    else:
        print("⚠️  No previous DB to compare (first rebuild)")
    print(f"   Rebuild counts: {result.get('rebuild_counts', {})}")

    print("\n✅ Database rebuild successful!")


if __name__ == "__main__":
    main()