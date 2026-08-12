from tuiloom.command import Command
from tuiloom.screen_context.screen_context import ScreenContext


class MenuRenderer:
    """Build a complete terminal menu box from screen context."""

    def __init__(self, screen_context: ScreenContext) -> None:
        """Capture the screen state required to render the menu."""
        self.update_screen_context(screen_context)

    def update_screen_context(self, screen_context: ScreenContext) -> None:
        """Replace the menu state with the current screen context."""
        self.app_name = screen_context.app_name
        self.title = screen_context.title
        self.commands = screen_context.commands
        self.text = screen_context.text
        self.two_columns = screen_context.two_columns
        self.message = screen_context.message
        self.alert = screen_context.alert
        self.prompt = screen_context.prompt

        requested_width = screen_context.width
        self.width: int = (
            requested_width if requested_width is not None else self._calculate_width()
        )

    def _calculate_width(self) -> int:
        """Calculate the smallest width that fits every menu element."""
        width_requirements = [len(self.app_name), len(self.title)]

        for content in (self.text, self.message, self.alert):
            if content:
                width_requirements.extend(
                    len(line) + 2 for line in content.splitlines()
                )

        items = self._get_menu_items()

        if self.two_columns:
            middle = (len(items) + 1) // 2
            left_items = items[:middle]
            right_items = items[middle:]

            left_requirement = max(
                (len(f" {key}. {command[1]}") for key, command in left_items),
                default=0,
            )
            right_requirement = max(
                (len(f" {key}. {command[1]}") for key, command in right_items),
                default=0,
            )

            width_requirements.append(
                max(
                    2 * left_requirement,
                    2 * right_requirement - 1,
                )
            )
        else:
            width_requirements.extend(
                len(f" {key}. {command[1]}") for key, command in items
            )

        zero_command = self.commands.get("0")
        if zero_command is not None:
            width_requirements.append(len(f" 0. {zero_command[1]}"))

        return max(width_requirements)

    def render(self) -> str:
        """Compose the complete menu box, footer, and prompt."""
        if self.alert:
            body_display = self._get_alert_display()
            footer_display = self._get_footer_display()
            prompt_display = self._get_alert_prompt_display()
        else:
            body_display = self._get_body_display()
            footer_display = self._get_footer_display()
            prompt_display = self._get_prompt_display()

        return (
            f"╭{'─' * self.width}╮\n"
            f"│{'':{self.width}}│\n"
            f"│{f'{self.app_name}':^{self.width}}│\n"
            f"│{'':{self.width}}│\n"
            f"├{'─' * self.width}┤\n"
            f"│{self.title:^{self.width}}│\n"
            f"├{'─' * self.width}┤\n"
            f"{body_display}"
            f"{footer_display}"
            "\n"
            f"{prompt_display}"
        )

    def _get_alert_display(self) -> str:
        """Render alert text as wrapped menu rows."""
        if not self.alert:
            return ""

        alert_display = ""

        for line in self._wrap_lines(self.alert):
            alert_display += f"│{' ' + line:<{self.width}}│\n"

        return alert_display

    def _get_body_display(self) -> str:
        """Build the normal menu body from text and commands."""
        body_display = ""

        if self.text:
            body_display += self._get_text_display()

        body_display += self._get_commands_display()

        return body_display

    def _get_text_display(self) -> str:
        """Render optional descriptive text above the command list."""
        if not self.text:
            return ""

        text_label = ""

        for line in self._wrap_lines(self.text):
            text_label += f"│{' ' + line:<{self.width}}│\n"

        text_label += f"│{'':{self.width}}│\n"

        return text_label

    def _get_commands_display(self) -> str:
        """Render commands followed by the reserved zero command."""
        items = self._get_menu_items()

        if self.two_columns:
            commands_label = self._get_two_columns_commands(items)
        else:
            commands_label = self._get_single_column_commands(items)

        commands_label += (
            f"│{'':{self.width}}│\n│{' 0. ' + self.commands['0'][1]:<{self.width}}│\n"
        )

        return commands_label

    def _get_menu_items(self) -> list[tuple[str, Command]]:
        """Return command entries excluding the reserved zero command."""
        return [(key, value) for key, value in self.commands.items() if key != "0"]

    def _get_two_columns_commands(
        self,
        items: list[tuple[str, Command]],
    ) -> str:
        """Format command entries in a balanced two-column layout."""
        left_width = self.width // 2
        right_width = self.width - left_width

        middle = (len(items) + 1) // 2
        left_items = items[:middle]
        right_items = items[middle:]

        commands_label = ""

        for i in range(middle):
            left_key, left_value = left_items[i]
            left_text = f" {left_key}. {left_value[1]}"

            right_text = ""
            if i < len(right_items):
                right_key, right_value = right_items[i]
                right_text = f" {right_key}. {right_value[1]}"

            commands_label += (
                f"│{left_text:<{left_width}}{right_text:<{right_width}}│\n"
            )

        return commands_label

    def _get_single_column_commands(
        self,
        items: list[tuple[str, Command]],
    ) -> str:
        """Format command entries in a single-column layout."""
        commands_label = ""

        for key, value in items:
            text = f" {key}. {value[1]}"
            commands_label += f"│{text:<{self.width}}│\n"

        return commands_label

    def _get_footer_display(self) -> str:
        """Build the menu footer and optional message section."""
        footer_display = ""

        if self.message:
            footer_display += f"├{'─' * self.width}┤\n"
            footer_display += self._get_message_display()

        footer_display += f"╰{'─' * self.width}╯\n"

        return footer_display

    def _get_message_display(self) -> str:
        """Render message text as wrapped footer rows."""
        if not self.message:
            return ""

        message_display = ""

        for line in self._wrap_lines(self.message):
            message_display += f"│{' ' + line:<{self.width}}│\n"

        return message_display

    def _get_alert_prompt_display(self) -> str:
        """Return the prompt displayed while an alert is active."""
        if self.prompt is not None:
            return self.prompt

        return "Press Enter to continue: "

    def _get_prompt_display(self) -> str:
        """Return the custom or default normal menu prompt."""
        if self.prompt is not None:
            return self.prompt

        return f"Choice? (0-{len(self.commands) - 1}): "

    def _wrap_lines(self, text: str) -> list[str]:
        """Wrap multiline text to the menu's available inner width."""
        wrapped_lines: list[str] = []

        max_width = self.width - 2

        for raw_line in text.splitlines():
            words = raw_line.split()
            current_line = ""

            if not words:
                wrapped_lines.append("")
                continue

            for word in words:
                if not current_line:
                    current_line = word
                elif len(current_line) + 1 + len(word) <= max_width:
                    current_line += " " + word
                else:
                    wrapped_lines.append(current_line)
                    current_line = word

            wrapped_lines.append(current_line)

        return wrapped_lines
