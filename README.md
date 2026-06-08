# GitHub Stars Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Comprehensive CLI toolkit for managing GitHub starred repositories: scrape, enrich with AI metadata, export to multiple formats, mirror/migrate to another account, and search with hybrid keyword+vector retrieval.

## Installation

```bash
git clone <repo-url> gh-stars-manager && cd gh-stars-manager
pip install -e ".[dev]"
```

## Quick Start

```bash
cp .env.example .env    # edit with your keys

# 3-step pipeline
ghstars scrape <username>      # Step 1: fetch stars
ghstars enrich                 # Step 2: AI metadata
ghstars export --format all    # Step 3: export everything
ghstars index                  # Optional: build vector index for hybrid search
```

## Top New Features

### Incremental Scraping
Fetch only new stars since your last scrape:
```bash
ghstars scrape OMIXEC --incremental
```
Tracks last scrape per user in `scrape_meta` table. Only fetches repos starred after the previous run.

### Multi-User Database
Same DB stores stars from multiple users. All export/search/status commands support `--user`:
```bash
ghstars scrape user1
ghstars scrape user2
ghstars status --user user1
ghstars export --format all --user user2
ghstars search "Python CLI" --user user1
```

### RAG Chat (LLM-Powered Recommendations)
Chat with your star collection — ask for the best repos for any task:
```bash
ghstars chat "I need a Python async HTTP client for web scraping"
ghstars chat "best Kubernetes monitoring tools" --min-score 7 --lang Go
ghstars chat "CI/CD pipeline framework" --category DevOps --top-k 20
```
Uses hybrid search + LLM to rank repos with explanations of why each fits your task and how to use them.

### CI/CD Pipeline (GitHub Actions)
Scheduled automatic scraping + enrichment + export:
```yaml
# .github/workflows/stars-pipeline.yml
# Runs daily at 6am UTC — scrape, enrich, and upload export artifacts
```
Set `STARS_USERNAME` as a repo variable to auto-scrape a tracked profile.
Or trigger manually via `workflow_dispatch` with custom username.

### Model Switching (OpenAI + Anthropic + Deepseek)
```bash
ghstars enrich --model gpt-4o-mini
ghstars enrich --model deepseek-v4-flash
ghstars enrich --model deepseek-v4-pro
ghstars chat "..." --model deepseek-v4-pro
ghstars chat "..." --model claude-sonnet-4-20250514
```

---

## Full Command Reference

### `ghstars scrape` — Fetch starred repos

```bash
# By username
ghstars scrape OMIXEC

# By GitHub profile URL
ghstars scrape https://github.com/OMIXEC

# By email (resolves via GitHub search)
ghstars scrape user@example.com

# Limit to N repos (most recent first)
ghstars scrape OMIXEC --max 50

# Fetch READMEs too (needed for quality enrichment)
ghstars scrape OMIXEC --readmes

# With a PAT for higher rate limits (5,000 req/hr vs 60)
ghstars scrape OMIXEC --token ghp_xxxx
```

**Rate limits (no token):** 60 requests/hour — about 600 repos per scrape window.  
**Rate limits (with PAT):** 5,000 requests/hour — virtually unlimited for personal stars.

### `ghstars enrich` — AI metadata generation

```bash
# Enrich all unscraped repos (uses provider/model from .env)
ghstars enrich

# Specify model explicitly
ghstars enrich --model gpt-4o-mini
ghstars enrich --model deepseek-v4-flash
ghstars enrich --model deepseek-v4-pro
ghstars enrich --model claude-sonnet-4-20250514

# Re-enrich already enriched repos
ghstars enrich --force

# Limit batch size for speed/memory
ghstars enrich --batch-size 20

# Enrich only first N repos
ghstars enrich --limit 100

# Combine options
ghstars enrich --model deepseek-v4-flash --force --limit 50
```

**Generated metadata per repo:**
`category`, `subcategory`, `primary_use_case`, `secondary_use_cases`, `utility_score` (0-10), `community_health` (0-10), `stars_rate` (slow/steady/fast/viral), `best_for`, `tags`, `maturity_level`, `ai_enriched_desc`, `related_repos`

### `ghstars export` — Export in all formats

```bash
# Export to individual formats
ghstars export --format md       # Obsidian-compatible Markdown
ghstars export --format jsonl    # RAG-ready line-delimited JSON
ghstars export --format csv      # Notion / Google Sheets / Excel
ghstars export --format github   # Re-star manifest + raw list
ghstars export --format all      # All four at once

# Custom output directory
ghstars export --format all --output ./my-exports

# Single-file markdown index (instead of per-repo files)
ghstars export --format md --single

# Include embedding vectors in JSONL (for direct vector DB import)
ghstars export --format jsonl --embeddings
```

### `ghstars index` — Build vector embeddings

```bash
# Build sentence-transformer embeddings for all repos (hybrid search prerequisite)
ghstars index

# First run downloads ~80MB model (all-MiniLM-L6-v2), cached after that
```

### `ghstars search` — Hybrid keyword + vector search

```bash
# Interactive (prompts for query)
ghstars search

# One-shot with query
ghstars search "kubernetes container orchestration tools"
ghstars search "rust CLI for file watching"

# Keyword-only (no vectors needed, instant)
ghstars search "security" --keyword-only

# Hybrid (needs 'ghstars index' first)
ghstars search "python async web framework" --hybrid

# Filter by category
ghstars search "database" --category DevOps
ghstars search "llm" --category "ML/AI"

# Filter by language
ghstars search "testing" --lang Python
ghstars search "frontend" --lang TypeScript

# Filter by minimum utility score
ghstars search "monitoring" --min-score 7

# Combine filters
ghstars search "api" --category Backend --lang Go --min-score 5 --limit 10
```

### `ghstars info` — Detailed repo view

```bash
ghstars info vercel/next.js
ghstars info PortSwigger/turbo-intruder
```

### `ghstars status` — Database statistics

```bash
ghstars status
# Shows: total repos, enriched count, avg utility score, total stars, categories, languages
```

### `ghstars mirror` — Fork repos to another account

```bash
# Fork all repos to a target account
ghstars mirror targetuser --token ghp_target_token

# Also re-star them on the target account
ghstars mirror targetuser --token ghp_target_token --restar

# Dry-run: see what would be forked, don't actually do it
ghstars mirror targetuser --token ghp_target_token --dry-run

# Limit how many to fork
ghstars mirror targetuser --token ghp_target_token --limit 100
```

### `ghstars migrate` — Full migration pipeline

```bash
# Complete migration: scrape source → enrich → export → fork → re-star
ghstars migrate OMIXEC targetuser \
  --source-token ghp_source_token \
  --target-token ghp_target_token

# Skip enrichment (if already in DB)
ghstars migrate OMIXEC targetuser \
  --source-token ghp_source_token \
  --target-token ghp_target_token \
  --no-enrich

# Fork only, no re-star
ghstars migrate OMIXEC targetuser \
  --source-token ghp_source_token \
  --target-token ghp_target_token \
  --no-restar

# Fork only, no re-star, limit
ghstars migrate OMIXEC targetuser \
  --source-token ghp_source_token \
  --target-token ghp_target_token \
  --limit 50 --no-enrich --no-restar
```

---

## Environment Variables Cheatsheet

Copy `.env.example` to `.env`:

```bash
# === Required for enrichment ===
LLM_PROVIDER=openai          # openai | anthropic | deepseek

# --- Option A: OpenAI ---
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini     # or gpt-4o, gpt-4.1, etc.

# --- Option B: Anthropic ---
#ANTHROPIC_API_KEY=sk-ant-...
#ANTHROPIC_MODEL=claude-sonnet-4-20250514
#LLM_PROVIDER=anthropic

# --- Option C: Deepseek ---
#DEEPSEEK_API_KEY=sk-...
#DEEPSEEK_MODEL=deepseek-v4-flash
#LLM_PROVIDER=deepseek

# === Optional ===
GITHUB_TOKEN=ghp_...           # higher API rate limits
ENRICH_BATCH_SIZE=10           # repos per LLM call (saves tokens)
ENRICH_CONCURRENCY=3           # parallel LLM calls
```

### Model Switching Reference

| Provider | Model | Best For | Cost |
|----------|-------|----------|------|
| `openai` | `gpt-4o-mini` | Fast, cheap, good quality | $0.15/1M input |
| `openai` | `gpt-4o` | Highest quality enrichment | $2.50/1M input |
| `openai` | `gpt-4.1` | Latest, best reasoning | ~$2/1M input |
| `anthropic` | `claude-sonnet-4-20250514` | Excellent structured output | ~$3/1M input |
| `deepseek` | `deepseek-v4-flash` | Fastest, cheapest | ~$0.28/1M input |
| `deepseek` | `deepseek-v4-pro` | Best price/quality ratio | ~$1.10/1M input |

`ghstars enrich --model <model>` overrides the `.env` default.

---

## Provider / Model-Specific Notes

**OpenAI** — Native `response_format: json_object` ensures valid JSON output. Uses `max_completion_tokens`. Best structured output reliability.

**Anthropic Claude** — Uses native Messages API. No `response_format` natively, but prompts include explicit JSON instructions. Default model: `claude-sonnet-4-20250514`.

**Deepseek** — OpenAI-compatible API endpoint. Uses `max_tokens` (like older OpenAI convention). Does NOT support `response_format: json_object` — relies on prompt engineering for JSON output. Two models:
  - `deepseek-v4-flash` — fast, cheap, good for bulk enrichment
  - `deepseek-v4-pro` — higher quality reasoning, strong for categorization

---

## No-Token / Offline Workflow (Anonymized Scanning)

You don't need a GitHub token to scrape public profiles:

```bash
# Scrape ANY public user (no auth, 60 req/hr each)
ghstars scrape torvalds --max 100
ghstars scrape OMIXEC
ghstars scrape https://github.com/someuser

# Save the scraped data to export/share
ghstars export --format all

# Create a static searchable database with no external deps
# (enrichment requires an LLM key, but scraping + export don't)
```

**Batch multiple profiles:**
```bash
for user in torvalds OMIXEC kennethreitz; do
  ghstars scrape "$user" --max 100
done
ghstars export --format all --output ./batch-export
```

---

## Token Cost Estimation

| Stars | Enrichment model | Approx cost |
|-------|-----------------|-------------|
| 100 | `gpt-4o-mini` | ~$0.02 |
| 100 | `deepseek-v4-flash` | ~$0.01 |
| 500 | `gpt-4o-mini` | ~$0.10 |
| 1,000 | `gpt-4o-mini` | ~$0.20 |
| 1,000 | `deepseek-v4-flash` | ~$0.08 |
| 1,000 | `deepseek-v4-pro` | ~$0.30 |
| 1,000 | `gpt-4o` | ~$0.70 |
| 5,000 | `deepseek-v4-flash` | ~$0.40 |

Batch processing sends 10 repos per API call, saving ~60% token overhead vs one-by-one.

---

## Export Format Reference

### Markdown (`--format md`)
```
exports/markdown/{owner}-{repo}.md
```
Each file has YAML frontmatter + structured sections. Drop into Obsidian, Dendron, Foam.

### JSONL (`--format jsonl`)
```
exports/jsonl/stars.jsonl
```
One JSON object per line. `text` field for embedding, `metadata` for filtering. Compatible with:
- LangChain JSONLoader
- LlamaIndex SimpleDirectoryReader
- Chroma / Pinecone / Weaviate / Qdrant ingestion
- `jq` for CLI processing: `cat stars.jsonl | jq '.metadata.category' | sort | uniq -c`

### CSV (`--format csv`)
```
exports/csv/stars.csv
```
Flat table with all columns. Import directly into Notion, Airtable, Google Sheets, Excel.

### GitHub Format (`--format github`)
```
exports/github/stars_manifest.json   # full metadata manifest
exports/github/restar_list.txt       # owner/repo, one per line
```
Used by `ghstars mirror` and `ghstars migrate`.

---

## Database & Storage

All data is stored locally in a single SQLite database:

```
data/
  stars.db           # main database (SQLite)
  stars.db-wal       # write-ahead log (auto)
  stars.db-shm       # shared memory (auto)
exports/
  markdown/          # Obsidian .md files
  jsonl/             # RAG ingestion files
  csv/               # spreadsheet files
  github/            # migration manifests
```

To reset: `rm -f data/stars.db` (keep exports).

To backup: copy `data/` and `exports/` folders.

---

## Common Workflows

### Workflow 1: Research a user's stars
```bash
ghstars scrape someuser --max 200 --readmes
ghstars enrich --model deepseek-v4-flash   # cheap bulk enrichment
ghstars export --format all
ghstars index
ghstars search "machine learning framework" --min-score 7
```

### Workflow 2: Migrate your stars to another account
```bash
ghstars migrate myolduser mynewuser \
  --source-token ghp_old_token \
  --target-token ghp_new_token
```

### Workflow 3: Build a searchable knowledge base
```bash
ghstars scrape OMIXEC
ghstars enrich --model deepseek-v4-pro
ghstars index
ghstars search "cybersecurity red team tooling" --hybrid --min-score 6
```

### Workflow 4: Export for RAG pipeline
```bash
ghstars scrape youruser
ghstars enrich
ghstars export --format jsonl --embeddings
# Now import exports/jsonl/stars.jsonl into Chroma/Pinecone/etc.
```

### Workflow 5: Update existing database (re-scrape)
```bash
ghstars scrape youruser             # upserts new stars, updates existing
ghstars enrich --force --limit 50   # re-enrich only new/changed repos
ghstars index                       # rebuild vectors
```

### Workflow 6: No-enrichment quick export
```bash
ghstars scrape someuser
ghstars export --format all          # exports raw data, no AI needed
# The JSONL/CSV will have blank enrichment fields but topics + language intact
```

---

## Enriched Repo Metadata Model

```yaml
full_name: vercel/next.js           # owner/repo
url: https://github.com/vercel/next.js
description: The React Framework... # GitHub description
topics: [react, framework, ssr]     # GitHub topics
language: JavaScript
stars: 130000
forks: 28000
license: MIT License

# ── AI Enriched ──
category: Frontend Framework
subcategory: React Meta-Framework
primary_use_case: "Building production React applications with SSR, SSG, and ISR"
secondary_use_cases:
  - "Full-stack web applications"
  - "API routes with serverless functions"
  - "Static site generation for blogs and marketing sites"
utility_score: 9
community_health: 10
stars_rate: viral
best_for:
  - "Full-stack web developers"
  - "Teams migrating from Create React App"
  - "E-commerce platforms needing SSR/SEO"
tags: [react, ssr, static-site, edge-rendering, app-router, server-components]
maturity_level: production-ready
ai_enriched_desc: "Next.js is a React meta-framework..."
related_repos: [remix-run/remix, sveltejs/kit, nuxt/nuxt]
enrichment_timestamp: 2026-05-31T19:31:45+00:00
```

---

## CLI Quick Reference

```
ghstars scrape    <user|email|url>    [-t TOKEN] [--readmes] [--max N]
ghstars enrich                        [--model M] [--force] [--limit N] [--batch-size N]
ghstars export    --format md|jsonl|csv|github|all  [-o DIR] [--single] [--embeddings]
ghstars search    [QUERY]             [--hybrid|--keyword-only] [-c CAT] [--min-score N] [--lang L] [--limit N]
ghstars index
ghstars info      <owner/repo>
ghstars status
ghstars mirror    <target-user>       -t TOKEN [--restar] [--limit N] [--dry-run]
ghstars migrate   <from> <to>         -s SRC_TOKEN -t TGT_TOKEN [--fork] [--restar] [--enrich] [--limit N]
ghstars version
```

---

## License

MIT
