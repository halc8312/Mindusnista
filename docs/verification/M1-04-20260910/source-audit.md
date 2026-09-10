# M1-04 独立読取監査

取得日: 2026-09-10。Mindustry v159.7 固定コミット
`c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。

GitHub 接続で固定コミットの本文を今回再取得した。
`../M1-03/upstream-BuildingComp.java` と `upstream-Drill.java` は、
過去の保存処理で付いた末尾の改行1個を除いて今回取得本文と完全一致する。

| 原作パス | 取得本文 SHA256 |
|---|---|
| core/src/mindustry/entities/comp/BuildingComp.java | `972405cf0be70bfac07b4e10eb5587c8c7c2dc76af5ec7a8ffc5e49b247b293d` |
| core/src/mindustry/world/blocks/production/Drill.java | `a04af188ccb8287803ebd801907b919a1e9659f2ac482eeaae12f4f142a311f4` |

`core/src/mindustry/world/modules/ItemModule.java` も同じ固定コミットから再取得・読取した。

## 呼出順と相違

- BuildingComp 1007–1020: `offload` は `produced(item,1)`、開始cursor保存、各隣接先に
  **cursor増加→accept→handle** の順。全拒否・隣接なしなら自分の `handleItem` を呼ぶ。
- 1026–1039: `put` は同じ探索順だが production記録と自分へのfallbackを行わず成否を返す。
- 866–868: 継承元 `handleItem` は `items.add(item,1)` のみで容量確認なし。
- 1045–1051: `produced` はキャンペーンsectorの生産記録・unlockであり、移植側の
  `stats["mined"]` と同じ機能ではない。
- 1078–1127: 在庫から出す `dump` は受入・移送後にcursorを増やす。
  生産 `offload` と増加位置が異なるため、M1-03 `dump` を置き換えてはならない。
- Drill 287–293: 定期dumpが採掘対象なしのreturn・生産処理より先。
- 300–313: 容量不足・鉱床・効率の条件を満たすとwarmup更新とprogress加算。
- 315–321: 生産開始前に一度容量確認し、`amount = (int)(progress/delay)` 個をすべて
  `offload` してから `progress %= delay`。ループ内で容量を再確認しない。

旧Pythonでは受入成功後にだけcursorを更新し、全拒否時の過大cursorが正規化されない。
生産loopの容量再確認で複数完了分を捨てる場合があり、剰余更新も生産より前だった。

## 保存と大量の完了分

ItemModule 24–25は `int[]` と `int total`、238–243の加算は容量を確認しない。
291–324の保存・復元ではitem数をsigned intで扱い、itemCapacityとの照合はない。
従って容量10を超える在庫は単に「不正」とは判定できない。

現行Pythonは保存progressを1e12まで、調整用drill_timeを正の小数まで認めている。
新しい保存上限をint32へ固定しても、Pythonが生成できる調整済み状態を拒否しうる。
最小変更としてドリルの在庫だけを厳密な正のPython整数として検証し、容量上限を撤去する。
他設備の在庫条件・品目キー・既存ファイルバイト数検査は維持する。
これは原作msavの整数範囲・Javaオーバーフロー互換の実装ではない。

progressが大きい旧保存では、単純に容量breakを削ると数十億回の空振りが発生しうる。
現在のWorldでは、すべての受入拒否は無副作用で、acceptsはsourceの在庫・progress・
mined数を参照しない。受入先の在庫・弾数・荷物・配置とsourceの種類・配置だけを見る。
tickを挟まず同じ品目を生産するため、一度全隣接先に拒否された後は全残数も拒否される。
一巡後cursorは正規化済みで、続く一巡でも変わらない。

したがって最初の完全拒否までは逐次処理し、それ以降の在庫とmined加算をまとめても、
現在対応するWorldの最終状態は同じ。成功分の順番を維持し、全拒否の最初の探索は省かない。
大きなprogressの検査は算術で期待値を出し、旧コードの巨大loopは実行しない。

## 明示する比較境界

- 同じ近隣リスト、同じ順序、同じ対応品目、単一チーム、静的な受入先。
- 原作のfloat32、キャンペーンproduction、効果、液体、効率、全contentは対象外。
- 原作scheduler・近隣構築履歴・タイマー位相・建物置換をこの修正だけで同一としない。
- 拒否中の副作用、独自canDump、MOD、再入・並行更新がある受入先には一括化の証明を流用しない。
- Pythonista実機、原作全体の工場実行、原作msav保存交換は未確認。

## 実装の独立レビュー

`src/mindusnista/app.py` の変更を原作と照合し、現在の範囲で阻害事項なし。
moduloは生産後、完全拒否suffixだけの一括加算、ドリルだけの正整数保存に限定されている。

CPython 3.12.14 で独立実行:

```sh
python -m unittest discover -s tests -p test_drill_offload.py -v
```

16 unittestが成功、失敗・エラー・skipなし。実行した生成物SHA256は
`bfd9606bb178016c2324e40378109dde32569c517fa25f256868d0751ab10fca`。

追加で一括化のみに関する具体的な懸念（複数の受入先、途中拒否、過大cursor）を確認した。
4方向の実際のWorld受入設備、銅/鉛、詰まり、在庫、周期dumpを変える固定seedの48条件を
用意し、最適化側と「全offloadを省略せず実行する」側のWorld.digestを比較した。
883回の逐次offloadを含め全条件一致。元の巨大loopを実行していない。

```sh
python review-aggregation.py /absolute/path/to/Mindusnista
```

実行器は同じフォルダの `review-aggregation.py`、実結果は
`review-aggregation-result.json`。原作Java・実機・性能測定の結果ではない。
## 抽出Java・fixture・checkerの独立レビュー

`DrillOffloadReference.java`、`drill_offload_scenarios.json`、
`check_offload_reference.py` の実装を読取。固定本文のoffload/dumpとdry Drill分岐へ
照合し、現在の比較境界に阻害事項なし。callerでのmined記録は参照アダプターと明記され、
元のキャンペーンproductionを移植したと扱っていない。

各明示呼出しの全在庫・全受取先在庫・cursor・progress・生産数・結果を比較する。
dumpの試行は全件、tick内offloadは最初の一回の試行のみ、連続offloadのeventは一種類へ
畳み込むことを条件に宣言している。一括化した空振りの実行回数を一致条件へ含めていない。
integer-exactのprogressで比較し、warmupのfloat32全体互換を主張していない。

独立実行:

```sh
python tools/check_offload_reference.py --output ../evidence/M1-04/review-local-offload.json
```

21ケース・42明示呼出しのPython trace生成と検証を完了。
終了コード2、`status=unavailable_toolchain`、`java_comparison=not run`。
ローカルJava未実行なので、抽出比較成功はCI実行後の別証跡で確認する必要がある。

- Java参照SHA256: `b8f42c172ade89f6fa67d0c2704208eeab5094b2eccaac2652943c48886f75a0`
- fixture SHA256: `d0ab8e9e6d30798d68b896d647527b3e7792876e6d3a8eaa2020efb6f6877358`
- 本体SHA256: `bfd9606bb178016c2324e40378109dde32569c517fa25f256868d0751ab10fca`

実行結果は同じフォルダの `review-local-offload.json`。

## 最終の小変更に対する再レビュー

参照checkerの空在庫条件をCounterの真偽値から `sum(cargo.values()) > 0` へ変更。
0件のキーが残っていても空在庫を正しく扱うための変更で、原作 `items.total()==0` と一致する。
空在庫で非生産tick→周期dump tickを行い、過大cursor 17を維持するfixtureを追加した。
現在のfixtureは **22ケース・44明示呼出し**、SHA256は
`fbfa6075e57f6d881126a185c4062eec0c0e05c3a0d794188a35ab0c76d48247`。
前節の21ケース・42呼出しはその時点の実行記録として保持する。

最終読取中にfixture名と検査側参照名の不一致を見つけて通知し、
`empty_dump_preserves_oversized_cursor` への統一を読み戻した。
その後 `DrillOffloadReferenceTests` の5メソッドだけをCPython 3.12.14で独立実行し、
全成功、失敗・エラー・skipなし。この中で最終22ケース・44呼出しのPython trace生成・
検証、cursor保持、比較器の故障検知、Java不在を成功扱いしないことを確認した。
本体とJava参照の前掲SHA256は不変。Javaローカル再実行は行っていない。
最終変更について追加の阻害事項なし。CIでの実際のJava比較成功は別途確認する。
