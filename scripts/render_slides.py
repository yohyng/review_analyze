"""スライドを headless Chromium で PNG に書き出す（目視確認用）。

デザインの正典（design_handoff_voicebaum）と見比べるために使う。
ダミーデータの「デモ美術館」＋競合5施設で1枚ずつ描く。

    python3 scripts/render_slides.py [出力先ディレクトリ]

Playwright が入っていない環境ではスキップせずエラーにする（黙って
「確認した」ことにならないように）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, dummy_data, preview, report_theme, slides, topic_score  # noqa: E402

SLIDES = [
    ("00_disclaimer", slides.slide0_disclaimer),
    ("01_facility",   slides.slide1_facility_info),
    ("02_market",     slides.slide2_market_position),
    ("03_market_dt",  slides.slide2_market_detail),
    ("04_compare",    slides.slide3_competitor_compare),
    ("05_compare_dt", slides.slide3_competitor_detail),
    ("06_timeline",   slides.slide4_timeline),
    ("07_space",      slides.slide5_space_experience),
    ("08_space_dt",   slides.slide5_space_detail),
    ("09_voices",     slides.slide6_voices),
    ("10_discussion", slides.slide7_discussion),
]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{font}" rel="stylesheet">
<style>*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#F7F7F4}}
body{{width:1600px;padding:20px}}</style>
</head><body>{body}</body></html>"""


def build_bundle(db_path: Path) -> dict:
    conn = db.get_conn(db_path)
    db.init_db(conn)
    names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
    if not names:
        dummy_data.build(conn)
        names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]

    matrix = {n: topic_score.analyze_facility(conn, n) for n in names}
    return preview.build_bundle(conn, dummy_data.target_name(), matrix, None, None,
                                peers_override=dummy_data.peer_names())


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_slides")
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    # 環境に置かれている Chromium を明示的に使う（pip の playwright が期待する
    # ビルド番号と、入っているビルドがずれることがあるため）
    exe = next(iter(sorted(Path("/opt/pw-browsers").glob(
        "chromium-*/chrome-linux/chrome"))), None)

    b = build_bundle(out / "render.db")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(exe) if exe else None)
        page = browser.new_page(viewport={"width": 1600, "height": 940},
                                device_scale_factor=1)
        for name, fn in SLIDES:
            page.set_content(PAGE.format(font=report_theme.FONT_URL, body=fn(b)))
            page.wait_for_timeout(700)
            el = page.query_selector("body > div")
            el.screenshot(path=str(out / f"{name}.png"))
            print(f"  {name}.png")
        browser.close()
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
