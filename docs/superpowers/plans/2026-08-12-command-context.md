# Command Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every public command callback receive a fresh execution-specific `CommandContext` and resolve each entered command as one exact key.

**Architecture:** A new `tuiloom.command` module owns the public context and command aliases plus the private zero-argument adapter. `TerminalMenu` remains the dispatch coordinator: it asks `TerminalApp` for one exact global match, then performs one exact local lookup; whichever layer resolves the command creates and passes the context immediately before invocation.

**Tech Stack:** Python 3.12, dataclasses, pytest, mypy strict mode, Ruff, Hatchling/uv

---

## File Map

- Create `src/tuiloom/command.py`: public command context and aliases, private adapter for bound internal actions.
- Modify `src/tuiloom/__init__.py`: expose the public command API.
- Modify `src/tuiloom/screen_context/screen_context.py`: consume `CommandDict` from the command module.
- Modify `src/tuiloom/render/menu_renderer.py`: consume `Command` from the command module.
- Modify `src/tuiloom/terminal_app.py`: type global callbacks and dispatch one exact global command with context.
- Modify `src/tuiloom/terminal_menu.py`: type local callbacks, adapt internal actions, and dispatch one local command with context.
- Create `tests/test_command.py`: validate the context value object, aliases, and private adapter.
- Create `tests/test_command_dispatch.py`: cover local/global execution, exact lookup, internal actions, closures, and errors.
- Modify `tests/test_terminal_app.py`: migrate existing callbacks and private global-dispatch calls.
- Modify `tests/test_public_api.py`: validate root exports and public class documentation.
- Modify `README.md`: document direct context usage and closure-based dependency capture.

### Task 1: Introduce the command type module and public exports

**Files:**

- Create: `src/tuiloom/command.py`
- Modify: `src/tuiloom/__init__.py`
- Modify: `src/tuiloom/screen_context/screen_context.py`
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Create: `tests/test_command.py`
- Modify: `tests/test_public_api.py`

- [ ] **Step 1: Write the failing public-type tests**

Create `tests/test_command.py` with:

```python
from dataclasses import FrozenInstanceError

import pytest

from tuiloom import (
    Command,
    CommandBehavior,
    CommandContext,
    CommandDict,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.command import _without_context


def test_command_context_is_frozen_slotted_execution_data() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    context = CommandContext(app=app, menu=menu, command_key="1")

    assert context.app is app
    assert context.menu is menu
    assert context.command_key == "1"
    assert not hasattr(context, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(context, "command_key", "2")


def test_public_command_aliases_describe_one_context_callback() -> None:
    contexts: list[CommandContext] = []
    behavior: CommandBehavior = contexts.append
    command: Command = (behavior, "Capture")
    commands: CommandDict = {"1": command}

    assert commands["1"] == (behavior, "Capture")


def test_without_context_ignores_the_execution_context() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    calls: list[str] = []
    wrapped = _without_context(lambda: calls.append("called"))

    wrapped(CommandContext(app=app, menu=menu, command_key="1"))

    assert calls == ["called"]
```

Update the expected names and public classes in `tests/test_public_api.py`:

```python
from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu


def test_public_api_contains_only_supported_symbols() -> None:
    expected = {
        "Command",
        "CommandBehavior",
        "CommandContext",
        "CommandDict",
        "ContentSource",
        "ScreenContext",
        "TerminalApp",
        "TerminalMenu",
    }
    assert set(tuiloom.__all__) == expected
    assert all(getattr(tuiloom, name) is not None for name in expected)
    assert not hasattr(tuiloom, "MessageRegistry")
```

Include `CommandContext` first in the existing public-class documentation tuple:

```python
for public_class in (
    CommandContext,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
):
```

- [ ] **Step 2: Run the tests and verify the missing API failure**

Run:

```bash
uv run pytest tests/test_command.py tests/test_public_api.py -q
```

Expected: collection fails because `CommandBehavior` and `CommandContext` cannot yet be imported from `tuiloom`.

- [ ] **Step 3: Add the minimal command module**

Create `src/tuiloom/command.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Describe one command execution created by Tuiloom.

    The context exposes the active application, originating menu, and resolved
    registry key to the user callback handling that execution.
    """

    app: TerminalApp
    menu: TerminalMenu
    command_key: str


type CommandBehavior = Callable[[CommandContext], None]
type Command = tuple[CommandBehavior, str]
type CommandDict = dict[str, Command]


def _without_context(action: Callable[[], None]) -> CommandBehavior:
    """Adapt an internal zero-argument action to a command callback."""

    def wrapped(context: CommandContext) -> None:
        action()

    return wrapped
```

Change `src/tuiloom/screen_context/screen_context.py` to remove its local aliases and import the registry type:

```python
from dataclasses import dataclass, field

from tuiloom.command import CommandDict
```

Change the first import in `src/tuiloom/render/menu_renderer.py` to:

```python
from tuiloom.command import Command
from tuiloom.screen_context.screen_context import ScreenContext
```

In both `src/tuiloom/terminal_app.py` and
`src/tuiloom/terminal_menu.py`, import the registry type from its new owner while
continuing to import `ScreenContext` from the screen-context module:

```python
from tuiloom.command import CommandDict
from tuiloom.screen_context.screen_context import ScreenContext
```

Export the four command symbols from `src/tuiloom/__init__.py`:

```python
from tuiloom.command import (
    Command,
    CommandBehavior,
    CommandContext,
    CommandDict,
)
from tuiloom.render.content_renderer import ContentSource
from tuiloom.screen_context.screen_context import ScreenContext
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu

__all__ = [
    "Command",
    "CommandBehavior",
    "CommandContext",
    "CommandDict",
    "ContentSource",
    "ScreenContext",
    "TerminalApp",
    "TerminalMenu",
]
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
uv run pytest tests/test_command.py tests/test_public_api.py -q
```

Expected: all tests in both files pass.

- [ ] **Step 5: Commit the public command API**

```bash
git add src/tuiloom/command.py src/tuiloom/__init__.py src/tuiloom/screen_context/screen_context.py src/tuiloom/render/menu_renderer.py src/tuiloom/terminal_app.py src/tuiloom/terminal_menu.py tests/test_command.py tests/test_public_api.py
git commit -m "feat: add public command context types"
```

### Task 2: Dispatch local commands with fresh contexts

**Files:**

- Modify: `src/tuiloom/terminal_menu.py`
- Create: `tests/test_command_dispatch.py`

- [ ] **Step 1: Write failing tests for local context construction and closure use**

Create `tests/test_command_dispatch.py` with these helpers and tests:

```python
from inspect import signature

import pytest

from tuiloom import (
    CommandBehavior,
    CommandContext,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)


def make_menu(app: TerminalApp, name: str = "Menu") -> TerminalMenu:
    return TerminalMenu(app, ScreenContext(app_name="Example", menu_name=name, title=name))


def enter(menu: TerminalMenu, command: str) -> None:
    menu._input_buffer = command
    menu._handle_enter()


def test_local_command_receives_fresh_context_for_each_execution() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    contexts: list[CommandContext] = []
    menu.add_command("Capture", contexts.append, index=10)

    enter(menu, "10")
    enter(menu, "10")

    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert all(context.app is app for context in contexts)
    assert all(context.menu is menu for context in contexts)
    assert all(context.command_key == "10" for context in contexts)


def test_business_dependencies_can_be_captured_by_a_closure() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    def make_generate_command(prefix: str) -> CommandBehavior:
        def generate(context: CommandContext) -> None:
            context.menu.set_content_source(f"{prefix}: generated")

        return generate

    menu.add_command("Generate", make_generate_command("Result"), index=1)
    enter(menu, "1")

    assert menu._content_source == "Result: generated"
```

- [ ] **Step 2: Run the local-context tests and verify the callback failure**

Run:

```bash
uv run pytest tests/test_command_dispatch.py::test_local_command_receives_fresh_context_for_each_execution tests/test_command_dispatch.py::test_business_dependencies_can_be_captured_by_a_closure -q
```

Expected: both fail because local dispatch still calls callbacks with no context.

- [ ] **Step 3: Type and invoke local callbacks with context**

In `src/tuiloom/terminal_menu.py`, replace the callback/type imports with:

```python
from tuiloom.command import (
    CommandBehavior,
    CommandContext,
    CommandDict,
    _without_context,
)
```

Change `add_command()` to accept:

```python
behavior: CommandBehavior,
```

Change its `behavior` docstring text to:

```text
Callback invoked with a context describing this execution.
```

Register the built-in command in `__init__()` as:

```python
self.commands["0"] = (_without_context(self.stop), "Back")
```

After exact local resolution in `_handle_enter()`, invoke:

```python
action = command_data[0]
action(CommandContext(app=self.app, menu=self, command_key=command))
```

- [ ] **Step 4: Run the local-context tests and verify they pass**

Run:

```bash
uv run pytest tests/test_command_dispatch.py::test_local_command_receives_fresh_context_for_each_execution tests/test_command_dispatch.py::test_business_dependencies_can_be_captured_by_a_closure -q
```

Expected: both tests pass.

- [ ] **Step 5: Write failing tests for local errors and internal actions**

Append to `tests/test_command_dispatch.py`:

```python
def test_unknown_command_keeps_existing_message() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    enter(menu, "missing")

    assert menu.screen_context.message == "Unknown command 'missing'"


def test_callback_exceptions_propagate() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    def fail(context: CommandContext) -> None:
        raise RuntimeError(f"failed {context.command_key}")

    menu.add_command("Fail", fail, index=1)

    with pytest.raises(RuntimeError, match="failed 1"):
        enter(menu, "1")


def test_zero_command_stops_menu_without_changing_stop_signature() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    menu.running = True

    enter(menu, "0")

    assert menu.running is False
    assert not signature(menu.stop).parameters


def test_submenu_command_runs_zero_argument_bound_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = TerminalApp("Example")
    parent = make_menu(app, "Parent")
    submenu = make_menu(app, "Child")
    calls: list[str] = []

    def run_submenu() -> None:
        calls.append("child")

    monkeypatch.setattr(submenu, "run", run_submenu)
    parent.add_menu(submenu, "Open child", index=1)

    enter(parent, "1")

    assert calls == ["child"]
    assert not signature(submenu.run).parameters
```

- [ ] **Step 6: Run the internal-action tests and verify the submenu failure**

Run:

```bash
uv run pytest tests/test_command_dispatch.py -q
```

Expected: the submenu test fails because `add_menu()` still registers `menu.run` as a context-taking callback; the already migrated local, unknown, exception, and zero-command tests pass.

- [ ] **Step 7: Adapt submenu execution without changing `run()`**

Change the registration in `TerminalMenu.add_menu()` to:

```python
self.add_command(
    name=name,
    behavior=_without_context(menu.run),
    index=index,
)
```

Leave these signatures unchanged:

```python
def run(self) -> None:
def stop(self) -> None:
```

- [ ] **Step 8: Run all local dispatch tests and verify they pass**

Run:

```bash
uv run pytest tests/test_command_dispatch.py -q
```

Expected: every test currently defined in `tests/test_command_dispatch.py` passes.

- [ ] **Step 9: Commit local context dispatch**

```bash
git add src/tuiloom/terminal_menu.py tests/test_command_dispatch.py
git commit -m "feat: pass context to local commands"
```

### Task 3: Resolve exactly one global command with its originating menu

**Files:**

- Modify: `src/tuiloom/terminal_app.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_command_dispatch.py`
- Modify: `tests/test_terminal_app.py`

- [ ] **Step 1: Add failing tests for global contexts, normalization, and origin**

Append to `tests/test_command_dispatch.py`:

```python
def test_global_command_receives_normalized_key_and_originating_menu() -> None:
    app = TerminalApp("Example")
    first_menu = make_menu(app, "First")
    second_menu = make_menu(app, "Second")
    contexts: list[CommandContext] = []
    app.add_global_command("x", "Capture", contexts.append)

    enter(second_menu, "x")

    assert len(contexts) == 1
    assert contexts[0].app is app
    assert contexts[0].menu is second_menu
    assert contexts[0].menu is not first_menu
    assert contexts[0].command_key == "X"


def test_global_command_gets_a_new_context_for_each_execution() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    contexts: list[CommandContext] = []
    app.add_global_command("x", "Capture", contexts.append)

    enter(menu, "X")
    enter(menu, "X")

    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
```

- [ ] **Step 2: Run the global-context tests and verify the signature failure**

Run:

```bash
uv run pytest tests/test_command_dispatch.py::test_global_command_receives_normalized_key_and_originating_menu tests/test_command_dispatch.py::test_global_command_gets_a_new_context_for_each_execution -q
```

Expected: both fail because `_handle_global_command()` neither receives the origin menu nor passes a context.

- [ ] **Step 3: Implement one exact global lookup and context creation**

In `src/tuiloom/terminal_app.py`, remove the `Callable` import and import:

```python
from tuiloom.command import CommandBehavior, CommandContext, CommandDict
```

Change `add_global_command()` to accept:

```python
behavior: CommandBehavior,
```

Update its docstring so `behavior` is described as a callback receiving the execution context, and replace the statement about sequence dispatch with exact-key lookup semantics.

Replace `_handle_global_command()` with:

```python
def _handle_global_command(self, command: str, menu: TerminalMenu) -> bool:
    """Resolve and execute one exact normalized global command."""
    command_key = command.upper()
    command_data = self.global_commands.get(command_key)

    if command_data is None:
        return False

    action = command_data[0]
    action(CommandContext(app=self, menu=menu, command_key=command_key))
    return True
```

In `TerminalMenu._handle_enter()`, pass the origin menu:

```python
if self.app._handle_global_command(command, self):
    return
```

- [ ] **Step 4: Run the global-context tests and verify they pass**

Run:

```bash
uv run pytest tests/test_command_dispatch.py::test_global_command_receives_normalized_key_and_originating_menu tests/test_command_dispatch.py::test_global_command_gets_a_new_context_for_each_execution -q
```

Expected: both tests pass.

- [ ] **Step 5: Add exact-input and collision regression tests**

Append to `tests/test_command_dispatch.py`:

```python
@pytest.mark.parametrize("command", ["XY", "XX"])
def test_global_input_is_never_split_into_characters(command: str) -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command("x", "Run X", lambda context: calls.append(context.command_key))
    app.add_global_command("y", "Run Y", lambda context: calls.append(context.command_key))

    enter(menu, command)

    assert calls == []
    assert menu.screen_context.message == f"Unknown command '{command}'"


def test_one_character_input_executes_exactly_one_global_command() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command("x", "Run X", lambda context: calls.append(context.command_key))

    enter(menu, "X")

    assert calls == ["X"]


def test_global_command_keeps_priority_over_colliding_local_command() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command("x", "Global", lambda context: calls.append("global"))
    menu.add_command("Local", lambda context: calls.append("local"), index=1)
    menu.commands["X"] = menu.commands.pop("1")

    enter(menu, "X")

    assert calls == ["global"]
```

- [ ] **Step 6: Run exact-input tests and verify they pass**

Run:

```bash
uv run pytest tests/test_command_dispatch.py -q
```

Expected: all local and global dispatch tests pass; `XY` and `XX` each produce one unknown-command result without invoking registered single-character commands.

- [ ] **Step 7: Migrate existing application tests to the new callback signature**

In `tests/test_terminal_app.py`, import `CommandContext`:

```python
from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu
```

Update `test_global_command_dispatch_is_internal()` to create an origin menu and accept contexts:

```python
def test_global_command_dispatch_is_internal() -> None:
    calls: list[str] = []
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    app.add_global_command("x", "Run X", lambda context: calls.append(context.command_key))
    assert not hasattr(app, "handle_global_command")
    assert app._handle_global_command("X", menu) is True
    assert calls == ["X"]
    assert app._handle_global_command("missing", menu) is False
```

Add this typed no-op near the top of the file:

```python
def do_nothing(context: CommandContext) -> None:
    pass
```

Use `do_nothing` in the two key-validation tests instead of zero-argument lambdas.

- [ ] **Step 8: Run the complete dispatch and application tests**

Run:

```bash
uv run pytest tests/test_command.py tests/test_command_dispatch.py tests/test_terminal_app.py tests/test_internal_docstrings.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit exact global dispatch**

```bash
git add src/tuiloom/terminal_app.py src/tuiloom/terminal_menu.py tests/test_command_dispatch.py tests/test_terminal_app.py
git commit -m "feat: dispatch exact global command keys"
```

### Task 4: Document the breaking callback contract

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Add direct and closure-based command examples**

Write a concise README section containing:

````markdown
# Tuiloom

Tuiloom builds typed terminal menus whose command callbacks receive the context
of each execution.

## Commands

```python
from tuiloom import CommandBehavior, CommandContext, TerminalApp

app = TerminalApp("Generator")
menu = app.set_main_menu("Generation")


def generate(context: CommandContext) -> None:
    context.menu.set_content_source("Generated from this menu")


menu.add_command("Generate", generate)
```

Tuiloom creates `CommandContext` during dispatch. Its `app`, `menu`, and
`command_key` fields identify the active application, the menu where the command
was entered, and the exact resolved registry key.

Application dependencies can stay in closures; no command class is required:

```python
def make_generate_command(
    decoder: ConstrainedDecoder,
    prompt_builder: PromptBuilder,
) -> CommandBehavior:
    def generate(context: CommandContext) -> None:
        instructions = prompt_builder.get_prompt()
        context.menu.set_content_source(decoder.stream(instructions))

    return generate
```
````

- [ ] **Step 2: Check documentation formatting**

Run:

```bash
uv run ruff format --check src tests
git diff --check
```

Expected: both commands exit successfully with no formatting or whitespace errors.

- [ ] **Step 3: Commit the command usage documentation**

```bash
git add README.md
git commit -m "docs: explain command context callbacks"
```

### Task 5: Verify behavior, typing, lint, and package exports

**Files:**

- No planned file changes; any diagnostic must be resolved in the scoped file
  that introduced it before rerunning this task.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass, including the original 35 tests and the new command tests.

- [ ] **Step 2: Run strict type checking over source and tests**

Run:

```bash
uv run mypy src tests
```

Expected: success with no type errors. In particular, every public test callback accepts `CommandContext`, while `TerminalMenu.run()` and `TerminalMenu.stop()` remain zero-argument bound actions.

- [ ] **Step 3: Run lint and formatting checks without automatic mutation**

Run:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: both commands exit successfully with no diagnostics.

- [ ] **Step 4: Verify root-package imports explicitly**

Run:

```bash
uv run python -c 'from tuiloom import Command, CommandBehavior, CommandContext, CommandDict; print(CommandContext.__name__)'
```

Expected output:

```text
CommandContext
```

- [ ] **Step 5: Inspect the final diff and repository state**

Run:

```bash
git diff --check 920fa99..HEAD
git status --short
```

Expected: no whitespace errors and no uncommitted implementation files. Confirm that the diff is limited to command API, dispatch, tests, public exports, and README documentation.
