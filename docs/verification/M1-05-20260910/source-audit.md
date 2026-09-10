# M1-05 independent source / runtime audit

2026-09-10。対象 worktree: `Mindusnista-M15`、基準 main `9f466b9f43fd80c172f6e6a7de9db60fac7c004d`。
AGENTS / HANDOFF / PORT_STATUS / DEVICE_TESTS / NEXT_TASK / FULL_PORT_REQUIREMENTS を読み、
GitHub connector で下記の固定コミットの原作を今回新たに取得した。

固定基準: v159.7 / `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。

| Source | Git blob SHA |
|---|---|
| [Router.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Router.java) | `538ccb7d3154de29c4552d35548a3c8b4d495975` |
| [Conveyor.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Conveyor.java) | `3fe2d78477bf0a3a0e1742f22542db4c5e6dafe1` |
| [Drill.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/production/Drill.java) | `cc123b120a6e8f92719bded067915749afbf19d5` |
| [BuildingComp.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/entities/comp/BuildingComp.java) | `bc69046b3c2d9deebd3fbb1681acb3e0f47c56c9` |
| [Block.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/Block.java) | `75fd4d67ce8f549dedd024de25525b91826e09cc` |
| [Blocks.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/content/Blocks.java) | `27f6a687b621e9e1e14cd6340c7348d8c8e66414`（実装担当が同じ固定commitから再取得、通常速度0.046fを確認） |
| [Tile.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/Tile.java) | `3db5a8ebcd20d9fde0ce07cc05d08c5c336c8502` |

## 修正前に確認した差

Router.getTileTarget (100–130行) の走査開始位置・次回位置は Building.rotation。
BuildingComp.offload / dump で使う cdump と別の状態である。基準 Python は両方を
Building.cursor に割り当て、Router の rotation を選択に使用していなかった。

既存 World に router (10,10, rotation=1, cursor=0)、東向き conveyor (11,10)、
北向き conveyor (10,11)、router在庫銅1個を置いて1回更新した実観測:

```json
{"neighbors": [2, 3], "rotation": 1, "cursor": 0}
{"east": ["copper"], "north": [], "rotation": 1, "cursor": 1, "time": 0.125}
```

同じ明示近隣順での原作規則なら北を最初に試し、成功後 rotation=0 となる。
これは修正前 Python の実行と原作ソースの比較であり、Java実行成功の記録ではない。

UI.change_direction / rotation_target は既設 conveyor のみ変更する。一方 apply_tool は
全 BUILD_TOOLS について build_rotation を World.place に渡し、World.place は rotation % 4
を保持する。したがって、ベルトで選んだ方向の後にrouterを新設した場合にも非ゼロ初期rotation
は到達可能。原作 Router は rotate を true にせず、Block.rotate は初期値falseであるが、
Tile.setBlock は引数rotationを4で正規化して構築へ渡す。

## Router の維持すべき条件

- 在庫がある時だけ time を進め、まずset=falseで最初の受入可能な隣を探す。
- 最初の相手が Router / instantTransfer ならtime>=1になるまで待つ。
  後続に即時受入可能な conveyor があってもそれへ飛ばさない。
- 実際に搬出する場合だけset=trueで同じ走査を行い、試した隣ごとにrotationを進める。
  固定近隣・純粋acceptItemでは最初の相手が同一。原作は再走査自体を行う。
- lastInput の特例は overflowGate から来た場合だけ。普通のrouter同士の返送を
  last_input によって一律禁止してはならない。
- 受領時にtimeを0にし、lastInputを保存する。Pythonのlast_inputはID表現であり原作Tile参照ではない。
- Pythonの有効router在庫はschema 1検証で容量1。原作lastItemとitems.first()の復旧を
  通常在庫1個に限って対応づける。制御、removeStack、未対応instantTransfer設備は別の範囲。

## 保存と比較範囲への注意

schema 1はrotation、cursor、router_time、last_inputを既に別々に保存している。
cursorを移行時に破棄・上書きしない。修正後にrouterのrotationを使用するなら、旧保存の
次の分配先が従来cursorから変わり得る挙動変更を明記する。通常routerの近隣は最大4なので
rotation 0..3 の保存検証と整合する。新版の保存復元後の継続一致を試験する。

連続比較は原作から抽出したRouter / Conveyor / Drill / dump / offloadを接続し、
同じ明示近隣順と更新順で実受取設備のaccept/handleまで通す。
原作updateProximityのset iteration / 配置履歴、EntityGroupの登録・削除・sleep、
timer位相はこの比較から証明できない。Java floatとPython doubleの位置・進捗差は
小さい明示許容差を設けても、搬出tick・品目・個数・順序・cursorを許容差で吸収しない。
長いtickで境界の違いを見つけた場合は、許容差を広げず別の実差として記録する。

## 実装・回帰の独立確認

追加された `_router_target` はset=false→set=trueの再走査と受入前rotation更新を実装。
`receive` はaccept確認後に `_handle_item` へ委譲し、Routerは選択済みの相手へhandleだけ行う。
固定した非制御・既存設備・純粋accept条件で原作の順序と整合する。
在庫から1個だけ減らす。保存4項目を破棄せず、UI部分に変更なし。

実装者の `before-router-fix-valid.txt` を読んで7本中4失敗・3成功・0errorを確認。
最初の非validログとは分け、報告にはvalidの方を使用する。
修正後に独立して `python -m unittest discover -s tests -p test_integrated_transport.py -v`
を実行し7本すべて成功、skipなしを確認した。
初期rotation選択、旧cursor保存、実受取前のrotation、遅延先を飛ばさない条件、
普通の入力元への返送、全拒否/空、schema 1の復元続行を検査している。
この時点の本体差分にブロッカーなし。

## Java 抽出実装の独立確認

`reference/IntegratedTransportReference.java` のドラフトを対象固定ソースと照合。
Routerの二走査、Conveyorの容量3の配列挿入・cached minitem/mid・引渡し、
Drillの乾式採掘・dump/offloadを実受取処理へ接続した構造にブロッカーなし。
Java float演算を保持している。Drill.warmupSpeedは固定原作の0.015f。

追加で固定Arc `208a7540445a0387dbc026b1ee378ede8035ca6f` の
[Mathf.java](https://github.com/Anuken/Arc/blob/208a7540445a0387dbc026b1ee378ede8035ca6f/arc-core/src/arc/math/Mathf.java)
（blob `13115d3cf59ec18cde7b0705ba1f083a8041fb16`）を取得し、approachの加算/clamp式を照合。
固定Mindustryの[Edges.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/Edges.java)
（blob `7a7ad0dd0ba21935e70cfc338bfaded734c868d4`）とTile.relativeToも取得し、
size 2ドリルの接触端をclampする面方向と一致した。

このharnessはConveyor ItemModuleを実行状態として同期せず、生存貨物配列から在庫観測を作る。
対象のaccept/handle/updateが配列を参照する条件では妥当だが、ItemModule、stack API、
senseを含む原作状態全体を検査したとは扱わない。Java直接TSVはfixture入力専用で、
Python側の厳格validatorを通して近隣の隣接・重複・重なり・入力範囲を保証する必要がある。

## Python adapter とシナリオの独立確認

`tools/check_integrated_transport.py` と `reference/integrated_transport_scenarios.json`
を読み、14ケース・985明示更新を独立にPython実行した。58件の搬出イベントを観測し、
全traceのvalidatorを通過。これはJavaとの不一致0を意味せず、Python側の整合検査である。
環境はLinux 6.18.35 x86_64 / CPython 3.12.14。

fixture validatorは、同一辺の完全な隣接集合と指定順序、重複・重なり、
有限の数値範囲、整数型、在庫と貨物容量、鉱石と枚数、既知の更新対象を検証する。
実Worldのaccept/handleを計装して搬出直前のsource rotation/cursorを観測し、
受入結果の表による代用は行わない。全設備状態を明示更新ごとに出力する。
比較は整数/品目/リスト順/搬出更新を厳密に合わせ、連続値だけ絶対2e-5を認める。
NaN/infは比較前のvalidatorで拒否する。

原作既定の通常コンベア速度は0.046で、標準速度ケースはこれを使う。
0.125と0.03は追加の指定速度ケースである。全在庫を搬出できたことや、長期定常流量を
この小さいケース群から主張しない。更新順の前向き・逆向き、背圧、混在在庫、
採掘対象なしのdump、低温/停止時warmup、Routerの遅延と逆流等を含む。

比較器のmake_worldは観測対象だけを構築しcoreを含めないため、このままでは
通常のschema 1全World復元条件を満たさない。Router保存の独立回帰と、連続するJava比較を
「連続工場全体の保存をJavaで比較した」と合算してはならない。
品目別の生産増分検証を追加した最終validatorを再確認した。毎更新でmined増分を当該drillの
固定鉱石にだけ加え、非採掘更新での生産増加を拒否し、品目別の全貨物を検証する。
14ケース985更新は通過。生産済み標準速度ケースのframeで銅1個を鉛1個へ置き換え、
総数を保持した改変は `trace violates per-item cargo conservation` として拒否された。

JavaとPythonの搬出eventsは実外部handle入口に対応する。自己offloadの在庫戻しは
両方eventsに含まず、最終状態と生産台帳で検査する。明示更新ごとに比較するため、
異なる更新で搬出された貨物を数値許容差や最終在庫だけの一致で吸収しない。
現時点で本体・Java抽出・Python adapter・fixtureにブロッカーなし。

追加10本の比較器試験を含む17本を独立に再実行し、全成功・0fail/error/skipを確認した。
欠落フレーム、NaN、float/boolの離散値、生産後の品目置換、非採掘生産、許容差、
不正なfixture、JDK不在、既存レポート保護を検査している。
JDK不在診断を模擬した単体試験は、未実行を成功扱いしない経路の検査に限られる。
Pythonトレース同士の自己比較もJavaの実行結果ではない。
実JDKによるコンパイル/実行と985更新の照合がCIで成功するまで、原作抽出比較成功とは記録しない。
Javaコンパイル/実行はこの独立ローカル監査時点でCI待ち。
端末未実行。0.1.2の実機成功や原作全体互換への判定変更なし。
