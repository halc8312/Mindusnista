# 0.1.2追加参照（2026-09-09確認）

- Pythonista scene API: https://omz-software.com/pythonista/docs-3.4/py3/ios/scene.html
- Codex CLI: https://developers.openai.com/codex/cli/
- Project instructions: https://developers.openai.com/codex/guides/agents-md/

今回の方向UIは本移植版の新規実装で、原作UIの完全移植を意味しません。
以下は旧版から継承したゲームロジックの参照情報です。

# Primary references

M1-01（2026-09-10）: 上記固定版の Conveyor.java の更新と引渡しを
`reference/ConveyorTransferReference.java` へ抽出・改変。fixture の条件、Java float / Python double の
公差、cached minitem / mid 等の残差は [M1-01 検証記録](docs/M1_01_VERIFICATION_ja.md) を参照。
原作本体を起動した oracle ではありません。

2026-09-10: [v159.7 tag ref](https://api.github.com/repos/Anuken/Mindustry/git/ref/tags/v159.7)
を取得し、完全コミット `c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c` を確認。
保存形式の固定コミット参照は [原作セーブ調査](docs/SAVE_COMPATIBILITY_RESEARCH_ja.md)、
Pythonista/NumPy/CPython/Apple の API 根拠は [並列化調査](docs/PARALLEL_RESEARCH_ja.md) に記録。
これらの調査は実機の性能、原作データの往復、完全互換性の実証ではない。

Checked on 2026-09-09. Implementation reference is pinned to **v159.7**, not an unpinned `master`.
The original complete Java files are not bundled; the isolated modified reference in `reference/` documents its extracted scope.

| Reference | Used for |
|---|---|
| https://github.com/Anuken/Mindustry/releases/tag/v159.7 | Stable reference release (short commit displayed by release: c9686eb) |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/world/blocks/distribution/Conveyor.java | Lines 24–25: item spacing/capacity; 239–249: movement; 320–348: acceptance/insertion; 422–440: list management. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/world/blocks/production/Drill.java | Hardness/warmup defaults, getDrillTime, ore choice, dry update branch. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/world/blocks/distribution/Router.java | Capacity 1, speed 8, output delay distinction. Full unit control and overflow handling are not ported. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/content/Blocks.java | Selected six block definitions; conveyor speed, mechanical drill cost/time, core health/capacity, wall health, Duo copper bullet values. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/content/Items.java | Copper and lead hardness, ordering, colors. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/core/src/mindustry/world/Block.java | Default item capacity 10, dump interval 5, default health scaling. |
| https://raw.githubusercontent.com/Anuken/Mindustry/v159.7/LICENSE | GPLv3. The same standard GPLv3 text is included locally in LICENSE. |
| https://omz-software.com/pythonista/docs-3.4/py3/ios/scene.html | Scene, Node, SpriteNode, LabelNode, Texture(ui.Image), coordinates, touch callbacks, dt, pause/resume/stop, frame_interval. |
| https://omz-software.com/pythonista/docs-3.4/py3/ios/ui.html | ImageContext, Path drawing, colors used by the procedural texture adapter. |

## Evidence boundaries

The test fixtures are **not** captures from a running, full Mindustry game.
They are outputs of the included isolated Java reference using the source's float arithmetic.
They only establish agreement for the selected kernels within the documented tolerances.

The mocked scene/ui tests are **not** Pythonista execution. They only exercise Python-side logic.
There is no iPhone screenshot, hardware benchmark, original-save round trip, or multiplayer test in this release.

## Pythonista lifecycle documentation consulted for 0.1.1

https://omz-software.com/pythonista/docs-3.4/py3/ios/scene.html

Official Scene.setup/update/did_change_size/pause/resume/stop documentation.
Consulted 2026-09-09. This documentation does not identify the device-specific
initial exception from the reported missing-_failed traceback.

## P-01 開発専用CIのNumPy条件

Python 3.10には1.26.4（公式対応3.9～3.12）、3.13には2.3.5（3.11～3.14）を指定。
[1.26.4公式ノート](https://github.com/numpy/numpy/blob/v1.26.4/doc/source/release/1.26.4-notes.rst)、
[2.3.5公式ノート](https://github.com/numpy/numpy/blob/v2.3.5/doc/source/release/2.3.5-notes.rst)。
2026-09-10取得。これは開発CIの条件で、Pythonista同梱版の推定ではない。
