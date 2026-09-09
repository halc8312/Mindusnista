# Mindusnista

Mindustry のゲーム本体を **iPhone の Pythonista 用 Python に移植する非公式プロジェクト**です。
現時点は **0.1.2-dev の部分移植**。完全移植は目標であり、完成・原作完全互換を表すものではありません。
WebView 埋め込みやリモートプレイへの置き換えは、このプロジェクトの目的ではありません。

## 開始

**Work へ引き継ぐ人:** [START_HERE_ja.md](START_HERE_ja.md) を読み、
[初回プロンプト](prompts/01_START_WORK_ja.txt) を使ってください。

**作業するエージェント:** [AGENTS.md](AGENTS.md) → [引き継ぎ](docs/HANDOFF_ja.md)
→ [移植台帳](PORT_STATUS.md) → [次の作業](docs/NEXT_TASK_ja.md) の順に読みます。

**iPhone で遊ぶ人:** `mindustry_pythonista.py` を Pythonista 本体のエディタで開き実行します。
操作・保存先は [README_ja.md](README_ja.md) を参照。
実行時に pip、JVM、外部アセット、ネット接続は不要です。旧ファイルとセーブは退避してください。

## 検査

```sh
python tools/check_project.py
```

Python 3.10 互換を開発上の目標とします。PC 上のシミュレーション・模擬 UI テストであり、iPhone 実機試験ではありません。
引き継ぎ準備時に **117 tests + self-test 成功**。詳細は [今回の再検査記録](docs/HANDOFF_VERIFICATION.md)。
GitHub Actions 設定は同梱していますが、引き継ぎ準備時点では GitHub 上で実行していません。

M0-01 での新しい実行結果・保存状況は [基準版移入の検証記録](docs/M0_01_VERIFICATION_ja.md) を参照。
今回もゲーム本体・版番号・既存テストは変更していません。

M0-02 では [配布生成](docs/RELEASE_ja.md) を実装しました。
`python tools/build_release.py` で本体と一致する単体 `.py`、ソース ZIP、SHA256 一覧を生成できます。
配布対象は明示したファイルのみで、既存の異なる出力を上書きしません。

## 現在できること／できないこと

コア、ドリル、ベルト、ルーター、デュオ、銅の壁を使う小さなデモです。
一部の輸送・採掘計算は原作参照、ワールド・敵・戦闘・独自 JSON 保存は暫定実装です。
0.1.2 では四方向ボタン、90 度回転、設置プレビュー、設置済みベルトの回転を追加しました。
電力、液体、製造、原作ユニット、キャンペーン、原作ファイル、通信、既存 MOD 互換等は未実装です。

0.1.1 の起動成功はユーザー報告あり。**0.1.2 の実機結果は未報告**です。
[DEVICE_TESTS.md](DEVICE_TESTS.md) と [PORT_STATUS.md](PORT_STATUS.md) を区別して管理します。

## 保存・開発の基準

対象リポジトリ: https://github.com/halc8312/Mindusnista

初回は添付一式を作業ブランチへ移入し、テスト後に PR を作ります。
GitHub に取り込んだ後は最新のコミットを基準とし、古い添付 ZIP で上書きしません。
チャット、ローカル編集、GitHub 保存、main への統合、iPhone 実機成功は別々の状態です。

## ライセンス

GPL-3.0-only。既存の [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)、[SOURCES.md](SOURCES.md) を継承します。
原作の名称・作者との公式な関係を示すものではありません。原作のメディア素材は同梱していません。
この引き継ぎはゲーム本体・テストを変更せず、開発資料、検査用マニフェスト、CI 設定を加えたものです。
