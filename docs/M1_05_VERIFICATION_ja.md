# M1-05 分配器の巡回位置と連続搬送の検証

2026-09-10。基点main `9f466b9f43fd80c172f6e6a7de9db60fac7c004d`、
ブランチ `port/integrated-transport`。0.1.2-dev / Python 3.10互換 / 単体配布 / schema 1を維持。
原作基準はv159.7 / `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。

## 変更と保存

旧実装はRouterの巡回にdump/offload用のcursorを使い、原作のrotationと異なる相手へ搬出していた。
配置時のrotationが1、cursorが0なら、同じ東・北の近隣順でも東へ出してしまう。
原作のrotationを使う検索と、実搬出時の再走査・受入判定前の巡回位置更新へ修正した。
受入済みの品物を処理する `_handle_item` を既存receiveから分離し、通常receiveの受入検査は維持する。
分配器同士の待機、最初の待機相手を飛ばさない条件、普通の入力元への返送も保持する。

旧schema 1のrotation、cursor、router_time、last_inputを破棄・変換せず保持して読む。
今後routerの選択にはrotationを使うため、旧保存の次の搬出先は旧版と変わる場合がある。
新版で保存・復元した後の続行は回帰で照合する。保存の数値範囲・版番号・起動ガード・操作・GPLは変更しない。
表示上の回転更新はベルトだけで、分配器内の品物は中心位置にあるため今回の巡回位置変更で表示は回らない。

## 先行回帰と独立レビュー

Routerの先行7本は修正前に **4失敗・0エラー**、修正後に7本成功した。
無効な試験セットアップによる初期試行は、この有効な先行回帰の本数へ含めていない。
比較器の検査を加えた新規17本は、実受取・明示順・貨物保存・入力の検証、
型と非有限値、不完全な近隣、生産後の品目すり替わり、Java未実行の区別、既存出力保護を検査する。
独立担当が固定原作、最小本体差分、Java抽出、Pythonアダプタ、fixture、許容差をレビューした。

- [有効な修正前の回帰](verification/M1-05-20260910/regression-before.txt)
- [修正直後の7本](verification/M1-05-20260910/regression-after.txt)
- [固定ソースと独立監査](verification/M1-05-20260910/source-audit.md)

## 統合比較の境界

14ケース・985明示更新の小さな配置で、ドリル・ベルト・分配器の実受取処理を接続する。
Python側では58回の外部搬出を観測した。搬出時のsource rotation/cursor、品目・個数・順序、
キャッシュ・在庫・進捗・暖機・入力元を各更新後に比較する。
生産後も品目別に「初期個数＋その品目の生産数＝現在の全貨物」を検証する。
コンベア速度は既定0.046、追加小数0.03、切り分け用の二進値0.125を明記して使う。

連続数値だけ絶対誤差2e-5以内。離散的な搬出時点・品目・個数・順序・rotation/cursorは厳密一致を要求する。
近隣構築、原作scheduler、timer位相、制御router、overflow gate、原作ItemModule全体、全float32、
原作セーブ形式はこの比較の外。元エンジンや実工場全体を実行した証拠ではない。
[原作条件と残差](M1_05_RULES_ja.md)を参照。

## 検査とGitHub

基点はLinux / CPython 3.12.14で309 unittestとself-test成功、失敗・エラー・skip各0。
変更後は **326 unittestとself-test成功**、失敗・エラー・skip各0。
Python 3.10構文・単体同期・配布関連の検査も成功した。ログをまとめて捕捉し、完了行まで確認した。
ローカルJavaの実行可否、ソースhashと実数は同じ検証フォルダーへ記録した。
ローカルに使用可能なJDKはなく、Java比較はGitHub CIのJDK17で実行して結果を読み戻すまで未実行とする。

- [基点の全体検査](verification/M1-05-20260910/before-check-project.txt)
- [基点の環境と本数](verification/M1-05-20260910/before-check-project.json)
- [変更後326本とセルフテスト](verification/M1-05-20260910/after-check-project.txt)
- [変更後の環境・本数・本体hash](verification/M1-05-20260910/after-check-project.json)
- [ローカルJava未実行の実診断](verification/M1-05-20260910/local-java.json)
- [新規17本の検査](verification/M1-05-20260910/regression-final.txt)
- [直前PR #14の実CI・マージ記録](verification/M1-05-20260910/PR14_CI_GITHUB.json)

manifest・単体同期・配布再現性を検査して作業ブランチへ保存し、PRの対象headのCIを確認してマージする。
今回の実head、PR URL、CI URL、merge SHAは作成後に読み戻し、PR本文と配布記録へ保存する。
mainへの直接push、強制push、設定変更は行わない。

0.1.2の実機結果は未報告。起動・操作・連続搬送・旧保存復帰・速度はPythonistaでの確認が必要。
既存1,504件の独立Java計算比較や今回のPC試験を、実機成功・原作全体互換へ読み替えない。
次のM1-06はサイズと配置履歴を含む近隣構築の照合。P-05は別PRで実Worldの測定と標的選択候補を扱う。
