# P-03: 数値状態を配列として継続保持する比較

更新日: 2026-09-10。開発用の単体比較器を追加した。ゲーム本体・0.1.2-dev・旧保存schema 1は変更しない。
これは大規模処理のデータ構造を検証する独立した運動モデルであり、ゲームの代替や新しいゲームではない。
完全移植の機能・規模・エフェクト・原作iOS/Steam保存共有の要件を削減しない。

## 実行方法

`tools/pythonista_array_state_probe.py` 一つをPythonistaへ置いて実行できる。
Python 3.10互換で、既存のNumPyがあれば使う。追加インストールやゲーム本体の読込は行わない。
従来のP-01/P-02比較器とは別のファイルであり、そちらの引数と動作は維持する。

```sh
python tools/pythonista_array_state_probe.py --count 20000 --warmups 1 --repeats 5 --output p03-20000.json
python tools/pythonista_array_state_probe.py --count 200000 --warmups 1 --repeats 5 --output p03-200000.json
```

Pythonistaでは引数なしで20,000件・初回1＋warmup2＋steady7回を実行できる。
件数や反復数を変える場合は実行引数を渡す。最初は20,000件で動作と出力を確認する。
JSON出力先を省くと標準出力へJSON、標準エラーへ日本語の要約を出す。
出力先は実行前に新規作成し、既存ファイルを上書きしない。書込・flush・close失敗は終了コード2。
比較失敗・バックエンド例外・終了処理失敗は全体を`failed`として終了コード1にする。

NumPy本体が存在しないとき、または`--no-numpy`のときはPythonだけを実行し、
NumPyの3条件を`not_run`、全体を`partial`にする。NumPy内部依存の欠落や壊れたimportは`error`。
NumPy不在を数値一致や速度改善と扱わない。取得できる場合、Pythonista・iOS・NumPyの版をJSONへ記録する。

## 同じ仕事と継続状態

各行は整数IDと、float64のx・y・vx・vy・target_x・target_y・threshold²を保持する。
初期値と速度はseedから再現可能な二進分数で、両軸の速度は非ゼロ。毎tickすべての位置を
`x += vx; y += vy`で更新し、その時点の距離二乗と閾値判定を全行について計算する。
P-02のように元の座標から毎回算出し直さず、各バックエンドの前tickの状態を継続して使う。

| 条件 | 継続状態 | 毎tickの処理 |
|---|---|---|
| Python / 1 | Pythonの行リスト | 全位置更新 → 全距離・判定 → 全ID・位置・距離・真偽のPythonリスト |
| NumPy / 1・2・4 | 初回取込後のint64 ID配列とfloat64状態配列 | 全位置更新 → 非重複の仕事をdispatch・全完了待機 → 同じ全結果をPythonリストへコピー |

NumPyの位置更新は主スレッドの配列演算で、距離計算を1/2/4ワーカーへ分ける。
1ワーカーにも同じexecutor経路を使う。ワーカー数は同時CPU実行の証明ではない。
各ワーカーの状態ビュー・dx・dy・判定領域は互いに非重複で、途中のワーカー例外でも
開始済みの全処理を待ってから例外を返す。前tickの書込と次tickの入力変更を重ねない。
IDをfloatへ変換せず、2^53を超えるIDの回帰も用意した。

初回を含めて全tick、ID・位置・距離・真偽・件数・順序を独立したPython参照と完全照合する。
actualとexpectedのdigestはそれぞれ算出する。出力は独立したPythonリストなので、次tickが
過去の出力を書き換えることはない。距離二乗・判定のリスト生成はPythonの計算区間にも含む。
誤った結果や保存復元に失敗した条件へ速度比を付けない。

これはfloat64の独立モデルであり、原作Java float32の精度・輸送順・衝突・探索・乱数の互換検証ではない。
生成・削除、外部コマンド、標的移動、画面・GPU・エフェクト等の仕事も含まない。
ここで省いている仕事を、完成するゲームの機能から省くという意味にはしない。

## 時間の範囲

すべて`time.perf_counter()`の経過時間。初回・warmup・steadyの各標本とsteadyのp50/p95/最大を記録する。
p95はnearest rankで、今回のsteady5回では最大値になる。短い共有PC測定で持続性能は判断しない。

| 項目 | 含む処理 |
|---|---|
| `workload.dataset_seconds` | 共通の初期行リスト生成。全条件に共通の別記録 |
| `prepare_seconds` | 各条件の初期行取込・コピー/変換・保持バッファ確保・executor作成 |
| `initial_conversion_seconds` | 初期状態のコピー/配列化。prepareの内数 |
| `state_update_seconds` | 全位置の継続更新とtick加算 |
| `compute_sync_seconds` | 全距離/判定、NumPyのdispatch・全future待機。Pythonでは最終距離/判定リストの生成も含む |
| `result_apply_seconds` | 全ID/x/yのPythonリスト反映、NumPyでは距離・真偽の全件`tolist`も含む |
| `runner_overhead_seconds` | 呼出し・戻り・計測辞書作成など、内側の3区間の外 |
| `total_seconds` | `step`呼出しから戻りまで。上記4区間の和 |

`first_with_prepare_seconds`は準備＋初回。
`amortized_seconds_per_tick`は準備＋初回/warmup/steady全tickの総時間を完了tick数で割る。
`amortized_with_import_seconds_per_tick`は、候補単独利用を想定してNumPyのimportを一度だけ加える。
初期変換をprepareと別に二重加算しない。参照生成・全件照合・digest・報告生成・shutdownはtick計測の外。
実際のゲーム処理を連続実行した測定ではなく、参照照合の挿入、固定実行順、周波数・他負荷の影響がある。

## 共通JSONへの実際の保存と復元

全計測tick後に一度、次の共通形式へ全状態を取り出す。

```text
format: mindusnista-p03-synthetic-state
schema: 1
columns: [id, x, y, vx, vy, target_x, target_y, threshold2]
tick: 完了tick数
rows: 全行の全8値
```

このschemaは比較器専用。ゲームの独自schema 1や原作`.msav`とは別形式で、ゲーム保存は読み書きしない。
`json.dumps`からUTF-8 bytesへ実際に変換し、`json.loads`・型/有限値/ID検証を経て
同じバックエンドを新規作成する。NumPyでは復元時のPython行→配列変換も含む。
全バックエンドの保存bytesが参照と完全一致し、復元直後の全状態とその後3tickの全出力を照合する。

| checkpoint項目 | 計測する処理 |
|---|---|
| `state_export_seconds` | 全IDと全数値状態を共通Python辞書・行リストへ変換 |
| `json_encode_seconds` | 共通辞書→JSON文字列→UTF-8 bytes |
| `json_decode_validate_seconds` | bytes→JSON読込→全行/型/値の検証 |
| `state_restore_seconds` | 復元用の状態取込・バッファ/executor確保 |
| `total_seconds` | 上記4区間の和 |

`amortized_with_checkpoint_seconds_per_tick`は、準備と全計測tickにcheckpoint総時間を加え、
計測tick数で割る。**今回は7tickごとに1回保存復元する費用配分**であり、実ゲームの保存頻度ではない。
NumPy importはこの項目には含めない。復元後3tickは検証用で、`resume_samples`へ別記し償却分母にも入れない。
復元executorのスレッド起動は遅延するため、初回`resume_samples`側に現れる。
ディスクI/O・shutdown・原作codecの費用は含まない。

数値保持バッファの概算は1行81バイト（float64状態7列＋int64 ID＋float64作業2列＋bool）。
20,000件は1,620,000バイト、200,000件は16,200,000バイト。入力・出力・参照・保存のPythonオブジェクト、
NumPy内部一時領域・executor・allocator・ランタイムを除く。**実プロセスのピークメモリは未測定**で、
この概算を実使用量と呼ばない。

## PC実測

Linux x86_64 / CPython 3.12.14 / NumPy 2.3.5。20,000/200,000件とも初回1＋warmup1＋steady5回、
各条件の最後に共通JSONの保存復元と3tickの継続を実行した。全4条件で各7回＋復元後3回の全行が一致。
各条件の照合は20,000件では200,000行分、200,000件では2,000,000行分であり、テストメソッド数ではない。
保存bytesのSHA-256も4条件間で完全一致した。最終ツールSHA-256:
`e65a7d79866c20f91c8abdd00edb133bf6b34585ab17dd10227e388b855efb4c`。
比較例外の記録修正前にも予備測定したが、以下は修正後の再測定だけを採用している。

| 条件 | 20,000件 tick p50 / p95 | 200,000件 tick p50 / p95 | 200,000件 保存復元 |
|---|---:|---:|---:|
| Python / 1 | 4.769 / 4.857 ms | 74.904 / 89.671 ms | 1,606.092 ms |
| NumPy / 1 | 1.214 / 6.412 ms | 21.519 / 30.616 ms | 1,812.735 ms |
| NumPy / 2 | 1.518 / 2.604 ms | 18.507 / 23.479 ms | 1,494.418 ms |
| NumPy / 4 | 2.022 / 2.807 ms | 15.430 / 20.776 ms | 1,400.563 ms |

**この独立モデルでは、状態の配列保持が全結果反映込みのtick時間を短くした。**
20,000件ではNumPyの1ワーカーが最短、200,000件では4ワーカーが最短だった。
ワーカー数を増やせば必ず速いという結果ではなく、今回の少ない反復だけで同時CPU実行や端末性能を証明しない。

200,000件・NumPy4の区間中央値は位置更新1.797ms、計算/同期1.397ms、全結果反映11.849ms。
結果反映の費用が残る。区間中央値の和を総時間の一つの標本としては扱わない。
準備250.870ms、準備込み7tickの償却52.517ms/tick、1回の保存復元を含めた償却252.597ms/tick。
Pythonの対応値は準備188.903ms、準備償却106.282ms/tick、保存込み335.723ms/tickだった。
いずれもNumPy importは除外した値で、import込みの別項目もJSONへ保存している。

共通JSONは20,000件で1,629,258バイト、200,000件で16,494,648バイト。
200,000件・NumPy4の保存復元1,400.563msの内訳は全状態反映259.081ms、encode450.326ms、
decode/検証362.249ms、状態再確保328.907ms。保存時の全状態変換とJSON処理は大きな費用として残った。
この比較器の保存容量をゲームの現行8MiB制限の撤去、原作セーブ互換、大規模保存の実機成功とはしない。

## 回帰と次の判断

新規20 unittestは全件の実変化・手計算の閾値・出力非alias・全列の型・独立digest・失敗時の記録を検査。
1/3/17件×1/2/4ワーカー、保持アドレス・非重複範囲、2^53を超えるID、保存bytes・復元直後と継続を含む。
NumPy欠如と壊れたimport、worker例外・終了例外、単体コピーでのCLI・Python 3.10 AST・既存出力保護、
遅延close失敗も確認する。ローカルCPython 3.12.14では20本成功、失敗・エラー・skip各0。
NumPyがない環境では実NumPyを使う5本をskipし、未実行と記録する。

比較例外でサンプルだけが追加されdigest列とずれる不具合は、修正前の失敗回帰で固定して修正した。
初回と途中の例外で、完成したサンプル・actual/expected digestの件数が一致する。
数値不一致は完了した比較として残し、不正な出力でdigestを生成できない場合は`null`を記録する。

**P-02とP-03の時間を割って「同じ仕事が何倍速くなった」とは言わない。** P-02は毎tick全入力を
Pythonリストから受け取る境界、P-03は状態を内部保持する別の仕事である。
今回の候補が有効でも、実ゲームに必要な生成・削除・コマンド反映・探索・順序・保存を含めて再検証が必要。
原作float32照合、実機の持続性能・発熱・ピークメモリ、Accelerate/Metal、ゲームへの導入は未実施。
機能・規模・エフェクトを削って合格にせず、[完全移植の要件](FULL_PORT_REQUIREMENTS_ja.md)を維持する。
