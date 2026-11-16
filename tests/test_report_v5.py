"""PPT v5（18枚固定）のテスト。

原典（ppt-spec-v5.md）が強い言い方で禁じていることを、そのまま見張る。

  - 18枚固定・順番固定・タイトル固定。**省略・統合・順番変更は禁止**
  - **データが不足する場合も該当スライドを作成**し、その旨を明記する
  - **表の最小フォントは12pt。収まらなくても縮小しない**

とくに1つめは「データが無いと枚数が減る」という形で簡単に壊れる。
既存の report.py がまさにその作りなので、ここで固定しておく。
"""
from __future__ import annotations

from pptx import Presentation
from pptx.util import Pt

from src import rare as rare_mod
from src import report_v5
from src import vffi as vffi_mod

RICH = "子どもと一緒に体験でき、歴史も学べて発見が多く、写真も撮れて楽しい"


def _build(tmp_path, ctx, name="d.pptx"):
    out = report_v5.build_report_v5(ctx, tmp_path / name)
    return Presentation(str(out))


def _texts(slide) -> str:
    out = []
    for sh in slide.shapes:
        if sh.has_text_frame:
            out.append(sh.text_frame.text)
        if getattr(sh, "has_table", False) and sh.has_table:
            for r in sh.table.rows:
                out.extend(c.text for c in r.cells)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 18枚固定
# --------------------------------------------------------------------------- #
def test_empty_context_still_makes_18_slides(tmp_path):
    """データが1つも無くても18枚。**ここが壊れると仕様違反になる。**"""
    prs = _build(tmp_path, report_v5.Ctx(target="テスト館"))
    assert len(prs.slides) == 18


def test_full_context_also_makes_18_slides(tmp_path):
    reviews = [(5.0, RICH)] * 40
    ctx = report_v5.Ctx(target="テスト館", reviews=reviews,
                        vffi=vffi_mod.assess(reviews))
    assert len(_build(tmp_path, ctx).slides) == 18


def test_titles_are_fixed_and_in_order(tmp_path):
    prs = _build(tmp_path, report_v5.Ctx(target="テスト館"))
    for i, (slide, want) in enumerate(zip(prs.slides, report_v5.SPEC_TITLES), 1):
        if i == 1:
            continue                       # 表紙はタイトルバーを持たない
        assert want in _texts(slide), f"{i}枚目に「{want}」が無い"


def test_builder_count_matches_the_spec():
    assert len(report_v5.BUILDERS) == len(report_v5.SPEC_TITLES) == 18


# --------------------------------------------------------------------------- #
# データ不足でも面を作る
# --------------------------------------------------------------------------- #
def test_missing_data_says_so_instead_of_being_blank(tmp_path):
    """白紙にしない。何が無いのかを書く。"""
    prs = _build(tmp_path, report_v5.Ctx(target="テスト館"))
    market = _texts(list(prs.slides)[2])    # 3枚目 市場ポジション
    assert "データ不足" in market
    assert "トピックスコア" in market       # 理由が書いてある


def test_vffi_slide_keeps_the_caveat(tmp_path):
    """係数が原典に無いことを、スライド上でも断る。"""
    reviews = [(5.0, RICH)] * 40
    ctx = report_v5.Ctx(target="テスト館", reviews=reviews,
                        vffi=vffi_mod.assess(reviews))
    t = _texts(list(_build(tmp_path, ctx).slides)[10])   # 11枚目 VFFI
    assert "原典に定義が無く" in t
    assert "仮置きした仮説" in t


# --------------------------------------------------------------------------- #
# 13枚目 — 測っていないものを数字にしない
# --------------------------------------------------------------------------- #
def test_physio_slide_exists_but_has_no_numbers(tmp_path):
    """β/α と PNN50 は生体計測の指標。クチコミからは出せない。

    枚数を詰めて17枚にもしない（原典の順番固定に従う）。
    """
    prs = _build(tmp_path, report_v5.Ctx(target="テスト館"))
    slide = list(prs.slides)[12]            # 13枚目
    t = _texts(slide)
    assert "感情・生理指標推定" in t
    assert "測定していません" in t
    assert "β/α" in t and "PNN50" in t
    # 代理値の表を置かない
    assert not any(getattr(sh, "has_table", False) and sh.has_table
                   for sh in slide.shapes)


def test_physio_slide_is_at_position_13(tmp_path):
    """詰めない。13番目のままにする。"""
    assert report_v5.SPEC_TITLES[12] == "感情・生理指標推定"
    assert report_v5.BUILDERS[12] is report_v5._s13_physio


# --------------------------------------------------------------------------- #
# 12pt を下回らない
# --------------------------------------------------------------------------- #
def _table_sizes(prs):
    out = []
    for sl in prs.slides:
        for sh in sl.shapes:
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    for c in r.cells:
                        for p in c.text_frame.paragraphs:
                            out.extend(run.font.size for run in p.runs
                                       if run.font.size)
    return out


def test_no_table_font_below_12pt(tmp_path):
    reviews = [(5.0, RICH)] * 40
    ctx = report_v5.Ctx(target="テスト館", reviews=reviews,
                        vffi=vffi_mod.assess(reviews))
    sizes = _table_sizes(_build(tmp_path, ctx))
    assert sizes, "表が1つも無い"
    too_small = [s.pt for s in sizes if s < Pt(report_v5.MIN_TABLE_PT)]
    assert not too_small, f"12pt未満のフォント: {too_small}"


def test_long_tables_drop_rows_instead_of_shrinking(tmp_path):
    """収まらないときは行を削る。縮小はしない。そして削ったことを残す。"""
    ctx = report_v5.Ctx(target="テスト館")
    rows = [("x", "y")] * 40
    kept = report_v5._fit_rows(rows, ctx, "テスト表")
    assert len(kept) == report_v5.MAX_TABLE_ROWS
    assert ctx.notes and "40 行中" in ctx.notes[0]


def test_short_tables_are_not_trimmed():
    ctx = report_v5.Ctx(target="テスト館")
    rows = [("x", "y")] * 3
    assert report_v5._fit_rows(rows, ctx, "テスト表") == rows
    assert not ctx.notes


# --------------------------------------------------------------------------- #
# 個別の面
# --------------------------------------------------------------------------- #
def test_rare_slide_respects_the_per_facility_cap(tmp_path):
    class _R:
        def __init__(self, i):
            self.text, self.score, self.category = f"レア口コミ{i}", 0.9, "設備"
    ctx = report_v5.Ctx(target="テスト館", rares=[_R(i) for i in range(10)])
    slide = list(_build(tmp_path, ctx).slides)[17]      # 18枚目
    table = next(sh.table for sh in slide.shapes
                 if getattr(sh, "has_table", False) and sh.has_table)
    assert len(table.rows) - 1 == rare_mod.MAX_PER_FACILITY


def test_kpi_slide_lists_all_seven_layers(tmp_path):
    from src import kpi
    t = _texts(list(_build(tmp_path, report_v5.Ctx(target="テ")).slides)[13])
    for layer in kpi.LAYERS:
        assert layer in t, f"{layer} が KPI 面に無い"


def test_quadrants_use_the_source_names(tmp_path):
    reviews = [(5.0, RICH)] * 20 + [(1.0, RICH)] * 20
    ctx = report_v5.Ctx(target="テ", reviews=reviews, vffi=vffi_mod.assess(reviews))
    t = _texts(list(_build(tmp_path, ctx).slides)[11])   # 12枚目
    for name in ("理想顧客", "施設サービス改善が必要",
                 "想定外ヒット", "マーケティング改善が必要"):
        assert name in t


# --------------------------------------------------------------------------- #
# 画面への配線
#   テストが通っても UI が壊れていた事例があるので、経路そのものを固定する。
# --------------------------------------------------------------------------- #
def _ui_src() -> str:
    from pathlib import Path
    return Path("src/ui/analysis_mode.py").read_text(encoding="utf-8")


def test_worker_builds_the_18_slide_deck():
    """分析ワーカーが既存レポートと並べて18枚版も作ること。"""
    src = _ui_src()
    assert "report_v5.build_report_v5(_ctx5, _tmp_v5)" in src
    assert 'ss_out["an_result_path_v5"]' in src


def test_v5_build_does_not_block_the_existing_report():
    """18枚版が作れなくても既存レポートは出すこと。"""
    src = _ui_src()
    block = src[src.index("_tmp_v5 = None"):src.index('ss_out["an_preview"]')]
    assert "except Exception:" in block
    assert "_tmp_v5 = None      # 18枚版が作れなくても既存レポートは出す" in block


def test_v5_reuses_computed_data_without_new_llm_calls():
    """ここまでで計算済みのものを詰め直すだけ。LLM を呼び直さない。"""
    src = _ui_src()
    block = src[src.index("_tmp_v5 = None"):src.index('ss_out["an_preview"]')]
    for banned in ("llm.generate_insights", "llm.build_prompt",
                   "llm.pick_voice_quadrants", "llm.build_discussion_points"):
        assert banned not in block, f"{banned} を呼んでいる"


def test_download_button_exists_for_v5():
    src = _ui_src()
    assert 'key="an_dl_v5"' in src
    assert "18枚固定版" in src
    # 既存のボタンを消していないこと
    assert 'key="an_dl"' in src
    assert "⬇ PowerPointでダウンロード" in src


def test_session_default_is_registered():
    from pathlib import Path
    assert '"an_result_path_v5": None,' in Path("app.py").read_text(encoding="utf-8")
