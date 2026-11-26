# 名古屋市科学館レポートの作業スクリプト

経緯と残作業は `docs/handoff-nagoya.md` を参照。

**データ（xlsx）はここに置かない。** 実際の口コミ本文を含むので、
リポジトリが公開のうちはコミットしない。スクラッチパッドの
`nagoya_data/` に置いて使う。

```bash
SCR=<scratchpad>
VOICEBAUM_DB=$SCR/nagoya.db python3 -I scripts/nagoya/nagoya_import.py   # 初回のみ
VOICEBAUM_DB=$SCR/nagoya.db python3 -I scripts/nagoya/nagoya_report.py
```

`nagoya_texts.py` は Claude Code がこの場で執筆した文章。LLM は呼ばず、
ここの文字列を `slide_summaries` に流し込んでいる。
