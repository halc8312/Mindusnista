# M1-03 定期搬出の統合検証

2026-09-10。統合起点main `6e0c924a6543be815b7fd904c40765a8f445da19`。
ブランチ `port/drill-offload`。0.1.2-dev / schema 1 / Pythonista単体配布を維持。

在庫辞書の挿入順で搬出品を選んでいた処理を、採掘対象の在庫優先、隣接先→品目ID順へ変更した。
`World.dump` の追加とドリルの定期呼出だけを変更し、新しい保存項目は追加していない。
原作の固定SHA、条件、timer・scheduler等の残差は [移植規則](M1_03_RULES_ja.md) に記録した。
UI-01、起動ガード、旧保存の読込、コンベアキャッシュ、GPL、版番号を維持する。

独立着手時の基準は225本。先に9本の有効な回帰を追加して7失敗・2成功を確認した。
先行PR #10の比較器修正を取り込んだ基準は227本で、本タスクの追加18本を含め
**245 unittestとself-testが成功**（Linux / CPython 3.12.14 / NumPy 2.3.5）。
失敗・エラー・skipなし、Python 3.10 ASTと生成同期も成功。独立レビューを実施した。

- [独立着手時の基準](verification/M1-03-20260910/before-check-project.txt)
- [変更前の回帰失敗](verification/M1-03-20260910/regression-before.txt)
- [最終検査の全出力](verification/M1-03-20260910/after-check-project.txt)
- [環境・本数・本体SHA256](verification/M1-03-20260910/result.json)
- [ローカルJava診断とPython trace](verification/M1-03-20260910/local-java.json)

抽出Java参照は14シナリオ・49明示呼出し。在庫、cursor、選択品、受入試行順と結果を完全一致で比較する。
受取先は同じ受入表を使う試験用処理で、原作の工場全体の実行ではない。
実際のWorldのドリル・ベルト・分配器・デュオ等による保存・再開・貨物保存はPython回帰に分けて検査した。
ローカルはjavac不在とjavaのlibjli.so不足によりJava比較未実行、終了コード2。
CIにはJDK17でこの比較を実行するstepを追加した。対象headの結果を読み戻してPR本文へ記録する。
従来のコンベア抽出比較20ケース・59更新と、1,504件の独立式比較も継続する。

旧保存の読込時点では在庫・cursor等を変更せず、その後の定期搬出が新しい規則で進む。
旧版と新版のゲーム進行が同じという保証ではない。原作msavの共有やPythonista実機の成功とも区別する。
次のM1-04は生産offloadの受入・在庫復帰・cursorと更新順の比較を扱う。
