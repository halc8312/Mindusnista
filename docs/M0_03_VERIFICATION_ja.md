# M0-03 最初の構造分割と単体生成

実施日: 2026-09-09。ゲーム **0.1.2-dev** / 原作 **v159.7** / 保存 schema **1**。
ユーザーの「マージはあなたの方でしていいので、そのまま進めてください」により、
検証済み PR のマージと続きの実装を進めた。

## M0-01 / M0-02 の統合

現在の head・CI・差分を再取得して確認し、expected head SHA を指定して通常の merge を実施。
PR #1 の統合後、#2 の比較元を main に変更して draft を解除し、差分が M0-02 の23ファイルのままであることを確認した。

| PR | 統合前 head | main へのマージ SHA |
|---|---|---|
| [#1](https://github.com/halc8312/Mindusnista/pull/1) | `285582c667f56a14c4c93f018df5b5a5af696960` | `75c53940181b75514131748c57e9843a6c9b74c1` |
| [#2](https://github.com/halc8312/Mindusnista/pull/2) | `9c02bde5472bbb7ede1ac3705e64743a2faa1211` | `4553462a16c6113dadcbfeea193a1f9f8b2d52a4` |

両 PR の merged=true と main を読み戻し、最新 main から `refactor/transport-kernels` を作成。
基準コミットは `4553462a16c6113dadcbfeea193a1f9f8b2d52a4`。
強制 push・保護設定・公開範囲の変更はしていない。
M0-01 / M0-02 の記録にある「main 未統合」は当時の履歴であり、この統合記録で更新される。

## 変更

- 編集元を `src/mindusnista/app.py` と `kernels.py` に分けた。
- kernels は `ITEM_SPACE` / `BELT_CAPACITY` と `clamp` / `approach` /
  `conveyor_accepts` / `advance_conveyor_positions`。原文の式・順序・注釈を維持。
- 採掘は World・在庫・offload と結び付いているので app に保持。World・保存・起動・UI も変更しない。
- `tools/build_single_file.py` が3箇所の明示した relative imports を定義の原文に置換。
  AST を使って対象を確認し、import / exec / eval でソースを実行することはない。
- root の `mindustry_pythonista.py` はチェックインする生成物。`--check` でずれを検知し、自動修復しない。
  開発者は src を編集して明示的に再生成する。iPhone 配布にパッケージや追加ファイルは不要。
- `check_project.py` が src の Python 3.10 構文検査と生成物整合チェックを行う。
  release builder も同じ snapshot から整合を確認してから配布し、更新忘れは拒否する。
- 配布テストを21→24本に拡張し、単体生成テスト14本を追加。既存ゲームテスト117本は無変更。

生成物は基準コミットの本体と **バイト完全一致**。
SHA256: `953ead54eb54bea25c7032cb673d178ef9e61e68880e77ec7382f9ae6a417f2a`。
従って本体の全 AST、docstring、`_SCRIPT_DIRECTORY`、起動ガード、保存・操作・GPL 全文も維持。
このハッシュは今回の構造分割の証跡で、将来の意図的な開発を固定ハッシュで禁止するテストではない。

## 検査

- 開始前: Linux / CPython 3.12.13、138 unittest と self-test 成功、終了0。
- 実装後: 同環境で `python tools/check_project.py` 成功、**155 unittest（117+24+14）**、
  失敗0・エラー0・skip0、self-test 成功、終了0。
- Python 3.10 AST 構文検査: root / tests / tools / src が成功。ローカル3.10実インタープリターは未提供。
- 分割した kernels と単体生成物で、既存の受入1,344件・移動120件の出力が厳密一致。
  既存ゲームテストの乾式採掘40件も維持。Java 再実行・原作全体互換テストではない。
- ソースパッケージを置かない場所で、Python `-I` の単体 import / self-test が成功。
  __file__ 由来の保存先、scene/ui の遅延依存を維持することも確認。
- 古い生成物の検出、原子的更新の失敗時の旧ファイル保持、symlink 拒否、CLI、
  CI の生成漏れ検出、ZIP の再展開・再生成も検査。

コマンド・時刻・終了コード・原文ログ・今回のバイト比較は
[verification/M0-03-20260909/](verification/M0-03-20260909/) に記録する。

## GitHub 保存と CI

実装コミット [`1b6f43c804d85b6b1ac610f94daf5cc5205df95e`](https://github.com/halc8312/Mindusnista/commit/1b6f43c804d85b6b1ac610f94daf5cc5205df95e) を
作業ブランチに保存し、[#3](https://github.com/halc8312/Mindusnista/pull/3) を main 対象で作成した。
GitHub の commit / branch / PR とローカルの全 tree を比較して一致を確認。
ソース保存は Git Data API、読み戻しは API と git fetch を使用した。

[実装コミットの CI run 34345750467](https://github.com/halc8312/Mindusnista/actions/runs/34345750467) は success。
Ubuntu / CPython **3.10.21** と **3.13.15** の両 job ログから、各 **155 unittest / OK** と
self-test 成功を読み戻した。ローカルの AST 検査とは別に Python 3.10 実行も確認できた。
ジョブ情報とテスト部分のログ抜粋は `github-ci-implementation.json` と `ci-python-*.txt` に保存。

この追記は上記実装コミットの後に行う資料更新。
最終 head の CI を再確認し、明示許可に従い expected head SHA を指定して通常マージする。
このファイル自身のコミット SHA やマージ SHA は自己参照できないため、
最終の統合状態と SHA は PR の merged / merge_commit_sha と main を読み戻して確認する。

## 実機と次の作業

0.1.1 起動成功はユーザー報告あり。0.1.2 の実機起動・方向操作・混在入力・保存復帰・負荷は未報告。
今回の生成物が同じバイト列でも実機成功には昇格させない。
M0 の最小配布・分割を終え、次は M1-01 の輸送統合比較へ進む。
固定タグの完全 SHA と原作ソースを取得し、複数ベルトの毎tick比較と最初の相違を一単位で扱う。
