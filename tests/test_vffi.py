"""VFFI（来場者適合指数）のテスト。

原典（facility-review-analysis / visitor-fit-analysis.txt）の式と、
**原典に書かれていない部分をどう扱うか**の両方を見張る。

この指数で一番危ないのは「それらしい数字が出てしまう」こと。
満足度が高い施設に「ミスマッチが大きい」と出したら、読み手は施設の問題だと
受け取る。実際には口コミが短くてコサインが伸びないだけ、ということが起きる。
"""
from __future__ import annotations

import math

import pytest

from src import vffi


# --------------------------------------------------------------------------- #
# 式そのもの
# --------------------------------------------------------------------------- #
def test_cosine_matches_the_definition():
    a, b = [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]
    assert vffi.cosine(a, b) == pytest.approx(0.5)
    assert vffi.cosine(a, a) == pytest.approx(1.0)


def test_zero_vector_is_unknown_not_zero():
    """要素が1つも立たない口コミは「似ていない」ではなく「測れない」。

    0.0 を返すと、日本語以外の口コミが全部「不適合」として集計されてしまう。
    """
    assert vffi.cosine([0.0, 0.0], [1.0, 1.0]) is None
    assert vffi.cosine([1.0, 1.0], [0.0, 0.0]) is None


def test_theta_matches_the_source():
    assert vffi.THETA == 0.70


def test_element_order_is_fixed():
    """次元の順序はベクトルの意味そのもの。変えると過去の値と比較できない。"""
    assert vffi.ELEMENTS[0] == "学習"
    assert len(vffi.ELEMENTS) == 12
    assert set(vffi.ELEMENTS) == set(vffi.KEYWORDS)


def test_experience_vector_counts_distinct_keywords():
    """同じ語の繰り返しでその要素が突出しないこと。"""
    one = vffi.experience_vector("勉強になった")
    many = vffi.experience_vector("勉強勉強勉強になった")
    assert one == many

    i = vffi.ELEMENTS.index("学習")
    assert vffi.experience_vector("勉強になり知識も増えた")[i] == 2


# --------------------------------------------------------------------------- #
# 短い口コミで数字が壊れる問題
# --------------------------------------------------------------------------- #
def test_single_element_reviews_cannot_reach_theta():
    """1要素しか立たない口コミは、12要素に広がる T と θ を超えられない。

    これを数えてしまうと、MatchingRate は適合ではなく口コミの長さを測る。
    """
    T = [1.0] * 12
    v = [0.0] * 12
    v[0] = 1.0
    assert vffi.cosine(T, v) == pytest.approx(1 / math.sqrt(12), abs=1e-6)
    assert vffi.cosine(T, v) < vffi.THETA


def test_sparse_corpus_suspends_the_verdict():
    """要素が立たない口コミばかりなら、判定を出さないこと。"""
    reviews = [(5.0, "勉強になりました")] * 40          # どれも1要素
    res = vffi.assess(reviews)
    assert res.mean_elements < vffi.MIN_ELEMENTS_FOR_FIT
    assert not res.match_reliable
    assert "判定保留" in res.band
    assert "適合率は判定に使えません" in vffi.vffi_note(res)


def test_rich_corpus_gets_a_real_verdict():
    rich = "子どもと一緒に体験でき、歴史も学べて発見が多く、写真も撮れて楽しい"
    res = vffi.assess([(5.0, rich)] * 40)
    assert res.computable
    assert res.match_reliable
    assert "判定保留" not in res.band


# --------------------------------------------------------------------------- #
# 算出不可の扱い
# --------------------------------------------------------------------------- #
def test_too_few_reviews_is_not_computed():
    res = vffi.assess([(5.0, "体験が楽しく学べた")] * 3)
    assert not res.computable
    assert str(vffi.MIN_REVIEWS) in res.reason


def test_non_japanese_is_flagged_not_scored():
    """英語・中国語ではキーワードが立たない。0点ではなく算出不可にする。"""
    res = vffi.assess([(5.0, "Great museum, very educational")] * 30)
    assert not res.computable
    assert res.language_mismatch
    assert res.score == 0.0


# --------------------------------------------------------------------------- #
# T（施設の狙い）
# --------------------------------------------------------------------------- #
def test_target_is_derived_from_high_rated_only():
    """T を全件から作ると T と V が同じ分布になり、Fit が構造的に高く出る。"""
    reviews = [(5.0, "体験が楽しい"), (5.0, "体験が楽しい"), (1.0, "混雑がひどい")]
    T = vffi.derive_target(reviews)
    i_ent = vffi.ELEMENTS.index("エンタメ性")
    i_exp = vffi.ELEMENTS.index("体験性")
    assert T[i_ent] > 0 and T[i_exp] > 0


def test_explicit_target_is_not_a_hypothesis():
    rich = "子どもと体験し歴史を学び発見があり写真も撮れた"
    auto = vffi.assess([(5.0, rich)] * 30)
    given = vffi.assess([(5.0, rich)] * 30, target=[1.0] * 12)
    assert auto.hypothesis_target is True
    assert given.hypothesis_target is False
    assert "仮置きした仮説" in vffi.vffi_note(auto)
    assert "仮置きした仮説" not in vffi.vffi_note(given)


# --------------------------------------------------------------------------- #
# 4象限と但し書き
# --------------------------------------------------------------------------- #
def test_quadrants_use_the_source_names():
    rich = "子どもと体験し歴史を学び発見があり写真も撮れた"
    res = vffi.assess([(5.0, rich)] * 20 + [(1.0, rich)] * 20)
    assert set(res.quadrants) == {
        "理想顧客", "施設サービス改善が必要", "想定外ヒット", "マーケティング改善が必要",
    }
    assert sum(q["count"] for q in res.quadrants.values()) == res.n_scored


def test_note_always_says_the_coefficients_are_ours():
    """α/β/γ は原典に無い。黙って使わないこと。"""
    res = vffi.assess([(5.0, "子どもと体験し学び発見があった")] * 30)
    note = vffi.vffi_note(res)
    assert "原典に定義が無く" in note
    assert "0.45" in note


def test_coefficients_can_be_overridden():
    rich = "子どもと体験し歴史を学び発見があり写真も撮れた"
    base = vffi.assess([(5.0, rich)] * 30)
    tweak = vffi.assess([(5.0, rich)] * 30, coeffs={"beta": 0.9})
    assert tweak.coeffs["beta"] == 0.9
    assert tweak.score != base.score
    assert "0.9" in vffi.vffi_note(tweak)


def test_score_stays_in_range():
    rich = "子どもと体験し歴史を学び発見があり写真も撮れた静かで専門的"
    for cf in ({"alpha": 5.0}, {"gamma": 5.0}, {}):
        res = vffi.assess([(5.0, rich)] * 30, coeffs=cf)
        assert 0.0 <= res.score <= 100.0


# 部分一致で誤爆しやすい語の実例。短さではなく**曖昧さ**を見る。
#   長さで切ると「昔」が落ちるが、実データ 717 件を見ると
#   昔ながら／昔懐かし／昔の車 と全てノスタルジー文脈で、誤爆しない。
#   逆に長くても「落ち着く」に「落ち」が当たるような事故は起きる
#   （rare.py で実際に踏んだ）。見るべきは語長ではない。
AMBIGUOUS = {
    "雑": "混雑",      "切れて": "売り切れて",  "におい": "において",
    "落ち": "落ち着く",  "迷": "迷路",            "期待": "期待以上",
}


def test_keywords_are_plain_tokens():
    """記号・空白を含む語を入れない。"""
    for elem, words in vffi.KEYWORDS.items():
        for w in words:
            assert w and w.strip() == w and " " not in w, f"{elem}: {w!r}"


def test_no_keyword_is_a_known_ambiguous_substring():
    """既知の誤爆語を使わないこと。長さではなく曖昧さで判定する。"""
    flat = {w for ws in vffi.KEYWORDS.values() for w in ws}
    bad = sorted(flat & set(AMBIGUOUS))
    assert not bad, (
        "部分一致で誤爆する語が含まれています: "
        + ", ".join(f"{w}（{AMBIGUOUS[w]} に当たる）" for w in bad)
    )


def test_single_char_keywords_are_deliberate():
    """1文字の語は許すが、意図したものだけに限る。

    実データ（企業ミュージアム 32,497件）で前後を数えて確かめたもの:
      昔  717件 … 昔ながら／昔懐かし／昔の車。すべてノスタルジー文脈
      孫  178件 … 孫を連れて／孫と一緒に。すべて家族文脈
    新しく1文字の語を足すときは、同じように現物を数えてからここに登録すること。
    """
    VERIFIED = {"昔", "孫"}
    singles = {w for ws in vffi.KEYWORDS.values() for w in ws if len(w) == 1}
    assert singles <= VERIFIED, (
        f"未検証の1文字キーワード: {sorted(singles - VERIFIED)}。"
        "実データで前後を数え、誤爆しないことを確かめてから VERIFIED に足すこと。"
    )
