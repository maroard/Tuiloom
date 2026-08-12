# Docstring Boundaries Design

## Goal

Make Tuiloom's documentation reflect its API boundaries: detailed guidance for
application authors and concise descriptions for internal implementation code.

## Detailed user-facing documentation

Keep Google-style docstrings with relevant `Args`, `Returns`, and `Raises`
sections for:

- every class and type exported through `tuiloom.__all__`;
- `TerminalApp` and all methods without a leading underscore;
- `TerminalMenu` and all methods without a leading underscore, including
  `run()` and `stop()`;
- `ScreenContext`, whose constructor fields form user-facing configuration.

These docstrings must explain observable behavior, scope, lifecycle constraints,
and intentional exceptions. They may use multiple paragraphs when needed.

## Concise internal documentation

Use docstrings of one or two physical lines for:

- methods whose names begin with `_`, including `TerminalApp._get_message()` and
  `TerminalApp._handle_global_command()`;
- `MessageKey`, `MessageRegistry`, and every registry method because the registry
  is encapsulated by `TerminalApp`;
- input, rendering, viewport, event, and rendered-content implementation classes
  and their methods.

Internal docstrings state purpose or a non-obvious constraint only. They do not
contain `Args`, `Returns`, or `Raises` sections. Existing comments may remain when
they explain implementation mechanics rather than API usage.

## Verification

Tests will introspect the public API to ensure detailed documentation remains and
the internal registry API to ensure its docstrings stay within two physical
lines. The full pytest, mypy, and Ruff checks must pass with no behavior changes.
