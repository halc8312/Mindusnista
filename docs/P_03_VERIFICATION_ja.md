# P-03 配列に継続状態を持つ比較器の統合検証

2026-09-10。統合起点main `cebaa2b1584ab1dbd1a4e228a2ad663d9c57ce93`、
ブランチ `tools/array-state-probe`。ゲーム本体はM1-03とバイト不変、0.1.2-dev / schema 1。

単体 `tools/pythonista_array_state_probe.py` を追加した。
Python行リストとNumPy配列に同じ位置・速度・ID等を保持し、全件を毎tick更新して全結果を返す。
毎回全入力をリストから受け取るP-02とは別の仕事で、両タスクの所要時間の比を改善倍率には使わない。
今回の範囲と全費用は [比較モデルと実測](P_03_PROBE_ja.md) に記録した。

20本の新規回帰が成功し、独立レビューも実施した。レビューで発見した比較例外時の記録件数のずれは
失敗回帰を先に確認して修正した。以下の正式測定は修正後の同じSHA256の比較器で再実行したものだけを使う。

- [修正前の回帰](verification/P-03-20260910/before-comparison-record-fix.txt)
- [修正後の20本](verification/P-03-20260910/after-comparison-record-fix.txt)
- [20,000件の正式測定](verification/P-03-20260910/pc-20000.json)
- [200,000件の正式測定](verification/P-03-20260910/pc-200000.json)
- [実行コマンド・終了コード](verification/P-03-20260910/commands.json)
- [統合後の全体検査](verification/P-03-20260910/after-check-project.txt)
- [環境・本数](verification/P-03-20260910/after-check-project.json)
- [統合起点・本体一致・測定コード一致](verification/P-03-20260910/scope.json)

Linux / CPython 3.12.14 / NumPy 2.3.5。M1-03の245本に新規20本を追加した
**265 unittestとself-testが成功**、失敗・エラー・skipなし。Python 3.10 ASTと単体生成同期も成功。
ID精度、bool/float/intの型、全件一致、非alias、配列所有、初期/途中例外、欠如・壊れたimport、
CLIと既存出力保護、実際のJSON encode/decode/復元直後と3tick続行を確認した。

正式測定は各件数・4条件それぞれ初回1＋warmup1＋steady5tick、同一JSON保存復元を1回、復元後3tick。
全ID・位置・距離・真偽値と保存bytesのdigestが一致した。200,000件のtick中央値はPython74.904ms、
NumPy4ワーカー15.430ms。NumPy4の初期準備250.870msと、保存復元1,400.563msも記録した。
7tickで1回保存復元する比較条件の償却は252.597ms/tick。単純なtick中央値と混同しない。
実際のディスクI/O、復元後3tick、終了処理はこの償却の外で、測定区間は詳細資料へ明記した。

前PR #11のCIとJavaの全dump traceも検証資料へ保存した。新しいPRでは対象headのCIを読み戻し、
実際の結果とSHAをPR本文へ記録する。コンベア20ケース・59更新、dump14ケース・49呼出しの抽出比較も継続する。

Pythonista実機、原作float32、生成・削除を含む実ゲーム、原作保存互換、ピークメモリ、持続負荷は未確認。
このモデルでの改善をゲーム本体のFPSへ換算しない。機能・規模・効果の要件を削減する変更はない。
次はP-04で生成・削除・外部コマンドを扱う状態管理、S-01で原作msavの読取診断を別の単位にする。
