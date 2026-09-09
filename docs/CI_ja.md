# CI 設定

`.github/workflows/ci.yml` は GitHub Actions で `python tools/check_project.py` を実行する設定です。
Ubuntu の Python 3.10 / 3.13 を指定しています。追加 pip 依存はありません。
`contents: read` とし、push、pull_request、手動実行を対象にしています。
ゲームの公開・リリース作成・main マージ・認証情報の登録は行いません。

**設定ファイルを用意しただけで、GitHub 上の成功を確認したわけではありません。**
引き継ぎ作成時のテストは Linux CPython 3.13.5 でした。3.10 は構文検査のみ。
実際の CI 実行で 3.10 による実行結果を取得し、実機テストとは分けて記録してください。

この設定は公式 Python CI 例を参照して checkout@v6 / setup-python@v5 を使います。
GitHub 側で Actions が許可されていること、連携が workflow ファイルを更新できることを確認します。
許可がなければそれを報告し、個人トークンを本文に要求したり、設定を無断変更したりしないこと。
将来 Actions の参照を更新・SHA固定する場合は公式リポジトリで確認してください。

`tools/verify_handoff.py` は最初の ZIP 受領時の検査です。
その後に意図的にコードや文書を修正するとハッシュは変わるので、固定マニフェストを将来の CI で強制しません。

出典（2026-09-09確認）:
https://docs.github.com/en/actions/tutorials/build-and-test-code/python
