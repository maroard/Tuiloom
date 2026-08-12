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
