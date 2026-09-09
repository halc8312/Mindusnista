# 引き継ぎ一式の再検査

実施日: 2026-09-09。引き継ぎ元: mindustry_pythonista_dev012.zip。
この作業ではゲーム本体・テスト・抽出 Java 参照を変更していません。

## 受領した 0.1.2 の再実行

- コマンド: `python tools/check_project.py`
- 環境: Linux / CPython 3.13.5
- 結果: 117 unittest 成功、組み込み self-test 成功、終了コード 0。
- Python 3.10: AST 構文検査のみ。3.10 インタープリターでは未実行。
- Java fixture: 既存の 1,504 ケースを再利用。Java 本体の再実行・fixture 再生成はしていない。
- UI: 同梱の scene/ui テストダブルを使用。iPhone・Pythonista・SpriteKit の実行ではない。
- ログ: `docs/handoff-check-results.txt`。

本体 SHA256:
`953ead54eb54bea25c7032cb673d178ef9e61e68880e77ec7382f9ae6a417f2a`

## 新しい資料・設定

README、Work 初回/継続/不具合プロンプト、AGENTS、引き継ぎ・次タスク・ロードマップ、
CI 設定、報告テンプレート、AST コード案内、初回用のマニフェスト検査ツールを追加。
この追加で 0.1.2 の本体が新しい機能を得たわけではありません。

## 別途未実施

GitHub への push・PR・CI 実行、iPhone 0.1.2 の実機起動・回転操作・速度測定は未実施。
GitHub は read-only の確認だけです。0.1.1 の起動成功は以前のユーザー報告です。

## 一式の組み立て後の検査

- 組み立て後の `python tools/check_project.py`: 117 unittest と self-test 成功、終了コード 0。
- 元 ZIP とのバイト比較: 本体・tests・reference・LICENSE の 9 ファイルが同一。
- 全 Python ファイル（追加 helper を含む）の Python 3.10 構文検査: 成功。
- 追加 checksum helper の独立スモーク検査: 9 条件で期待どおり。
  正常、変更検出、欠落、重複、空、親ディレクトリ脱出、絶対パス、Windows 形式、不正ハッシュ。
  この 9 条件は既存の117本とは別で、ゲームの新テスト本数には算入しない。
- Workflow YAML の読み取りと基本構造の検査: 成功。ただし GitHub Actions 自体は未実行。
- Markdown 内の相対ファイルリンクの存在: 成功。

最終 ZIP の再展開検査ログは配布ページの補助ファイル `Mindusnista_Handoff_Final_Check.txt` に出力。
このレポートの後から実施する ZIP 検査は、同ログの実際の結果を参照する。
