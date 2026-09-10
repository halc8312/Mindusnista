# P-02 途中例外時の照合記録を修正

2026-09-10。PR #9 のレビュー指摘を再現して修正した。
起点main: `1e0af04b00d4eee8c2c1a9a8fde7a216cd027351`。

`measure_frames` がrunner呼出前に照合用digestを追加していたため、途中例外でそのframeの
計測標本を作れない場合、digestだけ1件多く残っていた。digestは計測標本を追加した時にだけ記録する。
数値が不一致でも計測標本があるframeはdigestを残す。計算・入力更新・計測区間は変更しない。
過去のP-02成功測定にはこの失敗経路を通ったものはなく、過去の測定記録は書き換えない。

追加2メソッドで、最初/3番目のrunner例外と比較中の例外を検査した。修正前は計16メソッドのうち
3 subtest失敗を確認。修正後の全体はLinux / CPython 3.12.14 / NumPy 2.3.5で
**227 unittestとself-test成功**、失敗・エラー・skipなし。Python 3.10 ASTと単体生成同期も成功。

- [変更前の全体検査](verification/P02-error-records-20260910/before-check-project.txt)
- [修正前の回帰失敗](verification/P02-error-records-20260910/regression-before.txt)
- [修正後の全体検査](verification/P02-error-records-20260910/after-check-project.txt)
- [環境・本数・本体一致](verification/P02-error-records-20260910/result.json)

ゲーム本体はバイト不変、0.1.2-dev / schema 1 / GPL / UI-01を維持。実機未実施。
ユーザーの継続開発・検証後マージの許可もAGENTSとNEXTへ記録した。
GitHubへ保存後、対象headのCIとPR情報を読み戻し、実際のSHA・結果をPR本文へ記録する。
