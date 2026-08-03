"""分析パイプラインの動作確認用のダミーデータ。

管理画面の「🧪 ダミーデータ」から投入・削除・検証できる。
コマンドラインからは scripts/make_dummy_data.py。

施設ごとに「正解の強み・弱み」を先に決めてから、それに沿った口コミ文を生成する。
分析結果がその正解を再現できているかで、パイプラインが通っているかを判定できる。

生成物:
  デモ美術館            対象施設          80件
  競合A〜E              指定競合比較用    各50件
  市場施設01〜06        市場比較の母集団  各30件
                        （較正には8施設以上が必要なので背景として置く）

口コミ文は topic_score.DEFAULT_TOPICS のキーワードから組み立てるので、
トピック分類が意図どおり効く。乱数は固定シードで、何度実行しても同じ。
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from . import db, review_csv, topic_score

SEED = 20260803

# ── 施設ごとの「正解」プロファイル ─────────────────────────────────── #
# 値は 0.0（弱い）〜1.0（強い）。ここに書いた強み弱みが分析結果に出れば正常。
_BASE = 0.55
FACILITIES: list[dict] = [
    {
        # 件数は競合と揃える。口コミが多い施設ほどスコアがわずかに下がる偏りが
        # あるため（n=30→80 で総合 60.0→58.7）、件数差が比較に混ざらないようにする。
        "name": "デモ美術館", "role": "target", "n": 55,
        "category": "美術館・博物館",
        "strong": ["空間の感情的インパクト", "美的完成度", "提供内容の独自性",
                   "スタッフ対応", "体験満足度"],
        "weak": ["料金の適正さ", "立地・アクセス"],
    },
    {
        "name": "競合A ミュージアム", "role": "comparison", "n": 50,
        "category": "美術館・博物館",
        "strong": ["スタッフ対応", "情報提供", "空間の快適性"],
        "weak": ["提供内容の独自性", "空間の感情的インパクト"],
    },
    {
        "name": "競合B アートセンター", "role": "comparison", "n": 50,
        "category": "美術館・博物館",
        "strong": ["立地・アクセス", "料金の適正さ"],
        "weak": ["提供内容の品質", "空間の質感"],
    },
    {
        "name": "競合C 記念館", "role": "comparison", "n": 50,
        "category": "美術館・博物館",
        "strong": ["ブランドの歴史性", "ブランド信頼感"],
        "weak": ["提供内容の更新性", "美的完成度"],
    },
    {
        "name": "競合D 科学館", "role": "comparison", "n": 50,
        "category": "美術館・博物館",
        "strong": ["提供内容の多様性", "空間の機能性"],
        "weak": ["空間の質感", "スタッフ専門性"],
    },
    {
        "name": "競合E ギャラリー", "role": "comparison", "n": 50,
        "category": "美術館・博物館",
        "strong": ["スタッフ専門性", "提供内容の品質"],
        "weak": ["提供内容の多様性", "立地・アクセス"],
    },
]
# 市場の母集団（較正に8施設以上必要なので背景として置く）。
# 全観点をフラットにすると市場の分布が不自然に尖り、較正の基準が歪む。
# 施設ごとに違う強み弱みを持たせて、現実に近いばらつきを作る。
_MARKET_MIX = [
    (["情報提供", "サービスの種類"], ["ブランドの歴史性", "空間の感情的インパクト"]),
    (["空間の質感", "ブランド信頼感"], ["提供内容の多様性", "料金割引・決済"]),
    (["提供内容の更新性", "比較優位性"], ["スタッフ専門性", "空間の機能性"]),
    (["空間の快適性", "料金割引・決済"], ["提供内容の品質", "情報提供"]),
    (["提供内容の品質", "立地・アクセス"], ["空間の快適性", "比較優位性"]),
    (["スタッフ専門性", "美的完成度"], ["サービスの種類", "提供内容の更新性"]),
]
for _i, (_s, _w) in enumerate(_MARKET_MIX, 1):
    FACILITIES.append({
        "name": f"市場施設{_i:02d}", "role": "comparison", "n": 30,
        "category": "美術館・博物館", "strong": _s, "weak": _w,
    })

# 対象施設に起こす「出来事」。SLIDE 4 の変化点検出が拾えるかの確認用。
EVENT_MONTH_OFFSET = 14          # 期間の先頭から数えた月
EVENT_PENALTY = 0.45             # その月だけ評価を下げる強さ
EVENT_TOPICS = ["空間の快適性", "料金の適正さ"]

MONTHS = 30                      # 生成する期間（か月）

# ── トピックごとの文型（キーワードは DEFAULT_TOPICS 由来）───────────── #
POS_T = {
    "提供内容の品質": ["展示のクオリティが高く、完成度に驚きました",
                "作品の品質が上質で、見応えがありました"],
    "提供内容の多様性": ["展示の種類が豊富で、選択肢の幅広さが良かったです",
                 "ラインナップが多彩で、いろいろ楽しめました"],
    "提供内容の独自性": ["ここだけの独自の展示で、他にないユニークさがあります",
                 "オリジナルのこだわりが感じられ、個性が際立っていました"],
    "提供内容の更新性": ["季節ごとの新しい企画があり、リニューアルも頻繁です",
                 "最新の展示に入れ替わっていて、旬の内容が楽しめました"],
    "スタッフ対応": ["スタッフの接客がとても丁寧で、笑顔の対応が気持ちよかったです",
              "従業員の方が親切で、気配りのあるホスピタリティでした"],
    "スタッフ専門性": ["解説が専門的で知識が深く、説明がとても的確でした",
               "詳しいスタッフの技術と経験を感じる案内でした"],
    "サービスの種類": ["音声ガイドの貸出など、サービスの特典が充実しています",
               "オプションのプランが無料で使えて助かりました"],
    "情報提供": ["館内の案内表示が分かりやすく、説明も充実していました",
             "看板や掲示の情報が整理されていて迷いません"],
    "空間の機能性": ["動線が使いやすく、レイアウトも広さも機能的でした",
              "設備の配置が良く、使い勝手が考えられています"],
    "空間の質感": ["内装の素材に高級感があり、しつらえの質感が見事です",
             "木や石の重厚な調度で、上質な空間でした"],
    "空間の快適性": ["静かで落ち着く空間で、ゆったり快適に過ごせました",
              "居心地がよくリラックスできる、過ごしやすい館内です"],
    "空間の感情的インパクト": ["圧巻の世界観で没入でき、非日常の感動がありました",
                   "印象的な演出に驚きがあり、記憶に残る特別感でした"],
    "美的完成度": ["デザインが洗練されていて美しく、映える眺めでした",
             "おしゃれで綺麗な空間、美的な完成度が高いです"],
    "料金の適正さ": ["この内容でこの価格は妥当で、コスパが良いと感じました",
              "料金が安く、値段に見合うリーズナブルさでした"],
    "料金割引・決済": ["キャッシュレス決済に対応していて会計がスムーズでした",
               "割引クーポンが使え、支払いもカードで簡単でした"],
    "立地・アクセス": ["駅から近く立地が便利で、アクセスが良好です",
              "駐車場も広く、徒歩でのロケーションも最寄りから近いです"],
    "ブランド信頼感": ["さすがの実績で安心感があり、期待通りの信頼できる内容でした",
               "定評どおりで間違いない、信用できる館です"],
    "ブランドの歴史性": ["創業からの歴史と伝統が感じられ、由緒ある格式でした",
                "長年受け継がれた伝統的な佇まいが昔のままです"],
    "比較優位性": ["他と比べて一番良く、群を抜くナンバーワンだと思います",
             "他館より優れていて、この分野では随一でした"],
    "体験満足度": ["とても満足で楽しい時間、素晴らしい体験に感動しました",
             "大満足の充実した内容で、また来たいと思える良かった一日でした"],
    "推奨意向": ["人にぜひおすすめしたい、紹介したくなる場所です",
            "友人にも勧めたい、推薦できる内容でした"],
    "再訪意向": ["また来たいですし、リピートして通いたいです",
            "次回も再訪したい、何度も行きたくなります"],
}
NEG_T = {
    "提供内容の品質": ["展示の完成度が低く、クオリティが期待外れでした",
                "作品の品質が悪い印象で、出来に残念さが残ります"],
    "提供内容の多様性": ["展示の種類が少なく、選択肢の幅広さに欠けます",
                 "品揃えが乏しく、バリエーションが物足りません"],
    "提供内容の独自性": ["どこにでもある内容で、独自の個性が感じられません",
                 "オリジナルのこだわりが薄く、ユニークさに欠けます"],
    "提供内容の更新性": ["展示が長く変わらず、新しい企画がありません",
                 "リニューアルされておらず、最新の内容とは言えません"],
    "スタッフ対応": ["スタッフの接客が不親切で、対応の態度が残念でした",
              "店員の愛想が悪く、丁寧さに欠ける対応でした"],
    "スタッフ専門性": ["説明が曖昧で知識が浅く、専門性を感じませんでした",
               "解説が的確でなく、詳しい話は聞けませんでした"],
    "サービスの種類": ["貸出のサービスが少なく、オプションもありません",
               "特典やプランが乏しく、サービス内容が不足しています"],
    "情報提供": ["案内表示が分かりにくく、説明の掲示も不足しています",
             "看板が少なく、情報が整理されていないので迷いました"],
    "空間の機能性": ["動線が悪く使いにくい配置で、広さも足りません",
              "レイアウトの使い勝手が悪く、設備も古いです"],
    "空間の質感": ["内装の素材が安っぽく、しつらえの質感が残念でした",
             "調度が古く、高級感のない内装でした"],
    "空間の快適性": ["混雑していて騒がしく、落ち着かない空間でした",
              "静かに過ごせず、居心地が悪く快適とは言えません"],
    "空間の感情的インパクト": ["演出が平板で驚きがなく、印象に残りませんでした",
                   "世界観が弱く、感動や特別感は薄かったです"],
    "美的完成度": ["デザインが古く、美しいとは言えない見た目でした",
             "綺麗さに欠け、洗練された印象がありません"],
    "料金の適正さ": ["この内容で この価格は割高で、コスパが悪いです",
              "料金が高く、値段に見合わない妥当性のなさでした"],
    "料金割引・決済": ["現金のみで決済が不便、割引もありませんでした",
               "カードが使えず会計に時間がかかりました"],
    "立地・アクセス": ["駅から遠く立地が不便で、アクセスに苦労しました",
              "駐車場が狭く、徒歩での最寄りからの場所が分かりにくいです"],
    "ブランド信頼感": ["期待通りとは言えず、実績のわりに安心感がありません",
               "定評ほどではなく、信頼できる内容とは思えませんでした"],
    "ブランドの歴史性": ["歴史や伝統の重みが伝わらず、由緒が感じられません",
                "老舗の格式を期待しましたが、昔からの趣は薄いです"],
    "比較優位性": ["他と比べて見劣りし、優れた点が見つかりません",
             "他館のほうが良く、一番とは言い難いです"],
    "体験満足度": ["満足できず残念な体験で、期待外れでした",
             "楽しいとは言えず、がっかりする内容でした"],
    "推奨意向": ["人におすすめはしにくい内容でした",
            "友人に勧めるほどではありません"],
    "再訪意向": ["また来たいとは思えませんでした",
            "リピートして通うことはないと思います"],
}
ALL_TOPICS = [t.name for t in topic_score.DEFAULT_TOPICS]


def _profile(spec: dict) -> dict[str, float]:
    """施設の「正解」スコア（観点 → 0.0〜1.0）。

    弱みを極端（0.2以下）にすると、その否定的な文がトピック確率を通じて
    無関係な観点にまで染み出し、施設全体のスコアが不自然に沈む。
    現実の口コミもそこまで一方向には偏らないので、控えめな値にしてある。
    """
    p = {t: _BASE for t in ALL_TOPICS}
    for t in spec["strong"]:
        p[t] = 0.85
    for t in spec["weak"]:
        p[t] = 0.30
    return p


def _make_review(rng: random.Random, prof: dict[str, float],
                 penalty: float = 0.0) -> tuple[int, str]:
    """1件の口コミ本文と星評価を作る。"""
    topics = rng.sample(ALL_TOPICS, rng.choice([2, 2, 3, 3, 4]))
    # 体験満足度は多くの口コミで言及される
    if "体験満足度" not in topics and rng.random() < 0.5:
        topics.append("体験満足度")

    parts, scores = [], []
    for t in topics:
        p = max(0.0, min(1.0, prof[t] - penalty + rng.gauss(0, 0.13)))
        scores.append(p)
        pool = POS_T[t] if p >= 0.5 else NEG_T[t]
        parts.append(rng.choice(pool))
    rng.shuffle(parts)

    mean = sum(scores) / len(scores)
    # 0.0〜1.0 を 1〜5 の星へ。境界にゆらぎを持たせる
    star = 1 + int(min(4.999, max(0.0, mean * 5 + rng.gauss(0, 0.35))))
    return star, "。".join(parts) + "。"


def facility_names() -> list[str]:
    """このモジュールが作る施設名（削除の対象）。"""
    return [f["name"] for f in FACILITIES]


def target_name() -> str:
    return FACILITIES[0]["name"]


def peer_names() -> list[str]:
    return [f["name"] for f in FACILITIES[1:6]]


def remove(conn) -> int:
    """投入したダミー施設だけを消す。他のデータには触れない。"""
    n = 0
    for name in facility_names():
        row = conn.execute("SELECT id FROM facility WHERE name = ?", (name,)).fetchone()
        if row:
            db.delete_facility(conn, row["id"])
            n += 1
    return n


def build(conn, log=None) -> dict:
    """ダミー施設と口コミを投入する。既にあれば作り直す。"""
    rng = random.Random(SEED)
    remove(conn)

    start = date.today().replace(day=1) - timedelta(days=30 * MONTHS)
    truth = {}

    for spec in FACILITIES:
        prof = _profile(spec)
        truth[spec["name"]] = {"strong": spec["strong"], "weak": spec["weak"]}
        fid = db.upsert_facility(
            conn, spec["name"], ftype=spec["role"], category=spec["category"],
        )
        reviews = []
        for i in range(spec["n"]):
            m = rng.randrange(MONTHS)
            # 対象施設だけ、ある月に評価が落ち込む出来事を仕込む
            pen = 0.0
            if spec["role"] == "target" and m == EVENT_MONTH_OFFSET:
                pen = EVENT_PENALTY
            star, text = _make_review(rng, prof, penalty=pen)
            d = start + timedelta(days=30 * m + rng.randrange(28))
            reviews.append(review_csv.ParsedReview(
                review_id=f"{spec['name']}-{i:04d}", rating=star, text=text,
                review_date=d.isoformat() + "T00:00:00Z",
                reviewer_name=f"利用者{i:03d}", local_guide=bool(i % 5 == 0),
                likes=rng.randrange(0, 12), owner_response="",
                owner_response_date="", subscores=[],
            ))
        ins, _skip = db.insert_reviews(conn, fid, reviews)
        if log:
            log(f"{spec['name']}: {ins}件")

    conn.commit()
    return truth


def truth() -> dict:
    """仕込んだ強み・弱み（答え合わせ用）。"""
    return {f["name"]: {"strong": f["strong"], "weak": f["weak"]}
            for f in FACILITIES}


def event_month() -> str:
    """仕込んだ出来事の月（'YYYY-MM'）。"""
    start = date.today().replace(day=1) - timedelta(days=30 * MONTHS)
    ev = start + timedelta(days=30 * EVENT_MONTH_OFFSET)
    return f"{ev.year}-{ev.month:02d}"


def verify(conn) -> dict:
    """分析を回して、仕込んだ特徴が再現されるかを確かめる。

    戻り値はそのまま画面にもCLIにも出せる dict。
    """
    from . import preview

    names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
    matrix = {n: topic_score.analyze_facility(conn, n) for n in names}
    tgt = target_name()
    b = preview.build_bundle(conn, tgt, matrix, None, None,
                             peers_override=peer_names())

    want = truth()[tgt]
    got_s = [t for t, _m, _v, _d in b["strengths"][:5]]
    got_w = [t for t, _m, _v, _d in b["weaknesses"][:5]]
    hit_s = [t for t in want["strong"] if t in got_s]
    hit_w = [t for t in want["weak"] if t in got_w]

    ev = event_month()
    cps = b["change_points"]
    hit_ev = [c for c in cps if c.ym == ev and c.direction == "down"]

    ok = len(hit_s) >= 2 and len(hit_w) >= 2 and bool(hit_ev)
    return {
        "target": tgt,
        "calibrated": b["score_calibrated"],
        "rank": b["rank"], "total": b["total_fac"],
        "overall5": round((b["overall_sentiment"] or 0) / 20, 2),
        "want_strong": want["strong"], "got_strong": got_s, "hit_strong": hit_s,
        "want_weak": want["weak"], "got_weak": got_w, "hit_weak": hit_w,
        "event_month": ev,
        "change_points": [(c.ym, c.delta_pt) for c in cps],
        "event_detected": bool(hit_ev),
        "ok": ok,
    }
