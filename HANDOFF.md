# VoiceBAUM 引継ぎ資料

> 口コミ（Google レビュー等）から施設の実力を可視化し、**PowerPoint レポートをワンクリックで書き出す** Streamlit アプリ。
> このドキュメントだけで、別の開発者／セッションが実装を継続できることを目標に記述しています。

- **リポジトリ**: `yohyng/review_analyze`
- **開発ブランチ**: `claude/serene-babbage-nxvus`
- **現在バージョン**: `0.22.0`（`src/config.py` の `APP_VERSION`。変更のたびに上げる運用）
- **テスト**: `python -m pytest tests/ -q` → **181 passed**（push/PRでCI自動実行）
- **このドキュメントについて**: ツール非依存の引継ぎ資産。Claude Code / Codex など**複数の開発ツールを都度切り替えて作業する運用**を想定しているため、チャット履歴に頼らずここだけ読めば継続できるよう、機能追加・設計変更のたびに更新すること（§11 変更履歴に1行追記が最低限）。

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
| DISCLAIMER | `html_disclaimer` | **免責事項（冒頭1枚目）**。文言は `config.DISCLAIMER_TITLE`/`DISCLAIMER_POINTS`（preview/PPTX共通・1箇所で編集） |
| SLIDE 1「施設・基本情報」 | `html_facility_info` | **v0.22.0で新設**。旧OVERVIEW+PROFILE+APPENDIXを1枚に統合（詳細は直下） |
| SLIDE 01 | `html_slide01` | 比較分析による特徴点抽出＋インサイト（**topic_score**、単体時は中立50基準） |
| SLIDE 02 | `html_slide02` | 感情評価・トピック分類（**23観点の静的縦棒**・0-120軸・50中立破線） |
| SLIDE 03 | `html_slide03` | 数値による比較評価（強み/弱みTOP5・対象 vs 全体平均） |
| SLIDE 04 | `html_slide04` | **象徴的な口コミ ランキング**（TF-IDF総合＝`text_analysis.symbolic_ranking`） |

- SLIDE 02 は以前 plotly（可変/ツールバー付き）だったが、**他スライドと揃えて静的HTML**に変更（ユーザー要望）。
- `bundle` は分析時に1回作って `st.session_state["an_preview"]` にキャッシュ（プレビュー再描画を高速化）。
- `html_overview` / `html_profile` / `html_appendix`（旧OVERVIEW/PROFILE/APPENDIX）は**関数・テストとも削除せず残置**（呼び出し元だけ `html_facility_info` に統一）。

### SLIDE 1「施設・基本情報」（`html_facility_info`・v0.22.0で新設）
ユーザー提供のモック画像に忠実化した統合スライド。**このスライド限定の新配色**（濃紺 `S1_NAVY` + ピンク `S1_PINK`。他スライドの `ACCENT`=マゼンタ基調には影響しない）。
- **施設プロフィールカード**: 写真＋住所／開業／**延床**／カテゴリの4行。
- **口コミサマリーカード**: 総口コミ数／総合評価（★表示）。
- **口コミ数の推移カード**: `db.monthly_review_counts()` を月次**累積**にした折れ線（SVG polyline、`preserveAspectRatio="none"` + `vector-effect="non-scaling-stroke"` で線幅を保つ）。直近3ヶ月 vs その前3ヶ月の新規件数比較で「継続的に増加傾向／減少傾向／横ばい傾向」を自動判定（`_trend_trend_note`）。データ2点未満は「データが不足しています」。
- **比較対象施設カード**: `type=comparison` かつ**同カテゴリを優先**して最大5件、`facility_photo` があれば写真表示（無ければプレースホルダー）。同カテゴリ施設が5件に満たなければ他カテゴリで補充（`peer_display_same_category` で注記文言を出し分け）。
- **延床（floor_area）**: OSM等の外部データ源が存在しない完全手入力項目。`facility.floor_area` カラム（v0.22.0で追加・`_SCHEMA_VERSION=2`）に**永続化**（住所/アクセス/開業とは異なり、既存の「💾 保存」ボタンでDB保存される。他は現状セッションのみ＝§8参照）。PROFILE編集フォーム（`analysis_mode.py`）に入力欄あり。PPTX側 `report._slide_profile` にも延床行を追加済み。

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
- **`parse_maps_url(url)`**（v0.21.0）: Google Maps の **search URL**（`.../maps/search/?query=...`）と **place直リン**（`.../maps/place/施設名/@lat,lon,...`）の両方から施設名を抽出。`google.*`（`.com`/`.co.jp`等）ドメイン限定、失敗時は `None`（呼び出し側は手入力名にフォールバック）。ヒーロー画面のKAIZODE発注導線で使用（§6）。
- **`search_candidates` / `discover_by_keyword`（Overpassテーマ検索）は関数・テストとも残存しているが、v0.21.0時点でUIからは呼ばれていない**（§6・§11参照。OSM/Nominatimのカバレッジ不足でUIから撤去したが、コードは削除せず残置）。

---

## 5. PPTXレポート（`src/report.py`）

`build_report(conn, target, axis, insights, topic_list, topic_score_result, profile_info, photo_bytes, output_path)` が **python-pptx のネイティブ図表**（画像埋め込みでない＝日本語が正しく出る/編集可）でデッキを生成。

スライド構成: 表紙 / エグゼクティブサマリー / **PROFILE（写真＋基本情報）** / 感情・トピック統合スコア / スコア比較（比較データがある時）/ 強み・弱みTOP5 / テキスト分析 / **象徴的な口コミランキング** / トピック分析 / インサイト①② 。
- ファイル名 `VoiceBAUM_<施設名>.pptx`。16:9（13.333×7.5in）。
- プレビューで PROFILE を編集後、「📄 この内容でPPTXを更新」で **写真＋住所等を反映して再生成**（`an_axis`/`an_specific_name`/`an_topic_score`等を session から使う）。

---

## 6. データ層とデモデータ

### DBスキーマ（`src/db.py` の `SCHEMA`）
`facility`（施設マスタ: name/type/category/general_rating/total_reviews） / `review`（口コミ本文） / `review_subscore`（Google観点別） / `score`（Excel定量指標） / **`facility_photo`（写真BLOB）** / `kaizode_sync`（KAIZODE差分同期状態）/ `kaizode_usage`（月間取得件数・上限管理） / **`app_user`（管理ログイン用: email PK / password_hash / salt / role / created_at）**。
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

#### ヒーロー画面（一般ユーザー向け）の収集導線（`src/ui/analysis_mode.py` `_kz_collect_section` 系・v0.21.0で刷新）
検索した施設の口コミがDBに無いとき、ログイン中の管理者にその場で発注させる導線。**v0.17〜v0.20 では「Nominatim名前検索→候補選択」「Overpassテーマ検索」を用意していたが、OSMのカバレッジ不足（地方施設や「和紙」のようなテーマ語が拾えない）で実用に耐えず、v0.21.0で撤去し以下のシンプルなフローに置き換えた**:

1. **STEP1 入力**: 「Google MapsのURL または 施設名」を1つのテキスト欄に入力するだけ。URLなら `geocode.parse_maps_url()` で施設名を自動抽出（search URL / place直リン 両対応）。抽出できなければ入力文字列をそのまま施設名として使う。
2. **プレビュー**: 抽出した施設名で `geocode.lookup()`（Nominatim軽量版）を引き、住所が取れれば表示（取れなくても発注は可能）。あわせて `kaizode.match_datasets()` でKAIZODE側の**既存収集**をデータセット名の部分一致で表示（二重発注防止）。
3. **発注**: 「📡 今すぐ集める」→ `_kz_order()` が `create_dataset()` を呼び、返ってきた `dataset_id` を `st.session_state["an_kz_ongoing::{query}"]` に保存。
4. **STEP2 進捗表示**: `dataset_id` がセッションにある間、`_kz_progress_tracker()` が代わりに描画される。**`@st.fragment(run_every="3s")` で実装**（プログレスバー: status 10=33%/20=66%/30=100%）。fragmentなので**この部分だけ**が3秒ごとに再実行され、ページ全体はリロードされない（以前の `time.sleep()+st.rerun()` はページ全体がガクつく問題があった）。「🔄 今すぐ確認」ボタンは通常の `st.rerun()`（fragment自動更新中でない限り `scope="fragment"` は例外になるため）。
5. **STEP3 自動取り込み**: status=30（完了）を検知すると自動で `_kz_pull()` を呼び、DBに取り込んだ上で `an_target` にセットして分析画面へ。status=40（失敗）はエラー表示のみ。

- ⚠️ `geocode.search_candidates` / `discover_by_keyword`（Overpassテーマ検索）は**関数本体・テストは削除せず残置**（§4末尾）。将来また使う可能性がある場合の再利用のため。呼び出し元（UI）から外しただけ。
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
- **KAIZODEの月間上限（`MONTHLY_LIMIT=20,000`）はこのアプリ独自のローカル安全装置**（`kaizode_usage`テーブルで自前カウント）。**KAIZODE本体には対応する概念が無い**ので、KAIZODE側の管理画面等を見ても一致する「上限」表示は出ない。問い合わせが来たらまずここを疑う（§11 v0.21.0の境界値バグのような誤検知もあり得る）。
- `geocode.search_candidates` / `discover_by_keyword` はUIから外れた未使用コード（§6末尾）。今後完全に使わないと決まったら削除候補。
- **PROFILE項目の永続化は不揃い**: 住所／アクセス／開業／業種は `st.session_state` のみ（DB非永続・ページ再訪でOSM再取得 or 空）に対し、**延床（floor_area）だけ `facility` テーブルに永続化**（§3・§4）。「延床は保存されるのに住所は保存されない」という一貫性の無さは意図的な差（延床はOSM等の自動補完手段が無い純粋な手入力項目のため）だが、初見だと不整合に見えるので注意。

---

## 9. 次の一手

**候補**:
- `geocode.search_candidates` / `discover_by_keyword`（§6・§8）: 使わないと決まれば削除、または別の入口（管理画面側の一括登録等）に転用するか判断する。
- SBERTバックエンドの本番採用（requirements追加＋デプロイ要件確認）。
- 業種のWikidata(P31)マッピング（現状はOSMタイプのみ）。
- 画像をオブジェクトストレージ（R2/S3）に移す（大量運用時）。
- KAIZODE収集の進捗ポーリング（§6 `_kz_progress_tracker`）は現状ブラウザタブを開いている間のみ動く。閉じても継続収集自体はKAIZODE側で進むので実害は無いが、「離脱後に完了を知る」手段（通知等）が欲しくなったら要検討。

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

- **v0.22.0** 分析結果の1枚目を「施設・基本情報」統合スライドに刷新（詳細は§3末尾）:
  - ユーザー提供のモック画像に合わせ、旧 **OVERVIEW（KPI4枚）+ PROFILE（写真+基本情報）+ APPENDIX（比較施設一覧）を `html_facility_info()` 1枚に統合**。呼び出し元（`analysis_mode.py`）を新関数に一本化（旧3関数は削除せず残置）。
  - **このスライド限定の新配色**（濃紺+ピンク）を導入。他スライドの VoiceBAUM 基調（マゼンタ `ACCENT`）とは独立。
  - **延床（floor_area）を新規追加**: `facility` テーブルに `ALTER TABLE` で新規カラム（`_SCHEMA_VERSION` 1→2）。外部データ源が無い完全手入力項目のため、PROFILE編集フォームの「💾 保存」でDB永続化（住所/アクセス/開業は従来通りセッションのみ・§8に非対称性の注記あり）。PPTX (`report._slide_profile`) にも延床行を追加。
  - **口コミ数の推移**を新規追加: `db.monthly_review_counts()`（月次件数、`strftime('%Y-%m', review_date)` グルーピング）→ preview側で累積化し、SVG折れ線で描画。直近3ヶ月 vs その前3ヶ月の比較で増減傾向を自動ラベリング。
  - **比較対象施設に写真を追加**: `type=comparison` から**同カテゴリを優先**して最大5件選び、`facility_photo` があれば表示（無ければプレースホルダー）。
  - テスト 163→181（`tests/test_facility_info.py` 新設・`tests/test_db.py` に4件追加）。

- **v0.21.0** ヒーロー収集導線を全面刷新（詳細は§6）:
  - v0.17〜v0.20で作った「Nominatim名前検索→候補選択」「Overpassテーマ検索」をUIから撤去し、**「URL/施設名を1つ入力→自動抽出→プレビュー→発注」の1本道**に簡素化（OSMのカバレッジ不足で実用に耐えないと判断）。関数自体（`search_candidates`/`discover_by_keyword`）は削除せず残置。
  - `geocode.parse_maps_url()` 新設。Google Maps **search URL**と**place直リン**（`.../maps/place/施設名/@lat,lon`）の両方から施設名を抽出（`google.com`/`google.co.jp`等の`google.*`ドメインに対応）。
  - 発注後の収集状況を**プログレスバーでリアルタイム表示**（`_kz_progress_tracker`、status 10/20/30→33%/66%/100%）。**`@st.fragment(run_every="3s")`** で実装し、進捗カードだけが3秒毎に更新される（旧 `time.sleep()+st.rerun()` はページ全体が毎回作り直されガクついていた）。完了(30)検知で自動DB取り込み→分析画面へ、失敗(40)はエラー表示。
  - **月間上限判定の境界値バグを修正**: `sync_datasets()` の `truncated = len(reviews) >= budget` は、`islice`で既にbudget件に切り詰め済みの`reviews`に対して使うと実質 `len(reviews) == budget` としか判定できず、「ちょうど残枠と同数のレビューしかない（＝本当は全件取得できていた）」ケースを誤って「打ち切り」と判定していた。budget+1件を先読みし、実在するかで真の打ち切りを判定するよう修正（回帰テスト追加）。
  - テスト 159→163。

- **v0.20.0** ヒーロー収集に**テーマ・キーワード探索**を追加（`geocode.discover_by_keyword`）。「和紙」のような**施設の固有名でない語**は Nominatim（名前ズバリ検索）では基本ヒットしない仕様のため、OSMの `name` タグを **Overpass の正規表現検索**で見る別ルートを用意。地域（都道府県等）を指定すると高速・高精度、未指定だと全国対象（公開Overpassサーバのため数秒〜数十秒/失敗しやすい旨を明記）。候補描画は`_kz_candidate_picker` に共通化

- **v0.19.0** ヒーロー収集導線に**発注前プレビュー**を追加：検索した施設名でKAIZODE側の**既存データセット**（データセット名の部分一致、`kaizode.match_datasets`）を自動チェックし、状態（解析完了✅=取り込み可／収集中⏳）を表示。「見えない状態で発注」を防ぐ。これに伴い、ヒーロー発注のデータセット名を固定文字列から**施設名そのもの**に変更（施設名でのマッチングを可能にするため）

- **v0.18.0** ヒーロー検索のKAIZODE収集を**「OSMで実在確認→候補選択→その施設で発注」**に強化（`geocode.search_candidates`）。施設名→OSM/Nominatim候補（名前+住所+🗺️地図リンク）→クリックで**その正確な場所のGoogleマップURL**をKAIZODEに渡す（同名取り違えを低減）。候補が無ければ名前のまま発注のフォールバックも。※精度が要れば将来 Google Places API に差し替え可（UIそのまま・データ源交換）

- **v0.17.0** 最初の検索画面に**KAIZODE収集導線を統合**。施設名を検索→DBに口コミが無ければ「KAIZODEで収集を依頼／完了分を取り込む」を表示（**発注・取り込みはログイン必須**＝費用/枠保護、月間上限の範囲内）。候補があっても完全一致がDBに無ければエクスパンダで収集導線を出す。取り込み後にその施設の口コミが入れば自動で分析対象に。※DBが完全に空のときは「データ登録」ガードが優先（既存データがある状態で機能）

- **v0.16.0** KAIZODE取得に**月間上限（20,000件）＋月間進捗の可視化**を追加。`kaizode_usage`テーブルに当月取得数を記録し、`sync_datasets`が残枠まで(`islice`)で打ち切り（途中停止時はlast_syncを進めず翌月続き取得）。KAIZODE連携ページ上部に進捗バー（今月X/20,000）。上限は`kaizode.MONTHLY_LIMIT`

- **v0.15.0** KAIZODE「収集を発注」で**施設名だけでも発注可能**に（URL未指定の行は `kaizode.maps_search_url()` でGoogleマップ検索URLを自動生成）。KAIZODEは名前検索APIを持たないための対応。取り込みタブに利用上限の注意書きも追加

- **v0.14.0** 分析アウトプットの**冒頭1枚目に免責事項スライド**を追加（プレビュー＝`preview.html_disclaimer`／PPTX＝`report._slide_disclaimer`）。文言は `config.DISCLAIMER_*` に集約し1箇所で編集可

- **v0.13.1** KAIZODE連携で**APIキーに日本語（非ASCII）が入るとページがクラッシュ**（`x-api-key`ヘッダの latin-1 エンコードで `UnicodeEncodeError`）→ `KaizodeClient.__init__` でキーを検証し分かりやすい `KaizodeError` に、UI側もclient生成を try/except で保護。プレースホルダ文字列の貼り付けミスを親切に検出。CIに `pip-audit`（依存の脆弱性スキャン）も追加
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
