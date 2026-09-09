# Project instructions

## Goal and truthfulness

Build a Pythonista-native Python port of Mindustry, pinned to upstream v159.7.
This is currently a small partial port with substantial original scaffolding, not a complete port.
Read PORT_STATUS.md, DEVICE_TESTS.md and DEVELOPMENT_ja.md before planning the next change.
Keep source-based logic, transplanted constants, approximations and unimplemented scope distinct.
Do not replace the goal with an embedded web game. Do not claim full parity from kernel fixtures.

## Runtime and source layout

- Deliverable: mindustry_pythonista.py, runs directly in Pythonista without pip or runtime network.
- Python 3.10-compatible syntax/API. Core must import on a PC without scene/ui.
- World and kernel functions are headless. make_scene_class(sc, ui) is the injected UI adapter.
- Current release 0.1.2-dev; original save schema is 1. Old saves must remain readable.
- Keep the _ready/_failed startup guards, stable paths, atomic save writes and first-error reporting.
- Never delete or silently move user saves. Do not include personal saves in commits/releases.
- A future module split must preserve a reproducible single-file bundle for iPhone users and include bundle tests.
- No new third-party runtime dependency or native iOS assumptions without explicit discussion.

## Tests and evidence

Run `python tools/check_project.py` after changes. 0.1.2 baseline: 117 unittest tests.
Tests use scene/ui doubles, not actual iPhone execution. Record interpreter/OS and device limits.
reference/java_fixtures.json comes from the existing extracted Java kernel; it is not a full game oracle.
Add a failing regression for each bug before the fix, and avoid large unrelated rewrites.
Keep resource/cargo conservation, rotation coordinates, gesture cancellation, save round-trips and old startup regressions.
Update README_ja.md, PORT_STATUS.md, DEVICE_TESTS.md and TEST_REPORT.md where relevant.

## Porting method

Port one bounded upstream subsystem at a time. Record source tag/path, exceptions, intended invariants and comparison method.
Prioritize integrated transport/adjacency and tests before adding many approximate blocks.
Preserve GPL headers, LICENSE, NOTICE and asset provenance. No unofficial upstream version claims.
Never treat an iPhone benchmark as completed from PC numbers.
