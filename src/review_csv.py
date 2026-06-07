"""Step 3: parse a KAIZODE / Google-Maps review CSV (or TSV).

The export is messy, so this module is defensive:
  * delimiter auto-detected (tab vs comma)
  * `review` may be quoted and span multiple lines  -> handled by pandas
  * `review_details` / `photos` / `input` use Python-literal (single-quote)
    syntax, NOT JSON                                -> ast.literal_eval
  * `place_name` is often blank                     -> facility name is supplied
    by the caller (hand-typed in the UI)
  * header `overall_place_riviews` is misspelled    -> both spellings accepted
  * rows with an `error` value are skipped
  * missing review ids get a stable hash fallback so re-uploads still dedup
"""
from __future__ import annotations

import ast
import hashlib
import io
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# 47 prefectures — used to split "施設名 + 住所" query strings
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


@dataclass
class ParsedReview:
    review_id: str
    rating: Optional[int]
    text: str
    review_date: str
    reviewer_name: str
    local_guide: bool
    likes: Optional[int]
    owner_response: str
    owner_response_date: str
    subscores: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class ParseResult:
    reviews: list[ParsedReview]
    general_rating: Optional[float] = None
    total_reviews: Optional[int] = None
    category: Optional[str] = None
    n_raw: int = 0
    n_skipped: int = 0


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _load_text(source) -> str:
    """Read a path or file-like into text, trying common JP encodings."""
    if hasattr(source, "read"):
        data = source.read()
    else:
        with open(source, "rb") as f:
            data = f.read()
    if isinstance(data, bytes):
        for enc in ("utf-8-sig", "utf-8", "cp932"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
    return data


def _read_dataframe(text: str) -> pd.DataFrame:
    """Parse text into a DataFrame, auto-detecting tab vs comma delimiter."""
    header = text.split("\n", 1)[0]
    delim = "\t" if header.count("\t") >= header.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False)
    if df.shape[1] == 1 and delim != ",":
        df = pd.read_csv(io.StringIO(text), sep=",", dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _safe_literal(cell: str):
    """ast.literal_eval that returns None instead of raising."""
    if not isinstance(cell, str) or not cell.strip():
        return None
    try:
        return ast.literal_eval(cell)
    except (ValueError, SyntaxError):
        return None


def _to_float(val) -> Optional[float]:
    try:
        return float(str(val).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _to_int(val) -> Optional[int]:
    f = _to_float(val)
    return int(f) if f is not None else None


def _col(row: dict, *names: str) -> str:
    """First non-empty value among candidate column names."""
    for n in names:
        v = row.get(n, "")
        if v not in (None, ""):
            return v
    return ""


def _parse_subscores(cell: str) -> list[tuple[str, float]]:
    """`[{'title': 'Rooms', 'value': '5'}, ...]` -> [('Rooms', 5.0), ...]."""
    obj = _safe_literal(cell)
    out: list[tuple[str, float]] = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item.get("title"):
                v = _to_float(item.get("value"))
                if v is not None:
                    out.append((str(item["title"]).strip(), v))
    return out


def _fallback_id(text: str, date: str, reviewer: str) -> str:
    h = hashlib.sha1(f"{text}|{date}|{reviewer}".encode("utf-8")).hexdigest()[:16]
    return f"h:{h}"


# --------------------------------------------------------------------------- #
# facility-name inference (which facility is this CSV about?)
# --------------------------------------------------------------------------- #
def _strip_address(text: str) -> str:
    """'風の海 山口県下関市…' -> '風の海' (cut at prefecture, else first space)."""
    text = (text or "").strip()
    if not text:
        return ""
    for pref in PREFECTURES:
        idx = text.find(pref)
        if idx > 0:
            return text[:idx].strip(" 　,、")
    parts = re.split(r"[ 　]", text, maxsplit=1)
    return parts[0].strip()


def _decode_query_name(input_cell: str, url_cell: str) -> str:
    """Pull a facility name out of the search-URL `query=` parameter."""
    url = ""
    obj = _safe_literal(input_cell)
    if isinstance(obj, dict):
        url = obj.get("url", "")
    if not url:
        url = url_cell or ""
    if not url:
        return ""
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        q = qs.get("query", [""])[0]
    except (ValueError, KeyError):
        q = ""
    return _strip_address(urllib.parse.unquote(q))


def _facility_key_name(row: dict) -> tuple[str, str]:
    """Return (grouping_key, display_name) for one row."""
    name = _col(row, "place_name")
    if not name:
        name = _decode_query_name(_col(row, "input"), _col(row, "url"))
    key = _col(row, "place_id") or _col(row, "cid") or name
    return key, name


def infer_facilities(source) -> list[dict]:
    """Inspect a CSV and guess which facility/facilities it covers.

    Returns a list (most reviews first) of:
        {key, name, count, avg_rating}
    One entry per detected facility — a single CSV may contain several.
    """
    df = _read_dataframe(_load_text(source))
    groups: dict[str, dict] = {}
    for row in df.to_dict("records"):
        if _col(row, "error", "error_code"):
            continue
        if not _col(row, "review") and not _col(row, "review_rating"):
            continue
        key, name = _facility_key_name(row)
        key = key or "(不明)"
        g = groups.setdefault(key, {"names": Counter(), "count": 0, "ratings": []})
        if name:
            g["names"][name] += 1
        g["count"] += 1
        r = _to_float(_col(row, "review_rating"))
        if r is not None:
            g["ratings"].append(r)

    out = []
    for key, g in groups.items():
        name = g["names"].most_common(1)[0][0] if g["names"] else "(不明)"
        ratings = g["ratings"]
        out.append({
            "key": key,
            "name": name,
            "count": g["count"],
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        })
    out.sort(key=lambda x: -x["count"])
    return out


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def parse_reviews(source, facility_key: Optional[str] = None) -> ParseResult:
    """Parse a review CSV/TSV (path or file-like) into a ParseResult.

    If facility_key is given, only rows belonging to that facility (per
    infer_facilities' grouping) are included — used for multi-facility CSVs.
    """
    df = _read_dataframe(_load_text(source))
    records = df.to_dict("records")

    reviews: list[ParsedReview] = []
    general_rating = total_reviews = category = None
    n_skipped = 0

    for row in records:
        # skip scraper-error rows
        if _col(row, "error", "error_code"):
            n_skipped += 1
            continue

        # multi-facility filter
        if facility_key is not None and _facility_key_name(row)[0] != facility_key:
            continue

        text = _col(row, "review")
        date = _col(row, "review_date")
        reviewer = _col(row, "reviewer_name")
        review_id = _col(row, "review_id") or _fallback_id(text, date, reviewer)

        # drop empty junk lines
        if not text and not _col(row, "review_rating"):
            n_skipped += 1
            continue

        reviews.append(
            ParsedReview(
                review_id=review_id,
                rating=_to_int(_col(row, "review_rating")),
                text=text,
                review_date=date,
                reviewer_name=reviewer,
                local_guide=_col(row, "local_guide").strip().upper() == "TRUE",
                likes=_to_int(_col(row, "number_of_likes")),
                owner_response=_col(row, "response_of_owner"),
                owner_response_date=_col(row, "response_date"),
                subscores=_parse_subscores(_col(row, "review_details")),
            )
        )

        # facility-level meta: take first non-empty
        if general_rating is None:
            general_rating = _to_float(_col(row, "place_general_rating"))
        if total_reviews is None:
            total_reviews = _to_int(
                _col(row, "overall_place_reviews", "overall_place_riviews")
            )
        if category is None:
            category = _col(row, "category") or None

    return ParseResult(
        reviews=reviews,
        general_rating=general_rating,
        total_reviews=total_reviews,
        category=category,
        n_raw=len(records),
        n_skipped=n_skipped,
    )


if __name__ == "__main__":  # quick manual check
    import sys

    res = parse_reviews(Path(sys.argv[1]))
    print(f"parsed {len(res.reviews)} reviews "
          f"(raw={res.n_raw}, skipped={res.n_skipped})")
    print(f"general_rating={res.general_rating}, total_reviews={res.total_reviews}")
    for r in res.reviews[:3]:
        print(f"  [{r.rating}*] {r.review_id[:12]}  subscores={r.subscores}")
