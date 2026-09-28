# Content panel sizing — v0.6

The subsequent user-approved panel-only API change is recorded in
`2026-09-28-equivalent-content-panels.md`. Its removal of legacy menu shortcuts
supersedes this plan's earlier compatibility assumption.

**Goal:** Add independent visible-height allocation to ContentPanel while preserving
the existing renderer, worker lifecycle, focus and scroll behavior.

**Architecture:** Keep configuration on ContentPanel and route mutations through
its owning TerminalMenu. An internal renderer helper aims for weight ratios on
total visible height, applies minimum/maximum bounds, redistributes constrained
shares, and rounds by largest remainder with display-order ties. Keep responsive
virtual minimums separate from visible panel bounds. The user's rendering
clarification makes weights apply to complete frames including borders: for
23 rows, weights 3:1 yield frame heights 17:6 and viewport heights 15:4.
Minimum and maximum height options still count inner content rows.

**Tech stack:** Python 3.12, pytest, ruff, mypy; no new dependencies.

- [x] Add failing public API tests in `tests/test_content_panels.py`: defaults
  `(1, 1, None)`, creation options, atomic validation, complete configuration
  replacement, persistence across source replacement and movement, ownership.
- [x] Run `.venv/bin/pytest tests/test_content_panels.py -q`, observe failures,
  then add properties and `set_layout(*, weight=1, min_height=1, max_height=None)`
  in `src/tuiloom/content_panel.py`, creation keywords and owning-menu mutation
  in `src/tuiloom/terminal_menu.py`; rerun to green.
- [x] Add allocation tests to `tests/render/test_terminal_renderer.py`: exact
  equal-share compatibility, different weights/minimums, successive maximums,
  fixed heights, fractional and extreme weights, insufficient space and unused
  space when every panel is capped. Observe failures before implementation.
- [x] Implement `src/tuiloom/render/panel_layout.py` and call it from frame
  composition. Use exact rational shares to avoid float overflow and unstable
  integer rounding. Return the existing too-small frame on insufficient minimums.
- [x] Test live rendering invalidation, viewport identity and offset clamping,
  focused-panel scrolling, strict/smart following and responsive resize requests
  in renderer and event-loop tests. Keep workers and viewport objects intact.
- [x] Update public API documentation tests, README examples and version to
  0.6.0 in `pyproject.toml` and the local package entry of `uv.lock`.
- [x] Run `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`,
  `.venv/bin/mypy src tests`, and `.venv/bin/pytest --cov=tuiloom --cov-report=term-missing`.
  Review the final diff for API compatibility and allocation invariants.

## Verification

480 tests passed; total coverage 92.03%. Ruff lint/format and strict mypy passed.
Independent read-only review found no actionable findings; allocation matched
an exact reference over 100,000 randomized layouts. Wheel and source archives
for 0.6.0 were built successfully.

## Defined edge cases

`weight` is a finite strictly positive int or float; booleans are rejected.
`min_height` defaults to one visible row, `max_height` to no limit. Both supplied
heights must be positive integers and max must be at least min. Heights exclude
borders and content/menu spacing. When all panels reach their maximum, leave
unused terminal rows below the frame rather than exceeding a maximum. Replacing
layout resets unspecified options to their defaults; replacing content does not
change layout. Responsive callbacks continue to receive the larger of visible
height and the existing ScreenContent virtual minimum.

## Frame-height clarification

- [x] Reproduce the border accounting mismatch and obtain confirmation that
  weights must target complete panel heights.
- [x] Add a failing 23-row regression covering 17:6 frames, both panel orders
  and both spacing modes; update existing ratio expectations.
- [x] Allocate the complete frame budget with bounds shifted by two border
  rows, then subtract borders for each viewport. Preserve all viewport state.
- [x] Update Tuiloom and Fly-in documentation and Fly-in integration assertions.
- [x] Run Tuiloom `make check` (493 tests, 92.55% coverage) and Fly-in
  `make test lint` (42 tests); all checks passed.
