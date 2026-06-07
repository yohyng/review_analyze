"""SQLite storage for the ingestion layer.

Schema (minimal, driven by the whiteboard flow):
    facility          - 施設マスタ (step 1/2, name is hand-typed)
    review            - 口コミ本文 (step 3, from KAIZODE/Google CSV)
    review_subscore   - review_details を展開した Google 軸スコア (Rooms/Service/...)
    score             - 既存Excelの独自定量化指標 (step 4)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS facility (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    type            TEXT,                       -- 'target' / 'comparison'
    category        TEXT,
    general_rating  REAL,                       -- place_general_rating
    total_reviews   INTEGER,                    -- overall_place_reviews
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id         INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    review_id           TEXT,                   -- Google review id (dedup key)
    rating              INTEGER,
    text                TEXT,
    review_date         TEXT,
    reviewer_name       TEXT,
    local_guide         INTEGER,                -- 0/1
    likes               INTEGER,
    owner_response      TEXT,
    owner_response_date TEXT,
    UNIQUE(facility_id, review_id)
);

CREATE TABLE IF NOT EXISTS review_subscore (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_db_id    INTEGER NOT NULL REFERENCES review(id) ON DELETE CASCADE,
    axis            TEXT NOT NULL,              -- 'Rooms' / 'Service' / 'Location' ...
    value           REAL
);

CREATE TABLE IF NOT EXISTS score (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id     INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    metric_name     TEXT NOT NULL,             -- Excel column header (独自軸名)
    value           REAL,
    scale           REAL,                      -- 5 / 100 ...
    source          TEXT DEFAULT 'excel',
    UNIQUE(facility_id, metric_name, source)
);

CREATE INDEX IF NOT EXISTS idx_review_facility ON review(facility_id);
CREATE INDEX IF NOT EXISTS idx_subscore_review ON review_subscore(review_db_id);
CREATE INDEX IF NOT EXISTS idx_score_facility ON score(facility_id);
"""


def get_conn(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open (and lazily create) the SQLite database."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# Facility
# --------------------------------------------------------------------------- #
def upsert_facility(
    conn: sqlite3.Connection,
    name: str,
    ftype: Optional[str] = None,
    category: Optional[str] = None,
    general_rating: Optional[float] = None,
    total_reviews: Optional[int] = None,
) -> int:
    """Insert facility by name, or update its (non-null) metadata. Returns id."""
    name = name.strip()
    row = conn.execute("SELECT id FROM facility WHERE name = ?", (name,)).fetchone()
    if row:
        fid = row["id"]
        conn.execute(
            """UPDATE facility SET
                   type           = COALESCE(?, type),
                   category       = COALESCE(?, category),
                   general_rating = COALESCE(?, general_rating),
                   total_reviews  = COALESCE(?, total_reviews)
               WHERE id = ?""",
            (ftype, category, general_rating, total_reviews, fid),
        )
    else:
        cur = conn.execute(
            """INSERT INTO facility(name, type, category, general_rating, total_reviews)
               VALUES (?, ?, ?, ?, ?)""",
            (name, ftype, category, general_rating, total_reviews),
        )
        fid = cur.lastrowid
    conn.commit()
    return fid


# --------------------------------------------------------------------------- #
# Reviews (+ sub-scores)
# --------------------------------------------------------------------------- #
def insert_reviews(conn: sqlite3.Connection, facility_id: int, reviews: Iterable) -> tuple[int, int]:
    """Insert ParsedReview items. Dedups on (facility_id, review_id).

    Returns (inserted, skipped_duplicates).
    """
    inserted = skipped = 0
    for r in reviews:
        rid = r.review_id
        if rid:
            exists = conn.execute(
                "SELECT 1 FROM review WHERE facility_id = ? AND review_id = ?",
                (facility_id, rid),
            ).fetchone()
            if exists:
                skipped += 1
                continue
        cur = conn.execute(
            """INSERT INTO review(
                   facility_id, review_id, rating, text, review_date,
                   reviewer_name, local_guide, likes, owner_response, owner_response_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                facility_id, rid, r.rating, r.text, r.review_date,
                r.reviewer_name, int(r.local_guide), r.likes,
                r.owner_response, r.owner_response_date,
            ),
        )
        review_db_id = cur.lastrowid
        for axis, value in r.subscores:
            conn.execute(
                "INSERT INTO review_subscore(review_db_id, axis, value) VALUES (?, ?, ?)",
                (review_db_id, axis, value),
            )
        inserted += 1
    conn.commit()
    return inserted, skipped


# --------------------------------------------------------------------------- #
# Scores (Excel)
# --------------------------------------------------------------------------- #
def upsert_scores(
    conn: sqlite3.Connection,
    facility_id: int,
    scores: dict[str, float],
    scale: Optional[float] = None,
    source: str = "excel",
) -> int:
    """Upsert {metric_name: value} for a facility. Returns rows written."""
    n = 0
    for metric, value in scores.items():
        conn.execute(
            """INSERT INTO score(facility_id, metric_name, value, scale, source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(facility_id, metric_name, source)
               DO UPDATE SET value = excluded.value, scale = excluded.scale""",
            (facility_id, metric, value, scale, source),
        )
        n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------- #
# Read helpers (for the status page)
# --------------------------------------------------------------------------- #
def list_facilities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM facility ORDER BY id").fetchall()


def facility_stats(conn: sqlite3.Connection, facility_name: str) -> dict | None:
    """Rich stats for the 施設を選ぶ overview card. Returns None if not found."""
    row = conn.execute(
        "SELECT * FROM facility WHERE name = ?", (facility_name,)
    ).fetchone()
    if not row:
        return None
    fid = row["id"]

    rev = conn.execute(
        """SELECT COUNT(*) as cnt,
                  MIN(review_date) as oldest,
                  MAX(review_date) as newest,
                  AVG(CAST(rating AS REAL)) as avg_r
           FROM review WHERE facility_id = ?""",
        (fid,),
    ).fetchone()

    n_text = conn.execute(
        "SELECT COUNT(*) FROM review WHERE facility_id = ? AND text IS NOT NULL AND text != ''",
        (fid,),
    ).fetchone()[0]

    score_axes = [
        r["metric_name"]
        for r in conn.execute(
            "SELECT metric_name FROM score WHERE facility_id = ? ORDER BY metric_name",
            (fid,),
        ).fetchall()
    ]

    n = rev["cnt"] or 0
    can_tfidf = n_text >= 3     # minimum for meaningful keyword extraction
    can_score = bool(score_axes)

    def _short_date(d: str | None) -> str:
        return d[:7] if d and len(d) >= 7 else "-"

    return {
        "name": facility_name,
        "type": config.FACILITY_TYPES.get(row["type"], row["type"] or "-"),
        "n_reviews": n,
        "n_text_reviews": n_text,
        "date_oldest": _short_date(rev["oldest"]),
        "date_newest": _short_date(rev["newest"]),
        "avg_rating": round(rev["avg_r"], 2) if rev["avg_r"] else None,
        "general_rating": row["general_rating"],
        "total_reviews_platform": row["total_reviews"],
        "score_axes": score_axes,
        "can_analyze": n >= 1,
        "can_tfidf": can_tfidf,
        "can_score": can_score,
    }


def facility_overview(conn: sqlite3.Connection) -> list[dict]:
    """One row per facility with ingestion counts, for the dashboard."""
    out = []
    for f in list_facilities(conn):
        fid = f["id"]
        n_reviews = conn.execute(
            "SELECT COUNT(*) FROM review WHERE facility_id = ?", (fid,)
        ).fetchone()[0]
        sub_axes = [
            r["axis"]
            for r in conn.execute(
                """SELECT DISTINCT s.axis FROM review_subscore s
                   JOIN review r ON r.id = s.review_db_id
                   WHERE r.facility_id = ? ORDER BY s.axis""",
                (fid,),
            ).fetchall()
        ]
        score_axes = [
            r["metric_name"]
            for r in conn.execute(
                "SELECT metric_name FROM score WHERE facility_id = ? ORDER BY metric_name",
                (fid,),
            ).fetchall()
        ]
        out.append(
            {
                "id": fid,
                "施設名": f["name"],
                "種別": config.FACILITY_TYPES.get(f["type"], f["type"] or "-"),
                "口コミ数": n_reviews,
                "総合評点": f["general_rating"],
                "Google軸": ", ".join(sub_axes) if sub_axes else "-",
                "Excel指標": ", ".join(score_axes) if score_axes else "-",
            }
        )
    return out
