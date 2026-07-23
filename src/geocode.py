"""施設名 → PROFILE項目（住所・アクセス・開業・業種）を OpenStreetMap から機械的に補完。

LLM（生成）は使わず、構造化データのみを使う:
  * 住所 / 緯度経度 / 開業(start_date) / 業種  … Nominatim
  * アクセス（最寄り駅・徒歩分）               … Overpass（最寄りの railway=station）

取得できない環境（通信ブロック・レート制限・該当なし）では空を返し、
呼び出し側は手入力にフォールバックする。結果は lru_cache でメモ化。
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_UA = "VoiceBAUM/0.8 (facility review analysis; contact: admin@example.com)"

# OSM の type/class → 表示用の業種ラベル
_CATEGORY_MAP = {
    "museum": "美術館・博物館", "gallery": "ギャラリー", "artwork": "美術・展示",
    "attraction": "観光施設", "theme_park": "テーマパーク", "zoo": "動物園",
    "aquarium": "水族館", "library": "図書館", "adery": "醸造所",
    "viewpoint": "展望施設", "hotel": "ホテル", "restaurant": "レストラン",
    "cafe": "カフェ", "information": "案内施設",
}


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _year(val: str) -> Optional[str]:
    """'2015' / '2015-04-01' / 'C1998' などから西暦4桁を抽出。"""
    if not val:
        return None
    import re
    m = re.search(r"(1[6-9]\d\d|20\d\d)", str(val))
    return f"{m.group(1)}年" if m else None


def _simplify(name: str) -> str:
    """長い正式名称を検索しやすい形へ（括弧書き除去・『・』等の前半を採用）。"""
    import re
    n = re.sub(r"[（(][^）)]*[）)]", "", name or "")     # （…）除去
    n = re.split(r"[・･/／|｜]", n)[0]                   # 『高浜市…美術館・図書館』→ 前半
    return n.strip()


def _nominatim_one(query: str) -> Optional[dict]:
    import requests
    try:
        resp = requests.get(
            NOMINATIM,
            params={"q": query, "format": "jsonv2", "limit": 1,
                    "accept-language": "ja", "addressdetails": 1, "extratags": 1},
            headers={"User-Agent": _UA}, timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not data:
        return None
    top = data[0]
    extra = top.get("extratags") or {}
    otype = top.get("type") or ""
    return {
        "address": top.get("display_name") or "",
        "lat": top.get("lat"),
        "lon": top.get("lon"),
        "open_year": _year(extra.get("start_date") or extra.get("opening_date") or ""),
        "category": _CATEGORY_MAP.get(otype) or _CATEGORY_MAP.get(top.get("category") or ""),
    }


def search_candidates(name: str, limit: int = 5) -> list[dict]:
    """施設名で OSM/Nominatim を検索し、候補一覧を返す（実在確認＋選択用）。

    各候補 dict:
      name          … 施設名（OSMの name、無ければ入力名）
      address       … 住所（display_name）
      lat, lon      … 緯度経度（文字列）
      category      … 業種ラベル（分かれば）
      maps_url      … Googleマップ検索リンク（名前＋住所）。KAIZODEにもこれを渡す
    通信不可・該当なしのときは空リスト（呼び出し側でフォールバック）。
    """
    import urllib.parse

    import requests
    name = (name or "").strip()
    if not name:
        return []
    try:
        resp = requests.get(
            NOMINATIM,
            params={"q": name, "format": "jsonv2", "limit": max(1, min(limit, 10)),
                    "accept-language": "ja", "addressdetails": 1, "extratags": 1},
            headers={"User-Agent": _UA}, timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    out: list[dict] = []
    for r in data or []:
        addr = r.get("display_name") or ""
        disp = (r.get("name") or "").strip() or name
        otype = r.get("type") or ""
        _q = urllib.parse.quote(f"{disp} {addr}".strip())
        out.append({
            "name": disp,
            "address": addr,
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "category": _CATEGORY_MAP.get(otype) or _CATEGORY_MAP.get(r.get("category") or ""),
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={_q}",
        })
    return out


def _ql_escape(s: str) -> str:
    """Overpass QL の二重引用符内で安全に使えるようにエスケープする。"""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def discover_by_keyword(keyword: str, area: str = "", limit: int = 15) -> list[dict]:
    """テーマ・キーワードから関連施設を発掘する（Overpass の name 正規表現検索）。

    search_candidates（Nominatim）は「その名前ズバリの場所」を探す仕組みで、
    「和紙」のようなテーマ語（施設の固有名ではない語）では基本ヒットしない。
    こちらは OSM の name タグに keyword を含む地物を Overpass で正規表現検索
    するため、テーマからの施設発掘に向く（生成AIは使わず構造化データへの
    問い合わせのみ）。

    area（都道府県・市区町村名）を指定すると検索範囲をその地域に限定する
    （速く・精度も上がるため推奨）。未指定だと日本全国が対象になり、公開
    Overpass サーバでは数秒〜数十秒かかる/失敗しやすい点に注意。
    """
    import urllib.parse

    import requests
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    kw = _ql_escape(keyword)
    if area.strip():
        area_clause = f'area["name"="{_ql_escape(area.strip())}"]->.a;'
    else:
        area_clause = 'area["ISO3166-1"="JP"][admin_level=2]->.a;'
    limit = max(1, min(limit, 20))
    ql = (
        f'[out:json][timeout:25];'
        f'{area_clause}'
        f'(node["name"~"{kw}",i](area.a);way["name"~"{kw}",i](area.a);'
        f'relation["name"~"{kw}",i](area.a););'
        f'out center {limit};'
    )
    try:
        resp = requests.post(OVERPASS, data={"data": ql},
                             headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    seen: set[str] = set()
    out: list[dict] = []
    for el in (data.get("elements") or [])[:limit]:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        addr = "".join(
            tags.get(k, "") for k in
            ("addr:prefecture", "addr:city", "addr:suburb", "addr:street", "addr:housenumber")
        )
        otype = (tags.get("tourism") or tags.get("craft") or tags.get("shop")
                 or tags.get("amenity") or tags.get("leisure") or "")
        q = urllib.parse.quote(f"{name} {addr or area}".strip())
        out.append({
            "name": name,
            "address": addr,
            "lat": str(lat) if lat is not None else None,
            "lon": str(lon) if lon is not None else None,
            "category": _CATEGORY_MAP.get(otype),
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={q}",
        })
    return out


@lru_cache(maxsize=512)
def _geocode(name: str, hint: str = "") -> Optional[dict]:
    if not name or not name.strip():
        return None
    try:
        import requests  # noqa: F401  存在確認
    except Exception:
        return None
    # フル名称 → 簡略名 の順で試す（長い正式名はヒットしにくいため）
    full = f"{name} {hint}".strip()
    queries = [full]
    simp = _simplify(name)
    simp_q = f"{simp} {hint}".strip()
    if simp and simp != name and simp_q != full:
        queries.append(simp_q)
    for q in queries:
        r = _nominatim_one(q)
        if r and r.get("address"):
            return r
    return None


@lru_cache(maxsize=512)
def _nearest_station(lat: float, lon: float) -> Optional[tuple]:
    """(駅名, 徒歩分) or None。Overpass で 2km 以内の最寄り railway=station。"""
    try:
        import requests
    except Exception:
        return None
    q = (f'[out:json][timeout:10];'
         f'(node["railway"="station"](around:2500,{lat},{lon});'
         f'node["railway"="halt"](around:2500,{lat},{lon}););out body;')
    try:
        resp = requests.post(OVERPASS, data={"data": q},
                             headers={"User-Agent": _UA}, timeout=12)
        resp.raise_for_status()
        els = resp.json().get("elements", [])
    except Exception:
        return None
    best = None
    for e in els:
        nm = (e.get("tags") or {}).get("name")
        if not nm or e.get("lat") is None:
            continue
        d = _haversine_m(lat, lon, e["lat"], e["lon"])
        if best is None or d < best[1]:
            best = (nm, d)
    if not best:
        return None
    name = best[0] if best[0].endswith("駅") else best[0] + "駅"
    walk_min = max(1, round(best[1] / 80))   # 80 m/分
    return (name, walk_min)


@lru_cache(maxsize=512)
def _wikidata_facts(name: str) -> dict:
    """Wikidata の設立(P571) → 開業年。生成なし・構造化データのみ。無ければ {}。"""
    if not name or not name.strip():
        return {}
    try:
        import requests
    except Exception:
        return {}
    try:
        s = requests.get(WIKIDATA_API, params={
            "action": "wbsearchentities", "search": name, "language": "ja",
            "format": "json", "limit": 1, "type": "item"},
            headers={"User-Agent": _UA}, timeout=5)
        s.raise_for_status()
        hits = s.json().get("search", [])
        if not hits:
            return {}
        qid = hits[0]["id"]
        e = requests.get(WIKIDATA_API, params={
            "action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"},
            headers={"User-Agent": _UA}, timeout=5)
        e.raise_for_status()
        claims = e.json().get("entities", {}).get(qid, {}).get("claims", {})
    except Exception:
        return {}
    for c in claims.get("P571", []):   # P571 = inception（設立/開業）
        try:
            t = c["mainsnak"]["datavalue"]["value"]["time"]   # 例 "+2015-04-01T00:00:00Z"
        except Exception:
            continue
        y = _year(t)
        if y:
            return {"open_year": y}
    return {}


def lookup(name: str, hint: str = "") -> Optional[dict]:
    """住所のみの軽量取得（プレビュー初期表示用）。"""
    g = _geocode(name, hint)
    if g and g.get("address"):
        return {"address": g["address"], "lat": g.get("lat"), "lon": g.get("lon")}
    return None


def enrich(name: str, hint: str = "") -> dict:
    """住所・アクセス・開業・業種をまとめて機械補完（取れた項目のみ）。"""
    g = _geocode(name, hint) or {}
    out = {
        "address": g.get("address"),
        "open_year": g.get("open_year"),
        "category": g.get("category"),
    }
    if g.get("lat") and g.get("lon"):
        try:
            st = _nearest_station(float(g["lat"]), float(g["lon"]))
        except Exception:
            st = None
        if st:
            out["access"] = f"{st[0]} 徒歩約{st[1]}分"
    # 開業は OSM に無いことが多いので Wikidata(設立) で補完
    if not out.get("open_year"):
        wf = _wikidata_facts(name)
        if wf.get("open_year"):
            out["open_year"] = wf["open_year"]
    return {k: v for k, v in out.items() if v}
