"""Google Places API (New) から施設写真を引く。

**規約の制約が設計をほぼ決めている**（Google Maps Platform の利用規約）:

  保存してよい          place_id …… 無期限
  保存してよい          緯度経度 …… 最大30日
  保存してはいけない    写真・名称・評価・レビュー …… 都度取得

  → 写真そのものは DB に持てない。持てるのは place_id だけ。
    なので「place_id は施設マスタに1回だけ保存」「写真は表示のたびに取得」
    という形になる。PPTX に焼き込むのは保存・再配布にあたるので、
    ここで取った写真は **画面プレビュー専用**。配布物には
    facility_photo（手動アップロード）のぶんだけを使う。

  → 帰属表示（authorAttributions）の表示が必須。photo_attribution() で返す。

課金の考え方（2025年3月からSKUごとの無料枠）:
  - place_id の検索は Text Search の「ID のみ」= 一番安いSKU。
    しかも place_id は保存できるので **施設あたり生涯1回**で済む。
  - Place Details は photos フィールドを要求した時点で Pro 階層（無料枠 5,000/月）。
  - Place Photos は別SKU。
  レポート1回の閲覧で 6施設 × (Details 1 + Photos 1) = 12 呼び出し。

写真は資料の飾りなので、**失敗しても例外を投げない**（None を返す）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
_MEDIA_URL = "https://places.googleapis.com/v1/{photo_name}/media"

_TIMEOUT = 8
DEFAULT_MAX_PX = 800


@dataclass
class Photo:
    """表示に必要な最小限。写真そのものは保持しない（保存禁止のため）。"""
    url: str                      # <img src> にそのまま入れる Google 提供のURL
    attribution: str = ""         # 帰属表示。必ず写真の近くに出すこと

    def __bool__(self) -> bool:
        return bool(self.url)


def get_api_key() -> str:
    """env GOOGLE_MAPS_API_KEY → streamlit secrets → ''。"""
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if key:
        return key
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get("GOOGLE_MAPS_API_KEY", "") or ""
    except Exception:
        return ""


def _post(url: str, key: str, field_mask: str, body: dict):
    import requests  # noqa: PLC0415

    resp = requests.post(
        url, json=body, timeout=_TIMEOUT,
        headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": field_mask,
                 "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def _get(url: str, key: str, field_mask: str):
    import requests  # noqa: PLC0415

    resp = requests.get(
        url, timeout=_TIMEOUT,
        headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": field_mask},
    )
    resp.raise_for_status()
    return resp.json()


def find_place_id(name: str, api_key: str) -> str | None:
    """施設名から place_id を引く。

    FieldMask を places.id だけに絞る＝Text Search の一番安いSKU。
    place_id は保存してよいので、施設あたり1回引けば以降は不要。
    """
    if not (name or "").strip() or not api_key:
        return None
    try:
        data = _post(_SEARCH_URL, api_key, "places.id",
                     {"textQuery": name.strip(), "languageCode": "ja",
                      "maxResultCount": 1})
    except Exception:
        return None
    places = data.get("places") or []
    return (places[0].get("id") or None) if places else None


def maps_url(place_id: str) -> str:
    """place_id を指す Google マップの URL。

    施設名で検索する URL（/maps/search/?query=…）と違い、**その施設1件を
    確実に指す**。KAIZODE への発注はこちらを渡したい（名前で検索させると
    同名の別施設を拾って、収集枠を無駄にしうる）。
    """
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ""


@dataclass
class Resolved:
    """施設名から引き当てた Google 上の1件。"""
    place_id: str
    name: str = ""
    address: str = ""

    @property
    def maps_url(self) -> str:
        return maps_url(self.place_id)


def resolve(name: str, api_key: str) -> Resolved | None:
    """施設名から place_id・正式名称・住所を引く。

    find_place_id より1段リッチな（＝1段高いSKUの）呼び出し。施設の登録時に
    1回だけ使う想定。名称と住所を出して「この施設で合っているか」を人が
    確かめられるようにするため（KAIZODE の収集枠を無駄にしないのが目的）。
    """
    if not (name or "").strip() or not api_key:
        return None
    try:
        data = _post(_SEARCH_URL, api_key,
                     "places.id,places.displayName,places.formattedAddress",
                     {"textQuery": name.strip(), "languageCode": "ja",
                      "maxResultCount": 1})
    except Exception:
        return None
    places = data.get("places") or []
    if not places or not places[0].get("id"):
        return None
    p = places[0]
    return Resolved(
        place_id=p["id"],
        name=(p.get("displayName") or {}).get("text", "") or "",
        address=p.get("formattedAddress", "") or "",
    )


@dataclass
class Details:
    """表示に使う施設情報。いずれも保存せず、都度取得する。"""
    photo: Photo | None = None
    address: str = ""


def fetch_details(place_id: str, api_key: str, *,
                  max_px: int = DEFAULT_MAX_PX) -> Details:
    """place_id から写真と住所をまとめて取る。

    写真と住所を **1回の Details 呼び出し**で取る。photos を要求した時点で
    Pro 階層になるので、住所を足しても課金は変わらない（ただ乗りできる）。
    取れなければ空の Details を返す（写真も住所も資料の飾り）。
    """
    if not place_id or not api_key:
        return Details()
    try:
        data = _get(_DETAILS_URL.format(place_id=place_id), api_key,
                    "photos,formattedAddress")
    except Exception:
        return Details()

    out = Details(address=data.get("formattedAddress", "") or "")
    photos = data.get("photos") or []
    if photos and photos[0].get("name"):
        first = photos[0]
        who = [
            a.get("displayName", "").strip()
            for a in (first.get("authorAttributions") or [])
            if a.get("displayName")
        ]
        out.photo = Photo(
            url=(f"{_MEDIA_URL.format(photo_name=first['name'])}"
                 f"?maxWidthPx={int(max_px)}&key={api_key}"),
            attribution=("Google / " + "・".join(who[:2])) if who else "Google",
        )
    return out


def fetch_photo(place_id: str, api_key: str, *,
                max_px: int = DEFAULT_MAX_PX) -> Photo | None:
    """place_id から写真URLと帰属表示を得る。取れなければ None。"""
    return fetch_details(place_id, api_key, max_px=max_px).photo


def place_id_for(conn, name: str, api_key: str) -> str | None:
    """施設名に対応する place_id。無ければ引いて DB に覚える。

    place_id は規約上、無期限に保存してよい唯一の Places コンテンツ。
    覚えておけば、以降の呼び出しから検索1回ぶんを削れる。
    """
    from . import db  # noqa: PLC0415

    if not api_key:
        return None
    pid = db.get_place_id(conn, name)
    if pid:
        return pid
    pid = find_place_id(name, api_key)
    if pid:
        db.set_place_id(conn, name, pid)      # 失敗しても続行できるので握る
    return pid


def details_for_facility(conn, name: str, api_key: str, *,
                         max_px: int = DEFAULT_MAX_PX) -> Details:
    """施設名から写真と住所を。place_id は DB に覚える。"""
    pid = place_id_for(conn, name, api_key)
    return fetch_details(pid, api_key, max_px=max_px) if pid else Details()


def photo_for_facility(conn, name: str, api_key: str, *,
                       max_px: int = DEFAULT_MAX_PX) -> Photo | None:
    """施設名から写真を1枚。"""
    return details_for_facility(conn, name, api_key, max_px=max_px).photo
