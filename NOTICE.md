> 0.1.2-dev, 2026-09-09: Pythonista direction controls, placement preview and input regressions added.
> No upstream gameplay systems or original media assets added in this update.

# Notices

This is an **unofficial, incomplete development port** targeting Pythonista.
It is not endorsed by Anuken, the Mindustry project, or the Pythonista author.

## Mindustry-derived material

Copyright (c) Anuken and Mindustry contributors.
Original project: https://github.com/Anuken/Mindustry
Pinned reference version: **v159.7**.
License: **GNU General Public License, version 3**.

Selected conveyor movement and acceptance logic, the dry-drill update formula,
and selected content values have been adapted into Python. An isolated,
modified Java arithmetic reference is included for regression testing.
All such adaptations and the integration code in this package are distributed
under **GPL-3.0-only**. A complete license copy is in `LICENSE` and embedded in
the standalone Python file as `GPL3_LICENSE_TEXT`.

Modification date: 2026-09-09.
Modification summary: Java numerical routines adapted to Python; dependency-free
simulation scaffold, custom demonstration world/AI/combat, JSON persistence,
Pythonista scene/ui presentation, tests, documentation, and procedural icons.

See `SOURCES.md` for original locations and `PORT_STATUS.md` for deviations.
This distribution does not include the original game binaries, sprite atlas,
audio, maps, campaigns, branding graphics, or third-party font files.
The procedural graphics are created by the included Python code.

## Pythonista

Pythonista itself is a separate application and is not included or relicensed.
This source uses its public `scene` and `ui` APIs. The test doubles in `tests/`
are not an emulator and do not validate the actual Apple/Pythonista runtime.

## No warranty

This software is provided without warranty, including any implied warranty of
merchantability or fitness for a particular purpose. See the full GPL terms.
Back up saves before modifying code or testing new builds.

## Modification 0.1.1-dev (2026-09-09)

Added startup lifecycle guards, stable script paths, persistent save-directory fallback,
and first-error diagnostics. The gameplay World implementation is unchanged.
This is still an unofficial, incomplete development port; iPhone execution is unverified.

## Handoff packaging (2026-09-09)

Added repository documentation, task prompts, CI configuration and a snapshot-verification helper.
The 0.1.2 game script, tests and extracted references are unchanged. New package material uses GPL-3.0-only.
No upstream media assets, user saves or credentials are included. This is not a new game version.
