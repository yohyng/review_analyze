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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd


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
# public API
# --------------------------------------------------------------------------- #
def parse_reviews(source) -> ParseResult:
    """Parse a review CSV/TSV (path or file-like) into a ParseResult."""
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
