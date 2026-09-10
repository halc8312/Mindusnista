# Mindusnista — repository instructions

## Mission and starting point

Continue a Pythonista-native Python port of Mindustry, pinned to upstream **v159.7**.
The existing 0.1.2-dev is a partial port with substantial provisional scaffolding, NOT a complete port.
Do not replace it with a web view, remote game, Java runtime, or a new simplified lookalike.
Read `docs/HANDOFF_ja.md`, `PORT_STATUS.md`, `DEVICE_TESTS.md`, and `docs/NEXT_TASK_ja.md` before editing.
Read the actual code as well as the docs. Report disagreements instead of inventing facts.
User-facing explanations and task reports should be in Japanese.

## Source of truth and capabilities

Repository: `halc8312/Mindusnista`. Initial handoff archive: `Mindusnista_Work_Handoff_20260909.zip`.
For initial import only, use the attached 0.1.2 baseline. Afterwards inspect the current remote branch,
commit, open PRs and worktree; never overwrite newer code using the old archive.
A local edit, a commit, a remote push, a PR, a merged PR and a successful iPhone run are different states.
Check actual read/write/terminal capabilities. Account permission `push: true` is not proof that a tool
can write. Never claim a commit, PR, CI run or device test without evidence.
If a capability is absent, complete available work, return the files/diff/tests and state the blocker.
Never request tokens in conversation, expose credentials, change repo visibility/protections, or force-push.
Use a task branch and PR by default; do not merge or push directly to main without explicit approval.

## Runtime and invariants

- Runtime deliverable: `mindustry_pythonista.py`, directly runnable in Pythonista; Python 3.10-compatible.
- No pip, JVM, native extension installation, external assets download or network needed to start this baseline.
  Development-only tools such as JDK are allowed for reference testing, not required on the iPhone.
- The headless core must remain importable without `scene` / `ui`. UI adapter is `make_scene_class(sc, ui)`.
- Save format `mindustry-pythonista-dev`, schema **1**. Preserve old saves; do not silently discard fields.
- Keep `_ready` / `_failed` startup guards, stable paths, atomic writes, first-error diagnostics and save fallback.
  Do not delete or silently move user saves. No real saves/logs/personal configuration in commits or releases.
- Preserve 0.1.2 rotation controls, cargo/HP/ID/cost conservation, placement cancellation and touch semantics.
- Module splitting must include a deterministic, tested single-file output; do not maintain two editable sources.
  Separate structural refactoring from gameplay changes. Do not introduce a package requirement on iPhone.
- Preserve GPL headers, LICENSE, NOTICE and provenance. No unreviewed upstream media or fonts.

## Tests and evidence

Run `python tools/check_project.py` before and after relevant changes.
Baseline: **117 unittest tests**, self-test, and Python 3.10 syntax parsing. Record real counts and environment.
Add a failing regression before fixing bugs; do not delete or weaken tests simply to obtain green results.
`reference/java_fixtures.json` has **1,504 isolated-kernel cases**, not 1,504 test methods or a full-game oracle.
PC doubles do not run Pythonista / SpriteKit and cannot establish iPhone performance or gestures.
User reported 0.1.1 startup success; 0.1.2 has no device result yet. Never upgrade this evidence implicitly.
`HANDOFF_SHA256SUMS.txt` checks the original handoff before edits, NOT a permanent code-freeze test.
Do not run that frozen checksum as a mandatory check on future intentional development edits.
Inherited reports are historical; record new outcomes separately with commit/version/environment.

## Porting work

Choose one bounded subsystem per PR. Record upstream tag + full commit when verified, source files,
assumptions, preserved/changed behavior, fixtures, tolerances and remaining differences.
Prioritize integrated transport/mining parity before multiplying provisional content.
A source-derived calculation, source-derived constant, approximation and unimplemented feature are different.
Do not claim full compatibility from extracted equations, matching visuals or a test-count number.
The full goal includes content, rules, campaign, logic, files, network, media and MODs; assess each separately.
User requirements include very large factories/battles, original iOS/Steam save exchange (including campaign
state), and effects faithful to the original. Read `docs/FULL_PORT_REQUIREMENTS_ja.md`. Do not meet performance
gates by truncating valid game state, imposing smaller game limits, or silently reducing effects/features.
Audit inherited scaffold limits; replace them with tested data structures and original rules. Native/NumPy/GPU
acceleration is a research path, not demonstrated Pythonista performance until measured on the target device.
Do not drop a difficult goal silently, promise full compatibility without tests, or relabel a prototype complete.
If a broad task does not fit one iteration, implement and verify a smaller coherent slice and record the next step.

## Finish each task

Update affected `PORT_STATUS.md`, `DEVICE_TESTS.md`, `README_ja.md`, `docs/NEXT_TASK_ja.md` and test/task records.
Return the changed files, test commands/results, remaining limitations, and the iPhone file when it changes.
With write access, commit on a task branch, create/update a PR, and read back its metadata and commit SHA.
Without write access, return a complete updated source ZIP and diff and explicitly say GitHub was not updated.
Do not promise unstarted background work or use a plan-only reply when a bounded implementation is possible.
