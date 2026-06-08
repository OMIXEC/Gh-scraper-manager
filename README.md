# GitHub Stars Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-121%20passed-brightgreen)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Comprehensive CLI toolkit for managing GitHub starred repositories: scrape, enrich with AI metadata, export to multiple formats, mirror/migrate to another account, and search with hybrid keyword+vector retrieval. Also includes RAG-powered chat to find the best repos for any task.

## Quick Start

```bash
cp .env.example .env    # edit with your keys

# 3-step pipeline (no GitHub token needed for public profiles)
ghstars scrape <username>                    # Step 1: fetch stars
ghstars enrich --model deepseek-v4-flash     # Step 2: AI metadata (cheapest)
ghstars export --format all                  # Step 3: export everything
ghstars index                                # Optional: vector index for hybrid search
ghstars chat "best Python CLI framework"     # RAG-powered recommendations
```

## Installation

```bash
git clone https://github.com/omixec/gh-stars-manager && cd gh-stars-manager
pip install -e ".[dev]"
```

## Features at a Glance

| Feature | Description |
|---------|-------------|
| **Tokenless Scraping** | No GitHub PAT needed for public profiles — plain username works directly |
| **Incremental Sync** | `--incremental` fetches only new stars since last scrape |
| **Multi-User DB** | Store stars from any number of users in one SQLite database |
| **AI Enrichment** | 3 providers (OpenAI, Anthropic, Deepseek) generate categories, scores, tags, use cases |
| **4 Export Formats** | Markdown (Obsidian), JSONL (RAG), CSV (Notion), GitHub manifest |
| **RAG Chat** | Ask `ghstars chat "I need X for Y"` — LLM ranks repos with explanations |
| **Hybrid Search** | FTS5 keyword + sentence-transformer vector search in local SQLite |
| **Full Migration** | `ghstars migrate` — scrape → enrich → export → fork → re-star |
| **CI/CD Pipeline** | GitHub Actions workflow for scheduled daily scraping |

---

## Commands

### `ghstars scrape` — Fetch starred repos

```bash
# By username (no API call to resolve — instant)
ghstars scrape OMIXEC

# By GitHub profile URL
ghstars scrape https://github.com/OMIXEC

# By email (resolves via GitHub search API)
ghstars scrape user@example.com

# Incremental: only new stars since last scrape
ghstars scrape OMIXEC --incremental

# Limit, fetch READMEs, higher rate limits
ghstars scrape OMIXEC --max 50 --readmes --token ghp_xxxx
```

**Rate limits (no token):** 60 requests/hour.  
**Rate limits (with PAT):** 5,000 requests/hour.

### `ghstars enrich` — AI metadata generation

```bash
ghstars enrich                                    # use default from .env
ghstars enrich --model deepseek-v4-flash          # cheapest (bulk)
ghstars enrich --model deepseek-v4-pro            # best price/quality
ghstars enrich --model gpt-4o-mini                # OpenAI
ghstars enrich --model claude-sonnet-4-20250514   # Anthropic
ghstars enrich --force                            # re-enrich already enriched
ghstars enrich --limit 100 --batch-size 20        # partial enrichment
```

**Generated metadata:** category, subcategory, primary_use_case, secondary_use_cases, utility_score (0-10), community_health (0-10), stars_rate, best_for, tags, maturity_level, ai_enriched_desc, related_repos

### `ghstars chat` — RAG-powered repo recommendations

```bash
ghstars chat "I need a Python async HTTP client for web scraping"
ghstars chat "best CI/CD framework for monorepos" --lang Go --min-score 7
ghstars chat "Kubernetes monitoring" --category DevOps --top-k 20
ghstars chat "state management for React" --model deepseek-v4-pro
```

Uses hybrid search to find matching repos, then an LLM ranks and recommends the best ones with:
- **Best Pick** — the top recommendation with rationale
- **Also Recommended** — ranked alternatives with scores
- **Usage guidance** — how to get started with each
- **Combination strategy** — repos that work well together

### `ghstars export` — Export in all formats

```bash
ghstars export --format md        # Obsidian Markdown (per-repo + unified .md)
ghstars export --format jsonl     # RAG-ready JSONL
ghstars export --format csv       # Notion / Sheets
ghstars export --format github    # Re-star manifest
ghstars export --format all       # All four at once

ghstars export --format all --output ./my-exports
ghstars export --format md --single        # single index file
ghstars export --format jsonl --embeddings # include vector embeddings
ghstars export --format all --user OMIXEC   # per-user export
```

Exports go to `exports/<username>/markdown/`, `exports/<username>/jsonl/`, etc. Each user also gets a unified `<user>_all_stars.md` with all repos and GitHub links.

### `ghstars search` — Hybrid keyword + vector search

```bash
ghstars search                                  # interactive prompt
ghstars search "kubernetes monitoring tools"    # one-shot
ghstars search "security" --keyword-only        # instant (no vectors)
ghstars search "python async" --category Backend --lang Python
ghstars search "testing" --min-score 7 --limit 5
ghstars search "database" --user OMIXEC          # filter by user
```

### Other commands

```bash
ghstars index                    # Build vector embedding index (prerequisite for hybrid search)
ghstars info vercel/next.js      # Detailed enriched metadata view
ghstars status                   # Database stats (use --user for per-user)
ghstars version                  # Version info

# Mirror: fork repos to another account
ghstars mirror targetuser -t ghp_token --restar --dry-run

# Full migration pipeline
ghstars migrate OMIXEC targetuser -s ghp_src -t ghp_tgt --limit 100
```

---

## Model Switching Reference

| Provider | Models | Cost / 1M input | Structured JSON |
|----------|--------|----------------|-----------------|
| `openai` | `gpt-4o-mini`, `gpt-4o` | $0.15 — $2.50 | Native |
| `anthropic` | `claude-sonnet-4-20250514` | ~$3.00 | Prompt-based |
| `deepseek` | `deepseek-v4-flash`, `deepseek-v4-pro` | $0.28 — $1.10 | Prompt-based |

Override via CLI: `ghstars enrich --model <model>` or `ghstars chat --model <model>`.

---

## Environment Variables

Copy `.env.example` to `.env`:

```bash
# Provider
LLM_PROVIDER=openai              # openai | anthropic | deepseek

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Deepseek (cheapest)
#DEEPSEEK_API_KEY=sk-...
#DEEPSEEK_MODEL=deepseek-v4-flash
#LLM_PROVIDER=deepseek

# Anthropic
#ANTHROPIC_API_KEY=sk-ant-...
#ANTHROPIC_MODEL=claude-sonnet-4-20250514
#LLM_PROVIDER=anthropic

# Optional
GITHUB_TOKEN=ghp_...              # higher API rate limits
HF_TOKEN=hf_...                   # HuggingFace token for embedding model download
ENRICH_BATCH_SIZE=10
ENRICH_CONCURRENCY=3
STARS_USERNAME=OMIXEC              # CI/CD target user
```

---

## No-Token Scanning

Username lookups are resolved locally (no API call) — plain usernames just work:

```bash
# These all work without a GitHub token
ghstars scrape OMIXEC
ghstars scrape torvalds --max 100
ghstars scrape OMIXEC --incremental   # only new stars

# Batch scrape multiple users
for u in OMIXEC torvalds kennethreitz; do
  ghstars scrape "$u" --max 200
done
```

---

## Export Layout

```
exports/
  OMIXEC/
    markdown/
      anthropics-skills.md          # per-repo .md with YAML frontmatter
      vercel-next.js.md
      ...
      OMIXEC_all_stars.md           # unified index with all GitHub links
    jsonl/stars.jsonl               # RAG-ready JSONL
    csv/stars.csv                    # spreadsheet import
    github/stars_manifest.json       # re-star manifest
    github/restar_list.txt
```

---

## Database

Single SQLite file at `data/stars.db` with:
- **FTS5** full-text search over descriptions, categories, tags, topics
- **Vector storage** for sentence-transformer embeddings (384-dim)
- **Multi-user** isolation via composite `(full_name, scraped_by)` key
- **Scrape metadata** table tracking last scrape time per user for incremental mode

Reset: `rm -f data/stars.db`

---

## Testing

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

121 tests covering models, database CRUD, multi-user isolation, enrichment parsing, export formats, hybrid search, and CLI commands.

---

## CI/CD Pipeline

`.github/workflows/stars-pipeline.yml` — runs daily at 6am UTC. Set `STARS_USERNAME` repo variable for auto-targeting or trigger manually via `workflow_dispatch`.

---

## License

MIT
