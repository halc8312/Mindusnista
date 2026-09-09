# Work で最初に確認する能力

## M0-01 での実測（2026-09-09）

添付の展開・編集、CPython 3.12.13 実行、GitHub API の読取、git clone / fetch は成功。
通常の git push は CLI 認証手段なしで失敗（終了128）した。
別途 Work の GitHub 書込機能で branch / tree / commit 作成と非強制 ref 更新が成功し、
[PR #1](https://github.com/halc8312/Mindusnista/pull/1) を作成・再取得した。
GitHub Actions は Python 3.10.21 / 3.13.15 で各117本と self-test 成功を実際に確認。
この会話には Pythonista 実機を実行する手段はなく、0.1.2 実機は未報告。
詳細・根拠は [M0-01 検証記録](M0_01_VERIFICATION_ja.md)。
以下の一般的な案内・初回添付時の履歴から、将来の能力を断定しないこと。

## 次回も確認する項目

この引き継ぎでは特定モデルの利用可否を前提にしません。
Work が実際に提供するツールと認証を調べ、次の状態を分けて報告します。

| 能力 | 初回に確かめる方法 | 未提供なら |
|---|---|---|
| GitHub 読み取り | README、ブランチ、最新コミットを取得 | 認可対象のリポジトリを確認し、添付を基準に可能な範囲を検査 |
| 添付展開・編集 | ZIP の一覧とソースの読み取り、ローカルファイル編集 | ファイル操作が使える作業環境が必要と明記 |
| Python 実行 | check_project.py の実行結果と終了コード | 未実行と明記し、テスト済みと呼ばない |
| GitHub 書き込み | 対応アクション／認証済み環境を確認し、依頼されたブランチに実際に保存 | ZIP/差分まで返し、GitHub 未保存と明記 |
| PR 作成 | PR を作り、再取得して対象ブランチと commit を確認 | 保存先と未作成を分けて報告 |
| CI | 実際の run とジョブ結果を取得 | 設定済みと実行済みを区別 |
| iPhone 実機 | ユーザーの報告、または実際に提供された実機手段 | 模擬テストを実機と呼ばない |

通常の ChatGPT GitHub アプリは公式説明では読み取り専用です。
Codex は GitHub に接続するコード作業の別の選択肢です。
同じアカウントであること、モデルが高度であることだけでは、ツール権限は増えません。
AGENTS.md をエージェントが自動読み込みするかにも依存せず、初回プロンプトで読むよう明示します。

参考（2026-09-09確認）:
https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt
https://developers.openai.com/codex/cloud/
https://developers.openai.com/codex/guides/agents-md/
