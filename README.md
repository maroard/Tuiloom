# Tuiloom

[![PyPI](https://img.shields.io/pypi/v/tuiloom.svg)](https://pypi.org/project/tuiloom/)
[![Python](https://img.shields.io/pypi/pyversions/tuiloom.svg)](https://pypi.org/project/tuiloom/)
[![CI](https://github.com/maroard/Tuiloom/actions/workflows/ci.yml/badge.svg)](https://github.com/maroard/Tuiloom/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/tuiloom.svg)](https://github.com/maroard/Tuiloom/blob/main/LICENSE)

Tuiloom builds typed, keyboard-navigable terminal menus with dynamic content,
Unicode-safe rendering, captured task output, alerts, and free-form input. It is
small enough to learn from one document while still handling the awkward parts
of terminal state and background-work shutdown.

This README documents the complete public API of Tuiloom 0.1.1.1. Tuiloom requires
Python 3.12 or newer and is tested on Linux and macOS with Python 3.12–3.14.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Core concepts](#core-concepts)
- [Navigation and focus](#navigation-and-focus)
- [Screen state and visibility](#screen-state-and-visibility)
- [Commands and submenus](#commands-and-submenus)
- [Content sources](#content-sources)
- [Captured task output](#captured-task-output)
- [Safe shutdown](#safe-shutdown)
- [Free-form and hidden input](#free-form-and-hidden-input)
- [Alerts](#alerts)
- [Messages](#messages)
- [Key bindings and global commands](#key-bindings-and-global-commands)
- [Terminal hyperlinks](#terminal-hyperlinks)
- [API reference](#api-reference)
- [Runtime constraints](#runtime-constraints)
- [Development](#development)

## Installation

Install the latest release from PyPI:

```bash
python -m pip install tuiloom
```

To install the version documented here explicitly:

```bash
python -m pip install tuiloom==0.1.1.1
```

Tuiloom ships inline typing information through `py.typed` and has no required
framework or event-loop dependency.

## Quick start

```python
from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu

app = TerminalApp("Generator")
menu = TerminalMenu(
    app,
    ScreenContext(
        menu_name="main",
        title="Generation",
        text="Choose an operation",
        width=24,
    ),
    content_source="Ready",
)


def generate(context: CommandContext) -> None:
    context.menu.set_content_source("Generated")


menu.add_command("Generate", generate)
app.set_main_menu(menu)
app.run()
```

`TerminalApp.run()` is blocking. Call it from Python's main thread in a real
interactive terminal. It switches to the terminal's alternate screen and hides
the cursor while the application runs, then restores input, cursor, and screen
state before returning or propagating an exception.

## Core concepts

A Tuiloom application has three main layers:

1. `TerminalApp` owns application-wide configuration, global commands,
   messages, captured-output state, and the root menu.
2. `TerminalMenu` owns selectable commands, content, input, alerts, local
   overrides, and its event loop.
3. `ScreenContext` is the mutable visible state of one menu: name, title,
   minimum width, descriptive text, and footer message.

Every menu belongs to exactly one application. A submenu and its parent must
belong to the same `TerminalApp`. Registering a menu with `set_main_menu()` makes
its automatic final row `Quit`; other menus use `Back`. Registering another main
menu restores `Back` on the previous one.

Callbacks receive a frozen `CommandContext` containing the active application,
menu, command handle, and triggering binding:

```python
from tuiloom import CommandContext


def inspect_invocation(context: CommandContext) -> None:
    context.menu.show_alert(
        f"Command: {context.command!r}\nBinding: {context.binding!r}"
    )
```

## Navigation and focus

The menu has focus initially. The default controls are:

| Key | Action |
| --- | --- |
| Tab | Cycle through the menu and each content panel |
| Up / Down | Move the selected command, or scroll focused content vertically |
| Left / Right | Scroll focused content horizontally |
| Enter | Activate the selected command or confirm an alert |
| Escape | Leave input mode, go Back, or request Quit |

Command selection loops and skips disabled commands. The automatic `Back` or
`Quit` row is always selectable and always follows user commands. The selected
row contains `>`, so it remains visible without ANSI color support.

Tab changes focus only when the menu has content. It cycles through
`menu -> panel 1 -> panel 2 -> ... -> menu`. Focused boxes use solid borders;
unfocused boxes use dotted borders. Moving upward while
`auto_scroll="smart"` suspends automatic following, and reaching the bottom
enables it again.

All controls can be remapped through `KeyMap`; see
[Key bindings and global commands](#key-bindings-and-global-commands).

## Screen state and visibility

`ScreenContext` fields are live and mutable. Tuiloom observes changes while the
menu runs:

```python
menu.screen_context.title = "New title"
menu.screen_context.text = "Updated instructions"
menu.screen_context.message = "Saved"
menu.screen_context.width = 32
```

`width` is the minimum inner width, not a fixed terminal width. It must be a
positive integer or `None`; booleans are rejected. Tuiloom renders a
terminal-too-small message when the complete frame cannot fit.

By default, a content box and menu box have one blank row between them. Pass
`content_spacing=False` to remove it.

Setting `menu.show = False` clears the entire frame while its event loop,
content sources, and tasks keep running. While hidden, only global commands and
the Back/Escape binding are handled; other input is discarded and cannot be
replayed when the menu becomes visible again.

## Commands and submenus

### Menu commands

`add_command()` returns a stable `MenuCommand` handle. Use the owning menu to
mutate it:

```python
def connect(context: CommandContext) -> None:
    context.menu.show_alert("Connected")


def disconnect(context: CommandContext) -> None:
    context.menu.clear_alert()


command = menu.add_command("Connect", connect)
menu.set_command_label(command, "Disconnect")
menu.set_command_behavior(command, disconnect)
menu.move_command(command, 0)
menu.disable_command(command)
menu.enable_command(command)
menu.set_exit_label("Close")
```

Positions are zero-based. `position=None` appends a command; an explicit valid
position inserts it there. Booleans, negative positions, and out-of-range
positions are rejected before mutation. `menu.commands` is an immutable tuple
view, and a handle from another menu is rejected.

The handle exposes read-only `label`, `behavior`, `position`, and `enabled`
properties. Their current values reflect mutations performed through the menu.

### Submenus

```python
settings = TerminalMenu(
    app,
    ScreenContext("settings", "Settings", text="Configure the application"),
)
open_settings = menu.add_menu(settings, "Settings", position=0)
```

Activating the returned command runs the submenu until its `Back` row is
activated. The parent then resumes. `add_menu()` rejects a submenu owned by a
different application.

## Content sources

`ContentSource` accepts exactly four forms:

```python
from collections.abc import Iterator

static_text = "one\ntwo"
static_lines = ["one", "two"]


def stream() -> Iterator[str]:
    yield "one\n"
    yield "two\n"


def refreshed() -> str | list[str]:
    return ["current", "state"]


menu.set_content_source(static_text)
menu.set_content_source(static_lines)
menu.set_content_source(stream(), description="Loading records")
menu.set_content_source(refreshed, description="Refreshing state")
```

The forms behave differently:

| Source | Behavior |
| --- | --- |
| `str` | Static text split into display lines |
| `list[str]` | Static lines displayed as supplied |
| `Iterator[str]` | A background worker consumes chunks until exhaustion |
| `Callable[[], str \| list[str]]` | A background worker repeatedly evaluates the latest state |

Static content is normalized immediately. Iterator chunks may contain partial
lines and multiple newlines; carriage returns replace the unfinished line, which
supports progress-style output. Iterators must yield only strings. Dynamic
callables must return `str` or `list[str]` and have at most one evaluation in
flight.

Unsafe terminal controls are removed from rendered content. Unicode graphemes,
cell widths, safe SGR styling, tabs, and line boundaries are normalized for the
terminal.

### Multiple content panels

`add_content_panel()` creates an independently managed content box and returns
a stable `ContentPanel` handle:

```python
logs = menu.add_content_panel(
    log_stream,
    description="Downloading",
    auto_scroll="strict",
)
metrics = menu.add_content_panel(
    get_metrics,
    description="Indexing",
)

logs.set_source(new_log_stream)
logs.set_description("Downloading model")
logs.set_auto_scroll("smart")
metrics.move(0)
metrics.remove()
```

`menu.content_panels` exposes the handles in display order as an immutable
tuple. Visible panels are stacked vertically at equal height and labeled when
more than one is present. Each panel owns its source worker, viewport, scroll
position, and auto-scroll mode. Panels can be added, reordered, replaced, or
removed while the menu is running.

The constructor's `content_source`, `set_content_source()`, and
`menu.auto_scroll` remain the compatibility API for the primary panel. A menu
with only that panel keeps the original unlabeled content-box appearance.

### Inherited and local content

```python
app = TerminalApp("Monitor", global_content_source="Shared status")
inherited = TerminalMenu(app, ScreenContext("main", "Main"))
local = TerminalMenu(
    app,
    ScreenContext("logs", "Logs"),
    content_source="Local status",
)
```

A menu constructed with `content_source=None` takes the application's
`global_content_source`. A local source wins when supplied. If neither exists,
the content box is omitted and `NO_CONTENT_SOURCE` is shown in the footer when
the menu starts.

### Replacing active content

`set_content_source(source, description=...)` changes the primary panel.
`panel.set_source(source)` applies the same replacement semantics to any panel.
If the menu is running, Tuiloom installs the source through the active event
loop.

Replacing an iterator or an in-flight dynamic evaluation requests cooperative
cancellation of the old source. The UI remains responsive, waits for the old
worker to stop, and then installs only the latest requested replacement. If
several replacements arrive during cleanup, the last request wins. Results and
errors from an explicitly cancelled source are discarded; ordinary source
errors still propagate after resources are cleaned up.

For cooperative iterator cancellation, Tuiloom calls an optional `cancel()`
method as soon as cancellation is requested and an optional `close()` method
when the consumer exits. A blocking iterator should implement `cancel()` so it
can wake or release its own `__next__()` call. A dynamic callable cannot be
interrupted in the middle of an evaluation; that call must return before its
worker can stop.

### Auto-scroll

Set `auto_scroll` in the constructor or later:

```python
menu = TerminalMenu(
    app,
    ScreenContext("logs", "Logs"),
    content_source=stream(),
    auto_scroll="smart",
)

menu.auto_scroll = "strict"
menu.auto_scroll = None

logs.set_auto_scroll("smart")
```

- `"smart"` follows new iterator content until the user scrolls upward, then
  resumes when the viewport reaches the bottom.
- `"strict"` always follows the newest iterator content.
- `None` disables automatic following.

Changing a panel's mode or replacing its content resets its smart-scroll state.
Invalid modes raise `ValueError`.

## Captured task output

`run_with_output()` runs blocking Python work on a non-daemon worker and uses
its captured stdout/stderr as the menu's temporary content source:

```python
def download() -> str:
    print("Downloading…")
    return "archive.zip"


def start_download(context: CommandContext) -> None:
    context.menu.run_with_output(
        download,
        on_success=lambda path: context.menu.show_alert(f"Saved {path}"),
        on_error=lambda error: context.menu.show_alert(str(error)),
        description="Downloading archive",
    )


menu.add_command("Download", start_download)
```

The call itself starts the work and returns immediately. It is valid only while
the menu is active, and only one captured task may run in the application at a
time. A second task raises `RuntimeError`.

During the task, output appears in a temporary panel with strict auto-scroll;
the menu's other panels remain visible and unchanged. On normal completion,
Tuiloom removes the temporary panel after its output is consumed, then runs
`on_success(result)` or `on_error(exception)` on the UI thread.

Capture includes `print()` and Python writes to `sys.stdout` and `sys.stderr`.
It cannot capture subprocess output or direct POSIX file-descriptor writes.
Tuiloom does not inject a cancellation token into `action`. Wait and quit
therefore requires the action to return, while Force quit terminates the whole
process without waiting for the action.

## Safe shutdown

Quitting the root menu while one operation is active opens a normal menu titled
`Operation in progress`; multiple operations use `Operations in progress`:

```text
Force quit
Wait and quit
Cancel
```

- **Force quit** immediately restores the terminal and terminates the process
  with status zero because it is an explicitly handled user action. It does not
  wait for active Python threads or native calls, and it does not run their
  completion callbacks. Partial third-party writes, such as model cache
  downloads, may be resumed or cleaned up by that library on the next launch.
- **Wait and quit** lets work finish normally, animates its description, runs a
  captured task's completion callback, and exposes only a selectable `Cancel`
  row while waiting.
- **Cancel** restores the previous menu, focus, and selection. The configured
  Back action is equivalent to Cancel in both interactive exit states.

Navigate with the configured Up/Down actions and activate with Enter. The former
numeric shortcuts `1`, `2`, and `0` are not accepted.

Iterator sources count as active work until they finish. Dynamic sources count
as active only while an evaluation is in progress. Static content does not block
exit. Every active operation is displayed in its own labeled panel. The list is
live in every mode: completed panels disappear immediately, singular/plural
titles update, and newly started operations are included. The application exits
automatically when no blocking operation remains, even before a choice is made.

**Wait and quit** and ordinary shutdown use cooperative cancellation and wait
without a timeout before restoring the terminal. **Force quit** is the escape
hatch for native or application code that does not return: it restores terminal
modes and then terminates the whole process without waiting for workers.

The same guarantee applies when a callback, source, or renderer raises: Tuiloom
joins active workers before restoring the terminal and propagating the error.

## Free-form and hidden input

```python
def submit_password(value: str) -> None:
    if value:
        menu.leave_input_mode()
        menu.show_alert("Password received")


menu.enter_input_mode("Password: ", submit_password, hidden=True)
```

`enter_input_mode()` clears the previous buffer. Printable input is appended,
Backspace removes a complete Unicode grapheme, Enter calls the `InputBehavior`
with the full string, and Escape calls `leave_input_mode()` without submitting.
The callback decides whether input mode stays active after submission.

With `hidden=True`, one `*` is displayed per grapheme, including combining
characters and emoji sequences. The original Unicode text is passed to the
callback. Every global command is disabled while free-form input is active.

An alert temporarily suspends the prompt, buffer, hidden state, and input
callback without destroying them. Clearing the alert reveals the same input
state again.

## Alerts

A blocking alert has no confirmation prompt and Enter does not close it:

```python
menu.show_alert("Waiting for an external event")
menu.clear_alert()
```

A confirmable alert receives a `CommandContext`:

```python
menu.show_alert(
    "Saved",
    on_confirm=lambda context: context.menu.set_content_source("Ready"),
    prompt="Continue",
)
```

If `prompt` is omitted for a confirmable alert, Tuiloom uses
`Press Enter to continue`. The alert is cleared only after its callback returns
normally. If the callback raises, the alert remains and the exception
propagates. Alert confirmation has `context.command is None` and the Enter
binding in `context.binding`.

Alerts preserve the content box. Global commands remain active while an alert
is displayed, and Escape still performs Back/Quit.

## Messages

Messages occupy `ScreenContext.message`, the menu footer. Register custom
messages on the application, then show or suppress them by key:

```python
from tuiloom import MessageKey

app.add_message("connected", "Connected successfully")
menu.show_message("connected")       # True when displayed
menu.clear_message()

menu.disable_message("connected")    # suppress only in this menu
menu.enable_message("connected")
app.disable_message("connected")     # suppress in every menu
app.enable_message("connected")

menu.show_message(MessageKey.NO_CONTENT_SOURCE)
```

The built-in keys are:

| `MessageKey` | Value | Purpose |
| --- | --- | --- |
| `NO_CONTENT_SOURCE` | `"no_content_source"` | Explain a missing content source |
| `UNKNOWN_COMMAND` | `"unknown_command"` | Report discarded textual command input |
| `TASK_EXIT_CHOICES` | `"task_exit_choices"` | Compatibility key for the former numeric exit prompt |
| `TASK_WAITING` | `"task_waiting"` | Compatibility key for the former waiting footer |
| `TASK_STOPPING` | `"task_stopping"` | Compatibility key for the former stopping footer |

`show_message()` validates the key and returns `False` without changing the
footer when the message is suppressed. Otherwise it displays the message and
returns `True`. Local and application-wide suppression combine;
`is_message_enabled()` reports the effective state. Unknown keys raise
`KeyError`. Custom keys must be nonempty and unique, including against built-in
keys.

Automatic messages use the same registry and respect suppression.
The three `TASK_*` compatibility keys remain available to application code but
no longer control Tuiloom's automatic task-exit menu.

## Key bindings and global commands

### Custom system bindings

```python
from tuiloom import KeyBinding, KeyMap, TerminalApp

keymap = KeyMap()
keymap.set_binding("focus", KeyBinding("f", ctrl=True))
app = TerminalApp("App", keymap=keymap)
```

The seven system actions are `focus`, `up`, `down`, `left`, `right`, `activate`,
and `back`. `keymap.bindings` is a read-only live mapping, and the same bindings
are available as `keymap.focus`, `keymap.up`, and so on. `action_for(binding)`
returns the matching action or `None`.

`set_binding()` rejects unknown actions, non-`KeyBinding` values, and collisions
with another system action or application global command. Validation happens
before mutation, so a failure leaves the previous binding unchanged.

`KeyBinding` accepts a nonempty key string or normalized special-key name and the
boolean modifiers `ctrl`, `alt`, and `shift`. These aliases normalize to the
canonical names:

| Alias | Canonical key |
| --- | --- |
| `return` | `enter` |
| `esc` | `escape` |
| `arrow_up` | `up` |
| `arrow_down` | `down` |
| `arrow_left` | `left` |
| `arrow_right` | `right` |

Multi-character names are lowercased. Terminal protocols cannot always report
every modifier distinctly: Ctrl+letter is commonly case-insensitive, and Shift
may arrive only as character case.

### Invisible global commands

```python
def refresh(context: CommandContext) -> None:
    context.menu.set_content_source("Refreshed")


refresh_command = app.add_global_command(
    KeyBinding("r", ctrl=True),
    "Refresh",
    refresh,
)

app.set_global_command_binding(refresh_command, KeyBinding("f5"))
app.set_global_command_label(refresh_command, "Reload")
app.set_global_command_behavior(refresh_command, refresh)
```

Global commands are invoked immediately when their binding arrives and are not
rendered as menu rows. `app.global_commands` is an immutable tuple of handles;
their read-only metadata can power a custom help screen.

A menu can override or disable an application global command locally:

```python
menu.set_global_command_behavior(refresh_command, refresh)
menu.disable_global_command(refresh_command)
menu.enable_global_command(refresh_command)
menu.clear_global_command_behavior(refresh_command)
```

Global-command handles belong to one application. Foreign handles are rejected.
Global commands remain available while a menu is hidden or an alert is shown,
but not during free-form input or a root task-exit choice.

Input priority is: task-exit choice, hidden-menu handling, free-form input,
global commands, alerts, then focus/navigation. Unknown terminal sequences are
consumed and do not block later input.

## Terminal hyperlinks

```python
from tuiloom import hyperlink

label = hyperlink("Project", "https://github.com/maroard/Tuiloom")
```

`hyperlink()` produces a complete OSC 8 hyperlink. It accepts only absolute
HTTP or HTTPS URLs with a network location. Empty URLs, whitespace, C0/C1
controls, Escape, and backslash are rejected with `ValueError`.

Visible text is sanitized: unsafe controls and nested OSC links are removed,
while printable Unicode and safe SGR color/style sequences are preserved.

## API reference

All supported imports come directly from `tuiloom`:

```python
from tuiloom import (
    AutoScrollMode,
    CommandBehavior,
    CommandContext,
    ContentPanel,
    ContentSource,
    GlobalCommand,
    InputBehavior,
    KeyBinding,
    KeyMap,
    MenuCommand,
    MessageKey,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
    hyperlink,
)
```

Anything outside this export list is internal and may change without notice.

### Type aliases

```python
type ContentSource = (
    str
    | list[str]
    | Iterator[str]
    | Callable[[], str | list[str]]
)
type AutoScrollMode = Literal["smart", "strict"]
type CommandBehavior = Callable[[CommandContext], None]
type InputBehavior = Callable[[str], None]
```

`AutoScrollMode | None` is used where automatic scrolling may be disabled.

### `ScreenContext`

```text
ScreenContext(
    menu_name: str,
    title: str,
    width: int | None = None,
    text: str | None = None,
    message: str | None = None,
)
```

A mutable dataclass holding visible menu state:

- `menu_name`: internal name used in contextual messages;
- `title`: heading in the menu box;
- `width`: positive minimum inner width, or `None` for content-based sizing;
- `text`: optional description above commands;
- `message`: optional footer.

Construction and later assignment validate `width`; invalid values raise
`ValueError`.

### `KeyBinding`

```text
KeyBinding(
    key: str,
    ctrl: bool = False,
    alt: bool = False,
    shift: bool = False,
)
```

A frozen, hashable binding value. `key` must be a nonempty string or
construction raises `ValueError`; every modifier must be `bool` or construction
raises `TypeError`. Special aliases and multi-character normalization are
described above.

### `KeyMap`

```python
KeyMap()
```

- `bindings` → `Mapping[str, KeyBinding]`: read-only live action mapping.
- `focus`, `up`, `down`, `left`, `right`, `activate`, `back -> KeyBinding`:
  current bindings exposed as dynamic read-only properties.
- `set_binding(action: str, binding: KeyBinding) -> None`: atomically replace a
  system binding. Raises `KeyError` for an unknown action, `TypeError` for a
  non-binding, or `ValueError` for a collision.
- `action_for(binding: KeyBinding) -> str | None`: return the matching system
  action.

### `CommandContext`

```text
CommandContext(
    app: TerminalApp,
    menu: TerminalMenu,
    command: MenuCommand | GlobalCommand | None,
    binding: KeyBinding | None,
)
```

A frozen dataclass created by Tuiloom for callbacks. `command` is `None` for
alert confirmation. `binding` may be `None` for programmatic execution.

### `MenuCommand`

```text
MenuCommand(
    menu: TerminalMenu,
    label: str,
    behavior: CommandBehavior,
)
```

Applications normally obtain this stable handle from `add_command()` or
`add_menu()` instead of constructing it directly. Its properties are read-only:

- `label -> str`;
- `behavior -> CommandBehavior`;
- `position -> int`, zero-based among user commands;
- `enabled -> bool`.

Use the owning menu's `set_command_*`, `move_command`, `disable_command`, and
`enable_command` methods to mutate it.

### `GlobalCommand`

```text
GlobalCommand(
    app: TerminalApp,
    binding: KeyBinding,
    label: str,
    behavior: CommandBehavior,
)
```

Applications normally obtain this handle from `add_global_command()`. Its
read-only properties are `binding`, `label`, and `behavior`. Use the owning
application's `set_global_command_*` methods for application-wide mutation, or a
menu's global-command methods for local behavior and enablement.

### `MessageKey`

`MessageKey` is a `StrEnum` with `NO_CONTENT_SOURCE`, `UNKNOWN_COMMAND`,
`TASK_EXIT_CHOICES`, `TASK_WAITING`, and `TASK_STOPPING`. The values and purpose
of each member are listed in [Messages](#messages). Enum members can be passed
where a message key string is accepted.

The three task-related members are retained for compatibility. The automatic
safe-shutdown interface is rendered as a temporary menu and does not read these
message values.

### `ContentPanel`

Applications obtain `ContentPanel` handles from
`TerminalMenu.add_content_panel()` rather than constructing them directly.

Read-only properties:

- `description -> str`: current visible and shutdown label;
- `position -> int`: current zero-based display position;
- `auto_scroll -> AutoScrollMode | None`: independent iterator-follow policy.

Explicit mutation methods:

```text
set_source(content_source: ContentSource) -> None
set_description(description: str) -> None
set_auto_scroll(mode: AutoScrollMode | None) -> None
move(position: int) -> None
remove() -> None
```

The handle keeps its identity across source, label, mode, and position changes.
Calling a mutation method after removal raises `ValueError`.

### `TerminalApp`

```text
TerminalApp(
    name: str,
    global_content_source: ContentSource | None = None,
    *,
    keymap: KeyMap | None = None,
)
```

The constructor stores the display name, optional content inherited by menus
created without a local source, and an optional custom system key map.

Read-only properties:

- `name -> str`: application name displayed by every menu;
- `global_content_source -> ContentSource | None`: source inherited at menu
  construction;
- `keymap -> KeyMap`: configurable system key map;
- `global_commands -> tuple[GlobalCommand, ...]`: immutable ordered handle view;
- `main_menu -> TerminalMenu | None`: registered root menu.

Methods:

```text
set_main_menu(menu: TerminalMenu) -> None
```

Register an application-owned root menu and update automatic exit labels.
Raises `ValueError` for a foreign menu.

```text
add_global_command(
    binding: KeyBinding,
    label: str,
    behavior: CommandBehavior,
) -> GlobalCommand
```

Register an invisible application command. Raises `TypeError` for a non-binding
and `ValueError` when the binding collides with a system or global command.

```text
set_global_command_binding(
    command: GlobalCommand,
    binding: KeyBinding,
) -> None
set_global_command_label(command: GlobalCommand, label: str) -> None
set_global_command_behavior(
    command: GlobalCommand,
    behavior: CommandBehavior,
) -> None
```

Mutate an owned global handle. Binding replacement is validated atomically.
Foreign handles raise `ValueError`.

```text
add_message(key: str, text: str) -> None
disable_message(key: str) -> None
enable_message(key: str) -> None
```

Register or globally suppress messages. `add_message()` raises `ValueError` for
an empty or duplicate key; enable/disable raise `KeyError` for unknown keys.

```text
run() -> None
```

Run the registered main menu. Raises `RuntimeError` if no main menu exists or if
called outside Python's main thread. It blocks until the application exits,
joins workers, restores terminal state, and then propagates any pending error.

### `TerminalMenu`

```text
TerminalMenu(
    app: TerminalApp,
    screen_context: ScreenContext,
    content_source: ContentSource | None = None,
    content_spacing: bool = True,
    show: bool = True,
    auto_scroll: AutoScrollMode | None = None,
)
```

Create a menu owned by `app`. `content_source=None` inherits application
content. `content_spacing` and `show` must be booleans. `auto_scroll` accepts
`"smart"`, `"strict"`, or `None`.

Properties:

- `app -> TerminalApp`: read-only owner;
- `screen_context -> ScreenContext`: read-only reference to mutable display
  state;
- `commands -> tuple[MenuCommand, ...]`: immutable ordered handle view;
- `is_main -> bool`: whether this is the registered root;
- `show -> bool`: readable and writable visibility state;
- `auto_scroll -> AutoScrollMode | None`: readable and writable iterator-follow
  policy for the primary panel;
- `content_panels -> tuple[ContentPanel, ...]`: immutable ordered panel-handle
  view.

#### Command methods

```text
add_command(
    label: str,
    behavior: CommandBehavior,
    *,
    position: int | None = None,
) -> MenuCommand
add_menu(
    submenu: TerminalMenu,
    label: str,
    *,
    position: int | None = None,
) -> MenuCommand
```

Add a command or application-owned submenu and return its stable handle.
Invalid positions raise `TypeError` or `ValueError`; foreign submenus raise
`ValueError`.

```text
set_command_label(command: MenuCommand, label: str) -> None
set_command_behavior(
    command: MenuCommand,
    behavior: CommandBehavior,
) -> None
move_command(command: MenuCommand, position: int) -> None
disable_command(command: MenuCommand) -> None
enable_command(command: MenuCommand) -> None
set_exit_label(label: str) -> None
```

Mutate owned menu commands or the automatic Back/Quit label. `move_command()`
requires an existing zero-based position. Foreign handles raise `ValueError`.

#### Global-command methods

```text
set_global_command_behavior(
    command: GlobalCommand,
    behavior: CommandBehavior,
) -> None
clear_global_command_behavior(command: GlobalCommand) -> None
disable_global_command(command: GlobalCommand) -> None
enable_global_command(command: GlobalCommand) -> None
```

Override, restore, disable, or enable an application global command in this menu
only. Foreign handles raise `ValueError`.

#### Content and task methods

```text
add_content_panel(
    content_source: ContentSource,
    *,
    description: str = "Content in progress",
    auto_scroll: AutoScrollMode | None = None,
    position: int | None = None,
) -> ContentPanel
```

Add an independently rendered panel and return its stable handle. `position`
is zero-based; invalid positions or auto-scroll modes raise `TypeError` or
`ValueError`.

```text
set_content_source(
    content_source: ContentSource,
    *,
    description: str = "Content in progress",
) -> None
```

Store and, while active, safely install the primary panel's content source.
Replacement semantics are described in
[Replacing active content](#replacing-active-content).

```text
run_with_output[T](
    action: Callable[[], T],
    *,
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None],
    description: str = "Task in progress",
) -> None
```

Start one captured application task. Raises `RuntimeError` outside an active
menu or when another task is running. Completion callbacks run on the UI thread.

#### Input and alert methods

```text
enter_input_mode(
    prompt: str,
    behavior: InputBehavior,
    *,
    hidden: bool = False,
) -> None
leave_input_mode() -> None
```

Start a fresh input buffer or clear all input state.

```text
show_alert(
    text: str,
    *,
    on_confirm: CommandBehavior | None = None,
    prompt: str | None = None,
) -> None
clear_alert() -> None
```

Show a blocking/confirmable alert or clear it and reveal suspended input state.

#### Message methods

```text
show_message(key: str) -> bool
clear_message() -> None
disable_message(key: str) -> None
enable_message(key: str) -> None
is_message_enabled(key: str) -> bool
```

Show, clear, locally suppress, or inspect registered messages. Every keyed
operation validates the key. Effective enablement combines local and global
suppression.

#### Lifecycle methods

```text
run() -> None
stop() -> None
```

`run()` runs the menu until Back/Quit and is intended for the application or a
submenu callback; calling it outside `TerminalApp.run()` raises `RuntimeError`.
`stop()` requests Back/Quit. On the root menu it presents safe shutdown choices
when background work is active; otherwise it stops immediately.

### `hyperlink`

```text
hyperlink(text: str, url: str) -> str
```

Return sanitized visible text wrapped in a complete OSC 8 open/close pair.
Unsafe or non-HTTP(S) URLs raise `ValueError`.

## Runtime constraints

- `TerminalApp.run()` is blocking, main-thread-only, and requires an interactive
  terminal.
- Only one `run_with_output()` task can run per application.
- Python stdout/stderr capture does not include subprocess or direct
  file-descriptor output.
- Normal shutdown joins non-daemon content and task workers before returning.
  Force quit instead restores terminal modes and terminates the process without
  joining workers.
- Terminal protocols may collapse modifier combinations, so not every theoretical
  `KeyBinding` is distinguishable on every terminal.
- Rendered content is Unicode-cell-aware and sanitizes unsafe terminal control
  sequences, but application callbacks remain responsible for their own domain
  errors and side effects.

## Development

Clone the repository and install the locked development environment:

```bash
git clone https://github.com/maroard/Tuiloom.git
cd Tuiloom
make install
```

Available checks:

```bash
make check       # Ruff lint/format check, strict MyPy, tests, and coverage
make fix         # apply Ruff formatting and safe lint fixes
make build       # build wheel/sdist and validate both with Twine
```

CI runs on Linux and macOS with Python 3.12, 3.13, and 3.14. It verifies typing,
tests, at least 90% branch-aware coverage, distributions, package metadata,
`py.typed`, licensing, and installation of the built wheel in a clean
environment.

Tuiloom is released under the [MIT License](LICENSE). Report defects and request
features through [GitHub Issues](https://github.com/maroard/Tuiloom/issues).
