# M1-01 コンベア引渡し順序と抽出参照

2026-09-10。起点 main: `3e3cc5cd8019849b7504d5299ea40f3569ae1dc4`。
ブランチ: `port/conveyor-handoff`。0.1.2-dev / 原作 v159.7 / 独自保存 schema 1 を維持。

## 確認した問題と修正

先頭の荷物が隣のコンベアへ渡った後、後続の荷物は空いた空間へその tick 内で進める。
従来は全品の位置を計算してから引き渡していたため、すでに移った先頭に後続が制限されていた。
通常速度 .046、後続 copper の y=.58、先頭 lead の y=.99、出力先が空の直列2本を使うと、
原作の更新順から導いた後続位置は **.626**、従来実装は **.600** になる。

`World._tick_conveyor` を、前方の品から「移動→受入判定・引渡し→削除」の順に進めるよう修正。
次の品の移動時には、引渡し後の品数を使う。隣のベルトの間隔制約、横位置の引継ぎ、
受入失敗時の停止は維持する。純粋な移動計算カーネルは変更せず、統合処理の順序だけを直した。
新設備、採掘、全体の建物更新順、操作、保存フィールド、版番号は変更していない。

## 参照と比較範囲

固定原作 SHA: `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。
[Conveyor.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Conveyor.java)
の `updateTile`、`pass`、`acceptItem`、`handleItem`、`add` を確認した。

開発用 `reference/ConveyorTransferReference.java` は、これらを最小の Java 環境へ抽出・改変した参照。
`tools/check_conveyor_reference.py` は fixture に指定した入力と更新順を両方へ渡し、各更新後の
品名・順序・個数は完全一致、x/y は絶対誤差 **2e-6** 以内で比較する。
Java は float、Python は倍精度。今回の公差を全ゲームや通信の許容値にはしない。

11シナリオ・22回の明示更新。直列の4方位、A→B / B→A の順、出口停止、隣のベルトとの間隔、直角、向かい合わせ、
側方→後方の搬入を対象とする。fixture の初期 minitem と mid の条件も記録する。
一致しても、原作本体の実行や entity scheduler 全体の互換性は証明しない。

## 回帰と実行結果

変更前基準: Linux / CPython 3.12.14、172 unittest と self-test 成功。
新しい回帰は修正前に7メソッド中10件の subtest failure を再現し、修正後は7メソッドすべて成功。
修正前の unittest 出力は行末空白のみ除去して保存した。
4方位、詰まり、曲がり、明示更新順、品の保存、schema 1 の保存再開を検査した。
変更後の全体検査は **179 unittest と self-test 成功**、失敗・エラー・skipなし。
実本数・環境・終了コードは [検査記録](verification/M1-01-20260910/after-check-project.json)、
[全出力](verification/M1-01-20260910/after-check-project.txt) に保存する。

この Work 環境の `java --version` は `libjli.so` 不足で実行不能、`javac` も利用できない。
ローカル Java 比較は未実行。GitHub CI の Python 3.10 側へ JDK 17 と比較コマンドを追加し、
実際の head に対する結果を確認して PR に記録する。Java は開発時だけで、iPhone の起動依存にはしない。

```sh
python tools/build_single_file.py
python tools/check_project.py
python tools/check_conveyor_reference.py
python tools/build_release.py --output dist/m1-01
```

## 残る相違と次の単位

- 原作 minitem は更新時に作るキャッシュで、handleItem は更新しない。現実装は受入のたびに最小位置を計算する。
  同じ tick で後方→側方の順に搬入する場面等の判定に差がある。
- 原作 mid は更新ループで求める挿入位置。現実装の追加後 sort と一般に同値とは確認していない。
- 固定版の lastInserted は通常の初期値0で、handleItem/addでは書き換えられない。
  今回の前方搬送で使う index0 を独自に一般化しない。
- チーム、sleep/noSleep、効率変動、原作のエンティティ構成・更新順・保存形式は比較対象外。

次の M1-02 は cached minitem / mid と同一 tick の複数搬入を、旧セーブと継続性を保って比較・移植する。
現在の受入試験を単に書き換えて緑にせず、固定版参照に基づく失敗ケースと変更理由を先に残す。
今回の輸送修正、UI-01、並列性・大規模負荷の Pythonista 実機結果は未確認。
