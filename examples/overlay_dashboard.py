"""Run with: uv run python examples/overlay_dashboard.py."""

from __future__ import annotations

from dataclasses import dataclass
from math import sin
from time import monotonic

from tuiloom import (
    ChoiceContext,
    ChoiceOption,
    CommandContext,
    ContentSize,
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
)


@dataclass
class Simulation:
    started: float | None = None
    seconds_per_turn: float = 0.5

    def turn(self) -> int:
        started = self.started
        return (
            0
            if started is None
            else min(15, int((monotonic() - started) / self.seconds_per_turn))
        )

    def graph(self, size: ContentSize) -> list[str]:
        turn = self.turn()
        height = max(1, size.height - 1)
        grid = [[" "] * size.width for _ in range(height)]
        for column in range(size.width):
            wave = sin(column / 5 + turn / 3)
            row = round((1 - wave) * (height - 1) / 2)
            grid[row][column] = "●"
        return [f"Simulation curve — turn {turn}", *("".join(row) for row in grid)]

    def logs(self) -> str:
        turn = self.turn()
        if self.started is None:
            return "Open the menu with M, then choose Run simulation."
        return "\n".join(
            f"Turn {index}: {min(25, index * 2)}/25 delivered"
            for index in range(turn + 1)
        )

    def status(self) -> str:
        turn = self.turn()
        phase = "READY" if self.started is None else "DONE" if turn == 15 else "RUNNING"
        return (
            f"{phase} │ Turn {turn} │ {min(25, turn * 2)}/25 delivered"
            " │ [M] Menu │ [Tab] Focus │ [Esc] Back/Quit"
        )


def main() -> None:
    simulation = Simulation()
    app = TerminalApp(
        "Overlay dashboard",
        ScreenContent.responsive(simulation.graph, refresh_mode="continuous"),
    )
    menu = TerminalMenu(
        app, MenuDisplay("main", "Main Menu", width=24), presentation="overlay"
    )
    settings = TerminalMenu(app, MenuDisplay("settings", "Settings", width=24))
    # Settings inherits overlay when pushed. Each menu retains its own panels.
    for screen in (menu, settings):
        screen.content_panels[0].set_description("Graph")
        screen.content_panels[0].update_layout(weight=3)
        screen.add_content_panel(
            ScreenContent.dynamic(simulation.logs),
            description="Simulation",
            weight=1,
            max_height=6,
        )
        screen.set_status_bar(StatusBar.dynamic(simulation.status))

    def run(context: CommandContext) -> None:
        simulation.started = monotonic()
        context.menu.hide_menu()

    def set_speed(context: ChoiceContext) -> None:
        simulation.seconds_per_turn = (0.5, 1.0)[context.index]

    settings.add_choice(
        "Speed", [ChoiceOption("Fast"), ChoiceOption("Slow")], set_speed
    )
    menu.add_command("Run simulation", run)
    menu.add_submenu(settings, "Settings")
    menu.add_command(
        "Credits",
        lambda context: context.menu.show_alert(
            "Tuiloom overlay demo", on_confirm=lambda context: None
        ),
    )
    menu.add_command("Hide menu", lambda context: context.menu.hide_menu())
    # This shortcut belongs to this demo; Tuiloom adds no menu-toggle binding.
    app.add_global_command(
        KeyBinding("m"), "Toggle menu", lambda context: context.menu.toggle_menu()
    )
    app.set_main_menu(menu)
    menu.hide_menu()
    app.run()


if __name__ == "__main__":
    main()
