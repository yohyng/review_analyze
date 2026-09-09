"""NMSI / VFFI — 来場体験の満足度指標と、狙いと実来場者の適合度。

外部プロジェクト（facility-review-pipeline）からの移植。VoiceBAUM の
22観点スコアとは**別の指標**であって、置き換えではない。

  NMSI  来場体験を7フェーズ（来訪前/到着/展示/体験/ショー交流/飲食物販/
        退出振り返り）に分け、文ごとの感情×根拠重みでフェーズ効果を出し、
        記憶・再訪推奨・摩擦で補正して 0-100 に写す。   pipeline.py
  VFFI  施設側が置いた「狙い」（特徴量ごとの目標値と重み）と、口コミから
        推定した実際の来場者像とのギャップ。            visitor_pipeline.py

移植したのは DB に触らない計算本体だけ:
    models.py / openai_service.py / pipeline.py / visitor_pipeline.py
元の run_nmsi.py / run_vffi.py は PostgreSQL 直結だったので持ち込まず、
VoiceBAUM の DB から入力を作る部分は source.py に書き直している。

**LLM を使う**。文ごとの属性付け（phase/sentiment/intensity/memory/…）は
OpenAI 互換 API に投げる。22観点スコア（キーワード＋TF-IDF・生成AI不使用）
とは前提が違うので、混ぜて語らないこと。
"""
