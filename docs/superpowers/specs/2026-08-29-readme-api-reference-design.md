# README API Reference Design

## Goal

Make `README.md` the complete, accurate user guide and public API reference for
Tuiloom 0.1.1. A reader should be able to install the package, build an
application, understand its runtime rules, and use every intentionally exported
symbol without reading the implementation.

## Audience and scope

The primary audience is Python developers using Tuiloom to build interactive
terminal menus. The README will document the 14 names exported by
`tuiloom.__all__`, including every public constructor, property, and method on
the exported classes. Internal workers, renderers, registries, and event-loop
objects remain out of scope.

The document will describe version 0.1.1, Python 3.12 or newer, and the tested
Linux and macOS platforms. It will replace the obsolete pre-publication notice
with current PyPI, CI, Python, and license links or badges.

## Information architecture

The README will use a progressive-guide-plus-reference structure:

1. Project summary, status badges, requirements, and installation.
2. A minimal runnable application and the runtime requirements of
   `TerminalApp.run()`.
3. A navigable table of contents.
4. Conceptual guides for application/menu ownership, navigation, screen state,
   commands and submenus, content sources and scrolling, captured output and
   safe shutdown, input, alerts, messages, global bindings, visibility, and
   hyperlinks.
5. A complete public API reference grouped by exported type, with signatures,
   attributes, return values, mutation rules, relevant exceptions, and lifecycle
   restrictions.
6. Development commands, compatibility, and known terminal/thread limitations.

The guide sections will use focused examples. The reference will avoid repeating
large examples and link readers back to the relevant guide section instead.

## Accuracy rules

- Public surface area is defined by `tuiloom.__all__` and
  `tests/test_public_api.py`.
- Signatures and semantics come from the implementation and its tests, not from
  assumptions or stale prose.
- Examples must type-check conceptually with the published Python requirement
  and use only public imports from `tuiloom`.
- The shutdown section must distinguish normal completion, wait-and-quit,
  cooperative stop-and-quit, and irreversible cancellation.
- The content section must distinguish static strings/lists, iterators, and
  dynamic callables, including replacement and active-work behavior.
- Limitations must state that Python threads cannot be safely killed and that
  subprocess or direct file-descriptor output is not captured.

## Verification

Before committing the README:

- compare all exports and public members against the API inventory test;
- scan README code snippets for public import and signature mismatches;
- run Markdown-oriented whitespace/link checks available locally;
- run `make check` to ensure the repository remains green;
- inspect the final diff for accidental non-documentation changes.

The final commit will update `README.md` only; this design document is a separate
planning artifact committed before implementation.
