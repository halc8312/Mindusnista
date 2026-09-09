# 0.1.2 コード案内

基準版の AST から作成した案内です。下表の行番号は初回 0.1.2-dev 当時のものです。
UI-01 では UI と定数の追加により行番号が変わったため、現在の編集では名前で検索してください。

M0-03 から root の本体は生成物です。編集元は次の二つです。

| 編集元 | 対象 |
|---|---|
| `src/mindusnista/kernels.py` | ITEM_SPACE / BELT_CAPACITY、clamp / approach / conveyor_accepts / advance_conveyor_positions |
| `src/mindusnista/app.py` | World・採掘・コンテンツ・保存・起動・Pythonista UI・GPL 全文 |

`tools/build_single_file.py` が app の明示した relative imports を kernels の原文で置換します。
編集後は再生成し、`--check` と `tools/check_project.py` で更新漏れを確認します。
M0-03 時点では生成物が元とバイト一致していました。UI-01 の操作変更後は本体も更新しています。
分割対象を増やす場合は bundler の `EXPORTS`・対応テスト・配布一覧も更新します。

| 名前 | 行 |
|---|---|
| `clamp` | 88–89 |
| `approach` | 92–93 |
| `finite_number` | 96–101 |
| `integer` | 104–107 |
| `validate_content` | 110–141 |
| `load_content` | 144–157 |
| `read_json` | 160–165 |
| `atomic_json` | 168–181 |
| `conveyor_accepts` | 184–198 |
| `advance_conveyor_positions` | 201–219 |
| `BeltItem` | 223–226 |
| `Building` | 230–248 |
| `Enemy` | 252–263 |
| `Bullet` | 267–274 |
| `segment_circle_hit` | 277–292 |
| `World` | 295–939 |
| `data_directory` | 942–943 |
| `private_data_directory` | 946–948 |
| `prepare_data_directory` | 951–983 |
| `self_test` | 986–1006 |
| `benchmark` | 1009–1020 |
| `make_scene_class` | 1025–2047 |
| `run_pythonista` | 2050–2058 |
| `main` | 2741–2751 |

## World のメソッド

| 名前 | 行 |
|---|---|
| `__init__` | 301–327 |
| `uid` | 329–332 |
| `random` | 334–337 |
| `inside` | 339–340 |
| `index` | 342–343 |
| `at` | 345–346 |
| `size_of` | 348–349 |
| `center` | 351–353 |
| `tiles` | 355–359 |
| `cores` | 361–362 |
| `invalidated` | 364–369 |
| `neighbors` | 371–383 |
| `mine_info` | 385–394 |
| `can_place` | 396–421 |
| `place` | 423–439 |
| `remove` | 441–454 |
| `incoming_direction` | 456–468 |
| `front` | 470–472 |
| `accepts` | 474–491 |
| `receive` | 493–512 |
| `offload` | 514–523 |
| `_tick_drill` | 525–554 |
| `_tick_conveyor` | 556–572 |
| `_tick_router` | 574–590 |
| `_tick_turret` | 592–619 |
| `rebuild_path` | 621–651 |
| `_tick_enemy` | 653–687 |
| `_tick_bullets` | 689–710 |
| `start_wave` | 712–719 |
| `spawn_enemy` | 721–730 |
| `step` | 732–762 |
| `demo` | 765–796 |
| `to_dict` | 798–812 |
| `from_dict` | 815–928 |
| `save` | 930–931 |
| `load` | 934–935 |
| `digest` | 937–939 |

## テスト

`tests/test_engine.py`: 抽出 Java fixture、World、資源・保存など。
`tests/test_pythonista_adapter.py`: scene/ui 注入境界。
`tests/test_startup_regressions.py`: 初期化・保存先・最初の例外の保持。
`tests/test_rotation_controls.py`: 方向・回転・タッチ・配置・旧保存。
`tests/test_placement_controls.py`: マス操作、候補の確定、長押しと誤スライドの取消。
`tests/pythonista_stub.py`: 模擬 scene/ui。実機や iOS エミュレーターではない。

`reference/ConveyorKernelReference.java` と `java_fixtures.json` は抽出計算参照。
原作全コード・アセットはこのフォルダーにない。実装時には SOURCES.md の固定タグの原作を読む。

UI-01 の入口は app の `layout` / `move_preview` / `_perform` / `arm_build_gesture` /
`touch_began` / `touch_moved` / `touch_ended` です。World と kernels は今回変更していません。
