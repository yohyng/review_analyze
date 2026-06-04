"""Generate a provisional sample report deck from demo data.

    python samples/make_report.py
    -> samples/sample_report.pptx

Seeds a temp DB with a realistic-ish set of hotel reviews + scores so the
charts / TF-IDF / N-gram / tables look populated, then builds the deck with
canned LLM insights (so it works without an API key).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, report, score_excel  # noqa: E402
from src.llm import InsightResult  # noqa: E402
from src.review_csv import ParsedReview  # noqa: E402

# --- demo reviews (対象: 風の海) ------------------------------------------- #
KAZE_REVIEWS = [
    (5, "スタッフの対応がとても丁寧で、チェックインから親切でした。部屋からの景色も最高で、食事のフグ料理も美味しかったです。"),
    (5, "全室個室の露天風呂が素晴らしく、景色を眺めながら入浴できました。スタッフの心遣いも行き届いていて大満足です。"),
    (4, "立地がよく海が一望できます。食事はローストビーフが絶品でした。ただ部屋の設備が少し古く感じました。"),
    (4, "スタッフの接客が丁寧で気持ちよく過ごせました。景色も料理も良かったですが、お風呂の脱衣所が少し狭いです。"),
    (3, "部屋からの眺めは良かったですが、食事の提供が少し遅かったです。接客は丁寧でした。"),
    (3, "景色は最高でしたが、設備が全体的に古く、空調の効きが悪かったのが残念でした。"),
    (5, "記念日に利用しました。スタッフが特別なサービスをしてくれて感動しました。料理も景色も文句なしです。"),
    (4, "海沿いの立地が最高で、夕日が綺麗でした。食事も美味しく、スタッフの対応も丁寧でした。"),
    (2, "設備の古さが気になりました。お湯の温度も安定せず、食事も提供が遅く期待外れでした。"),
    (4, "清潔感のある部屋で快適でした。スタッフの接客も丁寧で、景色も素晴らしかったです。"),
    (5, "露天風呂付きの部屋で景色を独り占めできました。料理長の心遣いも嬉しく、また来たいです。"),
    (3, "立地と景色は良いですが、設備のメンテナンスが必要だと思います。接客は良かったです。"),
]

# --- demo reviews (比較: 海の宿 潮) --------------------------------------- #
SHIO_REVIEWS = [
    (4, "食事のボリュームが多く満足しました。設備も新しく清潔でしたが、スタッフの対応がやや事務的でした。"),
    (4, "館内が新しくて綺麗です。料理も美味しかったですが、立地が駅から遠く不便でした。"),
    (3, "設備は充実していますが、接客に温かみがなく残念でした。食事は美味しかったです。"),
    (5, "新しい設備で快適に過ごせました。バイキングの種類も豊富で子供も喜んでいました。"),
    (3, "建物は綺麗ですが、立地がわかりにくく、スタッフの案内も不親切でした。"),
    (4, "コスパが良く、食事も設備も満足です。ただ景色は普通でした。"),
    (2, "スタッフの対応が冷たく、チェックインで長く待たされました。設備は良いだけに残念。"),
    (4, "清潔で新しい館内が好印象でした。料理の品数も多く満足です。"),
]


def _mk(reviews, prefix):
    out = []
    for i, (rating, text) in enumerate(reviews):
        out.append(
            ParsedReview(
                review_id=f"{prefix}_{i:03d}",
                rating=rating,
                text=text,
                review_date=f"2025-{(i % 12) + 1:02d}-15",
                reviewer_name=f"利用者{i}",
                local_guide=(i % 3 == 0),
                likes=i % 5,
                owner_response="",
                owner_response_date="",
                subscores=[],
            )
        )
    return out


CANNED_INSIGHTS = InsightResult(
    summary=(
        "「風の海」は海沿いの立地と全室個室露天風呂による景観体験、"
        "そしてスタッフの丁寧な接客が高く評価されている。一方で館内設備の"
        "老朽化と食事提供オペレーションに改善余地があり、比較施設に対する"
        "弱点となっている。"
    ),
    strengths=[
        "立地・景観：海を一望できるロケーションと露天風呂が口コミで最も高評価",
        "接客品質：スタッフの心遣い・記念日対応が顧客満足を牽引",
        "清潔感：客室の清潔さが安定して評価されている",
    ],
    weaknesses=[
        "設備の老朽化：空調・お湯の温度・脱衣所など設備面の不満が散見",
        "食事提供の遅延：料理の質は高いが提供スピードに不満",
        "比較施設に対し設備スコアが劣後",
    ],
    implications=[
        "強み（立地・接客）は維持コストが低く、訴求の軸に据えるべき",
        "弱み（設備・オペ）は投資・運用改善で解消可能な性質のもの",
    ],
    improvements=[
        "客室設備（空調・給湯）の計画的な更新・点検",
        "食事提供フローの見直し（厨房動線・配膳タイミングの最適化）",
        "高評価の景観・露天風呂を予約サイトの主要訴求として強化",
    ],
)


def main() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "demo.db"
    conn = db.get_conn(tmp)
    db.init_db(conn)

    # scores from the sample Excel (風の海 = target, 海の宿 潮 = comparison)
    here = Path(__file__).resolve().parent
    score_path = here / "sample_scores.xlsx"
    if not score_path.exists():
        from samples.make_sample import make_scores_xlsx  # type: ignore
        make_scores_xlsx()
    sdf = score_excel.read_table(score_path)
    g = score_excel.guess_columns(sdf)
    scores = score_excel.extract_scores_wide(sdf, g.name_col, g.numeric_cols)

    fid_t = db.upsert_facility(conn, "風の海", ftype="target")
    db.upsert_scores(conn, fid_t, scores["風の海"], scale=5)
    db.insert_reviews(conn, fid_t, _mk(KAZE_REVIEWS, "kaze"))

    fid_c = db.upsert_facility(conn, "海の宿 潮", ftype="comparison")
    db.upsert_scores(conn, fid_c, scores["海の宿 潮"], scale=5)
    db.insert_reviews(conn, fid_c, _mk(SHIO_REVIEWS, "shio"))

    out = here / "sample_report.pptx"
    return report.build_report(
        conn, "風の海", axis="comparison_avg",
        insights=CANNED_INSIGHTS, output_path=out,
    )


if __name__ == "__main__":
    path = main()
    print("wrote", path)
