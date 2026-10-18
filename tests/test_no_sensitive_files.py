"""個人情報・社外秘ファイルが追跡されていないことの検査。

2026-08-02 に以下が public リポジトリへ出た:
  - data/museums/reviews.csv.gz … 実在レビュアー氏名 24,404人分・本文 32,497件
  - docs/design/slide_p09.png 他 … 「confidential」印字・乃村ブランドの社内資料

.gitignore は**すでに追跡されているファイルには効かない**し、`git add -f` で
素通りできる。ここで落とすことで初めて仕組みになる。

既知の分は KNOWN_DEBT に列挙してある。**減らすための一覧であって、
足すための一覧ではない。** ここに追記する前に、本当に追跡が必要か考えること。
"""
from __future__ import annotations

import csv
import gzip
import io
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 追跡を許さないパス形。データとバイナリの置き場を絞る。
RISKY_SUFFIXES = (".csv", ".csv.gz", ".tsv", ".jsonl", ".db", ".sqlite", ".sqlite3")
RISKY_DIRS = ("docs/design/",)
RISKY_DIR_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf")

# 個人を指す列名。CSV の中身で判定する（パスをすり抜けても捕まえる）。
PERSONAL_COLUMNS = {
    "reviewer_name", "reviewer_url", "profile_pic_url", "publisher_name",
    "author", "author_title", "投稿者", "氏名", "email", "mail",
}

# ── 既知の負債 ────────────────────────────────────────────────────────── #
#    public 公開の事故で出たもの。private 化・履歴除去の判断待ち。
#    新しいファイルをここに足さないこと。
KNOWN_DEBT = {
    "data/museums/reviews.csv.gz": "実名 24,404人分。reviewer_name は読み出し0なので列ごと削除可能",
    "samples/sample_reviews.csv": "実名1件と Google 寄稿者URL。make_sample.py にも直書きあり",
    **{f"docs/design/slide_p{n:02d}.png": "confidential 印字の社内資料"
       for n in range(3, 13)},
}

# 中身を確認済みで、個人情報を含まないもの。
VERIFIED_CLEAN = {
    "data/kaizode/facilities.sample.csv": "施設名と EXAMPLE URL のみ",
    "samples/sample_scores.xlsx": "施設名とスコアのみ",
}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def _is_risky_path(p: str) -> bool:
    if any(p.endswith(s) for s in RISKY_SUFFIXES):
        return True
    return (any(p.startswith(d) for d in RISKY_DIRS)
            and any(p.endswith(s) for s in RISKY_DIR_SUFFIXES))


def test_no_new_sensitive_files_are_tracked():
    """既知の負債より増えていないこと。"""
    allowed = set(KNOWN_DEBT) | set(VERIFIED_CLEAN)
    offenders = [p for p in _tracked() if _is_risky_path(p) and p not in allowed]
    assert not offenders, (
        "個人情報・社外秘になりうるファイルが新たに追跡されています:\n  "
        + "\n  ".join(offenders)
        + "\n\n.gitignore を通さずに追加された可能性があります。"
        "本当に必要なら中身を確認し、個人情報が無いことを確かめてから "
        "VERIFIED_CLEAN に理由つきで登録してください。"
    )


def test_known_debt_does_not_grow():
    """KNOWN_DEBT が増えていないこと。ここは減らすための一覧。"""
    assert len(KNOWN_DEBT) == 12, (
        f"KNOWN_DEBT が {len(KNOWN_DEBT)} 件になっています（既知は12件）。"
        "減ったなら期待値を下げてください。増えたなら、それは新しい事故です。"
    )


def _read_header(path: Path) -> list[str]:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                line = f.readline()
        else:
            line = path.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    except Exception:
        return []
    delim = "\t" if line.count("\t") > line.count(",") else ","
    return [c.strip().strip('"').lower() for c in next(csv.reader(io.StringIO(line), delimiter=delim), [])]


@pytest.mark.parametrize("rel", sorted(
    p for p in _tracked()
    if p.endswith((".csv", ".csv.gz", ".tsv")) and p not in KNOWN_DEBT))
def test_tracked_csv_has_no_personal_columns(rel):
    """追跡中の CSV に個人を指す列が無いこと（既知の負債は除く）。

    パスの形をすり抜けても、列名で捕まえる。
    """
    hit = sorted(set(_read_header(ROOT / rel)) & PERSONAL_COLUMNS)
    assert not hit, (
        f"{rel} に個人を指す列があります: {hit}\n"
        "架空データに置き換えるか、列ごと落としてください。"
    )
