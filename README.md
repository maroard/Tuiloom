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

## ANSI styles and Unicode

Every visual Tuiloom string supports SGR colors and styles, including 16-color,
256-color, and true-color sequences. Layout and cursor positioning account for
combining characters, wide CJK text, and emoji grapheme clusters.

Tuiloom intentionally strips terminal control sequences that can move the
cursor, erase the screen, scroll, or change terminal state. The renderer keeps
exclusive control of terminal geometry while preserving user-provided style.

## Streaming performance

Synchronous iterators keep the same public API shown above, but Tuiloom consumes
them outside the UI thread. Generated chunks cross a bounded buffer and are
grouped into visual updates rendered at up to 60 frames per second. Keyboard
input, scrolling, and cursor updates therefore remain responsive while a source
waits for its next chunk.

Generators should release the Python GIL during long native work when possible.
A cancelled generator must eventually return from a blocked `next()` call before
Tuiloom can close that generator's own resources, although stale output is
ignored immediately.
