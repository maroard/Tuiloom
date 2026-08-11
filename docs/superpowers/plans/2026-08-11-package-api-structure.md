# Package API and Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flatten Tuiloom's internal package structure, publish a documented and typed public API, and add a first automated regression suite.

**Architecture:** Keep terminal input and rendering grouped by domain, but move message configuration to the package root and remove the unnecessary `render/user_content` level. Protect each new import boundary with tests before moving code, then expose only application-author-facing symbols through `tuiloom.__all__`.

**Tech Stack:** Python 3.12, pytest, mypy strict mode, Ruff, Hatchling, PEP 561.

---

## Repository safety note

`Makefile`, `README.md`, `pyproject.toml`, `src/`, `tests/`, and `uv.lock` are
pre-existing untracked user work. Do not commit those files or perform a bulk
`git add` without explicit user authorization. The checkpoints below use fresh
test, type-check, lint, and build results instead of implementation commits.

### Task 1: Move and characterize the message registry

**Files:**
- Create: `src/tuiloom/message_registry.py`
- Delete: `src/tuiloom/screen_context/message_registry.py`
- Modify: `src/tuiloom/terminal_app.py:6`
- Create: `tests/test_message_registry.py`

- [ ] **Step 1: Write the failing message-registry tests**

```python
import pytest

from tuiloom.message_registry import MessageRegistry


def test_returns_built_in_messages_with_context() -> None:
    registry = MessageRegistry()

    assert registry.get(registry.UNKNOWN_COMMAND, command="wat") == (
        "Unknown command 'wat'"
    )
    assert "Settings" in (
        registry.get(registry.NO_CONTENT_SOURCE, menu_name="Settings") or ""
    )


def test_custom_message_can_be_disabled_and_enabled() -> None:
    registry = MessageRegistry()
    registry.add_message("saved", "Saved successfully")

    assert registry.get("saved") == "Saved successfully"
    registry.disable("saved")
    assert registry.get("saved") is None
    registry.enable("saved")
    assert registry.get("saved") == "Saved successfully"


def test_rejects_empty_and_duplicate_message_keys() -> None:
    registry = MessageRegistry()

    with pytest.raises(ValueError, match="cannot be empty"):
        registry.add_message("", "Invalid")

    registry.add_message("saved", "Saved")
    with pytest.raises(ValueError, match="already exists"):
        registry.add_message("saved", "Duplicate")


def test_rejects_unknown_message_when_toggling() -> None:
    registry = MessageRegistry()

    with pytest.raises(KeyError, match="Unknown message key"):
        registry.disable("missing")
```

- [ ] **Step 2: Verify that the new import path fails**

Run: `uv run pytest tests/test_message_registry.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'tuiloom.message_registry'`.

- [ ] **Step 3: Move the registry and update its consumer**

Move the complete, unchanged implementation from
`src/tuiloom/screen_context/message_registry.py` to
`src/tuiloom/message_registry.py`. Delete the old file and replace this import in
`src/tuiloom/terminal_app.py`:

```python
from tuiloom.message_registry import MessageRegistry
```

- [ ] **Step 4: Verify the registry tests pass**

Run: `uv run pytest tests/test_message_registry.py -q`

Expected: `4 passed`.

### Task 2: Flatten user-content rendering

**Files:**
- Create: `src/tuiloom/render/content_renderer.py`
- Create: `src/tuiloom/render/rendered_content.py`
- Delete: `src/tuiloom/render/user_content/__init__.py`
- Delete: `src/tuiloom/render/user_content/content_renderer.py`
- Delete: `src/tuiloom/render/user_content/rendered_content.py`
- Modify: `src/tuiloom/terminal_app.py:5`
- Modify: `src/tuiloom/terminal_menu.py:10`
- Modify: `src/tuiloom/render/terminal_renderer.py:5`
- Modify: `src/tuiloom/render/viewport.py:1`
- Create: `tests/render/__init__.py`
- Create: `tests/render/test_content_renderer.py`
- Create: `tests/render/test_viewport.py`

- [ ] **Step 1: Write failing tests against the flattened renderer import**

Create `tests/render/__init__.py` with:

```python
"""Tests for Tuiloom rendering components."""
```

Create `tests/render/test_content_renderer.py` with:

```python
from collections.abc import Iterator

import pytest

from tuiloom.render.content_renderer import ContentRenderer


def test_static_content_is_normalized_immediately() -> None:
    rendered = ContentRenderer("first\nsecond").update()

    assert rendered.lines == ["first", "second"]
    assert (rendered.width, rendered.height, rendered.finished) == (6, 2, True)


def test_dynamic_content_is_refreshed_on_each_update() -> None:
    values = iter(["first", "second\nline"])
    renderer = ContentRenderer(lambda: next(values))

    assert renderer.update().lines == ["first"]
    assert renderer.update().lines == ["second", "line"]
    assert renderer.rendered_content.finished is False


def test_streaming_content_accumulates_until_exhausted() -> None:
    source: Iterator[str] = iter(["first", "\nsecond"])
    renderer = ContentRenderer(source)

    assert renderer.update().lines == ["first"]
    assert renderer.update().lines == ["first", "second"]
    assert renderer.update().finished is True


def test_rejects_invalid_static_content() -> None:
    with pytest.raises(TypeError, match="Content source must be"):
        ContentRenderer(["valid", 42])  # type: ignore[list-item]


def test_rejects_invalid_streamed_chunk() -> None:
    source: Iterator[str] = iter([42])  # type: ignore[list-item]
    renderer = ContentRenderer(source)

    with pytest.raises(TypeError, match="chunks must be str"):
        renderer.update()
```

Create `tests/render/test_viewport.py` with:

```python
import pytest

from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.viewport import Viewport


def make_content() -> RenderedContent:
    return RenderedContent(
        lines=["abcdef", "ghijkl", "mnopqr"],
        width=6,
        height=3,
        finished=True,
    )


def test_render_clips_and_pads_content() -> None:
    viewport = Viewport(make_content(), width=4, height=4)

    assert viewport.render() == "abcd\nghij\nmnop\n    "


def test_scrolling_stays_within_content_bounds() -> None:
    viewport = Viewport(make_content(), width=3, height=2)

    for _ in range(10):
        viewport.scroll_right()
        viewport.scroll_down()
    assert viewport.render() == "jkl\npqr"

    for _ in range(10):
        viewport.scroll_left()
        viewport.scroll_up()
    assert viewport.render() == "abc\nghi"


@pytest.mark.parametrize("width, height", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_rejects_non_positive_dimensions(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        Viewport(make_content(), width=width, height=height)


def test_rejects_non_integer_dimensions() -> None:
    with pytest.raises(TypeError, match="must be int"):
        Viewport(make_content(), width=3.0, height=2)  # type: ignore[arg-type]
```

- [ ] **Step 2: Verify that both new renderer imports fail**

Run: `uv run pytest tests/render -q`

Expected: collection fails for missing `tuiloom.render.content_renderer` and
`tuiloom.render.rendered_content`.

- [ ] **Step 3: Move both renderer modules without changing behavior**

Move the full implementations to `src/tuiloom/render/content_renderer.py` and
`src/tuiloom/render/rendered_content.py`, then use exactly these imports:

```python
# src/tuiloom/render/content_renderer.py
from tuiloom.render.rendered_content import RenderedContent

# src/tuiloom/render/viewport.py
from tuiloom.render.rendered_content import RenderedContent

# src/tuiloom/render/terminal_renderer.py
from tuiloom.render.content_renderer import ContentRenderer

# src/tuiloom/terminal_app.py
from tuiloom.render.content_renderer import ContentSource

# src/tuiloom/terminal_menu.py
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
```

Delete all three files under `src/tuiloom/render/user_content/` after their
replacements exist.

- [ ] **Step 4: Verify renderer behavior through the new paths**

Run: `uv run pytest tests/render -q`

Expected: `12 passed` including four parameter cases.

### Task 3: Publish the typed API

**Files:**
- Modify: `src/tuiloom/__init__.py`
- Create: `src/tuiloom/py.typed`
- Create: `tests/test_public_api.py`

- [ ] **Step 1: Write the failing public-API and typing-marker tests**

```python
from importlib.resources import files

import tuiloom


def test_public_api_contains_only_supported_symbols() -> None:
    expected = {
        "Command",
        "CommandDict",
        "ContentSource",
        "MessageRegistry",
        "ScreenContext",
        "TerminalApp",
        "TerminalMenu",
    }

    assert set(tuiloom.__all__) == expected
    assert all(getattr(tuiloom, name) is not None for name in expected)


def test_package_declares_inline_typing() -> None:
    assert files("tuiloom").joinpath("py.typed").is_file()
```

- [ ] **Step 2: Verify the API test fails for the missing exports**

Run: `uv run pytest tests/test_public_api.py -q`

Expected: failure because `tuiloom.__all__` and `py.typed` do not exist.

- [ ] **Step 3: Define the complete public API**

Replace `src/tuiloom/__init__.py` with:

```python
"""Build typed terminal applications with menus and dynamic content."""

from tuiloom.message_registry import MessageRegistry
from tuiloom.render.content_renderer import ContentSource
from tuiloom.screen_context.screen_context import Command, CommandDict, ScreenContext
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu

__all__ = [
    "Command",
    "CommandDict",
    "ContentSource",
    "MessageRegistry",
    "ScreenContext",
    "TerminalApp",
    "TerminalMenu",
]
```

Create an empty `src/tuiloom/py.typed` file.

- [ ] **Step 4: Verify the public API and marker**

Run: `uv run pytest tests/test_public_api.py -q`

Expected: `2 passed`.

### Task 4: Document the supported API and internalize dispatch

**Files:**
- Modify: `src/tuiloom/message_registry.py`
- Modify: `src/tuiloom/screen_context/screen_context.py`
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_public_api.py`
- Create: `tests/test_terminal_app.py`

- [ ] **Step 1: Add failing documentation coverage**

Append to `tests/test_public_api.py`:

```python
from inspect import getdoc

from tuiloom import MessageRegistry, ScreenContext, TerminalApp, TerminalMenu


def test_every_public_class_has_documentation() -> None:
    for public_class in (MessageRegistry, ScreenContext, TerminalApp, TerminalMenu):
        assert getdoc(public_class), public_class.__name__


def test_every_user_facing_method_has_documentation() -> None:
    public_members = {
        MessageRegistry: ("__init__", "add_message", "disable", "enable", "get"),
        TerminalApp: ("__init__", "set_main_menu", "add_global_command", "run"),
        TerminalMenu: (
            "__init__",
            "is_main",
            "add_command",
            "add_menu",
            "set_content_source",
            "disable_message",
            "enable_message",
            "is_message_enabled",
            "set_exit_command_label",
            "run",
            "stop",
        ),
    }

    for public_class, names in public_members.items():
        for name in names:
            member = getattr(public_class, name)
            documented = member.fget if isinstance(member, property) else member
            assert getdoc(documented), f"{public_class.__name__}.{name}"
```

Create `tests/test_terminal_app.py` with:

```python
from tuiloom import TerminalApp


def test_global_command_dispatch_is_internal() -> None:
    calls: list[str] = []
    app = TerminalApp("Example")
    app.add_global_command("x", "Run X", lambda: calls.append("x"))

    assert not hasattr(app, "handle_global_command")
    assert app._handle_global_command("X") is True
    assert calls == ["x"]
    assert app._handle_global_command("missing") is False
```

- [ ] **Step 2: Verify missing docstrings and the old dispatch name fail**

Run: `uv run pytest tests/test_public_api.py tests/test_terminal_app.py -q`

Expected: failures naming undocumented public members and
`TerminalApp.handle_global_command` still being present.

- [ ] **Step 3: Add exact public documentation**

Use Google-style docstrings. The following descriptions and sections are
required; preserve the runtime behavior of every method:

```python
class TerminalApp:
    """Configure and run a Tuiloom application in the active terminal."""

    def __init__(...) -> None:
        """Create an application.

        Args:
            name: Name displayed in every menu.
            global_content_source: Default content used by menus that do not
                define their own source.
        """

    def set_main_menu(...) -> TerminalMenu:
        """Create and register the application's main menu.

        Args:
            title: Heading displayed inside the menu.
            name: Internal menu name used in contextual messages.
            width: Inner menu width, or ``None`` to calculate it automatically.

        Returns:
            The configured main menu, ready for commands and content.
        """

    def add_global_command(...) -> None:
        """Register a command available from every running menu.

        Args:
            key: Alphabetic key or key sequence used to trigger the command.
            name: Human-readable command label.
            behavior: Zero-argument callable executed when the key is entered.

        Raises:
            ValueError: If ``key`` contains a non-alphabetic character.
        """

    def run(self) -> None:
        """Run the main menu and restore the terminal when execution ends.

        Raises:
            RuntimeError: If no main menu has been configured.
        """
```

```python
class TerminalMenu:
    """Configure commands, content, and messages for one application menu."""

    def __init__(...) -> None:
        """Create a menu attached to an application.

        Args:
            app: Application that owns the menu.
            screen_context: Text, dimensions, commands, and display options.
            content_source: Static, streaming, or callable menu content.
            spacing_with_content: Blank lines between content and menu.
            show: Whether this menu is intended to be displayed.
        """

    @property
    def is_main(self) -> bool:
        """Return whether this menu is the application's registered main menu."""

    def add_command(...) -> None:
        """Add or replace a numbered command.

        Args:
            name: Label displayed beside the command number.
            behavior: Zero-argument callable executed when selected.
            index: Command number, or ``None`` for the next available number.

        Raises:
            ValueError: If index zero is requested because it is reserved.
        """

    def add_menu(...) -> None:
        """Add another menu as a command that opens it.

        Args:
            menu: Menu to run when the command is selected.
            name: Label displayed beside the command number.
            index: Command number, or ``None`` for the next available number.
        """

    def set_content_source(...) -> None:
        """Replace the content source used the next time the menu runs.

        Args:
            content_source: Static text, lines, text iterator, or callable.
        """

    def disable_message(self, key: str) -> None:
        """Hide one registered application message in this menu.

        Args:
            key: Message registry key to hide locally.
        """

    def enable_message(self, key: str) -> None:
        """Allow one registered application message in this menu.

        Args:
            key: Message registry key to enable locally.
        """

    def is_message_enabled(self, key: str) -> bool:
        """Return whether a message key is enabled for this menu.

        Args:
            key: Message registry key to inspect.

        Returns:
            ``True`` when this menu may display the message.
        """

    def set_exit_command_label(self, label: str) -> None:
        """Change the label of the reserved zero command.

        Args:
            label: Replacement label for the Back or Quit command.
        """

    def run(self) -> None:
        """Run this menu until its stop command is selected.

        Raises:
            RuntimeError: If called outside ``TerminalApp.run``.
        """

    def stop(self) -> None:
        """Request that this menu stop after the current loop iteration."""
```

```python
class MessageRegistry:
    """Store, customize, and selectively disable application messages."""

    def __init__(self) -> None:
        """Create a registry populated with Tuiloom's built-in messages."""

    def add_message(self, key: str, text: str) -> None:
        """Register a custom static message.

        Args:
            key: Unique non-empty identifier.
            text: Text returned when the message is requested.

        Raises:
            ValueError: If the key is empty or already registered.
        """

    def disable(self, key: str) -> None:
        """Disable a registered message globally.

        Args:
            key: Registered message identifier.

        Raises:
            KeyError: If the key is not registered.
        """

    def enable(self, key: str) -> None:
        """Re-enable a registered message globally.

        Args:
            key: Registered message identifier.

        Raises:
            KeyError: If the key is not registered.
        """

    def get(self, key: str, **context: object) -> str | None:
        """Resolve an enabled message.

        Args:
            key: Registered message identifier.
            **context: Values required by a contextual built-in message.

        Returns:
            Resolved text, or ``None`` when the message is disabled or unknown.
        """
```

Add a class docstring to `ScreenContext` explaining that it stores the display
state consumed by renderers. Add adjacent comments describing `Command`,
`CommandDict`, and `ContentSource` in their defining modules.

- [ ] **Step 4: Rename global command dispatch as internal**

Rename `TerminalApp.handle_global_command` to
`TerminalApp._handle_global_command`, and update the only caller in
`TerminalMenu._handle_enter`:

```python
if self.app._handle_global_command(command):
    return
```

- [ ] **Step 5: Verify documentation and dispatch behavior**

Run: `uv run pytest tests/test_public_api.py tests/test_terminal_app.py -q`

Expected: `5 passed`.

### Task 5: Full verification and distribution inspection

**Files:**
- Verify: all files under `src/` and `tests/`
- Generated locally: `dist/*.whl`, `dist/*.tar.gz`

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`

Expected: all tests pass with zero failures.

- [ ] **Step 2: Run strict type checking**

Run: `uv run mypy`

Expected: `Success: no issues found`.

- [ ] **Step 3: Run lint checks**

Run: `uv run ruff check src tests`

Expected: `All checks passed!`.

- [ ] **Step 4: Confirm stale imports and directories are gone**

Run:

```bash
rg -n "tuiloom\.render\.user_content|tuiloom\.screen_context\.message_registry" src tests
find src/tuiloom/render -maxdepth 1 -type f -print | sort
```

Expected: `rg` has no matches, and the render listing contains
`content_renderer.py` and `rendered_content.py` directly.

- [ ] **Step 5: Build and inspect the wheel**

Run:

```bash
uv build
unzip -l dist/tuiloom-0.1.0-py3-none-any.whl | rg "tuiloom/(py\.typed|__init__\.py)"
```

Expected: build succeeds and both `tuiloom/__init__.py` and
`tuiloom/py.typed` appear in the wheel.

- [ ] **Step 6: Review only intended implementation files**

Run: `git status --short`

Expected: the original untracked project files remain visible; no unrelated
tracked file is modified. Ask the user before staging or committing any of the
pre-existing untracked implementation tree.
