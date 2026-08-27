"""新規施設の追加を「名前を入れる → 1クリック → あとは自動」にするための土台。

これまでの導線は9ステップあった:
  1 ヒーロー検索に施設名を入れる
  2 候補に無いので expander を開く
  3 未ログインなら管理モードへ飛んでログインし、戻ってくる
  4 **もう一度**「Google MapsのURL または 施設名」に入力する
  5 施設情報の照会を待つ
  6「今すぐ集める」を押す
  7 収集を待つ
  8「取り込みを再度試す」を押す
  9 分析画面に戻って「この内容で分析する」を押す

構造上どうしても縮められないのは 7（KAIZODE は外部の収集なので実時間がかかる）。
それ以外は自動化できる。ここでは「いま何をすべきか」を1つの関数で判定し、
UI 側は判定に従って画面を1枚出すだけにする。

Streamlit に依存しないので、そのままテストから呼べる。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 何をすべきか
READY = "ready"            # DBに口コミがある → すぐ分析できる
EMPTY = "empty"            # 施設はあるが口コミが無い → 収集が要る
NEW = "new"                # DBに無い → 登録して収集する
AMBIGUOUS = "ambiguous"    # 名前が曖昧 → 候補から選ばせる
NOT_FOUND = "not_found"    # Google でも見つからない → 手がかりを求める


@dataclass
class Plan:
    """入力された施設名に対して、次に何をすべきか。"""
    action: str
    query: str = ""
    facility: str = ""              # 確定した施設名（DB上の名前）
    candidates: list[str] = field(default_factory=list)
    n_reviews: int = 0
    place_id: str = ""
    address: str = ""
    display_name: str = ""          # Google 上の正式名称
    maps_url: str = ""

    @property
    def needs_collection(self) -> bool:
        return self.action in (EMPTY, NEW)

    @property
    def label(self) -> str:
        """ボタンに出す1行。何が起きるかを言い切る。"""
        who = self.display_name or self.facility or self.query
        if self.action == READY:
            return f"「{who}」を分析する（口コミ {self.n_reviews:,} 件）"
        if self.needs_collection:
            return f"「{who}」の口コミを集めて分析する"
        return ""


def plan(conn, query: str, *, names: list[str] | None = None,
         gmaps_key: str = "") -> Plan:
    """入力された施設名から、次にやることを1つ決める。

    - DB に完全一致があり口コミもある      → READY（そのまま分析）
    - DB に完全一致があるが口コミが無い     → EMPTY（収集）
    - DB に無く、Google で1件に定まる       → NEW（登録して収集）
    - DB に似た名前が複数ある               → AMBIGUOUS（選ばせる）
    - どこにも無い                          → NOT_FOUND
    """
    from . import db, places, search  # noqa: PLC0415

    q = (query or "").strip()
    if not q:
        return Plan(action=NOT_FOUND, query=q)

    if names is None:
        names = [r["name"] for r in
                 conn.execute("SELECT name FROM facility ORDER BY name").fetchall()]

    exact = next((n for n in names if n == q), None)
    if exact:
        n_rev = _review_count(conn, exact)
        return Plan(action=READY if n_rev else EMPTY,
                    query=q, facility=exact, n_reviews=n_rev)

    # 部分一致 + あいまい検索。1件に絞れなければ選ばせる。
    subs = [n for n in names if q.lower() in n.lower()]
    cands: list[str] = []
    for n in subs + search.suggest(q, names):
        if n not in cands:
            cands.append(n)

    if len(cands) == 1:
        only = cands[0]
        n_rev = _review_count(conn, only)
        return Plan(action=READY if n_rev else EMPTY,
                    query=q, facility=only, n_reviews=n_rev, candidates=cands)
    if cands:
        return Plan(action=AMBIGUOUS, query=q, candidates=cands[:8])

    # DB に手がかりが無い → Google で1件に確定できるか
    r = places.resolve(q, gmaps_key) if gmaps_key else None
    if r:
        return Plan(action=NEW, query=q, facility=r.name or q,
                    place_id=r.place_id, address=r.address,
                    display_name=r.name, maps_url=r.maps_url)
    # キーが無くても、名前だけで発注はできる（確度は落ちる）
    return Plan(action=NEW if q else NOT_FOUND, query=q, facility=q,
                display_name=q)


def _review_count(conn, name: str) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(r.id) FROM facility f "
            "LEFT JOIN review r ON r.facility_id = f.id WHERE f.name = ?",
            (name,),
        ).fetchone()
    except Exception:
        return 0
    return int(row[0]) if row and row[0] else 0


def register(conn, p: Plan) -> str:
    """施設をDBに登録し、分かっていれば place_id も覚える。施設名を返す。

    収集を発注する前に登録しておく。発注が失敗しても施設は残るので、
    あとから手でCSVを入れる道も残る。
    """
    from . import db  # noqa: PLC0415

    name = (p.facility or p.query).strip()
    if not name:
        return ""
    db.upsert_facility(conn, name, ftype="target")
    if p.place_id:
        db.set_place_id(conn, name, p.place_id)
    return name


def collect_url(p: Plan) -> str:
    """KAIZODE に渡す Google マップ URL。

    place_id が取れていればその1件を指す URL。取れていなければ名前で検索する
    URL に落ちる（同名の別施設を拾いうるので、UI 側で断りを出すこと）。
    """
    from . import kaizode  # noqa: PLC0415

    return p.maps_url or kaizode.maps_search_url(p.facility or p.query)
