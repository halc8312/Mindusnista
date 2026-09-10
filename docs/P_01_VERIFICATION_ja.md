# P-01 最初の比較器の統合検証

2026-09-10。統合起点 main: `1b3d7ed92b1e7b2df275c0ae549c969f27237e03`（M1-01）。
ブランチ: `tools/pythonista-parallel-probe`。本体は M1-01 と同じバイト列、0.1.2-dev / schema 1を維持。

比較器は独立worktreeで作成し、検証済みM1-01を取り込んでから統合検査した。
追加前のゲーム基準179本は [M1-01の検査](verification/M1-01-20260910/after-check-project.txt) を参照。
比較器の個別11メソッド、Linux / CPython 3.12.14 / NumPy 2.3.5で成功。
統合後は **190 unittest と self-test 成功**、失敗・エラー・skipなし。Python 3.10 ASTと生成同期も成功。
分割・全件照合・欠如時の未実行・不一致の失敗・単体CLI・出力保護を確認した。
独立レビューで見つかった遅延flush/close失敗は先に回帰を再現し、保存成功表示前に失敗を報告するよう修正。
保存したテキストログは行末空白のみ除去した。

- [統合検査の環境・終了コード](verification/P-01-20260910/after-check-project.json)
- [統合検査の全出力](verification/P-01-20260910/after-check-project.txt)
- [20,000件の測定](verification/P-01-20260910/numpy-probe-20000.json)
- [200,000件の測定](verification/P-01-20260910/numpy-probe-200000.json)
- [本体一致](verification/P-01-20260910/scope.json)

測定は出力close修正前に行った。計測する数値・分割・時間区間はその修正で変更していない。
少ない反復と固定順によるPCの観測で、性能の一般的な倍率ではない。
両件数・全ワーカーで全結果一致。ただしNumPyの総時間はPython基準より遅く、採用を決める結果ではない。
入力変換等の内訳分析、配列常駐、実機持続試験を次へ残した。

CIは開発専用依存としてPython 3.10にNumPy 1.26.4、3.13に2.3.5を指定し、実NumPy試験の実行を確かめる。
対応するPython版は各NumPyの公式リリースノートを確認した。iPhoneでのpip導入を必要にする変更ではない。
NumPyのないPCでも標準ライブラリの比較器は起動する。その場合、実NumPy試験1本のskipを未実行と明記する。
各CI結果は対象headとログを読み戻してPRに記録する。JDK参照もM1-01から継続する。

Pythonistaでの比較器起動・NumPy同梱版・CPU同時実行・FPS・発熱・実ピークメモリは未確認。
Accelerate・Metal・原作セーブ互換は今回未実装。ゲームの機能・規模・効果は削っていない。
[次の作業](NEXT_TASK_ja.md) はM1-02、P-02、S-01を参照。
