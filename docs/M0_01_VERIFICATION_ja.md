# M0-01 基準版移入の検証記録

実施日: 2026-09-09。対象: `halc8312/Mindusnista`。
ゲーム版 **0.1.2-dev**、原作基準 **v159.7**、保存 schema **1** を維持する資料整備・基準版移入。
この記録は今回の再実行結果。`TEST_REPORT.md`、`verification.json`、
`docs/HANDOFF_VERIFICATION.md`、`docs/handoff-state.json` 等は過去の記録として保持する。

## 入力と移入

- 入力: `Mindusnista_Work_Handoff_20260909(1).zip`（提供された添付）。
- ZIP SHA256: `622c8d54d9fa882550fe73dfa9eda730f9cd53e1ebe8ea665e866dfccd4e9ba2`。
- 入力は59ファイル。最上位 `Mindusnista/` の中身をリポジトリ直下へ移入。
  `.github/`、`.gitignore`、`.gitattributes` を含む。ZIP 自体のコミットではない。
- 開始時 main: `0e4ff7dfb16eeeacd206c357e6bd89f563e1fe49`。
  GitHub API と `git ls-remote`、clone 後の履歴・ファイル一覧で再確認。
  `README.md`（`# Mindusnista`）のみ、ブランチは main のみ、open PR は0件。
  新しい本体・利用者の変更は見つからず、README を添付の案内へ発展させた。
- ブランチ: `bootstrap/pythonista-0.1.2`。上記 main から作成。
- 本体 SHA256: `953ead54eb54bea25c7032cb673d178ef9e61e68880e77ec7382f9ae6a417f2a`。

本体・tests・reference・LICENSE・NOTICE・SOURCES・既存検査スクリプト・CI は添付のまま。
新設備、ゲームロジック、操作、起動ガード、旧セーブ、単体 `.py` 構成、GPL 表示、版番号に変更なし。
今回の編集は案内・状態資料への追記と検査記録の追加に限る。
原作 v159.7 の完全コミット SHA は今回検証していない（既存 SOURCES の短縮 SHA を継承）。

## 今回の実行環境

- Linux x86_64: `Linux-6.18.35-x86_64-with-glibc2.39`。
- CPython `3.12.13 (main, Aug 7 2026, 02:25:39) [Clang 22.1.3]`。
- `python`: `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python`。
- Git `2.51.1`。ローカル展開・読取・編集・コード実行・clone が実際に成功。
- ローカルに Python 3.10 と `gh`、`javac` は見つからない。
- `PYTHONDONTWRITEBYTECODE=1` を使用。ログは未編集添付の外側へ保存してから作業ブランチへ収録。

## 検査結果

| 対象 | コマンド | 結果 |
|---|---|---|
| 未編集添付 | `python tools/verify_handoff.py` | 終了0、マニフェスト記載58ファイル一致 |
| 未編集添付 | `python tools/check_project.py` | 終了0、117 unittest、self-test 成功 |
| 移入後 | `python tools/check_project.py` | 終了0、117 unittest、self-test 成功 |
| GitHub Actions / Python 3.10.21 | `python tools/check_project.py` | ジョブ成功、117 unittest、self-test 成功 |
| GitHub Actions / Python 3.13.15 | `python tools/check_project.py` | ジョブ成功、117 unittest、self-test 成功 |

未編集添付・移入後とも unittest は117本、失敗0、エラー0、skip 0。
内訳: engine 54、Pythonista adapter 14、startup regressions 21、rotation controls 28。
self-test は輸送・採掘・保存復元・決定的続行を検査し、117本には加算しない。
Python 3.10 構文検査は本体と tests の `ast.parse(feature_version=(3, 10))`。
Python 3.10 インタープリターの実行試験とは別。上表の GitHub Actions では実際の
3.10.21 / 3.13.15 で実行したことをログの Interpreter 行から確認した。
CI 環境は `Linux-6.17.0-1022-azure-x86_64-with-glibc2.39`、GCC 13.3.0。
CI も各117本、失敗0、エラー0、skip 0。

既存 Java fixture は1,504件（コンベア位置120、受入1,344、乾式採掘40）を3本の
unittest メソッド内で再利用。Java の再実行・fixture 再生成・原作全体の headless 実行は未実施。
本数一致や抽出計算比較を、輸送ワールド全体・原作全機能の互換性の証拠にしない。

証跡: [verification/M0-01-20260909/](verification/M0-01-20260909/)。
`baseline-integrity.txt`、`baseline-check-project.txt` と同名 JSON にコマンド・時刻・終了コード、
`remote-before.json` に開始時のリポジトリ状態を保存。
`import-check-project.txt` / `.json` に移入後の検査、`baseline-comparison.json` に添付との差分一覧と
本体・検査・設定・ライセンスのバイト一致を記録した。
`git diff --cached --check` は終了2。元添付の `history/startup-fix_0.1.1.patch` と
`rotation-controls.patch` にあるパッチ内の空白行等を警告した（`diff-check-original.json`）。
この2件は履歴の原文としてバイト維持し、両パッチを除く差分の空白検査は成功。
`HANDOFF_SHA256SUMS.txt` は元添付の検証専用。今回の文書編集後に固定チェックとして再適用しない。

## GitHub 保存と CI

- 通常の `git push --set-upstream origin HEAD:refs/heads/bootstrap/pythonista-0.1.2` は終了128。
  `could not read Username for 'https://github.com': terminal prompts disabled`。CLI 用の認証手段がない。
- Work の GitHub 書込機能で、開始時 main からブランチ作成、tree / commit 作成、
  `force=false` のブランチ更新に実際に成功。権限表示だけから成功を推測していない。
- 初回移入コミット: [efdf3377bf63b372c26b3fc0dbf21c8cbc5f8d51](https://github.com/halc8312/Mindusnista/commit/efdf3377bf63b372c26b3fc0dbf21c8cbc5f8d51)。
  parent は開始時 main。tree は `b21f770311591e30be4b8ba4a7e4ace8c5029b35`。
  GitHub から commit・branch ref・再帰 tree の69ファイルを読み戻し、検査済みローカル tree と一致。
- PR: [#1](https://github.com/halc8312/Mindusnista/pull/1)。
  `bootstrap/pythonista-0.1.2` → `main`、open、未マージを再取得して確認。
- CI: [run 34338852244](https://github.com/halc8312/Mindusnista/actions/runs/34338852244)、
  `pull_request`、対象 head は上記移入コミット、結果 success。
  `tests (3.10)` job `102424595927` と `tests (3.13)` job `102424595628` の
  完了状態・テストステップ成功・Interpreter 行・117本・self-test 成功を取得。
- `github-import-receipt.json` に読み戻しの要約、`ci-python310-check-project.txt` と
  `ci-python313-check-project.txt` にテスト部分のログ抜粋を保存した。
- 本記録の確定追記は移入コミットより後の文書更新。上記 SHA / CI は明記した対象の記録であり、
  将来の head 全体の CI 成功を意味しない。最新 head と CI は PR から再取得する。
- **GitHub 保存・PR 作成済み、main 未統合**。
  main への直接 push・マージ・強制 push、公開範囲・保護設定の変更は実施していない。

## 実機の状態と次の作業

0.1.1 の起動成功はユーザー報告あり。0.1.2 は実機結果未報告のまま。
PC の scene/ui テストダブルは Pythonista / SpriteKit 実行ではない。
機種・iOS・Pythonista 版、初回起動、旧セーブ復元、方向・二本指操作、画面回転、
保存・再開・バックグラウンド復帰、FPS・負荷は実機で未確認。
実施時は [DEVICE_TESTS.md](../DEVICE_TESTS.md) の手順と端末情報を記録する。

次は main 統合を確認してから M0-02。`tools/build_release.py` と包装テストを実装し、
本体とバイト一致する `.py`、再現可能な source ZIP、SHA256 一覧を生成する。
配布に必要な GPL・資料・テスト・reference を含め、セーブ・秘密情報・ログ等を除外し、
出力先を安全に扱う。詳細な完了条件は [NEXT_TASK_ja.md](NEXT_TASK_ja.md)。今回は未実装。
