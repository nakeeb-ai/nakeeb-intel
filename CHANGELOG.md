# Changelog

All notable changes to Nakeeb AI – Opportunity Intelligence.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [2.1.0] - 2026-11-13

### Phase 0 — Audit Complete
- **CONDITIONAL GO** — Technical feasibility verified
- Horizon suitability gate **PASSED** (D-HORIZON-01: SUITABLE, commit `3239500`)
- Five public sources verified: GitHub API, Hacker News, arXiv, HF Hub, RSS
- AI providers verified: Gemini Decision 1 (primary), OpenRouter free (fallback)
- Repository visibility: **PUBLIC** mandated for $0 operations
- Google Drive backup: **DEFERRED** to Phase 6 (OAuth requires browser)
- Cloudflare Worker: **DEFERRED** to Phase 5+ (Wrangler install blocked)
- Telegram commands: **DEFERRED** (option c)

### Added
- Initial repository structure per v2.1 architecture
- Phase 0 audit reports (`/root/nakeeb-audit-phase0/`)
- Capability declaration with environment evidence

---

## [Unreleased] — Phase 1 — Foundation

### Planned
- Repository initialization with full directory structure
- Event sourcing engine (`index/events.jsonl`, SQLite rebuild)
- Deduplication engine (URL canonicalization + fingerprinting)
- Deterministic scoring engine (100-point rubric)
- Quota manager with internal safety caps
- Error handling & logging framework
- Unit tests: dedup, scoring, quota, event sourcing
- Pre-commit hooks (gitleaks, ruff, mypy, pytest)
- Configuration profiles: ai-tools, agent-engineering

---

## Version History

| Version | Date | Phase | Status |
|---------|------|-------|--------|
| 2.1.0 | 2026-11-13 | Phase 0 | Complete |
| 2.0.0 | — | — | (Hermes — separate project) |