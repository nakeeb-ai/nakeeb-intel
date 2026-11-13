# Nakeeb AI – Opportunity Intelligence v2.1

> **Automated discovery, evaluation, and briefing on public open-source AI tools and AI agent engineering projects.**

---

## Overview

This system autonomously:

1. **Discovers** public AI tools & agent engineering projects from approved sources (GitHub, RSS, Hacker News, arXiv, Hugging Face Hub)
2. **Normalizes & deduplicates** discoveries with provenance tracking
3. **Enriches** with verifiable public metadata (stars, license, activity, dependencies, free-tier compatibility)
4. **Scores** using a deterministic 100-point rubric (practical usefulness, technical quality, free access, documentation, maintenance, integration potential, originality)
5. **Generates** evidence-backed opportunity briefs + reverse-engineering reports (score ≥80)
6. **Publishes** daily Telegram digests
7. **Archives** encrypted to Google Drive (Phase 6)
8. **Displays** results via Hugging Face Static dashboard

---

## Architecture (v2.1)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   C1 Radar  │────▶│  C2 Intake  │────▶│  C3 Enrich  │────▶│  C4 Brief   │
│  (Sources)  │     │  (Dedup)    │     │  (Score)    │     │  (Reports)  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                                    │
                                                                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  C6 Archive │◀────│ C5 Commands │◀────│  C6 Publish │◀────│  (Events)   │
│ (Drive)     │     │ (Telegram)  │     │ (Digest)    │     │ (JSONL)     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

**Six Logical Components:**
- **C1 Radar** — Source adapters (GitHub, RSS, HN, arXiv, HF Hub, Horizon)
- **C2 Intake** — URL normalization, fingerprinting, deduplication
- **C3 Enrichment** — Public metadata, deterministic scoring, LLM enrichment (optional)
- **C4 Brief** — Opportunity briefs + reverse-engineering reports
- **C5 Commands** — Telegram bot via GitHub Actions dispatch (Cloudflare Worker deferred)
- **C6 Publish/Archive** — Telegram digest, event log, encrypted Drive backup

---

## Quick Start

```bash
# Clone
git clone https://github.com/nakeeb-ai/nakeeb-intel.git
cd nakeeb-intel

# Install dependencies
python3 -m pip install -r requirements.txt --break-system-packages

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run locally
python3 -m src.cli --help
python3 -m src.cli run --dry-run
```

---

## Configuration

| File | Purpose |
|------|---------|
| `config/sources.yaml` | Source definitions (GitHub, RSS, HN, arXiv, HF Hub) |
| `config/profiles/ai-tools.yaml` | Domain 1 profile |
| `config/profiles/agent-engineering.yaml` | Domain 2 profile |
| `config/quotas.yaml` | Internal safety caps (NOT provider guarantees) |
| `prompts/*.md` | LLM prompt templates |

---

## Domains (Initial)

| Domain | Description |
|--------|-------------|
| **1. Open-Source AI Tools** | Public GitHub repos, AI tools, model projects, libraries, APIs |
| **2. AI Agent Engineering** | Agent architectures, orchestration, memory, tools, evaluation |

*Deferred: AI Business Automation, AI Content, Financial Research, Model/API Discovery*

---

## Automation

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `daily-radar.yml` | 4×/day (00:17, 06:17, 12:17, 18:17 UTC) | Main collection pipeline |
| `weekly-digest.yml` | Weekly (Monday 00:17) | Weekly summary |
| `on-demand.yml` | Manual | Ad-hoc runs |
| `pre-commit.yml` | Per PR | Lint, test, secret scan |

---

## Dashboard

**Hugging Face Static Space:** Reads `https://raw.githubusercontent.com/nakeeb-ai/nakeeb-intel/main/index/events.jsonl`

- Filters: domain, date, score, source
- Search, verification status, last-update timestamp
- No backend — pure HTML/CSS/JS

---

## Security

- **Secrets:** GitHub Actions Secrets only (never in code/logs)
- **Telegram:** Chat ID allowlist, webhook secret verification, update_id deduplication
- **Input validation:** URL allowlists, command allowlist, size limits
- **Pre-commit:** gitleaks, ruff, pytest

---

## Cost Policy

**$0 ONLY** — No paid APIs, hosting, VPS, or payment-dependent trials.

| Service | Tier | Cost |
|---------|------|------|
| GitHub Actions | Public repo | Free (unlimited) |
| Hugging Face Static Space | Static SDK | Free |
| Google Gemini API | Free tier (verified) | Free |
| OpenRouter | Free router | Free |
| Cloudflare Workers | Free tier (deferred) | Free |
| Google Drive | rclone crypt | Free (15 GB) |

---

## License

MIT — See [LICENSE](LICENSE)

---

## Status

**Phase 1 — Foundation** — See [CHANGELOG](CHANGELOG.md)