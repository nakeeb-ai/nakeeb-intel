"""
Nakeeb AI - Event Sourcing & Index
Append-only event log + rebuildable SQLite.
"""

from __future__ import annotations

import fcntl
import json
import sqlite3
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Iterator
from uuid import uuid4

from .errors import EventStoreError, ConcurrencyError
from .intake import Discovery
from .score import ScoredDiscovery


# Event types
EVENT_TYPES = {
    "discovery_created",
    "enriched",
    "scored",
    "brief_generated",
    "reverse_engineered",
    "status_changed",
    "source_error",
    "run_started",
    "run_completed",
    "quota_exhausted",
    "all_providers_unavailable",
    "publish_error",
    "backup_completed",
    "backup_failed",
    "command_received",
    "command_processed",
    "missed_run_detected",
    "index_locked",
}


@dataclass
class Event:
    """Event in the append-only log."""
    schema_version: int = 1
    event_id: str = field(default_factory=lambda: str(uuid4()))
    discovery_id: str = ""
    event_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict = field(default_factory=dict)
    source_run_id: str = ""

    def __post_init__(self):
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.event_type}")

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "Event":
        data = json.loads(line)
        return cls(**data)


class EventStore:
    """Append-only event log with file locking."""

    def __init__(self, events_path: Path):
        self.events_path = events_path
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file_handle: Optional[Any] = None

    @contextmanager
    def _locked_file(self, mode: str = "a"):
        """Context manager for file locking."""
        with self._lock:
            fh = open(self.events_path, mode, encoding="utf-8")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                yield fh
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                fh.close()

    def append(self, event: Event) -> None:
        """Append event to log (atomic with locking)."""
        line = event.to_jsonl() + "\n"
        with self._locked_file("a") as fh:
            fh.write(line)
            fh.flush()

    def append_batch(self, events: list[Event]) -> None:
        """Append multiple events atomically."""
        lines = "".join(e.to_jsonl() + "\n" for e in events)
        with self._locked_file("a") as fh:
            fh.write(lines)
            fh.flush()

    def read_all(self) -> Iterator[Event]:
        """Read all events from log."""
        if not self.events_path.exists():
            return
        with self._locked_file("r") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield Event.from_jsonl(line)

    def get_events_for_discovery(self, discovery_id: str) -> list[Event]:
        """Get all events for a specific discovery."""
        return [e for e in self.read_all() if e.discovery_id == discovery_id]

    def get_last_run_id(self) -> Optional[str]:
        """Get the most recent source_run_id."""
        run_ids = set()
        for event in self.read_all():
            if event.source_run_id:
                run_ids.add(event.source_run_id)
        return sorted(run_ids)[-1] if run_ids else None

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """Verify event log integrity."""
        errors = []
        seen_ids = set()
        for i, event in enumerate(self.read_all()):
            if event.event_id in seen_ids:
                errors.append(f"Duplicate event_id at line {i}: {event.event_id}")
            seen_ids.add(event.event_id)
            if event.event_type not in EVENT_TYPES:
                errors.append(f"Unknown event_type at line {i}: {event.event_type}")
        return len(errors) == 0, errors


# SQLite Schema
SCHEMA_SQL = """
-- Nakeeb AI Discovery Index
-- Rebuildable from events.jsonl
-- This file is the source of truth for schema

CREATE TABLE IF NOT EXISTS discoveries (
    stable_id       TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL UNIQUE,
    canonical_url   TEXT NOT NULL,
    original_url    TEXT NOT NULL,
    original_title  TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_discoveries_source ON discoveries(source_id);
CREATE INDEX IF NOT EXISTS idx_discoveries_fetched ON discoveries(fetched_at);
CREATE INDEX IF NOT EXISTS idx_discoveries_fingerprint ON discoveries(fingerprint);

CREATE TABLE IF NOT EXISTS enrichments (
    stable_id       TEXT PRIMARY KEY REFERENCES discoveries(stable_id),
    name            TEXT,
    description     TEXT,
    repo_url        TEXT,
    owner           TEXT,
    license         TEXT,
    stars           INTEGER DEFAULT 0,
    forks           INTEGER DEFAULT 0,
    last_commit     TEXT,
    releases        TEXT,  -- JSON
    dependencies    TEXT,  -- JSON
    install_reqs    TEXT,
    api_pricing     TEXT,
    hosting_reqs    TEXT,
    hardware_reqs   TEXT,
    free_tier       TEXT,
    security_notes  TEXT,
    provenance      TEXT,  -- JSON
    confidence      TEXT,  -- JSON
    missing_info    TEXT,  -- JSON
    enrich_errors   TEXT,  -- JSON
    enriched_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scores (
    stable_id           TEXT PRIMARY KEY REFERENCES discoveries(stable_id),
    practical_usefulness INTEGER,
    technical_quality   INTEGER,
    free_access         INTEGER,
    documentation       INTEGER,
    maintenance         INTEGER,
    integration_potential INTEGER,
    originality         INTEGER,
    total_score         INTEGER,
    tier                TEXT,  -- reject, standard, reverse_engineer
    confidence          REAL,
    reasoning           TEXT,  -- JSON
    provenance          TEXT,  -- JSON
    missing_info        TEXT,  -- JSON
    flags               TEXT,  -- JSON
    config_hash         TEXT,
    scored_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_tier ON scores(tier);

CREATE TABLE IF NOT EXISTS briefs (
    stable_id       TEXT PRIMARY KEY REFERENCES discoveries(stable_id),
    content         TEXT,
    tier            TEXT,
    brief_id        TEXT,
    generated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT,  -- running, completed, failed
    sources_attempted INTEGER,
    sources_succeeded INTEGER,
    discoveries_new INTEGER,
    discoveries_dup INTEGER,
    scored_count    INTEGER,
    llm_calls       INTEGER,
    quota_usage     TEXT,  -- JSON
    error           TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL UNIQUE,
    discovery_id    TEXT,
    event_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    payload         TEXT,  -- JSON
    source_run_id   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_discovery ON events(discovery_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(source_run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
"""


class DiscoveryIndex:
    """SQLite index rebuilt from event log."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Initialize database with schema."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def rebuild_from_events(self, event_store: EventStore) -> dict[str, int]:
        """Rebuild entire index from event log. Returns counts."""
        # Clear tables (preserving schema)
        tables = ["discoveries", "enrichments", "scores", "briefs", "runs", "events"]
        for table in tables:
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()

        counts = {t: 0 for t in tables}

        for event in event_store.read_all():
            self._apply_event(event)
            counts["events"] += 1
            # Increment specific table counters
            if event.event_type == "discovery_created":
                counts["discoveries"] += 1
            elif event.event_type == "enriched":
                counts["enrichments"] += 1
            elif event.event_type == "scored":
                counts["scores"] += 1
            elif event.event_type == "brief_generated":
                counts["briefs"] += 1
            elif event.event_type in ("run_started", "run_completed"):
                counts["runs"] += 1

        self._conn.commit()
        return counts

    def _apply_event(self, event: Event):
        """Apply single event to index."""
        p = event.payload

        if event.event_type == "discovery_created":
            self._conn.execute("""
                INSERT OR REPLACE INTO discoveries
                (stable_id, fingerprint, canonical_url, original_url, original_title,
                 normalized_title, source_id, source_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p.get("stable_id"), p.get("fingerprint"), p.get("canonical_url"),
                p.get("original_url"), p.get("original_title"), p.get("normalized_title"),
                p.get("source_id"), p.get("source_url"), p.get("fetched_at"),
            ))

        elif event.event_type == "enriched":
            self._conn.execute("""
                INSERT OR REPLACE INTO enrichments
                (stable_id, name, description, repo_url, owner, license, stars, forks,
                 last_commit, releases, dependencies, install_reqs, api_pricing,
                 hosting_reqs, hardware_reqs, free_tier, security_notes,
                 provenance, confidence, missing_info, enrich_errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.discovery_id,
                p.get("name"), p.get("description"), p.get("repo_url"), p.get("owner"),
                p.get("license"), p.get("stars", 0), p.get("forks", 0), p.get("last_commit"),
                json.dumps(p.get("releases", [])), json.dumps(p.get("dependencies", [])),
                p.get("install_requirements"), p.get("api_pricing"),
                p.get("hosting_requirements"), p.get("hardware_requirements"),
                p.get("free_tier_compatibility"), p.get("security_notes"),
                json.dumps(p.get("provenance", {})), json.dumps(p.get("confidence", {})),
                json.dumps(p.get("missing_info", [])), json.dumps(p.get("enrichment_errors", [])),
            ))

        elif event.event_type == "scored":
            self._conn.execute("""
                INSERT OR REPLACE INTO scores
                (stable_id, practical_usefulness, technical_quality, free_access,
                 documentation, maintenance, integration_potential, originality,
                 total_score, tier, confidence, reasoning, provenance,
                 missing_info, flags, config_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.discovery_id,
                p.get("scores", {}).get("practical_usefulness", 0),
                p.get("scores", {}).get("technical_quality", 0),
                p.get("scores", {}).get("free_access", 0),
                p.get("scores", {}).get("documentation", 0),
                p.get("scores", {}).get("maintenance", 0),
                p.get("scores", {}).get("integration_potential", 0),
                p.get("scores", {}).get("originality", 0),
                p.get("total", 0), p.get("tier"), p.get("confidence", 0.0),
                json.dumps(p.get("reasoning", {})), json.dumps(p.get("provenance", {})),
                json.dumps(p.get("missing_info", [])), json.dumps(p.get("flags", [])),
                p.get("config_hash", ""),
            ))

        elif event.event_type == "brief_generated":
            self._conn.execute("""
                INSERT OR REPLACE INTO briefs (stable_id, content, tier, brief_id)
                VALUES (?, ?, ?, ?)
            """, (event.discovery_id, p.get("content"), p.get("tier"), p.get("brief_id")))

        elif event.event_type == "run_started":
            self._conn.execute("""
                INSERT INTO runs (run_id, started_at, status, sources_attempted)
                VALUES (?, ?, ?, ?)
            """, (event.source_run_id, event.timestamp, "running", p.get("sources_attempted", 0)))

        elif event.event_type == "run_completed":
            self._conn.execute("""
                UPDATE runs SET completed_at=?, status=?, sources_succeeded=?,
                    discoveries_new=?, discoveries_dup=?, scored_count=?,
                    llm_calls=?, quota_usage=?, error=?
                WHERE run_id=?
            """, (
                event.timestamp, p.get("status", "completed"),
                p.get("sources_succeeded", 0), p.get("discoveries_new", 0),
                p.get("discoveries_dup", 0), p.get("scored_count", 0),
                p.get("llm_calls", 0), json.dumps(p.get("quota_usage", {})),
                p.get("error"), event.source_run_id,
            ))

        # Always record in events table
        self._conn.execute("""
            INSERT OR IGNORE INTO events
            (event_id, discovery_id, event_type, timestamp, payload, source_run_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event.event_id, event.discovery_id, event.event_type,
            event.timestamp, json.dumps(event.payload), event.source_run_id,
        ))

    def query_discoveries(
        self,
        tier: str | None = None,
        min_score: int = 0,
        max_score: int = 100,
        source_id: str | None = None,
        domain: str | None = None,
        since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query discoveries with optional filters."""
        sql = """
            SELECT d.*, s.total_score, s.tier, s.confidence
            FROM discoveries d
            LEFT JOIN scores s ON d.stable_id = s.stable_id
            WHERE 1=1
        """
        params = []

        if tier:
            sql += " AND s.tier = ?"
            params.append(tier)
        if min_score > 0:
            sql += " AND s.total_score >= ?"
            params.append(min_score)
        if max_score < 100:
            sql += " AND s.total_score <= ?"
            params.append(max_score)
        if source_id:
            sql += " AND d.source_id = ?"
            params.append(source_id)
        if since:
            sql += " AND d.fetched_at >= ?"
            params.append(since)

        sql += " ORDER BY s.total_score DESC, d.fetched_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self._conn.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get index statistics."""
        stats = {}
        cursor = self._conn.execute("SELECT COUNT(*) FROM discoveries")
        stats["total_discoveries"] = cursor.fetchone()[0]

        cursor = self._conn.execute("SELECT tier, COUNT(*) FROM scores GROUP BY tier")
        stats["by_tier"] = dict(cursor.fetchall())

        cursor = self._conn.execute("SELECT source_id, COUNT(*) FROM discoveries GROUP BY source_id")
        stats["by_source"] = dict(cursor.fetchall())

        cursor = self._conn.execute("SELECT AVG(total_score) FROM scores WHERE total_score IS NOT NULL")
        avg = cursor.fetchone()[0]
        stats["avg_score"] = round(avg, 1) if avg else 0

        return stats

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


def verify_rebuild(event_store: EventStore, db_path: Path) -> dict:
    """
    Verify logical equivalence of rebuild.
    Builds temp DB from events, compares logical contents.
    """
    import tempfile
    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "temp_index.db"
        index = DiscoveryIndex(temp_db)
        counts = index.rebuild_from_events(event_store)
        index.close()

        # Compare with main DB (if exists)
        if db_path.exists():
            main_index = DiscoveryIndex(db_path)
            main_stats = main_index.get_stats()
            temp_stats = DiscoveryIndex(temp_db).get_stats()
            main_index.close()

            # Logical equivalence: same counts, same stats
            equivalent = (
                main_stats["total_discoveries"] == temp_stats["total_discoveries"] and
                main_stats["by_tier"] == temp_stats["by_tier"] and
                main_stats["by_source"] == temp_stats["by_source"]
            )

            return {
                "equivalent": equivalent,
                "main_stats": main_stats,
                "temp_stats": temp_stats,
                "rebuild_counts": counts,
            }

    return {
        "equivalent": True,  # No main DB to compare
        "rebuild_counts": counts,
    }
