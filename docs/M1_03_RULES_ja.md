# M1-03: ドリルの周期的な在庫搬出

固定基準は Mindustry **v159.7**、コミット
`c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。ゲームは 0.1.2-dev / 独自保存 schema 1 を維持する。

## 確認した原作と変更

| 参照した原作 | 今回移植した条件 |
|---|---|
| [Drill.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/production/Drill.java) の `DrillBuild.updateTile` | 周期搬出では、採掘対象 `dominantItem` が在庫にあればその品目だけを指定する。拒否されても別品目へ切り替えない。対象がない／在庫がないときは品目指定なしで搬出する。 |
| [BuildingComp.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/entities/comp/BuildingComp.java) の `dump(Item)` / `incrementDump` | 呼出開始時の cursor から隣接建物を巡り、各隣接先で content ID 順に在庫品を試す。隣接先ごとに cursor を1回進め、成功した1個だけを在庫から除く。 |
| [Items.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/content/Items.java) の `load` | 現在扱う銅は ID 0、鉛は ID 1。この順序を既存 `ITEMS` で使う。 |

`World.dump` を追加し、`_tick_drill` の周期搬出をそこへ接続した。以前は在庫辞書の挿入順で
品目を選び、その品目について全隣接先を探していたため、混在在庫の送り先・品目に相違があった。
空在庫・隣接なし・指定品目の在庫なしでは cursor を変えない。全隣接先に拒否された場合は
隣接数だけ進めるので、正常範囲の cursor は元に戻り、過大な保存 cursor は正規化される。

原作の Drill は `hasItems=true`、`canDump` は継承元の常時 true を使う。今回の公開メソッドは
既存の在庫を持てる建物の正しい状態を前提とし、現在のゲーム呼出元はドリルだけ。
新しい保存フィールドはなく、schema 1 の在庫・cursor・周期カウンターをそのまま保存する。

## 比較境界

`python tools/check_dump_reference.py` は、上記 Java メソッドを抽出した
`reference/DrillDumpReference.java` と Python の実際の `World.dump` / ドリルの品目選択を比較する。
14シナリオ・49回の明示呼出しについて、指定品目、成否、cursor、全品目在庫、受取在庫、
受入試行の順序・品目・成否・試行前 cursor を整数・真偽値の**完全一致**で検査する。
数値許容誤差を用いる浮動小数点の比較ではない。

両側へ同じ順序の隣接リストと「受取可能な品目集合・合計容量」の試験用受入処理を渡す。
これは原作受取設備の移植完了や原作 headless 工場の実行を意味しない。
Python 側ドリル呼出しは、周期到達時点を明示し、fixture の呼出回数を制限して新規生産がないことも検査する。
Java の cursor は原作と同じ int。比較器は cursor と探索加算が int の範囲を超える fixture を拒否する。
ゲーム自身の既存 schema 1 cursor 検証の範囲は変更していない。

実際の World のドリル・ベルト・分配器・デュオ・壁を使う回帰試験は別に設け、
混在在庫、採掘対象の拒否、受取先優先、cursor、4→5回の周期境界、個数保存、保存・再読込後の継続を確認する。
有効な変更前回帰9本で7本の失敗を確認してから本体を修正した。
修正後は回帰14本と比較器の検査4本を追加した。実行環境・全体検査・CI の結果は統合検証記録へ記載する。

ローカルで `javac` / `java` が使用できない場合は終了コード **2** と
`java_comparison: "not run"` を返す。Python trace の生成だけを Java 比較成功にはしない。
比較器は開発用であり、iPhone へ JDK を導入する必要はない。

## 残る相違

- 生産直後の `offload`、Router の出力、近隣リストの構築順、建物の登録・更新順は今回の対象外。
- 原作の `Time.time` に基づくタイマーの初回位相は未移植。従来の5回カウンターを維持した。
- 原作一般形の受取中の近隣変更、チーム・MOD、全 content、電力・液体・効率は未比較。
- 原作 `.msav` との交換、原作全体互換、Pythonista 実機での輸送・負荷は未確認。

次の輸送タスクは、生産 `offload` の cursor・在庫への戻し方を固定ソースと比較し、
その後にドリル→ベルト→分配器の更新順を広げる。今回の狭い比較結果を scheduler の完成と扱わない。
