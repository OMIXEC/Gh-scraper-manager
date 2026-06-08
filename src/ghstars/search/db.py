"""SQLite database for storing and searching enriched repositories with FTS5 + vectors.
Multi-user: each repo is keyed by (full_name, scraped_by)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from ghstars.models import EnrichedRepo


CREATE_REPOS_TABLE = """
CREATE TABLE IF NOT EXISTS repos (
    full_name TEXT NOT NULL,
    scraped_by TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    topics TEXT,
    language TEXT,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    license TEXT,
    homepage TEXT,
    created_at TEXT,
    updated_at TEXT,
    starred_at TEXT,
    readme_text TEXT,
    readme_summary TEXT,
    category TEXT DEFAULT 'Uncategorized',
    subcategory TEXT,
    primary_use_case TEXT,
    secondary_use_cases TEXT,
    utility_score INTEGER DEFAULT 0,
    community_health INTEGER DEFAULT 0,
    stars_rate TEXT DEFAULT 'steady',
    best_for TEXT,
    tags TEXT,
    maturity_level TEXT DEFAULT 'unknown',
    ai_enriched_desc TEXT,
    related_repos TEXT,
    enrichment_timestamp TEXT,
    embedding BLOB,
    search_text TEXT,
    PRIMARY KEY (full_name, scraped_by)
);
"""

CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS repos_fts USING fts5(
    full_name,
    description,
    language,
    category,
    subcategory,
    primary_use_case,
    secondary_use_cases,
    best_for,
    tags,
    ai_enriched_desc,
    topics,
    content='repos',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

CREATE_VEC_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS repos_vec USING vec0(
    embedding FLOAT[384]
);
"""

CREATE_VEC_TABLE_FALLBACK = """
CREATE TABLE IF NOT EXISTS repos_vec (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    scraped_by TEXT NOT NULL DEFAULT '',
    embedding BLOB NOT NULL,
    UNIQUE(full_name, scraped_by)
);
"""

CREATE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS repos_fts_rebuild AFTER INSERT ON repos BEGIN
    INSERT INTO repos_fts(repos_fts) VALUES('rebuild');
END;
CREATE TRIGGER IF NOT EXISTS repos_fts_rebuild_u AFTER UPDATE ON repos BEGIN
    INSERT INTO repos_fts(repos_fts) VALUES('rebuild');
END;
CREATE TRIGGER IF NOT EXISTS repos_fts_rebuild_d AFTER DELETE ON repos BEGIN
    INSERT INTO repos_fts(repos_fts) VALUES('rebuild');
END;
"""

CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS scrape_meta (
    scraped_by TEXT NOT NULL DEFAULT '',
    last_scraped_at TEXT,
    total_stars_at_last INTEGER DEFAULT 0,
    PRIMARY KEY (scraped_by)
);
"""

MIGRATE_V1 = """
-- Add scraped_by column and composite PK for existing single-user databases
ALTER TABLE repos ADD COLUMN scraped_by TEXT NOT NULL DEFAULT '';
"""


class RepoDatabase:
    """SQLite database manager for repository storage and search per user."""

    def __init__(self, db_path: Path, embedding_dim: int = 384):
        self.db_path = db_path
        self.embedding_dim = embedding_dim
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self) -> None:
        conn = self.conn
        conn.execute(CREATE_REPOS_TABLE)
        conn.execute(CREATE_FTS_TABLE)

        try:
            conn.execute(CREATE_VEC_TABLE)
            self._has_vec_extension = True
        except Exception:
            conn.execute(CREATE_VEC_TABLE_FALLBACK)
            self._has_vec_extension = False

        conn.executescript(CREATE_TRIGGERS)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_category ON repos(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_score ON repos(utility_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_stars ON repos(stars DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_language ON repos(language)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_scraped_by ON repos(scraped_by)")
        conn.execute(CREATE_META_TABLE)
        conn.commit()

    def get_last_scrape(self, scraped_by: str) -> tuple[str | None, int]:
        """Get (last_scraped_at, total_stars) for a user, or (None, 0) if never scraped."""
        row = self.conn.execute(
            "SELECT last_scraped_at, total_stars_at_last FROM scrape_meta WHERE scraped_by = ?",
            (scraped_by,),
        ).fetchone()
        if row:
            return row["last_scraped_at"], row["total_stars_at_last"]
        return None, 0

    def set_last_scrape(self, scraped_by: str, total_stars: int):
        """Update the last scrape timestamp and star count for a user."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO scrape_meta (scraped_by, last_scraped_at, total_stars_at_last) VALUES (?, ?, ?)",
            (scraped_by, now, total_stars),
        )
        self.conn.commit()

    def upsert(self, repo: EnrichedRepo) -> None:
        conn = self.conn
        data = repo.model_dump(exclude={"embedding"})
        for field in ("topics", "secondary_use_cases", "best_for", "tags", "related_repos"):
            val = data.get(field, [])
            data[field] = json.dumps(val) if val else "[]"
        if data.get("maturity_level") is not None:
            data["maturity_level"] = data["maturity_level"].value if hasattr(data["maturity_level"], "value") else str(data["maturity_level"])
        from datetime import datetime
        for dt_field in ("created_at", "updated_at", "starred_at", "enrichment_timestamp"):
            val = data.get(dt_field)
            if isinstance(val, datetime):
                data[dt_field] = val.isoformat()
        data["search_text"] = repo.combined_search_text

        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        updates = ", ".join(f"{k}=excluded.{k}" for k in data if k not in ("full_name", "scraped_by"))

        sql = (
            f"INSERT INTO repos ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(full_name, scraped_by) DO UPDATE SET {updates}"
        )
        conn.execute(sql, list(data.values()))
        conn.commit()

    def upsert_embedding(self, full_name: str, scraped_by: str, embedding: list[float]) -> None:
        import struct
        packed = struct.pack(f"{len(embedding)}f", *embedding)
        conn = self.conn
        conn.execute(
            "INSERT OR REPLACE INTO repos_vec (full_name, scraped_by, embedding) VALUES (?, ?, ?)",
            (full_name, scraped_by, packed),
        )
        conn.commit()

    def keyword_search(
        self, query: str, limit: int = 20, category: Optional[str] = None,
        min_score: int = 0, language: Optional[str] = None,
        scraped_by: Optional[str] = None,
    ) -> list[tuple[EnrichedRepo, float]]:
        conn = self.conn
        where = ["repos_fts MATCH ?"]
        params: list = [query]

        if category:
            where.append("repos.category = ?")
            params.append(category)
        if min_score > 0:
            where.append("repos.utility_score >= ?")
            params.append(min_score)
        if language:
            where.append("repos.language = ?")
            params.append(language)
        if scraped_by:
            where.append("repos.scraped_by = ?")
            params.append(scraped_by)

        where_clause = " AND ".join(where)
        sql = f"""
            SELECT repos.*, rank
            FROM repos_fts
            JOIN repos ON repos.rowid = repos_fts.rowid
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return self._rows_to_results(rows, match_type="keyword")

    def vector_search(
        self, query_embedding: list[float], limit: int = 20,
        category: Optional[str] = None, min_score: int = 0,
        scraped_by: Optional[str] = None,
    ) -> list[tuple[EnrichedRepo, float]]:
        import struct
        import numpy as np
        conn = self.conn

        rows = conn.execute(
            "SELECT repos.*, repos_vec.embedding "
            "FROM repos_vec JOIN repos ON repos.full_name = repos_vec.full_name "
            "AND repos.scraped_by = repos_vec.scraped_by"
        ).fetchall()

        query_vec = np.array(query_embedding)
        scored = []
        for row in rows:
            d = dict(row)
            vec_data = d.pop("embedding")
            n = len(query_embedding)
            vec = np.array(struct.unpack(f"{n}f", vec_data))
            similarity = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec)))
            repo = self._row_to_repo(d)
            if scraped_by and repo.scraped_by != scraped_by:
                continue
            if category and repo.category != category:
                continue
            if min_score > 0 and repo.utility_score < min_score:
                continue
            scored.append((repo, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def hybrid_search(
        self, query: str, query_embedding: Optional[list[float]] = None,
        limit: int = 20, keyword_weight: float = 0.3, category: Optional[str] = None,
        min_score: int = 0, language: Optional[str] = None,
        scraped_by: Optional[str] = None,
    ) -> list[tuple[EnrichedRepo, float]]:
        keyword_results = self.keyword_search(
            query, limit=limit * 2, category=category, min_score=min_score,
            language=language, scraped_by=scraped_by,
        )
        vector_results = []
        if query_embedding:
            vector_results = self.vector_search(
                query_embedding, limit=limit * 2, category=category,
                min_score=min_score, scraped_by=scraped_by,
            )
        return self._fuse_results(keyword_results, vector_results, keyword_weight, limit)

    def _fuse_results(
        self, keyword_results: list[tuple[EnrichedRepo, float]],
        vector_results: list[tuple[EnrichedRepo, float]],
        keyword_weight: float, limit: int,
    ) -> list[tuple[EnrichedRepo, float]]:
        scores: dict[str, tuple[EnrichedRepo, float]] = {}
        for rank, (repo, score) in enumerate(keyword_results):
            fused = (1.0 / (rank + 60)) * keyword_weight
            key = f"{repo.full_name}|{repo.scraped_by}"
            scores[key] = (repo, fused)
        for rank, (repo, score) in enumerate(vector_results):
            vec_weight = 1.0 - keyword_weight
            fused = (1.0 / (rank + 60)) * vec_weight
            key = f"{repo.full_name}|{repo.scraped_by}"
            if key in scores:
                existing_repo, existing_score = scores[key]
                scores[key] = (existing_repo, existing_score + fused)
            else:
                scores[key] = (repo, fused)
        sorted_results = sorted(scores.values(), key=lambda x: x[1], reverse=True)
        return sorted_results[:limit]

    def get_all_repos(self, scraped_by: Optional[str] = None, enriched_only: bool = False) -> list[EnrichedRepo]:
        conn = self.conn
        where = []
        params = []
        if scraped_by:
            where.append("scraped_by = ?")
            params.append(scraped_by)
        if enriched_only:
            where.append("enrichment_timestamp IS NOT NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(f"SELECT * FROM repos {clause}", params).fetchall()
        return [self._row_to_repo(dict(row)) for row in rows]

    def get_repo(self, full_name: str, scraped_by: str = "") -> Optional[EnrichedRepo]:
        row = self.conn.execute(
            "SELECT * FROM repos WHERE full_name = ? AND scraped_by = ?",
            (full_name, scraped_by),
        ).fetchone()
        if row:
            return self._row_to_repo(dict(row))
        return None

    def count(self, scraped_by: Optional[str] = None, enriched_only: bool = False) -> int:
        where = []
        params = []
        if scraped_by:
            where.append("scraped_by = ?")
            params.append(scraped_by)
        if enriched_only:
            where.append("enrichment_timestamp IS NOT NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        row = self.conn.execute(f"SELECT COUNT(*) FROM repos {clause}", params).fetchone()
        return row[0] if row else 0

    def get_users(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT scraped_by FROM repos WHERE scraped_by != '' ORDER BY scraped_by"
        ).fetchall()
        return [r[0] for r in rows]

    def get_categories(self, scraped_by: Optional[str] = None) -> list[str]:
        where = "WHERE scraped_by = ?" if scraped_by else ""
        params = [scraped_by] if scraped_by else []
        rows = self.conn.execute(
            f"SELECT DISTINCT category FROM repos {where} ORDER BY category", params
        ).fetchall()
        return [r[0] for r in rows]

    def get_languages(self, scraped_by: Optional[str] = None) -> list[str]:
        where = "WHERE language IS NOT NULL"
        params = []
        if scraped_by:
            where += " AND scraped_by = ?"
            params.append(scraped_by)
        rows = self.conn.execute(
            f"SELECT DISTINCT language FROM repos {where} ORDER BY language", params
        ).fetchall()
        return [r[0] for r in rows]

    def get_stats(self, scraped_by: Optional[str] = None) -> dict:
        conn = self.conn
        where = ""
        params: list = []
        if scraped_by:
            where = "WHERE scraped_by = ?"
            params = [scraped_by]

        total = conn.execute(f"SELECT COUNT(*) FROM repos {where}", params).fetchone()[0]
        enriched = conn.execute(
            f"SELECT COUNT(*) FROM repos {where}{' AND ' if where else 'WHERE '}enrichment_timestamp IS NOT NULL", params
        ).fetchone()[0]
        avg_score = conn.execute(
            f"SELECT AVG(utility_score) FROM repos {where}{' AND ' if where else 'WHERE '}utility_score > 0", params
        ).fetchone()[0] or 0
        total_stars = conn.execute(f"SELECT SUM(stars) FROM repos {where}", params).fetchone()[0] or 0

        return {
            "total_repos": total,
            "enriched_repos": enriched,
            "avg_utility_score": round(avg_score, 1),
            "total_stars": total_stars,
        }

    def _row_to_repo(self, row: dict) -> EnrichedRepo:
        for field in ("topics", "secondary_use_cases", "best_for", "tags", "related_repos"):
            val = row.pop(field, "[]")
            if isinstance(val, str):
                try:
                    row[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    row[field] = []
            elif val is None:
                row[field] = []
        return EnrichedRepo(**{k: _coerce_field(k, v) for k, v in row.items()})

    def _rows_to_results(
        self, rows: list[sqlite3.Row], match_type: str
    ) -> list[tuple[EnrichedRepo, float]]:
        results = []
        for row in rows:
            d = dict(row)
            rank = d.pop("rank", 0.0)
            if match_type == "keyword":
                score = 1.0 / (1.0 + abs(rank)) if rank is not None else 0.0
            else:
                score = float(rank) if rank else 0.0
            repo = self._row_to_repo(d)
            results.append((repo, score))
        return results


def _coerce_field(key: str, value):
    from datetime import datetime
    from ghstars.models import MaturityLevel
    if value is None:
        return None
    if key == "maturity_level" and isinstance(value, str):
        try:
            return MaturityLevel(value)
        except ValueError:
            return MaturityLevel.UNKNOWN
    if key in ("created_at", "updated_at", "enrichment_timestamp") and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value
