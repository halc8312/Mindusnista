# P-05 独立レビュー

対象: `Mindusnista-P05/tools/profile_world.py` と実 `World`。コードは変更していない。

- AGENTS、引き継ぎ、移植台帳、実機台帳、NEXT、完成要件と `World.step/save/load/digest` を確認。
- per-instance wrapper は元の bound method を同じ引数で呼び、finally で積算・context 終了時に元の属性を復元する。
- exclusive は inclusive から直接の子 wrapper の inclusive を差し引く。多重階層を二重に減算しない。wrapper の費用は推定除去せず、normal と profiled の外側 step wall time を別々に出す。
- 保存状態と現行 World の非保存 grid/revision/neighbors/path/distance/message を毎 tick 比較。保存復元後は本来再構築される cache を同一と要求せず、保存されるゲーム状態と継続結果を比較する。
- 固定 fixture と命令を使い、既存 schema 1 validation で検査。小規模試験は輸送・混在53設備（ベルト40、ドリル4、router4、duo4、core1）、戦闘7設備（duo6、core1）。戦闘・混在は24敵で、初期弾数0。既存上限を変更しない。
- `World.save` / `World.load` を生成fixtureだけで実行し、固有tempディレクトリへ隔離。input/checkpoint bytesの不変、保存復元後の続行を検証。利用者のゲーム保存へ触れない。
- 初回・warmup・steady、path dirty/clean、命令・検証の計測領域外、normal先行の順序bias、未測定描画/ピークメモリ/実機が明示されている。

独立小検査: CPython 3.12.14 / Linux、small 3 scenarios、warmup 0、steady 8（初回を含み各9 tick）＋復元後3 tick。全シナリオ passed。性能JSONは保存しておらず、性能値としては使用しない。大きな性能測定は実施していない。

指摘: cache_state の距離が +inf/-inf を両方 None へ正規化し、差を見逃す。比較専用値なので距離配列そのものを比較する修正と回帰試験を依頼。将来の World 項目を黙って漏らさないカバレッジ検査も提案。

tests/docs の完成版、上記修正、正式生データのhash/数値の監査は未完了。このファイルは最終合格報告ではない。


## 測定ツール完成版と予備実測の再確認

上記±inf比較穴は、生の距離配列比較と回帰試験で修正済み。未知World属性は失敗にし、計装stepの例外でもfailed_attemptへfailed_calls内訳を保存する。完成コード・17本の試験・`docs/P_05_PROFILE_ja.md`を読み戻し、測定ツールに残るブロッカーはない。保存復元cache比較の境界も明記済み。

予備実測 `pilot.json` SHA256: `94bcbfc5f282cd7ebb99f52a69a4b1d259935fdcc38bd5efa02a5514a94f2bc0`。
ツールSHA256: `4d09c518fdc18ecf02d45aac9ff8e81b0ca1f4501d6030d09dcc4085b2417bae`。
実行本体SHA256: `bfd9606bb178016c2324e40378109dde32569c517fa25f256868d0751ab10fca`。
現ファイルhashと一致。standard各66tick、計198tickのverifiedおよびexclusive合計=step inclusive、各保存と3tick継続passedをJSONから監査した。これは公式最終性能値ではない。

battle steadyは砲台1920calls/exclusive148.319639ms、弾60calls/72.001276ms。未計装step p50=3.863253ms、計装p50=4.115889ms、比1.06539463。32砲台、192敵から184敵、実発射弾のみを扱う条件。初回やpath dirty区間に計装比が1を下回る観測もある。測定順・共有PC負荷・GC等を排除しておらず、計装費用や改善倍率をこの順位だけから断定していない。

親の依頼で次に `_tick_turret` の距離重複計算・候補リスト削減候補を独立レビューする。最終公式JSONと採否は未監査。


## 砲台標的選択候補のコードレビュー

`src/mindusnista/app.py` のHEADとの差分について、_tick_turret以外のASTが完全一致することを独立実行で確認。標的選択後の照準・reload・RNG・弾生成以降のソースもバイト不変。候補は hp > 0 の敵だけに、元と同じ **2 の距離式と閉射程 <= を用い、(距離, ID) のstrict最小を同じ挿入順で選ぶ。一致keyは先頭を維持し、NaN条件反転も行わない。有効な現Worldでは、単一呼出し中の位置/contentは不変で、元のfilter/minの結果と同じ敵になる。

比較器のBASELINE_SOURCEを `git show 9f466b9f43fd80c172f6e6a7de9db60fac7c004d:src/mindusnista/app.py` のAST行範囲と照合。バイト完全一致、SHA256 `f06cb4e4bdfafc0d418068dd17b63628cc6b8a761a2bbb6ccd132a6bcd2e8248` を確認。比較では現在のWorldを共用し、旧砲台methodだけ差替えるのでM15等の別差分を混ぜない。双方にMethodTypeをbindし、tick/repeatごとに実行順を交互にする。全状態/cacheを毎tick照合し、双方の実保存bytesと4状態の保存再開後3tick＋新place/remove命令も照合する。

新規12本は射程直前/境界/直後、距離とID優先、死/空/無弾薬、射撃角境界/reload/RNG/ID、無効な直接入力のNaN/inf除外、3seed×4実Worldシナリオ、順序交替、改変状態/例外失敗、実保存、出力保護を扱う。修正前の12本成功ログを読み戻し。これは挙動不変の最適化であり、既存挙動を変える不具合修正ではない。現時点で数値・状態・比較設計の残ブロッカーなし。

正式な性能値・採否と完成した対象選択docはまだ未監査。


## 対象選択doc・候補後ログ

`docs/P_05_TARGETING_ja.md` と `targeting-candidate-tests.txt` を確認。候補後12 unittest成功（3.789s）、最適化前326本+self-testは別履歴、原作戦闘/float32/超大規模/実機未達の境界は正確。候補の探索オーダーは依然として砲台数×敵数で、機能や個数を減らす変更ではない。

文言の明確化として、先行順の偏りは3repeatの初回標本について（全66tick・steady60tickでは各repeat同数）、exit2は引数不正を指しruntime読込等の実行失敗はexit1であることを担当へ依頼した。計測ソースに影響しないdocs修正であり、正式測定を止める指摘ではない。

この時点でコード・状態同値・計測器のレビューは完了。正式JSON・統合記録の数値/採否監査を待つ。


## 正式測定の独立監査（完了）

再ベンチマークは行わず、M1-05合流後の `docs/verification/P-05-20260910/` にある生JSON、commands.json、現在のソースを読み、集計とhashを独立再計算した。採用を妨げる残指摘はない。以下の性能値はLinux / CPython 3.12.14の共有PC上の観測であり、iPhoneの性能や原作戦闘互換の成功ではない。

### hashと実行記録

- runtime: `14ba5722ccfb0f3641452e10beb025d43bdbb63f8f77013dfe52bc9d555bc850`
- profile_world.py: `4d09c518fdc18ecf02d45aac9ff8e81b0ca1f4501d6030d09dcc4085b2417bae`
- check_target_selection.py: `5fe8011f36580e940043e1f48cb548f2c525b04b97b6493756fed968118fd204`
- 候補_turret: `e85f4e63c56dcec2ed388b00c979aaaf34d163fcb5fd530730eb46ffa2ed0911`
- world-profile-standard.json: `3abd31ce1c2dab1e4c8fb131ff7bf4bfcc3cbb2d3efd2afdc1b6b40a5b1e465c`
- target-selection-standard.json: `401feb5250f83efb6a5ba31c62224daeb14d1d2fa321c47da7e96d5ee2e9a4f4`

報告された各ソースhashが現ファイルと一致し、候補methodも実生成物のAST行範囲から再計算して一致。commands.jsonの実行引数はstandard/all/steady60/warmup5、対象比較はrepeat3で、双方終了0とpassedを記録している。

### 状態・件数・集計の確認

測定器3条件×66tick＝198 paired ticks、対象比較4条件×3repeat×66tick＝792 paired ticksについて、成功標本数・各verified・tick連番・命令と順序交代・保存と3tick続行のpassedを確認した。対象比較の4World続行は、元の基準/候補と復元の基準/候補へ同じ新しい配置/撤去命令を適用するコードを既にレビューしている。to_dictにrng_state・next_id・全敵/弾/設備/在庫/統計が含まれることと毎tickの比較呼出しを確認済み。今回は実行後の生JSONを監査しており、全ワールドを独立再実行したという意味ではない。

さらに共通の輸送/戦闘/混在条件について、測定器と対象比較の全repeat間で、初期digest・各66tickのdigest・命令・checkpoint SHA256がすべて一致することを独立assertした。基準/候補の保存bytesハッシュも一致し、入力/checkpointの不変と続行一致がすべて記録されている。

全first/warmup/steady/path dirty/path clean集計の件数・total・median・nearest-rank p95・最大と、全methodのcalls/inclusive/exclusiveを生標本から再算し完全一致。測定器の全tickでexclusive合計=step inclusive、failed_calls=0。対象比較の各repeatは同じ毎tickdigestを持つ。

実負荷は輸送/混在373設備（ベルト336、ドリル12、分配器12、デュオ12、コア1）、戦闘33設備（デュオ32、コア1）。戦闘は初期192敵→続行後184敵、最大弾29、69tick後shots124/kills8。混在は192敵を維持、最大弾21、69tick後shots36/kills0。通常開始は48×32・21設備・この短い測定中は敵0。これらを超大規模達成や高弾数一般の結果へ拡大しない。

### 対象比較の独立集計

各条件3repeatのsteady計180標本をpoolした値（ms）:

| 条件 | 基準p50 | 候補p50 | 基準p95 | 候補p95 |
|---|---:|---:|---:|---:|
| 通常 | 0.019395 | 0.018971 | 0.034980 | 0.033528 |
| 輸送 | 1.3774135 | 1.3921065 | 2.171911 | 1.885135 |
| 戦闘 | 3.784668 | 2.804693 | 5.970361 | 4.663051 |
| 混在 | 3.4405845 | 3.0085175 | 8.983712 | 9.016767 |

各repeatのp50比（候補/基準）:

| 条件 | 1回目 | 2回目 | 3回目 |
|---|---:|---:|---:|
| 通常 | 1.130777 | 0.968005 | 1.038923 |
| 輸送 | 1.012934 | 1.003553 | 1.013021 |
| 戦闘 | 0.710222 | 0.766964 | 0.762968 |
| 混在 | 0.870146 | 0.868631 | 1.007060 |

戦闘は全3repeatでp50とp95が改善し、pool p50は約25.89%短い。混在pool p50は約12.56%短いが、3回目p50は約0.706%長く、pool p95も約0.368%長い。輸送pool p50は約1.067%長い。通常は短い時間のばらつきがあり、poolが少し短いことを安定した改善とは呼ばない。結果の悪い条件を隠さず併記することを親へ伝達した。

完全状態同値、戦闘の3repeatでの一貫したp50/p95改善、最小のコード差分を根拠に、現行の暫定戦闘処理への限定採用は妥当と判断する。全条件が高速化したとの主張、並列化成功、機能/効果/上限の完成、Pythonista持続性能への一般化は認めない。共有PC・GC・測定順・周波数等の影響は排除されていない。

この独立レビューはコード・正式生データ・集計の監査を完了した。後から作られる統合文書やGitHub保存/CI/マージの実在確認は親の担当であり、このレビューで実施済みとはしていない。

## 追加確認: 作業用一時ディレクトリ

正式測定と単独CLIテストに一致する合成入力が作業環境に残存していた。
レビュー担当は作成・復元・削除しておらず、残存原因は未確定。
TemporaryDirectoryを呼ぶ設計と限定cleanup試験は確認したが、正式JSONは全runの消失を確認していない。
実削除成功の表記はこの範囲へ訂正する。rootは原本をリポジトリ外へ保存し配布へ含めない。
