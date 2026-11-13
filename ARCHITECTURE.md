# Architecture — Nakeeb AI v2.1

**Status:** Phase 1 — Foundation  
**Audit:** Phase 0 complete — CONDITIONAL GO  
**Decision Log:** `PHASE0_DECISIONS.md`

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        NAKEEB AI – OPPORTUNITY INTELLIGENCE                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │  C1     │───▶│  C2     │───▶│  C3     │───▶│  C4     │───▶│  C6     │  │
│  │ Radar   │    │ Intake  │    │Enrich   │    │ Brief   │    │Publish  │  │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘  │
│         ▲                                                        │        │
│         │                    ┌─────────┐                         │        │
│         └────────────────────│  C5     │◀────────────────────────┘        │
│                              │Commands │                                  │
│                              └─────────┘                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Specifications

### C1 — Radar (Source Collection)
**Location:** `src/radar/` (to be created in Phase 2)

**Approved Sources:**
| Source | Adapter | Auth | Rate Limit | Status |
|--------|---------|------|------------|--------|
| GitHub API | `GitHubAdapter` | Fine-grained PAT | 5,000/hr | READY |
| Hacker News | `HNAdapter` | None | No limit | READY |
| arXiv | `ArxivAdapter` | None | 3 sec/request | READY |
| HF Hub | `HFHubAdapter` | Token (optional) | No limit | READY |
| RSS Feeds | `RSSAdapter` | None | Publisher | READY |
| Horizon | `HorizonAdapter` | Optional LLM | N/A | SUITABLE |

**Source Interface:**
```python
class SourceAdapter(ABC):
    @abstractmethod
    async def fetch(self, since: datetime) -> FetchResult:
        """Return items + per-source failures"""
    
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier: github, hn, arxiv, hf_hub, rss, horizon"""
```

**Failure Isolation:** Each source runs independently; failures recorded as `source_error` events.

---

### C2 — Intake & Deduplication
**Location:** `src/intake.py`, `src/dedup.py`

**URL Normalization:**
- Lowercase host
- Strip tracking params (`utm_*`, `fbclid`, `gclid`, etc.)
- Normalize path (remove trailing slash)
- Preserve meaningful query params

**Fingerprint:** `sha256(canonical_url + "|" + normalized_title)`
**Stable ID:** `sha256(canonical_url)`

**Dedup Rules:**
- Exact duplicates (same stable ID) → auto-grouped
- Fuzzy ≥0.92 (title similarity) → candidate for human review
- Never auto-merge unrelated

---

### C3 — Enrichment & Scoring
**Location:** `src/enrich.py`, `src/score.py`, `src/quota.py`, `src/llm.py`

**Metadata Collected (with provenance):**
| Field | Source | Verifiable |
|-------|--------|------------|
| name, description | Source | YES |
| repo URL, owner | GitHub API | YES |
| license | GitHub API / SPDX | YES |
| stars, forks | GitHub API | YES |
| last commit | GitHub API | YES |
| release activity | GitHub API | YES |
| dependencies | requirements.txt / pyproject.toml | YES |
| install requirements | README / docs | YES |
| API pricing tier | Provider docs | YES |
| hosting requirements | README / docs | YES |
| hardware requirements | README / docs | YES |
| free-tier compatibility | Provider docs | YES |
| security notes | Advisories / code review | PARTIAL |

**Deterministic 100-Point Rubric:**
| Criterion | Weight | Max |
|-----------|--------|-----|
| Practical usefulness | 20 | 20 |
| Technical quality | 20 | 20 |
| Free / low-cost access | 15 | 15 |
| Documentation | 15 | 15 |
| Activity / maintenance | 10 | 10 |
| Integration potential | 10 | 10 |
| Originality / opportunity | 10 | 10 |
| **Total** | | **100** |

**LLM Enrichment (Optional):**
- Provider: Gemini Decision 1 (primary), OpenRouter free (fallback)
- Output marked as `ASSESSMENT` not verified fact
- Confidence + missing-info flags stored
- Identical input + config = same stored score

**Thresholds:**
- 65–79: Standard opportunity brief
- 80–100: Standard brief + reverse-engineering report

---

### C4 — Brief & Reverse Engineering
**Location:** `src/brief.py` (to be created in Phase 3)

**Standard Brief Sections:**
1. Executive summary
2. What it does
3. Why it matters
4. Capabilities
5. Architecture
6. Tech stack
7. Install requirements
8. Operating costs
9. Free-tier compatibility
10. License
11. Security notes
12. Integration options
13. Limitations
14. Practical use cases
15. Suggested experiments
16. Evidence links
17. Recommendation
18. Confidence + missing-info flags

**Reverse-Engineering Report (Score ≥80):**
- Architecture & components
- Data flow
- Model usage
- Agent orchestration
- Memory strategy
- Tool integrations
- Deployment strategy
- Performance
- Cost structure
- Licensing
- Security
- Strengths / weaknesses
- Reproducibility
- Potential improvements
- Practical opportunities

---

### C5 — Command Router (Deferred)
**Location:** `workers/telegram-router/` (Phase 5+)

**Current Implementation:** GitHub Actions `repository_dispatch`
- Commands: `/status`, `/analyze <id>`, `/verify <id>`, `/cost <id>`, `/buildplan <id>`, `/help`
- Trigger: `gh api repos/nakeeb-ai/nakeeb-intel/dispatches --field event_type=command --field client_payload='{"cmd": "...", "chat_id": ...}'`
- Response: Published via C6

**Cloudflare Worker (Future):**
- Minimal dispatch only (10ms CPU limit)
- Webhook secret verification
- Chat ID allowlist
- Update ID deduplication
- No arbitrary execution

---

### C6 — Publish & Archive
**Location:** `src/publish.py`, `src/archive.py` (Phase 3/6)

**Telegram Digest:**
- One per successful cycle
- ≤ 3,800 chars
- Title, score, confidence, source, report link
- Failure → `publish_error` event (discoveries preserved)

**Google Drive (Phase 6):**
- rclone crypt encryption
- SHA-256 manifest
- Isolated restore test required
- Temporary config, cleanup on exit

---

## Event Sourcing

**Source of Truth:** `index/events.jsonl` (append-only, committed)
**Derived DB:** `index/discoveries.db` (rebuildable, gitignored)

**Event Schema:**
```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "discovery_id": "sha256",
  "event_type": "discovery_created|enriched|scored|brief_generated|...",
  "timestamp": "ISO8601",
  "payload": {},
  "source_run_id": "uuid"
}
```

**Event Types:**
- `discovery_created`, `enriched`, `scored`, `brief_generated`, `reverse_engineered`
- `status_changed`, `source_error`, `run_started`, `run_completed`
- `quota_exhausted`, `all_providers_unavailable`, `publish_error`
- `backup_completed`, `backup_failed`, `command_received`, `command_processed`
- `missed_run_detected`, `index_locked`

**Integrity:**
- Unique event IDs
- Idempotent replay
- File-level lock during writes
- Workflow-level concurrency control
- Max 3 rebase/retry attempts
- Logical equivalence rebuild test

---

## Data Flow

```
┌──────────────┐
│  SCHEDULED   │
│  (GitHub     │
│   Actions)   │
└──────┬───────┘
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  VALIDATE    │────▶│  REBUILD     │────▶│  COLLECT     │
│  ENV + EVENT │     │  SQLITE      │     │  SOURCES     │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  APPEND      │◀────│  SCORE +     │◀────│  DEDUP +     │
│  EVENTS      │     │  ENRICH      │     │  ENRICH      │
└──────┬───────┘     └──────────────┘     └──────────────┘
       ▼
┌──────────────┐     ┌──────────────┐
│  PUBLISH     │────▶│  ARCHIVE     │
│  (Telegram)  │     │  (Drive)     │
└──────────────┘     └──────────────┘
```

---

## Configuration Files

| File | Purpose | Phase |
|------|---------|-------|
| `config/sources.yaml` | Source definitions + scheduling | 1 |
| `config/profiles/ai-tools.yaml` | Domain 1 profile | 1 |
| `config/profiles/agent-engineering.yaml` | Domain 2 profile | 1 |
| `config/quotas.yaml` | Internal safety caps | 1 |
| `prompts/*.md` | LLM prompt templates | 3 |

---

## Security Boundaries

| Boundary | Control |
|----------|---------|
| Secrets | GitHub Actions Secrets only; never in code/logs |
| Telegram | Chat ID allowlist, webhook secret, update_id dedup, command allowlist |
| Input | URL allowlist, size limits (200 chars), no arbitrary execution |
| LLM | No private data sent; free-tier only; circuit breaker |
| Filesystem | `.gitignore` excludes secrets, DB, private reports |
| Supply Chain | Pinned dependencies; no unreviewed actions |

---

## Deployment Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        GITHUB ACTIONS                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ daily-radar │  │  weekly-    │  │  on-demand  │              │
│  │  (4×/day)   │  │  digest     │  │             │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
└─────────┼────────────────┼────────────────┼─────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NAKEEB-INTEL REPO                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ events.jsonl│  │ reports/    │  │ index/      │              │
│  │ (committed) │  │ (committed) │  │ discoveries │              │
│  └─────────────┘  └─────────────┘  │   .db       │              │
│                                     │ (gitignored)│              │
│                                     └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
          │                                    │
          ▼                                    ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│   HUGGING FACE          │         │    GOOGLE DRIVE         │
│   STATIC SPACE          │         │    (rclone crypt)       │
│   (dashboard)           │         │    (Phase 6)            │
│   Reads raw.githubusercontent.com/                               │
│   nakeeb-ai/nakeeb-intel/                                        │
│   main/index/events.jsonl                                        │
└─────────────────────────┘         └─────────────────────────┘
```

---

## Decisions Log

See `PHASE0_DECISIONS.md` for all evidence-driven decisions.

Key decisions:
- **D-GITHUB-01:** Repository MUST be PUBLIC
- **D-HORIZON-01:** Horizon SUITABLE for C1 (RSS-only)
- **D-AI-01:** Gemini Decision 1 primary, OpenRouter free fallback
- **D-CLOUDFLARE-01:** Worker deferred to Phase 5+
- **D-DRIVE-01:** Drive backup deferred to Phase 6
- **D-TELEGRAM-01:** Commands deferred (option c)

---

## Non-Goals

- ❌ No paid APIs, hosting, VPS
- ❌ No automatic trading/financial execution
- ❌ No private data collection
- ❌ No always-on processes
- ❌ No Docker/systemd/root requirements
- ❌ No modification of existing projects (Hermes, etc.)