# Command Context Design

## Goal

Every public command callback receives a fresh `CommandContext` describing the
specific execution. Tuiloom constructs that context during dispatch; users do
not create, retrieve, or retain it through framework APIs.

This change deliberately breaks compatibility with zero-argument public
callbacks.

## Public API

A focused `tuiloom.command` module owns the command API:

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
    app: TerminalApp
    menu: TerminalMenu
    command_key: str


type CommandBehavior = Callable[[CommandContext], None]
type Command = tuple[CommandBehavior, str]
type CommandDict = dict[str, Command]
```

`CommandContext`, `CommandBehavior`, `Command`, and `CommandDict` are exported
from the package root. `ScreenContext` imports `CommandDict` from this module
instead of owning command-related aliases.

`TerminalMenu.add_command()` and `TerminalApp.add_global_command()` accept only
`CommandBehavior`. There is no union, signature inspection, or compatibility
fallback for old zero-argument callbacks.

## User-facing Usage

A callback uses the execution context directly to reach its originating menu or
active application:

```python
def generate(context: CommandContext) -> None:
    context.menu.set_content_source(...)


menu.add_command("Generate", generate)
```

External business dependencies remain injectable with an ordinary closure:

```python
def make_generate_command(
    decoder: ConstrainedDecoder,
    prompt_builder: PromptBuilder,
) -> CommandBehavior:
    def generate(context: CommandContext) -> None:
        instructions = prompt_builder.get_prompt(...)
        context.menu.set_content_source(decoder.stream(instructions))

    return generate
```

Tuiloom does not impose a command class or dependency container on users.

## Dispatch Flow

When Enter is pressed, `TerminalMenu` consumes the entire input buffer as one
command key and clears the buffer. It then resolves exactly one command:

1. Ask the application to resolve an exact global key for the whole input.
2. If no global command matches, look up the exact local key.
3. If neither matches, preserve the existing unknown-command message behavior.

Global lookup normalizes the whole input with `upper()` and performs one
dictionary lookup. It never iterates over input characters. Thus `X` invokes
global `X`, while `XY` invokes only a command registered as `XY` and otherwise
invokes nothing. With the current public registration validation, global keys
remain one alphabetic character, but exact lookup deliberately supports the
registry's uniform semantics and prevents character-wise dispatch.

If global and local keys collide, the global command retains priority.

## Context Construction

Context creation occurs only after a command is resolved and immediately before
its callback is invoked.

- A local command receives the active app, the current menu, and its exact local
  dictionary key.
- A global command receives the active app, the menu that submitted the input,
  and the normalized global dictionary key.

Each invocation creates a distinct frozen, slotted context instance. Tuiloom
does not store a current context on `TerminalApp` or `TerminalMenu` and does not
expose a context getter.

Callback exceptions propagate unchanged through dispatch.

## Bound Internal Actions

Object-bound internal actions retain their natural zero-argument signatures.
The command registry remains uniformly typed by adapting them privately:

```python
def _without_context(action: Callable[[], None]) -> CommandBehavior:
    def wrapped(context: CommandContext) -> None:
        action()

    return wrapped
```

The unused parameter is intentionally named `context` to make the adapter's
contract explicit. The adapter is used for the built-in `0` command and for
sub-menu `run()` callbacks. `TerminalMenu.stop()` and `TerminalMenu.run()` remain
zero-argument bound methods.

## Tests

The new test suite exercises behavior through real `TerminalApp` and
`TerminalMenu` instances while directly invoking the private dispatch boundary
where running a terminal loop is unnecessary. It covers:

- local and global context contents and identity per execution;
- exact global lookup, normalization, non-splitting of `XY` and `XX`, and
  global-over-local priority;
- multi-character local keys and existing unknown-command messages;
- the built-in `0` action, sub-menu opening, and the private adapter;
- unchanged zero-argument signatures for internal bound methods;
- root-package imports for all public command types;
- callback exception propagation;
- migration of all test callbacks to the context-taking public contract.

Tests are added before production changes and observed failing for the missing
behavior. After implementation, the full pytest suite, strict mypy check, Ruff
check, and direct public-import check must pass.

## Documentation Scope

The root README is currently empty, so it will receive a compact command API
example showing both direct context usage and dependency capture with a closure.
No unrelated package restructuring or terminal behavior changes are included.
