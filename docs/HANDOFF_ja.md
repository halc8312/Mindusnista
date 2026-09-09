# 開発引き継ぎ — 2026-09-09

以下は初回添付を作った時点の履歴です。M0-01 担当による再確認・検査・保存の最新結果は
[M0-01 検証記録](M0_01_VERIFICATION_ja.md) と [NEXT_TASK](NEXT_TASK_ja.md) を参照。

## ユーザーの希望

Mindustry を iPhone の Pythonista の中で直接編集できる **Python 本体**へ完全移植したい。
Web 版表示やリモートプレイではない。ユーザーは iPhone 中心に Work + GitHub で開発を継続する予定。
目標が大きいことを理由に、単なる似たゲームへ目的をすり替えない。
同時に、部分移植を「完成」「完全互換」と呼ばない。

## ここまでの履歴

| 版 | 変更 | 確認状況 |
|---|---|---|
| 0.1.0 | 採掘・輸送・砲台・敵の最小デモ、保存、Pythonista UI | PC 68 tests と一部抽出 Java 計算比較 |
| 0.1.1 | `_failed` 未初期化エラー対策、起動ガード、保存先フォールバック、最初の例外保持 | PC 89 tests。ユーザーが起動時エラーなしと報告 |
| 0.1.2 | 方向選択列、90度回転、ゴースト、設置済みベルト回転 | PC 117 tests。実機結果は未報告 |
| handoff-20260909 | 本体を変えず Work 用資料・CI・初回検査補助を追加 | docs/HANDOFF_VERIFICATION.md |

実機で起きた初回の `AttributeError: 'MindustryScene' object has no attribute '_failed'` は、
初期化完了前の更新を安全に扱っていなかった。元の初期化が実機で何により中断したかは確定していない。
この修正を消したり、例外を黙って握りつぶす形へ戻さない。

ユーザーが最後に検証したと確認できるのは **0.1.1 の起動**。
0.1.2 の方向操作を便利になったと報告した、全操作が動いた、などと推測しない。
機種、iOS、Pythonista のバージョン、実機 FPS は不明。

## 正式な引き継ぎ元

`mindustry_pythonista_dev012.zip` 内の一式。単体コード SHA256:
`953ead54eb54bea25c7032cb673d178ef9e61e68880e77ec7382f9ae6a417f2a`

この ZIP は、旧開発版フォルダーの内容を継承しています。
`mindustry_pythonista.py`、`tests/`、`reference/`、`LICENSE` は同じバイト列を維持しました。
root の古い SHA256SUMS は `history/SHA256SUMS_0.1.2.txt` に保存。
root の `verification.json` / `TEST_REPORT.md` / `*-results.txt` は **0.1.2 当時の記録**。
今回の再検査と混同しないでください。新しい記録は `docs/HANDOFF_VERIFICATION.md` です。

## リポジトリ確認

GitHub コネクターでメタデータ、直下ファイル、README、main を読み取り済み。
対象: `halc8312/Mindusnista`（公開、default branch: main）。
確認時の main: `0e4ff7dfb16eeeacd206c357e6bd89f563e1fe49`。
内容は `README.md` のみ、本文は `# Mindusnista`。
これは完全にコミットがないリポジトリではありません。通常のブランチ作成と PR の出発点があります。
**次の作業者は現在の状態を再取得すること。確認時の SHA を固定して古い状態を push しないこと。**
今回、このリポジトリへの書き込み・PR 作成はしていません。

根拠となる読み取り先（認証情報・ユーザーのメール等は記録しない）:
https://api.github.com/repos/halc8312/Mindusnista/contents
https://api.github.com/repos/halc8312/Mindusnista/branches/main
https://github.com/halc8312/Mindusnista/blob/main/README.md

## GitHub 連携に関する訂正

前の会話は「この接続にファイル更新・PR 作成機能がある」と説明しましたが、
今回実際に列挙されたアクションは読み取り系のみです。その前の説明を能力の証拠にしないでください。
API が返すユーザーの `push` 権限と、Work が呼べる書き込み機能は別です。
公式ヘルプは通常の GitHub アプリを読み取り専用と説明しています。
Work の実際のツール／認証済み開発環境を最初に確認し、利用できる範囲だけを実施します。

## 実装上の重要点

表示とシミュレーションは同じファイルですが、`World` と計算関数はヘッドレスで使えます。
`make_scene_class` が `scene` / `ui` を注入する境界。自作テストダブルもあります。
保存は原作 `.msav` ではなく独自 schema 1 JSON。原作セーブ互換とは別問題です。
`_SCRIPT_DIRECTORY` は起動時に取得し、コールバック内の `__file__` 有無に依存させません。
回転の変更で `World` の採掘・輸送を再実装しないこと。

ベルトのドラッグ進行方向に応じた自動回転・自動曲がりは未実装。
これは改善候補であり、今回のユーザーが追加を明示した新しい必須仕様ではありません。
操作を変える場合は選択式等の設計を行い、既存工場を横切るだけで回さない性質を保ちます。

## 参照資料

コードの場所: `docs/CODE_MAP.md`。
詳細な対応範囲: `PORT_STATUS.md`。
次のタスク: `docs/NEXT_TASK_ja.md`。
長期ロードマップ: `docs/ROADMAP_ja.md`。
API・原作出典: `SOURCES.md`。GPL: `LICENSE` / `NOTICE.md`。
旧 PC/Codex 向け案内: `DEVELOPMENT_ja.md`（現在の Work 案内は START_HERE を優先）。
