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
    同じ階層の formattedAddress / userRatingCount / rating は相乗りできる（追加課金なし）。
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

# data: URI にして埋め込むので、極端に大きい画像は弾く（HTMLが膨らむ）。
_MAX_PHOTO_BYTES = 4 * 1024 * 1024


@dataclass
class Photo:
    """表示に必要な最小限。写真そのものは保持しない（保存禁止のため）。

    **APIキーをここに入れないこと**。以前は `key=...` を含む媒体URLを持たせて
    そのまま `<img src>` に流していたが、それはキーをページのHTMLに露出させる
    （分析画面はログイン不要なので、ソースを表示すれば誰でも読める）。
    保持するのは `photos/xxx` というリソース名だけで、実体の取得は
    fetch_photo_data_uri() がサーバ側で行う。
    """
    name: str                     # "places/X/photos/Y" というリソース名
    attribution: str = ""         # 帰属表示。必ず写真の近くに出すこと

    def __bool__(self) -> bool:
        return bool(self.name)


SESSION_KEY = "places_session_key"


def _secret(name: str) -> str:
    """secrets.toml から読む。**単独の try で囲むこと**（理由は llm._secret）。"""
    try:
        import streamlit as st  # noqa: PLC0415

        return st.secrets.get(name, "") or ""
    except Exception:
        return ""


def _session_key(name: str) -> str:
    """管理画面でのセッション入力。DBやファイルには保存しない。"""
    try:
        import streamlit as st  # noqa: PLC0415

        return st.session_state.get(name, "") or ""
    except Exception:
        return ""


def get_api_key() -> str:
    """環境変数 → Streamlit secrets → 管理画面でのセッション入力、の順に探す。

    セッション入力も見るのは、恒久設定を持たない環境でも管理画面から
    使えるようにするため（Gemini / KAIZODE と同じ扱い）。
    **DBやファイルには保存しない**。
    """
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if key:
        return key
    return _secret("GOOGLE_MAPS_API_KEY") or _session_key(SESSION_KEY)


def api_key_source() -> str:
    """どこから読めたか。画面に出して切り分けに使う。"""
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        return "環境変数"
    if _secret("GOOGLE_MAPS_API_KEY"):
        return "secrets"
    if _session_key(SESSION_KEY):
        return "セッション入力"
    return ""


def ping(api_key: str) -> tuple[bool, str]:
    """鍵が通るかだけ確かめる。**一番安いSKU**（Text Search の ID のみ）。

    find_place_id() と同じ呼び出しだが、あちらは写真が飾りなので例外を
    握り潰す。こちらは「設定できたつもりで通っていない」を切り分けるのが
    目的なので、**失敗の理由をそのまま返す**。
    """
    if not api_key:
        return False, "APIキーが未設定です"
    import requests  # noqa: PLC0415

    resp = None
    try:
        resp = requests.post(
            _SEARCH_URL,
            json={"textQuery": "東京駅", "languageCode": "ja",
                  "maxResultCount": 1},
            timeout=_TIMEOUT,
            headers={"X-Goog-Api-Key": api_key,
                     "X-Goog-FieldMask": "places.id",
                     "Content-Type": "application/json"},
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        detail = _extract_api_error(resp)
        hint = ""
        if resp is not None and resp.status_code == 403:
            hint = ("／Places API (New) が有効か、キーの制限"
                    "（HTTPリファラ・IP）を確認してください")
        return False, f"API エラー ({resp.status_code}): {detail}{hint}"
    except requests.exceptions.RequestException as e:
        return False, f"通信エラー: {e}"
    if not (resp.json().get("places") or []):
        return False, "応答は返りましたが結果が空でした（FieldMask を確認）"
    return True, "接続できました（Text Search・IDのみ）"


def _extract_api_error(resp) -> str:
    """エラー応答から人が読める理由を取り出す。

    `.get("message", resp.text[:200])` と書かないこと。default は
    **必ず評価される**ので、JSON が取れている場合でも本文の復号が走る。
    """
    if resp is None:
        return "応答なし"
    try:
        msg = resp.json().get("error", {}).get("message", "")
        if msg:
            return str(msg)
    except Exception:
        pass
    try:
        return resp.text[:200]
    except Exception:
        return "（本文を読めませんでした）"


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
class Candidate:
    """検索で出てきた Google 上の施設の候補、1件ぶん。

    「施設名を入れる → 候補を見る → これでいい、と決めてから集める」
    ための材料。件数と評価を並べるのは、**KAIZODE に発注する前に**
    同名の別施設や支店を取り違えていないかを人が確かめられるようにするため
    （発注は取り消せないうえ、月の取得枠を減らす）。

    review_count / rating は **保存しないこと**（place_id 以外は都度取得）。
    """
    place_id: str
    name: str = ""
    address: str = ""
    review_count: int | None = None
    rating: float | None = None
    # Google 自身が返す、その施設の正規URL。
    # KAIZODE は「マップで施設を開いたときのURL」を正とするため、
    # こちらを優先して渡す（?q=place_id:… では拾えない場合がある）。
    maps_uri: str = ""

    @property
    def maps_url(self) -> str:
        return self.maps_uri or maps_url(self.place_id)


def search_candidates(name: str, api_key: str, *,
                      limit: int = 5) -> list["Candidate"]:
    """施設名から候補を複数返す。件数の多い順。

    resolve() は先頭1件を黙って採る。こちらは人に選ばせるためのもので、
    同名の別館・支店を取り違えたまま発注する事故を防ぐのが目的。

    **課金の注意**: userRatingCount / rating は Text Search の中でも上の
    SKU 階層に入る可能性が高い（2025年3月からのSKU区分）。ここは
    「集める前に1回」しか呼ばない前提で、呼び出し側でキャッシュすること。
    実際にどの階層で課金されたかは Google Cloud の請求画面で確かめてほしい
    （この開発環境からは料金表に到達できず、机上で断定できない）。
    """
    if not (name or "").strip() or not api_key:
        return []
    try:
        data = _post(
            _SEARCH_URL, api_key,
            "places.id,places.displayName,places.formattedAddress,"
            "places.userRatingCount,places.rating,places.googleMapsUri",
            {"textQuery": name.strip(), "languageCode": "ja",
             "maxResultCount": max(1, min(int(limit), 20))},
        )
    except Exception:
        return []
    out: list[Candidate] = []
    for p in (data.get("places") or []):
        if not p.get("id"):
            continue
        out.append(Candidate(
            place_id=p["id"],
            name=(p.get("displayName") or {}).get("text", "") or "",
            address=p.get("formattedAddress", "") or "",
            review_count=p.get("userRatingCount"),
            rating=p.get("rating"),
            maps_uri=p.get("googleMapsUri", "") or "",
        ))
    # 件数の多い順。不明は末尾に置く（選ばせる材料が無いので）。
    out.sort(key=lambda c: (c.review_count is None, -(c.review_count or 0)))
    return out


@dataclass
class Details:
    """表示に使う施設情報。いずれも保存せず、都度取得する。"""
    photo: Photo | None = None
    address: str = ""
    # Google マップ上の総評価数と平均。KAIZODE がどれだけ拾えているかの分母。
    #   **保存しないこと**（規約上、無期限に保存してよいのは place_id だけ）。
    #   表示のたびに取り直す。
    review_count: int | None = None
    rating: float | None = None


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
        # userRatingCount / rating は photos と同じ Pro 階層なので、
        # ここに足しても課金は変わらない（住所と同じ相乗り）。
        data = _get(_DETAILS_URL.format(place_id=place_id), api_key,
                    "photos,formattedAddress,userRatingCount,rating")
    except Exception:
        return Details()

    def _num(v, cast):
        try:
            return cast(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    out = Details(
        address=data.get("formattedAddress", "") or "",
        review_count=_num(data.get("userRatingCount"), int),
        rating=_num(data.get("rating"), float),
    )
    photos = data.get("photos") or []
    if photos and photos[0].get("name"):
        first = photos[0]
        who = [
            a.get("displayName", "").strip()
            for a in (first.get("authorAttributions") or [])
            if a.get("displayName")
        ]
        out.photo = Photo(
            name=first["name"],
            attribution=("Google / " + "・".join(who[:2])) if who else "Google",
        )
    return out


def fetch_photo_data_uri(photo_name: str, api_key: str, *,
                         max_px: int = DEFAULT_MAX_PX) -> str:
    """写真の実体をサーバ側で取って data: URI にする。取れなければ ""。

    **APIキーをブラウザに渡さないための関数**。媒体URLに `key=` を付けて
    `<img src>` に置くと、分析画面（ログイン不要）のHTMLからキーが読めてしまう。
    ここで取得を済ませてしまえば、キーはサーバとGoogleの間から出ない。

    保存はしない（規約上、写真は都度取得）。呼び出し側が短時間だけ
    メモリに載せる（_places_cached の ttl）ぶんは性能目的の一時キャッシュ。
    """
    if not photo_name or not api_key:
        return ""
    import base64      # noqa: PLC0415
    import requests    # noqa: PLC0415

    try:
        resp = requests.get(
            _MEDIA_URL.format(photo_name=photo_name),
            params={"maxWidthPx": int(max_px)},
            headers={"X-Goog-Api-Key": api_key},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception:
        return ""

    blob = resp.content or b""
    if not blob or len(blob) > _MAX_PHOTO_BYTES:
        return ""
    mime = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if not mime.startswith("image/"):
        return ""
    return f"data:{mime};base64," + base64.b64encode(blob).decode()


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
