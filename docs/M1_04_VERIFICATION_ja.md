# M1-04 生産offloadと全完了数の検証

2026-09-10。基点main `004f2ec4fb6a205f4be5a49d0cb4119f52c5ed24`、
ブランチ `port/drill-production-offload`。ゲーム0.1.2-dev / schema 1 / 原作v159.7を維持。

生産品の搬出先・cursor・全拒否時の在庫追加、複数完了時の貨物保存、最後の進捗剰余を修正した。
容量超過在庫をドリルだけ厳密な正整数として保存復元する。新しい保存フィールドはない。
最初の全拒否より後は同じ結果になる残数をまとめ、個数やゲーム機能を切り捨てない。
[原作条件・集約の根拠・未対応範囲](M1_04_RULES_ja.md)を参照。

## ローカルで実行した検査

Linux x86_64 / CPython 3.12.14 / NumPy 2.3.5。
変更前は265 unittest、変更後は**287 unittestとself-testが成功**、失敗・エラー・skip各0。
Python 3.10のAST構文と単体生成同期も成功。3.10実行そのものはCIで別途確認する。
追加22本は実Worldの17本と比較器5本。修正前の有効な15本では10失敗・1エラー・4成功だった。
そのエラーは、期待した容量超過在庫の復元を旧readerが拒否したもの。修正前の失敗を成功には数えない。

- [変更前の全体検査](verification/M1-04-20260910/before-check-project.txt)
- [修正前回帰](verification/M1-04-20260910/regression-before.txt)、[修正後22本](verification/M1-04-20260910/regression-after.txt)
- [変更後の全体検査](verification/M1-04-20260910/after-check-project.txt)、[環境と本数](verification/M1-04-20260910/result.json)
- [前mainの実コードが作った保存の継続](verification/M1-04-20260910/previous-main-save.json)

前mainの単体コードで合成デモを500tick進めて作った保存を、新コードが全フィールドを変えずに読めた。
新コードで実際に保存・再読込し、さらに500tickの続行状態が一致した。ユーザーの実セーブではない。
既存保存の読込と、容量超過を含む新しい保存を旧スクリプトで読めるかは別で、後者は保証しない。

## 独立レビューと原作抽出比較

別担当が固定原作を再取得し、app・保存検証・Java抽出・比較器をレビューした。
Counterの空在庫判定とfixture名の不一致も、最終検査前に修正・再確認した。
[独立監査記録](verification/M1-04-20260910/source-audit.md)を保存する。

一括加算は、48通りの実Worldを使い、すべての品を実際にoffloadする逐次版と比較した。
逐次版の合計883回について、貨物だけでなくWorld全体のdigestが一致。
[結果](verification/M1-04-20260910/review-aggregation-result.json)と
[再実行用コード](verification/M1-04-20260910/review-aggregation.py)を保存した。

```sh
python docs/verification/M1-04-20260910/review-aggregation.py .
python tools/check_offload_reference.py
```

抽出比較は**22ケース・44明示呼出し**。直接offloadは全試行、生産tickは最終状態・定期dumpと
最初のoffload試行・進捗処理順を照合する。Java側は小さいfixtureで元の生産ループを実行する。
集約で省いた反復の呼出回数や、原作工場のscheduler全体を比較したという意味ではない。
ローカルはJDK不備でexit 2、Javaは未実行。Python trace検証のみ成功した。
[未実行を含む実記録](verification/M1-04-20260910/local-java.json)。

CIには3.10側でこの比較を追加し、コンベア20ケース・59更新、定期dump14ケース・49呼出しも継続する。
対象headのCIログを読み戻してからマージし、実SHA・PR URL・CI結果をPR本文へ記録する。

## 配布と未確認事項

本体SHA256: `bfd9606bb178016c2324e40378109dde32569c517fa25f256868d0751ab10fca`。
単体ファイルはsrcから再生成し、配布manifestを更新する。GPL、起動ガード、UI-01、版番号を維持。

Pythonistaの実機、全原作工場、float32全体、Java int32オーバーフロー、原作msav交換、
campaign production、任意MOD・副作用付き受入、近隣形成・timer位相・schedulerは未確認／未対応。
大きい完了数の算術検査をiPhone性能へ換算しない。0.1.2の実機成功は未報告。
次はM1-05で、実際の受取処理も含むドリル・ベルト・分配器の連続tick抽出比較を進める。
