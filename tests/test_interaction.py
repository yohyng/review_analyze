"""分析スライドのインタラクション層（L0/L1/L2）。

設計の原則:
  1. インタラクションは「追加情報」に限る。そこにしか無い情報を置かない
     （PPTX・スクショ・印刷では全部消えるため）。
  2. 今の静的な見た目を壊さない。重ねるだけ。
  3. ホバーだけに頼らない（タブレットには hover が無い）。

Streamlit の st.markdown は <script> を落とすので、全部 CSS だけで組む。
何が通るかは実ブラウザで実測済み（:has() / :focus-within / :checked すべて可）。
"""
from __future__ import annotations

import re

import pytest

from src import db, preview, slides, topic_score

TOPICS = [t.name for t in topic_score.DEFAULT_TOPICS]


def _markup(html: str) -> str:
    """<style> を落として、実際の要素だけを見る。

    TOOLTIP_CSS は各スライドに埋め込まれるので、`"vb-unmeasured" in html` の
    ような素朴な検査は CSS の側に当たって必ず真になる（一度ひっかかった）。
    """
    return re.sub(r"<style>.*?</style>", "", html, flags=re.S)



def _result(sentiment: float, salience_of=None):
    w = 1.0 / len(TOPICS)
    return topic_score.TopicScoreResult(
        topics=[
            topic_score.TopicScore(
                name=t, weight=w, avg_score=sentiment * w,
                total_score=sentiment * w,
                salience=(salience_of(t) if salience_of else w),
                sentiment=sentiment)
            for t in TOPICS
        ],
        overall_score=sentiment, n_reviews=40, n_sentences=1000, empty=False,
    )


def _bundle(tmp_path, salience_of=None, peers=True):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"peer{i}" for i in range(5)]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison", category="美術館")
    matrix = {nm: _result(0.5 + 0.03 * i, salience_of if nm == "target" else None)
              for i, nm in enumerate(names)}
    return preview.build_bundle(conn, "target", matrix, None, None,
                                peers_override=names[1:] if peers else None)


# ── L0: ホバー以外の手段でも届くこと ──────────────────────────────── #
def test_tooltips_are_reachable_without_a_mouse(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide2_market_position(b)
    # 吹き出しを持つ要素は必ずフォーカスできること
    tips = re.findall(r'<span ([^>]*class="vb-tip(?: [^"]*)?"[^>]*)>', html)
    assert tips, "吹き出しが1つも無い"
    for attrs in tips:
        assert 'tabindex="0"' in attrs, f"フォーカスできない: {attrs[:120]}"
    css = slides.TOOLTIP_CSS
    assert ".vb-tip:focus>.vb-tipbody" in css.replace(" ", "")
    assert ".vb-tip:focus-within>.vb-tipbody" in css.replace(" ", "")


def test_no_javascript_is_relied_on():
    """Streamlit は <script> を落とす（実測）。JS に依存しないこと。"""
    css = slides.TOOLTIP_CSS
    assert "<script" not in css
    assert "onclick" not in css and "onmouseover" not in css


# ── L1: 根拠カード ─────────────────────────────────────────────── #
def test_tooltip_carries_the_evidence_not_just_the_definition(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide2_market_position(b)
    assert "スコア" in html, "スコアの行が無い"
    assert "言及" in html, "言及量の行が無い"
    assert b["baseline_label"] in html, "何と比べたのかが出ていない"
    # 「34文 / 1,000文（4.5%）」の形
    assert re.search(r"\d[\d,]*文 / [\d,]+文", html), "言及量が件数で出ていない"


def test_evidence_needs_no_bundle_to_stay_safe():
    """bundle を渡さない呼び出しでも従来どおり定義だけで動くこと。"""
    name = TOPICS[0]
    plain = slides.topic_tooltip(name)
    assert name in plain and "vb-tip" in plain
    assert "スコア" not in plain


# ── L1: 言及されていない観点を強み/弱みとして読ませない ───────────── #
def test_unmeasured_topics_are_marked_statically_and_in_the_card(tmp_path):
    """言及ゼロの観点は、ホバーしなくても薄く見えること。

    較正は「一度も語られていない観点」にも施設全体の平均感情を配るので、
    未測定の軸が強みとして描かれてしまう。ホバーでしか分からない注意書きは
    スクショにも PPTX にも残らないので、静的な指示子も必ず付ける（原則1）。
    """
    dead = TOPICS[3]
    live = 1.0 / (len(TOPICS) - 1)

    b = _bundle(tmp_path, salience_of=lambda t: 0.0 if t == dead else live)
    assert b["topic_salience"][dead] == 0.0
    assert b["salience_floor"] > 0

    assert slides._is_unmeasured(dead, b) is True
    assert slides._is_unmeasured(TOPICS[0], b) is False

    marked = slides.topic_tooltip(dead, b=b)
    assert "vb-unmeasured" in marked, "静的な指示子が付いていない"
    assert "読まないでください" in marked, "カードに注意書きが無い"

    ok = slides.topic_tooltip(TOPICS[0], b=b)
    assert "vb-unmeasured" not in ok

    assert ".vb-unmeasured" in slides.TOOLTIP_CSS


# ── L2: 相互ハイライト ──────────────────────────────────────────── #
def test_same_topic_elements_are_linked_for_cross_highlighting(tmp_path):
    b = _bundle(tmp_path)
    ids = set(re.findall(r'data-t="(\d+)"', _markup(slides.slide2_market_detail(b))))
    assert len(ids) >= 5, f"観点の目印が少なすぎる: {ids}"

    # 目印は DEFAULT_TOPICS の添字であること
    for i in ids:
        assert 0 <= int(i) < len(TOPICS)

    css = slides.TOOLTIP_CSS
    for i in sorted(ids)[:3]:
        assert f'.vb-cv:has([data-t="{i}"]:hover) [data-t="{i}"]' in css


def test_highlighting_is_scoped_to_one_slide():
    """起点が .vb-cv（スライド1枚）であること。隣のスライドに波及させない。"""
    css = slides.TOOLTIP_CSS
    rules = [r for r in css.split("}") if ":has(" in r]
    assert rules
    for r in rules:
        assert ".vb-cv:has(" in r, f"スライドに閉じていない: {r[:100]}"


def test_canvas_carries_the_scope_class():
    html = slides.canvas("<i></i>", "<i></i>", "<i></i>")
    assert 'class="vb-cv"' in html


# ── 原則2: 静的な出力を壊していないこと ───────────────────────────── #
@pytest.mark.parametrize("fn", slides.report_slides(),
                         ids=[f.__name__ for f in slides.report_slides()])
def test_every_slide_still_renders(tmp_path, fn):
    b = _bundle(tmp_path)
    html = fn(b)
    assert html.startswith("<div") and html.rstrip().endswith("</div>")
    assert "None" not in html.replace("None的", "")


def test_uniform_salience_does_not_grey_out_half_the_slide(tmp_path):
    """「平均より下」を静的な指示子の条件にしないこと。

    salience は平均トピック確率で Σ=1 なので、平均はちょうど 1/観点数。
    それを閾値にすると定義上ほぼ半数が該当し、スライドの半分が灰色になる。
    静的に薄くするのは「言及が1文も無い」ときだけ。
    """
    b = _bundle(tmp_path)                      # 全観点が同じ salience（=平均）
    assert all(abs(v - b["salience_floor"]) < 1e-6
               for v in b["topic_salience"].values())

    greyed = [t for t in TOPICS if slides._is_unmeasured(t, b)]
    assert greyed == [], f"平均ちょうどの観点まで薄くしている: {greyed[:5]}"

    assert "vb-unmeasured" not in _markup(slides.slide2_market_detail(b))

    # ただし「他と比べられる水準ではない」ことは吹き出しでは伝える
    assert slides._is_thin(TOPICS[0], b) is True
    assert "参考値として扱ってください" in slides.topic_tooltip(TOPICS[0], b=b)


def test_a_clearly_mentioned_topic_gets_no_caution(tmp_path):
    lots = {TOPICS[0]: 40.0}
    rest = (100.0 - 40.0) / (len(TOPICS) - 1)
    b = _bundle(tmp_path, salience_of=lambda t: (lots.get(t, rest)) / 100)

    assert slides._is_thin(TOPICS[0], b) is False
    card = slides.topic_tooltip(TOPICS[0], b=b)
    assert "参考値として扱って" not in card
    assert "読まないでください" not in card
    assert "言及" in card


def test_cross_highlight_pairs_exist_where_the_same_axis_is_drawn_twice(tmp_path):
    """同じ観点が1枚の中で2箇所に出るスライドでは、必ず結ばれていること。

    - 競合比較: 傾いたX軸（-62°）↔ ヒートマップの指標名
    - 空間体験: レーダーの軸ラベル ↔ 評価軸テーブルの行
    傾いたX軸は回転を子が継承するので吹き出しは置けないが、
    data-t だけは置ける（v0.49 で説明を諦めた箇所を拾い直している）。
    """
    from collections import Counter
    b = _bundle(tmp_path)
    for fn, want in ((slides.slide3_competitor_compare, 5),
                     (slides.slide5_space_experience, 5)):
        ids = Counter(re.findall(r'data-t="(\d+)"', _markup(fn(b))))
        paired = [k for k, v in ids.items() if v > 1]
        assert len(paired) >= want, (
            f"{fn.__name__}: 連動する観点が {len(paired)} 個しかない")
