# M1-05: ドリル・ベルト・分配器の連続搬送比較

更新日: 2026-09-10。ゲームは0.1.2-dev、保存schema 1のまま。
原作の固定基準はMindustry v159.7、commit
`c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。

## 本体で修正する規則

原作の通常の分配器は`rotation`を巡回選択の位置として使う。移植側は従来`cursor`を使っていたため、
向きを選んでから新設した分配器や、二つの値が異なる保存で、原作とは別の受取先を選ぶことがあった。
`cursor`はドリル等の`BuildingComp.cdump`に対応する別の状態である。

`_router_target`で次を移植した。

1. `rotation`から近隣を調べ、最初に受け取れる相手を探す。この検索では位置を進めない。
2. その相手が分配器なら累積時間1まで待機する。途中で後続のベルトへ選び直さない。
3. 搬出できる時だけ同じ順で再検索し、各受入判定の前に`rotation`を1つ進める。
4. 選んだ相手へ搬入してから、送り元の当該品目を1個取り除く。

原作`acceptItem`と`handleItem`の境界に合わせ、既存`receive`の受入判定後の処理を
`_handle_item`へ分けた。`receive`の呼出し方・返却値・受入規則は維持する。
現行の受入判定は副作用を持たず、この二度の検索で選択先は変わらない。
分配器同士の速度8、累積`1/8`はこの条件では2進で正確に表せる。

通常の搬入元へ戻す動作は許可する。原作が搬入元を除外するのはその元がoverflow gateの場合だけであり、
全ての逆流を禁止する実装にはしない。overflow gateとユニット操作中の分配器は未実装。
現行の分配器以外の設備は`instantTransfer`ではない。将来対応する設備ではこの遅延条件の拡張も必要。

## 保存と操作

フィールドの追加・削除・schema変更はない。旧保存の`rotation`、`cursor`、`router_time`、`last_input`を
読み込み、そのまま保存する。**今後の分配先選択は保存されている`rotation`に従うため、
旧実装で`cursor`を使っていた時と次の搬出先が変わり得る。** 古い`cursor`を移行時に上書きしない。
独自schema 1保存は原作`.msav`ではない。

設備配置時の方向指定は維持する。分配器の描画はこの`rotation`で回転せず、
設置済み設備の回転ボタンの対象は従来通りベルトである。
マス操作・静止保持後の連続設置・誤スライド抑制、版番号、GPL、起動ガードを変更しない。
通常Worldの保存・復元後の分配器継続は独立した回帰で確認する。

## 抽出比較の範囲

`reference/IntegratedTransportReference.java`は、次の原作メソッドを一つの小さなJavaモデルで実行する。
受取先を受入可否の表に置き換えず、ベルトと分配器の実際の受入・搬入処理を相互接続する。

| 出典 | 対象 |
|---|---|
| [Router.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Router.java) | 通常のgetTileTarget、updateTile、acceptItem、handleItem |
| [Conveyor.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Conveyor.java) | updateTile、pass、acceptItem、handleItem、add、前方接続 |
| [Drill.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/production/Drill.java) | 乾式・効率1の採掘、生産完了と周期dump |
| [BuildingComp.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/entities/comp/BuildingComp.java) | dump、offload、incrementDump、受取メソッド境界 |
| [Blocks.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/content/Blocks.java) | 通常ベルトspeed=0.046f、ドリル等の固定パラメータ |

`tools/check_integrated_transport.py`はPython本体の同じメソッドを呼び出す。
fixtureは全ての実隣接を明示した順番で渡す。同じ固定順で一設備ずつ更新し、
その直後の**全設備**の品目別在庫、貨物の配列順と座標、minitem/mid、cursor、rotation、
分配器の時刻と搬入元、採掘進捗・暖機・dumpカウンターを比較する。
成功した搬入については相手・品目・搬入前の送り元rotation/cursorも比較する。
ベルトの在庫観測値は双方とも生きている貨物配列から数える。原作ItemModule全機能の比較ではない。

14ケース・985回の明示更新を含む。Python側の搬入イベントは58回。
主な条件は、分配器の初期方向と旧cursor、受入拒否後の選択、8更新の待機と通常逆流、
ドリル→ベルト→分配器→ベルトの正順・逆順更新、混在在庫の周期dumpと複数生産、
鉱石が無くなったドリルの残在庫、満杯時の暖機低下、冷間からの暖機である。
通常速度0.046に加えて、2進速度0.125と追加の小数速度0.03を比較条件として使う。
後二つを原作の通常速度とは扱わない。連続モデルの保存復元試験は今回含めない。

全ての更新で、初期の品目別貨物と、その更新を行ったドリルの鉱石に帰属する生産数を積算し、
全設備の貨物と一致することを独立に検査する。生産後に総数だけを維持して銅を鉛へ変える改変も拒否する。
不足する更新、未知の設備、非隣接や重複した接続、重複占有、非有限値、離散値へのfloat/bool混入、
過大なfixture進捗を拒否する。比較用fixtureの実行上限をゲームの規模制限には使わない。

## 数値の許容差と未対応範囲

Javaは原作通りfloat32、Python本体は現行float64を維持する。
座標、minitem、時刻、採掘進捗、暖機だけに絶対差`2e-5`を許す。
この短いfixtureではベルトの0～1座標と明示した採掘進捗の丸め誤差を扱うための値であり、
一般の長時間float32互換を保証する値ではない。
貨物ID・配列順・数・搬入が起きる更新・選択位置・cursor・各整数カウンターは完全一致で判定する。
丸めが搬出更新や数量を変えた場合は不一致のまま記録し、数値許容差で吸収しない。

これは**原作エンジンのheadless実行ではない**。proximityのObjectSet順序や履歴、
EntityGroupの更新・削除・休止順序、実時間のInterval位相、効率・液体・timeScaleの変動、
全コンテンツ・チーム・ユニット制御・MODの副作用、効果や原作保存形式は対象外。
ドリルの5更新カウンターは既存移植側と合わせたテスト用の周期であり、原作Time.timeの移植ではない。
鉱石選択・数は固定fixtureであり、地形生成や原作鉱石走査全体の比較でもない。
M1-02等で記録した、手で作った不規則な貨物配列と原作の配列切詰めの差も解消済みにはしない。

## 検査の実行

```sh
python tools/check_integrated_transport.py
```

開発時だけJDK17を必要とする。Pythonistaのゲーム起動にJVMを追加しない。
JDKが無い・壊れている場合は`comparison=not_run`、終了コード2とする。
実行済みの不一致は終了コード1、全比較成功だけが終了コード0。
結果は[M1-05検証記録](M1_05_VERIFICATION_ja.md)で、ローカル未実行とCI実行を区別する。
PCの回帰・抽出Java比較をiPhoneの成功、FPS、原作全体互換へ転記しない。
0.1.2の実機結果は今回も未報告。
