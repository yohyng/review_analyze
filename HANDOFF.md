# VoiceBAUM 引継ぎ資料

> 口コミ（Google レビュー等）から施設の実力を可視化し、**PowerPoint レポートをワンクリックで書き出す** Streamlit アプリ。
> このドキュメントだけで、別の開発者／セッションが実装を継続できることを目標に記述しています。

- **リポジトリ**: `yohyng/review_analyze`
- **開発ブランチ**: `claude/serene-babbage-nxvus`
- **現在バージョン**: `0.13.0`（`src/config.py` の `APP_VERSION`。変更のたびに上げる運用）
- **テスト**: `python -m pytest tests/ -q` → **143 passed**（push/PRでCI自動実行）

---

## 0. まず動かす

```bash
pip install -r requirements.txt
streamlit run app.py
# テスト
python -m pytest tests/ -q
```

- **DB**: `TURSO_URL` + `TURSO_TOKEN`（環境変数 or `.streamlit/secrets.toml`）があれば Turso、無ければローカル `data/reviews.db`（SQLite）。
- **LLMインサイト（任意）**: `GEMINI_API_KEY`（無くてもレポートは出る）。
- **テーマ**: `.streamlit/config.toml` でライト固定（ダークモードでも崩れない）。

---

## 1. プロダクト概要

2モード構成の Streamlit アプリ。**`app.py` は薄いオーケストレータ（約360行）**で、
UI 実体は `src/ui/` パッケージに分割: `theme.py`（CSS/デザイントークン）/
`data.py`（DB接続＋キャッシュ層）/ `components.py`（HTMLビルダー）/
`analysis_mode.py`（分析モード `render()`）/ `admin_mode.py`（管理モード `render()`）。

### 分析モード（一般ユーザー向け・サイドバー非表示のヒーロー画面）
```
設定(setup) → ローディング(running) → プレビュー(preview)
  施設を検索して選ぶ → 6ステップの解析オーバーレイ → 16:10スライド×6+APPENDIX + PPTX DL
```
`st.session_state["an_screen"]` が `setup / running / preview` を遷移。

### 管理モード（運用者向け・左サイドバーナビ・**ログイン必須**）
`st.session_state["admin_page"]`: `dashboard / facilities / import / topic / score / text / report / profiler / kaizode / integration / account`

**認証（v0.11.0：メール＋パスワードのアカウント制・招待コードゲート）** — `src/auth.py`
- ログインは **メールアドレス＋パスワード**。ユーザーは **`app_user` テーブル**（db.py SCHEMA）に保存。パスワードは **`pbkdf2_hmac(sha256, 20万回)` でハッシュ化＋ソルト**（平文は持たない）。照合は `hmac.compare_digest`、失敗時1秒スリープ。合格で `session_state["admin_authed"]=True` / `admin_email` に格納。サイドバー下部にログイン中メール表示＋🔓ログアウト。
- **新規登録は招待コード `SIGNUP_CODE`（secrets/環境変数）を知っている人だけ**＝URLを知っているだけでは管理者になれない「登録ゲート」。登録画面（ログイン画面のタブ）でメール＋PW＋招待コードを入力→合致すれば作成し自動ログイン。**`SIGNUP_CODE` 未設定なら新規登録は無効**（登録タブに設定手順を表示）。
- **`ADMIN_PASSWORD` は「最初の1人を作る/ロックアウト回避」用の非常口**（マスターパスワード）として併存。ログインのパスワード欄にこれを入れると、アカウントが無くても入れる。後方互換。
- **完全ロック**は「ユーザー0人 かつ `SIGNUP_CODE` 未設定 かつ `ADMIN_PASSWORD` 未設定」のときのみ（入口が一つも無い状態）。それ以外はログイン/新規登録タブを表示。
- **アカウント管理ページ `👤 アカウント`**: ユーザー一覧（自分は削除不可）、招待コード無しでのユーザー追加（ログイン済み管理者の権限）、自分のパスワード変更、招待コード/非常口の設定状況表示。
- ローカル開発では `SIGNUP_CODE=xxx ADMIN_PASSWORD=yyy streamlit run app.py`。
- AppTest でも `at.session_state["admin_authed"]=True`（＋`admin_email`）を先にセットしないと管理ページに到達できない。フォーム越しの登録/ログイン検証は「シナリオごとに fresh な AppTest ＋ 一時DBファイル固定」で行う（`session_state` を使い回すとウィジェット状態が壊れる）。

ブランド: **VoiceBAUM**、アクセント **マゼンタ `#B0338A`**、背景 `#F7F7F4`、フォント Manrope + Noto Sans JP。

---

## 2. コア資産：感情・トピック統合スコアモデル（`src/topic_score.py`）

ユーザー提供の仕様書（`sentiment_topic_score_model`）を**忠実移植した「正」の実装**。SLIDE 01–03 の全数値はこのモデルから算出（TF-IDF は SLIDE 04 のみ）。

**フロー**（文単位）:
```
文 → 感情分析(キーワード辞書) → 温度スケーリング(T=0.7) → 非線形補正(α=0.7) → v_sentiment∈[0,1]
文 → 埋め込み → コサイン類似 → z-score → 適応温度 → softmax → Top-kブースト(0.5) → p_topic
文×トピック = v_sentiment × p_topic → レビュー平均 → 重み合算 → 全体
```

- **忠実性**: 参照コードと数値完全一致を検証済み（`tests/test_topic_score.py`）。ベクトル化バッチ（`_topic_probabilities_batch`）で高速化（2000件/5000文 ≈ 2秒、逐次版とビット一致）。
- **トピック軸 = 22観点**（`DEFAULT_TOPICS`、順序は `TOPIC_ORDER`）+「全体」。ReviewLens の23観点に一致。各軸にキーワード群と重み。
- **バックエンド（差し替え可能）**:
  - **既定 = 軽量**: 共有 TF-IDF 空間のコサイン類似（torch 不要・どこでも動く）。
  - **任意 = SBERT**: `analyze_facility(conn, name, backend="sbert")`。`sentence-transformers` + `sonoisa/sentence-bert-base-ja-mean-tokens` が必要（torch ~1-2GB）。
  - ⚠️ **軽量版の限界**: 22観点は粒度が細かく（提供内容の品質/多様性/独自性…）、軽量バックエンドではスコアが平坦になりがち。精度を出すなら SBERT 推奨。
- **主API**: `analyze_reviews(reviews, topics, backend)` / `analyze_facility(conn, name)` / `facility_topic_matrix(conn, names)`（全施設分・比較用）。
- 出力 `TopicScoreResult`: `topics[TopicScore]`（name/weight/avg_score/salience/sentiment）、`weighted_sentiment_100`（表示用の総合スコア）、`sentiment_by_topic()` 等。

---

## 3. 分析結果スライド（`src/preview.py`）

`build_bundle(conn, target, topic_results, profile, insights)` が**素材dict（bundle）を一括生成**し、`html_*` 関数が **16:10 の固定サイズHTMLキャンバス**（`container-type:inline-size` + `cqw` 単位）を返す。app.py はそれを `st.markdown(..., unsafe_allow_html=True)` で縦に並べる。

| スライド | 関数 | 内容 / データ源 |
|---|---|---|
| OVERVIEW | `html_overview` | 施設名＋KPI4枚（総合評価/比較順位/レビュー件数/ポジティブ率） |
| PROFILE | `html_profile` | 写真＋基本情報（施設名/業種/住所/アクセス/開業/口コミ） |
| SLIDE 01 | `html_slide01` | 比較分析による特徴点抽出＋インサイト（**topic_score**、単体時は中立50基準） |
| SLIDE 02 | `html_slide02` | 感情評価・トピック分類（**23観点の静的縦棒**・0-120軸・50中立破線） |
| SLIDE 03 | `html_slide03` | 数値による比較評価（強み/弱みTOP5・対象 vs 全体平均） |
| SLIDE 04 | `html_slide04` | **象徴的な口コミ ランキング**（TF-IDF総合＝`text_analysis.symbolic_ranking`） |
| APPENDIX | `html_appendix` | **比較対象施設一覧**（3カラム・ピア施設名。`bundle["peer_names"]`＝口コミのある比較施設。ピア0件なら空文字を返し非表示） |

- SLIDE 02 は以前 plotly（可変/ツールバー付き）だったが、**他スライドと揃えて静的HTML**に変更（ユーザー要望）。
- `bundle` は分析時に1回作って `st.session_state["an_preview"]` にキャッシュ（プレビュー再描画を高速化）。

---

## 4. PROFILE（写真・住所補完）

### 写真（Turso/SQLite に永続化・自動リサイズ）
- **`src/images.py` `resize_for_storage`**: 長辺1200px/JPEG q80 に縮小（Pillow）。1枚150-350KB。
- **`src/db.py`**: `facility_photo(facility_id PK, image BLOB, mime, updated_at)` ＋ `save_photo/get_photo/photo_updated_at/delete_photo`。
- **Turso HTTPクライアントのBLOB対応**（重要）: `_encode_params` が bytes→`{"type":"blob","base64":...}`、`_parse_turso_result` が blobセル→bytes。ローカルSQLiteはネイティブ。
- app.py プレビューの PROFILE は **「✏️ 編集」トグルでその場をインライン編集**（静的スライド ↔ 編集フォームを切替）。左に写真アップローダ＋プレビュー＋保存/削除、右に業種/住所/アクセス/開業の手入力＋「🗺️ 自動取得」＋「📄 PPTXを更新」。アップ→自動リサイズ→「💾 保存」で永続化。読込は `@st.cache_data`（`updated_at`で無効化）。**非保存でも表示＋DL反映**。
- **容量**: 250KB/枚 → 9GBで約3.6万枚。46施設で約11MB。問題なし。

### 住所・アクセス・開業（`src/geocode.py`・OSM/Wikidata・生成AI不使用）
| 項目 | ソース | 関数 |
|---|---|---|
| 住所/緯度経度/開業(start_date)/業種 | Nominatim | `_geocode` |
| アクセス（最寄り駅・徒歩分） | Overpass（`railway=station`）+ ハバースイン距離 | `_nearest_station` |
| 開業（OSMに無い場合の補完） | Wikidata 設立(P571) | `_wikidata_facts` |

- 統合API `enrich(name)` → 取れた項目のみのdict。全て構造化データ（**嘘=ハルシネーションは出ない**）。失敗時は空（手入力フォールバック）。全て `lru_cache` + 短タイムアウト + try/except。

---

## 5. PPTXレポート（`src/report.py`）

`build_report(conn, target, axis, insights, topic_list, topic_score_result, profile_info, photo_bytes, output_path)` が **python-pptx のネイティブ図表**（画像埋め込みでない＝日本語が正しく出る/編集可）でデッキを生成。

スライド構成: 表紙 / エグゼクティブサマリー / **PROFILE（写真＋基本情報）** / 感情・トピック統合スコア / スコア比較（比較データがある時）/ 強み・弱みTOP5 / テキスト分析 / **象徴的な口コミランキング** / トピック分析 / インサイト①② 。
- ファイル名 `VoiceBAUM_<施設名>.pptx`。16:9（13.333×7.5in）。
- プレビューで PROFILE を編集後、「📄 この内容でPPTXを更新」で **写真＋住所等を反映して再生成**（`an_axis`/`an_specific_name`/`an_topic_score`等を session から使う）。

---

## 6. データ層とデモデータ

### DBスキーマ（`src/db.py` の `SCHEMA`）
`facility`（施設マスタ: name/type/category/general_rating/total_reviews） / `review`（口コミ本文） / `review_subscore`（Google観点別） / `score`（Excel定量指標） / **`facility_photo`（写真BLOB）** / `kaizode_sync`（KAIZODE差分同期状態） / **`app_user`（管理ログイン用: email PK / password_hash / salt / role / created_at）**。
`get_conn()` は Turso（`_secret("TURSO_URL")`+`_secret("TURSO_TOKEN")`）優先、無ければローカルSQLite。行は `_Row`（sqlite3.Row互換・**dict非継承**なので pandas に位置で渡せる）。

### KAIZODE 連携（口コミ対象施設の自動取得・v0.9.0）
「画面を閉じていても動く」バックグラウンド収集。KAIZODE 側がレビュー収集を非同期で行うため、こちらのジョブは軽い（発注と回収の2役）。

- **`src/kaizode.py`**: APIクライアント。`x-api-key` 認証・**3.2秒スロットル（20req/分制限）**・429リトライ・ページネーション（`iter_reviews`、既定5000件/回=30MB上限対策）・`published_since` 差分取得。`to_parsed_review()` が KAIZODE Review → `ParsedReview` 変換（`review_id` がそのまま使え重複排除が自然に効く）。同期状態は **`kaizode_sync` テーブル**（db.py SCHEMA に追加済み）に `last_published_at` を記録。
- **`scripts/fetch_kaizode.py`**: CLI。
  - `--status` … データセット一覧と収集状況（status 10=抽出中/20=解析中/30=完了/40=失敗）
  - `--create facilities.csv` … 施設リスト（name,url,since）からデータセット作成→収集開始（発注）
  - `--sync` … **status=30 のみ**差分DL→施設ごとに `upsert_facility`+`insert_reviews`（回収）。`--category`/`--ftype`/`--full`/`--dataset-id` オプションあり
- **`.github/workflows/kaizode-sync.yml`**: 毎日 JST 3:00 に `--sync` を実行（`workflow_dispatch` で手動も可）。必要 Secrets: `KAIZODE_API_KEY` / `TURSO_URL` / `TURSO_TOKEN`。
- **管理画面「📡 KAIZODE連携」ページ（v0.10.0）**: ログイン後のみ到達。3タブ＝収集状況（一覧）/収集を発注（施設名,URL,since を行入力）/DBへ取り込み（差分同期・category指定可）。同期の実体は CLI と共通の `kaizode.sync_datasets()`。**APIキーは secrets/環境変数を優先し、無ければ「セッション限り」のパスワード入力**（DB・ファイルに保存しない、末尾4桁のみ表示、破棄ボタンあり）。
- サンプル: `data/kaizode/facilities.sample.csv`。テスト: `tests/test_kaizode.py`（モックセッションで13本）。
- ⚠️ **実APIとの疎通はこのサンドボックスでは未検証**（外部通信遮断のため）。モックで検証済み。初回はローカルで `--status` から確認を。

### 企業ミュージアム デモデータ
- **`data/museums/reviews.csv.gz`**（46施設・約32k件の口コミ。元は `all_1.xlsx`）。
- **`scripts/import_museums.py`**: `db.get_conn()` の接続先へ取り込み（Turso認証があればTurso）。
  - category=「企業ミュージアム」固定、**容器文化ミュージアム=対象(target)**、他45=比較(comparison)。
  - `--max-per-facility 200`（既定・比較施設のみ／対象は全件・デモを軽く）、`--max-per-facility 0` で全件、`--reset` で既存削除。
  - review_id は決定論ハッシュ（再実行で重複しない）。
- **Turso一括挿入を高速化済み**: `db.insert_reviews` の Turso 経路は **50件/HTTP のバッチ**（1件1HTTPだと数万件で数十分→数秒）。
- デモ検証値（容器文化ミュージアム・軽量backend）: 総合感情52.1 / 順位38/46 / 強み=美的完成度+5.8 / 弱み=比較優位性-5.9。46施設のトピック行列 ≈ 32秒（`@st.cache_data`で以降即時）。

---

## 7. 重要な設計判断（なぜそうしたか）

1. **軽量バックエンド既定**: Streamlit Cloud 無料枠で動かすため torch を避ける。SBERTは任意（精度優先時）。
2. **施設選択はネイティブ `st.button`（クエリパラメータ・リンク方式は撤去）**: `?pick=`等の `<a>` はページ全リロードを起こし、(1)一瞬ブラックアウト (2)`session_state` リセットで `an_target` が消え分析が始まらない、という不具合が出たため（v0.7.3で修正）。**今後もリロード方式は使わないこと**。
3. **スライドは16:10固定HTMLキャンバス**（plotly可変ではなく）: 見た目統一・DLと一致。SLIDE 02も静的化。
4. **PROFILE自動補完は生成AI不使用**: OSM/Overpass/Wikidata の構造化データのみ（ユーザー方針）。取れなければ空欄。
5. **写真はTurso BLOB＋自動リサイズ**: リクエストサイズ上限・DB肥大を回避（長辺1200px）。
6. **デモ取り込みはサンプリング既定**: 全件だと行列計算が155秒→キャップで32秒。

---

## 8. 既知の制約・注意点

- **この開発サンドボックスは外部通信（OSM/Nominatim/Overpass/Wikidata）がプロキシで403ブロック**。→ geocode系は実ネットワーク往復を**この環境では検証不可**。ロジックはモック/オフラインでテスト済み（`tests/test_geocode.py`）。**デプロイ先（通信可）で動く想定**。
- **Turso認証情報はこの環境に無い**ため、Tursoへの実書き込みは未実施。BLOB encode/decode は**モックpipeline接続で検証済み**。実Tursoへ入れるには認証情報を設定して `python scripts/import_museums.py` を実行（ユーザーが実施する運用）。
- **22観点は軽量backendで平坦**になりがち（§2）。
- **PPTXは16:9固定**（プレビューは16:10）。合わせたい場合は座標再調整が必要。
- Nominatim は User-Agent の実在連絡先が必要（現在プレースホルダ）。本番投入時は正規のUAに。

---

## 9. 次の一手

**かわら美術館でPROFILEが空だった件は v0.8.4 で対応済み**:
- ✅ **業種(category)を配線**: `enrich` の category を bundle 注入＋エディタ「業種」欄に反映（優先度: 手入力 > DB > OSM）。
- ✅ **自動取得を自動化**: プレビュー初回描画で `geocode.enrich` を1回だけ実行（`_prof["_enriched"]` フラグ＋spinner）。住所/アクセス/開業/業種が**ボタン無しで**入る。
- ✅ **長い施設名のフォールバック**: `_geocode` がフル名称→`_simplify`（括弧除去・`・`前半）の順で試行。
- ✅ **フィードバック**: ボタン押下時に取得できた項目を明示（例「取得しました: 住所・アクセス」）。

**その他の候補**:
- SBERTバックエンドの本番採用（requirements追加＋デプロイ要件確認）。
- 業種のWikidata(P31)マッピング（現状はOSMタイプのみ）。
- 画像をオブジェクトストレージ（R2/S3）に移す（大量運用時）。

---

## 10. ファイル早見表

| ファイル | 役割 |
|---|---|
| `app.py` | 薄いオーケストレータ（約360行）: 設定/CSS/session/ナビ+ログインゲート→ `*_mode.render()` へ振り分け |
| `src/ui/theme.py` | デザイントークン＋グローバルCSS（`inject_global_css()`） |
| `src/ui/data.py` | DB接続（`get_conn` cache_resource）＋キャッシュ済みデータ層 |
| `src/ui/components.py` | 純粋HTMLビルダー（loading/selected カード、facility_card） |
| `src/ui/analysis_mode.py` | 分析モード `render()`（setup/running/preview） |
| `src/ui/admin_mode.py` | 管理モード `render()`（全11ページ） |
| `src/auth.py` | **管理ログインの認証**（pbkdf2ハッシュ・招待コードゲート・ユーザーCRUD） |
| `src/topic_score.py` | **感情・トピック統合スコアモデル（正）**。22観点 |
| `src/preview.py` | 分析結果スライド（bundle生成＋16:10 HTML） |
| `src/report.py` | PPTX生成（python-pptxネイティブ） |
| `src/text_analysis.py` | TF-IDF/N-gram/代表口コミ/**symbolic_ranking** |
| `src/geocode.py` | 住所/アクセス/開業の**OSM/Wikidata補完（生成なし）** |
| `src/images.py` | 写真の自動リサイズ（Pillow） |
| `src/db.py` | Turso(HTTP)/SQLite・スキーマ・**BLOB対応**・写真CRUD |
| `src/analysis.py` | 施設比較（`build_comparison`・comparison_avg/all_avg/specific） |
| `src/charts.py` | plotly図（管理モード/詳細分析で使用） |
| `src/scoring.py` | 口コミ→定量スコア自動算出 |
| `src/review_csv.py` `src/score_excel.py` `src/csv_profiler.py` | 取り込み系 |
| `src/llm.py` `src/search.py` `src/topics.py` | LLMインサイト / あいまい検索 / 旧トピック(KMeans) |
| `scripts/import_museums.py` | 企業ミュージアム46施設の取り込み |
| `data/museums/reviews.csv.gz` | デモ口コミデータ |

---

## 11. 変更履歴（要約）

- **v0.13.0** 抜本アップデート（A/B/E）: ①**依存バージョン固定**＋**テストCI**（push/PRでpytest）＋**アップロード上限50MB**（安定化）。②**`app.py` を `src/ui/` へ分割**（2451→約360行、theme/data/components/analysis_mode/admin_mode）。③非推奨 **`use_container_width`→`width="stretch"`** 全50箇所移行、解析エラーの見える化＋ログ。④取り込みに**「1施設あたり最大件数」上限**（大量取込の現実化）＋**PRAGMA user_version マイグレーション土台**。分割中に潜在バグ（関数内 `import os` による UnboundLocalError）も修正
- **v0.12.1** マルチ施設取り込みが途中(約20/46施設)で力尽きる問題を修正。原因は保存ループが施設ごとに `parse_reviews` を呼び**ファイル全体を毎回再解析**（O(n²)、実測46施設で約22秒→Cloudで更に遅くヘルスチェック切れ）。`review_csv.parse_reviews_grouped()`（1回解析で全施設へ振り分け＝実測18.7倍高速）を追加し保存ループを置換。ネストした`st.status`ウィジェットを廃し施設ベースの単一プログレスバーに。`_load_text` を**生bytes対応**（アプリは `uploaded.getvalue()` を渡す）。Turso挿入バッチ 50→100
- **v0.12.0** 分析資料の最後に **APPENDIX「比較対象施設一覧」スライド**を追加（プレビュー＝`preview.html_appendix`／PPTX＝`report._slide_appendix`、3カラム・ピア施設名・施設数バッジ・上限45で「ほかN施設」）。ピア0件なら非表示
- **v0.11.1** 取り込み画面のクラッシュ修正: マルチ施設のチェック操作の再実行ごとに `infer_facilities`（数万行フル再解析）が走りOOMで落ちていた → `@st.cache_data` でファイル内容キャッシュ化（返り値は小さいサマリ）。単一施設プレビューの `parse_reviews` も同様にキャッシュ（max_entries=8）。保存ループは1件ずつ処理でメモリ安全なので据え置き
- **v0.11.0** 管理ログインを**メール＋パスワードのアカウント制**に（`src/auth.py`・`app_user`テーブル・pbkdf2ハッシュ）。**新規登録は招待コード`SIGNUP_CODE`ゲート**、`ADMIN_PASSWORD`は非常口として併存。画面上のログイン/新規登録タブ＋`👤 アカウント`管理ページ（一覧/追加/自分のPW変更）
- **v0.10.1** 管理ログインの非ASCIIパスワードでの `hmac.compare_digest` TypeError 修正（UTF-8 bytesで比較）
- **v0.10.0** 管理モードのログイン必須化（ADMIN_PASSWORD・フェイルクローズ）＋管理画面「📡 KAIZODE連携」ページ（発注/状況/取り込み、キーはsecrets優先・セッション限り入力可）
- **v0.9.0** KAIZODE連携（APIクライアント＋発注/回収CLI＋GitHub Actions定期同期＝画面を閉じても動く収集）
- **v0.8.5** PROFILEをその場でインライン編集（✏️トグルで写真アップ＋各項目の手入力）。下部の折りたたみ編集は廃止
- **v0.8.4** PROFILE自動補完を完成（業種配線・自動化・長い名称フォールバック・取得フィードバック）
- **v0.8.3** 開業のWikidata(設立)補完
- **v0.8.2** 写真をTurso/SQLiteにBLOB永続化＋自動リサイズ
- **v0.8.1** PROFILE自動補完（OSM/Overpass、生成なし）
- **v0.8.0** SLIDE 02静的化 / PROFILE写真＋住所 / SLIDE 04ランキング
- **v0.7.3** 施設選択のブラックアウト＆分析停止を修正（ネイティブボタン化）
- **v0.7.2** 企業ミュージアム デモデータ＋importer / Tursoバッチ挿入
- **v0.7.1** 分析ヒーロー画面を画像忠実化（検索/候補/選択）
- **v0.7.0** SLIDE 01-03を22観点モデル駆動 / TF-IDFはSLIDE 04のみ
- **v0.6.x** 統合スコアモデル実装 / VoiceBAUM UI / 16:10スライド / ダークモード対策 / ローディングオーバーレイ
- **v0.5.0** VoiceBAUM リデザイン（2モード）
```
