"""Storage layer — Turso (libSQL) when credentials are set, local SQLite otherwise.

  TURSO_URL   libsql://your-db-xxx.turso.io   (copy from Turso dashboard)
  TURSO_TOKEN eyJh...                          (create via "+ Create Token")

Set both as environment variables or Streamlit secrets.  When neither is
present the app uses a local SQLite file (data/reviews.db) as before.

Turso is accessed via the HTTP v2/pipeline API using only `requests` — no
native extensions required, so it works on every platform including
Streamlit Cloud.

Schema:
    facility          - 施設マスタ
    review            - 口コミ本文
    review_subscore   - Google 軸スコア (Rooms/Service/...)
    score             - 定量化指標 (Excel / auto)
"""
from __future__ import annotations

import base64
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import config


# --------------------------------------------------------------------------- #
# Row factory — sqlite3.Row-compatible object for both sqlite3 and libsql
# --------------------------------------------------------------------------- #
class _Row:
    """sqlite3.Row-compatible: supports row["col"], row[0], and positional iteration.

    Intentionally NOT a dict subclass so pandas treats it as a sequence and
    pd.DataFrame(rows, columns=[...]) assigns columns positionally.
    """

    __slots__ = ("_cols", "_vals", "_map")

    def __init__(self, cols, vals):
        self._cols = list(cols)
        self._vals = list(vals)
        self._map = dict(zip(self._cols, self._vals))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._map[key]

    def __iter__(self):  # yields values like sqlite3.Row
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return self._cols


def _row_factory(cursor, row):
    cols = [d[0] for d in cursor.description]
    return _Row(cols, row)


# --------------------------------------------------------------------------- #
# Turso HTTP client (no native extensions — works everywhere)
# --------------------------------------------------------------------------- #
class _TursoCursor:
    """Minimal sqlite3.Cursor-compatible object backed by Turso HTTP results."""

    def __init__(self, description, rows, lastrowid=None):
        self.description = description   # tuple of (col_name, ...) 7-tuples
        self._rows = rows                # list of plain Python lists
        self.lastrowid = lastrowid
        self.row_factory = None

    def fetchone(self):
        if not self._rows:
            return None
        row = self._rows[0]
        return self.row_factory(self, row) if self.row_factory else row

    def fetchall(self):
        if self.row_factory:
            return [self.row_factory(self, r) for r in self._rows]
        return list(self._rows)

    def __getitem__(self, key):
        return self.fetchall()[key]


def _encode_params(params) -> list:
    """Convert Python values to Turso v2/pipeline arg objects."""
    args = []
    for p in params:
        if p is None:
            args.append({"type": "null"})
        elif isinstance(p, bool):
            args.append({"type": "integer", "value": str(int(p))})
        elif isinstance(p, int):
            args.append({"type": "integer", "value": str(p)})
        elif isinstance(p, float):
            args.append({"type": "float", "value": p})
        elif isinstance(p, (bytes, bytearray, memoryview)):
            args.append({"type": "blob",
                         "base64": base64.b64encode(bytes(p)).decode("ascii")})
        else:
            args.append({"type": "text", "value": str(p)})
    return args


def _parse_turso_result(res, row_factory=None) -> "_TursoCursor":
    """Parse one Turso pipeline result object into a _TursoCursor."""
    if res.get("type") == "error":
        raise RuntimeError(f"Turso: {res['error']['message']}")
    result = res["response"]["result"]
    desc = tuple(
        (c["name"], None, None, None, None, None, None)
        for c in result.get("cols", [])
    )
    rows = []
    for raw in result.get("rows", []):
        row = []
        for cell in raw:
            t, v = cell.get("type"), cell.get("value")
            if t == "null" or (v is None and t != "blob"):
                row.append(None)
            elif t == "integer":
                row.append(int(v))
            elif t == "float":
                row.append(float(v))
            elif t == "blob":
                b64 = cell.get("base64") or (v if isinstance(v, str) else "") or ""
                row.append(base64.b64decode(b64) if b64 else b"")
            else:
                row.append(v)
        rows.append(row)
    last = result.get("last_insert_rowid")
    cur = _TursoCursor(desc, rows, int(last) if last else None)
    cur.row_factory = row_factory
    return cur


def _turso_call(session, base_url, sql, params):
    """POST one SQL statement to Turso v2/pipeline. Returns _TursoCursor."""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": _encode_params(params)}},
            {"type": "close"},
        ]
    }
    resp = session.post(f"{base_url}/v2/pipeline", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return _parse_turso_result(data["results"][0])


class _TursoConn:
    """sqlite3.Connection-compatible wrapper using the Turso HTTP v2 API.

    Uses only `requests` — no native extensions required.
    """

    def __init__(self, url: str, token: str):
        import requests  # noqa: PLC0415
        self._session = requests.Session()
        url = url.replace("libsql://", "https://").replace("wss://", "https://")
        self._base_url = url.rstrip("/")
        self._session.headers["Authorization"] = f"Bearer {token}"
        self._session.headers["Content-Type"] = "application/json"
        self.row_factory = None

    def execute(self, sql: str, params=()):
        cur = _turso_call(self._session, self._base_url, sql, params)
        cur.row_factory = self.row_factory
        return cur

    def execute_pipeline(self, statements: list[tuple[str, tuple]]) -> None:
        """Send multiple (sql, params) statements in ONE HTTP request (no result needed)."""
        requests_body = [
            {"type": "execute", "stmt": {"sql": sql, "args": _encode_params(params)}}
            for sql, params in statements
        ]
        requests_body.append({"type": "close"})
        resp = self._session.post(
            f"{self._base_url}/v2/pipeline",
            json={"requests": requests_body},
            timeout=60,
        )
        resp.raise_for_status()
        for res in resp.json()["results"][:-1]:
            if res.get("type") == "error":
                raise RuntimeError(f"Turso: {res['error']['message']}")

    def commit(self):
        pass  # Turso HTTP is auto-commit per execute

    def close(self):
        self._session.close()


# --------------------------------------------------------------------------- #
# Secret helper
# --------------------------------------------------------------------------- #
def _secret(key: str) -> str:
    """Read key from env var, then Streamlit secrets, else empty string."""
    val = os.environ.get(key, "")
    if not val:
        try:
            import streamlit as st
            val = st.secrets.get(key, "") or ""
        except Exception:
            pass
    return val

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

CREATE TABLE IF NOT EXISTS facility_photo (
    facility_id     INTEGER PRIMARY KEY REFERENCES facility(id) ON DELETE CASCADE,
    image           BLOB,                      -- 縮小済み JPEG
    mime            TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS kaizode_sync (
    dataset_id        TEXT PRIMARY KEY,        -- KAIZODE データセットID
    dataset_name      TEXT,
    last_published_at TEXT,                    -- 差分取得用: 取得済みレビューの最新 published_at
    synced_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_facility ON review(facility_id);
CREATE INDEX IF NOT EXISTS idx_subscore_review ON review_subscore(review_db_id);
CREATE INDEX IF NOT EXISTS idx_score_facility ON score(facility_id);
"""


def get_conn(db_path: Optional[Path | str] = None):
    """Return a DB connection.

    Uses Turso when TURSO_URL + TURSO_TOKEN are set; otherwise local SQLite.
    The returned object is API-compatible with sqlite3.Connection for all
    operations used in this codebase.
    """
    url = _secret("TURSO_URL")
    token = _secret("TURSO_TOKEN")

    if url and token:
        conn = _TursoConn(url, token)
    else:
        path = Path(db_path) if db_path is not None else config.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")

    conn.row_factory = _row_factory
    return conn


def init_db(conn) -> None:
    """Create tables / indexes.  Split SCHEMA into individual statements
    so this works with both sqlite3.executescript() and libsql.execute()."""
    for stmt in (s.strip() for s in SCHEMA.split(";") if s.strip()):
        conn.execute(stmt)
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
def insert_reviews(
    conn: sqlite3.Connection,
    facility_id: int,
    reviews: Iterable,
    progress_callback=None,
) -> tuple[int, int]:
    """Insert ParsedReview items. Dedups on (facility_id, review_id).

    progress_callback(current: int, total: int) — called after each review.
    Returns (inserted, skipped_duplicates).

    Turso optimisation: uses execute_pipeline() to send one review's INSERT +
    all its subscore INSERTs in a single HTTP request (vs N+1 before).
    Existence check is done in one bulk IN query upfront.
    """
    reviews = list(reviews)
    total = len(reviews)
    if not total:
        return 0, 0

    # ── bulk EXISTS check — one query instead of one per review ──────────── #
    rids = [r.review_id for r in reviews if r.review_id]
    existing: set[str] = set()
    _CHUNK = 900  # safely under SQLite/Turso variable limit (999)
    for i in range(0, len(rids), _CHUNK):
        chunk = rids[i: i + _CHUNK]
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT review_id FROM review WHERE facility_id = ? AND review_id IN ({ph})",
            (facility_id, *chunk),
        ).fetchall()
        for row in rows:
            existing.add(row[0])

    use_pipeline = hasattr(conn, "execute_pipeline")

    insert_sql = """INSERT INTO review(
               facility_id, review_id, rating, text, review_date,
               reviewer_name, local_guide, likes, owner_response, owner_response_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    subscore_sql = """INSERT INTO review_subscore(review_db_id, axis, value)
                      SELECT id, ?, ? FROM review
                      WHERE facility_id = ? AND review_id = ?"""

    inserted = skipped = 0

    # ── Turso: batch many reviews' INSERTs into one HTTP request ─────────── #
    # (was one HTTP per review → prohibitively slow for bulk loads). A review
    # and its subscore INSERTs always stay together and in order within a chunk.
    if use_pipeline:
        _CHUNK_STMTS = 50
        batch: list[tuple[str, tuple]] = []
        for idx, r in enumerate(reviews):
            if r.review_id in existing:
                skipped += 1
                if progress_callback:
                    progress_callback(idx + 1, total)
                continue
            batch.append((insert_sql, (
                facility_id, r.review_id, r.rating, r.text, r.review_date,
                r.reviewer_name, int(r.local_guide), r.likes,
                r.owner_response, r.owner_response_date,
            )))
            for axis, value in r.subscores:
                batch.append((subscore_sql, (axis, value, facility_id, r.review_id)))
            inserted += 1
            if progress_callback:
                progress_callback(idx + 1, total)
            if len(batch) >= _CHUNK_STMTS:
                conn.execute_pipeline(batch)
                batch = []
        if batch:
            conn.execute_pipeline(batch)
        conn.commit()
        return inserted, skipped

    # ── SQLite sequential path (unchanged) ───────────────────────────────── #
    for idx, r in enumerate(reviews):
        if r.review_id in existing:
            skipped += 1
            if progress_callback:
                progress_callback(idx + 1, total)
            continue
        cur = conn.execute(insert_sql, (
            facility_id, r.review_id, r.rating, r.text, r.review_date,
            r.reviewer_name, int(r.local_guide), r.likes,
            r.owner_response, r.owner_response_date,
        ))
        review_db_id = cur.lastrowid
        for axis, value in r.subscores:
            conn.execute(
                "INSERT INTO review_subscore(review_db_id, axis, value) VALUES (?, ?, ?)",
                (review_db_id, axis, value),
            )
        inserted += 1
        if progress_callback:
            progress_callback(idx + 1, total)

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
# Facility photo (BLOB) — Turso/SQLite。保存前に縮小しておくこと（src.images）。
# --------------------------------------------------------------------------- #
def save_photo(conn, facility_id: int, image_bytes: bytes, mime: str = "image/jpeg") -> None:
    """施設写真を保存（1施設1枚・上書き）。"""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("DELETE FROM facility_photo WHERE facility_id = ?", (facility_id,))
    conn.execute(
        "INSERT INTO facility_photo(facility_id, image, mime, updated_at) VALUES (?, ?, ?, ?)",
        (facility_id, image_bytes, mime, ts),
    )
    conn.commit()


def get_photo(conn, facility_id: int) -> Optional[dict]:
    """{image: bytes, mime: str, updated_at: str} or None。"""
    row = conn.execute(
        "SELECT image, mime, updated_at FROM facility_photo WHERE facility_id = ?",
        (facility_id,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    img = row[0]
    if isinstance(img, str):        # 念のため（一部ドライバが str を返す場合）
        img = img.encode("latin-1", "ignore")
    return {"image": bytes(img), "mime": row[1] or "image/jpeg", "updated_at": row[2]}


def photo_updated_at(conn, facility_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT updated_at FROM facility_photo WHERE facility_id = ?", (facility_id,)
    ).fetchone()
    return row[0] if row else None


def delete_photo(conn, facility_id: int) -> None:
    conn.execute("DELETE FROM facility_photo WHERE facility_id = ?", (facility_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
# Read helpers (for the status page)
# --------------------------------------------------------------------------- #
def list_facilities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM facility ORDER BY id").fetchall()


def delete_facility(conn: sqlite3.Connection, facility_id: int) -> None:
    """Delete a facility and all its reviews/subscores/scores (CASCADE)."""
    conn.execute("DELETE FROM score WHERE facility_id = ?", (facility_id,))
    conn.execute("DELETE FROM review WHERE facility_id = ?", (facility_id,))
    conn.execute("DELETE FROM facility WHERE id = ?", (facility_id,))
    conn.commit()


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
