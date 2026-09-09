# 次の作業

更新日: 2026-09-09。ゲーム 0.1.2-dev / 原作基準 v159.7 / 保存 schema 1。

## M0-01: 基準版移入の PR 作成済み

[PR #1](https://github.com/halc8312/Mindusnista/pull/1) は今回の開始時も open・未マージ。
基準版 head は `285582c667f56a14c4c93f018df5b5a5af696960`、main は
`0e4ff7dfb16eeeacd206c357e6bd89f563e1fe49`（README.md のみ）。
M0-01 の検証・保存の履歴は [M0_01_VERIFICATION_ja.md](M0_01_VERIFICATION_ja.md)。
古い添付から再移入しない。次回も現在の main・PR・作業ツリーを再取得する。

## M0-02: 再現可能な配布出力

ユーザーの継続依頼により、M0-01 の main 統合待ちの間に、保存済み head から
`build/reproducible-release` を作り先行実装した。基準版ブランチを対象とする依存 PR として提示する。
main 統合という元の前提が完了したとは扱わず、main への直接 push・マージ・強制 push はしない。

実装済み:

- `tools/build_release.py`: 標準ライブラリで単体 `.py`、版付きソース ZIP、SHA256 一覧を生成。
- `tools/release_files.txt`: 配布対象の明示一覧。私用・生成物の既知のパスを拒否。
- `tests/test_release_packaging.py`: 本体バイト一致、再現性、再展開後の再ビルド、既存データ保護等の回帰試験。
- `tools/check_project.py`: tools も Python 3.10 の AST 構文検査に含める。
- [配布手順](RELEASE_ja.md) と [M0-02 の検証・保存記録](M0_02_VERIFICATION_ja.md)。

ローカル検査: Linux / CPython 3.12.13、138 unittest（既存117 + 配布21）と self-test 成功。
生成 `.py` の self-test と、ZIP 展開後の再ビルド同一性も成功。
GitHub 保存・[ドラフト PR #2](https://github.com/halc8312/Mindusnista/pull/2) 作成・読み戻し済み。
実装コミット: `55224adab4433250c31b3fd5b67ced97a63d63bd`。
[確認済み CI run](https://github.com/halc8312/Mindusnista/actions/runs/34341672730) では
Python 3.10.21 / 3.13.15 の各138本と self-test 成功。本記録はその後の資料追記。
最新 head は PR で再取得し、未マージ・main 未統合という状態と区別する。
本体・既存ゲームテスト・reference・GPL・版番号・操作・schema は変更していない。
配布 `.py` の PC self-test と Pythonista 実機成功は別。0.1.2 の実機結果は引き続き未報告。

## 次: M0-03 最初の小さな構造分割

前提: M0-01 → M0-02 の順に main へ統合されたことを確認する。
基準版 PR が先に統合された場合、M0-02 の比較元を main に変更し、差分・CI を確認する。
未統合の依存 PR を「完了済み main」として扱わない。

目的: 編集元を少しずつ整理しながら、iPhone には引き続き一つの `.py` を渡す。
M0 を際限なく拡張せず、分割の最小単位を終えたら M1 の輸送・採掘移植へ進む。

最初の実装内容:

- `docs/CODE_MAP.md` と実コードを確認し、独立した輸送・採掘の純粋計算関数等から一単位を選ぶ。
- 編集元を一つに保ち、決定的な単体ファイル出力を生成する。二つの手編集本体を作らない。
- ゲーム挙動・定数・保存 schema・起動ガード・操作を変えず、構造の変更だけにする。
- 配布一覧と builder を更新し、生成物でも既存ゲームテストと self-test を実行する。
- 旧セーブ続行、単体 import、Pythonista adapter の模擬試験、配布再現性を維持する。
- 変更前後の実行結果・本数・環境・原作と未互換の範囲を記録し、一つの PR にまとめる。

その次は M1-01: 固定版に基づく輸送・採掘統合の比較基盤と最初の相違の修正。
原作の完全コミット SHA と対象ソースを確認し、抽出 fixture と原作本体実行の証拠を区別する。
実機で再現する不具合報告が届いた場合は、その回帰試験と安全な修正を先に行い予定変更を記録する。
