# Tuiloom Package API and Structure Design

## Goal

Simplify Tuiloom's package layout, expose a deliberate public API, document every
user-facing entry point, ship PEP 561 typing metadata, and establish an initial
automated test suite.

## Package structure

The source tree will use one level of grouping for rendering components:

```text
src/tuiloom/
├── __init__.py
├── py.typed
├── message_registry.py
├── terminal_app.py
├── terminal_menu.py
├── input_handler/
│   ├── __init__.py
│   ├── input_event.py
│   └── input_handler.py
└── render/
    ├── __init__.py
    ├── content_renderer.py
    ├── menu_renderer.py
    ├── rendered_content.py
    ├── terminal_renderer.py
    └── viewport.py
```

`MessageRegistry` moves out of `screen_context` because it represents
application-level message configuration rather than screen state. The
`render/user_content` package is removed; its two modules belong directly beside
the other rendering components. Existing import paths do not need compatibility
shims because the project is still under active development.

## Public API

`tuiloom.__init__` will expose only the objects an application author needs:

- `TerminalApp`: application setup and lifecycle.
- `TerminalMenu`: menu configuration and composition.
- `ContentSource`: accepted content input type.
- `MessageRegistry`: customization and enable/disable control for messages.
- `ScreenContext`: configuration required when constructing a menu directly.
- `Command` and `CommandDict`: types used by `ScreenContext` and menu commands.

These names will be listed in `__all__`. Rendering machinery, terminal input
objects, and `RenderedContent` remain internal implementation details even though
Python still permits importing their modules directly.

The public import style becomes:

```python
from tuiloom import ContentSource, MessageRegistry, ScreenContext, TerminalApp
```

## User-facing documentation

Every exported class receives a concise descriptive docstring. Exported type
aliases are documented in their defining module and with an adjacent descriptive
comment because Python aliases cannot carry runtime docstrings. Every public
constructor, property, and method on `TerminalApp`, `TerminalMenu`, and
`MessageRegistry` receives a precise docstring covering:

- its purpose and observable behavior;
- the meaning and constraints of each argument;
- its return value;
- exceptions intentionally raised by the method;
- important lifecycle constraints;
- a short usage example when the call is not self-explanatory.

Internal helpers beginning with `_` do not require user-facing documentation.
`TerminalApp.handle_global_command` is orchestration used only by
`TerminalMenu`; it will become `_handle_global_command`. All other methods that
currently lack a leading underscore remain supported and receive user-facing
documentation.

Docstrings will use normal Python triple-quoted strings, not runtime f-strings.
An f-string interpolates values while code executes and is not the appropriate
format for API documentation.

## Typing metadata

An empty `src/tuiloom/py.typed` marker will declare that the installed package
ships inline type annotations, as defined by PEP 561. A test will verify that the
marker exists as a package resource, and the built wheel will be inspected to
ensure it is included in the distribution.

## Tests

The initial suite mirrors the relevant source domains:

```text
tests/
├── __init__.py
├── test_message_registry.py
├── test_public_api.py
└── render/
    ├── __init__.py
    ├── test_content_renderer.py
    └── test_viewport.py
```

The suite will verify:

- every supported public symbol can be imported directly from `tuiloom`;
- `__all__` matches the intended public API;
- `py.typed` is present as an installed package resource;
- built-in and custom messages, duplicate validation, enable/disable behavior,
  and contextual message factories;
- static, dynamic, and streaming content rendering, including invalid content;
- viewport padding, clipping, and bounded scrolling.

Tests will be written before each structural or behavioral change and observed
failing for the expected reason. Interactive terminal I/O is excluded from this
first suite because it requires a separate injectable I/O design.

## Verification

The completed change must satisfy all of the following:

```text
uv run pytest
uv run mypy
uv run ruff check src tests
uv build
```

The built wheel must contain `tuiloom/py.typed`, and no source import may refer to
`tuiloom.render.user_content` or `tuiloom.screen_context.message_registry`.
