"""Interactive CLI for GitHub Stars Manager - scrape, enrich, export, mirror, search."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.tree import Tree

from ghstars import __version__
from ghstars.config import settings
from ghstars.enrich.llm import EnrichmentError, LLMEnricher
from ghstars.export.csv_export import export_csv
from ghstars.export.github_fmt import export_github_format, export_restar_batch
from ghstars.export.jsonl import export_jsonl
from ghstars.export.markdown import export_markdown
from ghstars.mirror.forker import GitHubMirror
from ghstars.scraper.collector import GitHubClient, RateLimitError
from ghstars.search.chat import StarChat
from ghstars.search.db import RepoDatabase
from ghstars.search.hybrid import HybridSearchEngine

app = typer.Typer(
    name="ghstars",
    help="Comprehensive GitHub Stars manager: scrape, enrich, export, mirror, and search.",
)
console = Console()


@app.callback()
def callback():
    """GitHub Stars Manager - manage your starred repositories."""


def _resolve_user_arg(
    user: Optional[str], db: Optional[RepoDatabase] = None
) -> Optional[str]:
    """Resolve --user flag: explicit arg > only user in DB > None (all)."""
    if user:
        return user
    if db:
        db.initialize()
        users = db.get_users()
        if len(users) == 1:
            return users[0]
    return None


@app.command()
def scrape(
    target: str = typer.Argument(help="GitHub username, email, or profile URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GitHub PAT (or set GITHUB_TOKEN env)"),
    include_readmes: bool = typer.Option(False, "--readmes", help="Also fetch README content"),
    max_repos: Optional[int] = typer.Option(None, "--max", "-m", help="Maximum repos to fetch"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Only fetch new stars since last scrape"),
):
    """Scrape all starred repositories from a GitHub user profile."""
    token = token or settings.github_token
    console.print(f"\n[bold cyan]Scraping stars from:[/] [bold]{target}[/]")

    async def _run():
        client = GitHubClient(token=token)
        try:
            username = await client.resolve_user(target)
            if not username:
                console.print(f"[red]Could not resolve user: {target}[/]")
                raise typer.Exit(1)

            console.print(f"Resolved username: [bold green]{username}[/]")

            newer_than = None
            if incremental:
                db_check = RepoDatabase(settings.database_path)
                db_check.initialize()
                last_at, last_count = db_check.get_last_scrape(username)
                newer_than = last_at
                if last_at:
                    console.print(f"[dim]Incremental: fetching only stars newer than {last_at}[/]")

            with Progress(SpinnerColumn(), TextColumn("Fetching starred repos..."), transient=True):
                repos = await client.fetch_starred_repos(username, incremental=incremental, newer_than=newer_than)

            if incremental and newer_than:
                console.print(f"[green]Found {len(repos)} new starred repos[/]")
            else:
                console.print(f"[green]Found {len(repos)} starred repos[/]")

            if max_repos:
                repos = repos[:max_repos]
                console.print(f"Limited to [yellow]{max_repos}[/] repos")

            if include_readmes:
                with Progress(BarColumn(), TaskProgressColumn(), TextColumn("READMEs")) as progress:
                    task = progress.add_task("READMEs", total=len(repos))
                    repos = await client.fetch_readmes_batch(repos, lambda: progress.advance(task))

            db = RepoDatabase(settings.database_path)
            db.initialize()
            for repo in repos:
                db.upsert(repo)
            db.set_last_scrape(username, len(repos) + (last_count if incremental else 0) if incremental else len(repos))

            stats = db.get_stats(scraped_by=username)
            console.print(f"[green]Stored {len(repos)} repos for '{username}'[/]")
            _render_stats(stats)

        except RateLimitError:
            console.print("[red]GitHub API rate limit exceeded. Set GITHUB_TOKEN env var.[/]")
            raise typer.Exit(1)
        finally:
            await client.close()

    asyncio.run(_run())


@app.command()
def enrich(
    batch_size: int = typer.Option(10, "--batch-size", "-b"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    force: bool = typer.Option(False, "--force", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Only enrich repos for this user"),
):
    """Enrich repositories with AI-generated metadata."""
    if not settings.llm_api_key:
        provider = settings.llm_provider.upper()
        env_var = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }.get(settings.llm_provider, f"{provider}_API_KEY")
        console.print(f"[red]No LLM API key found. Set {env_var} or LLM_PROVIDER.[/]")
        raise typer.Exit(1)

    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    repos = db.get_all_repos(scraped_by=scraped_by)
    if not force:
        repos = [r for r in repos if not r.enrichment_timestamp]
    if limit:
        repos = repos[:limit]

    if not repos:
        console.print("[yellow]No repos to enrich.[/]")
        return

    console.print(f"[cyan]Enriching [bold]{len(repos)}[/] repos via {settings.llm_provider} ({model or settings.llm_model})...[/]")
    enricher = LLMEnricher(model=model)
    succeeded, failed = 0, 0

    with Progress(BarColumn(), TaskProgressColumn(), TextColumn("Enriching")) as progress:
        task = progress.add_task("Enriching", total=len(repos))
        for i in range(0, len(repos), batch_size):
            batch = repos[i:i + batch_size]
            try:
                enriched = asyncio.run(enricher.enrich_batch(batch))
                for repo in enriched:
                    db.upsert(repo)
                succeeded += len(enriched)
            except EnrichmentError as e:
                console.print(f"[red]Batch failed: {e}[/]")
                failed += len(batch)
            progress.advance(task, len(batch))

    console.print(f"\n[green]Enriched: {succeeded}[/]  [red]Failed: {failed}[/]")
    _render_stats(db.get_stats(scraped_by=scraped_by))


@app.command()
def export(
    output_format: str = typer.Option("md", "--format", "-f", help="md, jsonl, csv, github, all"),
    output_dir: Path = typer.Option("./exports", "--output", "-o"),
    single_file: bool = typer.Option(False, "--single"),
    include_embeddings: bool = typer.Option(False, "--embeddings"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Export repos for a specific user"),
):
    """Export repository data in various formats."""
    _do_export(output_format, output_dir, single_file, include_embeddings, user)


def _do_export(
    fmt: str = "all",
    output_dir: Path = Path("./exports"),
    single_file: bool = False,
    include_embeddings: bool = False,
    user: Optional[str] = None,
):
    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    repos = db.get_all_repos(scraped_by=scraped_by)
    if not repos:
        console.print("[yellow]No repos in database.[/]")
        return

    formats = ["md", "jsonl", "csv", "github"] if fmt == "all" else [fmt]
    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    for f in formats:
        if f == "md":
            paths = export_markdown(repos, export_dir, single_file=single_file)
            console.print(f"[green]Markdown:[/] {len(paths)} files → {paths[0].parent}")
        elif f == "jsonl":
            paths = export_jsonl(repos, export_dir, include_embeddings=include_embeddings)
            for p in paths:
                console.print(f"[green]JSONL:[/] → {p}")
        elif f == "csv":
            paths = export_csv(repos, export_dir)
            for p in paths:
                console.print(f"[green]CSV:[/] → {p}")
        elif f == "github":
            paths = export_github_format(repos, export_dir)
            for p in paths:
                console.print(f"[green]Manifest:[/] → {p}")
            rpaths = export_restar_batch(repos, export_dir)
            for p in rpaths:
                console.print(f"[green]Re-star list:[/] → {p}")
        else:
            console.print(f"[red]Unknown format: {f}[/]")


def _export_all():
    _do_export("all")


@app.command()
def mirror(
    target_username: str = typer.Argument(help="Target GitHub username to fork repos to"),
    target_token: str = typer.Option(..., "--token", "-t", prompt=True),
    restar: bool = typer.Option(False, "--restar"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Mirror repos from this user's stars"),
):
    """Fork all starred repos to another GitHub account."""
    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    repos = db.get_all_repos(scraped_by=scraped_by, enriched_only=True)
    if not repos:
        repos = db.get_all_repos(scraped_by=scraped_by)
    if limit:
        repos = repos[:limit]

    console.print(f"[cyan]Mirroring [bold]{len(repos)}[/] repos to [bold]{target_username}[/]...[/]")

    if dry_run:
        table = Table(title=f"Dry Run — {len(repos)} repos to fork")
        table.add_column("Repo", style="cyan")
        table.add_column("Stars", justify="right")
        table.add_column("Language")
        for repo in sorted(repos, key=lambda r: r.stars, reverse=True)[:50]:
            table.add_row(repo.full_name, str(repo.stars), repo.language or "")
        console.print(table)
        return

    if not Confirm.ask(f"Fork {len(repos)} repos to {target_username}?"):
        console.print("[yellow]Cancelled.[/]")
        return

    mirror_client = GitHubMirror(target_token=target_token)
    with Progress(BarColumn(), TaskProgressColumn(), TextColumn("Forking")) as progress:
        task = progress.add_task("Forking", total=len(repos))
        result = asyncio.run(mirror_client.mirror_repos(repos, restar=restar))
        progress.advance(task, len(repos))
    asyncio.run(mirror_client.close())

    table = Table(title="Mirror Results")
    table.add_column("Metric", style="bold")
    table.add_column("Count")
    table.add_row("Total", str(result.total))
    table.add_row("[green]Forked[/]", str(result.forked))
    table.add_row("[red]Failed[/]", str(result.failed))
    table.add_row("[yellow]Skipped[/]", str(result.skipped))
    console.print(table)

    if result.failed:
        console.print("\n[red]Failures:[/]")
        for d in result.details:
            if not d.success:
                console.print(f"  {d.repo_full_name}: {d.error}")


@app.command()
def search(
    query: Optional[str] = typer.Argument(None),
    limit: int = typer.Option(20, "--limit", "-l"),
    hybrid: bool = typer.Option(True, "--hybrid/--keyword-only"),
    category: Optional[str] = typer.Option(None, "--category", "-c"),
    min_score: int = typer.Option(0, "--min-score"),
    language: Optional[str] = typer.Option(None, "--lang"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Search within this user's stars"),
):
    """Search starred repos with hybrid keyword + vector search."""
    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    if db.count() == 0:
        console.print("[yellow]No repos indexed. Run 'ghstars scrape' first.[/]")
        return

    if not query:
        query = Prompt.ask("[bold]Search query[/]")
    if not query:
        return

    engine = HybridSearchEngine(db)
    with console.status("[cyan]Searching...[/]"):
        if hybrid:
            results = engine.search(
                query, limit=limit, category=category,
                min_score=min_score, language=language, scraped_by=scraped_by,
            )
        else:
            results = engine.quick_keyword(query, limit=limit)

    if not results:
        console.print("[yellow]No results found.[/]")
        return

    _render_search_results(results, query)


@app.command()
def chat(
    task: Optional[str] = typer.Argument(None, help="What task do you need a repo for?"),
    top_k: int = typer.Option(15, "--top-k", "-k", help="Max repos in LLM context"),
    top_p: float = typer.Option(0.9, "--top-p", "-p", help="Nucleus sampling threshold"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model for chat"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    min_score: int = typer.Option(0, "--min-score", help="Minimum utility score"),
    language: Optional[str] = typer.Option(None, "--lang", help="Filter by language"),
    limit: int = typer.Option(20, "--limit", "-l", help="Search result limit"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Search within this user's stars"),
):
    """Chat with your star collection — find the best repos for your specific task.
    
    Uses hybrid search to find relevant repos, then an LLM ranks and recommends 
    the best ones with explanations of how to use them and why they fit your task.
    """
    if not settings.llm_api_key:
        provider = settings.llm_provider.upper()
        env_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(
            settings.llm_provider, f"{provider}_API_KEY"
        )
        console.print(f"[red]No LLM API key found. Set {env_var}.[/]")
        raise typer.Exit(1)

    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    if db.count() == 0:
        console.print("[yellow]No repos indexed. Run 'ghstars scrape' first.[/]")
        return

    if not task:
        task = Prompt.ask("[bold]What task do you need a repo for?[/]\n  e.g. 'Python async HTTP client for scraping'")

    if not task:
        return

    console.print(f"\n[bold cyan]Searching stars for:[/] {task}")
    console.print(f"[dim]top_k={top_k}  model={model or settings.llm_model}  provider={settings.llm_provider}[/]")

    engine = HybridSearchEngine(db)
    with console.status("[cyan]Searching repos...[/]"):
        results = engine.search(
            task, limit=max(limit, top_k), category=category,
            min_score=min_score, language=language, scraped_by=scraped_by,
        )

    if not results:
        console.print("[yellow]No matching repos found.[/]")
        return

    console.print(f"[dim]Found {len(results)} matching repos, generating recommendations...[/]")

    chatter = StarChat(model=model)
    with console.status("[cyan]AI analyzing recommendations...[/]"):
        response = asyncio.run(chatter.chat(task, results, top_k=top_k, top_p=top_p))

    console.print(f"\n[bold]Top repos from:[/] [dim]{scraped_by or 'all users'}[/]")
    console.print(response)


@app.command()
def status(
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Show stats for a specific user"),
):
    """Show database statistics and stored repository overview."""
    db = RepoDatabase(settings.database_path)
    db.initialize()

    users = db.get_users()
    if user:
        scraped_by = user
    elif len(users) == 1:
        scraped_by = users[0]
    else:
        scraped_by = None

    stats = db.get_stats(scraped_by=scraped_by)
    label = f" ({scraped_by})" if scraped_by else ""
    console.print(f"[bold]Database Stats{label}[/]")
    _render_stats(stats)

    if users:
        console.print("\n[bold]Users in database:[/]")
        for u in users:
            u_stats = db.get_stats(scraped_by=u)
            console.print(f"  • [cyan]{u}[/] — {u_stats['total_repos']} repos, {u_stats['enriched_repos']} enriched")

    categories = db.get_categories(scraped_by=scraped_by)
    if categories:
        console.print("\n[bold]Categories:[/]")
        for cat in sorted(categories)[:20]:
            console.print(f"  • {cat}")

    if stats["total_repos"] > 0:
        langs = db.get_languages(scraped_by=scraped_by)
        if langs:
            console.print("\n[bold]Top Languages:[/]")
            for lang in langs[:10]:
                console.print(f"  • {lang}")


@app.command()
def index(
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Index repos for a specific user"),
):
    """Build vector embeddings index for hybrid search."""
    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    repos = db.get_all_repos(scraped_by=scraped_by)
    if not repos:
        console.print("[yellow]No repos in database.[/]")
        return

    console.print(f"[cyan]Building embedding index for [bold]{len(repos)}[/] repos...[/]")
    console.print("[dim]Model: all-MiniLM-L6-v2 (first run downloads ~80MB)[/]")

    engine = HybridSearchEngine(db)
    engine.build_index(repos)
    console.print("[green]Index built successfully![/]")


@app.command()
def info(
    repo: str = typer.Argument(help="Repository full name, e.g. 'owner/repo'"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="User who starred this repo"),
):
    """Show detailed enriched information about a specific repository."""
    db = RepoDatabase(settings.database_path)
    db.initialize()
    scraped_by = _resolve_user_arg(user, db)

    r = db.get_repo(repo, scraped_by=scraped_by or "")
    if not r:
        console.print(f"[red]Repo '{repo}' not found in database.[/]")
        return

    table = Table(title=f"[bold cyan]{r.full_name}[/]")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("URL", r.url)
    table.add_row("Stars", str(r.stars))
    table.add_row("Forks", str(r.forks))
    table.add_row("Language", r.language or "N/A")
    table.add_row("License", r.license or "N/A")
    if r.scraped_by:
        table.add_row("Scraped by", r.scraped_by)
    table.add_row("Category", r.category)
    if r.subcategory:
        table.add_row("Subcategory", r.subcategory)
    table.add_row("Utility Score", f"{r.utility_score}/10")
    table.add_row("Community Health", f"{r.community_health}/10")
    table.add_row("Maturity", r.maturity_level.value)
    table.add_row("Stars Rate", r.stars_rate)
    if r.primary_use_case:
        table.add_row("Primary Use Case", r.primary_use_case)
    if r.best_for:
        table.add_row("Best For", ", ".join(r.best_for))
    if r.tags:
        table.add_row("Tags", " ".join(f"[cyan]{t}[/]" for t in r.tags))
    if r.ai_enriched_desc:
        table.add_row("AI Description", r.ai_enriched_desc)
    console.print(table)


@app.command()
def version():
    """Show version info."""
    console.print(f"[bold]gh-stars-manager[/] v{__version__}")


@app.command()
def migrate(
    from_username: str = typer.Argument(help="Source GitHub username with stars"),
    to_username: str = typer.Argument(help="Target GitHub username for migration"),
    source_token: str = typer.Option(..., "--source-token", "-s"),
    target_token: str = typer.Option(..., "--target-token", "-t"),
    restar: bool = typer.Option(True, "--restar/--no-restar"),
    fork: bool = typer.Option(True, "--fork/--no-fork"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l"),
    enrich_first: bool = typer.Option(True, "--enrich/--no-enrich"),
):
    """Full migration: scrape source → enrich → fork/restar on target account."""
    console.print(Panel.fit(
        f"[bold]Migration Plan[/]\n"
        f"Source: [cyan]{from_username}[/] → Target: [cyan]{to_username}[/]\n"
        f"Fork: {'Y' if fork else 'N'}  |  Re-star: {'Y' if restar else 'N'}  |  Enrich: {'Y' if enrich_first else 'N'}",
        title="gh-stars-manager",
    ))

    console.print("\n[bold]Step 1/4:[/] Scraping stars...")

    async def _scrape():
        client = GitHubClient(token=source_token)
        try:
            repos = await client.fetch_starred_repos(from_username)
            if limit:
                repos = repos[:limit]
            db = RepoDatabase(settings.database_path)
            db.initialize()
            for repo in repos:
                db.upsert(repo)
            return len(repos)
        finally:
            await client.close()

    count = asyncio.run(_scrape())
    console.print(f"[green]Scraped {count} repos[/]")

    if enrich_first and count > 0:
        console.print("\n[bold]Step 2/4:[/] Enriching with AI metadata...")
        try:
            _ = settings.llm_api_key
        except ValueError:
            console.print("[yellow]Skipping enrichment — no LLM API key configured.[/]")
        else:
            db = RepoDatabase(settings.database_path)
            repos = db.get_all_repos(scraped_by=from_username)
            enricher = LLMEnricher()
            batch_size = settings.enrich_batch_size
            with Progress(BarColumn(), TaskProgressColumn(), TextColumn("Enriching")) as progress:
                task = progress.add_task("Enriching", total=len(repos))
                for i in range(0, len(repos), batch_size):
                    batch = repos[i:i + batch_size]
                    try:
                        enriched = asyncio.run(enricher.enrich_batch(batch))
                        for repo in enriched:
                            db.upsert(repo)
                    except EnrichmentError:
                        pass
                    progress.advance(task, len(batch))
            console.print("[green]Enrichment complete[/]")

    console.print("\n[bold]Step 3/4:[/] Exporting data...")
    _do_export("all", user=from_username)

    if fork:
        console.print(f"\n[bold]Step 4/4:[/] Forking to {to_username}...")
        db = RepoDatabase(settings.database_path)
        repos = db.get_all_repos(scraped_by=from_username)
        if limit:
            repos = repos[:limit]
        mirror_client = GitHubMirror(target_token=target_token)
        with Progress(BarColumn(), TaskProgressColumn(), TextColumn("Forking")) as progress:
            task = progress.add_task("Forking", total=len(repos))
            result = asyncio.run(mirror_client.mirror_repos(repos, restar=restar))
            progress.advance(task, len(repos))
        asyncio.run(mirror_client.close())

        table = Table(title=f"Migration: {from_username} → {to_username}")
        table.add_column("Metric", style="bold")
        table.add_column("Count")
        table.add_row("Repos scraped", str(count))
        table.add_row("[green]Forked[/]", str(result.forked))
        table.add_row("[red]Failed[/]", str(result.failed))
        console.print(table)

    console.print(f"\n[bold green]Migration complete![/]")
    console.print(f"[dim]Exports saved to {Path('exports').absolute()}/[/]")


def _render_stats(stats: dict):
    table = Table(title="Database Stats")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    for key, value in stats.items():
        table.add_row(key.replace("_", " ").title(), str(value))
    console.print(table)


def _render_search_results(results, query: str):
    console.print(f"\n[bold]Results for:[/] [cyan]\"{query}\"[/]\n")
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim")
    table.add_column("Repo")
    table.add_column("Score", justify="right")
    table.add_column("Cat")
    table.add_column("Match")
    table.add_column("Description")

    for i, r in enumerate(results[:30], 1):
        repo = r.repo
        desc = (repo.ai_enriched_desc or repo.description or "")[:80]
        table.add_row(
            str(i),
            f"[bold cyan]{repo.full_name}[/]\n[dim]{repo.language or ''} ⭐{repo.stars}[/]",
            f"{r.score:.3f}",
            repo.category[:15] if repo.category else "",
            r.match_type,
            desc,
        )

    console.print(table)
    console.print(f"\n[dim]{len(results)} results | Use 'ghstars info <repo>' for details[/]")


if __name__ == "__main__":
    app()
