# ARCH-01 要件・並列化・セーブ共有の調査記録

作業日: 2026-09-10。開始 main: `ad2124f29e79d243b9ad6f0292e4abde20ccafd4`。
作業ブランチ: `docs/full-port-requirements`。0.1.2-dev / v159.7 / 独自保存 schema 1 を維持。

## 変更

超大規模・高負荷、原作 iOS/Steam とのセーブ共有、エフェクト品質をユーザー指定の完成要件として記録。
現行のマップ・敵・保存の暫定上限を監査し、完成仕様に流用しないことを明記した。
並列化と原作保存の一次資料を調査し、P-01 / S-01 / R-01 を早期検証として計画へ追加。
AGENTS、ロードマップ、次タスク、台帳、実機試験予定、README、出典と配布一覧を更新した。

本体・src・テストの変更はない。加速器、原作 codec、新しい効果の実装ではない。
本体のバイト一致と SHA256 は [scope.json](verification/ARCH-01-20260910/scope.json) に記録した。
原作 v159.7 の完全コミットは `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c` と tag ref で確認。

## 実行検査

Linux x86_64 / CPython **3.12.14**。今回の環境を過去の 3.12.13 と区別する。
変更前の `python tools/check_project.py` は **172 unittest と self-test 成功**、失敗・エラー・skip なし。
Python 3.10 AST 構文検査と単体生成物の同期検査も成功した。3.10 実行の代わりにはしない。

- [変更前コマンド・環境・終了コード](verification/ARCH-01-20260910/before-check-project.json)
- [変更前の全出力](verification/ARCH-01-20260910/before-check-project.txt)
- [変更後コマンド・環境・終了コード](verification/ARCH-01-20260910/after-check-project.json)
- [変更後の全出力](verification/ARCH-01-20260910/after-check-project.txt)

変更後も **172 unittest と self-test 成功**、失敗・エラー・skip なし。構文・生成同期検査も成功。
GitHub CI はこの作業の PR で head SHA と結果を照合し、
PR 本文に実在する commit・run・job の証跡を追記する。過去の PR の緑表示を今回の結果にしない。
資料の差分・ローカル参照・配布一覧を検査して保存する。

## 未実施と次の作業

Pythonista の並列性・Accelerate/Metal の実行、負荷やエフェクトの端末測定、原作セーブの実往復は未実施。
0.1.1 起動成功のユーザー報告を維持し、UI-01 の総合実機結果は未確認のまま。
172本と1,504件の抽出計算は、超大規模対応・原作全体互換・実機成功の証拠ではない。

次は M1-01 の輸送比較を主軸に、独立する P-01 の数値比較器、S-01 の原作保存読取診断を実装する。
[次タスク](NEXT_TASK_ja.md)、[完成要件](FULL_PORT_REQUIREMENTS_ja.md)、
[並列化調査](PARALLEL_RESEARCH_ja.md)、[セーブ調査](SAVE_COMPATIBILITY_RESEARCH_ja.md) を参照。
