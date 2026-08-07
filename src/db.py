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


# --------------------------------------------------------------------------- #
# 一時的な失敗のリトライ
#
#   Turso は 1クエリ = 1 HTTPリクエスト。分析は施設数ぶんクエリを撃つので、
#   途中で 1 回でもゲートウェイが 502 を返すと分析全体が落ちていた
#   （実際に get_topic_score_cache のループ中に 502 で停止した）。
#   ゲートウェイ由来の 5xx と接続断だけを、指数バックオフで数回やり直す。
# --------------------------------------------------------------------------- #
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_MAX = 4                       # 初回 + 4回
_RETRY_BASE = 0.5                    # 0.5 → 1 → 2 → 4 秒

# 「もう一度送っても結果が変わらない」文だけをやり直す。
# 502 は「DBに届かなかった」ことも「届いたが応答が失われた」ことも意味しうるので、
# 素の INSERT INTO をやり直すと行が二重に入る。そこは即座に諦める。
_IDEMPOTENT_HEAD = (
    "select", "pragma", "with", "create", "update", "delete", "drop", "alter",
    "insert or replace", "insert or ignore",
)


def _is_retriable_sql(sql: str) -> bool:
    s = " ".join(str(sql).split()).lower()
    return s.startswith(_IDEMPOTENT_HEAD)


def _should_retry(exc) -> bool:
    """ゲートウェイ由来の一時障害か（＝やり直す価値があるか）。"""
    import requests  # noqa: PLC0415

    if isinstance(exc, (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        return resp is not None and resp.status_code in _RETRY_STATUS
    return False


def _post_with_retry(session, url, payload, timeout, retriable: bool):
    """v2/pipeline へ POST。一時障害なら指数バックオフでやり直す。"""
    import time as _time  # noqa: PLC0415

    last = None
    for attempt in range(_RETRY_MAX + 1):
        try:
            resp = session.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:                       # noqa: BLE001
            last = exc
            if not retriable or not _should_retry(exc) or attempt == _RETRY_MAX:
                raise
            _time.sleep(_RETRY_BASE * (2 ** attempt))
    raise last                                          # pragma: no cover


def _turso_call(session, base_url, sql, params):
    """POST one SQL statement to Turso v2/pipeline. Returns _TursoCursor."""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": _encode_params(params)}},
            {"type": "close"},
        ]
    }
    resp = _post_with_retry(session, f"{base_url}/v2/pipeline", payload, 30,
                            _is_retriable_sql(sql))
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
        # まとめ送りは全文が「やり直して安全」なときだけリトライする
        # （素の INSERT INTO が混じるバッチは、二重投入になるのでやり直さない）
        resp = _post_with_retry(
            self._session, f"{self._base_url}/v2/pipeline",
            {"requests": requests_body}, 60,
            all(_is_retriable_sql(sql) for sql, _p in statements),
        )
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
    floor_area      TEXT,                       -- 延床（手入力・任意の表記のまま保持）
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

CREATE TABLE IF NOT EXISTS app_user (
    email           TEXT PRIMARY KEY,          -- ログインID（メールアドレス, 小文字正規化）
    password_hash   TEXT NOT NULL,             -- pbkdf2_hmac(sha256) の16進
    salt            TEXT NOT NULL,             -- 16進ソルト
    role            TEXT NOT NULL DEFAULT 'admin',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kaizode_usage (
    month           TEXT PRIMARY KEY,          -- 'YYYY-MM'
    downloaded      INTEGER NOT NULL DEFAULT 0, -- 当月KAIZODEから取得したレビュー件数
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS topic_score_cache (
    facility_id   INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    n_reviews     INTEGER NOT NULL,
    topics_json   TEXT    NOT NULL,
    overall_score REAL    NOT NULL DEFAULT 0,
    n_sentences   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (facility_id, n_reviews)
);

CREATE TABLE IF NOT EXISTS text_profile_cache (
    facility_id     INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    n_reviews       INTEGER NOT NULL,
    tfidf_json      TEXT    NOT NULL DEFAULT '[]',
    bigrams_json    TEXT    NOT NULL DEFAULT '[]',
    trigrams_json   TEXT    NOT NULL DEFAULT '[]',
    high_rated_json TEXT    NOT NULL DEFAULT '[]',
    low_rated_json  TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (facility_id, n_reviews)
);

CREATE TABLE IF NOT EXISTS token_cache (
    h          TEXT PRIMARY KEY,       -- 本文のハッシュ（blake2b 8バイトの16進）
    tokens     TEXT NOT NULL,          -- 空白区切りの分かち書き結果
    created_at TEXT DEFAULT (datetime('now'))
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


# Bump when adding an ALTER-based migration in _migrate() below.
_SCHEMA_VERSION = 2


def _migrate(conn) -> None:
    """Apply incremental schema migrations keyed by PRAGMA user_version.

    New TABLES are handled by `CREATE TABLE IF NOT EXISTS` in SCHEMA. This
    runner exists for ALTER TABLE (new columns) on already-existing databases,
    which `CREATE ... IF NOT EXISTS` cannot add. Guarded so an unsupported
    backend is a harmless no-op.

    To add a migration: write the ALTER under `if ver < N:` and set
    _SCHEMA_VERSION = N. Example:
        if ver < 2:
            conn.execute("ALTER TABLE facility ADD COLUMN region TEXT")
    """
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        ver = int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return  # backend without PRAGMA support → skip silently

    if ver < 2:
        try:
            conn.execute("ALTER TABLE facility ADD COLUMN floor_area TEXT")
        except Exception:
            pass  # 既にカラムがある（CREATE TABLE IF NOT EXISTS 側で新規作成済み）等

    if ver < _SCHEMA_VERSION:
        try:
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.commit()
        except Exception:
            pass


def init_db(conn) -> None:
    """Create tables / indexes.  Split SCHEMA into individual statements
    so this works with both sqlite3.executescript() and libsql.execute()."""
    for stmt in (s.strip() for s in SCHEMA.split(";") if s.strip()):
        conn.execute(stmt)
    conn.commit()
    _migrate(conn)


# --------------------------------------------------------------------------- #
# Topic-score cache (永続化キャッシュ — 口コミ件数が変わったら自動失効)
# --------------------------------------------------------------------------- #
def get_topic_score_cache(conn, facility_id: int, n_reviews: int):
    """キャッシュがあれば {"topics_json": str, "overall_score": float, "n_sentences": int} を返す。"""
    row = conn.execute(
        "SELECT topics_json, overall_score, n_sentences FROM topic_score_cache "
        "WHERE facility_id = ? AND n_reviews = ?",
        (facility_id, n_reviews),
    ).fetchone()
    return dict(row) if row else None


def review_texts_by_facility(conn, names: Iterable[str]) -> dict[str, list[str]]:
    """指定した施設の口コミ本文を1クエリでまとめて読む。

    施設ごとに引くと Turso では施設数ぶんの HTTP 往復になる（46施設なら46回）。
    未計算の施設だけを渡して、まとめて取る用。
    """
    names = [n for n in names]
    if not names:
        return {}
    ph = ",".join("?" * len(names))
    rows = conn.execute(
        f"""SELECT f.name, r.text FROM review r
            JOIN facility f ON f.id = r.facility_id
            WHERE f.name IN ({ph}) AND r.text IS NOT NULL AND r.text != ''""",
        tuple(names),
    ).fetchall()
    out: dict[str, list[str]] = {n: [] for n in names}
    for r in rows:
        out.setdefault(r[0], []).append(r[1])
    return out


def get_topic_score_cache_bulk(conn) -> dict[tuple[int, int], dict]:
    """全施設ぶんのキャッシュを1クエリで読む。キーは (facility_id, n_reviews)。

    Turso は 1クエリ = 1 HTTPリクエストなので、施設ごとに引くと
    施設数ぶんの往復になり、遅いうえに 502 を踏む機会もその回数だけ増える。
    分析の頭でまとめて読む。
    """
    try:
        rows = conn.execute(
            "SELECT facility_id, n_reviews, topics_json, overall_score, n_sentences "
            "FROM topic_score_cache"
        ).fetchall()
    except Exception:
        return {}
    return {
        (r["facility_id"], r["n_reviews"]): {
            "topics_json": r["topics_json"],
            "overall_score": r["overall_score"],
            "n_sentences": r["n_sentences"],
        }
        for r in rows
    }


def set_topic_score_cache(
    conn,
    facility_id: int,
    n_reviews: int,
    topics_json: str,
    overall_score: float,
    n_sentences: int,
) -> None:
    """スコア結果をDBにキャッシュ保存する（同キーがあれば上書き）。"""
    set_topic_score_cache_bulk(
        conn, [(facility_id, n_reviews, topics_json, overall_score, n_sentences)]
    )


_TOPIC_CACHE_SQL = (
    "INSERT OR REPLACE INTO topic_score_cache "
    "(facility_id, n_reviews, topics_json, overall_score, n_sentences) "
    "VALUES (?, ?, ?, ?, ?)"
)


def set_topic_score_cache_bulk(conn, rows: list[tuple]) -> int:
    """複数施設ぶんをまとめて書く。rows = [(fid, n_reviews, json, score, n_sent), ...]

    施設ごとに書くと Turso では施設数ぶんの HTTP 往復になる。
    INSERT OR REPLACE なので、まとめ送りが途中で失敗してやり直しても安全。
    書けなくても分析は続行できる（次回また計算するだけ）。
    """
    rows = list(rows)
    if not rows:
        return 0
    try:
        if hasattr(conn, "execute_pipeline"):
            _CHUNK = 100
            for i in range(0, len(rows), _CHUNK):
                conn.execute_pipeline(
                    [(_TOPIC_CACHE_SQL, r) for r in rows[i:i + _CHUNK]]
                )
        else:
            for r in rows:
                conn.execute(_TOPIC_CACHE_SQL, r)
        conn.commit()
    except Exception:
        return 0
    return len(rows)


# --------------------------------------------------------------------------- #
# Text-profile cache (TF-IDF キーワード + N-gram を永続化)
# --------------------------------------------------------------------------- #
def get_text_profile_cache(conn, facility_id: int, n_reviews: int):
    """DBキャッシュがあれば {"tfidf_json", "bigrams_json", "trigrams_json",
    "high_rated_json", "low_rated_json"} を返す。"""
    row = conn.execute(
        "SELECT tfidf_json, bigrams_json, trigrams_json, high_rated_json, low_rated_json "
        "FROM text_profile_cache WHERE facility_id = ? AND n_reviews = ?",
        (facility_id, n_reviews),
    ).fetchone()
    return dict(row) if row else None


def set_text_profile_cache(
    conn,
    facility_id: int,
    n_reviews: int,
    tfidf_json: str,
    bigrams_json: str,
    trigrams_json: str,
    high_rated_json: str,
    low_rated_json: str,
) -> None:
    """TF-IDF プロファイルをDBにキャッシュ保存する（同キーがあれば上書き）。"""
    conn.execute(
        "INSERT OR REPLACE INTO text_profile_cache "
        "(facility_id, n_reviews, tfidf_json, bigrams_json, trigrams_json, "
        "high_rated_json, low_rated_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (facility_id, n_reviews, tfidf_json, bigrams_json, trigrams_json,
         high_rated_json, low_rated_json),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# 形態素解析のキャッシュ（本文は取り込み後に変わらないので失効しない）
# --------------------------------------------------------------------------- #
def load_token_cache(conn) -> dict[str, list[str]]:
    """トークンキャッシュを一括で読む。

    Turso は1クエリ＝1HTTPリクエストなので、1件ずつ引くと壊滅的に遅い。
    分析の開始時にまとめて読み、終了時にまとめて書く。
    """
    try:
        rows = conn.execute("SELECT h, tokens FROM token_cache").fetchall()
    except Exception:
        return {}
    return {r[0]: (r[1].split(" ") if r[1] else []) for r in rows}


def save_token_cache(conn, items: dict[str, list[str]]) -> int:
    """新しく解析したぶんだけを一括で書く。失敗しても分析は続行する。"""
    if not items:
        return 0
    rows = [(h, " ".join(toks)) for h, toks in items.items()]
    sql = "INSERT OR REPLACE INTO token_cache(h, tokens) VALUES (?, ?)"
    try:
        if hasattr(conn, "execute_pipeline"):
            _CHUNK = 200
            for i in range(0, len(rows), _CHUNK):
                conn.execute_pipeline([(sql, r) for r in rows[i:i + _CHUNK]])
        else:
            for r in rows:
                conn.execute(sql, r)
        conn.commit()
    except Exception:
        return 0
    return len(rows)


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
    floor_area: Optional[str] = None,
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
                   total_reviews  = COALESCE(?, total_reviews),
                   floor_area     = COALESCE(?, floor_area)
               WHERE id = ?""",
            (ftype, category, general_rating, total_reviews, floor_area, fid),
        )
    else:
        cur = conn.execute(
            """INSERT INTO facility(name, type, category, general_rating, total_reviews, floor_area)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, ftype, category, general_rating, total_reviews, floor_area),
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
        _CHUNK_STMTS = 100   # 1 HTTPリクエストあたりの文数（多いほど往復が減る）
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
        "floor_area": row["floor_area"],
        "score_axes": score_axes,
        "can_analyze": n >= 1,
        "can_tfidf": can_tfidf,
        "can_score": can_score,
    }


def monthly_review_counts(conn: sqlite3.Connection, facility_id: int) -> list[tuple[str, int]]:
    """施設の口コミを投稿月（'YYYY-MM'）でグルーピングした新規件数（非累積）。

    review_date が無い/パース不能な行は除外。月順（昇順）のリストを返す。
    """
    rows = conn.execute(
        "SELECT strftime('%Y-%m', review_date) as ym, COUNT(*) as cnt "
        "FROM review WHERE facility_id = ? AND review_date IS NOT NULL AND review_date != '' "
        "GROUP BY ym ORDER BY ym",
        (facility_id,),
    ).fetchall()
    return [(r["ym"], r["cnt"]) for r in rows if r["ym"]]


def monthly_rating_counts(
    conn: sqlite3.Connection, facility_id: int
) -> list[tuple[str, int, int, int]]:
    """月別にポジティブ（rating>=4）・ネガティブ（rating<=2）・合計件数を返す。

    Returns [(YYYY-MM, pos_count, neg_count, total), ...] 昇順。
    rating が NULL / 日付が無い行は除外。
    """
    rows = conn.execute(
        "SELECT strftime('%Y-%m', review_date) as ym, "
        "SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as pos, "
        "SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) as neg, "
        "COUNT(*) as total "
        "FROM review WHERE facility_id = ? AND review_date IS NOT NULL AND review_date != '' "
        "AND rating IS NOT NULL "
        "GROUP BY ym ORDER BY ym",
        (facility_id,),
    ).fetchall()
    return [(r["ym"], r["pos"], r["neg"], r["total"]) for r in rows if r["ym"]]


def monthly_sentiment_series(
    conn: sqlite3.Connection, facility_id: int
) -> list[tuple[str, int, float, float, float, float]]:
    """月別のポジ／ネガ要因スコア。SLIDE 4「時間軸分析」の素。

    5点満点の星評価を −1〜+1 に線形変換して集計する（PDF の注記どおり）:
        変換値 = (rating − 3) / 2      … ★5→+1.0 / ★3→0 / ★1→−1.0
        ポジティブ要因スコア = 変換値の正の部分の平均（0〜+1）
        ネガティブ要因スコア = 変換値の負の部分の平均（−1〜0）
        差分 = ポジ ＋ ネガ（＝変換値そのものの平均）

    Returns [(YYYY-MM, 件数, pos, neg, diff, 平均★), ...] 月順。
    rating か review_date が無い行は除外。
    """
    rows = conn.execute(
        "SELECT strftime('%Y-%m', review_date) as ym, rating "
        "FROM review WHERE facility_id = ? AND rating IS NOT NULL "
        "AND review_date IS NOT NULL AND review_date != ''",
        (facility_id,),
    ).fetchall()

    buckets: dict[str, list[float]] = {}
    for r in rows:
        if r["ym"]:
            buckets.setdefault(r["ym"], []).append(float(r["rating"]))

    out = []
    for ym in sorted(buckets):
        stars = buckets[ym]
        n = len(stars)
        conv = [(s - 3.0) / 2.0 for s in stars]
        pos = sum(c for c in conv if c > 0) / n
        neg = sum(c for c in conv if c < 0) / n
        out.append((ym, n, round(pos, 4), round(neg, 4),
                    round(pos + neg, 4), round(sum(stars) / n, 4)))
    return out


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
