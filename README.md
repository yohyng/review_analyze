# 口コミ分析アプリ

施設の口コミ（Googleマップ/KAIZODE）と既存スコアExcelを取り込み、強み・弱み分析と
インサイト（LLM）、パワポレポートまで自動化するためのアプリ。

ホワイトボードのフロー（①〜⑨）を段階的に実装します。

```
①施設名入力 → ②比較施設入力 → ③口コミCSV取込 → ④スコアExcel取込
   → ⑤グラフ化 → ⑥強み弱みTOP5 → ⑦TF-IDF/N-gram → ⑧LLMインサイト → ⑨パワポ化
```

## 実装状況：①〜⑨ すべて実装済み ✅

| ステップ | 内容 | 実装 |
|---|---|---|
| ①②③ | 施設名入力・比較施設・口コミCSV取込 | `src/review_csv.py` |
| ④ | スコアExcel取込（汎用インポータ） | `src/score_excel.py` |
| ⑤⑥ | グラフ化・強み弱みTOP5（3比較軸） | `src/analysis.py` `src/charts.py` |
| ⑦ | TF-IDF + N-gram テキスト分析 | `src/text_analysis.py` |
| ⑧ | LLMインサイト（まとめ/強み/弱み/示唆/改善提案） | `src/llm.py` |
| ⑨ | パワポ化（編集可能なネイティブchart/table） | `src/report.py` |

## セットアップ & 起動

```bash
pip install -r requirements.txt
python samples/make_sample.py   # 取り込み用サンプル生成（任意）
python samples/make_report.py   # 仮レポート samples/sample_report.pptx を生成（任意）
streamlit run app.py
```

画面（サイドバー）:
1. **口コミCSV取り込み** — 施設名を手入力し、CSV/TSVを投入
2. **スコアExcel取り込み** — Excelを投入 → 列を確認して保存
3. **取り込み状況** — DBの中身を一覧
4. **強み・弱み分析** — レーダー/差分バー + TOP5（3比較軸タブ）
5. **テキスト分析 & インサイト** — TF-IDF/N-gram + LLMインサイト
6. **レポート出力 (PPTX)** — 全分析を1つのPowerPointに

## LLM（⑧）の設定

`ANTHROPIC_API_KEY` を環境変数 / `.streamlit/secrets.toml` / 画面入力 のいずれかで設定。

## レポート（⑨）について

`python-pptx` のネイティブchart/tableで生成するため、出力pptxは**PowerPoint上で
編集可能**（画像埋め込みではない）。日本語フォントの問題も回避。全7スライド構成：
タイトル → サマリー → スコア比較（レーダー+バー）→ 強み弱みTOP5 →
テキスト分析 → インサイト①(強み/弱み) → インサイト②(示唆/改善提案)。

## データの扱い

### ③ 口コミCSV（`src/review_csv.py`）
KAIZODE/Googleマップ系のクセを吸収します：
- タブ/カンマ区切りを自動判定
- `review` の複数行・クオート囲みに対応
- `review_details`・`photos`・`input` の**Python literal**（シングルクオート）を `ast.literal_eval` で解析
- `place_name` が空でも、**施設名は手入力**で確定（1 CSV = 1 施設）
- ヘッダの綴り違い `overall_place_riviews` を許容
- `error` 行はスキップ／`review_id` で重複排除（無い行はハッシュで代替）

`review_details` は Google 固有のサブ軸（Rooms/Service/Location…）として
`review_subscore` に展開。御社の独自指標とは別物として保持します。

### ④ スコアExcel（`src/score_excel.py`）
列を固定しない汎用インポータ：
- `.xlsx/.csv` を読み、**施設名列**と**数値の指標列**を自動推定 → 画面で確認
- スケール（5/100点）を最大値から推定
- 横持ち（1施設1行）／縦持ち（施設・指標・値）の両対応
- 施設名は③の手入力名と**完全一致**で紐付け

## DBスキーマ（SQLite, `data/reviews.db`）

| テーブル | 役割 |
|---|---|
| `facility` | 施設マスタ（名前・種別・総合評点） |
| `review` | 口コミ本文（重複排除キー付き） |
| `review_subscore` | `review_details` のGoogle軸スコア |
| `score` | Excelの独自定量化指標 |

## テスト

```bash
python -m pytest -q
```

## 構成

```
app.py                 # Streamlit UI（6画面）
src/
  config.py            # パス・定数
  db.py                # SQLite スキーマ + CRUD
  review_csv.py        # ③ 口コミCSVパーサ
  score_excel.py       # ④ スコアExcel汎用インポータ
  analysis.py          # ⑤⑥ スコア正規化・比較・TOP5
  charts.py            # ⑤⑥ plotly グラフ
  text_analysis.py     # ⑦ TF-IDF + N-gram
  llm.py               # ⑧ LLMインサイト
  report.py            # ⑨ PPTX生成
samples/
  make_sample.py       # 取り込み用サンプル生成
  make_report.py       # 仮レポート生成
tests/                 # pytest（26 tests）
```
