# Equivalent content panels

**Goal:** Remove the primary-panel distinction, including its public shortcuts
and duplicated runtime state. The user explicitly authorizes breaking changes.

**Architecture:** TerminalMenu owns only an ordered collection of ContentPanel
handles. Each panel owns its renderer, viewport, source, layout and scroll state.
The terminal renderer and event loop iterate that collection without aliases
or a fallback content renderer. Global content remains supported and creates
one ordinary panel per menu, as explicitly selected by the user.

- [x] Add failing tests for removal of menu shortcuts/constructor options,
  inherited-panel equivalence, empty runtime and panel add/remove/readd lifecycle.
- [x] Remove TerminalMenu.set_content(), menu.auto_scroll, content constructor
  option, primary references and mirrored content fields.
- [x] Simplify renderer and event-loop constructors; remove primary viewport,
  worker aliases and unqualified scrolling/replacement helpers. Keep per-panel
  worker retirement, stale-event protection and responsive refresh behavior.
- [x] Migrate existing tests to explicit panel handles while preserving their
  behavioral assertions; retain v0.6 weighted sizing semantics.
- [x] Update README examples, API reference and migration instructions, and the
  no-content message. Global panels are additional to explicitly added panels.
- [x] Run full pytest coverage, ruff lint/format, strict mypy, package build and
  package checks. Review for remaining primary assumptions and lifecycle bugs.

## Verification

488 tests passed; total coverage 92.52%. Ruff lint/format, strict mypy and offline
lockfile validation passed. Wheel/source build and twine checks passed. An
isolated installed-wheel smoke test verified inherited ordinary panels, the
panel-only API, exact 5:15 allocation and content replacement. Read-only review
found no actionable findings or remaining primary assumptions in production.

A new regression test demonstrated that deferred replacement could leave a
stale frame when source revisions coincided. The render key now includes each
panel's renderer identity; the regression passes for both panel positions.
