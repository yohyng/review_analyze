# 口コミ分析アプリ

施設の口コミ（Googleマップ/KAIZODE）と既存スコアExcelを取り込み、強み・弱み分析と
インサイト（LLM）、パワポレポートまで自動化するためのアプリ。

ホワイトボードのフロー（①〜⑨）を段階的に実装します。

```
①施設名入力 → ②比較施設入力 → ③口コミCSV取込 → ④スコアExcel取込
   → ⑤グラフ化 → ⑥強み弱みTOP5 → ⑦TF-IDF/N-gram → ⑧LLMインサイト → ⑨パワポ化
```

## 現在の実装範囲：取り込み層（①〜④）✅

口コミCSVとスコアExcelを投げ込んでSQLiteに格納し、状況を確認できる所まで。
⑤〜⑨（グラフ・強み弱み・テキスト分析・LLM・パワポ）は次フェーズ。

## セットアップ & 起動

```bash
pip install -r requirements.txt
python samples/make_sample.py   # 動作確認用サンプル生成（任意）
streamlit run app.py
```

画面（サイドバー）:
1. **口コミCSV取り込み** — 施設名を手入力し、CSV/TSVを投入
2. **スコアExcel取り込み** — Excelを投入 → 列を確認して保存
3. **取り込み状況** — DBの中身を一覧

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
app.py                 # Streamlit UI（取り込み3画面）
src/
  config.py            # パス・定数
  db.py                # SQLite スキーマ + CRUD
  review_csv.py        # ③ 口コミCSVパーサ
  score_excel.py       # ④ スコアExcel汎用インポータ
samples/make_sample.py # サンプルデータ生成
tests/                 # pytest
```
