# 次の作業

更新日: 2026-09-09。今回の記録: [M0-01 検証記録](M0_01_VERIFICATION_ja.md)。

## M0-01 基準版のリポジトリ移入: PR 作成完了

状態: 基準版移入・検査・GitHub 保存・PR 作成と読み戻し完了。**main 未統合**。
PR: [#1](https://github.com/halc8312/Mindusnista/pull/1)（open、未マージ）。
移入コミット: `efdf3377bf63b372c26b3fc0dbf21c8cbc5f8d51`。
この文書は保存確認後の追記。最新 head SHA は PR から再取得し、上記の移入コミットと区別する。
作業ブランチ: `bootstrap/pythonista-0.1.2`。
現在の main を再取得し、`0e4ff7dfb16eeeacd206c357e6bd89f563e1fe49`、README.md のみ、
開いている PR なしを確認して開始。添付最上位 `Mindusnista/` の中身を直下へ移入した。
本体・テスト・reference・LICENSE は添付とバイト一致し、ゲーム版は 0.1.2-dev のまま。

今回の検査: Linux / CPython 3.12.13、未編集添付のハッシュ58ファイル一致、
未編集添付・移入後とも117 unittest と self-test 成功（失敗・エラー・skip なし）。
ローカルの Python 3.10 は AST 構文検査のみ。
GitHub Actions は Python 3.10.21 / 3.13.15 の実インタープリターで各117本と self-test 成功。
[確認済み CI run](https://github.com/halc8312/Mindusnista/actions/runs/34338852244) の対象は上記移入コミット。
GitHub 保存は通常の git push が認証不足で失敗したため、GitHub 書込機能のコミット作成・非強制 ref 更新で実施。
0.1.2 の実機は引き続き未報告。0.1.1 の起動成功のみユーザー報告あり。

M0-01 で実施した成果物と保存確認項目:
- リポジトリ直下のソース・テスト・資料（ZIP をそのまま1ファイルとして登録しない）。
- 117 tests とセルフテストの新しい実行結果、環境、コード SHA。
- 機能未変更であること、実機未確認の範囲を記した PR。
- `.github/workflows/ci.yml` と、実行済み CI の run / job / 検査ログ。

実施手順（次回は古い添付で再移入しない）:
1. GitHub 内容と書き込み／実行機能を確認。既存 main の変更を上書きしない。
2. 未編集の添付フォルダーで `python tools/verify_handoff.py` を実行。
3. AGENTS と台帳を読み、`python tools/check_project.py` を実行。
4. README だけなら本 README に発展させる。他の内容が増えていたら差分を照合。
5. 作業ブランチへ保存し PR 作成。GitHub からコミットと PR を読み戻して確認。
6. NEXT_TASK の状態・実行記録を更新。main への取り込みはユーザーの承認を待つ。

制約: ゲーム本体を変更しない。版を 0.1.3 に上げない。モジュール分割や新設備追加を混ぜない。
書き込み不可なら、検査済み更新 ZIP と差分を返し「GitHub 未保存」で停止位置を記録する。
手順 2 の checksum は添付受領時だけ。以後、記録を更新すると checksum と変わるのは正常です。
今回は GitHub 保存・PR 作成済み。残件はユーザーによる PR 確認・main 統合と実機試験。

## 次: M0-02 再現可能な配布出力を実装

前提: M0-01 の PR が main に統合済みであることを確認する。
最初の開発タスクとして **コードを実装してテストする**。設計だけで終了しない。

目的: 今後もソースと iPhone 用 `.py` が一致する配布を一つのコマンドで作る。
初回の範囲は本体のコピーとソース ZIP の作成だけ。まだモジュール分割しない。

作る候補: `tools/build_release.py`、`tests/test_release_packaging.py`。
出力: `dist/mindustry_pythonista.py`、版付き source ZIP、SHA256 一覧。

完了条件:
- 依存は Python 標準ライブラリのみ。ユーザーのセーブや外部ソースを自動ダウンロードしない。
- 生成 `.py` と root の本体がバイト一致。生成したファイルでも self-test 成功。
- 同じ入力で ZIP の内容・順序・タイムスタンプが一定。同じ環境で繰り返し作った SHA が一致。
- LICENSE / NOTICE / ソース / テスト / reference / 必要文書を同梱。
- `.git/`、`dist/`、キャッシュ、認証情報、ユーザーセーブ・ログ・個人設定が混入しない。
- 出力先の扱いを検証し、本体やユーザーファイルを消さない。
- unittest と `check_project.py` 成功、新テストを加えた実数を記録。
- 配布の整備のみなのでゲーム処理・保存 schema・操作・ゲーム版は変えない。

## その次

M0-03: 単一ファイル出力のテストを保ちながら、段階的にモジュール分割。
M1-01: 原作固定版に基づく輸送・採掘統合の比較基盤と最初の相違の修正。
実機で再現する不具合が届いた場合は安全な修正を先に行い、予定変更を記録。
