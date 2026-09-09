# 0.1.1-dev テスト報告

実施日：2026-09-09。対象ファイル：`mindustry_pythonista.py` **0.1.1-dev**。

## 結果

**89テストが成功しました。** 既存68本と、今回追加した起動・初期化・保存先・例外報告の回帰テスト21本です。

```text
Ran 89 tests in 1.787s

OK
```

`test-results.txt` に実行済みの全テスト名と結果を収録しています。
組込セルフテストも成功し、`self-test-results.txt` に結果があります。

## 実行環境

CPython **3.13.5** / Linux。Pythonistaの `scene` / `ui` は同梱の模擬モジュールを使用しました。
Python 3.10構文は `ast.parse(feature_version=(3, 10))` で検査しました。
**Python 3.10そのものでの実行試験ではありません。**

```sh
python -m unittest discover -s tests -v
python mindustry_pythonista.py --self-test
python -m py_compile mindustry_pythonista.py tests/test_startup_regressions.py
```

## 旧版での再現

0.1.0を同じ模擬scene/uiで起動し、次の二通りで同じAttributeErrorを確認しました。

```text
BEFORE SETUP: AttributeError 'MindustryScene' object has no attribute '_failed'
FIRST ERROR: PermissionError synthetic storage access failure
SECOND ERROR: AttributeError 'MindustryScene' object has no attribute '_failed'
```

これは合成した条件での再現であり、ユーザーの端末における最初の例外や発生順の確定ではありません。

## 追加した21本

1. コンストラクター直後のフラグ初期化。
2. setup前のupdateから一度だけ初期化し、後続setupで二重初期化しないこと。
3. 0×0サイズ時には初期化せず、有効サイズを受けてから起動すること。
4. setup前のタッチ・休止・復帰・終了・保存・リサイズで未初期化状態を参照しないこと。
5. 初期化途中に合成した再入コールバックで未完成のワールドを使わず、保存しないこと。
6. 模擬の親コンストラクターがコールバックやsetupを呼んだ場合のフラグ保護。
7. 起動時の元の例外を保持し、後続通知が再初期化や二次AttributeErrorを起こさないこと。
8. 更新エラーを一度だけ報告し、その後に保存を上書きしないこと。
9. ログ書き込み自体の失敗が、最初のTracebackを置き換えないこと。
10. 主保存先にログを書けない場合の代替ログ保存。
11. エラー画面のLabel描画自体の失敗が最初のTracebackを置き換えないこと。
12. 保存を読み込んだ後のレイアウト失敗でも、既存autosaveがバイト単位で変わらないこと。
13. リサイズ中の例外を安全な停止処理で扱うこと。
14. 書込可能な元の保存先を優先し、既存ファイルを変更しないこと。
15. 元の保存先を作れないときに代替保存先を選び、通知すること。
16. 読取専用を模擬した保存先の既存セーブを移動・削除せず、代替先を使うこと。
17. 両方の保存先が失敗しても未初期化エラーを連鎖させないこと。
18. 代替先を選んだシーンの起動と、その選択先への保存。
19. モジュールの `__file__` を後から削除した合成条件での起動と新規デモ。
20. 実行開始時に固定したスクリプトディレクトリーから設定を読むこと。
21. 従来の保存形式での読み込みとシミュレーション状態の一致。

## 既存処理の保護

旧版から続く68本（シミュレーション54本、模擬画面アダプター14本）も再実行して成功しました。
原作由来の計算と保存済みJava参照fixtureとの比較も、その既存テストに含まれます。
今回Javaコンパイラーを再実行してfixtureを生成し直したわけではありません。

旧版と新版の `World` クラスをASTで比較し、処理が変更されていないことを確認しました。
既存のトップレベル関数／クラスで変更したものは `data_directory` と `make_scene_class` です。
保存先の補助関数を新設し、保存フォーマットのバージョンは1のままです。

## 限界

**実機のPythonista/iOSは未検証です。** 実際の描画、タッチ入力、OS通知の順序、
Filesアプリ／File Providerのアクセス権、iPhoneのFPSやメモリーは検証していません。

今回報告された未初期化エラーが起きるコード経路を修正したもので、ユーザーの端末で
すべての起動条件が満たされる保証ではありません。別の起動エラーが残る場合は、
最初の原因を記録して次の修正につなげられるようにしています。

0.1.0時点の履歴は `history/TEST_REPORT_0.1.0.md` を参照してください。
