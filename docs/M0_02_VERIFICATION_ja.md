# M0-02 再現可能な配布出力の実装記録

実施日: 2026-09-09。ゲーム 0.1.2-dev / 原作 v159.7 / 保存 schema 1。
基準コミット: `285582c667f56a14c4c93f018df5b5a5af696960`。
ブランチ: `build/reproducible-release`。

## 開始時と今回の範囲

開始時に GitHub を再取得し、PR #1 が open・未マージ、main は
`0e4ff7dfb16eeeacd206c357e6bd89f563e1fe49`、基準版ブランチは上記コミットであることを確認。
ユーザーの「開発をしばらく続けてください」という継続依頼により、main 統合待ちの間に
PR #1 の head から別ブランチで M0-02 を先行実装する。main 統合済みとは扱わない。
PR は基準版ブランチに依存する形で提示し、main への直接 push・マージは行わない。

編集元とバイト一致する `.py`、再現可能な source ZIP、SHA256 一覧を一つのコマンドで作る。
`tools/build_release.py`、配布対象一覧 `tools/release_files.txt`、配布テストを追加。
`check_project.py` の Python 3.10 構文検査対象に tools を含める。
本体・既存ゲームテスト・reference・GPL・版番号は維持。モジュール分割やゲーム機能追加は今回の範囲外。
操作方法と出力先の保護は [RELEASE_ja.md](RELEASE_ja.md) を参照。

## 検査

開始前: Linux x86_64 / CPython 3.12.13、`python tools/check_project.py` 終了0。
117 unittest（失敗0・エラー0・skip0）と self-test 成功。
実装後: 同じ Linux / CPython 3.12.13 で `python tools/check_project.py` 終了0。
**138 unittest（既存117 + 配布21）、失敗0・エラー0・skip0、self-test 成功**。
本体・tests・tools の Python 3.10 AST 構文検査も成功。ローカルに3.10実インタープリターはない。

配布テストでは本体・GPL・参照・資料の同梱、生成 `.py` のバイト一致と実際の self-test、
ファイル順・日時・権限の固定、ソース mtime / 権限 / 出力場所が変わっても同一の配布、
Git のない ZIP 展開先での再ビルド、任意 cwd からの CLI、既存出力の無変更・衝突時の拒否、
私用ファイルの除外・シンボリックリンク拒否を確認した。

独立レビューで見つかった大小文字が衝突するパスと `VERSION +=` の誤受入は、
修正前に20本中2失敗を再現し、修正後20本成功。その後、出力先が並行作成されたときの
user-save 内容・mtime 保持を検査する1本を加え、最終21本となった。
出力先は新規ディレクトリを排他的に確保し、各ファイルを新規作成専用で書き、
checksum を最後に書く。I/O 失敗では部分生成が残り得るが、既存ファイルを消去しない。

コマンド・開始終了時刻・結果と修正前後ログは
[verification/M0-02-20260909/](verification/M0-02-20260909/) に保存。
`unchanged-runtime.json` は本体・既存ゲームテスト・reference・ライセンスの11ファイルが
基準コミットと同一であることを記録している。
配布 ZIP を展開した Git のないソースでも `python tools/check_project.py` を実行し、
138本と self-test 成功を確認（`unpacked-check-project.txt`）。
GitHub Actions でも Python **3.10.21 / 3.13.15** で各138本と self-test 成功。
環境は Linux-6.17.0-1022-azure-x86_64-with-glibc2.39 / GCC 13.3.0。
ジョブ状態に加え Interpreter 行・テスト実数・self-test のログを取得した。

## GitHub 保存

- 実装コミット: [55224adab4433250c31b3fd5b67ced97a63d63bd](https://github.com/halc8312/Mindusnista/commit/55224adab4433250c31b3fd5b67ced97a63d63bd)。
- tree: `cbd704190ddcecb264148f70e020a0e7b64d821a`。保存後に commit と branch ref を読み戻し、
  git fetch した内容とローカルの全 tree が同一であることを確認した。
- PR: [#2](https://github.com/halc8312/Mindusnista/pull/2)、open / draft / 未マージ。
  `build/reproducible-release` → `bootstrap/pythonista-0.1.2`。PR #1 に依存する。
- CI: [run 34341672730](https://github.com/halc8312/Mindusnista/actions/runs/34341672730)、上記実装コミット、success。
  Python 3.10 job `102433656514` / Python 3.13 job `102433656741`。
- 前回と同じ GitHub 書込機能によるコミット作成・非強制 ref 更新で保存。CLI の認証情報は求めていない。
- `github-implementation-receipt.json` に読み戻し要約、`ci-python310-check-project.txt` /
  `ci-python313-check-project.txt` にテストログ抜粋を保存した。
- 本記録の確定追記は実装コミットより後の資料変更。最新 head とその CI は PR から再取得する。
  **M0-01 / M0-02 とも main 未統合**。main への直接 push・マージ・強制 push は実施していない。

本体 SHA256（変更しない基準）:
`953ead54eb54bea25c7032cb673d178ef9e61e68880e77ec7382f9ae6a417f2a`。

PC のテストダブルや配布検査は実機試験ではない。0.1.2 の起動・操作・保存復帰・負荷は未報告。
1,504件の抽出 Java fixture は既存のものを再利用し、Java 再実行・原作全体互換の試験にはしない。

## 次の作業

M0-01 → M0-02 の順に main へ取り込まれたことを確認し、M0-03 の最初の小さな構造分割へ進む。
配布の再現性と単体実行テストを維持し、ゲームロジック変更は別の PR とする。
