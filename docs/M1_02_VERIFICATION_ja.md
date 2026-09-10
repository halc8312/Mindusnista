# M1-02 コンベアのキャッシュ・搬入順・保存再開

2026-09-10。起点 main `787aabd28593519c996ed79a6aa8ea3cdb741ba4`、ブランチ `port/conveyor-cache`。
0.1.2-dev / Python 3.10互換 / 独自保存 schema 1 / GPL / Pythonista単体配布を維持する。
UI-01、起動ガード、保存先・原子的書込、計算カーネルは変更しない。

## 原作と変更範囲

原作 v159.7、固定コミット `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c` の
[Conveyor.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/world/blocks/distribution/Conveyor.java)
を読み直した。`updateTile`、`acceptItem`、`handleItem`、`add` の通常単品搬入を対象とする。

- `minitem` / `mid` は搬入ごとに再計算せず、コンベア更新開始時にリセットし、逆順の移動・搬出中に更新する。
- 受入判定と同方向の前方間隔は保存した `minitem` を使う。後方入力は配列の0、側方は保存した `mid` へ挿入する。
- 複数搬入後の配列をsortしない。位置が非昇順でも原作の通常搬入で生じる順序を維持する。
- 固定ソースの通常経路では `lastInserted` は0のまま。横位置の引継ぎもその位置を使う。

既存テスト2本の「1回搬入した直後は必ず拒否」という期待は、上記の原作更新時点と矛盾するため変更した。
同じ更新前なら次の搬入も受理し、更新後は拒否することと品目順を検査する。容量・前方拒否等は維持する。
前方の詰まり試験は「前回更新で計算済み」のキャッシュをfixtureに明示した。

## 保存の互換性

Buildingに `conveyor_minitem` と `conveyor_mid` を追加し、schema番号は1のままとする。
両方がある保存はキャッシュと配列順をそのまま復元する。片方だけの欠落は不正。
minitemは有限数0〜1、midはbool以外の整数0〜min(個数,1)。非コンベアは1/0のみ。
品目・容量・座標等の従来の検証は残す。意図的に古いキャッシュなので、現在位置の最小値との等値は要求しない。

旧schema 1で両方が欠ける場合、従来通り昇順の荷物を要求し、現在位置から最小値を復元する。
midは末尾から逆順に、位置が厳密に0.5より大きいとき index-1 を記録する。
移動や搬出を実行せず、品物の座標・在庫・tick・乱数状態を変更しない。
旧版に存在しなかったキャッシュ履歴を完全に再現したという意味ではなく、決定的な移行規則である。

**旧保存を新版で読めるが、新版の保存を旧スクリプトで読める保証はない。**
旧版は追加フィールドを受け付けないため、戻す場合に備えて旧スクリプトと旧保存を退避する。
原作 `.msav` の共有対応ではない。

## 実行した検査

Linux / CPython 3.12.14 / NumPy 2.3.5。変更前190本、変更後 **211 unittestとself-testが成功**。
失敗・エラー・skipは各0。Python 3.10 ASTと単体生成の同期も成功。
18本の搬入・キャッシュ・保存回帰を先に追加し、修正前に7失敗・20 subtestエラー、修正後は成功を確認した。
さらに比較器のキャッシュ不一致検出・不正値拒否・全traceの貨物保存を3本で検査した。

- [変更前の環境](verification/M1-02-20260910/before-check-project.json) / [全出力](verification/M1-02-20260910/before-check-project.txt)
- [回帰の修正前](verification/M1-02-20260910/cache-before.txt) / [修正後](verification/M1-02-20260910/cache-after.txt)
- [変更後の環境・本数](verification/M1-02-20260910/after-check-project.json) / [全出力](verification/M1-02-20260910/after-check-project.txt)
- [本体・カーネルのSHA256と変更範囲](verification/M1-02-20260910/scope.json)
- [実際の旧コードによる移行確認](verification/M1-02-20260910/legacy-migration.json)

旧mainのコードでデモを500tick実行して保存し、新版への読込で既存データが変わらないことも確認した。
移行後の保存と再読込は新版同士で500tickのdigestが一致した。利用者の実セーブは使っていない。
旧版と新版で移動を開始した後のゲーム処理が等しいという試験ではない。

## Java抽出比較と残差

既存11シナリオ・22更新を維持し、計20シナリオ・59明示更新へ拡張した。
後方→側方、側方→後方、両側方、古いキャッシュによる受入・前方間隔、空状態リセット、mid=1を含む。
初期キャッシュは明示し、密集した連続後方入力等の人工境界はfixture内で区別する。
Java/Pythonの位置・minitemは絶対公差2e-6、品目順・個数・mid・lastInsertedは完全一致を要求する。
毎更新の品種別貨物保存も検査する。fixture schema 2は開発用形式で、ゲーム保存のschemaではない。

ローカルではPython traceの形・範囲・貨物保存が成功。
javac不在、javaはlibjli.so不足のため **Java比較は未実行**、終了コード2と記録した。
[診断とPython trace](verification/M1-02-20260910/local-reference.json) を参照。
GitHub CIのJDK17で比較を実行し、対象headの結果を読み戻してPR本文に記録してからマージする。

通常の空開始・搬入・移動・回転で到達する状態では、搬出される荷物は配列の現末尾になる。
任意に手編集した配列まで原作同値とはしない。例えば非末尾にy=1を作った異常配列では、原作の
`len=min(i,len)` は他のslotも除外する一方、Pythonは渡した1品のみ削除して他の荷物を保持する。
人工的なmid=1の挿入API試験も、通常生成状態の互換根拠と区別する。

抽出コードは原作エンジンではない。原作scheduler、チーム、効率、sleep、stack API、原作シリアライズ、
全体の採掘・分配器・描画は未比較。1,504件の独立計算比較とも別の検査である。
Pythonista実機、超大規模性能、原作全体互換は未確認。次はM1-03で更新順とoffload/dumpの統合境界を追う。
