# Tuiloom

Tuiloom builds typed, keyboard-navigable terminal menus with dynamic content,
Unicode-safe rendering, captured task output, alerts, and free-form input. It
supports Python 3.12–3.14 on Linux and macOS.

> Tuiloom is not published yet. The API described here is the pre-PyPI API.

## Installation

```bash
pip install tuiloom
```

## First menu

```python
from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu

app = TerminalApp("Generator")
menu = TerminalMenu(
    app,
    ScreenContext(
        menu_name="main",
        title="Generation",
        text="Choose an operation",
        width=24,  # minimum inner width, not a fixed width
    ),
    content_source="Ready",
)

def generate(context: CommandContext) -> None:
    context.menu.set_content_source("Generated")

menu.add_command("Generate", generate)
app.set_main_menu(menu)
app.run()
```

`TerminalApp.run()` is blocking. It requires an interactive terminal and must
run on the Python main thread. Terminal and cursor state are restored if a
callback or renderer raises.

## Navigation and focus

The menu initially has focus. Up and Down move the selected command in a loop,
Enter activates it, and Escape activates the automatic final `Back` or `Quit`
option. The selected row always contains `>` so selection remains visible
without ANSI colors.

When content exists, Tab alternates focus between the menu and content boxes.
With content focused, all four arrows move its viewport. Manual upward movement
suspends `auto_scroll="smart"`; reaching the bottom resumes it.

Focused boxes use solid borders and unfocused boxes use dotted borders. A menu
without content has one solid box and Tab does nothing. Use
`content_spacing=False` to remove the otherwise single blank row between boxes.

## Content sources

All four `ContentSource` forms are accepted:

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
menu.set_content_source(refreshed)
```

An omitted menu source inherits `TerminalApp.global_content_source`. A content
box is rendered only when a source exists. Iterators count as active work until
they finish. Dynamic callables count as active only while an evaluation is in
progress. Replacing an active source cancels it cooperatively; the UI stays
responsive, waits for that worker to stop, then starts only the latest requested
replacement.

## Stable command handles

Adding a command returns a stable handle. Positions are zero-based; booleans,
negative positions, and out-of-range positions are rejected immediately.

```python
command = menu.add_command("Connect", connect)
menu.set_command_label(command, "Disconnect")
menu.set_command_behavior(command, disconnect)
menu.move_command(command, 0)
menu.disable_command(command)
menu.enable_command(command)
menu.set_exit_label("Close")
```

Submenus must belong to the same application and are validated when added:

```python
settings = TerminalMenu(app, ScreenContext("settings", "Settings"))
open_settings = menu.add_menu(settings, "Settings", position=0)
```

`CommandContext.command` is the invoked `MenuCommand` or `GlobalCommand`.
`CommandContext.binding` is its triggering `KeyBinding`. Alert confirmation uses
`command=None` and the Enter binding.

## Bindings and global commands

```python
from tuiloom import KeyBinding, KeyMap, TerminalApp

keymap = KeyMap()
keymap.set_binding("focus", KeyBinding("f", ctrl=True))
app = TerminalApp("App", keymap=keymap)

refresh = app.add_global_command(
    KeyBinding("r", ctrl=True),
    "Refresh",
    refresh_callback,
)
app.set_global_command_binding(refresh, KeyBinding("f5"))
app.set_global_command_label(refresh, "Reload")
app.set_global_command_behavior(refresh, reload_callback)
```

Global commands are intentionally invisible. `app.global_commands` is a
read-only tuple of handles whose binding, label, and callback metadata can be
used to build custom help text. A menu may override or disable one locally:

```python
menu.set_global_command_behavior(refresh, local_refresh)
menu.disable_global_command(refresh)
menu.enable_global_command(refresh)
menu.clear_global_command_behavior(refresh)
```

System and global bindings cannot collide. Mutations validate first and leave
the old binding unchanged on failure. Terminals using legacy keyboard protocols
cannot distinguish every modifier combination: Ctrl+letter is often
case-insensitive and Shift may be represented only by character case.

## Free-form and hidden input

```python
def submit_password(value: str) -> None:
    if value:
        menu.leave_input_mode()

menu.enter_input_mode("Password: ", submit_password, hidden=True)
```

Hidden masking and Backspace operate on complete Unicode graphemes, including
combining characters and emoji sequences. During free-form entry every global
command is disabled. Enter submits the current value and Escape leaves input
mode.

Input priority is: task-exit choice, hidden-menu handling, free-form input,
global commands, alerts, then focus/navigation. Unknown terminal sequences are
consumed and never block later input.

## Alerts

A blocking alert has no misleading confirmation prompt and Enter does not close
it:

```python
menu.show_alert("Waiting for an external event")
menu.clear_alert()
```

A confirmable alert receives a `CommandContext` and closes only when its callback
returns normally:

```python
menu.show_alert(
    "Saved",
    on_confirm=lambda context: context.menu.set_content_source("Ready"),
    # prompt="Continue",  # optional; default is Press Enter to continue
)
```

Alerts preserve the content box and suspend any input prompt, buffer, hidden
state, and callback. Clearing the alert restores them. Global commands remain
active while an alert is shown.

## Messages and visibility

```python
from tuiloom import MessageKey

app.add_message("saved", "Saved successfully")
menu.show_message("saved")       # True when displayed
menu.clear_message()
menu.disable_message("saved")    # local suppression
app.disable_message("saved")     # application-wide suppression

menu.show_message(MessageKey.NO_CONTENT_SOURCE)
```

`MessageKey` also includes unknown-input and captured-task exit/wait messages.
Message keys are validated by every enable/disable/show operation. A suppressed
message returns `False` from `show_message()` without replacing the current
footer.

Setting `menu.show = False` clears the complete frame while its loop, sources,
and tasks keep running. Only global commands and Escape remain active; all other
input is discarded and cannot reappear when the menu is shown again.

## Captured task output and closing

```python
def download() -> str:
    print("Downloading…")
    return "archive.zip"

menu.run_with_output(
    download,
    on_success=lambda path: menu.show_alert(f"Saved {path}"),
    on_error=lambda error: menu.show_alert(str(error)),
    description="Download in progress",
)
```

Only one application task may run at a time. Its callback runs on the UI thread.
Capture covers `print` and Python writes to `sys.stdout`/`sys.stderr`; subprocess
output and direct POSIX file-descriptor writes are not captured.

Quitting the root menu during a captured task, an iterator, or an in-progress
dynamic evaluation displays:

- `1`: stop and quit, request cooperative cancellation, discard later results,
  errors, output, and callbacks, then keep showing `Stopping…` until every worker
  has really stopped;
- `2`: wait and quit, animate the description, run the completion callback, then
  restore the terminal and quit even if the callback changes menus;
- `0`: cancel the exit request and restore the previous footer.

While waiting normally, `0` remains available. Once stop has been requested it
is irreversible. `TASK_STOPPING` is a registered message key and can be disabled
like the other built-in messages.

Python cannot safely kill an arbitrary thread. Tuiloom therefore uses
cooperative cancellation and waits without a timeout before closing sockets,
restoring the terminal, or returning from the application. Native code that
never returns can consequently leave `Stopping…` visible indefinitely; use a
separate process when forceful termination is required. Terminal restoration is
also delayed until workers finish when a callback or renderer raises.

## Terminal hyperlinks

```python
from tuiloom import hyperlink

label = hyperlink("Project", "https://github.com/maroard/Tuiloom")
```

Only absolute HTTP/HTTPS URLs with a network location are accepted. Whitespace,
C0/C1 controls, Escape, and backslash are rejected. Link text is sanitized while
safe SGR styles are preserved.

## Development

```bash
make install
make check       # read-only lint, format, strict MyPy, tests and coverage
make fix         # the only formatting/fix target
make build       # wheel + sdist + twine check
```

CI runs Linux and macOS with Python 3.12, 3.13, and 3.14, then verifies the
distributions and installs the wheel in a fresh environment.
