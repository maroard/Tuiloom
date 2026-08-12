# Docstring Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep rich documentation on Tuiloom's supported API while giving every internal class and method a concise one- or two-line description.

**Architecture:** Treat `tuiloom.__all__`, `TerminalApp` public methods, and `TerminalMenu` public methods as the supported surface. Everything in private modules, rendering/input modules, or named with a leading underscore is internal and receives only a compact purpose statement.

**Tech Stack:** Python 3.12, `inspect`, pytest, mypy strict mode, Ruff.

---

### Task 1: Lock the documentation boundary with tests

**Files:**
- Modify: `tests/test_public_api.py`
- Create: `tests/test_internal_docstrings.py`

- [ ] **Step 1: Strengthen the public documentation test**

Add a helper using the raw `__doc__` value so physical source lines remain
observable:

```python
def doc_lines(member: object) -> list[str]:
    doc = getattr(member, "__doc__", None)
    assert doc is not None
    return [line for line in doc.strip().splitlines() if line.strip()]
```

Assert that `TerminalApp`, `TerminalMenu`, and `ScreenContext` each have more
than two non-empty lines. For every method already listed in
`test_every_user_facing_method_has_documentation`, assert more than two non-empty
lines. Properties continue to be checked through `fget`.

- [ ] **Step 2: Add internal docstring constraints**

Create `tests/test_internal_docstrings.py` with explicit internal classes and
methods. Import:

```python
from tuiloom._message_registry import MessageKey, MessageRegistry
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.viewport import Viewport
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu
```

Use these exact groups:

```python
INTERNAL_CLASSES = (
    MessageKey,
    MessageRegistry,
    InputEvent,
    InputHandler,
    ContentRenderer,
    MenuRenderer,
    RenderedContent,
    TerminalRenderer,
    Viewport,
)

INTERNAL_METHODS = {
    MessageRegistry: (
        "__init__",
        "_register_built_in_messages",
        "_add_built_in_message",
        "add_message",
        "disable",
        "enable",
        "get",
        "_validate_new_key",
        "_validate_existing_key",
        "_no_content_source_message",
        "_unknown_command",
    ),
    InputHandler: ("__init__", "poll", "_parse_buffer", "close"),
    ContentRenderer: (
        "__init__",
        "update",
        "_handle_static_state",
        "_handle_streaming_state",
        "_handle_dynamic_state",
        "_normalize_content",
    ),
    MenuRenderer: (
        "__init__",
        "_calculate_width",
        "render",
        "_get_alert_display",
        "_get_body_display",
        "_get_text_display",
        "_get_commands_display",
        "_get_menu_items",
        "_get_two_columns_commands",
        "_get_single_column_commands",
        "_get_footer_display",
        "_get_message_display",
        "_get_alert_prompt_display",
        "_get_prompt_display",
        "_wrap_lines",
    ),
    TerminalRenderer: (
        "__init__",
        "render",
        "_render_terminal_too_small",
        "scroll_up",
        "scroll_down",
        "scroll_left",
        "scroll_right",
    ),
    Viewport: (
        "__init__",
        "render",
        "scroll_up",
        "scroll_down",
        "scroll_left",
        "scroll_right",
    ),
    TerminalApp: (
        "_get_message",
        "_handle_global_command",
        "_enter_terminal_screen",
        "_leave_terminal_screen",
    ),
    TerminalMenu: (
        "_handle_no_content_source",
        "_handle_event",
        "_handle_char",
        "_handle_backspace",
        "_handle_enter",
        "_handle_unknown_command",
        "_handle_scroll",
        "_handle_escape",
    ),
}
```

For every listed object, assert a docstring exists, has at most two physical
lines, and contains none of `Args:`, `Returns:`, or `Raises:`.

- [ ] **Step 3: Verify RED**

Run:

```bash
uv run pytest tests/test_public_api.py tests/test_internal_docstrings.py -q
```

Expected: failures for public one-line class/property docs, verbose registry
methods, and internal objects currently missing docstrings.

### Task 2: Review and normalize production docstrings

**Files:**
- Modify: `src/tuiloom/_message_registry.py`
- Modify: `src/tuiloom/input_handler/input_event.py`
- Modify: `src/tuiloom/input_handler/input_handler.py`
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `src/tuiloom/render/rendered_content.py`
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `src/tuiloom/render/viewport.py`
- Modify: `src/tuiloom/screen_context/screen_context.py`
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `src/tuiloom/terminal_menu.py`

- [ ] **Step 1: Expand public class and short method documentation**

Keep all existing Google-style detail on public methods. Expand the currently
short public objects using this exact intent:

- `TerminalApp`: explain that it owns global commands/messages/content, creates
  the main menu, and restores terminal state after running.
- `TerminalMenu`: explain that it owns menu-local commands/content/message
  suppression and runs within its application.
- `ScreenContext`: add an `Attributes:` section describing all eleven dataclass
  fields (`app_name`, `menu_name`, `title`, `width`, `commands`, `text`,
  `two_columns`, `message`, `alert`, `prompt`, `show_menu`).
- `TerminalMenu.is_main`: add a `Returns:` section.
- `TerminalMenu.stop`: explain the loop-boundary effect and add a `Returns:`
  section stating that it returns `None`.

- [ ] **Step 2: Give every internal class and method a compact docstring**

Use one physical line per internal docstring wherever possible. The descriptions
must express these responsibilities:

- `MessageKey`: built-in message identifiers.
- `MessageRegistry`: internal storage and global enable state.
- `InputEvent`: normalized terminal input.
- `InputHandler`: raw terminal input lifecycle and parsing.
- `ContentRenderer`: normalize static, dynamic, or streaming sources.
- `MenuRenderer`: build the menu box as text.
- `RenderedContent`: normalized lines and dimensions.
- `TerminalRenderer`: compose and write viewport plus menu.
- `Viewport`: clip content using scroll offsets.

Method docstrings describe the operation in an imperative or declarative
sentence, for example:

```python
def _get_message(...) -> str | None:
    """Resolve a message through the application's private registry."""

def _parse_buffer(...) -> InputEvent | None:
    """Parse one normalized event from the buffered terminal bytes."""

def render(self) -> str:
    """Render the visible content region at the current offsets."""
```

Replace the verbose registry method docstrings with one-line descriptions; do
not change their behavior, signatures, or exceptions. Convert explanatory
method-header comments in `MenuRenderer` into one-line docstrings so introspection
can see them.

- [ ] **Step 3: Verify GREEN**

Run:

```bash
uv run pytest tests/test_public_api.py tests/test_internal_docstrings.py -q
```

Expected: all documentation-boundary tests pass.

### Task 3: Full verification

**Files:**
- Verify: `src/tuiloom/**/*.py`
- Verify: `tests/**/*.py`

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run strict typing and linting**

Run:

```bash
uv run mypy
uv run ruff check src tests
```

Expected: mypy reports no issues and Ruff reports all checks passed.

- [ ] **Step 3: Inspect documentation boundaries**

Run a Python introspection script that prints the public and internal docstring
line counts. Expected: every public item has more than two non-empty physical
lines; every internal item has one or two lines and no Google-style sections.

Do not stage or commit the pre-existing untracked source and test trees.
