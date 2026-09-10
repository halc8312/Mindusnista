# Pythonista の並列化・GPU 利用調査

調査日: 2026-09-10。対象: 標準 Pythonista / Python 3.10、Mindustry v159.7 の完全移植。
これは一次資料に基づく設計候補であり、並列バックエンドの実装完了や iPhone の速度保証ではない。
超大規模な工場・戦闘への対応、機能の維持、原作に相応するエフェクトを共通の目標にする。
設備・敵・弾の上限追加、処理の脱落、描画品質の低下を性能試験の合格手段にしない。

## 証拠の段階

- **資料確認済み**: 下記 API や GIL 解放の原理を公式資料で確認した。
- **設計上の推論**: それらを本移植の仕事へ組み合わせる候補。実装・性能はまだ実証していない。
- **端末未検証**: 対象 iPhone での可用性、正しさ、速度、メモリ、長時間の発熱は未測定。

Pythonista 公式は Python 3.10 対応と NumPy 同梱を記載している。
3.13 更新は開発中との記載であり、将来の free-threaded 実行を現行版の前提にしない。[1]
公開 objc_util / scene 文書は旧版の記載を含むため、対象実機の API とも照合する。

## 候補と使いどころ

| 経路 | 資料確認済みの原理 | 本移植への候補と未検証事項 |
|---|---|---|
| NumPy ＋ CPU ワーカー | 多くの数値配列演算は GIL を解放し、独立した配列を担当する複数スレッドがネイティブ演算中に並列実行できる。object dtype は対象外。[2] | 座標・距離・判定候補等を連続した数値配列で扱う。同梱版の対象演算、分割サイズ、1・2・4 ワーカーの効果を実測する。 |
| ctypes ＋ Accelerate | ctypes の CFUNCTYPE による外向きネイティブ呼び出しは GIL を解放する。Accelerate は CPU 向けの最適化されたベクトル演算等を提供する。[4][6] | 既存 vDSP 等への一括委譲を調べる。Pythonista からの呼び出し、型・寿命・関数のスレッド安全性、実際の性能は端末未検証。 |
| scene.Shader / EffectNode | GPU 上の GLSL fragment shader を SpriteNode / EffectNode に適用できる。EffectNode は子の描画結果へ後処理を適用できる。[8] | 発光・歪み等の描画処理を GPU へ委譲する。原作との見た目と表示順を比較し、画素処理量・描画回数も測る。 |
| objc_util ＋ Metal compute | objc_util は Objective-C の bridge とシステム framework 読み込みを提供する。Metal は newLibraryWithSource による実行時コンパイルを公式に提供する。[5][9] | .py 内の shader 文字列から GPU 計算を呼ぶ設計候補。Pythonista での実行成功、UI との併用、性能は未検証。 |

NumPy の通常の単一演算は基本的に単スレッドで、BLAS 内部の並列化は backend に依存する。[3]
「NumPy に変えれば全コアを使う」とは扱わない。SIMD 高速化と複数コア利用も別に測定する。
Pythonista の ObjCBlock で Python 関数を GCD 等へ渡しても、その Python 実行には GIL が必要。[7]
重い計算そのものをネイティブ関数や GPU へ渡せるかが判断点になる。

## 同じ挙動を維持する設計

確認した現行 `src/mindusnista/app.py` の `World.step` は建物、敵、弾を順に更新する。
`_tick_bullets` は弾ごとに敵を探索し、先の弾が与えた損害が後の弾の標的選択へ影響する。
従って、世界全体の更新や全命中処理を単純に同時実行してよいとは判断できない。

- ワーカーには読み取り専用の入力と専用の出力領域を渡し、共有配列へ競合して書かない。
- 並列化するのは独立性を確認した演算や判定候補の生成から始める。
  在庫・HP・破壊等への反映は、参照実装と同じ順序・条件を維持する。
- 原作の更新順、同距離の選択、乱数状態、浮動小数点の丸めを比較対象に含める。
  並列化による加算順変更や GPU の演算差を、誤差許容の後付けで隠さない。
- 固定入力からの毎 tick の状態・資源収支・命中結果と保存再開を比較する。
  現行実装との一致だけで原作互換とは呼ばず、原作比較の範囲も記録する。
- GPU は当初エフェクト等の独立した処理を候補にし、ゲーム状態へ影響する計算は
  数値と順序の一致を確認した範囲だけ採用する。描画と計算が使う帯域・同期時間も含めて測る。

## 単体 .py 配布

編集元は引き続き src とし、既存の生成手順で `mindustry_pythonista.py` 一つを配布する。
標準 Pythonista の同梱機能・システム API を候補とし、pip や追加ネイティブバイナリの導入を必須にしない。
shader ソースを採用する場合も生成対象へ含め、起動時の外部取得を必要としない。
headless core は scene / ui / objc_util を要求せず import できる境界を維持する。
利用不能な高速化経路を検出できるようにし、同じルールを実行する基準経路を保持する。
その際の性能未達は未達として記録する。

## P-01: 次に実装する小さな検証

最初の成果物は、ゲーム状態を変更しない単体実行可能な能力確認・数値カーネル比較器とする。
ゲーム本体への並列導入とは別タスクにして、まず「この端末で何が使えて速いか」を確認する。

1. Pythonista・Python・NumPy の版、機種・iOS、利用できる API を記録する。
2. 固定 seed の同一データで、独立した二次元距離判定を基準 Python と NumPy で比較する。
   閾値付近・同距離・大きさの違う入力も含め、マスクと数値の比較条件を先に固定する。
3. 総件数と演算内容を固定したまま NumPy の 1・2・4 ワーカーを比較する。
   全ワーカーへ同じ全件を重複配布する測定や、結果を使わない演算は避ける。
4. Accelerate の小さな対応演算を同じ比較器で試す。Metal は最小計算の起動・結果照合から
   可用性を確認し、まだゲーム全体の性能向上とは扱わない。
5. 初回準備と継続処理を分け、入力変換・コピー・割り当て・同期・結果反映を含む総時間を測る。
   中央値・p95、扱った総件数、推定バッファ量と測定可能な実使用メモリを区別して残す。
6. 正しさと性能の両方を確認できた経路のみ、次の小さなゲーム処理への採用候補にする。
   PC の検査は比較器の検証であり、iPhone の FPS・速度・発熱の証拠に転記しない。

P-01 後は実際の工場・戦闘で、同じ配置・入力・tick 数・カメラ・エフェクト条件を揃えて比較する。
長時間運転と保存時の停止も測り、単発カーネルの倍率をゲーム全体の倍率として報告しない。

## 一次資料

1. [Pythonista 公式: NumPy 同梱・対応 Python](https://www.omz-software.com/pythonista/)
2. [NumPy Thread Safety: GIL 解放と配列の共有](https://numpy.org/doc/stable/reference/thread_safety.html)
3. [NumPy 1.24 Global State: 演算と BLAS のスレッド数](https://numpy.org/doc/1.24/reference/global_state.html)
4. [CPython 3.10 ctypes: CFUNCTYPE](https://docs.python.org/3.10/library/ctypes.html#ctypes.CFUNCTYPE)
5. [Pythonista objc_util: bridge・load_framework・ObjCBlock](https://omz-software.com/pythonista/docs-3.4/py3/ios/objc_util.html)
6. [Apple: Introducing Accelerate for Swift](https://developer.apple.com/videos/play/wwdc2019/718/)
7. [CPython 3.10: Non-Python created threads](https://docs.python.org/3.10/c-api/init.html#non-python-created-threads)
8. [Pythonista scene: Shader・EffectNode](https://omz-software.com/pythonista/docs-3.4/py3/ios/scene.html#shader)
9. [Apple: Discover compilation workflows in Metal](https://developer.apple.com/videos/play/wwdc2021/10229/)
