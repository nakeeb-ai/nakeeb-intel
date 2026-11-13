# Accepted Sources — Nakeeb AI v2.1

**Status:** Phase 0 verified — all sources tested and accessible
**Date:** 2026-11-13
**Policy:** Only sources with verified free access, no OAuth, no paid tiers required

---

## ✅ APPROVED SOURCES (Active)

| Source | Type | Auth | Rate Limit | Verification | Domains |
|--------|------|------|------------|--------------|---------|
| GitHub API | REST | Fine-grained PAT | 5,000/hr | ✅ Live test | Both |
| Hacker News | Firebase API | None | No published limit | ✅ Live test | Both |
| arXiv | OAI-PMH | None | 3 sec/request | ✅ Live test | Both |
| Hugging Face Hub | REST | Optional token | No published limit | ✅ Live test | Both |
| RSS Feeds | Atom/RSS | None | Publisher-dependent | ✅ Live test | Per feed |
| Horizon (RSS-only) | Python lib | Optional LLM | N/A | ✅ SUITABLE gate | Both |

---

## 📋 SOURCE DETAILS

### GitHub API
- **Endpoints:** `/users/{username}/events/public`, `/repos/{owner}/{repo}/releases`
- **Auth:** Fine-grained PAT with `repo` scope (read) on `nakeeb-ai/nakeeb-intel` only
- **Pagination:** Link header (`rel="next"`)
- **Data:** User events (Push, Create, Release, Public, Watch), repo releases
- **Relevance:** AI/ML keywords in repo name, description, commit messages
- **Verified:** 2026-11-13 — 30 events from torvalds, 200 OK

### Hacker News
- **Endpoints:** `/topstories.json`, `/item/{id}.json`
- **Auth:** None
- **Data:** Title, URL, score, author, timestamp, text, top comments
- **Filter:** Min score 100, top 30 stories, 5 comments each
- **Verified:** 2026-11-13 — 500 stories, 200 OK

### arXiv
- **Endpoint:** `https://export.arxiv.org/api/query`
- **Query:** `cat:cs.AI OR cat:cs.LG OR cat:cs.CL`
- **Auth:** None
- **Rate:** 3 seconds between requests (polite)
- **Data:** Title, authors, abstract, categories, PDF link, submitted date
- **Verified:** 2026-11-13 — 5 entries, 200 OK (301 redirect handled)

### Hugging Face Hub
- **Endpoint:** `https://huggingface.co/api/models`
- **Params:** `sort=downloads`, `limit=30`, filter tags
- **Auth:** Optional token for higher limits
- **Data:** modelId, downloads, tags, likes, lastModified
- **Verified:** 2026-11-13 — 5 models, 200 OK

### RSS Feeds (Curated)
| Feed | URL | Category | Extractor |
|------|-----|----------|-----------|
| Simon Willison | https://simonwillison.net/atom/everything/ | ai-tools | trafilatura |
| vLLM Blog | https://vllm.ai/blog/rss.xml | llm-inference | trafilatura |
| Sean Goedecke | https://www.seangoedecke.com/rss.xml | software-engineering | trafilatura |
| NVIDIA CUDA | https://developer.nvidia.com/blog/tag/cuda/feed/ | cuda | trafilatura |
| LangChain Blog | https://blog.langchain.dev/rss/ | agent-framework | trafilatura |
| CrewAI Blog | https://blog.crewai.com/rss/ | agent-framework | trafilatura |
| Anthropic News | https://www.anthropic.com/news/rss.xml | ai-research | trafilatura |

- **Auth:** None
- **Extractor:** trafilatura (full article content)
- **Verified:** 2026-11-13 — Simon Willison feed: 30 entries, 200 OK

### Horizon (RSS-only mode)
- **Repository:** https://github.com/Thysrael/Horizon
- **Commit:** `323950050b079d054a009aa02198d89aae48e8da`
- **License:** MIT
- **Mode:** RSS/Atom, GitHub, Hacker News scrapers WITHOUT LLM
- **Output:** `ContentItem` Pydantic models
- **Gate:** D-HORIZON-01 SUITABLE
- **Verified:** 2026-11-13 — Live RSS test successful

---

## ❌ REJECTED / DEFERRED SOURCES

| Source | Reason | Revisit Condition |
|--------|--------|-------------------|
| Reddit | OAuth required, API restrictions | Free tier + OAuth flow verified |
| X/Twitter | Paid API tiers only | Free access restored |
| Google News | No official API, scraping ToS | Official free API released |
| GDELT | Complex, requires review | Manual verification |
| OpenBB | Optional dependency, finance-focused | Domain 4+ activation |
| OSSInsight | Requires API key | Free tier verified |
| Telegram | Requires bot token | Dedicated bot created |
| Twitter (Playwright) | Browser automation, fragile | Official API alternative |

---

## 🔒 SOURCE ADDITION PROCESS

To add a new source:
1. Verify free access (no paid tier, no credit card)
2. Test connectivity + structure (live HTTP test)
3. Document rate limits, pagination, ToS
4. Add to `config/sources.yaml` with `enabled: true`
5. Add profile mapping in domain profiles
6. Update this document
7. Run connectivity test in CI

---

## 📊 SOURCE HEALTH MONITORING

Per-run metrics recorded in events:
- `source_attempted`: source_id
- `source_success`: boolean
- `source_latency_ms`: integer
- `source_item_count`: integer
- `source_error`: string (if failed)

Alert if:
- Any source fails 3 consecutive runs
- Success rate < 50% over 7 days
- Latency > 30 seconds
- Item count = 0 for 2+ runs (may indicate API change)