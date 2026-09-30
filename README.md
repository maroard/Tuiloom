# Tuiloom

[![PyPI](https://img.shields.io/pypi/v/tuiloom.svg)](https://pypi.org/project/tuiloom/)
[![Python](https://img.shields.io/pypi/pyversions/tuiloom.svg)](https://pypi.org/project/tuiloom/)
[![CI](https://github.com/maroard/Tuiloom/actions/workflows/ci.yml/badge.svg)](https://github.com/maroard/Tuiloom/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/tuiloom.svg)](https://github.com/maroard/Tuiloom/blob/main/LICENSE)

Tuiloom builds typed, keyboard-navigable terminal menus with dynamic content,
Unicode-safe rendering, captured task output, alerts, and free-form input. It is
small enough to learn from one document while still handling the awkward parts
of terminal state and background-work shutdown.

This README documents the complete public API of Tuiloom 0.10.0. Tuiloom requires
Python 3.12 or newer and is tested on Linux and macOS with Python 3.12–3.14.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Core concepts](#core-concepts)
- [Navigation and focus](#navigation-and-focus)
- [Screen state and visibility](#screen-state-and-visibility)
- [Overlay menus](#overlay-menus)
- [Commands and submenus](#commands-and-submenus)
- [Screen content](#screen-content)
- [Content layouts](#content-layouts)
- [Status bar](#status-bar)
- [Captured task output](#captured-task-output)
- [Safe shutdown](#safe-shutdown)
- [Free-form and hidden input](#free-form-and-hidden-input)
- [Alerts](#alerts)
- [Messages](#messages)
- [Key bindings and global commands](#key-bindings-and-global-commands)
- [Text styling](#text-styling)
- [Terminal hyperlinks](#terminal-hyperlinks)
- [API reference](#api-reference)
- [Runtime constraints](#runtime-constraints)
- [Strict API migration](#strict-api-migration)
- [Development](#development)

## Installation

Install the latest release from PyPI:

```bash
python -m pip install tuiloom
```

To install this version explicitly:

```bash
python -m pip install tuiloom==0.10.0
```

Tuiloom ships inline typing information through `py.typed` and has no required
framework or event-loop dependency.

## Quick start

```python
from tuiloom import (
    CommandContext,
    ScreenContent,
    MenuDisplay,
    TerminalApp,
    TerminalMenu,
)

app = TerminalApp("Generator")
menu = TerminalMenu(
    app,
    MenuDisplay(
        menu_name="main",
        title="Generation",
        text="Choose an operation",
        width=24,
    ),
)
status = menu.add_content_panel(ScreenContent.static("Ready"))


def generate(context: CommandContext) -> None:
    status.set_content(ScreenContent.static("Generated"))


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
2. `TerminalMenu` owns selectable commands, content panels, input, alerts,
   an optional status bar, local overrides, and its event loop.
3. `MenuDisplay` is the mutable visible state of one menu: name, title,
   minimum width, descriptive text, and footer message.

Every menu belongs to exactly one application. A submenu and its parent must
belong to the same `TerminalApp`. While the application is running, the
navigation stack determines the automatic final row: the bottom menu displays
`Quit`, and every deeper menu displays `Back`. Registering another main menu
restores `Back` on the previous one until stack depth determines its runtime
label.

Command callbacks receive a frozen `CommandContext` containing the active
application, menu, command handle, and triggering binding:

```python
from tuiloom import CommandContext


def inspect_invocation(context: CommandContext) -> None:
    context.menu.show_alert(
        f"Command: {context.command!r}\nBinding: {context.binding!r}"
    )
```

Commands, choices, input submission, alert confirmation, and captured-task
completion run on the UI thread during normal application execution. Keep these
callbacks short; use `start_output_task()` for blocking application work.
`ScreenContent.dynamic()` and `responsive()` producers run in content workers,
while `StatusBar` producers run on the UI thread. Content producers should return
text rather than mutate menus, and synchronize access to any shared application
state.

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
`menu -> panel 1 -> panel 2 -> ... -> menu`, visiting custom layouts in
row-major order. Focused boxes use solid borders; unfocused boxes use dotted
borders. Moving upward in a panel with
`auto_scroll="smart"` suspends its automatic following, and reaching the bottom
enables it again.

All controls can be remapped through `KeyMap`; see
[Key bindings and global commands](#key-bindings-and-global-commands).

Navigation is owned by `TerminalApp`. Its centralized application loop drives
the runtimes of all opened menus without recursive `run()` calls. Start the
application with `app.run()` after registering a main menu, or pass an
application-owned entry menu to `app.run(entry_menu)`. In callbacks, transition
with the stack methods:

```python
def open_settings(context: CommandContext) -> None:
    context.app.push_menu(settings)


def open_dashboard(context: CommandContext) -> None:
    context.app.replace_menu(dashboard)


def return_home(context: CommandContext) -> None:
    context.app.reset_to(menu)
```

`push_menu()` adds a menu above the current one, `pop_menu()` returns to the
previous menu (or requests shutdown at the bottom), and `replace_menu()` swaps
only the current top menu. `reset_to()` truncates the stack after the requested
menu when it is already present; otherwise it replaces the entire stack with
that menu. Navigation targets must belong to the application, and a menu cannot
be pushed if it is already on the stack. Stack depth supplies `Quit` for the
bottom menu and `Back` above it unless `set_exit_label()` has assigned that menu
an explicit label; an explicit label always takes priority.

Menus that have not been opened remain lazy: pushing or otherwise scheduling a
menu does not initialize it until the application loop reaches it. Its runtime
and content workers are then initialized once per application run. Popping or
replacing the menu removes it from the visible stack but retains and services
that runtime in the background, including source processing and captured-task
completion callbacks. `push_menu()`, `replace_menu()`, and `reset_to()` reset the
target's focus, command selection, option preview, and input buffer, then invoke
its initial command-level `on_hover`, if configured. An existing input prompt and
callback remain installed; only its buffer is cleared. The first `on_hover` runs
before lazy runtime initialization, so it cannot start an output task in that
menu yet. `pop_menu()` reveals the retained state of the previous menu without
this reset. Reopening a retained runtime does not restart its workers.
On graceful exit, `TerminalApp.run()` closes every
initialized menu runtime and joins its workers, including menus no longer on the
stack.

## Screen state and visibility

`MenuDisplay` fields are live and mutable. Tuiloom observes changes while the
menu runs:

```python
menu.display_state.title = "New title"
menu.display_state.text = "Updated instructions"
menu.display_state.message = "Saved"
menu.display_state.width = 32
```

`width` is the minimum inner width. It must be a positive integer or `None`;
booleans are rejected. The menu grows to fit its text up to the terminal's inner
width. Text that still exceeds the available space wraps onto additional lines,
preferring word boundaries and splitting long words when necessary. Explicit
line breaks are preserved. Headings remain centered, and command continuations
align under their label with the selection marker on the first line only.

Set `strict_width=True` to keep the menu at exactly the specified inner `width`:

```python
menu.display_state.width = 32
menu.display_state.strict_width = True
```

`strict_width` defaults to `False` and has no effect when `width=None` (automatic
sizing). Both fields can be changed while the menu runs. Wrapping affects only
display; the original text and input buffer are retained. Content panels keep
using the available terminal width and their existing scrolling behavior.

The two border columns are additional: `width=32` needs at least 34 terminal
columns. Tuiloom still displays `Terminal window is too small.` when that minimum
cannot fit, or when the frame has insufficient height after wrapping. Automatic
sizing keeps a minimum inner width of four columns; an explicit strict width
may be smaller.

By default, a content box and menu box have one blank row between them. Pass
`content_spacing=False` to remove it.

Use `menu.hide_menu()` to hide the menu box while keeping content panels,
the status bar, and their runtime active. `show_menu()` reveals the box and
`toggle_menu()` switches its visibility. The former whole-frame `show` property
and constructor argument have been removed in v0.9.0.

## Overlay menus

Display the same `TerminalMenu` above a graph, dashboard, or logs:

```python
menu = TerminalMenu(
    app,
    MenuDisplay("dashboard", "Main Menu", width=24),
    presentation="overlay",
)
menu.add_content_panel(ScreenContent.static("Graph / dashboard"), description="Graph")
menu.add_content_panel(ScreenContent.static("Turn 15: done"), description="Simulation")
menu.set_status_bar("DONE │ Turn 15 │ 25/25 delivered")
menu.add_command("Resume dashboard", lambda context: context.menu.hide_menu())

# The application chooses its own shortcut; Tuiloom registers none.
app.add_global_command(
    KeyBinding("m"), "Toggle menu", lambda context: context.menu.toggle_menu()
)
```

`inline` retains the historical vertical layout. `overlay` centers the box
in the entire terminal body above the status bar. It can cover multiple panels
and their borders; it does not attach to one panel. The status row stays at the
bottom and is never covered. Weighted sizing, minimum/maximum heights and
collapsed heights still allocate panels as if the menu occupied zero rows.
`content_spacing` adds no rows in overlay mode. Opening/closing an overlay does
not change dimensions passed to responsive content producers.

An overlay uses the existing automatic width, `width`, `strict_width`, wrapping,
commands, choices, messages, alerts and input. If it cannot fit, the frame shows
`Terminal window is too small.`; a configured status bar returns when the
terminal becomes large enough.
The current background continues updating behind the menu and is restored when
it closes. Resizing recomputes both panel layout and centered menu placement.
On terminals supporting focus reports, returning to a terminal tab also repaints
the complete frame, including its bottom rows, even at an unchanged size. Focus
notifications do not invoke commands or modify pending input, even when a report
arrives in separate fragments. The terminal's previous focus-reporting mode is
restored when the application closes.
Focus reporting uses the terminal's mode save/restore controls without a capability
query, so no late query response can become input. It also works with `NO_COLOR`.
Terminals without focus reporting keep ordinary rendering, resizing and segment
diffs. See the [terminal protocol](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Focus-Tracking).

### Menu visibility

| API | Effect |
| --- | --- |
| `menu.hide_menu()` | Hide only the menu box; panels and status remain visible |
| `menu.show_menu()` | Reveal a hidden box and focus it |
| `menu.toggle_menu()` | Switch the box visibility |
| `menu.menu_visible` | Read the requested box visibility, initially `True` |

Box visibility works in both modes. Hiding an inline box also releases its
height and spacing. These operations preserve sources, workers, the navigation
stack, selection, alerts and input state. Showing/hiding an already
shown/hidden box is a no-op. The frame stays visible throughout.

Hiding keeps an already focused panel, or focuses the first available panel.
Tab cycles only through panels while the box is hidden; local menu commands,
alerts and input do not consume keys. Global commands remain available, including
an application-defined toggle shortcut. With no panels, there is no local focus
target; global commands and Back/Escape still work. When visible, input and
alerts keep their existing modal priority. A root quit confirmation temporarily
reveals the menu box while retaining `menu_visible=False`; cancelling restores
the hidden dashboard and prior panel focus.

### Submenu presentation inheritance

Omitting `presentation` (or passing `None`) means inherit when opened:

```python
settings = TerminalMenu(app, MenuDisplay("settings", "Settings"))
menu.add_submenu(settings, "Settings")  # Inherits overlay from menu on push.

full_page = TerminalMenu(
    app, MenuDisplay("details", "Details"), presentation="inline"
)  # Explicit modes always override inheritance.
```

`push_menu()` inherits from the current top menu. `replace_menu()` inherits
from the menu being replaced. Inheritance is resolved again on every opening,
so the same unconfigured submenu can appear inline or overlay from different
parents. `pop_menu()` restores the parent's presentation. `reset_to()` an
existing stack entry preserves its mode; a new root defaults to inline.
Read `menu.presentation` for the effective mode. Box visibility is local to
each menu and does not inherit. Navigation retains each menu's own panels and
status configuration, just as in v0.8.

Run the complete graph/dashboard example from a checkout:

```bash
uv run python examples/overlay_dashboard.py
```

It starts with the menu hidden. Press M to open it, start a simulation, or open
Settings to see presentation inheritance. The graph, logs and status keep
updating while the menu is open or hidden.

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
menu.set_command_callback(command, disconnect)
menu.move_command(command, 0)
menu.disable_command(command)
menu.enable_command(command)
menu.set_exit_label("Close")
```

Positions are zero-based. `position=None` appends a command; an explicit valid
position inserts it there. Booleans, negative positions, and out-of-range
positions are rejected before mutation. `menu.commands` is an immutable tuple
view, and a handle from another menu is rejected.

The handle exposes read-only `label`, `callback`, `position`, and `enabled`
properties. Their current values reflect mutations performed through the menu.
`on_hover` means keyboard selection: it runs when selection reaches the command,
including the initial selection when opening a menu. It does not require a mouse.
Its initial invocation has `context.binding is None`.

### Horizontal and vertical choices

Use `add_choice()` when a command should reveal several options on hover. The
callback receives a `ChoiceContext` with `app`, `menu`, `command`, `option`,
`index`, and the triggering `binding`. Hover callbacks receive the same context
for options; the command label's `on_hover` receives a `CommandContext`.

```python
from tuiloom import ChoiceContext, ChoiceOption


def preview_accurate(context: ChoiceContext) -> None:
    context.menu.display_state.message = "Preview: accurate simulation"


def apply_mode(context: ChoiceContext) -> None:
    context.menu.display_state.message = f"Mode: {context.option.label}"


app.add_message("fast_help", "Run the simulation to completion.")
mode = menu.add_choice(
    "Simulation mode",
    [
        ChoiceOption("Fast", hover_message="fast_help"),
        ChoiceOption("Accurate", on_hover=preview_accurate),
        ChoiceOption("Custom", row=1),
    ],
    on_select=apply_mode,
    rows=2,
    selected_index=0,
)
menu.set_choice_index(mode, 1)  # Update without calling on_select.
menu.set_choice_callback(mode, apply_mode)
```

Pass `vertical=True` to display the options in their original order, one per
logical row:

```python
menu.add_choice(
    "Simulation mode",
    [ChoiceOption("Fast"), ChoiceOption("Accurate"), ChoiceOption("Custom")],
    on_select=apply_mode,
    vertical=True,
)
```

Vertical choices use the width of the widest option. Their `rows` property is
the number of options. `vertical=True` cannot be combined with `rows>1` or an
option whose `row` is nonzero. A long option can wrap across physical terminal
lines while remaining one logical navigation row. Left and Right retain their
usual option order; Up and Down move between the vertical rows.

`ChoiceOption(label, *, row=0, on_hover=None, hover_message=None)` uses zero-based
declared rows. `hover_message` names a registered application message shown only
while the cursor is on that option. It overlays the persistent footer without
changing `MenuDisplay.message` or `active_message_key`; the previous footer
reappears when the cursor leaves. Unknown message keys raise `KeyError` when
the choice is added. `on_hover` remains available for other actions.
Empty declared rows are skipped. A narrow terminal wraps between options, and
arrow navigation follows those visible lines. Right from the label enters the
options; Down moves to the next command. Enter from the label moves to the
active option. With no `selected_index`, the first Enter previews the first
option without checking it; a second Enter confirms it. Moving the cursor
previews an option without changing `mode.selected_index` or
`mode.selected_option`. Before confirmation, these properties and
`mode.selected_label` are `None`. Once confirmed, `selected_label` returns the
option's static label (the fallback for `AnimatedText`). Enter on an option
confirms it and calls `on_select`, including when it is already selected. The
`>` marker follows the cursor; `✓` remains after the confirmed option's label
until another option is chosen. Option lines start two cells to the right of
command markers when the width permits. Use the owning menu's command mutation
methods to rename, move, disable, or remove a choice. Replace its selection
callback with `set_choice_callback()`, which accepts `ChoiceCallback`.
`set_command_callback()` accepts only regular commands.

`mode.on_select` exposes the original `ChoiceCallback`. The inherited
`mode.callback` is a real `CommandCallback` adapter: it creates a `ChoiceContext`
for the currently validated option, preserving the triggering binding. Calling
that adapter invokes `on_select` without opening the chooser or changing its
selected index. Calling it before confirmation raises `RuntimeError`. An
option's label is display text; use its index or your own
mapping for application values.

Every time a menu opens, its marker starts on the first enabled command from
the top. Disabled commands are skipped during initialization and navigation; if
all commands are disabled, the marker starts on the automatic `Back` or `Quit`
row.

### Submenus

```python
settings = TerminalMenu(
    app,
    MenuDisplay("settings", "Settings", text="Configure the application"),
)
open_settings = menu.add_submenu(settings, "Settings", position=0)
```

Activating the returned command pushes the submenu onto the application's
navigation stack. `add_submenu()` is the normal convenience helper for a submenu:
it creates a command whose callback calls `context.app.push_menu(settings)`; it
does not start a recursive menu loop. It rejects a submenu owned by a different
application. Use an explicit command callback with `push_menu()`,
`replace_menu()`, or `reset_to()` when a different transition is needed.
Application execution starts through `TerminalApp.run()`; menu navigation uses
these stack methods.

## Screen content

`ScreenContent` uses explicit factories for each production strategy:

```python
from collections.abc import Iterator
from tuiloom import ScreenContent


def stream() -> Iterator[str]:
    yield "one\n"
    yield "two\n"


def current_state() -> str | list[str]:
    return ["current", "state"]


panel = menu.add_content_panel(ScreenContent.static("one\ntwo"))
panel.set_content(ScreenContent.lines(["one", "two"]))
panel.set_content(ScreenContent.stream(stream()))
panel.set_description("Loading records")
panel.set_content(ScreenContent.dynamic(current_state))
panel.set_description("Refreshing state")
```

The factories behave differently:

| Factory | Behavior |
| --- | --- |
| `static(str)` | Fixed text split into display lines |
| `lines(list[str])` | An immutable copy of fixed display lines |
| `stream(Iterator[str])` | A worker consumes chunks until exhaustion |
| `dynamic(Callable[[], str \| list[str]])` | A worker evaluates the latest state up to 60 Hz |
| `responsive(Callable[[ContentSize], str \| list[str]])` | A worker renders for the panel's effective size |
| `animated(Callable[[ContentSize, AnimationFrame], str \| list[str]], fps=12)` | A worker renders due frames for the effective size |

Static content is normalized immediately. Iterator chunks may contain partial
lines and multiple newlines; carriage returns replace the unfinished line, which
supports progress-style output. Iterators must yield only strings. Dynamic
callables must return `str` or `list[str]` and have at most one evaluation in
flight.

Responsive content can declare `min_width` and `min_height`. Below either
minimum, the physical viewport remains the size of the terminal while the
renderer receives the larger virtual `ContentSize`; the result stays clipped
and scrollable. `refresh_mode="resize"` renders on first display, effective
size changes, and `panel.refresh()`. `refresh_mode="continuous"` additionally
renders up to 60 Hz.

Unsafe terminal controls are removed from rendered content. Unicode graphemes,
cell widths, safe SGR styling, tabs, and line boundaries are normalized for the
terminal.

### Multiple content panels

`add_content_panel()` creates an independently managed content box and returns
a stable `ContentPanel` handle:

```python
logs = menu.add_content_panel(
    ScreenContent.stream(log_stream),
    description="Downloading",
    auto_scroll="strict",
)
metrics = menu.add_content_panel(
    ScreenContent.dynamic(get_metrics),
    description="Indexing",
)

logs.set_content(ScreenContent.stream(new_log_stream))
logs.set_description("Downloading model")
logs.set_auto_scroll("smart")
metrics.swap_up()
metrics.remove()
```

Panel padding sits inside the border and reduces the viewport passed to
responsive or animated content. Configure each side when adding a panel, then
change selected sides with `panel.update_padding(top=..., bottom=...,
left=..., right=...)`. All sides default to zero.

`menu.content_panels` exposes the handles in flat registration order as an
immutable tuple. Visible panels are stacked vertically at equal height by
default and labeled when more than one is present. Each panel owns its source
worker, viewport, scroll position, and auto-scroll mode. Panels can be added,
placed, replaced, or removed while the menu is running.

Every panel has the same capabilities; there is no primary panel. A menu with
one panel shows an unlabeled content box. Create panels with
`menu.add_content_panel()` and keep their handles to change content, labels,
auto-scroll, or layout.

### Content layouts

The outer list is **rows from top to bottom**. Each inner list is **panels from
left to right** in that row:

```python
graph = menu.add_content_panel(
    ScreenContent.static("graph"), description="Graph", width_weight=2
)
stats = menu.add_content_panel(ScreenContent.static("stats"), description="Stats")
logs = menu.add_content_panel(ScreenContent.static("logs"), description="Logs")

menu.set_content_layout([
    [graph, stats],
    [logs],
])
```

```text
╭─ Graph ───────────────────╮╭─ Stats ─────╮
│                           ││             │
╰───────────────────────────╯╰─────────────╯
╭─ Logs ───────────────────────────────────╮
│                                         │
╰─────────────────────────────────────────╯
```

`content_panels` still lists which panels belong to the menu. The read-only
`content_layout` exposes their placement as `ContentRow` handles with a
read-only `panels` tuple. Without `set_content_layout()`, each panel occupies
its own row in `content_panels` order, exactly as before. Every explicit layout
must contain all live panels exactly once. Empty rows, duplicate, foreign,
removed, or missing panels are rejected without changing the old layout.
Adding a panel, including captured task output, appends a new singleton row;
removing a panel removes it from its row and removes an empty row.

Panels in the same row share its physical height. Their `width_weight` values
divide the complete row width, including borders. The example above gives
Graph about twice Stats' width. The default `width_weight=1` keeps equal-width
columns; leftover columns go to the first panel on a rounding tie. For a 3:1
split, configure `graph` with `width_weight=3` and `stats` with
`width_weight=1`. Borders touch with
no wasted horizontal gap; `content_spacing` still controls only the gap above
an inline menu. Each panel's responsive content receives its own column width
and row height, subject to its existing virtual `ScreenContent` minimums.
The status bar reserves its usual bottom row; an overlay menu is composed over
the content without changing row or column sizes.
Resizing and changing layouts reuse panels, workers, content, viewports, scroll
offsets, auto-scroll state, and focus. The focus key visits menu, then panels
in row-major order; arrow keys still scroll the focused panel.
If the focused panel is removed, focus goes to the next panel in its former
row-major order. With no next panel, it returns to the visible menu or to the
first remaining panel when the menu is hidden.

Rows own vertical collapse in a multi-column layout:

```python
menu.content_layout[0].collapse()
menu.content_layout[0].set_collapsed_height(2)
menu.content_layout[0].expand()
```

Members of one multi-panel row must agree on `collapsed` and
`collapsed_height`. Use its `ContentRow` handle for collapse changes; the v0.7
panel methods continue to work on singleton rows. A row's expanded
`height_weight` is the mean of its panels' `height_weight` values;
`min_height` is their largest minimum and
`max_height` their smallest configured maximum. Incompatible bounds are
rejected before changing the layout.

Directional mutations can change placement while the menu runs:

```python
graph.move_right()  # Exchange with the next panel in this row.
graph.move_down()   # Insert in the next row at its column, or at its end.
graph.swap_up()     # Exchange with the panel directly above, if present.
```

`move_left()` and `move_right()` permute adjacent panels within a row.
`move_up()` and `move_down()` remove the panel from its row and insert it into
the adjacent row, shifting later panels right and deleting an emptied row.
`swap_up()` and `swap_down()` exchange panels at the same column in adjacent
rows. A movement without a target is a no-op. These methods change the layout,
while `content_panels` and `panel.position` keep their flat registration order.
The v0.9 `panel.move(position)` method has been removed; use directional moves
or `set_content_layout()`.

### Content panel sizing

Each panel can set its share of horizontal and vertical space:

```python
logs = menu.add_content_panel(
    ScreenContent.stream(log_stream),
    description="Logs",
    height_weight=3,
    width_weight=2,
    min_height=4,
    max_height=30,
)
metrics = menu.add_content_panel(
    ScreenContent.dynamic(get_metrics),
    description="Metrics",
    height_weight=1,
    min_height=4,
)

# Configure another panel through its handle.
status = menu.add_content_panel(ScreenContent.static("Ready"))
status.set_layout(height_weight=2, width_weight=3, min_height=3, max_height=10)

# Replace the complete layout; omitted options use their defaults.
logs.set_layout(height_weight=4, min_height=2, max_height=20)

# Change only supplied options, retaining the others.
logs.update_layout(height_weight=3)  # Keep min_height=2 and max_height=20.
logs.update_layout(max_height=None)  # Remove only the upper bound.
logs.set_layout()  # Restore equal sharing without an upper limit.
```

`height_weight` and `width_weight` each default to `1` and accept finite
positive integers or floats. `height_weight` controls row height;
`width_weight` controls a panel's width relative to its neighbors in the same
row. A singleton panel always receives the complete available width.
The old `weight` name has been removed: replace it with `height_weight` in
existing applications.
`min_height` defaults to `1`; `max_height` defaults to `None` (no upper limit).
Minimum and maximum heights count visible content rows, excluding borders.
Supplied heights must be positive integers, and `max_height` must be at least
`min_height`. Booleans are rejected for both weights and both height bounds.
Invalid creation or
layout updates raise `TypeError` or `ValueError` before changing panel state.
`set_layout()` replaces the full expanded configuration and resets omitted
options to their defaults. `update_layout()` retains omitted options and uses
`max_height=None` to remove an existing upper bound.

Height weights target ratios on the **total** available panel height, including each
panel's two border rows and excluding the content/menu gap. For 23 rows,
weights `3` and `1` produce complete frames of `17` and `6` rows, containing
`15` and `4` visible content rows respectively. Bounds still apply to the inner
content: with 20 available frame rows, weights `1` and `3` and minimums of `4`
produce frames of `6` and `14` rows (content heights of `4` and `12`).
A panel that reaches a minimum or maximum keeps that
bound while the other panels share the remaining rows by height weight. Fractional
rows are rounded down, then leftover rows go to the largest fractional
remainders, with ties resolved in row order. Defaults preserve the original
equal sharing, including giving leftover rows to the first panels.

With [Content layouts](#content-layouts), the allocator sizes rows rather than
individual panels. Each row uses its members' mean height_weight, greatest minimum,
and smallest configured maximum. Incompatible bounds are rejected.

Width weights target ratios on each row's **complete frame width**, including
each panel's two border columns. At 80 terminal columns, `width_weight=3` and
`width_weight=1` give frames 60 and 20 columns wide, with inner viewport widths
58 and 18. Every frame needs at least three columns; if the row cannot fit,
Tuiloom displays `Terminal window is too small.` Width changes recompute each
responsive panel's `ContentSize` without replacing its worker.

If the minimum heights cannot all fit, Tuiloom displays
`Terminal window is too small.` If every panel reaches its maximum, unused
terminal rows remain below the frame. Layout changes preserve panel identity,
workers, focus, scroll positions and auto-scroll policy; viewport growth can
clamp an existing scroll offset to the new bottom. Replacing content or moving
a panel keeps its layout configuration.

Panel bounds size the physical viewport. The `min_height` on
`ScreenContent.responsive()` still specifies a **virtual** rendering minimum:
the callback receives the larger of the allocated height and that virtual
minimum, and its result remains clipped and scrollable. A layout change
refreshes responsive content when its effective `ContentSize` changes.

### Collapsible content panels

Panels start expanded. Collapse a panel to a fixed, smaller viewport while
keeping its content and runtime mounted:

```python
logs = menu.add_content_panel(
    ScreenContent.stream(log_stream),
    description="Logs",
    height_weight=3,
    min_height=4,
    max_height=30,
    collapsed_height=2,
)
logs.collapse()
assert logs.collapsed
logs.set_collapsed_height(1)
logs.expand()
logs.toggle_collapse()
```

`collapsed_height` defaults to `1` and counts visible content rows, excluding
the two border rows. It must be a positive integer; booleans are rejected.
Invalid creation or height updates raise `TypeError` or `ValueError` before
changing panel state. `collapse()` and `expand()` are idempotent;
`toggle_collapse()` switches the state. All mutation methods return `None`.

A collapsed panel reserves exactly `collapsed_height` content rows, independently
of its expanded `height_weight`, `min_height`, and `max_height`. Expanded panels share
the remaining frame rows using the usual weighted sizing. If the required
heights cannot fit, the existing terminal-too-small message is displayed. If
all panels are collapsed, unused terminal rows remain below the frame.

`expand()` recalculates the viewport from the current terminal size and expanded
sizing options. `set_layout()` changes only those expanded options, even while
collapsed; it never changes the collapse state or `collapsed_height`.

Collapsed panels remain visible, focusable, and scrollable. Collapsing or
expanding preserves the panel, renderer, viewport, worker, content buffer, and
auto-scroll policy. Streams and dynamic sources continue producing content.
Scroll offsets follow the existing viewport rules and may be clamped when the
viewport grows. Responsive content refreshes when its effective `ContentSize`
changes, still respecting its virtual rendering minimums and using the same
worker. No collapse shortcut is installed automatically; applications can bind
`toggle_collapse()` through their existing commands.
For a row with multiple panels, use its `ContentRow` handle to change the
shared collapse state or height; panel collapse methods remain for singleton
rows.

### Inherited and local content

```python
app = TerminalApp(
    "Monitor",
    global_content=ScreenContent.static("Shared status"),
)
menu = TerminalMenu(app, MenuDisplay("logs", "Logs"))
shared = menu.content_panels[0]  # Automatically added from global_content.
logs = menu.add_content_panel(ScreenContent.static("Local status"))

shared.set_description("Shared status")
shared.set_layout(height_weight=1, min_height=2)
shared.set_content(ScreenContent.static("Updated status"))
# shared.remove()  # Remove it like any other panel.
```

Each menu captures `app.global_content` at construction. When it is present,
Tuiloom automatically adds an ordinary panel for that source. Retrieve its
handle through `menu.content_panels`; it can be changed, placed, or removed
like any other panel. Explicitly added local panels are additional panels and
do not override inherited content.

For per-menu sources, pass `global_content_factory` instead. It is called once
per menu construction, on the thread constructing that menu, and must return a
`ScreenContent`. The two constructor options are mutually exclusive. A stream
has one consumer: the factory must create a fresh iterator for each menu.

```python
from collections.abc import Iterator

from tuiloom import MenuDisplay, ScreenContent, TerminalApp, TerminalMenu


def log_chunks() -> Iterator[str]:
    yield "Starting\n"
    yield "Ready\n"


def make_log_content() -> ScreenContent:
    return ScreenContent.stream(log_chunks())


app = TerminalApp("Monitor", global_content_factory=make_log_content)
main = TerminalMenu(app, MenuDisplay("main", "Monitor"))
details = TerminalMenu(app, MenuDisplay("details", "Details"))
main.add_submenu(details, "Details")
app.set_main_menu(main)
app.run()
```

The application rejects mounting the same iterator in two panels at once,
including panels in different menus of that application. The claim remains
while an old worker is retiring after removal or replacement, then ends once
that worker has stopped. Releasing ownership does not rewind an iterator or
make an exhausted stream reusable.

When both global content options are `None`, a new menu has no panels until one
is added.
A menu without panels omits the content box without displaying an automatic
message. Applications can still show `MessageKey.NO_CONTENT_SOURCE` explicitly
with `show_message()`.

### Replacing active content

`panel.set_content(content)` replaces that panel's source and returns `None`.
Use `panel.set_description(description)` to change its label separately. If the
menu is running, Tuiloom installs the source through the active event loop.

Replacing an iterator or an in-flight dynamic evaluation requests cooperative
cancellation of the old source. The UI remains responsive, waits for the old
worker to stop, and then installs only the latest requested replacement. If
several replacements arrive during cleanup, the last request wins.
`panel.content` continues to report the old mounted configuration until the new
one is installed. Results and
errors from an explicitly cancelled source are discarded; ordinary source
errors still propagate after resources are cleaned up.

For cooperative iterator cancellation, Tuiloom calls an optional `cancel()`
method as soon as cancellation is requested and an optional `close()` method
when the consumer exits. A blocking iterator should implement `cancel()` so it
can wake or release its own `__next__()` call. A dynamic callable cannot be
interrupted in the middle of an evaluation; that call must return before its
worker can stop.

### Auto-scroll

Set each panel's `auto_scroll` when adding it or through its handle later:

```python
menu = TerminalMenu(app, MenuDisplay("logs", "Logs"))
logs = menu.add_content_panel(
    ScreenContent.stream(stream()),
    auto_scroll="smart",
)

logs.set_auto_scroll("strict")
logs.set_auto_scroll(None)
logs.set_auto_scroll("smart")
```

- `"smart"` follows new iterator content until the user scrolls upward, then
  resumes when the viewport reaches the bottom.
- `"strict"` always follows the newest iterator content.
- `None` disables automatic following.

Changing a panel's mode or replacing its content resets its smart-scroll state.
Invalid modes raise `ValueError`.

### Strict API migration

This version uses the names below directly. Removed names have no aliases or
deprecated wrappers; update imports, keyword arguments, and attribute access
together. `stop()` and `on_hover` keep their existing names.

| Removed API | Current API |
| --- | --- |
| `ScreenContext`, `menu.screen_context` | `MenuDisplay`, `menu.display_state` |
| `CommandBehavior`, `InputBehavior`, `ChoiceBehavior` | `CommandCallback`, `InputCallback`, `ChoiceCallback` |
| Command `behavior` parameter/property | `callback` parameter/property |
| `set_command_behavior()` | `set_command_callback()` for regular commands; `set_choice_callback()` for choices |
| `set_global_command_behavior()`, `clear_global_command_behavior()` | `set_global_command_callback()`, `clear_global_command_callback()` |
| `set_choice_value()` | `set_choice_index()` |
| `choice.value` | `choice.selected_label`; use `selected_option` for the option object |
| `add_menu()` | `add_submenu()` |
| `delete_command()` | `remove_command()` |
| `run_with_output()` | `start_output_task()` |
| `style(color=..., highlight=...)` | `style(foreground=..., background=...)` |
| `TerminalMenu.run()` | `TerminalApp.run()` for execution; `push_menu()` for navigation |
| `MessageKey.TASK_EXIT_CHOICES`, `TASK_WAITING`, `TASK_STOPPING` | Removed; shutdown uses its own temporary menu state |

The panel-only API is a breaking change: `TerminalMenu` no longer accepts
`content` or `auto_scroll`, and `menu.set_content()` and `menu.auto_scroll` have
been removed. Create a panel with `menu.add_content_panel(content, ...)`, keep
its handle, and use `panel.set_content()`, `panel.set_description()`,
`panel.set_auto_scroll()`, and `panel.update_layout()` for partial updates. Use
`panel.set_layout()` to replace the full expanded layout and reset omitted
options. The menu's
`content_spacing` constructor option is keyword-only.
`TerminalApp.global_content` remains supported; access its automatically added
panel through `menu.content_panels`.

In v0.10.0, `ContentPanel.move(position)` is removed. Use
`menu.set_content_layout()` for an exact arrangement, `move_left/right/up/down()`
for insertion or one-column movement, and `swap_up/down()` for vertical exchange.
`content_panels` and `panel.position` now describe flat registration order;
`content_layout` describes visual placement.

## Status bar

A menu can display one persistent status line at the bottom of the terminal,
separate from its content panels and menu box:

```python
from tuiloom import StatusBar

menu.set_status_bar("READY │ [L] Logs │ [Q] Quit")
menu.set_status_bar(StatusBar.dynamic(lambda: f"RUNNING │ Turn {turn}/80"))


def render_status(width: int) -> str:
    if width < 65:
        return f"RUNNING │ {turn}/80 │ {delivered}/10 │ [L] Logs"
    return (
        f"RUNNING │ Turn {turn}/80 │ {delivered}/10 delivered"
        " │ [Space] Pause │ [L] Logs │ [Q] Quit"
    )


menu.set_status_bar(StatusBar.responsive(render_status))
menu.refresh_status_bar()  # state changed without a width or focus change
menu.clear_status_bar()
```

The application owns `turn` and `delivered` in this example. Shortcut labels are
text only; register their behaviors separately as commands or global commands.
Tuiloom does not choose shorter labels or introduce application-specific logic.

| Factory | Evaluation |
| --- | --- |
| `StatusBar.static(str)` | Fixed text; a plain string passed to `set_status_bar()` is equivalent |
| `StatusBar.dynamic(Callable[[], str])` | On scheduled visible UI frames, up to 60 Hz |
| `StatusBar.responsive(Callable[[int], str])` | On first display, replacement, terminal width or panel focus changes, or `menu.refresh_status_bar()` |
| `StatusBar.animated(Callable[[int, AnimationFrame], str], fps=12)` | On its own active-time frame boundaries, up to 60 Hz |

Status producers are lightweight renderers running synchronously in the UI
loop. They must read current state and return a string quickly, without I/O,
blocking calls, or expensive computation. Perform slow work in an application
task or worker, then update state for the renderer to read. No status worker is
created. Callback exceptions propagate through the normal terminal-restoration
path. Producers are not evaluated while the menu is covered by a submenu;
hiding the menu box keeps its status bar visible. Responsive output is cached;
use `refresh_status_bar()` when application
state changes at the same width and focus. Height changes alone do not reevaluate
it. The callback can read `menu.focused_panel`, which is `None` when the menu
box, input, or an alert has control.

The status line reserves exactly one physical row before panel and menu layout.
It stays on the final terminal row even with no panels, capped panels, or all
panels collapsed; any unused rows above it are blank. It has no focus, scrolling,
borders, or virtual minimum size. The responsive width is the full available
terminal width in cells. An empty string still reserves the row.

Text is sanitized and clipped with the existing Unicode/ANSI utilities, without
wrapping or splitting graphemes. Tabs are expanded and newline/carriage-return
controls are removed by single-line normalization. Strings longer than the
terminal width are clipped; responsive callbacks can select their own shorter
representation. When the body cannot fit with the reserved status row, only a
clipped terminal-too-small message appears. The status remains installed and
returns when the terminal grows.
A terminal reporting zero rows or columns receives an empty frame.

Each menu owns its own status configuration, retained when returning from a
submenu. Changes take effect without recreating the menu. `MenuDisplay.message`
continues to render independently inside the menu box. `menu.hide_menu()`
keeps the status line visible and its producer running. Without a status bar, frame
composition and sizing remain unchanged from v0.7.

## Captured task output

`start_output_task()` runs blocking Python work on a non-daemon worker and uses
its captured stdout/stderr in a temporary content panel:

```python
def download() -> str:
    print("Downloading…")
    return "archive.zip"


def start_download(context: CommandContext) -> None:
    context.menu.start_output_task(
        download,
        on_success=lambda path: context.menu.show_alert(f"Saved {path}"),
        on_error=lambda error: context.menu.show_alert(str(error)),
        description="Downloading archive",
    )


menu.add_command("Download", start_download)
```

The call itself starts the work and returns immediately. Its menu runtime must
already be initialized and running; another menu may currently be visible.
Only one captured task may run in the application at a time. A second task
raises `RuntimeError`.

During the task, output appears in a temporary panel with strict auto-scroll;
the menu's other panels remain visible and unchanged. On normal completion,
Tuiloom processes the outcome, releases the active task registration, requests
removal of the temporary panel, and runs `on_success(result)` or
`on_error(exception)` on the UI thread. Buffered output may still be draining
at that point; the panel disappears after consumption finishes. The callback
does not wait for the panel to disappear.

Capture includes `print()` and Python writes to `sys.stdout` and `sys.stderr`
from non-UI threads while the task is running, including independent workers.
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

Iterator sources count as active work until they finish. Dynamic and responsive
sources count as active while an evaluation is in progress, including an old
evaluation retiring during replacement. Static content does not block
exit. Every active operation is displayed in its own labeled panel. The list is
live in every mode: completed panels disappear immediately, singular/plural
titles update, and newly started operations are included. The application exits
automatically when no blocking operation remains, even before a choice is made.

While waiting to quit, Tuiloom stops scheduling new dynamic/responsive
evaluations; it lets the currently running work and stream consumers finish.
Cancel restores ordinary scheduling. Graceful shutdown requests cooperative
cancellation and waits without a timeout before restoring the terminal.
**Force quit** is the escape
hatch for native or application code that does not return: it restores terminal
modes and then terminates the whole process without waiting for workers.

When a callback, source, or renderer raises, Tuiloom attempts all worker and
terminal cleanup before propagating the error. If cleanup also fails, the
original error and cleanup failures are retained in an `ExceptionGroup` (or
`BaseExceptionGroup` when required). Iterator `cancel()`/`close()` hooks should
release blocking work reliably: a worker that never returns can prevent graceful
shutdown from finishing.

## Free-form and hidden input

```python
def submit_password(value: str) -> None:
    if value:
        menu.leave_input_mode()
        menu.show_alert("Password received")


menu.enter_input_mode("Password: ", submit_password, hidden=True)
```

`enter_input_mode()` clears the previous buffer. Printable input is appended,
Backspace removes a complete Unicode grapheme, Enter calls the `InputCallback`
with the full string, and Escape calls `leave_input_mode()` without submitting.
The callback decides whether input mode stays active after submission.

With `hidden=True`, one `*` is displayed per grapheme, including combining
characters and emoji sequences. The original Unicode text is passed to the
callback. Every global command is disabled while visible free-form input is active.
Hiding only the menu box suspends input without clearing the buffer and restores
panel/global handling; showing it resumes the same input state.

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
    on_confirm=lambda context: status.set_content(ScreenContent.static("Ready")),
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

Messages occupy `MenuDisplay.message`, the menu footer. Register custom
messages on the application, then show or suppress them by key:

```python
from tuiloom import MessageKey

app.add_message("connected", "Connected successfully")
menu.show_message("connected")  # True when displayed
menu.clear_message()

menu.disable_message("connected")  # suppress only in this menu
menu.enable_message("connected")
app.disable_message("connected")  # suppress in every menu
app.enable_message("connected")

menu.show_message(MessageKey.NO_CONTENT_SOURCE)
```

The built-in keys are:

| `MessageKey` | Value | Purpose |
| --- | --- | --- |
| `NO_CONTENT_SOURCE` | `"no_content_source"` | Explain missing content |
| `UNKNOWN_COMMAND` | `"unknown_command"` | Report discarded textual command input |

`show_message()` validates the key and returns `False` without changing the
footer when the message is suppressed. Otherwise it displays the message and
returns `True`. Local and application-wide suppression combine;
`is_message_enabled()` reports the effective state. Unknown keys raise
`KeyError`. Custom keys must be nonempty and unique, including against built-in
keys.

Automatic messages use the same registry and respect suppression.
`UNKNOWN_COMMAND` is disabled by default: unrecognized keys leave the current
footer unchanged. Enable reporting explicitly for the application:

```python
app.enable_message(MessageKey.UNKNOWN_COMMAND)
```

You can then suppress it again per menu or application with `disable_message()`.
`menu.active_message_key` is a read-only property identifying the registered
message currently displayed, or `None` for an empty or directly assigned footer.
Assigning `display_state.message` directly resets that identity, even when the
text is unchanged. Messages with identical text retain distinct keys.

Register a message once during application setup, then toggle it from a callback:

```python
app.add_message("credit", "Created by maroard")


def credit(context: CommandContext) -> None:
    context.menu.toggle_message("credit")
```

`toggle_message(key)` returns `True` when the requested message is displayed,
or `False` when it is hidden or suppressed. An active message is cleared; another
message is replaced only if the requested message is enabled. Unknown keys raise
`KeyError` without changing the footer. Suppression does not retroactively clear
an active message, which can still be hidden by toggling it. Clearing does not
restore a previous message.

## Key bindings and global commands

### Custom system bindings

```python
from tuiloom import KeyBinding, KeyMap, TerminalApp

keymap = KeyMap()
keymap.set_binding("focus", KeyBinding("f", ctrl=True))
app = TerminalApp("App", keymap=keymap)
second_app = TerminalApp("Second app", keymap=keymap.copy())
```

The seven system actions are `focus`, `up`, `down`, `left`, `right`, `activate`,
and `back`. `keymap.bindings` is a read-only live mapping, and the same bindings
are available as `keymap.focus`, `keymap.up`, and so on. `action_for(binding)`
returns the matching `KeyAction` or `None`. These seven properties are explicitly
typed and read-only, so a type checker can report misspelled attribute names.
`KeyAction` is a literal union of the seven action strings.

A `KeyMap` belongs to one application. Passing the same instance to a second
application raises `ValueError`. `copy()` copies its bindings into an independent,
unowned map; later remapping affects only that map and its owner.

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

`priority=True` affects dispatch of a focused panel command competing with a
global command. It does not affect key equality or hashing.

Multi-character names are lowercased. Terminal protocols cannot always report
every modifier distinctly: Ctrl+letter is commonly case-insensitive, and Shift
may arrive only as character case.

### Invisible global commands

```python
status = menu.add_content_panel(ScreenContent.static("Ready"))


def refresh(context: CommandContext) -> None:
    status.set_content(ScreenContent.static("Refreshed"))


refresh_command = app.add_global_command(
    KeyBinding("r", ctrl=True),
    "Refresh",
    refresh,
)

app.set_global_command_binding(refresh_command, KeyBinding("f5"))
app.set_global_command_label(refresh_command, "Reload")
app.set_global_command_callback(refresh_command, refresh)
```

Global commands are invoked immediately when their binding arrives and are not
rendered as menu rows. `app.global_commands` is an immutable tuple of handles;
their read-only metadata can power a custom help screen.

A menu can override or disable an application global command locally:

```python
menu.set_global_command_callback(refresh_command, refresh)
menu.disable_global_command(refresh_command)
menu.enable_global_command(refresh_command)
menu.clear_global_command_callback(refresh_command)
```

Global-command handles belong to one application. Foreign handles are rejected.
Global commands remain available while a menu is hidden or an alert is shown,
but not during visible free-form input or a root task-exit choice.

### Focused panel commands

```python
panel = menu.add_content_panel(ScreenContent.static("Logs"))
command = panel.add_key_command(
    KeyBinding("r", priority=True),
    "Refresh logs",
    lambda context: context.panel.set_content(ScreenContent.static("Updated")),
)
panel.remove_key_command(command)
```

`panel.key_commands` is a read-only tuple of command handles. Callbacks receive
`PanelCommandContext` with `app`, `menu`, `panel`, `command`, and `binding`.
Only the focused panel handles its commands; `menu.focused_panel` exposes that
panel or `None`. Panels may reuse a key. Global commands win a collision unless
the focused panel binding has `priority=True`. Unmodified Tab, Escape, and arrow
keys remain system keys; Shift+Left and Shift+Right may be panel shortcuts.
Input and modal views suspend panel commands.

Input priority is: task-exit choice, hidden-menu-box handling, free-form input,
global commands, alerts, then focus/navigation. Unknown terminal sequences are
consumed and do not block later input.

## Text styling

Use `style()` to combine terminal effects and foreground/background colors in
one safe string:

```python
from tuiloom import style

title = style("Important", bold=True)
warning = style(
    "Check this value",
    bold=True,
    underline=True,
    foreground="red",
    background="yellow",
)
```

The named colors are `black`, `red`, `green`, `yellow`, `blue`, `magenta`,
`cyan`, and `white`, plus their `bright_` variants. These use the terminal's
ANSI palette. The following additional names use fixed RGB values for both
`foreground` (text) and `background`:

| Name | RGB hexadecimal |
| --- | --- |
| `orange` | `#FFA500` |
| `brown` | `#A52A2A` |
| `crimson` | `#DC143C` |
| `darkred` | `#8B0000` |
| `gold` | `#FFD700` |
| `lime` | `#00FF00` |
| `maroon` | `#800000` |
| `purple` | `#800080` |
| `violet` | `#EE82EE` |
| `gray` | `#808080` |
| `dark_red` | `#7F0000` |
| `dark_green` | `#007F00` |
| `dark_yellow` | `#7F7F00` |
| `dark_blue` | `#00007F` |
| `dark_magenta` | `#7F007F` |
| `dark_cyan` | `#007F7F` |
| `dark_orange` | `#7F5200` |
| `dark_gray` | `#404040` |

Dark variants halve RGB components, rounding down, using full-intensity RGB
primaries/secondaries as the reference for red through cyan. They do not derive
their values from the terminal's configurable ANSI palette.

Colors can also use an ANSI index, an RGB tuple, or a hexadecimal string:

```python
indexed = style("Indexed", foreground=202)
named = style("Warning", foreground="orange", background="dark_gray")
rgb = style("RGB", foreground=(120, 40, 210), background=(245, 245, 245))
hexadecimal = style("Hex", foreground="#7A28D2", background="#F5F5F5")
```

The available effects are `bold`, `dim`, `italic`, `underline`,
`strikethrough`, and `reverse`. Input is sanitized before styling: printable
Unicode, safe SGR sequences, newlines, tabs, and HTTP(S) terminal hyperlinks
are retained, while unsafe controls are removed. If no effect or color is
selected, `style()` returns only that sanitized text.

## Animations

Tuiloom animates menus, status bars, and content panels on one monotonic
**active-time** timeline per menu. The timeline pauses when a child menu covers
it and resumes at the same phase. An `AnimationFrame` contains `elapsed` seconds
and an `index` at the source's requested rate. If rendering falls behind, the
next callback receives the current index; missed frames are skipped.

Use `AnimatedText(fallback, renderer, fps=12)` wherever a menu title,
description, footer message, command label, or choice-option label accepts a
string. It is a `str` subclass: code reading a label still gets its static
fallback, while the menu displays `renderer(frame)`. A renderer may return safe
ANSI styling made with `style()`. The same `AnimatedText` instance used in
several menu fields is evaluated once per image. Replace the field or command
label with a plain string to stop its animation.

```python
from tuiloom import AnimatedText, AnimationFrame, rainbow_color, style


def title(frame: AnimationFrame) -> str:
    color = rainbow_color(frame.elapsed, period=2.1)
    return style("Fly-in", bold=True, foreground=color)


menu.display_state.title = AnimatedText("Fly-in", title, fps=15)
```

`StatusBar.animated(renderer, fps=12)` calls `renderer(width, frame)` on the UI
thread. `ScreenContent.animated(renderer, fps=12, min_width=None,
min_height=None)` calls `renderer(size, frame)` on the panel's worker. They return
the same types as their non-animated counterparts: `str` for status, and `str`
or `list[str]` for content. Menu and status callbacks must be fast and
non-blocking. Panel calls are serialized; if one takes too long, pending frames
coalesce to the latest size and time. Replaced and removed sources cannot
publish stale results. `ContentPanel.refresh()` also forces an animated panel
to evaluate its current frame.

The `fps` argument accepts a finite number greater than zero and at most 60.
It is an upper bound, not a guarantee of terminal writes: unchanged output is
cached, and a slow callback or terminal can lower the effective rate. All
animations on a menu share its elapsed time, including sources added later.
Their `index` values can differ because each source has its own `fps`.

`rainbow_color(elapsed, period=2.1)` returns an RGB tuple cycling smoothly
through red, orange, yellow, green, blue, indigo, and violet. Pass that tuple
to `style(foreground=...)` or `style(background=...)`. `"rainbow"` itself is
not a static color name for `style()`; a string cannot animate without a new
rendered frame. See [animated_rainbow.py](examples/animated_rainbow.py) for a
complete three-surface example.

## Terminal hyperlinks

```python
from tuiloom import hyperlink, style

label = hyperlink(
    style("Project", underline=True, foreground="bright_blue"),
    "https://github.com/maroard/Tuiloom",
)
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
    AnimatedText,
    AnimationFrame,
    AutoScrollMode,
    ChoiceCallback,
    ChoiceContext,
    ChoiceOption,
    CommandCallback,
    CommandContext,
    ContentPanel,
    ContentRow,
    ContentRefreshMode,
    ContentSize,
    GlobalCommand,
    InputCallback,
    KeyAction,
    KeyBinding,
    KeyMap,
    MenuChoice,
    MenuCommand,
    MenuDisplay,
    MenuPresentation,
    MessageKey,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
    TextColor,
    display_width,
    hyperlink,
    rainbow_color,
    style,
)
```

Anything outside this export list is internal and may change without notice.

### Type aliases

```python
from collections.abc import Callable
from typing import Literal

from tuiloom import ChoiceContext, CommandContext

type ContentRefreshMode = Literal["resize", "continuous"]
type AutoScrollMode = Literal["smart", "strict"]
type MenuPresentation = Literal["inline", "overlay"]
type CommandCallback = Callable[[CommandContext], None]
type ChoiceCallback = Callable[[ChoiceContext], None]
type InputCallback = Callable[[str], None]
type KeyAction = Literal["focus", "up", "down", "left", "right", "activate", "back"]
type TextColor = str | int | tuple[int, int, int]
```

`AutoScrollMode | None` is used where automatic scrolling may be disabled.

### `AnimationFrame`, `AnimatedText`, and `rainbow_color`

```text
AnimationFrame(elapsed: float, index: int)
AnimatedText(
    fallback: str,
    renderer: Callable[[AnimationFrame], str],
    *,
    fps: float = 12,
) -> AnimatedText
rainbow_color(elapsed: float, *, period: float = 2.1) -> tuple[int, int, int]
```

`AnimationFrame` is immutable. `elapsed` is the active number of seconds since
the menu runtime began, and `index` is the integer frame number for that
source's rate. `AnimatedText` is an immutable `str` subclass that displays its
renderer output in menus and retains `fallback` as its ordinary string value.
The callback runs on the UI thread once per source and index, must return a
string, and must not block. Its output passes through the existing safe ANSI
and Unicode layout pipeline. `rainbow_color()` interpolates between seven RGB
stops and returns to red after each `period`; elapsed must be finite and
non-negative, period finite and positive. See [Animations](#animations) for
lifecycle and scheduling behavior.

### `ScreenContent` and `ContentSize`

`ContentSize` is a frozen dataclass with integer `width` and `height` fields,
measured in terminal cells and content rows. `ScreenContent` is an immutable
configuration created through named factories:

```text
ScreenContent.static(text: str) -> ScreenContent
ScreenContent.lines(lines: list[str]) -> ScreenContent
ScreenContent.stream(iterator: Iterator[str]) -> ScreenContent
ScreenContent.dynamic(renderer: Callable[[], str | list[str]]) -> ScreenContent
ScreenContent.responsive(
    renderer: Callable[[ContentSize], str | list[str]],
    *,
    min_width: int | None = None,
    min_height: int | None = None,
    refresh_mode: ContentRefreshMode = "resize",
) -> ScreenContent
ScreenContent.animated(
    renderer: Callable[[ContentSize, AnimationFrame], str | list[str]],
    *,
    fps: float = 12,
    min_width: int | None = None,
    min_height: int | None = None,
) -> ScreenContent
```

Direct construction raises `TypeError`. `lines()` copies its list into an
immutable tuple; `stream()` consumes the supplied iterator, which must yield
strings. Dynamic/responsive callbacks run in content workers and must return a
string or list of strings; only one evaluation per panel is in flight. Responsive
minimums are positive integers or `None` and describe virtual rendering size,
rather than physical panel allocation. Its refresh mode is `"resize"` or
`"continuous"`. See [Screen content](#screen-content) for replacement and refresh
timing.

Animated callbacks use the same size rules as responsive callbacks. They run
on a separate panel worker at their requested maximum rate and receive the
menu's active-time frame. `ContentPanel.refresh()` forces either a responsive
or animated snapshot.

### `StatusBar`

An immutable current-state configuration created through named factories:

```text
StatusBar.static(text: str) -> StatusBar
StatusBar.dynamic(renderer: Callable[[], str]) -> StatusBar
StatusBar.responsive(renderer: Callable[[int], str]) -> StatusBar
StatusBar.animated(
    renderer: Callable[[int, AnimationFrame], str], *, fps: float = 12
) -> StatusBar
```

Direct construction raises `TypeError`. `static()` requires a string; dynamic
and responsive factories require a callable. Producers must return a string;
invalid results raise `TypeError` during rendering. See [Status bar](#status-bar)
for evaluation, refresh, normalization, and layout behavior.

### `MenuDisplay`

```text
MenuDisplay(
    menu_name: str,
    title: str,
    width: int | None = None,
    text: str | None = None,
    message: str | None = None,
    strict_width: bool = False,
)
```

A mutable dataclass holding visible menu state:

- `menu_name`: internal name used in contextual messages;
- `title`: heading in the menu box;
- `width`: positive minimum inner width, or `None` for content-based sizing;
- `text`: optional description above commands;
- `message`: optional footer;
- `strict_width`: fix the inner width when `width` is specified; otherwise use
  automatic sizing. Defaults to `False`.

Construction and later assignment validate `width` and `strict_width`. Invalid
widths raise `ValueError`; non-boolean `strict_width` values raise `TypeError`.
Menu growth is bounded by the terminal, with overflowing text wrapped inside the
borders. The requested width plus two border columns must still fit.

### `KeyBinding`

```text
KeyBinding(
    key: str,
    ctrl: bool = False,
    alt: bool = False,
    shift: bool = False,
    priority: bool = False,
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

- `bindings` → `Mapping[KeyAction, KeyBinding]`: read-only live action mapping.
- `focus`, `up`, `down`, `left`, `right`, `activate`, `back -> KeyBinding`:
  current bindings exposed as explicitly typed read-only properties.
- `set_binding(action: KeyAction, binding: KeyBinding) -> None`: atomically replace a
  system binding. Raises `KeyError` for an unknown action, `TypeError` for a
  non-binding, or `ValueError` for a collision.
- `action_for(binding: KeyBinding) -> KeyAction | None`: return the matching system
  action.
- `copy() -> KeyMap`: copy the bindings without an application owner or collision
  validator. Later mutations are independent.

An application takes exclusive ownership of its map. Reusing the same instance
in another application raises `ValueError`; supply `keymap.copy()` instead.

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

`ChoiceContext` is the corresponding frozen context for option hover and
selection. It adds `option: ChoiceOption` and `index: int`, and its `command`
is always the owning `MenuChoice`. `ChoiceCallback` is a callback accepting
this context. During an option preview, `option` and `index` can differ from the
committed selection. When `on_select` is dispatched by the menu, the selection
has already been committed.

### `MenuChoice` and `ChoiceOption`

```text
ChoiceOption(
    label: str,
    *,
    row: int = 0,
    on_hover: ChoiceCallback | None = None,
    hover_message: str | None = None,
)
```

`ChoiceOption` is a frozen dataclass. `label` is display text, `row` is a logical
row within the expanded choice, and `hover_message` is a registered message key.
The menu validates option rows and message keys when the choice is added.

Obtain a `MenuChoice` from `add_choice()`. It extends `MenuCommand` with read-only
`options`, `rows`, `vertical`, `selected_index`, `selected_option`, `selected_label`, and
`on_select`. Before confirmation, `selected_index`, `selected_option`, and
`selected_label` are `None`. After confirmation, `selected_option` is a
`ChoiceOption` and `selected_label` is its text.
In vertical mode, `rows` equals the number of options.
For an animated option, `selected_label` returns its fallback without invoking
the animation callback.
`on_select` receives `ChoiceContext`. Its inherited `callback` receives
`CommandContext` and adapts it to `on_select` using the currently committed
option and the triggering binding. It does not change the selection or open the
chooser. Calling it before any option is selected raises `RuntimeError`. Use
`set_choice_callback()` to replace `on_select`.

### `MenuCommand`

```text
MenuCommand(
    menu: TerminalMenu,
    label: str,
    callback: CommandCallback,
    on_hover: CommandCallback | None = None,
)
```

Applications normally obtain this stable handle from `add_command()` or
`add_submenu()` instead of constructing it directly. Its properties are read-only:

- `label -> str`;
- `callback -> CommandCallback`;
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
    callback: CommandCallback,
)
```

Applications normally obtain this handle from `add_global_command()`. Its
read-only properties are `binding`, `label`, and `callback`. Use the owning
application's `set_global_command_*` methods for application-wide mutation, or a
menu's global-command methods for local behavior and enablement.

### `MessageKey`

`MessageKey` is a `StrEnum` with `NO_CONTENT_SOURCE` and `UNKNOWN_COMMAND`.
The values and purpose of each member are listed in [Messages](#messages).
Enum members can be passed
where a message key string is accepted.

The safe-shutdown interface is rendered as a temporary menu independent of
registered messages.

### `ContentPanel`

Applications obtain `ContentPanel` handles from
`TerminalMenu.add_content_panel()` or `menu.content_panels` rather than
constructing them directly. All panels, including automatically inherited
content, support the same methods.

Read-only properties:

- `content -> ScreenContent`: current mounted production configuration;
- `description -> str`: current visible and shutdown label;
- `position -> int`: current zero-based flat registration position;
- `auto_scroll -> AutoScrollMode | None`: independent iterator-follow policy;
- `height_weight -> float`: positive relative share of total panel height, including borders;
- `width_weight -> float`: positive relative share of row width, including borders;
- `min_height -> int`: minimum visible content rows, default `1`;
- `max_height -> int | None`: maximum expanded visible content rows, default `None`;
- `collapsed -> bool`: whether the panel uses its fixed collapsed height, default `False`;
- `collapsed_height -> int`: collapsed visible content rows, default `1`.
- `padding_top`, `padding_bottom`, `padding_left`, `padding_right -> int`:
  nonnegative inner padding, default `0`;
- `key_commands -> tuple[PanelKeyCommand, ...]`: registered shortcuts.

Explicit mutation methods:

```text
set_content(content: ScreenContent) -> None
refresh() -> None
set_description(description: str) -> None
set_auto_scroll(mode: AutoScrollMode | None) -> None
collapse() -> None
expand() -> None
toggle_collapse() -> None
set_collapsed_height(height: int) -> None
update_padding(*, top: int | None = None, bottom: int | None = None,
               left: int | None = None, right: int | None = None) -> None
add_key_command(binding: KeyBinding, label: str,
                callback: PanelCommandCallback) -> PanelKeyCommand
remove_key_command(command: PanelKeyCommand) -> None
set_layout(
    *,
    height_weight: float = 1,
    width_weight: float = 1,
    min_height: int = 1,
    max_height: int | None = None,
) -> None
update_layout(
    *,
    height_weight: float = <unchanged>,
    width_weight: float = <unchanged>,
    min_height: int = <unchanged>,
    max_height: int | None = <unchanged>,
) -> None
move_left() -> None
move_right() -> None
move_up() -> None
move_down() -> None
swap_up() -> None
swap_down() -> None
remove() -> None
```

The handle keeps its identity across content, label, mode, layout and placement
changes.
`set_layout()` replaces the expanded sizing configuration; omitted arguments
reset to their defaults. `update_layout()` changes only supplied options and
retains omitted ones; `max_height=None` removes the upper bound. Both validate
the resulting layout before mutation and leave `collapsed` and
`collapsed_height` unchanged. `<unchanged>` denotes the private omission
sentinel, not a value callers need to import.
`collapse()` and `expand()` are idempotent on singleton rows;
`toggle_collapse()` switches the state. On multi-panel rows, use the row's
methods instead; panel collapse methods raise `ValueError`.
`set_collapsed_height()` sets a positive integer content height independently of
the expanded bounds. See [Collapsible content panels](#collapsible-content-panels)
for allocation and runtime behavior. These methods can be called before or
during application execution.
`refresh()` forces a responsive or animated evaluation and raises `RuntimeError`
for other content variants. Calling a mutation method after removal raises
`ValueError`.

### `ContentRow`

Rows are obtained from `menu.content_layout`. Their read-only `panels` tuple
lists members left to right. `collapsed` and `collapsed_height` describe their
shared vertical state. Use `collapse()`, `expand()`, `toggle_collapse()`, and
`set_collapsed_height(height)` for row-level vertical changes. A row handle
replaced by a new layout or directional movement cannot be mutated; obtain the
current handle from `menu.content_layout`.

### `TerminalApp`

```text
TerminalApp(
    name: str,
    global_content: ScreenContent | None = None,
    *,
    keymap: KeyMap | None = None,
    global_content_factory: Callable[[], ScreenContent] | None = None,
)
```

The constructor stores the display name, optional content inherited by every
menu at construction as an ordinary panel, and an optional custom system key
map. Each menu captures the global configuration when it is created.
Alternatively, `global_content_factory` returns independent content for each
menu and is called once at menu construction, on the constructing thread.
Supplying both content options raises `ValueError`; an invalid factory or its
non-`ScreenContent` result raises `TypeError`. Stream factories must create a
fresh iterator per panel. The map has one application owner; reuse its
configuration through `KeyMap.copy()`.

Read-only properties:

- `name -> str`: application name displayed by every menu;
- `global_content -> ScreenContent | None`: content inherited at menu
  construction;
- `global_content_factory -> Callable[[], ScreenContent] | None`: optional
  per-menu content factory;
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
    callback: CommandCallback,
) -> GlobalCommand
```

Register an invisible application command. Raises `TypeError` for a non-binding
or non-callable callback and `ValueError` when the binding collides with a system
or global command.

```text
set_global_command_binding(
    command: GlobalCommand,
    binding: KeyBinding,
) -> None
set_global_command_label(command: GlobalCommand, label: str) -> None
set_global_command_callback(
    command: GlobalCommand,
    callback: CommandCallback,
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
push_menu(menu: TerminalMenu) -> None
pop_menu() -> None
replace_menu(menu: TerminalMenu) -> None
reset_to(menu: TerminalMenu) -> None
run(entry_menu: TerminalMenu | None = None) -> None
```

`push_menu()` adds an application-owned menu to the top of the stack and rejects
a menu already present there. `pop_menu()` removes the top menu when the stack
has multiple entries; at the bottom it requests application shutdown.
`replace_menu()` swaps only the top entry, or creates the first entry when the
stack is empty. `reset_to()` truncates the stack through an existing menu, or
replaces the whole stack when the menu is absent. Foreign navigation targets
raise `ValueError`; invalid simultaneous duplicates are rejected.

`run()` starts with `entry_menu` when supplied, otherwise with the registered
main menu. It raises `RuntimeError` if neither is available or if called outside
Python's main thread, and raises `ValueError` for a foreign entry menu. The call
blocks until the application exits, joins workers, restores terminal state, and
then propagates any pending error. Each run starts with a fresh navigation
stack. The bottom entry displays Quit and deeper entries display Back regardless
of which menu was registered as the main menu, except that a label assigned with
`set_exit_label()` always takes priority.

Push, replace, and reset clear the target's transient selection, focus, option
preview and input buffer, then run its initial `on_hover`. They retain the input
prompt/callback and any initialized workers. Pop reveals the previous menu's
retained state. When cleanup also fails, `run()` retains the original failure
and cleanup errors in an exception group; all cleanup actions are attempted.

### `TerminalMenu`

```text
TerminalMenu(
    app: TerminalApp,
    display_state: MenuDisplay,
    *,
    content_spacing: bool = True,
    presentation: MenuPresentation | None = None,
)
```

Create a menu owned by `app`. Global content or the result of
`app.global_content_factory` automatically creates an ordinary panel, available
through `content_panels`. Otherwise the menu starts without panels. Add explicit
panels with
`add_content_panel()`; they are additional to any inherited panel.
`content_spacing` must be a boolean and is keyword-only.
`presentation` is keyword-only: `None` inherits the parent on navigation or
uses inline at a root. Invalid modes raise `ValueError`; an explicit mode
overrides inheritance. The effective `presentation` property is read-only.

Properties:

- `app -> TerminalApp`: read-only owner;
- `display_state -> MenuDisplay`: read-only reference to mutable display
  state;
- `commands -> tuple[MenuCommand, ...]`: immutable ordered handle view;
- `is_main -> bool`: whether this is the registered root;
- `presentation -> MenuPresentation`: read-only effective mode;
- `menu_visible -> bool`: read-only requested menu-box visibility;
- `content_panels -> tuple[ContentPanel, ...]`: immutable flat registered-panel
  view;
- `content_layout -> tuple[ContentRow, ...]`: immutable row-handle view;
- `focused_panel -> ContentPanel | None`: current keyboard target outside modal
  states;
- `status_bar -> StatusBar | None`: read-only optional status configuration.

#### Menu-box visibility methods

```text
show_menu() -> None
hide_menu() -> None
toggle_menu() -> None
```

Reveal/focus, hide, or toggle only the menu box, preserving the rest of the
frame and its runtime. See [Overlay menus](#overlay-menus) for focus, suspension
and visibility semantics.

#### Status bar methods

```text
set_status_bar(content: str | StatusBar) -> None
clear_status_bar() -> None
refresh_status_bar() -> None
```

Install or replace the status configuration with `set_status_bar()`; a string
is shorthand for `StatusBar.static()`. Other types raise `TypeError` without
changing the current configuration. `clear_status_bar()` is idempotent and
returns the reserved row to the layout. `refresh_status_bar()` requests a new
responsive result on the next visible frame; it raises `RuntimeError` if there
is no status or its kind is static or dynamic. These methods preserve panels,
focus, scroll state, and messages.

#### Command methods

```text
add_command(
    label: str,
    callback: CommandCallback,
    *,
    on_hover: CommandCallback | None = None,
    position: int | None = None,
) -> MenuCommand
add_choice(
    label: str,
    options: list[ChoiceOption] | tuple[ChoiceOption, ...],
    on_select: ChoiceCallback,
    *,
    rows: int = 1,
    vertical: bool = False,
    selected_index: int | None = None,
    on_hover: CommandCallback | None = None,
    position: int | None = None,
) -> MenuChoice
set_choice_index(choice: MenuChoice, selected_index: int) -> None
set_choice_callback(choice: MenuChoice, callback: ChoiceCallback) -> None
add_submenu(
    submenu: TerminalMenu,
    label: str,
    *,
    on_hover: CommandCallback | None = None,
    position: int | None = None,
) -> MenuCommand
remove_command(command: MenuCommand) -> None
```

Add a command or application-owned submenu and return its stable handle.
Invalid positions raise `TypeError` or `ValueError`; foreign submenus raise
`ValueError`. `add_submenu()` installs a normal command that pushes `submenu` onto
the application's navigation stack without starting another application loop.

`add_choice()` validates a nonempty set of `ChoiceOption` objects, positive
`rows`, each option's row, and any initial `selected_index` before registration.
The default `None` leaves all options unchecked; pass `selected_index=0` to
check the first option initially.
With `vertical=True`, it places each option on its own logical row and rejects
`rows>1` or a nonzero option `row`. `vertical` must be a bool.
`set_choice_index()` changes the committed option without invoking `on_select`.
It requires a valid integer index and cannot clear a confirmed selection.
`set_choice_callback()` replaces that callback without invoking it or changing
the selection. Invalid indices/layouts and foreign or removed handles raise
`ValueError`; non-callable callbacks raise `TypeError`.

`remove_command()` atomically removes an owned command. The deleted handle is
immediately invalid: subsequent menu mutations, another deletion, and access to
its position raise `ValueError`. Handles from another menu and objects that are
not live command handles are also rejected. If the deleted command was
selected, selection moves to the next enabled command, then the previous enabled
command, and finally the automatic Back/Quit row. Deleting any other command
preserves the selected handle. A command callback may safely delete its own
handle; the same selection rules apply before activation returns.

```text
set_command_label(command: MenuCommand, label: str) -> None
set_command_callback(
    command: MenuCommand,
    callback: CommandCallback,
) -> None
move_command(command: MenuCommand, position: int) -> None
disable_command(command: MenuCommand) -> None
enable_command(command: MenuCommand) -> None
set_exit_label(label: str) -> None
```

Mutate owned menu commands or the automatic Back/Quit label. `move_command()`
requires an existing zero-based position. Foreign handles raise `ValueError`.
`set_command_callback()` rejects a `MenuChoice`; its selection callback uses
`ChoiceContext` and must be replaced through `set_choice_callback()` instead.

#### Global-command methods

```text
set_global_command_callback(
    command: GlobalCommand,
    callback: CommandCallback,
) -> None
clear_global_command_callback(command: GlobalCommand) -> None
disable_global_command(command: GlobalCommand) -> None
enable_global_command(command: GlobalCommand) -> None
```

Override, restore, disable, or enable an application global command in this menu
only. Foreign handles raise `ValueError`.

#### Content and task methods

```text
set_content_layout(layout: Sequence[Sequence[ContentPanel]]) -> None
add_content_panel(
    content: ScreenContent,
    *,
    description: str = "Content in progress",
    auto_scroll: AutoScrollMode | None = None,
    position: int | None = None,
    height_weight: float = 1,
    width_weight: float = 1,
    min_height: int = 1,
    max_height: int | None = None,
    collapsed_height: int = 1,
    padding_top: int = 0,
    padding_bottom: int = 0,
    padding_left: int = 0,
    padding_right: int = 0,
) -> ContentPanel
```

Add an independently rendered panel and return its stable handle. `position`
is a zero-based index in `content_panels`; invalid positions or auto-scroll
modes raise `TypeError` or `ValueError`. Sizing options are validated before
insertion; see
[Content panel sizing](#content-panel-sizing) for allocation and bounds.
`collapsed_height` sets the fixed content row count used after `collapse()`;
panels start expanded. See [Collapsible content panels](#collapsible-content-panels).
`set_content_layout()` atomically validates and installs complete nested rows;
see [Content layouts](#content-layouts).

Change a panel through its `ContentPanel` handle. See
[Replacing active content](#replacing-active-content) for source replacement
semantics.

```text
start_output_task[T](
    action: Callable[[], T],
    *,
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None],
    description: str = "Task in progress",
) -> None
```

Start one captured application task and return immediately. Raises `RuntimeError`
without an initialized running menu runtime or when another task is running;
the owning menu may be hidden behind another menu. Completion callbacks run on
the UI thread after processing the outcome and requesting panel removal, which
may still be waiting for buffered output to drain.

#### Input and alert methods

```text
enter_input_mode(
    prompt: str,
    callback: InputCallback,
    *,
    hidden: bool = False,
) -> None
leave_input_mode() -> None
```

Start a fresh input buffer or clear all input state. Submission keeps the buffer
and session until the callback calls `leave_input_mode()` or replaces it. The
configured Back action cancels without submission. Visible input consumes global
bindings; an alert or a hidden menu box suspends it without clearing its buffer.

```text
show_alert(
    text: str,
    *,
    on_confirm: CommandCallback | None = None,
    prompt: str | None = None,
) -> None
clear_alert() -> None
```

Show a blocking/confirmable alert or clear it and reveal suspended input state.

#### Message methods

```text
show_message(key: str) -> bool
toggle_message(key: str) -> bool
active_message_key: str | None  # read-only property
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
stop() -> None
```

`stop()` performs the current menu's Back/Quit action. At stack depth greater
than one it pops the menu. At the bottom it requests shutdown and presents safe
shutdown choices when background work is active; otherwise it stops
immediately.

### `style`

```text
style(
    text: str,
    *,
    bold: bool = False,
    dim: bool = False,
    italic: bool = False,
    underline: bool = False,
    strikethrough: bool = False,
    reverse: bool = False,
    foreground: TextColor | None = None,
    background: TextColor | None = None,
) -> str
```

Return sanitized text wrapped in one ANSI SGR opening sequence and targeted
resets for the selected categories. Named colors, ANSI indexes from 0 to 255,
RGB tuples with components from 0 to 255, and strict `#RRGGBB` strings are
accepted. Invalid types raise `TypeError`; unknown names, malformed hexadecimal
strings, and out-of-range numbers raise `ValueError`.

### `display_width`

```python
from tuiloom import display_width, style

display_width(style("●", foreground="green"))  # 1
display_width("e\u0301")  # 1: combining accent
display_width("界")  # 2: wide character
```

`display_width(text: str) -> int` measures terminal columns rather than Python
string length. It uses the same text sanitization and width calculation as
Tuiloom's renderer: supported ANSI styles and hyperlinks do not add width,
Unicode graphemes retain their terminal width, and tabs use eight-column stops.
Use it to measure a rendered line, for example when validating a canvas cell.

### `hyperlink`

```text
hyperlink(text: str, url: str) -> str
```

Return sanitized visible text wrapped in a complete OSC 8 open/close pair.
Unsafe or non-HTTP(S) URLs raise `ValueError`.

## Runtime constraints

- `TerminalApp.run()` is blocking, main-thread-only, and requires an interactive
  terminal.
- Popped and replaced menu runtimes continue servicing their content workers
  until the application closes them when `TerminalApp.run()` exits.
- Only one `start_output_task()` task can run per application.
- Python stdout/stderr capture does not include subprocess or direct
  file-descriptor output.
- Content producers run in workers; commands and status producers run on the UI
  thread. Synchronize state shared between them and keep UI callbacks fast.
- Stream history has no default size limit. Long-running logs retain their
  completed lines until their panel is replaced or removed; plan the source's
  volume and lifetime accordingly.
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
