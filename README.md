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

M0-01 の実行結果・保存状況は [基準版移入の検証記録](docs/M0_01_VERIFICATION_ja.md) を参照。
M0-01 当時はゲーム本体・版番号・既存テストを変更していません。

M0-02 では [配布生成](docs/RELEASE_ja.md) を実装しました。
`python tools/build_release.py` で本体と一致する単体 `.py`、ソース ZIP、SHA256 一覧を生成できます。
配布対象は明示したファイルのみで、既存の異なる出力を上書きしません。

M0-03 から編集元は `src/mindusnista/`、root の `mindustry_pythonista.py` は生成物です。
`python tools/build_single_file.py` → `python tools/check_project.py` の順に更新・検査します。
iPhone では従来どおり生成した単体 `.py` を開きます。M0-03 当時の生成物は分割前とバイト一致しました。

UI-01 ではマス単位の位置調整と誤スライド対策を追加し、単体 `.py` も再生成します。
検査結果・GitHub 保存状況は [UI-01 の検証記録](docs/UI_01_VERIFICATION_ja.md) を参照。

## 現在できること／できないこと

コア、ドリル、ベルト、ルーター、デュオ、銅の壁を使う小さなデモです。
一部の輸送・採掘計算は原作参照、ワールド・敵・戦闘・独自 JSON 保存は暫定実装です。
0.1.2 では四方向ボタン、90 度回転、設置プレビュー、設置済みベルトの回転を追加しました。
UI-01 では設備選択中の「マス操作」で矢印を位置調整に切り替え、「置く」で確定できます。
下部は3段・16ボタンを維持。通常のタップ設置は継続し、ベルト・壁・撤去の連続操作は
0.35秒の静止保持で準備してからスライドします。準備前に滑ったタッチでは設置・撤去しません。
電力、液体、製造、原作ユニット、キャンペーン、原作ファイル、通信、既存 MOD 互換等は未実装です。

0.1.1 の起動成功はユーザー報告あり。方向変更・連続設置への操作所感と誤スライドの報告はありますが、
そのときの版・端末条件は未確認です。**UI-01 変更後の実機試験は未確認**です。
[DEVICE_TESTS.md](DEVICE_TESTS.md) と [PORT_STATUS.md](PORT_STATUS.md) を区別して管理します。

## 保存・開発の基準

対象リポジトリ: https://github.com/halc8312/Mindusnista

初回は添付一式を作業ブランチへ移入し、テスト後に PR を作ります。
GitHub に取り込んだ後は最新のコミットを基準とし、古い添付 ZIP で上書きしません。
チャット、ローカル編集、GitHub 保存、main への統合、iPhone 実機成功は別々の状態です。

## ライセンス

GPL-3.0-only。既存の [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)、[SOURCES.md](SOURCES.md) を継承します。
原作の名称・作者との公式な関係を示すものではありません。原作のメディア素材は同梱していません。
初回の引き継ぎはゲーム本体・テストを変更せず、開発資料、検査用マニフェスト、CI 設定を加えた作業でした。
