# AGENTS.md

VoiceBAUM（クチコミ分析 → HTML/PPTX レポート）で作業する AI エージェント向けの指示。

**このファイルが正。** `CLAUDE.md` など各ツール向けのファイルは、ここへの転送だけを書く。
設計の背景と全体像は `HANDOFF.md`（296行）にある。作業前に該当節を読むこと。

---

## 0. 会社規程

このリポジトリは**利用部門システム開発管理細則**の適用対象。ルールは R-001〜R-015 に
構造化されている（NOMURA AI Guardrail Package）。

**本体はまだこのリポジトリに置いていない。** リポジトリが public のままなので、
社内規程を置くとそれ自体が公開されてしまうため。private 化後に `docs/guardrail/` へ
配置し、ここからの参照に差し替えること。それまでは担当者から受け取ること。

特に効いてくるもの:

- **R-002 入力禁止情報** — 個人情報・自社秘密情報をコミットしない。§3 を参照
- **R-005 認証情報保護** — APIキーを直書きしない。鍵は env / secrets / セッション入力のみ
- **R-008 第三者レビュー** — AI生成コードは人間のレビューを要する。AI同士のレビューは代替にならない
- **R-015 AI開発記録** — どのAIが何をしたかを残す。§5 を参照

判断に迷ったら、勝手に決めずに WARNING として人間に投げる。

---

## 1. 環境構築（ここで必ず詰まる）

```bash
python3 -m pip install -r requirements.txt   # ← pip ではなく python3 -m pip
python3 -m pytest -q
streamlit run app.py
```

**`pip install` は使わないこと。** このコンテナでは `pip` が Python 3.13 を、
`python3` が Python 3.11 を指している。`pip install` すると別の処理系に入り、
`ModuleNotFoundError: No module named 'numpy'` で全テストが collection error になる。

依存は `requirements.txt` に**バージョン固定**されている。上げるときは意図的に上げて
`python3 -m pytest -q` を通すこと。

DB は `TURSO_URL` + `TURSO_TOKEN` があれば Turso、無ければローカル `data/reviews.db`。

---

## 2. 壊しやすい場所（実際に壊した記録）

### 生HTMLは `src/ui/markup.py` の `html()` を通す

```python
from src.ui.markup import html as _html
_html(markup)          # ◯
st.html(markup)        # ✗ SVG が丸ごと消える
st.markdown(markup, unsafe_allow_html=True)   # ✗ <style> が途中で切れる
```

`st.html()` は `<svg>` を削除する。同じ文字列を両経路に流して DOM を数えた実測:

```
st.html()                           svg 0 / line 0 / rect 0 / polyline 0
st.markdown(unsafe_allow_html=True) svg 1 / line 1 / rect 1 / polyline 1
```

これでレーダーチャートと時間軸の棒グラフが全部消えた。マーカーは HTML の `<span>` なので
生き残り、「点だけ浮いていてグラフが無い」という気づきにくい壊れ方をする。

`st.markdown` 直叩きも不可。Markdown は空行で HTML ブロックを終わらせるので、
`<style>` が途中で切れる（6,049文字中 2,113文字で切れた実績あり）。
`markup.html()` は `flatten()` で1行に潰してから渡すことで両方を回避している。

`tests/test_markup.py` が `src/` 配下の `st.html(` を検出して落とす。

### Turso にトランザクションは無い

`conn.commit()` は何もしない。1文 = 1往復。DELETE→INSERT の間に落ちると中途半端に残る。
冪等な `INSERT OR REPLACE` を1文で撃つこと。100文ずつのバッチ送信なので、
失敗時は「途中まで入っている」が正しい。

### Streamlit のウィジェットは key を変えないとリセットされない

`session_state` からキーを消しても戻らない。`st.rerun()` はフロント側が持つ値を
送り直してくる。**key 自体を変えて別ウィジェットにする**のが唯一の方法
（`src/ui/analysis_mode.py` の `peer_widget_key()` が実例）。

### Google Places の規約がデータ設計を縛る

無期限に保存してよいのは `place_id` だけ。写真・名称・評価・レビュー本文は都度取得。
PPTX への焼き込みは再配布にあたるので不可。詳細は `src/places.py` 冒頭。

### 22観点スコアは日本語専用

キーワード辞書ベースなので、英語・中国語のクチコミでは**全22観点が完全に同値**になる
（実測: 感情の幅 0.000 / 言及度は一様 1/22）。日本語でも文の 76% は感情語に当たらず
中立 0.5 で埋まる。スコアが平坦なときは、まずデータの言語を疑うこと。

---

## 3. コミットしてはいけないもの

**このリポジトリは過去に public で個人情報と社外秘資料を公開した。** 同じことを繰り返さない。

```
data/**/*.csv*          実在レビュアー氏名を含む（24,404人分が公開された）
docs/design/*.png       confidential 印字の社内資料（公開された）
.streamlit/secrets.toml APIキー
*.db                    取り込み済みデータ
```

`samples/make_sample.py` には実在の氏名と Google 寄稿者URLが直書きされている。
サンプルを再生成するときは架空データに置き換えること。CSV だけ直しても復活する。

**新しいデータファイルを追加する前に、中身に個人情報が無いか確認すること。**

---

## 4. テストと検証

- 変更したら `python3 -m pytest -q` を通す。全件 green でないものはコミットしない
- **UI の変更はテストだけで確認しない。** 上に挙げた不具合はどれもテストを通過していた。
  Playwright で実際に描画して DOM を数えるか、スクリーンショットを撮ること
  （Chromium は `/opt/pw-browsers/` にある。`playwright install` は不要）
- 回帰を見つけたら、再発を検出するテストを同じコミットに入れる

結合テストは手薄。`scripts/` 配下はテストが無い。

---

## 5. コミットの作法

**どの AI が書いたかを記録に残すこと（R-015）。** 現状、全コミットが単一の名義になっており、
複数エージェントが混ざると記録として使えなくなる。

```
Co-Authored-By: <エージェント名> <アドレス>
```

メッセージは**何をしたか**ではなく**なぜそうしたか**を書く。壊れていた理由、
再現した手順、実測値を残す。既存のコミットログがその形になっている。

モデル名やバージョンをコード・コメント・コミットに埋め込まないこと。

作業ブランチは `claude/serene-babbage-nxvus`。**これが現在の default branch** であり、
ここへの push は本番デプロイ元に直接入る。審査フローが未整備なので、
大きな変更は人間の確認を挟むこと。

---

## 6. 書くときの作法

- コメントは**なぜ**を書く。何をしているかはコードを読めば分かる
- 既存コードの密度・命名・語り口に合わせる。日本語コメントが基本
- 推測で断定しない。確認していないことは「未確認」と書く
- 失敗したら隠さない。テストが落ちたらその出力ごと報告する
