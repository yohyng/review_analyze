"""Fuzzy facility name search.

suggest(query, names)  →  list of close matches
Used on the "施設を選ぶ" page to show "これですか？" hints when the
user types a facility name that might already exist in the DB.
"""
from __future__ import annotations

import difflib
import unicodedata


def _normalize(s: str) -> str:
    """Lower-case + NFKC for fair CJK comparison."""
    return unicodedata.normalize("NFKC", s).lower().strip()


def suggest(query: str, names: list[str], n: int = 4) -> list[str]:
    """Return up to n facility names that are close to query.

    Combines:
      - difflib close matches (edit-distance based)
      - substring containment (handles partial name input)
    """
    if not query or not names:
        return []
    nq = _normalize(query)
    scored: list[tuple[float, str]] = []
    for name in names:
        nn = _normalize(name)
        ratio = difflib.SequenceMatcher(None, nq, nn).ratio()
        # boost if one contains the other
        if nq in nn or nn in nq:
            ratio = max(ratio, 0.75)
        if ratio >= 0.45:
            scored.append((ratio, name))
    scored.sort(key=lambda x: -x[0])
    # exclude exact match (no need to suggest what was typed exactly)
    return [name for _, name in scored if _normalize(name) != nq][:n]
