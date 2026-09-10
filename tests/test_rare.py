"""n=1 の貴重意見抽出（資料「レアクチコミ抽出」§9）。

**珍しさではなく「構造的な問題の兆候か」で選ぶ。**

このテストの大半は、実データで踏んだ誤爆の再発防止。日本語の
キーワード照合は部分文字列で頻繁に事故を起こす。
"""
from __future__ import annotations

import pytest

from src import db, rare


# ── 前処理 ───────────────────────────────────────────────────────── #
def test_sentences_drops_noise_and_giant_blobs():
    out = rare.sentences("とても良かった。入口が分かりにくく受付にたどり着けない。あ。123")
    assert "入口が分かりにくく受付にたどり着けない" in out
    assert "あ" not in out and "123" not in out


def test_long_unpunctuated_text_is_split_on_commas():
    """句点の無い口コミが1文として丸ごと通らないこと。"""
    blob = "、".join([f"展示室{i}の照明が暗すぎて見えにくいと感じました" for i in range(6)])
    out = rare.sentences(blob)
    assert out, "全部落ちてしまっている"
    assert all(len(s) <= rare.MAX_CHARS for s in out)


def test_context_free_fragments_are_dropped():
    assert "分かりにくい" not in rare.sentences("分かりにくい。")


# ── 否定（実データで踏んだもの）───────────────────────────────────── #
@pytest.mark.parametrize("text", [
    "全くタバコ臭さがなく快適でした",
    "混雑もしないので落ち着いて見られる",
    "待ち時間もなくすぐに入れました",
])
def test_negated_complaints_are_not_counted(text):
    """「臭くない」を不満として拾わないこと。"""
    sev, _cat = rare.severity_of(text)
    assert sev == 0.0, text


@pytest.mark.parametrize("text,cat", [
    ("トイレが汚れていて臭いがひどい", "衛生"),
    ("エレベーターが故障していて使えなかった", "設備故障"),
    ("入口が分かりにくくたどり着けない", "導線"),
    ("階段に段差があって危ない", "安全"),
    ("待ち時間が長く館内は混雑していた", "混雑"),
])
def test_real_complaints_are_still_caught(text, cat):
    sev, got = rare.severity_of(text)
    assert sev > 0 and got == cat, (text, sev, got)


# ── 部分文字列の誤爆（実データで踏んだもの）───────────────────────── #
@pytest.mark.parametrize("text,why", [
    ("両面において興味深い展示だった", "「において」が「におい」に当たる"),
    ("館内が静かで落ち着いた雰囲気だった", "「落ち着く」が「落ち」に当たる"),
    ("グッズは午後には売り切れていました", "「売り切れ」が「切れて」に当たる"),
    ("買おうか本気で迷いました", "「迷う」が「迷」に当たる"),
])
def test_substring_false_positives(text, why):
    """短い語を単体で辞書に入れると日本語では誤爆する。"""
    sev, cat = rare.severity_of(text)
    assert sev == 0.0, f"{why} → {cat}"


# 実データで誤爆した語。長さではなく、他の語の一部になりうるかが問題。
#   におい ← 「において」 / 落ち ← 「落ち着く」
#   切れて ← 「売り切れて」 / 迷 ← 「迷う（判断に迷う）」
AMBIGUOUS = ("におい", "落ち", "切れて", "迷", "臭", "匂い", "止ま", "滑", "転")


def test_ambiguous_substrings_stay_out_of_the_dictionaries():
    """他の語の一部になる断片を辞書に入れないこと。

    「汚い」「故障」「混雑」のような2文字語は具体的で問題ない。
    長さではなく、部分文字列として他語に埋もれるかどうかで判断する。
    """
    for group, (words, _w) in rare.SEVERITY.items():
        bad = [w for w in words if w in AMBIGUOUS]
        assert bad == [], f"{group} に曖昧な語: {bad}"
    bad2 = [w for w in rare.PHENOMENA if w in AMBIGUOUS]
    assert bad2 == [], f"現象語に曖昧な語: {bad2}"


# ── 5軸 ─────────────────────────────────────────────────────────── #
def test_specificity_counts_elements():
    v, elems = rare.specificity_of("朝、2階のトイレが汚れていて臭いがひどかった")
    assert v > 0.6 and "場所" in elems and "時間" in elems and "現象" in elems

    v2, elems2 = rare.specificity_of("なんとなく不便だった")
    assert v2 == 0.0 and elems2 == ()


def test_actionability_penalises_vagueness():
    good = rare.actionability_of("入口の案内が小さく分かりにくい", ("場所", "現象"))
    bad = rare.actionability_of("なんとなく不便な気がする", ())
    assert good > 0.6 and bad == 0.0


def test_score_uses_the_documented_weights():
    r = rare.Rare("館", "x", novelty=1, specificity=1, severity=1,
                  actionability=1, credibility=1)
    assert r.score == pytest.approx(1.0)
    assert sum(rare.WEIGHTS.values()) == pytest.approx(1.0)
    assert rare.WEIGHTS["specificity"] == 0.25
    assert rare.WEIGHTS["severity"] == 0.25


# ── 除外ルール ───────────────────────────────────────────────────── #
def _extract(texts, **kw):
    return rare.extract(texts, "館", **kw)


def test_only_single_occurrences_are_candidates():
    """同じ文が2件以上あれば n=1 ではない。"""
    dup = "トイレが汚れていて臭いがひどかったです"
    got = _extract([dup, dup, "入口の案内が分かりにくく迷子になりました"])
    assert all(r.text != dup for r in got)


def test_praise_is_excluded():
    got = _extract(["展示が素晴らしく、記憶に残る快適な体験でした"])
    assert got == []


def test_conditional_statements_are_excluded():
    """仮定の話は起きた事実ではない。"""
    got = _extract(["予約が取れれば、絶対に体験する価値があります"])
    assert got == []


def test_personal_stories_are_excluded():
    got = _extract(["娘の誕生日に家族と来館し、受付が分かりにくかったです"])
    assert got == []


def test_cap_per_facility():
    texts = [f"展示室{i}の照明が暗すぎて解説が見えにくく感じました" for i in range(10)]
    assert len(_extract(texts, per_facility=3)) <= 3


def test_results_are_sorted_by_score():
    texts = ["入口の案内が分かりにくく受付にたどり着けない",
             "2階のトイレが汚れていて臭いがひどかった",
             "順路が分かりにくいと感じる場面がありました"]
    got = _extract(texts, per_facility=3)
    assert [r.score for r in got] == sorted((r.score for r in got), reverse=True)


def test_reason_explains_the_choice():
    got = _extract(["朝、2階のトイレが汚れていて臭いがひどかった"])
    assert got and "具体性" in got[0].reason and "衛生" in got[0].reason


def test_empty_input():
    assert _extract([]) == [] and _extract(["", "   "]) == []


def test_from_db(tmp_path):
    conn = db.get_conn(tmp_path / "r.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "館", ftype="target")
    for i, t in enumerate(["入口の案内が分かりにくく受付にたどり着けない",
                           "とても良かったです"]):
        conn.execute("INSERT INTO review(facility_id, review_id, rating, text,"
                     " review_date) VALUES (?,?,?,?,?)",
                     (fid, f"r{i}", 3, t, "2025-04-01"))
    conn.commit()
    got = rare.extract_from_db(conn, "館")
    assert len(got) == 1 and "分かりにく" in got[0].text
